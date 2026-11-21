import asyncio
import logging
from psycopg.errors import UniqueViolation
from datetime import timedelta
from uuid import uuid4

import httpx

from backend.services.analysis import AnalysisError, actions, drilldown, event_matches, get_decomposition, plan, training_data, window_rows
from backend.services.llm_client import ModelError, object_schema
from backend.services.sandbox import evidence_code, verify
from backend.services.sandbox_worker import TEMPLATES
from backend.models.schemas import AnalysisSpec, Planned, RuntimeSettings
from backend.models.store import dump, load, now
from backend.models.warehouse import Warehouse, baseline_period

logger = logging.getLogger(__name__)
TERMINAL = {"complete", "failed", "cancelled"}
STEPS = ("识别异动", "指标拆解", "维度下钻", "假设生成", "统计检验", "业务归因", "策略建议")
DRIVERS = {
    "traffic_drop": "visits", "conversion_drop": "conversion", "channel_mix": "conversion",
    "stockout_aov": "aov", "stockout_rate": "aov", "promo_increase": "visits", "aov_drop": "aov",
    "materials_rate": "materials", "commission_rate": "commission", "logistics_rate": "logistics",
}


def serialize_session(row, include_result=True):
    value = {key: row[key] for key in ("id", "owner", "domain_id", "title", "status", "created_at", "updated_at")}
    value.update(spec=load(row["spec"]))
    if include_result:
        value["result"] = load(row["result"])
    return value


class Jobs:
    def __init__(self, store, model, verifier=verify):
        self.store = store
        self.model = model
        self.verifier = verifier
        self.tasks = {}
        self.slots = asyncio.Semaphore(2)

    @staticmethod
    def emit(db, job_id, event, payload):
        db.execute("INSERT INTO job_event(job_id,type,payload) VALUES (%s,%s,%s)",
                   (job_id, event, dump(payload)))

    def create(self, session_id, username, question, request_key=None, db=None):
        if db is None:
            with self.store.connect() as connection:
                return self.create(session_id, username, question, request_key, connection)
        db.execute("SELECT id FROM analysis_session WHERE id=%s FOR UPDATE", (session_id,))
        if request_key:
            existing = db.execute("SELECT id,question FROM job WHERE session_id=%s AND request_key=%s",
                                  (session_id, request_key)).fetchone()
            if existing:
                if existing["question"] != question:
                    raise AnalysisError("同一幂等键已用于其他问题")
                return existing["id"]
        identifier, timestamp = uuid4().hex, now()
        try:
            db.execute("""
                INSERT INTO job(id,session_id,question,request_key,status,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (identifier, session_id, question, request_key, "queued", timestamp, timestamp))
        except UniqueViolation as exc:
            raise AnalysisError("此会话已有进行中的分析") from exc
        db.execute("UPDATE analysis_session SET status='queued',updated_at=%s WHERE id=%s", (timestamp, session_id))
        self.emit(db, identifier, "plan", {"status": "queued", "job_id": identifier, "steps": STEPS})
        self.store.audit(username, "analysis.queued", session_id, {"job_id": identifier}, db)
        return identifier

    def retry(self, job, username):
        with self.store.connect() as db:
            db.execute("SELECT id FROM analysis_session WHERE id=%s FOR UPDATE", (job["session_id"],))
            latest = db.execute("SELECT id FROM job WHERE session_id=%s ORDER BY created_at DESC LIMIT 1",
                                (job["session_id"],)).fetchone()
            if job["status"] != "failed" or latest["id"] != job["id"]:
                raise AnalysisError("仅可重试会话中最近一次失败的分析")
            identifier = self.create(job["session_id"], username, job["question"], db=db)
            checkpoints = (load(job["result"]) or {}).get("verified", {})
            verified = {key: item for key, item in checkpoints.items()
                        if item["status"] not in {"timeout", "error"}}
            db.execute("UPDATE job SET context=%s,plan=%s,result=%s WHERE id=%s",
                       (job["context"], job["plan"], dump({"verified": verified}), identifier))
            self.store.audit(username, "analysis.retry", job["session_id"],
                             {"original_job_id": job["id"], "job_id": identifier}, db)
        return identifier

    def launch(self, identifier):
        if identifier not in self.tasks:
            self.tasks[identifier] = asyncio.create_task(self.run(identifier))
            self.tasks[identifier].add_done_callback(lambda _: self.tasks.pop(identifier, None))

    def recover(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT id FROM job WHERE status IN ('queued','running')").fetchall()
            for row in rows:
                self.emit(db, row["id"], "step", {"status": "resumed", "label": "已恢复，继续执行"})
        for row in rows:
            self.launch(row["id"])

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def cancel(self, job, username):
        changed = self.finish(job, "cancelled", {"message": "已停止分析"}, user=username)
        if changed and (task := self.tasks.get(job["id"])):
            task.cancel()
        return changed

    def finish(self, job, status, info, result=None, user=None):
        stamp = now()
        identifier, session_id = job["id"], job["session_id"]
        with self.store.connect() as db:
            updated = db.execute("""
                UPDATE job SET status=%s,updated_at=%s WHERE id=%s AND status IN ('queued','running')
            """, (status, stamp, identifier)).rowcount
            if not updated:
                return False
            if status == "complete":
                db.execute("UPDATE job SET result=%s WHERE id=%s", (dump(result), identifier))
                db.execute("""
                    UPDATE analysis_session SET status=%s, updated_at=%s, spec=%s, result=%s, title=%s WHERE id=%s
                """, (status, stamp, dump(result["spec"]), dump(result), result["decomposition"]["name"], session_id))
                self.emit(db, identifier, "conclusion", result)
            else:
                db.execute("UPDATE analysis_session SET status=%s,updated_at=%s WHERE id=%s",
                           (status, stamp, session_id))
            self.emit(db, identifier, status, {"status": status, "job_id": identifier, **info})
            subject = user or db.execute("SELECT owner FROM analysis_session WHERE id=%s", (session_id,)).fetchone()["owner"]
            self.store.audit(subject, f"analysis.{status}", session_id, {"job_id": identifier, **info}, db)
        return True

    def step(self, job_id, index, status="running", **detail):
        with self.store.connect() as db:
            self.emit(db, job_id, "step", {"index": index, "label": STEPS[index], "status": status, **detail})

    async def run(self, identifier):
        async with self.slots:
            with self.store.connect() as db:
                job = db.execute("SELECT * FROM job WHERE id=%s FOR UPDATE", (identifier,)).fetchone()
                if job is None or job["status"] in TERMINAL:
                    return
                db.execute("UPDATE job SET status='running',updated_at=%s WHERE id=%s", (now(), identifier))
                db.execute("UPDATE analysis_session SET status='running',updated_at=%s WHERE id=%s",
                           (now(), job["session_id"]))
                session = db.execute("SELECT * FROM analysis_session WHERE id=%s", (job["session_id"],)).fetchone()
            try:
                async with asyncio.timeout(240):
                    result = await self.execute(job, session)
            except (AnalysisError, ModelError) as exc:
                self.finish(job, "failed", {"message": str(exc), "retryable": True})
            except httpx.HTTPError:
                self.finish(job, "failed", {"message": "数仓连接或查询失败", "retryable": True})
            except TimeoutError:
                self.finish(job, "failed", {"message": "分析任务超时，已保留检查点", "retryable": True})
            except Exception:
                logger.exception("Analysis job failed %s", identifier)
                self.finish(job, "failed", {"message": "分析任务执行失败，请查看后端日志", "retryable": True})
            else:
                self.finish(job, "complete", {}, result)

    async def execute(self, job, session):
        identifier, domain = job["id"], session["domain_id"]
        context = load(job["context"])
        if not context:
            version = self.store.setting("data_version")
            if not version:
                raise AnalysisError("请先初始化示例数仓")
            context = {
                "catalog": {key: item for key, item in self.store.catalog().items() if item["domain_id"] == domain},
                "version": version,
                "source": self.store.setting("source"),
                "settings": self.store.setting("runtime", {}),
                "inherited": load(session["spec"]),
                "events": [load(row["payload"]) for row in self.store.all(
                    "SELECT payload FROM biz_event WHERE domain_id=%s", (domain,)
                )],
            }
            self.store.write("UPDATE job SET context=%s WHERE id=%s", (dump(context), identifier))
        catalog, version = context["catalog"], context["version"]
        warehouse = Warehouse(context["source"])
        settings = RuntimeSettings.model_validate(context["settings"])
        inherited = AnalysisSpec.model_validate(context["inherited"])
        self.step(identifier, 0)
        if job["plan"]:
            selected = Planned.model_validate_json(job["plan"])
        else:
            selected = await plan(self.model, warehouse, catalog, domain, version, job["question"],
                                  inherited, settings.model_max_tokens)
            with self.store.connect() as db:
                db.execute("UPDATE job SET plan=%s WHERE id=%s", (selected.model_dump_json(), identifier))
                self.emit(db, identifier, "plan",
                          {"status": "planned", "job_id": identifier, **selected.model_dump(mode="json")})
        spec = selected.spec
        self.step(identifier, 0, "complete", metric_id=spec.metric_id)
        self.step(identifier, 1)
        decomposition = await asyncio.to_thread(get_decomposition, warehouse, domain, version, spec, catalog)
        if decomposition["delta"] is None:
            raise AnalysisError("指标不可计算，请调整分析口径")
        self.step(identifier, 1, "complete", method=decomposition["method"])
        self.step(identifier, 2)
        drill = await asyncio.to_thread(drilldown, warehouse, domain, version, spec, catalog, spec.dimensions)
        self.step(identifier, 2, "complete")
        self.step(identifier, 3, "complete", count=len(selected.hypotheses))
        self.step(identifier, 4)
        checked = (load(job["result"]) or {}).get("verified", {})
        baseline_start, baseline_end, variant = baseline_period(spec.start, spec.end, spec.baseline)
        semaphore = asyncio.Semaphore(3)

        async def check(index, hypothesis):
            ref = str(index + 1)
            if ref in checked:
                return checked[ref]
            factors = {row["metric_id"]: row for row in decomposition["factors"]}
            contribution = factors.get(DRIVERS.get(hypothesis.template), {}).get("contribution_rate") or 0
            request = {
                "domain": domain, "template": hypothesis.template, "scope": hypothesis.scope,
                "filters": spec.filters, "baseline": [str(baseline_start), str(baseline_end), variant],
                "current": [str(spec.start), str(spec.end), "actual"],
                "history": [str(spec.start - timedelta(days=84)), str(spec.start - timedelta(days=1)), "actual"],
                "coverage": abs(contribution), "threshold": settings.confidence_threshold,
            }
            code = evidence_code(request)
            start = asyncio.get_running_loop().time()
            context = {"hypothesis_id": ref, **hypothesis.model_dump(),
                       "statement": TEMPLATES[domain][hypothesis.template][0]}
            with self.store.connect() as db:
                self.emit(db, identifier, "hypothesis", {**context, "status": "verifying"})
                self.emit(db, identifier, "code", {"hypothesis_id": ref, **code})
                self.store.audit(session["owner"], "sandbox.started", session["id"], {
                    "job_id": identifier, "hypothesis_id": ref, "input": request, "code": code,
                }, db)
            async with semaphore:
                output = await self.verifier(version, request, settings.sandbox_timeout, settings.sandbox_memory_mb)
            item = {**context, **output, "code": code, "data_version": version,
                    "elapsed_ms": round((asyncio.get_running_loop().time() - start) * 1000)}
            checked[ref] = item
            with self.store.connect() as db:
                db.execute("UPDATE job SET result=%s WHERE id=%s", (dump({"verified": checked}), identifier))
                self.emit(db, identifier, "hypothesis", item)
                self.store.audit(session["owner"], "sandbox.verify", session["id"],
                                 {"job_id": identifier, "input": request, "evidence": item}, db)
            return item

        async with asyncio.TaskGroup() as group:
            verification = [group.create_task(check(i, item)) for i, item in enumerate(selected.hypotheses)]
        hypotheses = [task.result() for task in verification]
        if all(item["status"] in {"timeout", "error"} for item in hypotheses):
            raise AnalysisError("统计沙箱未返回结果，请检查镜像、挂载与资源配额")
        self.step(identifier, 4, "complete")
        self.step(identifier, 5)
        matched = event_matches(context.get("events", []), spec, drill)
        supported = sorted((item for item in hypotheses if item["status"] == "supported"),
                           key=lambda item: item["confidence"], reverse=True)
        for event in matched:
            related = [item["hypothesis_id"] for item in supported
                       if not event["after_window"] and item["scope"]
                       and all(key in event["scope"] and value in event["scope"][key]
                                                for key, value in item["scope"].items())]
            event["supporting_hypotheses"] = related
            if related:
                event["status"] = "consistent_with_evidence"
        self.step(identifier, 5, "complete", matched=len(matched))
        self.step(identifier, 6)
        history = await asyncio.to_thread(training_data, warehouse, domain, version, spec)
        _, current = await asyncio.to_thread(window_rows, warehouse, domain, version, spec)
        recommendations = await asyncio.to_thread(actions, spec.metric_id, catalog, history, current[0], decomposition)
        summary_evidence = [{"id": item["hypothesis_id"], "statement": item["statement"], "status": item["status"],
                             "scope": item["scope"], "reasons": item.get("reasons", [])} for item in hypotheses]
        if previous := load(session["result"]):
            prior_context = {"spec": previous["spec"], "summary": previous.get("summary")}
        else:
            prior_context = None
        summary = await self.model.json_request(
            "用中文概述已验证的经营分析，输出 JSON 对象，唯一字段 summary 为字符串。"
            "仅使用给定证据，区分已支持、已排除与候选外部事件。说明关联的局限，不生成任何数字。"
            "可以使用指标名或事件名。不得编造行动建议。",
            {"question": job["question"], "previous": prior_context, "evidence": summary_evidence,
             "drivers": [{"name": row["name"], "direction": "negative" if row["contribution"] < 0 else "positive"}
                         for row in decomposition["factors"]],
             "events": [{"title": event["title"], "status": event["status"]} for event in matched]},
            min(950, settings.model_max_tokens), schema=object_schema({"summary": {"type": "string"}}),
        )
        summary_text = summary.get("summary")
        if not isinstance(summary_text, str) or not summary_text.strip() or len(summary_text) > 1200:
            raise ModelError("模型返回的结论格式无效")
        self.step(identifier, 6, "complete", recommendations=len(recommendations))
        return dict(job_id=identifier, data_version=version, spec=spec.model_dump(mode="json"), decomposition=decomposition,
                    drilldown=drill, hypotheses=hypotheses, events=matched, actions=recommendations,
                    summary=summary_text.strip(), primary_hypothesis=supported[0]["hypothesis_id"] if supported else None,
                    secondary_hypotheses=[item["hypothesis_id"] for item in supported[1:]])
