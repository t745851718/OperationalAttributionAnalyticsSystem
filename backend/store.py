import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

from backend.config import RUNTIME


def now():
    return datetime.now(UTC).isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def load(value):
    return json.loads(value) if value is not None else None


class Store:
    def __init__(self, path=RUNTIME / "app.sqlite3"):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def setup(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS user_account (
                    username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
                    role TEXT NOT NULL, domains TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metric_def (
                    metric_id TEXT PRIMARY KEY, domain_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS biz_event (
                    event_id TEXT PRIMARY KEY, domain_id TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analysis_session (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, domain_id TEXT NOT NULL,
                    spec TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS session_owner ON analysis_session(owner, updated_at);
                CREATE TABLE IF NOT EXISTS job (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES analysis_session(id),
                    question TEXT NOT NULL, request_key TEXT, status TEXT NOT NULL,
                    plan TEXT, result TEXT, context TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(session_id, request_key)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS active_job ON job(session_id)
                    WHERE status IN ('queued', 'running');
                CREATE TABLE IF NOT EXISTS job_event (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES job(id), type TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS job_event_stream ON job_event(job_id, seq);
                CREATE TABLE IF NOT EXISTS evidence_review (
                    job_id TEXT NOT NULL REFERENCES job(id), hypothesis_id TEXT NOT NULL,
                    author TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, hypothesis_id, author)
                );
                CREATE TABLE IF NOT EXISTS snapshot (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES analysis_session(id),
                    label TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scenario (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES analysis_session(id),
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS report (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES analysis_session(id),
                    version INTEGER NOT NULL, status TEXT NOT NULL, title TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(session_id, version)
                );
                CREATE TABLE IF NOT EXISTS comment (
                    id TEXT PRIMARY KEY, report_id TEXT NOT NULL REFERENCES report(id),
                    author TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS digest_subscription (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL, domain_id TEXT NOT NULL,
                    interval_days INTEGER NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(username, domain_id)
                );
                CREATE TABLE IF NOT EXISTS digest (
                    id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL REFERENCES digest_subscription(id) ON DELETE CASCADE,
                    period INTEGER NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(subscription_id, period)
                );
                CREATE TABLE IF NOT EXISTS settings (
                    name TEXT PRIMARY KEY, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL,
                    action TEXT NOT NULL, target TEXT NOT NULL,
                    detail TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            columns = {column["name"] for column in db.execute("PRAGMA table_info(job)")}
            if "context" not in columns:
                db.execute("ALTER TABLE job ADD COLUMN context TEXT")

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
        sql = "INSERT INTO audit_log(username,action,target,detail,created_at) VALUES (?,?,?,?,?)"
        values = (username, action, target, dump(detail or {}), now())
        if db is not None:
            db.execute(sql, values)
        else:
            self.write(sql, values)

    def setting(self, name, default=None):
        row = self.one("SELECT payload FROM settings WHERE name = ?", (name,))
        return load(row["payload"]) if row else default

    def catalog(self):
        return {row["metric_id"]: load(row["payload"]) for row in self.all("SELECT * FROM metric_def")}
