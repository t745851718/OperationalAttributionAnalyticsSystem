"""Entry point for the isolated read-only verification worker."""

import json
import resource
import sys
from collections import defaultdict
from datetime import date

import duckdb
import numpy as np
from scipy import stats

from backend.catalog import DIMENSIONS, FACT_FIELDS

TEMPLATES = {
    "ecommerce": {
        "traffic_drop": ("流量减少", "visits", None, -1),
        "conversion_drop": ("转化效率下降", "orders", "visits", -1),
        "channel_mix": ("低转化渠道占比上升", "visits", "share", 1),
        "stockout_aov": ("断货品类客单价降低", "gmv", "orders", -1),
        "stockout_rate": ("断货访客占比上升", "stockouts", "visits", 1),
        "promo_increase": ("促销订单占比上升", "promo_orders", "orders", 1),
        "aov_drop": ("客单价降低", "gmv", "orders", -1),
    },
    "fmcg": {
        "materials_rate": ("原料成本率上升", "materials", "revenue", 1),
        "commission_rate": ("佣金费率上升", "commission", "revenue", 1),
        "logistics_rate": ("物流成本率上升", "logistics", "revenue", 1),
        "price_drop": ("销售均价下降", "revenue", "units", -1),
        "units_drop": ("销量减少", "units", None, -1),
    },
}


def scope_filter(row, scope):
    return all(row[key] == value for key, value in scope.items())


def get_query(domain, template, filters):
    _, numerator, denominator, _ = TEMPLATES[domain][template]
    if any(dim not in DIMENSIONS or dim == "day" for dim in filters):
        raise ValueError("无效切片")
    if numerator not in FACT_FIELDS[domain] or denominator not in {*FACT_FIELDS[domain], "share", None}:
        raise ValueError("无效检验口径")
    keys = [dim for dim in DIMENSIONS if dim != "day"]
    select = [f"SUM({numerator}) AS numerator",
              f"SUM({denominator}) AS denominator" if denominator not in (None, "share") else "1 AS denominator"]
    predicates = ["day BETWEEN ? AND ?", "variant = ?", *(f"{key} = ?" for key in filters)]
    group = ", ".join(["day", *keys])
    return (f"SELECT {group}, {', '.join(select)} FROM {domain} WHERE "
            + " AND ".join(predicates) + f" GROUP BY {group} ORDER BY {group}")


def _load(db, sql, window, filters):
    cursor = db.execute(sql, [*window, *filters.values()])
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def evaluate(db, request):
    domain, template = request["domain"], request["template"]
    filters, scope = request["filters"], request["scope"]
    _, _, denominator, direction = TEMPLATES[domain][template]
    query = get_query(domain, template, filters)
    all_periods = [_load(db, query, request[key], filters) for key in ("baseline", "current", "history")]
    if any(key == "day" or key not in DIMENSIONS for key in scope):
        raise ValueError("无效检验范围")
    subgroup = [dim for dim in DIMENSIONS if dim not in {"day", *filters, *scope}]

    def series(rows, strata=()):
        totals = defaultdict(float)
        selected = defaultdict(lambda: [0.0, 0.0, 0])
        for row in rows:
            key = (row["day"], *(row[dim] for dim in strata))
            totals[key] += row["numerator"]
            if scope_filter(row, scope):
                aggregate = selected[key]
                aggregate[0] += row["numerator"]
                aggregate[1] += row["denominator"]
                aggregate[2] += 1
        values = {}
        for key, (top, bottom, count) in selected.items():
            divisor = totals[key] if denominator == "share" else count if denominator is None else bottom
            if divisor:
                values[key] = top / divisor
        return values

    baseline, current, history = (series(rows) for rows in all_periods)
    before, after = list(baseline.values()), list(current.values())
    result = {"p_value": None, "effect_size": None, "confidence": None, "status": "insufficient_data",
              "baseline_n": len(before), "current_n": len(after), "baseline_mean": None,
              "current_mean": None, "strata_consistency": None, "partial_correlation": None,
              "timing_consistent": None, "reasons": []}
    if min(len(before), len(after)) < 3 or len(history) < 14:
        result["reasons"].append("统计窗口或参考历史样本不足")
        return result

    # Compare day-level samples and check for a reversal among comparable strata.
    a, b = float(np.mean(before)), float(np.mean(after))
    difference = b - a
    if np.var(before) or np.var(after):
        p_value = float(stats.ttest_ind(after, before, equal_var=False).pvalue)
    else:
        p_value = 0.0 if difference else 1.0
    std = float(np.sqrt((np.var(before, ddof=1) + np.var(after, ddof=1)) / 2))
    effect = difference / std if std else float(np.sign(difference)) * (8.0 if difference else 0)
    strata_means = []
    for rows in all_periods[:2]:
        grouped = defaultdict(list)
        for key, value in series(rows, subgroup).items():
            grouped[key[1:]].append(value)
        strata_means.append({key: float(np.mean(values)) for key, values in grouped.items()})
    shared = strata_means[0].keys() & strata_means[1].keys()
    consistency = (sum(direction * (strata_means[1][key] - strata_means[0][key]) > 0 for key in shared)
                   / len(shared)) if shared else None

    # Partial correlation of outcome with the incident indicator, controlling trend and weekday.
    chronological = sorted([(*key, value, 0) for key, value in history.items()]
                           + [(*key, value, 1) for key, value in current.items()])
    days = [day for day, _, _ in chronological]
    control = np.asarray([[1, (day - days[0]).days, *(int(day.weekday() == i) for i in range(6))]
                          for day in days])
    observations = np.asarray([[value, flag] for _, value, flag in chronological])
    residuals = observations - control @ np.linalg.lstsq(control, observations, rcond=None)[0]
    partial = float(np.corrcoef(residuals.T)[0, 1]) if np.std(residuals[:, 0]) > 1e-10 else 0.0
    start = date.fromisoformat(request["current"][0])
    recent = [value for (day,), value in history.items() if 0 < (start - day).days <= 4]
    historical_scale = max(float(np.std(list(history.values()))), abs(a) * .015, 1e-12)
    prior_shift = direction * (float(np.mean(recent)) - float(np.median(list(history.values())))) if recent else 0
    timing = bool(prior_shift < max(historical_scale * 2, abs(difference) * .65))
    coverage = max(0.0, min(1.0, request["coverage"]))
    confidence = .48 * (1 - p_value) + .32 * min(abs(effect) / 2.5, 1) + .20 * coverage
    if direction * difference <= 0:
        confidence *= .20
        result["reasons"].append("实测方向与假设相反")
    if consistency is not None and consistency < .55:
        confidence *= .50
        result["reasons"].append("主要分层方向不一致，可能存在辛普森悖论")
    if direction * partial < .08:
        confidence *= .65
        result["reasons"].append("控制趋势与星期效应后，关联偏弱或反向")
    if not timing:
        confidence *= .70
        result["reasons"].append("窗口开始之前已观察到同方向变化")
    result.update(baseline_mean=a, current_mean=b, difference=difference, effect_size=effect,
                  p_value=p_value, confidence=confidence, strata_consistency=consistency,
                  partial_correlation=partial, timing_consistent=timing,
                  status="supported" if confidence >= request["threshold"] else "excluded")
    return result


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    request = json.loads(sys.stdin.read(256_000))
    with duckdb.connect("/warehouse/demo.duckdb", read_only=True,
                        config={"threads": 1, "memory_limit": "160MB", "enable_external_access": False}) as db:
        print(json.dumps(evaluate(db, request), ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
