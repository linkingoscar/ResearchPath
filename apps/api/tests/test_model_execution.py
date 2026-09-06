from __future__ import annotations

import hashlib
import json
import time
from io import BytesIO
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest
from _model_execution_helpers import _moderated_mediation_median_reference, _process_percentile
from model_test_helpers import _await_analysis, _model_dataset, _spec, client
from moderation_assertions import assert_unified_moderation

from app.settings import get_settings


def test_nominal_covariate_is_treatment_encoded_end_to_end() -> None:
    dataset, measurement = _model_dataset(group_count=3)
    model = _spec("model_4", dataset, measurement)
    group = next(
        variable for variable in dataset["variables"] if variable["originalName"] == "group"
    )
    model["nodes"].append(
        {
            "id": "node_cov_group",
            "variableId": group["id"],
            "label": "职业类别",
            "kind": "observed",
            "role": "covariate",
            "dataType": "nominal",
            "encoding": {"method": "treatment", "referenceLevel": "A", "levels": ["A", "B", "C"]},
        }
    )
    model["covariates"].append({"nodeId": "node_cov_group", "outcomeNodeIds": ["node_y"]})
    model["estimation"]["bootstrap"]["replicates"] = 1000

    validation = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/validate",
        json={"model_spec": model},
    )
    assert validation.status_code == 200, validation.text
    assert validation.json()["valid"] is True, validation.json()["errors"]
    frozen = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={
            "model_spec": model,
            "override_reason": "横截面关联模型，仅用于验证分类控制变量编码。",
        },
    )
    assert frozen.status_code == 200, frozen.text
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen.json()['version']}/analysis"
    )
    result = _await_analysis(response)["result"]
    y_equation = next(item for item in result["equations"] if item["id"] == "equation_y")
    terms = {row["term"] for row in y_equation["coefficients"]}
    assert {"node_cov_groupB", "node_cov_groupC"}.issubset(terms)


def test_frozen_model_1_runs_hc3_and_moderation_probes_on_derived_data() -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_1", dataset, measurement)
    freeze_response = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={"model_spec": model},
    )
    assert freeze_response.status_code == 200, freeze_response.text
    frozen = freeze_response.json()

    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen['version']}/analysis"
    )

    state = _await_analysis(response)
    result = state["result"]
    assert result["run"]["template"] == "model_1"
    assert result["sampleFlow"]["included"] == 40
    assert len(result["probes"]) == 3
    assert result["johnsonNeyman"] is not None
    assert len(result["moderationPlots"]) == 1
    for line in result["moderationPlots"][0]["lines"]:
        assert len(line["confidenceLower"]) == len(line["confidenceUpper"]) == 2
        assert all(
            lower <= prediction <= upper
            for lower, prediction, upper in zip(
                line["confidenceLower"],
                line["predictedValues"],
                line["confidenceUpper"],
                strict=True,
            )
        )

    settings = get_settings()
    data = pd.read_parquet(settings.state_root / measurement["derivedDataset"]["storage"])
    x = data["scale_x"].to_numpy(dtype=float)
    y = data["scale_y"].to_numpy(dtype=float)
    w = data["scale_w"].to_numpy(dtype=float)
    age = data["age"].to_numpy(dtype=float)
    x = x - x.mean()
    w = w - w.mean()
    design = np.column_stack([np.ones(len(x)), x, w, x * w, age])
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    residual = y - design @ beta
    hat = np.sum(design * (design @ np.linalg.inv(design.T @ design)), axis=1)
    adjusted = residual / (1 - hat)
    bread = np.linalg.inv(design.T @ design)
    covariance = bread @ ((design * adjusted[:, None]).T @ (design * adjusted[:, None])) @ bread
    coefficients = {row["term"]: row for row in result["equations"][0]["coefficients"]}
    assert coefficients["node_x"]["estimate"] == pytest.approx(beta[1], abs=1e-8)
    assert coefficients["term_interaction"]["estimate"] == pytest.approx(beta[3], abs=1e-8)
    assert coefficients["term_interaction"]["standardError"] == pytest.approx(
        np.sqrt(covariance[3, 3]), abs=1e-8
    )
    assert_unified_moderation(result, data, beta, covariance)

    for include_data in (False, True):
        exported = client.get(
            f"/api/v1/analyses/{state['id']}/export",
            params={"include_data": str(include_data).lower()},
        )
        assert exported.status_code == 200, exported.text
        with ZipFile(BytesIO(exported.content)) as archive:
            names = archive.namelist()
            root = names[0].split("/")[0]
            required = {
                f"{root}/manifest.json",
                f"{root}/result-bundle.json",
                f"{root}/report/report.md",
                f"{root}/report/figures/model-path.svg",
                f"{root}/report/figures/model-path.png",
                f"{root}/report/figures/simple-slope-1.svg",
                f"{root}/report/figures/simple-slope-1.png",
                f"{root}/specifications/dataset-version.json",
                f"{root}/specifications/measurement-version.json",
                f"{root}/specifications/model-version.json",
                f"{root}/reproducibility/run-analysis.R",
                f"{root}/reproducibility/reproduce.ps1",
                f"{root}/ro-crate-metadata.json",
                f"{root}/replay/verify-package.py",
            }
            assert required.issubset(names)
            report_markdown = archive.read(f"{root}/report/report.md").decode("utf-8")
            assert "## 条件效应与简单斜率" in report_markdown
            assert "## Johnson–Neyman 区域" in report_markdown
            assert (f"{root}/data/analysis-data.csv" in names) is include_data
            manifest = json.loads(archive.read(f"{root}/manifest.json"))
            assert manifest["includeData"] is include_data
            bundled_result = json.loads(archive.read(f"{root}/result-bundle.json"))
            assert bundled_result["replay"]["packageGenerated"] is True
            assert bundled_result["replay"]["dataIncluded"] is include_data
            crate = json.loads(archive.read(f"{root}/ro-crate-metadata.json"))
            crate_values = {
                item["name"]: item["value"]
                for item in crate["@graph"]
                if item.get("@type") == "PropertyValue"
            }
            assert crate_values["cleanRoomVerified"] is False
            assert crate_values["dataIncluded"] is include_data
            for item in manifest["files"]:
                payload = archive.read(f"{root}/{item['path']}")
                assert hashlib.sha256(payload).hexdigest() == item["sha256"]
            if include_data:
                input_json = json.loads(archive.read(f"{root}/reproducibility/input.json"))
                data_item = next(
                    item for item in manifest["files"] if item["path"] == "data/analysis-data.csv"
                )
                assert input_json["dataSha256"] == data_item["sha256"]


@pytest.mark.parametrize(
    ("template", "expected_interactions"),
    [("model_2", 2), ("model_3", 3)],
)
def test_two_moderator_models_run_joint_conditional_effect_grid(
    template: str,
    expected_interactions: int,
) -> None:
    dataset, measurement = _model_dataset()
    model = _spec(template, dataset, measurement)
    frozen = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={"model_spec": model},
    ).json()
    result = _await_analysis(
        client.post(
            f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen['version']}/analysis"
        )
    )["result"]

    assert result["run"]["template"] == template
    assert len(result["probes"]) == 9
    assert all("secondaryModeratorValue" in probe for probe in result["probes"])
    assert len(result["moderationPlots"]) == 2
    interactions = [effect for effect in result["effects"] if effect["type"] == "interaction"]
    assert len(interactions) == expected_interactions
    assert result["johnsonNeyman"] is None

    settings = get_settings()
    data = pd.read_parquet(settings.state_root / measurement["derivedDataset"]["storage"])
    x = data["scale_x"].to_numpy(dtype=float)
    y = data["scale_y"].to_numpy(dtype=float)
    w = data["scale_w"].to_numpy(dtype=float)
    z = data["age"].to_numpy(dtype=float)
    xc, wc, zc = x - x.mean(), w - w.mean(), z - z.mean()
    columns = [np.ones(len(x)), xc, wc, xc * wc, zc, xc * zc]
    if template == "model_3":
        columns.extend([wc * zc, xc * wc * zc])
    beta = np.linalg.lstsq(np.column_stack(columns), y, rcond=None)[0]
    w_median = _process_percentile(w, 0.50) - w.mean()
    z_median = _process_percentile(z, 0.50) - z.mean()
    reference = beta[1] + beta[3] * w_median + beta[5] * z_median
    if template == "model_3":
        reference += beta[7] * w_median * z_median
    median_probe = next(
        probe for probe in result["probes"] if probe["label"] == "W_median__Z_median"
    )
    assert median_probe["effect"] == pytest.approx(reference, abs=1e-8)
    y_coefficients = {
        row["term"]: row["estimate"] for row in result["equations"][0]["coefficients"]
    }
    assert y_coefficients["term_x_w"] == pytest.approx(beta[3], abs=1e-8)
    assert y_coefficients["term_x_z"] == pytest.approx(beta[5], abs=1e-8)
    if template == "model_3":
        assert y_coefficients["term_x_w_z"] == pytest.approx(beta[7], abs=1e-8)


@pytest.mark.parametrize("template", ["model_7", "model_8", "model_14", "model_15"])
def test_moderated_mediation_runs_conditional_indirect_bootstrap(template: str) -> None:
    dataset, measurement = _model_dataset()
    model = _spec(template, dataset, measurement)
    model["estimation"]["bootstrap"]["replicates"] = 1000
    frozen_response = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={
            "model_spec": model,
            "override_reason": "横截面模型仅检验条件间接关联，不作因果解释。",
        },
    )
    assert frozen_response.status_code == 200, frozen_response.text
    frozen = frozen_response.json()

    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen['version']}/analysis"
    )

    result = _await_analysis(response)["result"]
    conditional = [effect for effect in result["effects"] if effect["type"] == "conditional"]
    index = next(effect for effect in result["effects"] if effect["type"] == "index")
    assert result["run"]["template"] == template
    assert len(conditional) == 3
    assert all(effect["confidenceInterval"]["replicates"] == 1000 for effect in conditional)
    assert index["confidenceInterval"]["lower"] < index["confidenceInterval"]["upper"]

    reference = _moderated_mediation_median_reference(measurement, template)
    conditional_at_median = next(
        effect for effect in conditional if effect["label"] == "conditional_indirect_median"
    )
    assert conditional_at_median["estimate"] == pytest.approx(reference, abs=1e-8)


def test_model_5_runs_indirect_bootstrap_and_direct_effect_probe() -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_5", dataset, measurement)
    model["estimation"]["bootstrap"]["replicates"] = 1000
    frozen = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={
            "model_spec": model,
            "override_reason": "横截面模型仅检验间接关联与条件直接效应。",
        },
    ).json()

    result = _await_analysis(
        client.post(
            f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen['version']}/analysis"
        )
    )["result"]

    indirect = next(effect for effect in result["effects"] if effect["id"] == "effect_indirect")
    assert result["run"]["template"] == "model_5"
    assert indirect["confidenceInterval"]["replicates"] == 1000
    assert len(result["probes"]) == 3
    assert len(result["moderationPlots"]) == 1
    assert not any(effect["type"] in {"conditional", "index"} for effect in result["effects"])


@pytest.mark.parametrize(
    ("template", "expected_plots"),
    [("model_58", 2), ("model_59", 3)],
)
def test_dual_stage_moderation_bootstraps_nonlinear_conditional_indirect_effects(
    template: str,
    expected_plots: int,
) -> None:
    dataset, measurement = _model_dataset()
    model = _spec(template, dataset, measurement)
    model["estimation"]["bootstrap"]["replicates"] = 1000
    frozen = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={
            "model_spec": model,
            "override_reason": "横截面模型仅检验非线性条件间接关联。",
        },
    ).json()

    result = _await_analysis(
        client.post(
            f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen['version']}/analysis"
        )
    )["result"]
    conditional = [effect for effect in result["effects"] if effect["type"] == "conditional"]

    assert result["run"]["template"] == template
    assert len(conditional) == 3
    assert len(result["moderationPlots"]) == expected_plots
    assert all(effect["confidenceInterval"]["replicates"] == 1000 for effect in conditional)
    assert not any(effect["type"] == "index" for effect in result["effects"])

    settings = get_settings()
    data = pd.read_parquet(settings.state_root / measurement["derivedDataset"]["storage"])
    x = data["scale_x"].to_numpy(dtype=float)
    m = data["scale_m"].to_numpy(dtype=float)
    y = data["scale_y"].to_numpy(dtype=float)
    w = data["scale_w"].to_numpy(dtype=float)
    age = data["age"].to_numpy(dtype=float)
    x_centered = x - x.mean()
    m_centered = m - m.mean()
    w_centered = w - w.mean()
    m_design = np.column_stack(
        [np.ones(len(x)), x_centered, w_centered, x_centered * w_centered, age]
    )
    y_columns = [
        np.ones(len(x)),
        x_centered,
        m_centered,
        w_centered,
        m_centered * w_centered,
    ]
    if template == "model_59":
        y_columns.append(x_centered * w_centered)
    y_columns.append(age)
    m_beta = np.linalg.lstsq(m_design, m_centered, rcond=None)[0]
    y_beta = np.linalg.lstsq(np.column_stack(y_columns), y, rcond=None)[0]
    w_median = _process_percentile(w, 0.50) - w.mean()
    reference_at_median = (m_beta[1] + m_beta[3] * w_median) * (y_beta[2] + y_beta[4] * w_median)
    conditional_at_median = next(
        effect for effect in conditional if effect["label"] == "conditional_indirect_median"
    )
    assert conditional_at_median["estimate"] == pytest.approx(reference_at_median, abs=1e-8)


@pytest.mark.parametrize(
    ("template", "expected_plots"),
    [("model_21", 2), ("model_22", 3)],
)
def test_two_moderator_staged_mediation_bootstraps_joint_conditional_indirect_effects(
    template: str,
    expected_plots: int,
) -> None:
    dataset, measurement = _model_dataset()
    model = _spec(template, dataset, measurement)
    model["estimation"]["bootstrap"]["replicates"] = 1000
    frozen = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={
            "model_spec": model,
            "override_reason": "横截面模型仅检验 W、Z 联合条件下的间接关联。",
        },
    ).json()

    result = _await_analysis(
        client.post(
            f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen['version']}/analysis"
        )
    )["result"]
    conditional = [effect for effect in result["effects"] if effect["type"] == "conditional"]

    assert result["run"]["template"] == template
    assert len(conditional) == 9
    assert len(result["moderationPlots"]) == expected_plots
    assert len(result["probes"]) == expected_plots * 3
    assert all(effect["confidenceInterval"]["replicates"] == 1000 for effect in conditional)
    assert not any(effect["type"] == "index" for effect in result["effects"])

    settings = get_settings()
    data = pd.read_parquet(settings.state_root / measurement["derivedDataset"]["storage"])
    x = data["scale_x"].to_numpy(dtype=float)
    m = data["scale_m"].to_numpy(dtype=float)
    y = data["scale_y"].to_numpy(dtype=float)
    w = data["scale_w"].to_numpy(dtype=float)
    z = data["age"].to_numpy(dtype=float)
    x_centered = x - x.mean()
    m_centered = m - m.mean()
    w_centered = w - w.mean()
    z_centered = z - z.mean()
    m_design = np.column_stack([np.ones(len(x)), x_centered, w_centered, x_centered * w_centered])
    y_columns = [
        np.ones(len(x)),
        x_centered,
        m_centered,
        z_centered,
        m_centered * z_centered,
    ]
    if template == "model_22":
        y_columns.extend([w_centered, x_centered * w_centered])
    m_beta = np.linalg.lstsq(m_design, m_centered, rcond=None)[0]
    y_beta = np.linalg.lstsq(np.column_stack(y_columns), y, rcond=None)[0]
    w_median = _process_percentile(w, 0.50) - w.mean()
    z_median = _process_percentile(z, 0.50) - z.mean()
    reference_at_medians = (m_beta[1] + m_beta[3] * w_median) * (y_beta[2] + y_beta[4] * z_median)
    conditional_at_medians = next(
        effect
        for effect in conditional
        if effect["label"] == "conditional_indirect_W_median__Z_median"
    )
    assert conditional_at_medians["estimate"] == pytest.approx(reference_at_medians, abs=1e-8)


def test_background_job_can_really_cancel_bootstrap() -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_7", dataset, measurement)
    model["estimation"]["bootstrap"]["replicates"] = 50000
    frozen_response = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={"model_spec": model, "override_reason": "取消能力压力测试。"},
    )
    frozen = frozen_response.json()
    started = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen['version']}/analysis"
    )
    assert started.status_code == 202
    run_id = started.json()["id"]
    deadline = time.monotonic() + 10
    state = started.json()
    while time.monotonic() < deadline and state["status"] == "queued":
        time.sleep(0.03)
        state = client.get(f"/api/v1/analyses/{run_id}").json()
    assert state["status"] == "running"
    cancellation_started = time.monotonic()
    cancelled = client.delete(f"/api/v1/analyses/{run_id}")
    assert cancelled.status_code == 200
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/analyses/{run_id}").json()
        if state["status"] == "cancelled":
            break
        time.sleep(0.05)
    assert state["status"] == "cancelled", state
    assert state["result"] is None
    assert time.monotonic() - cancellation_started < 2.5


def test_seeded_bootstrap_is_reproducible_and_within_performance_budget() -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_7", dataset, measurement)
    model["estimation"]["bootstrap"]["replicates"] = 1000
    frozen = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={"model_spec": model, "override_reason": "固定种子复现验证。"},
    ).json()
    endpoint = f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen['version']}/analysis"
    started_at = time.monotonic()
    first = _await_analysis(client.post(endpoint))["result"]
    second = _await_analysis(client.post(endpoint))["result"]
    duration = time.monotonic() - started_at
    first_effects = [
        (item["id"], item["estimate"], item.get("confidenceInterval")) for item in first["effects"]
    ]
    second_effects = [
        (item["id"], item["estimate"], item.get("confidenceInterval")) for item in second["effects"]
    ]
    assert first_effects == second_effects
    assert duration < 30, f"两次 1000 次 bootstrap 用时 {duration:.2f}s，超过 30s 门槛"


def test_5000_replication_bootstrap_meets_performance_budget() -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_7", dataset, measurement)
    model["estimation"]["bootstrap"]["replicates"] = 5000
    frozen = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={"model_spec": model, "override_reason": "性能预算验证。"},
    ).json()
    started_at = time.monotonic()
    state = _await_analysis(
        client.post(
            f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{frozen['version']}/analysis"
        )
    )
    duration = time.monotonic() - started_at
    assert state["completedReplicates"] == 5000
    assert duration < 20, f"5000 次 bootstrap 用时 {duration:.2f}s，超过 20s 门槛"
