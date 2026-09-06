from __future__ import annotations

import pytest
from model_test_helpers import _model_dataset, _spec, client

from app.services import model_service
from app.services.dataset_repository import DatasetRepository


@pytest.mark.parametrize(
    "template",
    [
        "model_1",
        "model_2",
        "model_3",
        "model_4",
        "model_5",
        "model_6",
        "model_7",
        "model_8",
        "model_14",
        "model_15",
        "model_21",
        "model_22",
        "model_58",
        "model_59",
    ],
)
def test_supported_templates_validate_against_derived_data(template: str) -> None:
    dataset, measurement = _model_dataset()
    model = _spec(template, dataset, measurement)

    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/validate",
        json={"model_spec": model},
    )

    assert response.status_code == 200, response.text
    validation = response.json()
    assert validation["valid"] is True, validation["errors"]
    assert validation["template"] == template
    assert validation["matchStatus"] == "exact"
    assert validation["executionAvailable"] is True
    assert validation["sampleFlow"]["included"] == 40


@pytest.mark.parametrize("template", ["model_21", "model_22"])
def test_two_moderator_mediation_with_reversed_roles_is_valid_but_unnumbered(
    template: str,
) -> None:
    dataset, measurement = _model_dataset()
    model = _spec(template, dataset, measurement)
    model["moderations"][0]["moderatorNodeId"] = "node_z"
    model["moderations"][1]["moderatorNodeId"] = "node_w"

    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/validate",
        json={"model_spec": model},
    )

    assert response.status_code == 200, response.text
    validation = response.json()
    assert validation["valid"] is True
    assert validation["matchStatus"] == "custom"
    assert validation["processModelNumber"] is None
    assert validation["executionAvailable"] is False


def test_canvas_only_change_reuses_precheck_without_reading_parquet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_4", dataset, measurement)
    DatasetRepository.clear_precheck_cache()
    original_read = model_service.pd.read_parquet
    reads = 0

    def counted_read(*args, **kwargs):
        nonlocal reads
        reads += 1
        return original_read(*args, **kwargs)

    monkeypatch.setattr(model_service.pd, "read_parquet", counted_read)
    endpoint = f"/api/v1/datasets/{dataset['id']}/models/validate"
    first = client.post(endpoint, json={"model_spec": model})
    moved = {**model, "canvas": {"positions": {"node_x": {"x": 999, "y": 999}}}}
    second = client.post(endpoint, json={"model_spec": moved})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert reads == 1


def test_missing_model_draft_is_an_empty_optional_resource() -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_4", dataset, measurement)

    response = client.get(f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/draft")

    assert response.status_code == 200
    assert response.json() is None


def test_cycle_and_wrong_target_are_rejected_but_draft_is_saved() -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_4", dataset, measurement)
    model["edges"].append(
        {"id": "edge_y_x", "from": "node_y", "to": "node_x", "kind": "regression"}
    )

    draft = client.put(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/draft",
        json={"model_spec": model},
    )

    assert draft.status_code == 200, draft.text
    assert draft.json()["status"] == "draft"
    assert draft.json()["validation"]["valid"] is False
    assert any("循环" in error for error in draft.json()["validation"]["errors"])
    restored = client.get(f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/draft")
    assert restored.status_code == 200, restored.text
    assert restored.json()["modelHash"] == draft.json()["modelHash"]
    assert restored.json()["modelSpec"] == model
    frozen = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={"model_spec": model},
    )
    assert frozen.status_code == 422


def test_freeze_requires_warning_override_and_creates_immutable_versions() -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_4", dataset, measurement)
    endpoint = f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze"

    rejected = client.post(endpoint, json={"model_spec": model})
    assert rejected.status_code == 422
    assert "覆盖理由" in rejected.json()["detail"]["message"]

    first = client.post(
        endpoint,
        json={"model_spec": model, "override_reason": "横截面设计仅作关联性探索，不作因果解释。"},
    )
    second = client.post(
        endpoint,
        json={"model_spec": model, "override_reason": "按预先设定的关联性分析方案复核。"},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["version"] == 1
    assert second.json()["version"] == 2
    assert first.json()["modelHash"] == second.json()["modelHash"]


def test_recognized_but_unsupported_model_can_freeze_but_cannot_run() -> None:
    dataset, measurement = _model_dataset()
    model = _spec("model_21", dataset, measurement)
    model["moderations"][0]["moderatorNodeId"] = "node_z"
    model["moderations"][1]["moderatorNodeId"] = "node_w"
    frozen = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={
            "model_spec": model,
            "override_reason": "保存自定义拓扑用于研究设计记录，不执行估计。",
        },
    )

    assert frozen.status_code == 200, frozen.text
    validation = frozen.json()["validation"]
    assert validation["valid"] is True
    assert validation["executionAvailable"] is False

    analysis = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}"
        f"/versions/{frozen.json()['version']}/analysis"
    )
    assert analysis.status_code == 422
    assert "暂" in analysis.json()["detail"]["message"] or "未" in analysis.json()["detail"]["message"]
