from __future__ import annotations

import time
from io import BytesIO
from zipfile import ZipFile

import pytest
from model_test_helpers import _model_dataset, client


def _await_empirical_job(response):
    assert response.status_code == 202, response.text
    state = response.json()
    deadline = time.monotonic() + 45
    while state["status"] not in {"succeeded", "failed", "cancelled"}:
        assert time.monotonic() < deadline, state
        time.sleep(0.05)
        state = client.get(f"/api/v1/analyses/{state['id']}").json()
    assert state["status"] == "succeeded", state.get("error")
    return state


def test_missing_data_report_counts_patterns_mcar_and_exports() -> None:
    dataset, measurement = _model_dataset(row_count=80, missing_pattern=True)
    started = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        "/empirical-analysis",
        json={"factor_count": 4},
    )
    meta = _await_empirical_job(started)
    summary = client.get(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        f"/empirical-analyses/{meta['reportId']}/segments/summary"
    )
    assert summary.status_code == 200, summary.text
    report = summary.json()["missingDataReport"]
    rows = {row["label"]: row for row in report["variables"]}
    assert rows["x1"]["missingCount"] == 16
    assert rows["m2"]["missingCount"] == 11
    assert rows["y1"]["missingCount"] == 7
    assert rows["x1"]["missingRate"] == pytest.approx(16 / 80, abs=1e-12)
    assert report["incompleteCaseCount"] > 0
    assert report["completeCaseCount"] + report["incompleteCaseCount"] == 80
    assert sum(row["missingCount"] for row in report["variables"]) == report[
        "anyMissingCellCount"
    ]
    assert sum(pattern["count"] for pattern in report["patterns"]) == 80

    mcar = report["littleMcar"]
    assert mcar["available"] is True, mcar.get("reason")
    assert mcar["statistic"] >= 0
    assert mcar["degreesOfFreedom"] > 0
    assert 0 <= mcar["pValue"] <= 1
    assert mcar["emConverged"] is True

    validity = client.get(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        f"/empirical-analyses/{meta['reportId']}/segments/validity"
    )
    assert validity.status_code == 200, validity.text
    assert validity.json()["measurementInvariance"] == {
        "available": False,
        "reason": "未选择分组变量",
    }

    regression = client.get(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        f"/empirical-analyses/{meta['reportId']}/segments/regression"
    )
    assert regression.status_code == 200, regression.text
    assert "groupComparison" not in regression.json()
    assert "aggregationDiagnostics" not in regression.json()
    assert "hierarchicalRegression" not in regression.json()
    assert "responseSurface" not in regression.json()

    exported = client.get(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        f"/empirical-analyses/{meta['reportId']}/export"
    )
    assert exported.status_code == 200, exported.text
    with ZipFile(BytesIO(exported.content)) as workbook:
        workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
        assert "缺失变量" in workbook_xml
        assert "缺失模式" in workbook_xml
        assert "缺失机制诊断" in workbook_xml
