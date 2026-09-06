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


def test_empirical_result_keeps_queue_and_report_on_one_context_lineage() -> None:
    dataset, measurement = _model_dataset()
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}/empirical-analysis",
        json={"factor_count": 4, "outcome_variable_id": "scale_y"},
    )

    meta = _await_empirical_job(response)
    assert meta["metadata"]["contextHash"] == meta["options"]["contextHash"]

    result = client.get(f"/api/v1/analyses/{meta['id']}/result")
    assert result.status_code == 200, result.text
    provenance = result.json()["provenance"]
    assert provenance["contextHash"] == meta["metadata"]["contextHash"]
    assert provenance["analysisContext"]["dataset"]["id"] == dataset["id"]
    assert provenance["analysisContext"]["dataset"]["sha256"] == dataset["originalFile"]["sha256"]
