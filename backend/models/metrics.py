import ast
import math
from collections import Counter
from functools import cache
from itertools import permutations
from random import Random

from backend.models.catalog import FACT_FIELDS

OPERATORS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
MUL = (ast.Mult, ast.Div)
ADD = (ast.Add, ast.Sub)


@cache
def parse(formula):
    if len(formula) > 300:
        raise ValueError("公式最长 300 字符")
    try:
        node = ast.parse(formula, mode="eval").body
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("公式格式无效") from exc
    if any(not isinstance(part, (ast.BinOp, ast.Name, ast.Load, *OPERATORS)) for part in ast.walk(node)):
        raise ValueError("公式仅支持指标引用和四则运算")
    return node


def divide(left, right):
    return left / right if right else None


def calculate(op, left, right):
    if left is None or right is None:
        return None
    return {"+": lambda: left + right, "-": lambda: left - right,
            "*": lambda: left * right, "/": lambda: divide(left, right)}[op]()


def unit_map(unit):
    if unit in {"ratio", "1", "%"}:
        return Counter()
    numerator, separator, denominator = unit.partition("/")
    result = Counter(numerator.split("*"))
    if separator:
        result.subtract(denominator.split("*"))
    return Counter({key: value for key, value in result.items() if value})


def validate_catalog(catalog):
    @cache
    def visit(metric_id, route=()):
        if metric_id in route:
            raise ValueError("检测到循环依赖")
        if metric_id not in catalog:
            raise ValueError(f"引用了不存在的指标 {metric_id}")
        item = catalog[metric_id]
        domain = item["domain_id"]
        declared = unit_map(item["unit"])
        if item["model"] == "atomic":
            source = item.get("source_field", {"sales": "gmv"}.get(metric_id, metric_id))
            if item["formula"] or source not in FACT_FIELDS[domain]:
                raise ValueError("原子指标必须绑定有效事实字段")
            source_unit = {
                "visits": "visit", "stockouts": "visit", "orders": "order",
                "promo_orders": "order", "units": "unit",
            }.get(source, "CNY")
            if declared != unit_map(source_unit):
                raise ValueError("声明单位与事实字段单位不一致")
            return declared
        node = parse(item["formula"])

        def expression_units(expression):
            if isinstance(expression, ast.Name):
                reference = catalog.get(expression.id)
                if not reference or reference["domain_id"] != domain:
                    raise ValueError("指标引用必须存在且属于同一指标域")
                return visit(expression.id, (*route, metric_id))
            left, right = expression_units(expression.left), expression_units(expression.right)
            if isinstance(expression.op, ADD):
                if left != right:
                    raise ValueError("加减法两侧的单位必须一致")
                return left
            result = left.copy()
            (result.update if isinstance(expression.op, ast.Mult) else result.subtract)(right)
            return Counter({key: value for key, value in result.items() if value})

        if expression_units(node) != declared:
            raise ValueError("公式推导单位与声明单位不一致")
        expected = {"add": ADD, "mul": MUL, "ratio": (ast.Div,)}[item["model"]]
        if isinstance(node, ast.BinOp) and not isinstance(node.op, expected):
            raise ValueError("公式运算与模型类型不一致")
        return declared

    for key in catalog:
        visit(key)


class Evaluator:
    def __init__(self, catalog, facts):
        self.catalog = catalog
        self.facts = facts

    def value(self, name):
        definition = self.catalog[name]
        if definition["model"] == "atomic":
            source = definition.get("source_field", {"sales": "gmv"}.get(name, name))
            return self.facts.get(source, 0.0)
        return self.expression(parse(definition["formula"]))

    def expression(self, node):
        if isinstance(node, ast.Name):
            return self.value(node.id)
        return calculate(OPERATORS[type(node.op)], self.expression(node.left), self.expression(node.right))


def flatten(node, operators, sign=1):
    if isinstance(node, ast.BinOp) and isinstance(node.op, operators):
        right_sign = -sign if isinstance(node.op, (ast.Sub, ast.Div)) else sign
        return [*flatten(node.left, operators, sign), *flatten(node.right, operators, right_sign)]
    return [(node, sign)]


def references(node):
    if isinstance(node, ast.Name):
        return [node.id]
    return [*references(node.left), *references(node.right)]


def label(node):
    return node.id if isinstance(node, ast.Name) else ast.unparse(node)


def log_ratio(current, baseline):
    relative = (current - baseline) / baseline
    return math.log1p(relative) if abs(relative) < .5 else math.log(current) - math.log(baseline)


def log_mean(baseline, current):
    return baseline if current == baseline else (current - baseline) / log_ratio(current, baseline)


def lmdi(before, after, signs, delta):
    epsilon = 1e-9
    smoothed = any(value == 0 for value in (*before, *after))
    previous = [epsilon if value == 0 else value for value in before]
    latest = [epsilon if value == 0 else value for value in after]
    baseline = math.prod(value ** power for value, power in zip(previous, signs))
    current = math.prod(value ** power for value, power in zip(latest, signs))
    contributions = [log_mean(baseline, current) * power * log_ratio(b, a)
                     for a, b, power in zip(previous, latest, signs)]
    remainder = delta - math.fsum(contributions)
    if contributions:
        index = max(range(len(contributions)), key=lambda i: abs(contributions[i]))
        contributions[index] += remainder
    return contributions, smoothed


def shapley(size, value, exact_limit=4, samples=96):
    if not size:
        return []
    if size <= exact_limit:
        orders = permutations(range(size))
    else:
        rng = Random(202506)
        orders = (rng.sample(range(size), size) for _ in range(samples))
    contributions = [0.0] * size
    base = value(0)
    for count, order in enumerate(orders, 1):
        mask, previous = 0, base
        for index in order:
            mask |= 1 << index
            current = value(mask)
            contributions[index] += current - previous
            previous = current
    return [total / count for total in contributions]


def decompose(metric_id, catalog, base_facts, current_facts, tree=True):
    before, after = Evaluator(catalog, base_facts), Evaluator(catalog, current_facts)
    definition = catalog[metric_id]
    a, b = before.value(metric_id), after.value(metric_id)
    if a is None or b is None:
        return {"metric_id": metric_id, "baseline": a, "current": b, "delta": None,
                "delta_rate": None, "method": "unavailable", "factors": [], "residual": None,
                "conserved": False, "tree": None}
    delta = b - a
    method, terms, values, smoothed = "difference", [], [], False
    tags = definition["model"]
    if tags != "atomic":
        node = parse(definition["formula"])
        if tags == "add":
            terms = flatten(node, ADD)
            values = [(after.expression(term) - before.expression(term)) * sign for term, sign in terms]
        elif tags == "mul":
            terms = flatten(node, MUL)
            previous = [before.expression(term) for term, _ in terms]
            latest = [after.expression(term) for term, _ in terms]
            signs = [sign for _, sign in terms]
            if all(value >= 0 for value in (*previous, *latest)):
                method = "LMDI"
                values, smoothed = lmdi(previous, latest, signs, delta)
            else:
                method = "Shapley"
                values = shapley(len(terms), lambda mask: math.prod(
                    (latest[i] if mask & (1 << i) else previous[i]) ** sign
                    for i, sign in enumerate(signs)
                ))
        elif metric_id in {"net_margin", "gross_margin"} and definition["formula"] in {
            "profit / revenue", "gross_profit / revenue"
        } and catalog[node.left.id]["formula"] in {
            "revenue - materials - logistics - commission", "revenue - materials",
        }:
            profit = parse(catalog[node.left.id]["formula"])
            terms = [(term, -1) for term, sign in flatten(profit, ADD) if sign == -1]
            values = [-(after.expression(term) / after.value("revenue")
                        - before.expression(term) / before.value("revenue")) for term, _ in terms]
            method = "cost_rate_bridge"
        elif isinstance(node, ast.BinOp):
            terms = [(node.left, 1), (node.right, 1)]
            method = "Shapley"
            values = shapley(2, lambda mask: calculate(
                OPERATORS[type(node.op)],
                (after if mask & 1 else before).expression(node.left),
                (after if mask & 2 else before).expression(node.right),
            ))
    if not terms:
        terms, values = [(ast.Name(id=metric_id), 1)], [delta]
    factors = []
    for (term, sign), contribution in zip(terms, values):
        key = label(term)
        child = decompose(key, catalog, base_facts, current_facts, tree=False) if (
            tree and key != metric_id and key in catalog and catalog[key]["model"] != "atomic"
        ) else None
        factors.append(dict(metric_id=key, name=catalog.get(key, {}).get("name", key),
                            baseline=before.expression(term), current=after.expression(term),
                            operator_sign=sign, contribution=contribution,
                            contribution_rate=divide(contribution, delta), breakdown=child))
    residual = delta - math.fsum(values)

    def node_tree(key):
        item = catalog[key]
        children = []
        if item["formula"]:
            names = dict.fromkeys(references(parse(item["formula"])))
            children = [node_tree(name) for name in names]
        initial, final = before.value(key), after.value(key)
        return {"metric_id": key, "name": item["name"], "baseline": initial, "current": final,
                "delta": final - initial if initial is not None and final is not None else None,
                "children": children}

    return dict(metric_id=metric_id, name=definition["name"], baseline=a, current=b, delta=delta, delta_rate=divide(delta, abs(a)),
                method=method, factors=factors, residual=residual, conserved=abs(residual) <= 1e-9,
                smoothed=smoothed, tree=node_tree(metric_id) if tree else None)
