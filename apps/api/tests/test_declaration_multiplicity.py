from __future__ import annotations

import time
from typing import Any, Mapping

from model_test_helpers import _model_dataset, client

from app.contracts import validate_contract
from app.main import app
from app.settings import get_settings


def _await_job(response, timeout: float = 45.0) -> dict[str, Any]:
    assert response.status_code == 202, response.text
    state = response.json()
    deadline = time.monotonic() + timeout
    while state["status"] not in {"succeeded", "failed", "cancelled"}:
        assert time.monotonic() < deadline, state
        time.sleep(0.05)
        polled = client.get(f"/api/v1/analyses/{state['id']}")
        assert polled.status_code == 200, polled.text
        state = polled.json()
    assert state["status"] == "succeeded", state
    result = client.get(f"/api/v1/analyses/{state['id']}/result")
    assert result.status_code == 200, result.text
    state["result"] = result.json()
    return state


def _declaration_plan(context: Mapping[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": "2.0.0",
        "title": "Declaration-driven multiplicity plan",
        "researchQuestion": "Do the planned predictors explain the declared outcome association?",
        "hypotheses": [
            {
                "id": "H1",
                "label": "The outcome is associated with X.",
                "analysisRole": "primary",
                "declarationTiming": "preregistered",
                "direction": "two_sided",
                "estimandIds": ["e_x"],
            },
            {
                "id": "H2",
                "label": "The outcome is associated with M.",
                "analysisRole": "primary",
                "declarationTiming": "preregistered",
                "direction": "two_sided",
                "estimandIds": ["e_m"],
            },
            {
                "id": "H3",
                "label": "The group comparison is exploratory.",
                "analysisRole": "exploratory",
                "declarationTiming": "post_hoc",
                "direction": "two_sided",
                "estimandIds": ["e_group"],
            },
            {
                "id": "H4",
                "label": "A planned primary estimand is intentionally unavailable in this run.",
                "analysisRole": "primary",
                "declarationTiming": "preregistered",
                "direction": "two_sided",
                "estimandIds": ["e_missing"],
            },
        ],
        "estimands": [
            {
                "id": "e_x",
                "quantity": "regression_coefficient",
                "outcomeId": "scale_y",
                "focalPredictorId": "scale_x",
            },
            {
                "id": "e_m",
                "quantity": "regression_coefficient",
                "outcomeId": "scale_y",
                "focalPredictorId": "scale_m",
            },
            {
                "id": "e_group",
                "quantity": "group_mean_difference",
                "outcomeId": "scale_x",
            },
            {
                "id": "e_missing",
                "quantity": "regression_coefficient",
                "outcomeId": "scale_y",
                "focalPredictorId": "scale_missing",
            },
        ],
        "analysisDeclarations": [
            {
                "id": "analysis_primary",
                "role": "primary",
                "estimandIds": ["e_x", "e_m", "e_missing"],
                "capabilitySliceId": "empirical.cross_sectional.hierarchical_regression",
                "requestedMethod": "ordinary_ols",
                "robustnessAnalysisIds": [],
                "parameters": {},
            },
            {
                "id": "analysis_exploratory",
                "role": "exploratory",
                "estimandIds": ["e_group"],
                "capabilitySliceId": "empirical.cross_sectional.group_comparison",
                "requestedMethod": "welch_or_anova_primary",
                "robustnessAnalysisIds": [],
                "parameters": {},
            },
        ],
        "multiplicityFamilies": [
            {
                "id": "primary_hypotheses",
                "label": "Primary hypotheses",
                "role": "primary",
                "adjustment": "holm",
                "memberEstimandIds": ["e_x", "e_m", "e_missing"],
            },
            {
                "id": "exploratory_effects",
                "label": "Exploratory effects",
                "role": "exploratory",
                "adjustment": "BH",
                "memberEstimandIds": ["e_group"],
            },
        ],
        "sampleDefinition": {"roles": []},
        "measurementPlan": {"constructs": []},
        "missingDataPlan": {
            "strategy": "complete cases with explicit missingness report",
            "sensitivityAnalysisIds": [],
            "reportMissingness": True,
        },
        "powerPlan": None,
        "context": context,
    }


def test_frozen_declaration_drives_empirical_multiplicity_and_excludes_control() -> None:
    dataset, measurement = _model_dataset()
    group_id = next(variable["id"] for variable in dataset["variables"] if variable["originalName"] == "group")
    age_id = next(variable["id"] for variable in dataset["variables"] if variable["originalName"] == "age")
    context = {
        "schemaVersion": "1.0.0",
        "timeStructure": "cross_sectional",
        "dependenceStructure": "independent",
        "design": "observational",
    }
    plan_response = client.post(
        f"/api/v1/projects/{dataset['projectId']}/study-plans",
        json={"payload": _declaration_plan(context)},
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = plan_response.json()
    frozen_response = client.post(f"/api/v1/study-plans/{plan['id']}/freeze")
    assert frozen_response.status_code == 200, frozen_response.text
    frozen = frozen_response.json()

    run = _await_job(
        client.post(
            f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}/empirical-analysis",
            json={
                "study_plan_binding": {
                    "studyPlanVersionId": frozen["id"],
                    "studyPlanHash": frozen["planHash"],
                    "hypothesisId": "H1",
                    "estimandId": "e_x",
                    "analysisDeclarationId": "analysis_primary",
                },
                "group_variable_id": group_id,
                "outcome_variable_id": "scale_y",
                "predictor_variable_ids": ["scale_x", "scale_m"],
                "control_variable_ids": [age_id],
                "factor_count": 1,
            },
        )
    )
    report: dict[str, Any] = {}
    for segment in ("summary", "correlation", "efa_cfa", "validity", "regression"):
        segment_response = client.get(
            f"/api/v1/datasets/{run['datasetId']}/measurements/{run['measurementVersion']}"
            f"/empirical-analyses/{run['reportId']}/segments/{segment}"
        )
        assert segment_response.status_code == 200, segment_response.text
        report.update(segment_response.json())
    assert report["multiplicity"]["declarationStatus"] == "typed"
    families = {row["id"]: row for row in report["multiplicity"]["declaredFamilyLedger"]}
    assert families["primary_hypotheses"]["declaredFamilySize"] == 3
    assert families["primary_hypotheses"]["adjustmentN"] == 3
    assert families["primary_hypotheses"]["observedMemberCount"] == 2
    assert families["primary_hypotheses"]["unobservedMemberEstimandIds"] == ["e_missing"]
    assert families["exploratory_effects"]["declaredFamilySize"] == 1
    assert "age" not in report["multiplicity"]["unmappedResultKeys"]
    assert report["publicationEligible"] is False
    assert "PRIMARY_MULTIPLICITY_FAMILY_INCOMPLETE" in report["publicationEligibilityReasons"]

    stored_report = app.state.services.dataset_repository.get_empirical_report(run)
    validate_contract(stored_report, get_settings().empirical_result_schema_path)
    stored_binding = stored_report["studyPlanBinding"]
    assert stored_binding["hypothesisIds"] == ["H1"]
    assert stored_binding["declarationStatus"] == "declared"
    assert stored_report["evidenceGraph"]["schemaVersion"] == "2.0.0"
    assert stored_report["evidenceGraph"]["resultBinding"] == stored_binding

    coefficients = {
        row["term"]: row
        for block in report["hierarchicalRegression"]["blocks"]
        for row in block["coefficients"]
    }
    assert coefficients["scale_x"]["estimandId"] == "e_x"
    assert coefficients["scale_x"]["multiplicityFamilyId"] == "primary_hypotheses"
    assert coefficients["scale_x"]["multiplicityFamilySize"] == 3
    assert coefficients["scale_x"]["multiplicityAdjustmentN"] == 3
    assert coefficients["scale_m"]["estimandId"] == "e_m"
    assert coefficients["scale_m"]["multiplicityFamilyId"] == "primary_hypotheses"
    assert coefficients["scale_m"]["multiplicityFamilySize"] == 3
    assert coefficients["scale_m"]["multiplicityAdjustmentN"] == 3
    assert coefficients[age_id]["analysisRole"] == "adjustment_covariate"
    assert "multiplicityFamilyId" not in coefficients[age_id]

    group_row = next(row for row in report["groupComparison"]["results"] if row["id"] == "scale_x")
    assert group_row["estimandId"] == "e_group"
    assert group_row["multiplicityFamilyId"] == "exploratory_effects"
    assert group_row["multiplicityFamilySize"] == 1
    assert group_row["pValueRaw"] is not None
    assert group_row["pValueAdjusted"] is not None
