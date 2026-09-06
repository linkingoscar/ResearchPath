from __future__ import annotations

import pytest
from model_test_helpers import client
from study_plan_test_helpers import typed_plan_payload


def _context(design: str) -> dict[str, str]:
    return {
        "schemaVersion": "1.0.0",
        "timeStructure": "cross_sectional",
        "dependenceStructure": "independent",
        "design": design,
    }


def _payload(
    context: dict[str, str],
    *,
    slice_id: str,
    causal_target: bool,
    roles: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload = typed_plan_payload(context, slice_id=slice_id, roles=roles)
    estimands = payload["estimands"]
    assert isinstance(estimands, list)
    estimand = estimands[0]
    assert isinstance(estimand, dict)
    estimand["causalTarget"] = causal_target
    return payload


@pytest.mark.parametrize(
    ("design", "slice_id", "roles"),
    [
        ("observational", "empirical.cross_sectional.hierarchical_regression", None),
        ("observational", "model.process_catalog", None),
        (
            "randomized",
            "experimental_design.factorial_anova.long.single_outcome",
            [{"key": "treatment", "label": "处理", "role": "treatment", "structureRole": "treatmentId"}],
        ),
    ],
)
def test_causal_target_draft_is_saveable_but_freeze_fails_closed(
    design: str,
    slice_id: str,
    roles: list[dict[str, object]] | None,
) -> None:
    dataset = client.post("/api/v1/demo/load").json()["dataset"]
    created = client.post(
        f"/api/v1/projects/{dataset['projectId']}/study-plans",
        json={
            "payload": _payload(
                _context(design),
                slice_id=slice_id,
                causal_target=True,
                roles=roles,
            )
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"

    frozen = client.post(f"/api/v1/study-plans/{created.json()['id']}/freeze")
    assert frozen.status_code == 409, frozen.text
    detail = frozen.json()["detail"]
    assert detail["code"] == "STUDY_PLAN_CAUSAL_TARGET_UNSUPPORTED"
    assert detail["message"].startswith("STUDY_PLAN_CAUSAL_TARGET_UNSUPPORTED:")
    assert "causalTarget" in detail["message"]


def test_non_causal_estimand_freezes_with_current_capability() -> None:
    dataset = client.post("/api/v1/demo/load").json()["dataset"]
    created = client.post(
        f"/api/v1/projects/{dataset['projectId']}/study-plans",
        json={
            "payload": _payload(
                _context("observational"),
                slice_id="empirical.cross_sectional.hierarchical_regression",
                causal_target=False,
            )
        },
    )
    assert created.status_code == 201, created.text

    frozen = client.post(f"/api/v1/study-plans/{created.json()['id']}/freeze")
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["status"] == "frozen"
