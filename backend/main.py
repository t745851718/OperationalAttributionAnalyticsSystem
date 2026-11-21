import asyncio
import fcntl
import logging
import subprocess
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated
from uuid import uuid4

import httpx
import jwt
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend import reports
from backend.analysis import AnalysisError, demo_spec, drilldown, get_decomposition, simulation, training_data, window_rows
from backend.auth import issue, matches, signing_key
from backend.catalog import DEMO_END, DEMO_START, DIMENSIONS, DOMAIN_LABELS
from backend.config import RUNTIME
from backend.jobs import TERMINAL, Jobs, serialize_session
from backend.metrics import Evaluator
from backend.model import MessagesModel, ModelError, object_schema
from backend.schemas import (
    AnalysisSpec, CreateSession, Dimension, Domain, EvidenceReviewInput, Login, Message, ReportInput, ScenarioInput,
    SnapshotInput,
)
from backend.store import Store, dump, load, now
from backend.warehouse import Warehouse

logger = logging.getLogger(__name__)


def create_app(store=None, model=None, verifier=None):
    store = store or Store()
    model = model or MessagesModel()

    @asynccontextmanager
    async def lifespan(app):
        store.path.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME.mkdir(parents=True, exist_ok=True)
        with store.path.with_suffix(".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("此 SQLite 数据库已由另一后端进程使用") from None
            store.setup()
            app.state.signing_key = signing_key()
            app.state.jobs = Jobs(store, model, **({"verifier": verifier} if verifier else {}))
            app.state.jobs.recover()
            from backend.management import digest_loop
            digest_task = asyncio.create_task(digest_loop(store))
            try:
                yield
            finally:
                digest_task.cancel()
                await asyncio.gather(digest_task, return_exceptions=True)
                await app.state.jobs.close()

    app = FastAPI(title="经营归因分析系统 API", version="0.1.0", lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    @app.exception_handler(httpx.HTTPError)
    def warehouse_error(_, exc):
        logger.warning("Warehouse request failed: %s", type(exc).__name__)
        return JSONResponse({"detail": "数仓请求失败，请检查连接及初始化状态"}, status_code=503)

    @app.exception_handler(AnalysisError)
    def analysis_error(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(ModelError)
    def model_error(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.middleware("http")
    async def audit_requests(request, call_next):
        response = await call_next(request)
        if username := getattr(request.state, "username", None):
            route = request.scope.get("route")
            await asyncio.to_thread(
                store.audit, username, "api.request", getattr(route, "path", "unknown"),
                {"method": request.method, "status": response.status_code},
            )
        return response

    def principal(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        def denied():
            return HTTPException(401, "请登录或刷新登录状态", headers={"WWW-Authenticate": "Bearer"})
        if not credentials:
            raise denied()
        try:
            claims = jwt.decode(credentials.credentials, app.state.signing_key,
                                algorithms=["HS256"], issuer="attribution",
                                options={"require": ["exp", "sub", "iat"]})
        except jwt.InvalidTokenError:
            raise denied() from None
        row = store.one("SELECT username,role,domains FROM user_account WHERE username=?", (claims["sub"],))
        if not row:
            raise denied()
        request.state.username = row["username"]
        return {**dict(row), "domains": load(row["domains"])}

    def authorize(actor, domain=None, roles=None):
        if (domain and domain not in actor["domains"]) or (roles and actor["role"] not in roles):
            raise HTTPException(403, "无权访问此指标域或执行此操作")

    def session_for(session_id, actor, write=False):
        row = store.one("SELECT * FROM analysis_session WHERE id=?", (session_id,))
        if not row:
            raise HTTPException(404, "分析会话不存在")
        authorize(actor, row["domain_id"], {"analyst", "admin"} if write else None)
        if row["owner"] != actor["username"] and actor["role"] != "admin":
            raise HTTPException(403, "此会话仅对创建者和管理员开放")
        return row

    def report_for(report_id, actor, write=False):
        row = store.one("""
            SELECT report.*, analysis_session.domain_id, analysis_session.owner
            FROM report JOIN analysis_session ON analysis_session.id=report.session_id WHERE report.id=?
        """, (report_id,))
        if not row:
            raise HTTPException(404, "报告不存在")
        authorize(actor, row["domain_id"], {"analyst", "admin"} if write else None)
        if row["owner"] != actor["username"] and actor["role"] != "admin" and (write or row["status"] != "published"):
            raise HTTPException(403, "报告尚未发布或无编辑权限")
        return row

    def job_for(job_id, actor, write=False):
        row = store.one("SELECT * FROM job WHERE id=?", (job_id,))
        if not row:
            raise HTTPException(404, "分析任务不存在")
        session_for(row["session_id"], actor, write)
        return row

    def warehouse_context():
        version = store.setting("data_version")
        if not version:
            raise HTTPException(503, "请先初始化示例数仓")
        return Warehouse(store.setting("source")), version

    def result_for(row):
        if not row["result"]:
            raise HTTPException(409, "请先完成一次分析")
        return load(row["result"])

    def completed_context(analysis):
        job_id = analysis.get("job_id")
        job = store.one("SELECT context FROM job WHERE id=?", (job_id,)) if job_id else None
        return load(job["context"]) if job else None

    @app.get("/api/health")
    def health():
        return {"status": "ok", "data_initialized": bool(store.setting("data_version"))}

    @app.post("/api/auth/login")
    def login(body: Login):
        row = store.one("SELECT * FROM user_account WHERE username=?", (body.username,))
        hash_to_check = row["password_hash"] if row else (
            "00000000000000000000000000000000:" + "0" * 128
        )
        if not matches(body.password, hash_to_check) or row is None:
            store.audit(body.username, "auth.login_failed", body.username)
            raise HTTPException(401, "用户名或密码错误")
        store.audit(body.username, "auth.login", body.username)
        return {"access_token": issue(body.username, app.state.signing_key), "token_type": "bearer",
                "user": {"username": row["username"], "role": row["role"], "domains": load(row["domains"])}}

    @app.get("/api/meta")
    def metadata():
        return {"demo_period": {"start": str(DEMO_START), "end": str(DEMO_END)},
                "baselines": ["mom", "yoy", "target"], "dimensions": DIMENSIONS}

    @app.get("/api/auth/me")
    def me(actor=Depends(principal)):
        return actor

    @app.get("/api/domains")
    def domains(actor=Depends(principal)):
        return [{"domain_id": domain, **store.setting(f"business_line:{domain}", {
            "name": DOMAIN_LABELS[domain], "description": "",
        })} for domain in actor["domains"]]

    @app.get("/api/dashboard/metrics")
    def dashboard(domain_id: Domain | None = None, start: date = DEMO_START, end: date = DEMO_END,
                  baseline: str = "mom", actor=Depends(principal)):
        from backend.schemas import Period
        try:
            period = Period(start=start, end=end, baseline=baseline)
        except ValueError:
            raise HTTPException(422, "日期或基期口径无效") from None
        authorize(actor, domain_id)
        warehouse, version = warehouse_context()
        catalog = store.catalog()
        result = []
        for domain in [domain_id] if domain_id else actor["domains"]:
            definitions = [item for item in catalog.values() if item["domain_id"] == domain]
            if not definitions:
                continue
            spec = AnalysisSpec(metric_id=definitions[0]["metric_id"], **period.model_dump())
            before, after = window_rows(warehouse, domain, version, spec)
            last_days = warehouse.facts(domain, version, period.start, period.end, group=("day",))
            for item in definitions:
                key = item["metric_id"]
                a = Evaluator(catalog, before[0]).value(key) if before else None
                b = Evaluator(catalog, after[0]).value(key) if after else None
                delta = b - a if b is not None and a is not None else None
                rate = delta / abs(a) if delta is not None and a else None
                result.append({**item, "baseline_value": a, "current_value": b, "delta": delta,
                               "delta_rate": rate, "anomaly": rate is not None and abs(rate) >= item["threshold"],
                               "trend": [{"day": row["day"], "value": Evaluator(catalog, row).value(key)}
                                         for row in last_days]})
        result.sort(key=lambda item: (item["metric_id"] not in {"gmv", "net_margin"}, -abs(item["delta_rate"] or 0)))
        return {"period": period.model_dump(mode="json"), "data_version": version, "metrics": result,
                "attention": sorted((item for item in result if item["anomaly"]),
                                    key=lambda item: abs(item["delta_rate"]), reverse=True)}

    @app.post("/api/sessions", status_code=201)
    async def create_session(body: CreateSession, actor=Depends(principal)):
        authorize(actor, body.domain_id, {"analyst", "admin"})
        warehouse_context()
        catalog = store.catalog()
        permitted = {key: row for key, row in catalog.items()
                     if row["domain_id"] in actor["domains"] and (not body.domain_id or row["domain_id"] == body.domain_id)}
        metric = body.metric_id
        if metric is None:
            response = await model.json_request(
                "选择用户想分析的指标。只返回 JSON 对象，字段 metric_id，只能从给定指标 ID 中选择。",
                {"question": body.question, "metrics": {key: item["name"] for key, item in permitted.items()}},
                600, schema=object_schema({"metric_id": {"type": "string", "enum": list(permitted)}}),
            )
            metric = response.get("metric_id")
        if not isinstance(metric, str) or metric not in permitted:
            raise HTTPException(422, "请选择有权访问的有效指标")
        definition = permitted[metric]
        domain = definition["domain_id"]
        try:
            spec = AnalysisSpec(metric_id=metric, start=body.start or DEMO_START, end=body.end or DEMO_END,
                                baseline=body.baseline)
        except ValueError:
            raise HTTPException(422, "日期区间无效") from None
        identifier, stamp = uuid4().hex, now()
        job_id = None
        with store.connect() as db:
            db.execute("INSERT INTO analysis_session VALUES (?,?,?,?,?,?,?,?,?)",
                       (identifier, actor["username"], domain, spec.model_dump_json(), definition["name"],
                        "idle", None, stamp, stamp))
            store.audit(actor["username"], "session.create", identifier, spec.model_dump(mode="json"), db)
            if body.auto_start:
                job_id = app.state.jobs.create(identifier, actor["username"],
                                               body.question or "按当前指标和所选日期自动归因", db=db)
        if job_id:
            app.state.jobs.launch(job_id)
        return {**serialize_session(session_for(identifier, actor)), "job_id": job_id,
                "stream_url": f"/api/jobs/{job_id}/events" if job_id else None}

    @app.get("/api/sessions")
    def sessions(domain_id: Domain | None = None, limit: int = Query(50, ge=1, le=200),
                 actor=Depends(principal)):
        authorize(actor, domain_id)
        clauses, values = [], []
        if actor["role"] != "admin":
            clauses.append("owner=?")
            values.append(actor["username"])
        allowed = [domain_id] if domain_id else actor["domains"]
        clauses.append(f"domain_id IN ({','.join('?' for _ in allowed)})")
        where = " AND ".join(clauses)
        rows = store.all(f"SELECT * FROM analysis_session WHERE {where} ORDER BY updated_at DESC LIMIT ?",
                         (*values, *allowed, limit))
        return [serialize_session(row, include_result=False) for row in rows]

    @app.get("/api/sessions/{session_id}")
    def session_detail(session_id: str, actor=Depends(principal)):
        row = session_for(session_id, actor)
        jobs = store.all("""
            SELECT j.id,j.question,j.status,j.created_at,json_extract(j.result,'$.summary') AS summary,
                   (SELECT max(e.seq) FROM job_event AS e WHERE e.job_id=j.id) AS last_event_id
            FROM job AS j WHERE j.session_id=? ORDER BY j.created_at
        """, (session_id,))
        return {**serialize_session(row), "messages": [dict(job) for job in jobs]}

    @app.post("/api/sessions/{session_id}/messages")
    async def send_message(session_id: str, body: Message, request: Request,
                           actor=Depends(principal),
                           idempotency_key: Annotated[str | None, Header(max_length=120)] = None):
        session_for(session_id, actor, write=True)
        try:
            identifier = app.state.jobs.create(session_id, actor["username"], body.content, idempotency_key)
        except AnalysisError as exc:
            raise HTTPException(409, str(exc)) from None
        app.state.jobs.launch(identifier)
        return stream(identifier, 0, request)

    def stream(job_id, cursor, request):
        async def events():
            nonlocal cursor
            keepalive = asyncio.get_running_loop().time()
            while not await request.is_disconnected():
                rows = store.all("SELECT * FROM job_event WHERE job_id=? AND seq>? ORDER BY seq LIMIT 100",
                                 (job_id, cursor))
                for row in rows:
                    cursor = row["seq"]
                    yield f"id: {cursor}\nevent: {row['type']}\ndata: {row['payload']}\n\n"
                    if row["type"] in TERMINAL:
                        return
                if not rows and store.one("SELECT status FROM job WHERE id=?", (job_id,))["status"] in TERMINAL:
                    return
                if not rows:
                    if asyncio.get_running_loop().time() - keepalive >= 10:
                        yield ": heartbeat\n\n"
                        keepalive = asyncio.get_running_loop().time()
                    await asyncio.sleep(.20)
        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                          "X-Analysis-Job-Id": job_id})

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request, actor=Depends(principal),
                         last_event_id: Annotated[int | None, Header(ge=0)] = None,
                         after: Annotated[int, Query(ge=0)] = 0):
        job_for(job_id, actor)
        return stream(job_id, last_event_id if last_event_id is not None else after, request)

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str, actor=Depends(principal)):
        job = job_for(job_id, actor, write=True)
        return {"cancelled": app.state.jobs.cancel(job, actor["username"])}

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    async def retry_job(job_id: str, actor=Depends(principal)):
        job = job_for(job_id, actor, write=True)
        try:
            identifier = app.state.jobs.retry(job, actor["username"])
        except AnalysisError as exc:
            raise HTTPException(409, str(exc)) from None
        app.state.jobs.launch(identifier)
        return {"job_id": identifier, "stream_url": f"/api/jobs/{identifier}/events"}

    def reviews(job_id, db=None):
        sql = "SELECT * FROM evidence_review WHERE job_id=? ORDER BY updated_at"
        rows = db.execute(sql, (job_id,)).fetchall() if db else store.all(sql, (job_id,))
        return [{"hypothesis_id": row["hypothesis_id"], "author": row["author"],
                 "updated_at": row["updated_at"], **load(row["payload"])} for row in rows]

    @app.get("/api/jobs/{job_id}/reviews")
    def evidence_reviews(job_id: str, actor=Depends(principal)):
        job_for(job_id, actor)
        return reviews(job_id)

    @app.put("/api/jobs/{job_id}/hypotheses/{hypothesis_id}/review")
    def review_evidence(job_id: str, hypothesis_id: str, body: EvidenceReviewInput, actor=Depends(principal)):
        job = job_for(job_id, actor, write=True)
        if job["status"] != "complete":
            raise HTTPException(409, "请等待分析完成")
        if not any(item["hypothesis_id"] == hypothesis_id for item in load(job["result"])["hypotheses"]):
            raise HTTPException(404, "假设不存在")
        stamp = now()
        payload = body.model_dump()
        with store.connect() as db:
            db.execute("""
                INSERT INTO evidence_review VALUES (?,?,?,?,?)
                ON CONFLICT(job_id,hypothesis_id,author) DO UPDATE
                SET payload=excluded.payload, updated_at=excluded.updated_at
            """, (job_id, hypothesis_id, actor["username"], dump(payload), stamp))
            store.audit(actor["username"], "evidence.review", job_id, {
                "hypothesis_id": hypothesis_id, **payload,
            }, db)
        return {"hypothesis_id": hypothesis_id, "author": actor["username"], "updated_at": stamp, **payload}

    @app.get("/api/sessions/{session_id}/decomposition")
    def decomposition(session_id: str, actor=Depends(principal)):
        row = session_for(session_id, actor)
        if result := load(row["result"]):
            return result["decomposition"]
        warehouse, version = warehouse_context()
        return get_decomposition(warehouse, row["domain_id"], version,
                                 AnalysisSpec.model_validate_json(row["spec"]), store.catalog())

    @app.get("/api/sessions/{session_id}/drilldown")
    def session_drilldown(session_id: str, dim: Annotated[list[Dimension] | None, Query()] = None,
                          actor=Depends(principal)):
        row = session_for(session_id, actor)
        if not dim and (result := load(row["result"])):
            return result["drilldown"]
        spec = AnalysisSpec.model_validate_json(row["spec"])
        dim = dim or spec.dimensions
        if len(set(dim)) != len(dim) or len(dim) > 5:
            raise HTTPException(422, "下钻维度最多五个且不可重复")
        if (analysis := load(row["result"])) and (context := completed_context(analysis)):
            warehouse, version, catalog = (Warehouse(context["source"]), context["version"], context["catalog"])
        else:
            warehouse, version = warehouse_context()
            catalog = store.catalog()
        return drilldown(warehouse, row["domain_id"], version, spec, catalog, dim)

    @app.get("/api/sessions/{session_id}/scenarios")
    def list_scenarios(session_id: str, actor=Depends(principal)):
        session_for(session_id, actor)
        return scenarios(session_id)

    def scenarios(session_id, db=None):
        sql = "SELECT payload FROM scenario WHERE session_id=? ORDER BY created_at"
        rows = db.execute(sql, (session_id,)).fetchall() if db else store.all(sql, (session_id,))
        return [load(row["payload"]) for row in rows]

    @app.post("/api/sessions/{session_id}/whatif")
    def what_if(session_id: str, body: ScenarioInput, actor=Depends(principal)):
        row = session_for(session_id, actor, write=True)
        analysis = result_for(row)
        spec = AnalysisSpec.model_validate(analysis["spec"])
        context = completed_context(analysis)
        warehouse = Warehouse(context["source"] if context else store.setting("source"))
        catalog = context["catalog"] if context else store.catalog()
        version = analysis["data_version"]
        history = training_data(warehouse, row["domain_id"], version, spec)
        _, current = window_rows(warehouse, row["domain_id"], version, spec)
        if not current:
            raise AnalysisError("所选时间或切片没有数仓数据")
        simulation_result = simulation(spec.metric_id, catalog, history, current[0], body.changes)
        result = {"id": uuid4().hex if body.save else None, "name": body.name, "spec": analysis["spec"],
                  "data_version": version, **simulation_result}
        if body.save:
            with store.connect() as db:
                db.execute("INSERT INTO scenario VALUES (?,?,?,?)", (result["id"], session_id, dump(result), now()))
                store.audit(actor["username"], "scenario.save", session_id, result, db)
        return result

    @app.delete("/api/sessions/{session_id}/whatif/{scenario_id}", status_code=204)
    def delete_scenario(session_id: str, scenario_id: str, actor=Depends(principal)):
        session_for(session_id, actor, write=True)
        with store.connect() as db:
            if not db.execute("DELETE FROM scenario WHERE id=? AND session_id=?",
                              (scenario_id, session_id)).rowcount:
                raise HTTPException(404, "推演情景不存在")
            store.audit(actor["username"], "scenario.delete", session_id, {"scenario_id": scenario_id}, db)

    @app.post("/api/sessions/{session_id}/snapshots", status_code=201)
    def snapshot(session_id: str, body: Annotated[SnapshotInput, Body()] = SnapshotInput(),
                 actor=Depends(principal)):
        row = session_for(session_id, actor, write=True)
        result = {"id": uuid4().hex, "label": body.label,
                  "analysis": result_for(row), "created_at": now()}
        with store.connect() as db:
            db.execute("INSERT INTO snapshot VALUES (?,?,?,?,?)",
                       (result["id"], session_id, body.label, dump(result), result["created_at"]))
            store.audit(actor["username"], "snapshot.save", session_id, {"snapshot_id": result["id"]}, db)
        return result

    @app.get("/api/sessions/{session_id}/snapshots")
    def list_snapshots(session_id: str, actor=Depends(principal)):
        session_for(session_id, actor)
        return [load(row["payload"]) for row in store.all(
            "SELECT payload FROM snapshot WHERE session_id=? ORDER BY created_at DESC", (session_id,)
        )]

    @app.post("/api/sessions/{session_id}/report", status_code=201)
    def create_report(session_id: str, body: Annotated[ReportInput, Body()] = ReportInput(),
                      actor=Depends(principal)):
        row = session_for(session_id, actor, write=True)
        analysis = result_for(row)
        identifier, stamp = uuid4().hex, now()
        title = body.title or f"{row['title']} · 经营归因报告"
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("SELECT coalesce(max(version),0)+1 FROM report WHERE session_id=?",
                                 (session_id,)).fetchone()[0]
            saved = [scenario for scenario in scenarios(session_id, db)
                     if scenario["spec"] == analysis["spec"] and scenario["data_version"] == analysis["data_version"]]
            payload = {"analysis": analysis, "scenarios": saved, "reviews": reviews(analysis.get("job_id"), db)}
            db.execute("INSERT INTO report VALUES (?,?,?,?,?,?,?,?)",
                       (identifier, session_id, version, "draft", title, dump(payload), stamp, stamp))
            store.audit(actor["username"], "report.create", identifier, {"version": version}, db)
        return {"id": identifier, "session_id": session_id, "version": version, "title": title, "status": "draft"}

    @app.get("/api/reports/{report_id}/preview", response_class=HTMLResponse)
    def preview(report_id: str, actor=Depends(principal)):
        row = report_for(report_id, actor)
        return reports.html_report(row["title"], load(row["payload"]))

    @app.get("/api/reports/{report_id}/export")
    def export(report_id: str, fmt: str = Query(pattern="^(md|pdf|xlsx)$"),
               section: Annotated[list[str] | None, Query()] = None, actor=Depends(principal)):
        row = report_for(report_id, actor)
        if section and any(key not in reports.TITLES for key in section):
            raise HTTPException(422, "包含未知报告章节")
        media = {"md": "text/markdown", "pdf": "application/pdf",
                 "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        renderer = {"md": reports.markdown, "pdf": reports.pdf, "xlsx": reports.excel}[fmt]
        try:
            output = renderer(row["title"], load(row["payload"]), section)
        except (OSError, subprocess.SubprocessError):
            logger.exception("Cannot render report %s", report_id)
            raise HTTPException(503, "报告渲染服务不可用") from None
        store.audit(actor["username"], "report.export", report_id, {"format": fmt, "sections": section})
        return Response(output, media_type=media[fmt], headers={
            "Content-Disposition": f'attachment; filename="attribution-{report_id[:8]}.{fmt}"',
            "Cache-Control": "no-store",
        })

    from backend.management import management_routes
    management_routes(app, store, principal, authorize, report_for, warehouse_context)
    return app


app = create_app()
