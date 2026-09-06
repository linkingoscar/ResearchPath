from __future__ import annotations

import copy

import pytest

from app.advanced_contracts import PowerAnalysisSpec
from app.contracts import (
    ContractValidationError,
    canonical_model_hash,
    load_json,
    validate_contract,
)
from app.semantics import SemanticValidationError, validate_m0_mediation
from app.settings import get_settings


def test_demo_model_passes_schema_and_semantic_validation() -> None:
    settings = get_settings()
    model = load_json(settings.demo_model_path)

    validate_contract(model, settings.model_schema_path)
    validate_m0_mediation(model)


def test_canvas_position_does_not_change_statistical_hash() -> None:
    settings = get_settings()
    model = load_json(settings.demo_model_path)
    moved = copy.deepcopy(model)
    moved["canvas"]["positions"]["node_x"]["x"] = 999

    assert canonical_model_hash(model) == canonical_model_hash(moved)


def test_array_order_does_not_change_statistical_hash() -> None:
    settings = get_settings()
    model = load_json(settings.demo_model_path)
    reordered = copy.deepcopy(model)
    reordered["nodes"] = list(reversed(reordered["nodes"]))
    reordered["edges"] = list(reversed(reordered["edges"]))

    assert canonical_model_hash(model) == canonical_model_hash(reordered)


def test_invalid_role_is_rejected_by_schema() -> None:
    settings = get_settings()
    model = load_json(settings.demo_model_path)
    model["nodes"][0]["role"] = "predictor"

    with pytest.raises(ContractValidationError):
        validate_contract(model, settings.model_schema_path)


def test_missing_mediation_edge_is_rejected_semantically() -> None:
    settings = get_settings()
    model = load_json(settings.demo_model_path)
    model["edges"] = model["edges"][:-1]

    with pytest.raises(SemanticValidationError):
        validate_m0_mediation(model)


def _advanced_power_schema(settings) -> dict[str, object]:
    spec = PowerAnalysisSpec(
        analysis_id="power_ci_width",
        name="precision check",
        family="power_analysis",
        design_family="regression",
        solve_for="ci_width",
        targetCIWidth=0.5,
        sd=1.0,
    )
    return spec.model_dump(by_alias=True, mode="json")


def test_advanced_power_ci_width_passes_both_contract_layers() -> None:
    settings = get_settings()
    payload = _advanced_power_schema(settings)
    validate_contract(payload, settings.advanced_spec_schema_path)
    PowerAnalysisSpec.model_validate(payload)


def test_advanced_schema_rejects_unimplemented_solve_for() -> None:
    settings = get_settings()
    payload = _advanced_power_schema(settings)
    payload["solveFor"] = "tost_power"
    with pytest.raises(ContractValidationError):
        validate_contract(payload, settings.advanced_spec_schema_path)


def test_advanced_schema_rejects_unsupported_precision_fields() -> None:
    settings = get_settings()
    payload = _advanced_power_schema(settings)
    payload["lowBound"] = 0
    payload["highBound"] = 1
    with pytest.raises(ContractValidationError):
        validate_contract(payload, settings.advanced_spec_schema_path)
