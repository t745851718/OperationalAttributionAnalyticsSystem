import asyncio
from uuid import uuid4

import httpx
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from backend.main import create_app
from backend.models.store import Store, dump, now
from backend.services.auth import password_hash
from backend.services.jobs import Jobs


@pytest.fixture
def store():
    base = Store()
    schema = "test_jobs_" + uuid4().hex
    with base.connect() as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield Store(make_conninfo(base.dsn, options=f"-c search_path={schema}"))
    finally:
        with base.connect() as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def seed(store):
    store.setup()
    with store.connect() as db:
        timestamp = now()
        db.execute("INSERT INTO user_account VALUES (%s,%s,%s,%s)",
                   ("test", password_hash("test-password"), "analyst", dump(["ecommerce"])))
        db.execute("INSERT INTO analysis_session VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                   ("session", "test", "ecommerce", "{}", "test", "idle", None, timestamp, timestamp))


def test_persisted_job_recovery_and_cancellation(store):
    seed(store)
    jobs = Jobs(store, object())
    identifier = jobs.create("session", "test", "original", "op")
    assert jobs.create("session", "test", "original", "op") == identifier
    with store.connect() as db:
        db.execute("UPDATE job SET status='running' WHERE id=%s", (identifier,))

    async def recover():
        jobs.recover()
        job = store.one("SELECT * FROM job WHERE id=%s", (identifier,))
        assert jobs.cancel(job, "test")
        await jobs.close()

    asyncio.run(recover())
    async def replay():
        app = create_app(store, model=object())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/auth/login", json={"username": "test", "password": "test-password"})
                headers = {"Authorization": "Bearer " + response.json()["access_token"]}
                response = await client.get(f"/api/jobs/{identifier}/events", headers=headers)
                assert response.status_code == 200
                assert "已恢复，继续执行" in response.text
                assert "event: cancelled" in response.text
                assert (await client.get("/api/events?domain_id=fmcg", headers=headers)).status_code == 403

    asyncio.run(replay())


def test_retry_reuses_successful_checkpoints_and_preserves_previous_result(store):
    seed(store)
    jobs = Jobs(store, object())
    identifier = jobs.create("session", "test", "original")
    with store.connect() as db:
        db.execute("UPDATE job SET status='failed',context=%s,plan=%s,result=%s WHERE id=%s",
                   (dump({"inherited": {"metric_id": "gmv"}}), dump({"spec": "checkpoint"}),
                    dump({"verified": {"1": {"status": "supported"}, "2": {"status": "timeout"}}}), identifier))
    retry = jobs.retry(store.one("SELECT * FROM job WHERE id=%s", (identifier,)), "test")
    row = store.one("SELECT * FROM job WHERE id=%s", (retry,))
    assert row["context"] == '{"inherited":{"metric_id":"gmv"}}'
    assert row["plan"] == '{"spec":"checkpoint"}'
    assert row["result"] == '{"verified":{"1":{"status":"supported"}}}'
