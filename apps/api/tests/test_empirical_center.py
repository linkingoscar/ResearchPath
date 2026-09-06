from __future__ import annotations

import time
from io import BytesIO
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest
from _empirical_center_helpers import (
    _await_empirical_job,
    _fetch_full_report,
    _reference_bh_adjust,
    _reference_holm_adjust,
)
from model_test_helpers import _model_dataset, client

from app.settings import get_settings


def test_questionnaire_empirical_center_computes_and_exports_paper_tables() -> None:
    dataset, measurement = _model_dataset()
    age = next(variable for variable in dataset["variables"] if variable["originalName"] == "age")
    group = next(variable for variable in dataset["variables"] if variable["originalName"] == "group")
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}/empirical-analysis",
        json={
            "factor_count": 4,
            "group_variable_id": group["id"],
            "aggregation_variable_id": group["id"],
            "outcome_variable_id": "scale_y",
            "predictor_variable_ids": ["scale_x", "scale_m"],
            "control_variable_ids": [age["id"]],
        },
    )
    meta = _await_empirical_job(response)
    result = client.get(f"/api/v1/analyses/{meta['id']}/result")
    assert result.status_code == 200, result.text
    report = _fetch_full_report(client, dataset["id"], measurement["version"], meta["reportId"])
    report.update({"reportId": meta["reportId"], "options": meta["options"]})
    assert report["resultAvailability"] == {
        "groups": "available",
        "regression": "available",
        "advanced": "available",
        "longitudinal": "not_requested",
        "diary": "not_requested",
    }
    settings = get_settings()
    derived = pd.read_parquet(settings.state_root / measurement["derivedDataset"]["storage"])
    assert report["sample"]["rowCount"] == 40
    assert len(report["descriptives"]) >= 4
    assert len(report["correlations"]["coefficients"]) >= 4
    correlation_ids = [row["id"] for row in report["correlations"]["variables"]]
    scale_x_index = correlation_ids.index("scale_x")
    scale_y_index = correlation_ids.index("scale_y")
    correlation_frame = derived[["scale_x", "scale_y"]].dropna()
    correlation_values = np.asarray(correlation_frame, dtype=float)
    reference_correlation = np.corrcoef(correlation_values[:, 0], correlation_values[:, 1])[0, 1]
    reference_ci_half_width = 1.959963984540054 / np.sqrt(len(correlation_frame) - 3)
    reference_correlation_ci = np.tanh(
        np.arctanh(reference_correlation)
        + np.asarray([-reference_ci_half_width, reference_ci_half_width])
    )
    assert report["correlations"]["coefficients"][scale_x_index][scale_y_index] == pytest.approx(
        reference_correlation, abs=1e-8
    )
    assert report["correlations"]["ciLower"][scale_x_index][scale_y_index] == pytest.approx(
        reference_correlation_ci[0], abs=1e-8
    )
    assert report["correlations"]["ciUpper"][scale_x_index][scale_y_index] == pytest.approx(
        reference_correlation_ci[1], abs=1e-8
    )
    correlation_multiplicity = report["correlations"]["multiplicity"]
    assert correlation_multiplicity["adjustment"] == "BH"
    assert correlation_multiplicity["familyId"] == "all_unique_off_diagonal_correlations"
    assert correlation_multiplicity["familySize"] > 1
    assert report["correlations"]["pValueDisplay"] == "adjusted"
    assert report["correlations"]["pValuesRaw"][scale_x_index][scale_y_index] <= report["correlations"]["pValuesAdjusted"][scale_x_index][scale_y_index]
    raw_family: list[float] = []
    adjusted_family: list[float] = []
    raw_matrix = report["correlations"]["pValuesRaw"]
    adjusted_matrix = report["correlations"]["pValuesAdjusted"]
    for row_index in range(len(raw_matrix)):
        for column_index in range(row_index + 1, len(raw_matrix)):
            if raw_matrix[row_index][column_index] is not None:
                raw_family.append(raw_matrix[row_index][column_index])
                adjusted_family.append(adjusted_matrix[row_index][column_index])
    assert adjusted_family == pytest.approx(_reference_bh_adjust(raw_family), abs=1e-12)
    paper_rows = {row["id"]: row for row in report["paperSummaryTable"]["rows"]}
    assert paper_rows["scale_x"]["mean"] == pytest.approx(derived["scale_x"].mean(), abs=1e-8)
    assert paper_rows["scale_x"]["sd"] == pytest.approx(derived["scale_x"].std(), abs=1e-8)
    assert paper_rows["scale_x"]["alpha"] is not None
    assert "omega" in paper_rows["scale_x"]
    assert paper_rows[age["id"]]["alpha"] is None
    assert paper_rows["scale_x"]["correlations"][scale_y_index] == pytest.approx(
        reference_correlation, abs=1e-8
    )
    assert report["commonMethodBias"]["available"] is True
    assert report["factorability"]["kmo"] is not None
    assert report["efa"]["available"] is True
    assert report["efa"]["methodExecution"]["requestedMethod"].startswith(
        "maximum_likelihood_factanal_"
    )
    assert report["efa"]["methodExecution"]["executedMethod"] == report["efa"]["method"]
    assert isinstance(report["efa"]["methodExecution"]["fallbackApplied"], bool)
    assert report["cfa"]["available"] is True and report["cfa"]["converged"] is True
    assert all(key in report["cfa"]["methodExecution"] for key in ("requestedMethod", "executedMethod", "fallbackApplied"))
    assert report["sample"]["measurementAdequacy"]["status"] == "caution"
    assert report["sample"]["measurementAdequacy"]["completeCases"] == 40
    assert report["sample"]["measurementAdequacy"]["estimatedParameterCount"] > 0
    assert report["cfa"]["validForConfirmatoryInterpretation"] is False
    assert report["cfa"]["casesPerParameter"] == pytest.approx(
        report["sample"]["measurementAdequacy"]["casesPerParameter"]
    )
    advanced_boundary = report["advancedMeasurementBoundary"]
    assert advanced_boundary["executedInBaseReport"] is False
    assert advanced_boundary["availableThrough"] == "advanced_workbench"
    assert advanced_boundary["sliceId"] == "questionnaire_measurement.esem_bifactor_irt"
    assert advanced_boundary["methods"] == ["ESEM", "Bifactor", "IRT", "DIF"]
    assert 0 <= report["cfa"]["rmseaCiLower"] <= report["cfa"]["rmseaCiUpper"]
    invariance = report["measurementInvariance"]
    assert invariance["available"] is False
    assert invariance["reason"]
    assert len(report["validity"]["constructs"]) == 4
    assert report["validity"]["htmtAvailable"] is True
    assert report["validity"]["htmtCorrelationSource"] == "pearson"
    assert report["validity"]["htmtMethodExecution"]["executedMethod"] == "pearson_HTMT"
    validity_fallbacks = [
        construct["fallbackApplied"] for construct in report["validity"]["constructs"]
    ]
    assert report["validity"]["methodExecution"]["fallbackApplied"] is any(
        validity_fallbacks
    )
    assert all(
        (construct["loadingSource"] == "single-factor eigen fallback")
        is construct["fallbackApplied"]
        for construct in report["validity"]["constructs"]
    )
    if report["validity"]["methodExecution"]["fallbackApplied"]:
        assert report["validity"]["methodExecution"]["fallbackReason"]
        warning_codes = {warning["code"] for warning in meta["warnings"]}
        assert "CFA_UNAVAILABLE_FALLBACK_SINGLE_FACTOR_EIGEN" in warning_codes
    assert len(report["groupComparison"]["results"]) == 4
    assert report["groupComparison"]["multiplicity"]["adjustment"] == "holm"
    assert report["groupComparison"]["multiplicity"]["primaryFamilySize"] == 4
    group_raw = [row["pValueRaw"] for row in report["groupComparison"]["results"]]
    group_adjusted = [row["pValueAdjusted"] for row in report["groupComparison"]["results"]]
    assert group_adjusted == pytest.approx(_reference_holm_adjust(group_raw), abs=1e-12)
    for comparison in report["groupComparison"]["results"]:
        assert comparison["pValue"] == comparison["pValueAdjusted"]
        assert comparison["pValueRaw"] <= comparison["pValueAdjusted"]
        assert comparison["multiplicityFamilyId"] == "group_omnibus_across_constructs"
    assert report["hierarchicalRegression"]["change"]["deltaRSquared"] is not None

    first_group = derived.loc[derived["group"] == "A", "scale_x"].to_numpy()
    second_group = derived.loc[derived["group"] == "B", "scale_x"].to_numpy()
    welch_reference = (first_group.mean() - second_group.mean()) / np.sqrt(
        first_group.var(ddof=1) / len(first_group) + second_group.var(ddof=1) / len(second_group)
    )
    scale_x_comparison = next(
        row for row in report["groupComparison"]["results"] if row["id"] == "scale_x"
    )
    assert abs(scale_x_comparison["statistic"]) == pytest.approx(abs(welch_reference), abs=1e-8)
    pooled_sd = np.sqrt(
        (
            (len(first_group) - 1) * first_group.var(ddof=1)
            + (len(second_group) - 1) * second_group.var(ddof=1)
        )
        / (len(first_group) + len(second_group) - 2)
    )
    cohen_d = (second_group.mean() - first_group.mean()) / pooled_sd
    correction = 1 - 3 / (4 * (len(first_group) + len(second_group) - 2) - 1)
    reference_g = correction * cohen_d
    reference_g_se = correction * np.sqrt(
        (len(first_group) + len(second_group)) / (len(first_group) * len(second_group))
        + cohen_d**2 / (2 * (len(first_group) + len(second_group) - 2))
    )
    assert scale_x_comparison["effectSize"] == pytest.approx(reference_g, abs=1e-8)
    assert scale_x_comparison["effectSizeCiLower"] == pytest.approx(
        reference_g - 1.959963984540054 * reference_g_se, abs=1e-8
    )
    assert scale_x_comparison["effectSizeCiUpper"] == pytest.approx(
        reference_g + 1.959963984540054 * reference_g_se, abs=1e-8
    )

    aggregation = report["aggregationDiagnostics"]
    scale_x_aggregation = next(
        row for row in aggregation["constructs"] if row["id"] == "scale_x"
    )
    cluster_groups = [
        group["scale_x"].to_numpy(dtype=float)
        for _, group in derived.groupby("group", sort=True)
    ]
    total_n = sum(len(group) for group in cluster_groups)
    cluster_count = len(cluster_groups)
    grand_mean = derived["scale_x"].mean()
    ss_between = sum(
        len(group) * (group.mean() - grand_mean) ** 2 for group in cluster_groups
    )
    ss_within = sum(np.sum((group - group.mean()) ** 2) for group in cluster_groups)
    ms_between = ss_between / (cluster_count - 1)
    ms_within = ss_within / (total_n - cluster_count)
    sizes = np.asarray([len(group) for group in cluster_groups], dtype=float)
    effective_size = (total_n - np.sum(sizes**2) / total_n) / (cluster_count - 1)
    reference_icc1 = (ms_between - ms_within) / (
        ms_between + (effective_size - 1) * ms_within
    )
    reference_icc2 = (ms_between - ms_within) / ms_between
    assert scale_x_aggregation["icc1"] == pytest.approx(reference_icc1, abs=1e-8)
    assert scale_x_aggregation["icc2"] == pytest.approx(reference_icc2, abs=1e-8)
    assert scale_x_aggregation["designEffect"] == pytest.approx(
        1 + (effective_size - 1) * reference_icc1,
        abs=1e-8,
    )
    assert scale_x_aggregation["rwg"]["expectedScoreVariance"] == pytest.approx(
        ((100**2 - 1) / 12) / 2,
        abs=1e-8,
    )

    variable_names = {variable["id"]: variable["originalName"] for variable in dataset["variables"]}
    ordered_item_names = [
        variable_names[item_id]
        for construct in measurement["constructs"]
        for item_id in construct["itemIds"]
    ]
    item_df = pd.DataFrame(derived[ordered_item_names])
    item_correlation = np.asarray(item_df.corr(), dtype=float)
    inverse = np.linalg.inv(item_correlation)
    partial = -inverse / np.sqrt(np.outer(np.diag(inverse), np.diag(inverse)))
    np.fill_diagonal(partial, 0)
    squared_correlation = item_correlation**2
    np.fill_diagonal(squared_correlation, 0)
    reference_kmo = float(squared_correlation.sum() / (squared_correlation.sum() + (partial**2).sum()))
    assert report["factorability"]["kmo"] == pytest.approx(reference_kmo, abs=1e-8)
    item_count = len(ordered_item_names)
    reference_bartlett = (
        -(len(derived) - 1 - (2 * item_count + 5) / 6) * np.linalg.slogdet(item_correlation)[1]
    )
    assert report["factorability"]["bartlett"]["statistic"] == pytest.approx(
        reference_bartlett, abs=1e-8
    )

    regression_frame = derived[["scale_y", "age", "scale_x", "scale_m"]].dropna()
    design = np.column_stack(
        [
            np.ones(len(regression_frame)),
            regression_frame["age"],
            regression_frame["scale_x"],
            regression_frame["scale_m"],
        ]
    )
    scale_y_arr = np.asarray(regression_frame["scale_y"], dtype=float)
    reference_beta = np.linalg.lstsq(design, scale_y_arr, rcond=None)[0]
    block_two = report["hierarchicalRegression"]["blocks"][1]
    scale_x_coefficient = next(row for row in block_two["coefficients"] if row["term"] == "scale_x")
    assert scale_x_coefficient["estimate"] == pytest.approx(reference_beta[2], abs=1e-8)
    residuals = scale_y_arr - design @ reference_beta
    inverse_xtx = np.linalg.inv(design.T @ design)
    leverage = np.diag(design @ inverse_xtx @ design.T)
    classic_se = np.sqrt(
        np.diag(inverse_xtx) * np.sum(residuals**2) / (len(regression_frame) - design.shape[1])
    )
    hc3_covariance = (
        inverse_xtx
        @ design.T
        @ np.diag((residuals / (1 - np.minimum(leverage, 0.99))) ** 2)
        @ design
        @ inverse_xtx
    )
    robust = report["hierarchicalRegression"]["robustness"]
    scale_x_robust = next(
        row for row in robust["standardErrorComparison"] if row["term"] == "scale_x"
    )
    assert scale_x_robust["classicStandardError"] == pytest.approx(classic_se[2], abs=1e-8)
    assert scale_x_robust["hc3StandardError"] == pytest.approx(
        np.sqrt(hc3_covariance[2, 2]), abs=1e-8
    )
    cook_distance = residuals**2 / (
        design.shape[1] * np.sum(residuals**2) / (len(regression_frame) - design.shape[1])
    ) * leverage / (1 - leverage) ** 2
    reference_influential = np.sum(
        (cook_distance > 4 / len(regression_frame))
        | (leverage > 2 * design.shape[1] / len(regression_frame))
    )
    assert robust["influence"]["influentialCount"] == reference_influential

    for construct in report["validity"]["constructs"]:
        # Signed loadings are intentional: mixed signs should depress CR and
        # surface reverse-coding/model-direction problems instead of being hidden.
        loadings = np.asarray(construct["standardizedLoadings"], dtype=float)
        reference_cr = loadings.sum() ** 2 / (loadings.sum() ** 2 + np.sum(1 - loadings**2))
        assert construct["compositeReliability"] == pytest.approx(reference_cr, abs=1e-8)

    exported = client.get(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}"
        f"/empirical-analyses/{report['reportId']}/export"
    )
    assert exported.status_code == 200, exported.text
    with ZipFile(BytesIO(exported.content)) as workbook:
        names = set(workbook.namelist())
        assert "[Content_Types].xml" in names
        assert "xl/workbook.xml" in names
        workbook_xml = workbook.read("xl/workbook.xml").decode("utf-8")
        for sheet_name in (
            "相关p值",
            "相关有效N",
            "相关95%CI下限",
            "相关95%CI上限",
            "论文整合表",
            "方法诊断",
            "测量方法执行",
            "CFA拟合",
            "CFA标准化载荷",
            "Fornell-Larcker",
            "HTMT",
            "聚合诊断",
            "分层回归区块",
            "回归稳健SE",
            "回归敏感性",
        ):
            assert sheet_name in workbook_xml


def test_partial_correlation_interval_uses_control_adjusted_fisher_degrees() -> None:
    dataset, measurement = _model_dataset()
    age = next(variable for variable in dataset["variables"] if variable["originalName"] == "age")
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}/empirical-analysis",
        json={"correlation_method": "partial", "control_variable_ids": [age["id"]]},
    )
    meta = _await_empirical_job(response)
    report = _fetch_full_report(client, dataset["id"], measurement["version"], meta["reportId"])
    correlations = report["correlations"]
    ids = [row["id"] for row in correlations["variables"]]
    x_index = ids.index("scale_x")
    y_index = ids.index("scale_y")

    settings = get_settings()
    derived = pd.read_parquet(settings.state_root / measurement["derivedDataset"]["storage"])
    frame = derived[["scale_x", "scale_y", "age"]].dropna()
    values = np.asarray(frame, dtype=float)
    x_values, y_values, age_values = values[:, 0], values[:, 1], values[:, 2]
    controls = np.column_stack([np.ones(len(frame)), age_values])
    x_residual = x_values - controls @ np.linalg.lstsq(controls, x_values, rcond=None)[0]
    y_residual = y_values - controls @ np.linalg.lstsq(controls, y_values, rcond=None)[0]
    reference = np.corrcoef(x_residual, y_residual)[0, 1]
    half_width = 1.959963984540054 / np.sqrt(len(frame) - 1 - 3)
    bounds = np.tanh(np.arctanh(reference) + np.asarray([-half_width, half_width]))

    assert correlations["coefficients"][x_index][y_index] == pytest.approx(reference, abs=1e-8)
    assert correlations["ciLower"][x_index][y_index] == pytest.approx(bounds[0], abs=1e-8)
    assert correlations["ciUpper"][x_index][y_index] == pytest.approx(bounds[1], abs=1e-8)
    assert "control variables" in correlations["confidenceIntervalMethod"]


def test_promax_returns_oblique_factor_results() -> None:
    dataset, measurement = _model_dataset()
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}/empirical-analysis",
        json={"factor_count": 4, "rotation": "promax"},
    )

    meta = _await_empirical_job(response)
    report = _fetch_full_report(client, dataset["id"], measurement["version"], meta["reportId"])
    efa = report["efa"]
    assert efa["available"] is True
    assert efa["rotation"] == "promax"
    assert len(efa["factorCorrelations"]) == efa["factorCount"]
    assert len(efa["structureMatrix"]) == len(efa["loadings"])
    assert all(np.isfinite(row["communality"]) for row in efa["loadings"])
    pattern = np.asarray([row["loadings"] for row in efa["loadings"]], dtype=float)
    factor_correlations = np.asarray(efa["factorCorrelations"], dtype=float)
    structure = np.asarray(efa["structureMatrix"], dtype=float)
    assert factor_correlations == pytest.approx(factor_correlations.T, abs=1e-10)
    assert np.diag(factor_correlations) == pytest.approx(np.ones(efa["factorCount"]), abs=1e-10)
    assert structure == pytest.approx(pattern @ factor_correlations, abs=1e-10)
    reference_communality = np.diag(pattern @ factor_correlations @ pattern.T)
    assert [row["communality"] for row in efa["loadings"]] == pytest.approx(
        reference_communality, abs=1e-10
    )


def test_parallel_analysis_is_seeded_and_empirical_options_are_strict() -> None:
    dataset, measurement = _model_dataset()
    endpoint = (
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}/empirical-analysis"
    )
    options = {
        "factor_count_method": "parallel_analysis",
        "parallel_iterations": 100,
        "random_seed": 271828,
    }

    first = client.post(endpoint, json=options)
    second = client.post(endpoint, json=options)
    different_seed = client.post(endpoint, json={**options, "random_seed": 314159})
    assert first.status_code == second.status_code == different_seed.status_code == 202

    first_meta = _await_empirical_job(first)
    second_meta = _await_empirical_job(second)
    different_meta = _await_empirical_job(different_seed)

    first_report = _fetch_full_report(
        client, dataset["id"], measurement["version"], first_meta["reportId"]
    )
    second_report = _fetch_full_report(
        client, dataset["id"], measurement["version"], second_meta["reportId"]
    )
    different_report = _fetch_full_report(
        client, dataset["id"], measurement["version"], different_meta["reportId"]
    )

    first_parallel = first_report["efa"]["parallelAnalysis"]
    second_parallel = second_report["efa"]["parallelAnalysis"]
    different_parallel = different_report["efa"]["parallelAnalysis"]
    assert first_parallel == second_parallel
    assert first_parallel["iterations"] == 100
    assert first_parallel["seed"] == 271828
    assert first_parallel["simulatedEigenvalues"] != different_parallel["simulatedEigenvalues"]

    assert client.post(endpoint, json={"rotation": "oblimin"}).status_code == 422
    assert client.post(endpoint, json={"correlation_method": "kendall"}).status_code == 422
    assert client.post(endpoint, json={"factor_count_method": "guess"}).status_code == 422


def test_empirical_job_can_be_cancelled_and_removes_work_directory() -> None:
    dataset, measurement = _model_dataset()
    endpoint = (
        f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}/empirical-analysis"
    )
    response = client.post(
        endpoint,
        json={
            "factor_count_method": "parallel_analysis",
            "parallel_iterations": 10000,
        },
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    cancelled = client.delete(f"/api/v1/analyses/{run_id}")
    assert cancelled.status_code == 200, cancelled.text
    deadline = time.monotonic() + 5
    state = cancelled.json()
    while state["status"] not in {"cancelled", "failed", "succeeded"}:
        assert time.monotonic() < deadline, state
        time.sleep(0.05)
        state = client.get(f"/api/v1/analyses/{run_id}").json()
    assert state["status"] == "cancelled", state
    run_root = get_settings().state_root / "projects/default/runs" / run_id
    cleanup_deadline = time.monotonic() + 2
    while (run_root / "work").exists() and time.monotonic() < cleanup_deadline:
        time.sleep(0.02)
    assert not (run_root / "work").exists()


def test_analysis_queue_is_bounded_and_returns_429() -> None:
    dataset, measurement = _model_dataset()
    manager = client.app.state.services.analysis_job_manager
    acquired = 0
    while manager._submission_slots.acquire(blocking=False):
        acquired += 1
    try:
        response = client.post(
            f"/api/v1/datasets/{dataset['id']}/measurements/"
            f"{measurement['version']}/empirical-analysis",
            json={},
        )
        assert acquired > 0
        assert response.status_code == 429, response.text
    finally:
        for _ in range(acquired):
            manager._submission_slots.release()


def test_cleanup_removes_terminal_job_state_and_empirical_report() -> None:
    dataset, measurement = _model_dataset()
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/measurements/"
        f"{measurement['version']}/empirical-analysis",
        json={},
    )
    state = _await_empirical_job(response)
    settings = get_settings()
    report_path = settings.state_root / state["resultPath"]
    run_root = settings.state_root / "projects/default/runs" / state["id"]
    assert report_path.exists()
    assert run_root.exists()

    cleanup = client.post("/api/v1/analyses/cleanup", json={"keep_count": 0})
    assert cleanup.status_code == 200, cleanup.text
    assert cleanup.json()["deleted"] >= 1
    assert not report_path.parent.exists()
    assert not run_root.exists()
    assert client.get(f"/api/v1/analyses/{state['id']}").status_code == 404
