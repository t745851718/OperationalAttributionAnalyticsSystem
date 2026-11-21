import asyncio
import logging
from datetime import UTC, datetime
from uuid import uuid4

from backend.models.store import dump, load

logger = logging.getLogger(__name__)


def refresh_digests(store):
    timestamp = datetime.now(UTC)
    with store.connect() as db:
        db.execute("LOCK TABLE digest_subscription IN SHARE MODE")
        subscriptions = db.execute("""
            SELECT s.* FROM digest_subscription AS s JOIN user_account AS u
            ON u.username=s.username WHERE u.role='manager'
        """).fetchall()
        for row in subscriptions:
            start = datetime.fromisoformat(row["created_at"])
            span = row["interval_days"] * 86400
            period = int((timestamp - start).total_seconds() // span)
            valid = db.execute("""
                SELECT 1 FROM user_account AS u, jsonb_array_elements_text(u.domains::jsonb) AS d(value)
                WHERE u.username=%s AND d.value=%s
            """, (row["username"], row["domain_id"])).fetchone()
            if not valid or db.execute("SELECT 1 FROM digest WHERE subscription_id=%s AND period=%s",
                                       (row["id"], period)).fetchone():
                continue
            cutoff = datetime.fromtimestamp(timestamp.timestamp() - span, UTC).isoformat()
            items = db.execute("""
                SELECT r.id,r.title,r.version,r.updated_at,r.payload FROM report AS r
                JOIN analysis_session AS a ON a.id=r.session_id
                WHERE r.status='published' AND a.domain_id=%s AND r.updated_at>=%s
                ORDER BY r.updated_at DESC LIMIT 20
            """, (row["domain_id"], cutoff)).fetchall()
            if not items:
                continue
            payload = [{"id": item["id"], "title": item["title"], "version": item["version"],
                        "updated_at": item["updated_at"], "summary": load(item["payload"])["analysis"]["summary"]}
                       for item in items]
            db.execute("INSERT INTO digest VALUES (%s,%s,%s,%s,%s) ON CONFLICT(subscription_id,period) DO NOTHING",
                       (uuid4().hex, row["id"], period, dump(payload), timestamp.isoformat()))


async def digest_loop(store):
    while True:
        try:
            await asyncio.to_thread(refresh_digests, store)
        except Exception:
            logger.exception("Digest scheduling failed")
        await asyncio.sleep(60)
