from __future__ import annotations

from io import BytesIO

import numpy as np
import pandas as pd
import pytest
from model_test_helpers import _await_analysis, client

from app.settings import get_settings


def test_logistic_regression_fits_binary_outcome() -> None:
    # 1. Create a dataset with a 0/1 binary outcome and a mediator M
    columns = ["respondent_id", "x1", "x2", "m1", "m2", "y_bin", "age", "treatment", "condition"]
    rows = [",".join(columns)]
    for index in range(1, 101):
        age_val = 20 + (index * 7) % 31
        # Deterministic but non-separated binary response: the event
        # probability rises with age while both outcomes remain present
        # throughout the age range. This tests logistic estimation rather
        # than relying on the former logistic-to-OLS fallback.
        event_score = (index * 37) % 100
        event_cutoff = 20 + (age_val - 20) * 2
        # Use 1/2 rather than 0/1 to verify explicit binary level encoding.
        y_val = 2 if event_score < event_cutoff else 1
        values = [
            index,
            10 + (index * 3) % 5,
            12 + (index * 4) % 5,
            8 + (index * 2) % 5,
            9 + (index * 3) % 5,
            y_val,
            age_val,
            index % 2,
            ("A", "B", "C")[index % 3],
        ]
        rows.append(",".join(str(value) for value in values))
    payload = ("\n".join(rows) + "\n").encode("utf-8")

    imported = client.post(
        "/api/v1/datasets/import",
        files={"file": ("logistic.csv", BytesIO(payload), "text/csv")},
    )
    assert imported.status_code == 201, imported.text
    dataset = imported.json()

    # 2. Confirm types
    updates = [
        {
            "id": var["id"],
            "confirmed_type": "id"
            if var["originalName"] == "respondent_id"
            else "binary"
            if var["originalName"] in {"y_bin", "treatment"}
            else "nominal"
            if var["originalName"] == "condition"
            else "continuous"
            if var["originalName"] == "age"
            else "likert",
        }
        for var in dataset["variables"]
    ]
    confirmed = client.put(
        f"/api/v1/datasets/{dataset['id']}/dictionary",
        json={"variables": updates},
    )
    assert confirmed.status_code == 200
    dataset = confirmed.json()

    # 3. Create constructs
    item_ids = {var["originalName"]: var["id"] for var in dataset["variables"]}
    constructs = [
        {
            "id": "construct_x",
            "name": "X",
            "item_ids": [item_ids["x1"], item_ids["x2"]],
            "reverse_item_ids": [],
            "theoretical_minimum": 1,
            "theoretical_maximum": 20,
            "aggregation": "mean",
            "minimum_valid_proportion": 0.8,
        },
        {
            "id": "construct_m",
            "name": "M",
            "item_ids": [item_ids["m1"], item_ids["m2"]],
            "reverse_item_ids": [],
            "theoretical_minimum": 1,
            "theoretical_maximum": 20,
            "aggregation": "mean",
            "minimum_valid_proportion": 0.8,
        },
    ]
    measured = client.put(
        f"/api/v1/datasets/{dataset['id']}/measurement",
        json={"constructs": constructs},
    )
    assert measured.status_code == 200
    measurement = measured.json()

    # 4. Fit model with binary outcome (Model 4: X -> M -> Y, X -> Y)
    model = {
        "schemaVersion": "1.0.0",
        "modelId": "logistic_model",
        "name": "Logistic Regression Test",
        "datasetVersionId": measurement["derivedDataset"]["id"],
        "design": {
            "timeStructure": "cross_sectional",
            "clustering": "none",
            "claimMode": "associational",
        },
        "nodes": [
            {
                "id": "node_x",
                "variableId": measurement["derivedDataset"]["scoreVariables"][0]["id"],
                "label": "X",
                "kind": "scale_score",
                "role": "x",
                "dataType": "continuous",
            },
            {
                "id": "node_m",
                "variableId": measurement["derivedDataset"]["scoreVariables"][1]["id"],
                "label": "M",
                "kind": "scale_score",
                "role": "m",
                "dataType": "continuous",
            },
            {
                "id": "node_y",
                "variableId": item_ids["y_bin"],
                "label": "Y (Binary)",
                "kind": "observed",
                "role": "y",
                "dataType": "binary",
            },
            {
                "id": "node_treatment",
                "variableId": item_ids["treatment"],
                "label": "Treatment",
                "kind": "observed",
                "role": "covariate",
                "dataType": "binary",
            },
            {
                "id": "node_condition",
                "variableId": item_ids["condition"],
                "label": "Condition",
                "kind": "observed",
                "role": "covariate",
                "dataType": "nominal",
                "encoding": {"method": "treatment", "referenceLevel": "A", "levels": ["A", "B", "C"]},
            },
        ],
        "edges": [
            {"id": "edge_x_m", "from": "node_x", "to": "node_m", "kind": "regression", "hypothesis": "H1"},
            {"id": "edge_m_y", "from": "node_m", "to": "node_y", "kind": "regression", "hypothesis": "H2"},
            {"id": "edge_x_y", "from": "node_x", "to": "node_y", "kind": "regression", "hypothesis": "H3"},
        ],
        "moderations": [],
        "covariates": [
            {"nodeId": "node_treatment", "outcomeNodeIds": ["node_y"]},
            {"nodeId": "node_condition", "outcomeNodeIds": ["node_y"]},
        ],
        "estimation": {
            "family": "ols",  # Auto-upgrades to logistic for binary outcomes
            "standardErrors": "hc3",
            "confidenceLevel": 0.90,
            "bootstrap": {
                "enabled": True,
                "replicates": 1000,
                "method": "percentile",
                "seed": 12345,
            },
            "missing": "complete_cases_per_model",
            "centering": {"method": "none", "nodeIds": []},
            "reportScale": "unstandardized_primary",
        },
    }

    current_context = client.get(
        f"/api/v1/projects/{dataset['projectId']}/study-context"
    )
    context_response = client.put(
        f"/api/v1/projects/{dataset['projectId']}/study-context",
        json={
            "expectedRevision": current_context.json()["revision"]
            if current_context.status_code == 200
            else None,
            "context": {
                "schemaVersion": "1.0.0",
                "timeStructure": "cross_sectional",
                "dependenceStructure": "independent",
                "design": "observational",
            },
        },
    )
    assert context_response.status_code == 200, context_response.text
    resolved = client.get(
        f"/api/v1/datasets/{dataset['id']}/resolved-analysis-context"
    ).json()
    model.update(
        {
            "contextHash": resolved["contextHash"],
            "datasetSha256": resolved["dataset"]["sha256"],
            "sampleVersionId": resolved["sample"]["id"],
            "sampleHash": resolved["sample"]["hash"],
            "structureVersionId": resolved["structure"]["id"] if resolved.get("structure") else None,
            "structureHash": resolved["structure"]["hash"] if resolved.get("structure") else None,
            "measurementVersionId": resolved["measurement"]["id"] if resolved.get("measurement") else None,
            "measurementHash": resolved["measurement"]["hash"] if resolved.get("measurement") else None,
        }
    )

    validate_res = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/validate",
        json={"model_spec": model},
    )
    print("VALIDATION RESPONSE:", validate_res.json())

    freeze_response = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={"model_spec": model, "override_reason": "忽略横截面警告。"},
    )
    assert freeze_response.status_code == 200, freeze_response.text
    frozen = freeze_response.json()

    # 5. Run analysis
    analysis_response = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen['version']}/analysis"
    )
    state = _await_analysis(analysis_response)
    result = state["result"]

    # Verify results
    assert len(result["equations"]) == 2
    y_eq = next(eq for eq in result["equations"] if eq["outcomeRole"] == "y")

    # Check R2 and Nagelkerke R2 in Y equation
    assert "rSquared" in y_eq
    assert "nagelkerkeRSquared" in y_eq
    assert y_eq["rSquared"] > 0
    assert y_eq["nagelkerkeRSquared"] > 0

    assert y_eq["modelFamily"] == "binomial_logit"
    assert y_eq["rSquaredType"] == "mcfadden_pseudo_r_squared"
    assert result["provenance"]["standardErrors"] == "hc3"
    assert any(warning["code"] == "BINARY_ENCODING_node_y" for warning in result["warnings"])

    # Y equation coefficients use HC3 with normal-theory inference and report ORs.
    for coef in y_eq["coefficients"]:
        assert coef["confidenceInterval"]["method"] == "hc3_z"
        assert coef["oddsRatio"] > 0
        assert coef["oddsRatioConfidenceInterval"]["lower"] > 0
        if coef["term"] != "(Intercept)":
            assert "averageMarginalEffect" in coef
            assert coef["marginalEffectEstimand"]
            assert coef["marginalEffectConfidenceInterval"]["level"] == pytest.approx(0.90)

    result_by_term = {coefficient["term"]: coefficient for coefficient in y_eq["coefficients"]}
    assert result_by_term["node_m"]["marginalEffectType"] == "continuous_derivative"
    assert result_by_term["node_x"]["marginalEffectType"] == "continuous_derivative"
    assert result_by_term["node_treatment"]["marginalEffectType"] == "discrete"
    assert result_by_term["node_treatment"]["marginalEffectReferenceLevel"] == "0"
    assert result_by_term["node_treatment"]["marginalEffectContrastLevel"] == "1"
    for term, level in (("node_conditionB", "B"), ("node_conditionC", "C")):
        assert result_by_term[term]["marginalEffectType"] == "categorical_contrast"
        assert result_by_term[term]["marginalEffectReferenceLevel"] == "A"
        assert result_by_term[term]["marginalEffectContrastLevel"] == level

    assert result["claimBoundary"]["claimMode"] == "association"
    assert result["claimBoundary"]["causalLanguageAllowed"] is False
    assert result["evidenceGraph"]["effectBindings"]
    indirect = next(effect for effect in result["effects"] if effect["id"] == "effect_indirect")
    assert indirect["edgeIds"] == ["edge_x_m", "edge_m_y"]
    assert indirect["hypothesisIds"] == ["H1", "H2"]
    indirect_binding = next(
        binding for binding in result["evidenceGraph"]["effectBindings"]
        if binding["effectId"] == "effect_indirect"
    )
    assert indirect_binding["edgeIds"] == ["edge_x_m", "edge_m_y"]
    assert indirect_binding["hypothesisIds"] == ["H1", "H2"]
    assert result["bootstrap"]["familyId"] == "process_effects"
    assert result["bootstrap"]["seed"] == 12345

    # Independent NumPy IRLS + HC3 sandwich cross-check for the logit equation.
    settings = get_settings()
    derived = pd.read_parquet(settings.state_root / measurement["derivedDataset"]["storage"])
    design = np.column_stack(
        [
            np.ones(len(derived)),
            derived["scale_m"].to_numpy(dtype=float),
            derived["scale_x"].to_numpy(dtype=float),
            derived["treatment"].to_numpy(dtype=float),
            (derived["condition"].astype(str) == "B").to_numpy(dtype=float),
            (derived["condition"].astype(str) == "C").to_numpy(dtype=float),
        ]
    )
    binary = (derived["y_bin"].to_numpy(dtype=float) == 2).astype(float)
    beta = np.zeros(design.shape[1])
    for _ in range(100):
        probability_values = 1 / (1 + np.exp(-(design @ beta)))
        weights = np.clip(probability_values * (1 - probability_values), 1e-12, None)
        information = design.T @ (design * weights[:, None])
        update = np.linalg.solve(information, design.T @ (binary - probability_values))
        beta += update
        if np.max(np.abs(update)) < 1e-12:
            break
    bread = np.linalg.inv(information)
    leverage = np.sum((design @ bread) * design, axis=1) * weights
    adjusted_score = (binary - probability_values) / (1 - leverage)
    sandwich = (
        bread @ ((design * adjusted_score[:, None]).T @ (design * adjusted_score[:, None])) @ bread
    )
    reference_se = np.sqrt(np.diag(sandwich))
    for index, term in enumerate(["(Intercept)", "node_m", "node_x", "node_treatment", "node_conditionB", "node_conditionC"]):
        assert result_by_term[term]["estimate"] == pytest.approx(beta[index], abs=1e-8)
        assert result_by_term[term]["standardError"] == pytest.approx(reference_se[index], abs=1e-7)

    base_probability = 1 / (1 + np.exp(-(design @ beta)))
    derivative_weight = base_probability * (1 - base_probability)
    for index, term in ((1, "node_m"), (2, "node_x")):
        expected_ame = np.mean(derivative_weight * beta[index])
        assert result_by_term[term]["averageMarginalEffect"] == pytest.approx(expected_ame, abs=1e-8)
    for index, term in ((3, "node_treatment"), (4, "node_conditionB"), (5, "node_conditionC")):
        reference_design = design.copy()
        contrast_design = design.copy()
        if term.startswith("node_condition"):
            reference_design[:, 4:6] = 0
            contrast_design[:, 4:6] = 0
        reference_design[:, index] = 0
        contrast_design[:, index] = 1
        expected_ame = np.mean(
            1 / (1 + np.exp(-(contrast_design @ beta)))
            - 1 / (1 + np.exp(-(reference_design @ beta)))
        )
        assert result_by_term[term]["averageMarginalEffect"] == pytest.approx(expected_ame, abs=1e-8)
