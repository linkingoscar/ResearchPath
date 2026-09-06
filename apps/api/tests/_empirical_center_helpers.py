from __future__ import annotations

import time

from model_test_helpers import client


def _reference_bh_adjust(values: list[float]) -> list[float]:
    """Independent Benjamini-Hochberg implementation for engine conformance."""
    count = len(values)
    order = sorted(range(count), key=values.__getitem__)
    adjusted = [0.0] * count
    running_minimum = 1.0
    for rank_index in range(count - 1, -1, -1):
        original_index = order[rank_index]
        rank = rank_index + 1
        running_minimum = min(running_minimum, values[original_index] * count / rank)
        adjusted[original_index] = min(1.0, running_minimum)
    return adjusted


def _reference_holm_adjust(values: list[float]) -> list[float]:
    """Independent Holm step-down implementation for engine conformance."""
    count = len(values)
    order = sorted(range(count), key=values.__getitem__)
    adjusted = [0.0] * count
    running_maximum = 0.0
    for rank_index, original_index in enumerate(order):
        running_maximum = max(running_maximum, values[original_index] * (count - rank_index))
        adjusted[original_index] = min(1.0, running_maximum)
    return adjusted


def _fetch_full_report(client, dataset_id, version, report_id):
    segments = ["summary", "correlation", "efa_cfa", "validity", "regression"]
    merged = {}
    for seg in segments:
        url = f"/api/v1/datasets/{dataset_id}/measurements/{version}/empirical-analyses/{report_id}/segments/{seg}"
        res = client.get(url)
        assert res.status_code == 200
        merged.update(res.json())
    return merged


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
