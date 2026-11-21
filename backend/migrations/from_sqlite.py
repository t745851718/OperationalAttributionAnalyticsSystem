"""Import the legacy application database into an empty PostgreSQL schema."""

import argparse
import fcntl
import sqlite3
from contextlib import closing
from pathlib import Path

from psycopg import sql

from backend.config import RUNTIME
from backend.models.store import Store

# Parents precede children so all foreign keys are checked during import.
TABLES = (
    "user_account", "metric_def", "biz_event", "analysis_session", "job", "job_event",
    "evidence_review", "snapshot", "scenario", "report", "comment", "digest_subscription",
    "digest", "settings", "audit_log",
)


def migrate(source, store):
    uri = source.resolve(strict=True).as_uri() + "?mode=ro"
    counts = {}
    with source.with_suffix(".lock").open("a") as lock, store.scheduler_lock():
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("请先停止使用此 SQLite 文件的旧后端") from None
        store.setup()
        with closing(sqlite3.connect(uri, uri=True)) as old, store.connect() as db:
            old.execute("BEGIN")
            for name in TABLES:
                table = sql.Identifier(name)
                db.execute(sql.SQL("LOCK TABLE {} IN EXCLUSIVE MODE").format(table))
                if db.execute(sql.SQL("SELECT 1 FROM {} LIMIT 1").format(table)).fetchone():
                    raise ValueError(f"目标表 {name} 已有数据，请使用空库迁移")
                rows = old.execute(f'SELECT * FROM "{name}"')
                columns = sql.SQL(", ").join(sql.Identifier(col[0]) for col in rows.description)
                with db.cursor().copy(sql.SQL("COPY {} ({}) FROM STDIN").format(table, columns)) as copy:
                    for row in rows:
                        copy.write_row(row)
                counts[name] = db.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(table)).fetchone()["n"]
                if counts[name] != old.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]:
                    raise ValueError(f"{name} 行数校验失败")
            for name, column in (("job_event", "seq"), ("audit_log", "id")):
                high = old.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (name,)).fetchone()
                if high and high[0]:
                    db.execute("SELECT setval(pg_get_serial_sequence(%s,%s),%s)", (name, column, high[0]))
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?", default=RUNTIME / "app.sqlite3")
    for table, count in migrate(parser.parse_args().source, Store()).items():
        print(f"{table}: {count}")
