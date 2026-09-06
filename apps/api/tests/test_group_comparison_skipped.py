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


def test_group_comparison_singleton_group_is_skipped_with_warning() -> None:
    dataset, measurement = _model_dataset(row_count=3, group_count=2)
    group = next(variable for variable in dataset["variables"] if variable["originalName"] == "group")
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/"
        f"{measurement['version']}/empirical-analysis",
        json={"group_variable_id": group["id"]},
    )
    meta = _await_empirical_job(response)
    report = _fetch_regression_report(
        client, dataset["id"], measurement["version"], meta["reportId"]
    )

    warning_codes = {warning["code"] for warning in meta["warnings"]}
    assert "GROUP_COMPARISON_SKIPPED" in warning_codes
    comparison = report["groupComparison"]
    assert comparison is not None
    skipped = [row for row in comparison["results"] if row.get("unavailable")]
    assert len(skipped) >= 1
    assert all(row.get("reason") for row in skipped)
