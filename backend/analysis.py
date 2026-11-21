import asyncio
import math
from collections import defaultdict
from datetime import date, timedelta
from itertools import permutations
from random import Random

import numpy as np

from backend.catalog import DEMO_END, DEMO_START, DIMENSIONS, FACT_FIELDS
from backend.metrics import Evaluator, decompose, divide, shapley
from backend.model import ModelError, object_schema
from backend.sandbox_worker import TEMPLATES
from backend.schemas import AnalysisSpec, Planned
from backend.warehouse import baseline_period

DRIVER_ACTIONS = {
    "visits": ("调整高转化渠道预算与投放节奏", "投放经理", 7),
    "conversion": ("修复低转化渠道的落地页和转化路径", "增长运营负责人", 7),
    "aov": ("补齐缺货高价款并恢复高价值商品曝光", "品类运营负责人", 10),
    "materials": ("重谈采购价并调整原料采购组合", "采购负责人", 21),
    "commission": ("重新协商佣金条款并优化渠道组合", "渠道负责人", 14),
    "logistics": ("优化承运商与履约路线", "物流负责人", 14),
}


class AnalysisError(ValueError):
    pass


def demo_spec(metric_id, baseline="mom"):
    return AnalysisSpec(metric_id=metric_id, start=DEMO_START, end=DEMO_END, baseline=baseline)


def window_rows(warehouse, domain, version, spec, group=()):
    baseline_start, baseline_end, variant = baseline_period(spec.start, spec.end, spec.baseline)
    args = (domain, version)
    current = warehouse.facts(*args, spec.start, spec.end, filters=spec.filters, group=group)
    baseline = warehouse.facts(*args, baseline_start, baseline_end, variant, spec.filters, group)
    return baseline, current


def lineage(warehouse, domain, version, spec, group=()):
    start, end, variant = baseline_period(spec.start, spec.end, spec.baseline)
    return {
        "baseline": warehouse.fact_query(domain, version, start, end, variant, spec.filters, group),
        "current": warehouse.fact_query(domain, version, spec.start, spec.end, "actual", spec.filters, group),
    }


def get_decomposition(warehouse, domain, version, spec, catalog):
    old, new = window_rows(warehouse, domain, version, spec)
    if not old or not new:
        raise AnalysisError("基期或现期没有数据，请调整日期或切片")
    result = decompose(spec.metric_id, catalog, old[0], new[0])
    result.update(unit=catalog[spec.metric_id]["unit"], source="ClickHouse",
                  formula=catalog[spec.metric_id]["formula"], lineage=lineage(warehouse, domain, version, spec),
                  current_period=[str(spec.start), str(spec.end)],
                  baseline_period=[str(item) for item in baseline_period(spec.start, spec.end, spec.baseline)[:2]])
    return result


def drilldown(warehouse, domain, version, spec, catalog, dimensions):
    before, after = window_rows(warehouse, domain, version, spec, dimensions)
    if not before or not after:
        raise AnalysisError("基期或现期没有下钻数据")
    base_start = baseline_period(spec.start, spec.end, spec.baseline)[0]
    fields = FACT_FIELDS[domain]
    empty = dict.fromkeys(fields, 0.0)

    def index(rows, origin):
        return {
            tuple((date.fromisoformat(row[dim]) - origin).days if dim == "day" else row[dim]
                  for dim in dimensions): row for row in rows
        }

    old, new = index(before, base_start), index(after, spec.start)
    keys = sorted(old.keys() | new.keys())
    old_total = {field: math.fsum(row[field] for row in old.values()) for field in fields}
    new_total = {field: math.fsum(row[field] for row in new.values()) for field in fields}
    changes = [[new.get(key, empty)[field] - old.get(key, empty)[field] for field in fields] for key in keys]

    def value(facts):
        return Evaluator(catalog, facts).value(spec.metric_id)

    initial, final = value(old_total), value(new_total)
    if initial is None or final is None:
        raise AnalysisError("指标分母为零，无法进行贡献拆解")
    delta = final - initial
    contributions = [0.0] * len(keys)
    if catalog[spec.metric_id]["model"] == "atomic":
        factor = catalog[spec.metric_id].get("source_field", {"sales": "gmv"}.get(spec.metric_id, spec.metric_id))
        contributions = [change[fields.index(factor)] for change in changes]
        method = "difference"
    else:
        rng = Random(4455)
        size = len(keys)
        if size <= 4:
            orders = permutations(range(size))
            method = "exact_bucket_shapley"
        else:
            orders = (rng.sample(range(size), size) for _ in range(min(96, max(16, 8000 // size))))
            method = "sampled_bucket_shapley"
        for count, order in enumerate(orders, 1):
            totals, previous = old_total.copy(), initial
            for position, i in enumerate(order, 1):
                for field, change in zip(fields, changes[i]):
                    totals[field] += change
                next_value = final if position == size else value(totals)
                # A coalition with no denominator receives zero until a valid total reappears.
                next_value = next_value if next_value is not None else 0.0
                contributions[i] += next_value - previous
                previous = next_value
        contributions = [contribution / count for contribution in contributions]
    rows = []
    for key, contribution in zip(keys, contributions):
        keys_display = {dim: str(spec.start + timedelta(days=part)) if dim == "day" else part
                        for dim, part in zip(dimensions, key)}
        rows.append(dict(dimensions=keys_display, baseline=value(old[key]) if key in old else None,
                         current=value(new[key]) if key in new else None, contribution=contribution,
                         contribution_rate=divide(contribution, delta),
                         baseline_rows=old.get(key, {}).get("row_count", 0),
                         current_rows=new.get(key, {}).get("row_count", 0)))
    rows.sort(key=lambda row: abs(row["contribution"]), reverse=True)

    def concentration(mask):
        groups = defaultdict(float)
        for row in rows:
            key = tuple(row["dimensions"][dim] for i, dim in enumerate(dimensions) if mask & (1 << i))
            groups[key] += row["contribution"]
        return math.fsum(abs(group) for group in groups.values())

    breakdown = shapley(len(dimensions), concentration)
    concentration_delta = math.fsum(breakdown)
    return dict(dimensions=dimensions, rows=rows, delta=delta, method=method,
                lineage=lineage(warehouse, domain, version, spec, dimensions),
                dimension_method="exact_shapley" if len(dimensions) <= 4 else "sampled_shapley",
                dimension_importance=[dict(dimension=dim, concentration=lift,
                                           share=divide(lift, concentration_delta))
                                      for dim, lift in zip(dimensions, breakdown)],
                residual=delta - math.fsum(contributions))


async def plan(model, warehouse, catalog, domain, version, question, inherited, max_tokens):
    allowed = {key: item["name"] for key, item in catalog.items() if item["domain_id"] == domain}
    template_info = {key: definition[0] for key, definition in TEMPLATES[domain].items()}
    selectable = tuple(dim for dim in DIMENSIONS if dim != "day")
    members = await asyncio.to_thread(
        warehouse.facts, domain, version, DEMO_START, DEMO_END, group=selectable,
    )
    filters_catalog = {dim: sorted({row[dim] for row in members}) for dim in selectable}
    payload = {
        "question": question, "inherited": inherited.model_dump(mode="json"),
        "metrics": allowed, "hypothesis_templates": template_info,
        "dimensions": DIMENSIONS, "allowed_filters": filters_catalog,
    }
    def choice(values):
        return {"type": "string", "enum": list(values)}

    scopes = object_schema({dim: choice(values) for dim, values in filters_catalog.items()}, required=[])
    constraints = object_schema({
        "spec": object_schema({
            "metric_id": choice(allowed), "start": {"type": "string"}, "end": {"type": "string"},
            "baseline": choice(("mom", "yoy", "target")), "filters": scopes,
            "dimensions": {"type": "array", "items": choice(DIMENSIONS), "minItems": 1, "maxItems": 5},
        }),
        "hypotheses": {"type": "array", "minItems": 3, "maxItems": 5, "items": object_schema({
            "template": choice(template_info), "scope": scopes,
        })},
    })
    answer = await model.json_request(
        "你是经营数据分析调度器。输出一个 JSON 对象，字段 spec 和 hypotheses。"
        "spec 的全部字段为 metric_id,start,end,baseline,filters,dimensions。"
        "只有用户明确修改时才覆盖继承的指标、日期、基期或切片，支持明确清除切片。"
        "baseline 可为 mom、yoy、target。dimensions 由下钻问题决定。"
        "hypotheses 为 3 到 5 个对象，字段 template 和 scope，"
        "只可使用给定模板和维度取值。scope 可为空，且不能和 spec.filters 冲突。"
        "日期使用 YYYY-MM-DD，假设的 template 和 scope 组合不得重复。"
        "从备选假设中包含可能被排除的假设，禁止伪造统计结果。只返回 JSON。",
        payload, max_tokens, schema=constraints,
    )
    try:
        parsed = Planned.model_validate(answer)
    except ValueError as exc:
        fields = ["/".join(map(str, error["loc"])) for error in exc.errors()]
        raise ModelError(f"模型返回的分析计划字段无效（{', '.join(fields[:4])}）") from None
    if parsed.spec.metric_id not in allowed:
        raise ModelError("模型返回了越域或未知指标")
    if any(item.template not in template_info for item in parsed.hypotheses):
        raise ModelError("模型选择了未知检验模板")
    used = set()
    for item in parsed.hypotheses:
        selection = (item.template, tuple(sorted(item.scope.items())))
        if selection in used:
            raise ModelError("模型返回了重复假设")
        used.add(selection)
        for dim, value in item.scope.items():
            if dim in parsed.spec.filters and parsed.spec.filters[dim] != value:
                raise ModelError("假设范围和分析切片冲突")
    for filters in (parsed.spec.filters, *(item.scope for item in parsed.hypotheses)):
        if any(value not in filters_catalog.get(dim, ()) for dim, value in filters.items()):
            raise ModelError("模型返回了未知维度值")
    return parsed


def event_matches(events, spec, drill):
    rows = drill["rows"]
    matches = []
    for event in events:
        start, end = date.fromisoformat(event["start"]), date.fromisoformat(event["end"])
        distance = max(0, (start - spec.end).days, (spec.start - end).days)
        if distance > 3:
            continue
        scope = event["scope"]
        if any(dim in scope and value not in scope[dim] for dim, value in spec.filters.items()):
            continue
        evidence = [row for row in rows if any(row["dimensions"].get(dim) in values
                                              for dim, values in scope.items())]
        compared = any(dim in drill["dimensions"] for dim in scope)
        if compared and not evidence and not any(dim in scope for dim in spec.filters):
            continue
        overlap = 1 if not scope or evidence or any(dim in scope for dim in spec.filters) else .5
        score = (1 - distance / 4) * overlap
        if score >= .25:
            matches.append({**event, "score": score, "distance_days": distance,
                            "after_window": start > spec.end,
                            "status": "candidate_explanation",
                            "linked_slices": [row["dimensions"] for row in evidence[:3]]})
    return sorted(matches, key=lambda item: item["score"], reverse=True)


def drivers(metric_id, catalog, facts):
    if catalog[metric_id]["domain_id"] == "ecommerce":
        return {key: Evaluator(catalog, facts).value(key) for key in ("visits", "conversion", "aov")
                if key in catalog}
    revenue = facts.get("revenue", 0)
    return {key: divide(facts.get(key, 0), revenue) for key in ("materials", "logistics", "commission")}


def training_data(warehouse, domain, version, spec):
    return warehouse.facts(domain, version, spec.start - timedelta(days=84),
                           spec.start - timedelta(days=1), filters=spec.filters, group=("day",))


def simulation(metric_id, catalog, history, current, changes):
    current_value = Evaluator(catalog, current).value(metric_id)
    allowed = drivers(metric_id, catalog, current)
    if any(key not in allowed for key in changes):
        raise AnalysisError("包含不可推演的驱动因子")
    histories = []
    keys = list(allowed)
    for row in history:
        value = Evaluator(catalog, row).value(metric_id)
        features = drivers(metric_id, catalog, row)
        if value and value > 0 and all(features[key] and features[key] > 0 for key in keys):
            histories.append([*(math.log(features[key]) for key in keys), math.log(value)])
    if len(histories) < 21 or current_value is None or current_value <= 0:
        raise AnalysisError("历史样本不足或指标非正，无法估计弹性")
    observations = np.diff(np.array(histories), axis=0)
    x, y = observations[:, :-1], observations[:, -1]
    x, y = x - x.mean(axis=0), y - y.mean()
    if np.linalg.matrix_rank(x) < len(keys):
        raise AnalysisError("历史驱动因子共线，无法估计弹性")
    coefficients = np.linalg.lstsq(x, y, rcond=None)[0]
    change = np.array([math.log1p(changes.get(key, 0)) for key in keys])
    forecast = float(current_value * np.exp(change @ coefficients))
    rng = np.random.default_rng(202506)
    resampled = np.array([np.linalg.lstsq(x[labels], y[labels], rcond=None)[0]
                          for labels in rng.integers(len(y), size=(1000, len(y)))])
    samples = current_value * np.exp(resampled @ change)
    low, high = np.quantile(samples, [.1, .9])
    curves = {}
    for key in changes:
        index = keys.index(key)
        points = []
        for adjustment in (-.20, -.10, 0, .10, .20):
            parameters = change.copy()
            parameters[index] = math.log1p(adjustment)
            points.append({"change": adjustment, "estimate": float(current_value * np.exp(parameters @ coefficients))})
        curves[key] = points
    if not np.isfinite(samples).all() or not math.isfinite(forecast):
        raise AnalysisError("历史弹性不稳定，无法生成有限的预测值")
    delta = forecast - current_value
    unit = catalog[metric_id]["unit"]
    impact = delta if unit == "CNY" else delta * current.get("revenue", 0) if unit == "ratio" else None
    return dict(current=current_value, estimate=forecast, interval_80=[float(low), float(high)],
                changes=changes, elasticities=dict(zip(keys, map(float, coefficients))), delta=delta,
                delta_rate=delta / current_value, expected_impact_cny=impact,
                samples=len(y), bootstrap_iterations=1000, sensitivity_curves=curves)


def actions(metric_id, catalog, history, current, decomposition):
    items = []
    for factor in sorted(decomposition["factors"], key=lambda row: row["contribution"]):
        key = factor["metric_id"]
        if factor["contribution"] >= 0 or key not in DRIVER_ACTIONS:
            continue
        action, owner, days = DRIVER_ACTIONS[key]
        change = -.05 if key in {"materials", "commission", "logistics"} else .05
        try:
            result = simulation(metric_id, catalog, history, current, {key: change})
        except AnalysisError:
            continue
        if result["expected_impact_cny"] is None or result["expected_impact_cny"] <= 0:
            continue
        items.append(dict(priority=len(items) + 1, driver=key, action=action, owner=owner,
                          recovery_days=days, contribution=factor["contribution"],
                          expected_recovery_cny=result["expected_impact_cny"], modeled_change=change))
    return items
