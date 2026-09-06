from __future__ import annotations

import time
from io import BytesIO
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest
from model_test_helpers import _model_dataset, client

from app.settings import get_settings


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


def test_response_surface_matches_independent_polynomial_fit_and_exports() -> None:
    dataset, measurement = _model_dataset(row_count=60)
    age = next(
        variable for variable in dataset["variables"] if variable["originalName"] == "age"
    )
    started = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        "/empirical-analysis",
        json={
            "factor_count": 4,
            "outcome_variable_id": "scale_y",
            "predictor_variable_ids": ["scale_x", "scale_m"],
            "control_variable_ids": [age["id"]],
            "response_surface_predictor_ids": ["scale_x", "scale_m"],
        },
    )
    meta = _await_empirical_job(started)
    regression = client.get(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        f"/empirical-analyses/{meta['reportId']}/segments/regression"
    )
    assert regression.status_code == 200, regression.text
    result = regression.json()["responseSurface"]
    assert result["available"] is True, result.get("reason")

    settings = get_settings()
    derived = pd.read_parquet(
        settings.state_root / measurement["derivedDataset"]["storage"]
    )
    frame = derived[["scale_y", "scale_x", "scale_m", "age"]].dropna()
    x = np.asarray(frame["scale_x"], dtype=float)
    z = np.asarray(frame["scale_m"], dtype=float)
    xc = x - x.mean()
    zc = z - z.mean()
    design = np.column_stack(
        [np.ones(len(frame)), xc, zc, xc**2, xc * zc, zc**2, frame["age"]]
    )
    beta = np.linalg.lstsq(
        design, np.asarray(frame["scale_y"], dtype=float), rcond=None
    )[0]
    coefficients = {row["term"]: row["estimate"] for row in result["coefficients"]}
    for term, expected in zip(
        [
            "(Intercept)", ".rp_x", ".rp_z", ".rp_x2", ".rp_xz", ".rp_z2",
            age["id"],
        ],
        beta,
        strict=True,
    ):
        assert coefficients[term] == pytest.approx(expected, abs=1e-8)

    surface = {row["id"]: row["estimate"] for row in result["surfaceTests"]}
    assert surface["a1"] == pytest.approx(beta[1] + beta[2], abs=1e-8)
    assert surface["a2"] == pytest.approx(beta[3] + beta[4] + beta[5], abs=1e-8)
    assert surface["a3"] == pytest.approx(beta[1] - beta[2], abs=1e-8)
    assert surface["a4"] == pytest.approx(beta[3] - beta[4] + beta[5], abs=1e-8)
    assert len(result["grid"]) == 81

    importance = regression.json()["hierarchicalRegression"]["relativeImportance"]
    assert importance["available"] is True, importance.get("reason")
    outcome = np.asarray(frame["scale_y"], dtype=float)

    def r_squared(columns: list[np.ndarray]) -> float:
        subset_design = np.column_stack(
            [np.ones(len(frame)), np.asarray(frame["age"], dtype=float), *columns]
        )
        fitted = subset_design @ np.linalg.lstsq(
            subset_design, outcome, rcond=None
        )[0]
        return 1 - np.sum((outcome - fitted) ** 2) / np.sum(
            (outcome - outcome.mean()) ** 2
        )

    base_r2 = r_squared([])
    x_r2 = r_squared([x])
    z_r2 = r_squared([z])
    full_r2 = r_squared([x, z])
    expected = {
        "scale_x": 0.5 * ((x_r2 - base_r2) + (full_r2 - z_r2)),
        "scale_m": 0.5 * ((z_r2 - base_r2) + (full_r2 - x_r2)),
    }
    rows = {row["id"]: row for row in importance["rows"]}
    for predictor_id, contribution in expected.items():
        assert rows[predictor_id]["contribution"] == pytest.approx(
            contribution, abs=1e-8
        )
    assert importance["contributionSum"] == pytest.approx(
        full_r2 - base_r2, abs=1e-8
    )

    exported = client.get(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        f"/empirical-analyses/{meta['reportId']}/export"
    )
    assert exported.status_code == 200, exported.text
    with ZipFile(BytesIO(exported.content)) as workbook:
        workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
        assert "响应面系数" in workbook_xml
        assert "响应面检验" in workbook_xml
        assert "响应面网格" in workbook_xml
        assert "相对重要性" in workbook_xml


def test_response_surface_requires_exactly_two_distinct_predictors() -> None:
    dataset, measurement = _model_dataset()
    endpoint = (
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        "/empirical-analysis"
    )
    response = client.post(
        endpoint,
        json={
            "outcome_variable_id": "scale_y",
            "response_surface_predictor_ids": ["scale_x"],
        },
    )
    assert response.status_code == 422
