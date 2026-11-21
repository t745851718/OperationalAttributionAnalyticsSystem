from datetime import date
from uuid import uuid4

from fastapi import Depends, HTTPException, Query

from backend.models.catalog import DIMENSIONS, DOMAIN_LABELS
from backend.models.metrics import validate_catalog
from backend.models.schemas import (
    BusinessLineInput,
    CommentInput,
    DataSourceInput,
    Domain,
    EventInput,
    MetricInput,
    ReportStatus,
    RuntimeSettings,
    SubscriptionInput,
)
from backend.models.store import dump, load, now
from backend.models.warehouse import TABLES, Warehouse
from backend.services.sandbox import verify
from backend.views import reports


def report_public(row, detail=False):
    result = {key: row[key] for key in ("id", "session_id", "version", "status", "title",
                                        "created_at", "updated_at", "owner", "domain_id")}
    if detail:
        result.update(payload=load(row["payload"]), sections=reports.TITLES)
    return result


def management_routes(app, store, principal, authorize, report_for, warehouse_context):
    def require_admin(actor, domain=None):
        authorize(actor, domain, {"admin"})

    def domain_objects(table, domain_id, actor):
        authorize(actor, domain_id)
        allowed = [domain_id] if domain_id else actor["domains"]
        return [load(row["payload"]) for row in store.all(
            f"SELECT payload FROM {table} WHERE domain_id IN ({','.join('%s' for _ in allowed)})", allowed,
        )]

    @app.get("/api/dimensions")
    def dimensions(domain_id: Domain, actor=Depends(principal)):
        authorize(actor, domain_id)
        warehouse, version = warehouse_context()
        from backend.models.catalog import DEMO_END, DEMO_START
        return [{"key": key, "name": label,
                 "values": [row[key] for row in warehouse.facts(
                     domain_id, version, DEMO_START, DEMO_END, group=(key,)
                 )]}
                for key, label in DIMENSIONS.items()]

    @app.get("/api/events")
    def events(domain_id: Domain | None = None, type: str | None = None,
               start: date | None = None, end: date | None = None, actor=Depends(principal)):
        if start and end and start > end:
            raise HTTPException(422, "日期区间无效")
        rows = domain_objects("biz_event", domain_id, actor)
        return sorted((item for item in rows if (not type or item["type"] == type)
                       and (not start or item["end"] >= str(start))
                       and (not end or item["start"] <= str(end))), key=lambda item: item["start"])

    def write_event(event_id, body, actor, update=False):
        require_admin(actor, body.domain_id)
        result = {"event_id": event_id, **body.model_dump(mode="json"), "updated_at": now()}
        with store.connect() as db:
            db.execute("LOCK TABLE biz_event IN SHARE ROW EXCLUSIVE MODE")
            if update:
                row = db.execute("SELECT domain_id FROM biz_event WHERE event_id=%s", (event_id,)).fetchone()
                if not row:
                    raise HTTPException(404, "事件不存在")
                require_admin(actor, row["domain_id"])
                if row["domain_id"] != body.domain_id:
                    raise HTTPException(422, "事件所属指标域不可修改")
                db.execute("UPDATE biz_event SET payload=%s WHERE event_id=%s", (dump(result), event_id))
            else:
                db.execute("INSERT INTO biz_event VALUES (%s,%s,%s)", (event_id, body.domain_id, dump(result)))
            store.audit(actor["username"], "event.update" if update else "event.create", event_id, result, db)
        return result

    @app.post("/api/events", status_code=201)
    def add_event(body: EventInput, actor=Depends(principal)):
        return write_event(uuid4().hex, body, actor)

    @app.put("/api/events/{event_id}")
    def update_event(event_id: str, body: EventInput, actor=Depends(principal)):
        return write_event(event_id, body, actor, update=True)

    @app.delete("/api/events/{event_id}", status_code=204)
    def delete_event(event_id: str, actor=Depends(principal)):
        require_admin(actor)
        with store.connect() as db:
            db.execute("LOCK TABLE biz_event IN SHARE ROW EXCLUSIVE MODE")
            row = db.execute("SELECT domain_id FROM biz_event WHERE event_id=%s", (event_id,)).fetchone()
            if not row:
                raise HTTPException(404, "事件不存在")
            require_admin(actor, row["domain_id"])
            db.execute("DELETE FROM biz_event WHERE event_id=%s", (event_id,))
            store.audit(actor["username"], "event.delete", event_id, db=db)

    @app.get("/api/metrics")
    def metrics(domain_id: Domain | None = None, actor=Depends(principal)):
        return domain_objects("metric_def", domain_id, actor)

    def write_metric(body, actor, update=False):
        require_admin(actor, body.domain_id)
        identifier = body.metric_id
        item = body.model_dump(mode="json", exclude_none=True)
        item["type"] = {"atomic": "atomic", "ratio": "derived"}.get(body.model, "composite")
        with store.connect() as db:
            db.execute("LOCK TABLE metric_def IN SHARE ROW EXCLUSIVE MODE")
            catalog = {row["metric_id"]: load(row["payload"]) for row in db.execute("SELECT * FROM metric_def")}
            if update:
                if identifier not in catalog:
                    raise HTTPException(404, "指标不存在")
                require_admin(actor, catalog[identifier]["domain_id"])
                if catalog[identifier]["domain_id"] != body.domain_id:
                    raise HTTPException(422, "指标所属域不可修改")
            elif identifier in catalog:
                raise HTTPException(409, "指标 ID 已存在")
            catalog[identifier] = item
            try:
                validate_catalog(catalog)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            db.execute("INSERT INTO metric_def VALUES (%s,%s,%s) "
                       "ON CONFLICT(metric_id) DO UPDATE SET payload=excluded.payload",
                       (identifier, body.domain_id, dump(item)))
            store.audit(actor["username"], "metric.update" if update else "metric.create", identifier, item, db)
        return item

    @app.post("/api/metrics", status_code=201)
    def add_metric(body: MetricInput, actor=Depends(principal)):
        return write_metric(body, actor)

    @app.put("/api/metrics/{metric_id}")
    def update_metric(metric_id: str, body: MetricInput, actor=Depends(principal)):
        if metric_id != body.metric_id:
            raise HTTPException(422, "指标 ID 不可修改")
        return write_metric(body, actor, update=True)

    @app.delete("/api/metrics/{metric_id}", status_code=204)
    def delete_metric(metric_id: str, actor=Depends(principal)):
        require_admin(actor)
        with store.connect() as db:
            db.execute("LOCK TABLE metric_def IN SHARE ROW EXCLUSIVE MODE")
            catalog = {row["metric_id"]: load(row["payload"]) for row in db.execute("SELECT * FROM metric_def")}
            removed = catalog.pop(metric_id, None)
            if not removed:
                raise HTTPException(404, "指标不存在")
            require_admin(actor, removed["domain_id"])
            try:
                validate_catalog(catalog)
            except ValueError:
                raise HTTPException(409, "指标仍被其他公式引用") from None
            if db.execute("""
                SELECT 1 FROM analysis_session WHERE spec::jsonb->>'metric_id'=%s LIMIT 1
            """, (metric_id,)).fetchone():
                raise HTTPException(409, "指标仍被分析会话引用")
            db.execute("DELETE FROM metric_def WHERE metric_id=%s", (metric_id,))
            store.audit(actor["username"], "metric.delete", metric_id, db=db)

    @app.get("/api/admin/settings")
    def settings(actor=Depends(principal)):
        require_admin(actor)
        return {"runtime": RuntimeSettings.model_validate(store.setting("runtime", {})),
                "source": store.setting("source", DataSourceInput().model_dump())}

    def write_setting(actor, key, model):
        item = model.model_dump()
        with store.connect() as db:
            db.execute("INSERT INTO settings VALUES (%s,%s) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload", (key, dump(item)))
            store.audit(actor["username"], "settings.update", key, item, db)
        return item

    @app.put("/api/admin/domains/{domain_id}")
    def edit_business_line(domain_id: Domain, body: BusinessLineInput, actor=Depends(principal)):
        require_admin(actor, domain_id)
        return {"domain_id": domain_id, **write_setting(actor, f"business_line:{domain_id}", body)}

    @app.put("/api/admin/settings/runtime")
    def change_runtime(body: RuntimeSettings, actor=Depends(principal)):
        require_admin(actor)
        return write_setting(actor, "runtime", body)

    @app.put("/api/admin/settings/source")
    def change_source(body: DataSourceInput, actor=Depends(principal)):
        require_admin(actor)
        version = store.setting("data_version")
        candidate = Warehouse(body.model_dump())
        for table in TABLES.values():
            if not version or not int(candidate.query(
                f"SELECT count() AS n FROM {table} WHERE data_version={{version:String}}", {"version": version}
            )[0]["n"]):
                raise HTTPException(422, "数据源缺少可与只读沙箱副本配对的数据版本")
        return write_setting(actor, "source", body)

    @app.get("/api/admin/audit")
    def audit_log(limit: int = Query(50, ge=1, le=200), before: int | None = None,
                  actor=Depends(principal)):
        require_admin(actor)
        if set(actor["domains"]) != set(DOMAIN_LABELS):
            raise HTTPException(403, "全局审计需要全部指标域权限")
        if before is not None:
            rows = store.all("SELECT * FROM audit_log WHERE id<%s ORDER BY id DESC LIMIT %s", (before, limit))
        else:
            rows = store.all("SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (limit,))
        return [{**dict(row), "detail": load(row["detail"])} for row in rows]

    @app.post("/api/sandbox/run")
    async def replay_sandbox(audit_id: int, actor=Depends(principal)):
        require_admin(actor)
        row = store.one("""
            SELECT audit_log.*, analysis_session.domain_id FROM audit_log
            JOIN analysis_session ON analysis_session.id=audit_log.target
            WHERE audit_log.id=%s AND action='sandbox.verify'
        """, (audit_id,))
        if not row:
            raise HTTPException(404, "验证记录不存在")
        require_admin(actor, row["domain_id"])
        detail = load(row["detail"])
        config = RuntimeSettings.model_validate(store.setting("runtime", {}))
        result = await verify(detail["evidence"]["data_version"], detail["input"],
                              config.sandbox_timeout, config.sandbox_memory_mb)
        store.audit(actor["username"], "sandbox.replay", row["target"], {"audit_id": audit_id, "result": result})
        return result

    @app.get("/api/reports")
    def archive(domain_id: Domain | None = None, actor=Depends(principal)):
        authorize(actor, domain_id)
        allowed = [domain_id] if domain_id else actor["domains"]
        args = list(allowed)
        visibility = ""
        if actor["role"] != "admin":
            visibility = " AND (report.status='published' OR analysis_session.owner=%s)"
            args.append(actor["username"])
        rows = store.all(f"""
            SELECT report.*,analysis_session.domain_id,analysis_session.owner
            FROM report JOIN analysis_session ON analysis_session.id=report.session_id
            WHERE analysis_session.domain_id IN ({','.join('%s' for _ in allowed)}) {visibility}
            ORDER BY report.updated_at DESC LIMIT 200
        """, args)
        return [report_public(row) for row in rows]

    @app.get("/api/reports/{report_id}")
    def report_detail(report_id: str, actor=Depends(principal)):
        return report_public(report_for(report_id, actor), detail=True)

    @app.patch("/api/reports/{report_id}")
    def publish(report_id: str, body: ReportStatus, actor=Depends(principal)):
        report_for(report_id, actor, write=True)
        with store.connect() as db:
            db.execute("UPDATE report SET status=%s,updated_at=%s WHERE id=%s", (body.status, now(), report_id))
            store.audit(actor["username"], "report.status", report_id, body.model_dump(), db)
        return report_public(report_for(report_id, actor))

    @app.get("/api/reports/{report_id}/comments")
    def comments(report_id: str, actor=Depends(principal)):
        report_for(report_id, actor)
        rows = store.all("SELECT * FROM comment WHERE report_id=%s ORDER BY created_at", (report_id,))
        return [{**{key: row[key] for key in ("id", "author", "created_at")}, **load(row["payload"])} for row in rows]

    @app.post("/api/reports/{report_id}/comments", status_code=201)
    def add_comment(report_id: str, body: CommentInput, actor=Depends(principal)):
        row = report_for(report_id, actor)
        authorize(actor, roles={"admin", "analyst"})
        if body.section not in reports.TITLES:
            raise HTTPException(422, "报告章节不存在")
        for username in body.mentions:
            target = store.one("SELECT domains,role FROM user_account WHERE username=%s", (username,))
            if not target or row["domain_id"] not in load(target["domains"]):
                raise HTTPException(422, "被提及用户无此报告的指标域权限")
            if row["status"] != "published" and username != row["owner"] and target["role"] != "admin":
                raise HTTPException(422, "被提及用户无此草稿的访问权限")
        identifier, stamp = uuid4().hex, now()
        with store.connect() as db:
            db.execute("INSERT INTO comment VALUES (%s,%s,%s,%s,%s)",
                       (identifier, report_id, actor["username"], body.model_dump_json(), stamp))
            store.audit(actor["username"], "report.comment", report_id, {"comment_id": identifier}, db)
        return {"id": identifier, "author": actor["username"], "created_at": stamp, **body.model_dump()}

    @app.get("/api/subscriptions")
    def subscriptions(actor=Depends(principal)):
        rows = store.all("SELECT * FROM digest_subscription WHERE username=%s", (actor["username"],))
        return [dict(row) for row in rows if row["domain_id"] in actor["domains"]]

    @app.post("/api/subscriptions", status_code=201)
    def subscribe(body: SubscriptionInput, actor=Depends(principal)):
        authorize(actor, body.domain_id, {"manager"})
        stamp, identifier = now(), uuid4().hex
        with store.connect() as db:
            db.execute("LOCK TABLE digest_subscription IN SHARE ROW EXCLUSIVE MODE")
            row = db.execute("SELECT * FROM digest_subscription WHERE username=%s AND domain_id=%s",
                             (actor["username"], body.domain_id)).fetchone()
            if row and row["interval_days"] == body.interval_days:
                return dict(row)
            if row:
                db.execute("DELETE FROM digest_subscription WHERE id=%s", (row["id"],))
            db.execute("INSERT INTO digest_subscription VALUES (%s,%s,%s,%s,%s)",
                       (identifier, actor["username"], body.domain_id, body.interval_days, stamp))
            store.audit(actor["username"], "digest.subscribe", identifier, body.model_dump(), db)
        return {"id": identifier, **body.model_dump(), "created_at": stamp}

    @app.delete("/api/subscriptions/{subscription_id}", status_code=204)
    def unsubscribe(subscription_id: str, actor=Depends(principal)):
        with store.connect() as db:
            changed = db.execute("DELETE FROM digest_subscription WHERE id=%s AND username=%s",
                                 (subscription_id, actor["username"])).rowcount
            if not changed:
                raise HTTPException(404, "订阅不存在")
            store.audit(actor["username"], "digest.unsubscribe", subscription_id, db=db)

    @app.get("/api/digests")
    def digests(actor=Depends(principal)):
        authorize(actor, roles={"manager"})
        rows = store.all("""
            SELECT d.*,s.domain_id FROM digest AS d JOIN digest_subscription AS s ON d.subscription_id=s.id
            WHERE s.username=%s ORDER BY d.created_at DESC LIMIT 50
        """, (actor["username"],))
        published = {row["id"] for row in store.all("SELECT id FROM report WHERE status='published'")}
        return [{**dict(row), "payload": [item for item in load(row["payload"]) if item["id"] in published]}
                for row in rows if row["domain_id"] in actor["domains"]]
