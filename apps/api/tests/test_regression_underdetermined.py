from __future__ import annotations

import time

from model_test_helpers import _model_dataset, client


def _await_empirical_job(response):
    assert response.status_code == 202, response.text
    state = response.json()
    deadline = time.monotonic() + 30
    while state["status"] not in {"succeeded", "failed", "cancelled"}:
        assert time.monotonic() < deadline, state
        time.sleep(0.05)
        polled = client.get(f"/api/v1/analyses/{state['id']}")
        assert polled.status_code == 200, polled.text
        state = polled.json()
    assert state["status"] == "succeeded", f"Error detail: {state.get('error')}"
    return state


def _fetch_regression_report(client, dataset_id, version, report_id):
    url = f"/api/v1/datasets/{dataset_id}/measurements/{version}/empirical-analyses/{report_id}/segments/regression"
    res = client.get(url)
    assert res.status_code == 200
    return res.json()


def test_hierarchical_regression_underdetermined_is_marked_and_warned() -> None:
    dataset, measurement = _model_dataset(row_count=5)
    original_ids = {
        variable["originalName"]: variable["id"] for variable in dataset["variables"]
    }
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/"
        f"{measurement['version']}/empirical-analysis",
        json={
            "factor_count": 2,
            "outcome_variable_id": "scale_y",
            "predictor_variable_ids": [
                original_ids[name] for name in ("x1", "x2", "m1", "m2", "w1", "w2")
            ],
            "control_variable_ids": [original_ids["age"]],
        },
    )
    meta = _await_empirical_job(response)
    report = _fetch_regression_report(
        client, dataset["id"], measurement["version"], meta["reportId"]
    )

    warning_codes = {warning["code"] for warning in meta["warnings"]}
    assert "REGRESSION_UNDERDETERMINED" in warning_codes
    regression = report["hierarchicalRegression"]
    assert regression is not None
    assert regression["underdetermined"] is True
    assert all(block["rSquared"] is None for block in regression["blocks"])
    assert regression["change"]["deltaRSquared"] is None
