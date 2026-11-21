import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from backend.config import postgres_dsn


def now():
    return datetime.now(UTC).isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def load(value):
    return json.loads(value) if value is not None else None


class Store:
    def __init__(self, dsn=None):
        self.dsn = dsn or postgres_dsn()

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    @contextmanager
    def scheduler_lock(self):
        # A single scheduler owns job recovery and the digest loop per schema.
        with psycopg.connect(self.dsn, autocommit=True) as db:
            acquired, = db.execute(
                "SELECT pg_try_advisory_lock(741532, current_schema()::regnamespace::int)"
            ).fetchone()
            if not acquired:
                raise RuntimeError("此数据库已有后端任务调度进程")
            yield

    def setup(self):
        schema = Path(__file__).with_name("schema.sql").read_text()
        with self.connect() as db:
            db.execute(schema)

    def one(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        with self.connect() as db:
            return db.execute(sql, args).fetchall()

    def write(self, sql, args=()):
        with self.connect() as db:
            db.execute(sql, args)

    def audit(self, username, action, target, detail=None, db=None):
        sql = "INSERT INTO audit_log(username,action,target,detail,created_at) VALUES (%s,%s,%s,%s,%s)"
        values = (username, action, target, dump(detail or {}), now())
        if db is not None:
            db.execute(sql, values)
        else:
            self.write(sql, values)

    def setting(self, name, default=None):
        row = self.one("SELECT payload FROM settings WHERE name = %s", (name,))
        return load(row["payload"]) if row else default

    def catalog(self):
        return {row["metric_id"]: load(row["payload"]) for row in self.all("SELECT * FROM metric_def")}
