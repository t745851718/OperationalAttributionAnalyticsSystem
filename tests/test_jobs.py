import asyncio

import httpx

from backend.auth import password_hash
from backend.jobs import Jobs
from backend.main import create_app
from backend.store import Store, dump, now


def seed(store):
    store.setup()
    with store.connect() as db:
        timestamp = now()
        db.execute("INSERT INTO user_account VALUES (?,?,?,?)",
                   ("test", password_hash("test-password"), "analyst", dump(["ecommerce"])))
        db.execute("INSERT INTO analysis_session VALUES (?,?,?,?,?,?,?,?,?)",
                   ("session", "test", "ecommerce", "{}", "test", "idle", None, timestamp, timestamp))


def test_persisted_job_recovery_and_cancellation(tmp_path):
    store = Store(tmp_path / "app.sqlite3")
    seed(store)
    jobs = Jobs(store, object())
    identifier = jobs.create("session", "test", "original", "op")
    assert jobs.create("session", "test", "original", "op") == identifier
    with store.connect() as db:
        db.execute("UPDATE job SET status='running' WHERE id=?", (identifier,))

    async def recover():
        jobs.recover()
        job = store.one("SELECT * FROM job WHERE id=?", (identifier,))
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


def test_retry_reuses_successful_checkpoints_and_preserves_previous_result(tmp_path):
    store = Store(tmp_path / "app.sqlite3")
    seed(store)
    jobs = Jobs(store, object())
    identifier = jobs.create("session", "test", "original")
    with store.connect() as db:
        db.execute("UPDATE job SET status='failed',context=?,plan=?,result=? WHERE id=?",
                   (dump({"inherited": {"metric_id": "gmv"}}), dump({"spec": "checkpoint"}),
                    dump({"verified": {"1": {"status": "supported"}, "2": {"status": "timeout"}}}), identifier))
    retry = jobs.retry(store.one("SELECT * FROM job WHERE id=?", (identifier,)), "test")
    row = store.one("SELECT * FROM job WHERE id=?", (retry,))
    assert row["context"] == '{"inherited":{"metric_id":"gmv"}}'
    assert row["plan"] == '{"spec":"checkpoint"}'
    assert row["result"] == '{"verified":{"1":{"status":"supported"}}}'
