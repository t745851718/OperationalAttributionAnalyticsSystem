"""Measure 100,000-row ClickHouse aggregation followed by decomposition."""

from time import perf_counter

from backend.services.analysis import demo_spec, drilldown
from backend.models.catalog import METRICS
from backend.models.metrics import decompose
from backend.models.warehouse import Warehouse

SQL = """
    SELECT
        concat('渠道 ', toString(number % 3)) AS channel,
        concat('区域 ', toString(intDiv(number, 3) % 3)) AS region,
        concat('品类 ', toString(intDiv(number, 9) % 3)) AS category,
        concat('客群 ', toString(intDiv(number, 27) % 2)) AS segment,
        sum(toFloat64(100 + number % 47) * {scale:Float64}) AS visits,
        sum(toFloat64(10 + number % 7) * {scale:Float64} * {conversion:Float64}) AS orders,
        sum(toFloat64(1600 + number % 481) * {scale:Float64}
            * {conversion:Float64} * {aov:Float64}) AS gmv,
        sum(toFloat64(number % 5)) AS stockouts,
        sum(toFloat64(number % 3)) AS promo_orders,
        count() AS row_count
    FROM numbers(100000)
    GROUP BY channel, region, category, segment
"""


class MeasuredWarehouse(Warehouse):
    def fact_query(self, domain, data_version, start, end, variant="actual", filters=None, group=()):
        factors = (1., 1., 1.) if start.day < 19 else (.8, .90, .96)
        return {"sql": SQL, "parameters": dict(zip(("scale", "conversion", "aov"), factors))}

    def facts(self, domain, data_version, start, end, variant="actual", filters=None, group=()):
        statement = self.fact_query(domain, data_version, start, end, variant, filters, group)
        rows = self.query(statement["sql"], statement["parameters"])
        return [{**row, "row_count": int(row["row_count"])} for row in rows]


def run():
    warehouse = MeasuredWarehouse()
    catalog = {item["metric_id"]: item for item in METRICS}
    spec = demo_spec("gmv")

    def total(rows):
        return {key: sum(row[key] for row in rows) for key in ("visits", "orders", "gmv")}

    start = perf_counter()
    before = total(warehouse.facts("ecommerce", "benchmark", spec.start.replace(day=15), spec.end))
    after = total(warehouse.facts("ecommerce", "benchmark", spec.start, spec.end))
    result = decompose("gmv", catalog, before, after)
    lmdi_seconds = perf_counter() - start
    start = perf_counter()
    pivot = drilldown(warehouse, "ecommerce", "benchmark", spec, catalog,
                      ["channel", "region", "category", "segment"])
    shapley_seconds = perf_counter() - start
    print(f"LMDI {lmdi_seconds:.3f}s · residual {result['residual']:.2g}")
    print(f"Shapley {shapley_seconds:.3f}s · {len(pivot['rows'])} buckets · residual {pivot['residual']:.2g}")
    if not result["conserved"] or max(lmdi_seconds, shapley_seconds) >= 3:
        raise SystemExit("benchmark failed")


if __name__ == "__main__":
    run()
