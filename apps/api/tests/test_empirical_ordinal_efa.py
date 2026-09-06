from __future__ import annotations

import time
from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from model_test_helpers import _ensure_independent_context, client

from app.settings import get_settings

# The 120-second empirical-job wait is wall-clock bounded and was reproduced
# timing out only under the 4-worker xdist R load on the hosted runner. Keep
# it in the existing single-process serial lane (coverage is merged later).
pytestmark = pytest.mark.serial


def _await_empirical_job(response) -> dict:
    assert response.status_code == 202, response.text
    state = response.json()
    deadline = time.monotonic() + 120
    while state["status"] not in {"succeeded", "failed", "cancelled"}:
        if time.monotonic() >= deadline:
            raise AssertionError(f"empirical job timed out: {state}")
        time.sleep(0.05)
        polled = client.get(f"/api/v1/analyses/{state['id']}")
        assert polled.status_code == 200, polled.text
        state = polled.json()
    assert state["status"] == "succeeded", state
    return state


def _fetch_segment(dataset_id: str, version: int, report_id: str, segment: str) -> dict:
    url = (
        f"/api/v1/datasets/{dataset_id}/measurements/{version}"
        f"/empirical-analyses/{report_id}/segments/{segment}"
    )
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.json()


def test_ordinal_items_use_polychoric_efa_and_never_pearson_pca() -> None:
    columns = ["respondent_id", *[f"item{i}" for i in range(1, 9)], "group"]
    rows = [",".join(columns)]
    rng = np.random.default_rng(20260826)
    for index in range(1, 121):
        values = [str(index)]
        values.extend(str(value) for value in rng.integers(1, 6, size=8))
        values.append("A" if index <= 60 else "B")
        rows.append(",".join(values))
    imported = client.post(
        "/api/v1/datasets/import",
        files={"file": ("ordinal.csv", BytesIO(("\n".join(rows) + "\n").encode("utf-8")), "text/csv")},
    )
    assert imported.status_code == 201, imported.text
    dataset = imported.json()
    updates = [
        {
            "id": variable["id"],
            "confirmed_type": (
                "id"
                if variable["originalName"] == "respondent_id"
                else "binary"
                if variable["originalName"] == "group"
                else "likert"
            ),
        }
        for variable in dataset["variables"]
    ]
    confirmed = client.put(
        f"/api/v1/datasets/{dataset['id']}/dictionary",
        json={"variables": updates},
    )
    assert confirmed.status_code == 200, confirmed.text
    dataset = confirmed.json()
    item_ids = {variable["originalName"]: variable["id"] for variable in dataset["variables"]}
    measured = client.put(
        f"/api/v1/datasets/{dataset['id']}/measurement",
        json={
            "constructs": [
                {
                    "id": "construct_x",
                    "name": "X",
                    "item_ids": [item_ids[f"item{i}"] for i in range(1, 5)],
                    "reverse_item_ids": [],
                    "theoretical_minimum": 1,
                    "theoretical_maximum": 5,
                    "aggregation": "mean",
                    "minimum_valid_proportion": 0.8,
                },
                {
                    "id": "construct_y",
                    "name": "Y",
                    "item_ids": [item_ids[f"item{i}"] for i in range(5, 9)],
                    "reverse_item_ids": [],
                    "theoretical_minimum": 1,
                    "theoretical_maximum": 5,
                    "aggregation": "mean",
                    "minimum_valid_proportion": 0.8,
                },
            ]
        },
    )
    assert measured.status_code == 200, measured.text
    measurement = measured.json()
    _ensure_independent_context(dataset)

    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}/empirical-analysis",
        json={
            "factor_count": 1,
            "factor_count_method": "manual",
            "group_variable_id": item_ids["group"],
        },
    )
    meta = _await_empirical_job(response)
    summary = _fetch_segment(dataset["id"], measurement["version"], meta["reportId"], "summary")
    efa_cfa = _fetch_segment(dataset["id"], measurement["version"], meta["reportId"], "efa_cfa")

    assert summary["commonMethodBias"]["correlationType"] == "polychoric"
    efa = efa_cfa["efa"]
    assert efa["correlationType"] == "polychoric"
    assert efa["requestedCorrelationType"] == "polychoric"
    assert efa["itemScale"] == "ordinal"
    if efa["available"]:
        assert efa["methodExecution"]["executedMethod"].endswith("_polychoric")
    else:
        assert "polychoric" in (efa["reason"] or "")
    assert efa["methodExecution"]["fallbackCode"] != "EFA_FACTANAL_FALLBACK_PCA"
    assert efa["methodExecution"]["executedMethod"] != "principal_components_varimax"

    settings = get_settings()
    derived = pd.read_parquet(settings.state_root / measurement["derivedDataset"]["storage"])
    assert len(derived) == 120
