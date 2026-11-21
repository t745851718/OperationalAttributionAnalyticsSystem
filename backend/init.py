import os
from pathlib import Path

import duckdb
import pandas as pd

from backend.auth import DEMO_USERS, password_hash
from backend.catalog import EVENTS, FACT_FIELDS, METRICS
from backend.config import RUNTIME
from backend.store import Store, dump, now
from backend.warehouse import Warehouse
from data.generators.demo import DATA_VERSION, generate


def initialize():
    store = Store()
    store.setup()
    warehouse = Warehouse()
    facts = {domain: list(generate(domain)) for domain in FACT_FIELDS}
    for domain, rows in facts.items():
        warehouse.seed(domain, rows, DATA_VERSION)
    warehouse.create_dimensions()
    destination = RUNTIME / f"{DATA_VERSION}.duckdb"
    temporary = Path(f"{destination}.{os.getpid()}.tmp")
    try:
        with duckdb.connect(str(temporary)) as db:
            for domain, rows in facts.items():
                columns = ", ".join(f"{key} DOUBLE" for key in FACT_FIELDS[domain])
                db.execute(f"""
                    CREATE TABLE {domain} (
                        day DATE, variant VARCHAR, channel VARCHAR, region VARCHAR,
                        category VARCHAR, segment VARCHAR, {columns}
                    )
                """)
                named = ["day", "variant", "channel", "region", "category", "segment", *FACT_FIELDS[domain]]
                db.register("fact_input", pd.DataFrame(rows, columns=named))
                db.execute(f"INSERT INTO {domain} SELECT * FROM fact_input")
                db.unregister("fact_input")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    with store.connect() as db:
        for username, (password, role, domains) in DEMO_USERS.items():
            db.execute("INSERT OR IGNORE INTO user_account VALUES (?,?,?,?)",
                       (username, password_hash(password), role, dump(domains)))
        for definition in METRICS:
            db.execute("INSERT OR IGNORE INTO metric_def VALUES (?,?,?)",
                       (definition["metric_id"], definition["domain_id"], dump(definition)))
        for event_id, domain, kind, title, start, end, scope, note in EVENTS:
            event = dict(event_id=event_id, domain_id=domain, type=kind, title=title,
                         start=start, end=end, scope=scope, impact_note=note, updated_at=now())
            db.execute("INSERT OR IGNORE INTO biz_event VALUES (?,?,?)", (event_id, domain, dump(event)))
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("data_version", dump(DATA_VERSION)))
    print(f"示例数据初始化成功 {DATA_VERSION}")


if __name__ == "__main__":
    initialize()
