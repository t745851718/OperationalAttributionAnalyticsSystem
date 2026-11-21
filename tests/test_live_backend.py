"""Run against a local server initialized with the demo data and Docker images."""

import io
import json
import os
import time
from pathlib import Path

import httpx
import pytest
from openpyxl import load_workbook

URL = os.getenv("ATTRIBUTION_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set ATTRIBUTION_TEST_URL for live verification")
EXPECTED = json.loads((Path(__file__).resolve().parents[1] / "data" / "expected_attribution.json").read_text())
ARTIFACT_DIR = os.getenv("ATTRIBUTION_TEST_ARTIFACT_DIR")


def login(client, role):
    response = client.post("/api/auth/login", json={"username": role, "password": f"{role}-demo-2025"})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def events(client, method, path, headers, **kwargs):
    all_events, record = [], {}
    started = time.monotonic()
    with client.stream(method, path, headers=headers, **kwargs) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line and record:
                if not all_events:
                    assert time.monotonic() - started < 2
                all_events.append(record)
                record = {}
            elif line and not line.startswith(":"):
                field, _, value = line.partition(": ")
                record[field] = json.loads(value) if field == "data" else value
    assert all_events, "empty event stream"
    assert all_events[-1]["event"] == "complete", all_events[-1]
    assert all_events[-2]["event"] == "conclusion"
    return all_events


@pytest.mark.parametrize("domain,question,expected_filter,driver,followup", [
    ("ecommerce", "按渠道下钻，只分析信息流", {"channel": "信息流"}, "visits", "再按品类下钻，保留信息流切片"),
    ("fmcg", "按品类下钻，只分析饮品", {"category": "饮品"}, "materials", "再按渠道下钻，保留饮品切片"),
])
def test_real_model_full_flow(domain, question, expected_filter, driver, followup):
    with httpx.Client(base_url=URL, timeout=210, trust_env=False) as client:
        analyst = login(client, "analyst")
        dashboard = client.get("/api/dashboard/metrics", params={"domain_id": domain}, headers=analyst)
        dashboard.raise_for_status()
        expected = EXPECTED[domain]
        card = next(item for item in dashboard.json()["metrics"] if item["metric_id"] == expected["metric"])
        assert card["anomaly"]
        body = {"domain_id": domain}
        if domain == "ecommerce":
            body["metric_id"] = expected["metric"]
        else:
            body["question"] = "分析快消品净利率异常下降"
        response = client.post("/api/sessions", headers=analyst, json=body)
        response.raise_for_status()
        result = response.json()
        job_path, session_id = result["stream_url"], result["id"]
        start = events(client, "GET", job_path, analyst)
        analysis = start[-2]["data"]
        assert analysis["decomposition"]["conserved"]
        assert set(expected["negative_drivers"]) <= {
            row["metric_id"] for row in analysis["decomposition"]["factors"] if row["contribution"] < 0
        }
        assert set(expected["events"]) <= {item["event_id"] for item in analysis["events"]}
        assert len(analysis["hypotheses"]) in range(3, 6)
        assert any(item["status"] in {"supported", "excluded"} for item in analysis["hypotheses"])
        assert all(item["elapsed_ms"] < 20_000 for item in analysis["hypotheses"])
        replay = events(client, "GET", job_path, {**analyst, "Last-Event-ID": start[-3]["id"]})
        assert len(replay) == 2
        path = f"/api/sessions/{session_id}"
        first = events(client, "POST", path + "/messages", analyst, json={"content": question})
        assert first[-2]["data"]["spec"]["filters"] == expected_filter
        second = events(client, "POST", path + "/messages", analyst, json={"content": followup})
        assert second[-2]["data"]["spec"]["filters"] == expected_filter
        reviewed = second[-2]["data"]
        hypothesis_id = reviewed["hypotheses"][0]["hypothesis_id"]
        client.put(f"/api/jobs/{reviewed['job_id']}/hypotheses/{hypothesis_id}/review", headers=analyst, json={
            "decision": "accepted", "note": "已核对执行结果",
        }).raise_for_status()
        client.post(path + "/snapshots", headers=analyst, json={"label": "复核"}).raise_for_status()
        for amount in (.05, .10):
            response = client.post(path + "/whatif", headers=analyst, json={
                "name": f"预案 {amount:.0%}", "changes": {driver: amount if domain == "ecommerce" else -amount},
            })
            response.raise_for_status()
            assert response.json()["bootstrap_iterations"] == 1000
        created = client.post(path + "/report", headers=analyst)
        created.raise_for_status()
        report_id = created.json()["id"]
        report_path = f"/api/reports/{report_id}"
        client.patch(report_path, headers=analyst, json={"status": "published"}).raise_for_status()
        client.post(report_path + "/comments", headers=analyst, json={
            "section": "conclusion", "content": "复核意见", "mentions": ["admin"],
        }).raise_for_status()
        for fmt in ("md", "xlsx", "pdf"):
            export = client.get(report_path + "/export", headers=analyst, params={"fmt": fmt})
            export.raise_for_status()
            if fmt == "md":
                assert "优先行动清单" in export.text
                assert "已核对执行结果" in export.text
            if fmt == "xlsx":
                workbook = load_workbook(io.BytesIO(export.content))
                assert isinstance(workbook["因子贡献率拆解"]["D4"].value, (int, float))
            if fmt == "pdf":
                assert export.content.startswith(b"%PDF")
            if ARTIFACT_DIR:
                output = Path(ARTIFACT_DIR)
                output.mkdir(exist_ok=True, parents=True)
                (output / f"{domain}.{fmt}").write_bytes(export.content)
        manager = login(client, "manager")
        status = client.get(report_path, headers=manager).status_code
        assert status == (200 if domain == "ecommerce" else 403)
        assert client.post("/api/sessions", headers=manager, json=body).status_code == 403


def test_manager_sees_only_allowed_indicators():
    with httpx.Client(base_url=URL, trust_env=False) as client:
        manager = login(client, "manager")
        response = client.get("/api/dashboard/metrics", headers=manager)
        response.raise_for_status()
        assert {item["domain_id"] for item in response.json()["metrics"]} == {"ecommerce"}
        assert client.get("/api/metrics?domain_id=fmcg", headers=manager).status_code == 403
