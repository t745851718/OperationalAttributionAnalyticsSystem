from datetime import date
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.controllers.management import management_routes
from backend.controllers.sessions import session_routes
from backend.models.catalog import DEMO_END, DEMO_START, DIMENSIONS, DOMAIN_LABELS
from backend.models.metrics import Evaluator
from backend.models.schemas import AnalysisSpec, Domain, Login
from backend.models.store import load
from backend.models.warehouse import Warehouse
from backend.services.analysis import window_rows
from backend.services.auth import issue, matches


def register_routes(app, store, model):
    bearer = HTTPBearer(auto_error=False)

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
        row = store.one("SELECT username,role,domains FROM user_account WHERE username=%s", (claims["sub"],))
        if not row:
            raise denied()
        request.state.username = row["username"]
        return {**dict(row), "domains": load(row["domains"])}

    def authorize(actor, domain=None, roles=None):
        if (domain and domain not in actor["domains"]) or (roles and actor["role"] not in roles):
            raise HTTPException(403, "无权访问此指标域或执行此操作")

    def session_for(session_id, actor, write=False):
        row = store.one("SELECT * FROM analysis_session WHERE id=%s", (session_id,))
        if not row:
            raise HTTPException(404, "分析会话不存在")
        authorize(actor, row["domain_id"], {"analyst", "admin"} if write else None)
        if row["owner"] != actor["username"] and actor["role"] != "admin":
            raise HTTPException(403, "此会话仅对创建者和管理员开放")
        return row

    def report_for(report_id, actor, write=False):
        row = store.one("""
            SELECT report.*, analysis_session.domain_id, analysis_session.owner
            FROM report JOIN analysis_session ON analysis_session.id=report.session_id WHERE report.id=%s
        """, (report_id,))
        if not row:
            raise HTTPException(404, "报告不存在")
        authorize(actor, row["domain_id"], {"analyst", "admin"} if write else None)
        if row["owner"] != actor["username"] and actor["role"] != "admin" and (write or row["status"] != "published"):
            raise HTTPException(403, "报告尚未发布或无编辑权限")
        return row

    def job_for(job_id, actor, write=False):
        row = store.one("SELECT * FROM job WHERE id=%s", (job_id,))
        if not row:
            raise HTTPException(404, "分析任务不存在")
        session_for(row["session_id"], actor, write)
        return row

    def warehouse_context():
        version = store.setting("data_version")
        if not version:
            raise HTTPException(503, "请先初始化示例数仓")
        return Warehouse(store.setting("source")), version

    @app.get("/api/health")
    def health():
        return {"status": "ok", "data_initialized": bool(store.setting("data_version"))}

    @app.post("/api/auth/login")
    def login(body: Login):
        row = store.one("SELECT * FROM user_account WHERE username=%s", (body.username,))
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
        from backend.models.schemas import Period
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

    session_routes(app, store, model, principal, authorize, session_for, report_for, job_for, warehouse_context)
    management_routes(app, store, principal, authorize, report_for, warehouse_context)
