from __future__ import annotations

import time
from io import BytesIO
from zipfile import ZipFile

import pytest
from model_test_helpers import _model_dataset, client


def _await_large_empirical_job(response):
    assert response.status_code == 202, response.text
    state = response.json()
    deadline = time.monotonic() + 120
    while state["status"] not in {"succeeded", "failed", "cancelled"}:
        assert time.monotonic() < deadline, state
        time.sleep(0.1)
        state = client.get(f"/api/v1/analyses/{state['id']}").json()
    assert state["status"] == "succeeded", state.get("error")
    return state


# Four nested R model fits are wall-clock-sensitive when executed beside the
# xdist R workload.  Run this end-to-end check in the existing isolated lane;
# it preserves the fixture, assertions, and product timeout under contention.
@pytest.mark.serial
def test_multigroup_measurement_invariance_runs_progressive_models_and_exports() -> None:
    dataset, measurement = _model_dataset(row_count=240)
    group = next(
        variable for variable in dataset["variables"] if variable["originalName"] == "group"
    )
    started = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}/empirical-analysis",
        json={"factor_count": 4, "group_variable_id": group["id"]},
    )
    meta = _await_large_empirical_job(started)
    segment = client.get(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        f"/empirical-analyses/{meta['reportId']}/segments/validity"
    )
    assert segment.status_code == 200, segment.text
    result = segment.json()["measurementInvariance"]

    assert result["available"] is True, result.get("reason")
    assert result["groupSizes"] == [120, 120]
    assert set(result["models"]) == {"configural", "metric", "scalar", "strict"}
    assert {"metric", "scalar"}.issubset(result["comparisons"])
    for current, previous in (("metric", "configural"), ("scalar", "metric")):
        comparison = result["comparisons"][current]
        current_model = result["models"][current]
        previous_model = result["models"][previous]
        current_cfi = current_model["cfiRobust"] or current_model["cfi"]
        previous_cfi = previous_model["cfiRobust"] or previous_model["cfi"]
        current_rmsea = current_model["rmseaRobust"] or current_model["rmsea"]
        previous_rmsea = previous_model["rmseaRobust"] or previous_model["rmsea"]
        assert comparison["deltaCfi"] == pytest.approx(current_cfi - previous_cfi, abs=1e-8)
        assert comparison["deltaRmsea"] == pytest.approx(
            current_rmsea - previous_rmsea, abs=1e-8
        )

    exported = client.get(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        f"/empirical-analyses/{meta['reportId']}/export"
    )
    assert exported.status_code == 200, exported.text
    with ZipFile(BytesIO(exported.content)) as workbook:
        workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
        assert "测量等值性" in workbook_xml
        assert "等值性比较" in workbook_xml
