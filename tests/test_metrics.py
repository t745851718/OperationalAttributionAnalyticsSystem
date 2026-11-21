import math

import pytest

from backend.models.catalog import METRICS
from backend.models.metrics import decompose, shapley, validate_catalog

CATALOG = {item["metric_id"]: item for item in METRICS}


@pytest.mark.parametrize("visits,orders,gmv,expected_smoothed", [
    (100, 5, 500, False), (100, 5, 0, True),
])
def test_gmv_lmdi_conserves_real_delta(visits, orders, gmv, expected_smoothed):
    base = {"visits": 200, "orders": 20, "gmv": 2000}
    current = {"visits": visits, "orders": orders, "gmv": gmv}
    result = decompose("gmv", CATALOG, base, current)
    assert result["smoothed"] is expected_smoothed
    assert result["method"] == "LMDI"
    assert result["conserved"]
    assert abs(math.fsum(row["contribution"] for row in result["factors"]) - (gmv - 2000)) <= 1e-9


def test_zero_delta_has_no_percentage():
    result = decompose("gmv", CATALOG, {"visits": 10, "orders": 5, "gmv": 100},
                       {"visits": 20, "orders": 5, "gmv": 100})
    assert result["delta"] == 0
    assert result["conserved"]
    assert all(item["contribution_rate"] is None for item in result["factors"])


def test_profit_bridge_recovers_margin_and_tree():
    base = {"revenue": 200, "materials": 80, "logistics": 20, "commission": 10}
    current = {**base, "materials": 100, "commission": 15}
    result = decompose("net_margin", CATALOG, base, current)
    assert result["delta"] == pytest.approx(-.125)
    assert result["conserved"]
    assert {row["metric_id"]: row["contribution"] for row in result["factors"]} == pytest.approx(
        {"materials": -.1, "commission": -.025, "logistics": 0}
    )
    assert result["tree"]["children"][0]["children"][1]["metric_id"] == "materials"


def test_formula_catalog_checks_cycles_and_units():
    validate_catalog(CATALOG)
    with pytest.raises(ValueError, match="循环"):
        validate_catalog({**CATALOG, "gmv": {**CATALOG["gmv"], "formula": "gmv * conversion"}})
    with pytest.raises(ValueError, match="单位"):
        validate_catalog({**CATALOG, "gmv": {**CATALOG["gmv"], "formula": "visits * aov"}})


def test_dimension_shapley_allocates_interaction_and_is_reproducible():
    assert shapley(2, lambda mask: (1 if mask & 1 else 0) + (2 if mask == 3 else 0)) == [2, 1]
    score = lambda mask: mask.bit_count() ** 2
    first = shapley(5, score)
    assert first == shapley(5, score)
    assert sum(first) == pytest.approx(25)
