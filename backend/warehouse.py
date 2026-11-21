import json
import os
from datetime import date, timedelta

import httpx

from backend.catalog import DIMENSIONS, DOMAIN_LABELS, FACT_FIELDS

TABLES = {"ecommerce": "attribution_fact_orders", "fmcg": "attribution_fact_cost"}


class Warehouse:
    def __init__(self, source=None):
        source = source or {}
        self.url = source.get("url") or os.getenv("CLICKHOUSE_URL", "http://127.0.0.1:8123")
        self.database = source.get("database") or os.getenv("CLICKHOUSE_DATABASE", "test_db")
        self.auth = (os.getenv("CLICKHOUSE_USER", "admin"), os.getenv("CLICKHOUSE_PASSWORD", "admin123"))

    def execute(self, sql, parameters=None, data=None, readonly=False):
        query = {"database": self.database}
        if readonly:
            query["readonly"] = "1"
        query.update({f"param_{key}": value for key, value in (parameters or {}).items()})
        if data is None:
            body = sql
        else:
            query["query"] = sql
            body = "\n".join(json.dumps(row, ensure_ascii=False) for row in data).encode()
        with httpx.Client(timeout=15, trust_env=False) as client:
            response = client.post(self.url, params=query, content=body, auth=self.auth)
            response.raise_for_status()
            return response.text

    def query(self, sql, parameters=None):
        result = self.execute(sql + " FORMAT JSONEachRow", parameters, readonly=True)
        return [json.loads(line) for line in result.splitlines() if line.strip()]

    def seed(self, domain, rows, data_version):
        table = TABLES[domain]
        columns = ", ".join(f"{field} Float64" for field in FACT_FIELDS[domain])
        schema = f"""
            day Date, variant LowCardinality(String), channel LowCardinality(String),
            region LowCardinality(String), category LowCardinality(String),
            segment LowCardinality(String), {columns}, data_version LowCardinality(String)
        """
        self.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} ({schema})
            ENGINE = MergeTree ORDER BY (data_version, variant, day, channel, region, category, segment)
        """)
        if self.query(f"SELECT count() AS n FROM {table} WHERE data_version = {{version:String}}",
                      {"version": data_version})[0]["n"] not in (0, "0"):
            return
        self.execute(f"INSERT INTO {table} FORMAT JSONEachRow",
                     data=({**row, "data_version": data_version} for row in rows))

    def create_dimensions(self):
        for dim in DIMENSIONS:
            table = f"attribution_dim_{dim}"
            union = " UNION ALL ".join(f"SELECT {dim} FROM {table}" for table in TABLES.values())
            self.execute(f"CREATE VIEW IF NOT EXISTS {table} AS SELECT DISTINCT {dim} FROM ({union})")
        self.execute("""
            CREATE VIEW IF NOT EXISTS attribution_fact_traffic_funnel AS
            SELECT day, variant, channel, region, category, segment, visits, orders, stockouts, data_version
            FROM attribution_fact_orders
        """)
        self.execute("""
            CREATE VIEW IF NOT EXISTS attribution_fact_promotion AS
            SELECT day, variant, channel, region, category, segment, promo_orders, data_version
            FROM attribution_fact_orders
        """)

    def fact_query(self, domain, data_version, start, end, variant="actual", filters=None, group=()):
        if domain not in DOMAIN_LABELS or any(dim not in DIMENSIONS for dim in (*group, *(filters or {}))):
            raise ValueError("指标域或维度无效")
        fields = [*group, *(f"sum({key}) AS total_{key}" for key in FACT_FIELDS[domain])]
        where = ["day >= {start:Date}", "day <= {end:Date}", "variant = {variant:String}",
                 "data_version = {version:String}"]
        params = {"start": str(start), "end": str(end), "variant": variant, "version": data_version}
        for dim, value in (filters or {}).items():
            where.append(f"{dim} = {{{dim}:String}}")
            params[dim] = value
        sql = f"SELECT {', '.join(fields)}, count() AS row_count FROM {TABLES[domain]} WHERE " + " AND ".join(where)
        if group:
            keys = ", ".join(group)
            sql += f" GROUP BY {keys} ORDER BY {keys}"
        return {"sql": sql, "parameters": params}

    def facts(self, domain, data_version, start, end, variant="actual", filters=None, group=()):
        query = self.fact_query(domain, data_version, start, end, variant, filters, group)
        rows = self.query(query["sql"], query["parameters"])
        return [{**{key: row[key] for key in group}, **{
            key: float(row[f"total_{key}"]) for key in FACT_FIELDS[domain]
        }, "row_count": int(row["row_count"])} for row in rows if int(row["row_count"])]


def baseline_period(start, end, baseline):
    if baseline == "target":
        return start, end, "target"
    if baseline == "yoy":
        def last_year(day):
            try:
                return day.replace(year=day.year - 1)
            except ValueError:
                return date(day.year - 1, 2, 28)
        return last_year(start), last_year(end), "actual"
    duration = (end - start).days + 1
    return start - timedelta(days=duration), start - timedelta(days=1), "actual"
