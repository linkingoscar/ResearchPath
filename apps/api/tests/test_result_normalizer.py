"""Unified R-to-Python result normalization tests."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from app.services.result_normalizer import normalize_and_validate, normalize_result_document


def _normalize(document: object) -> dict[str, object]:
    result = normalize_result_document(document)
    assert isinstance(result, dict)
    return result


def test_non_finite_floats_become_none() -> None:
    document = {
        "estimate": float("nan"),
        "nested": {"upper": float("inf"), "lower": float("-inf")},
        "list": [1.5, float("nan"), 3.0],
        "ok": 2.25,
        "text": "keep",
    }
    normalized = _normalize(document)
    assert normalized["estimate"] is None
    nested = normalized["nested"]
    assert isinstance(nested, dict)
    assert nested["upper"] is None
    assert nested["lower"] is None
    values = normalized["list"]
    assert isinstance(values, list)
    assert values[1] is None
    assert values[0] == 1.5
    assert normalized["ok"] == 2.25
    assert normalized["text"] == "keep"


def test_non_finite_floats_survive_json_round_trip() -> None:
    # json.loads parses NaN/Infinity literals into float values; the
    # normalizer must catch exactly those.
    raw = json.loads('{"value": NaN, "other": Infinity, "fine": 1.25}')
    normalized = _normalize(raw)
    assert normalized["value"] is None
    assert normalized["other"] is None
    assert normalized["fine"] == 1.25


def test_math_isfinite_covers_all_ieee_edge_cases() -> None:
    assert not math.isfinite(float("nan"))
    assert not math.isfinite(float("inf"))
    assert not math.isfinite(float("-inf"))
    assert math.isfinite(1e-300)
    assert math.isfinite(0.0)


def test_normalize_and_validate_accepts_schema_conformant_document() -> None:
    document = {"value": 1.0, "label": "x"}
    schema_path = Path(__file__).parents[1] / "app" / "contracts_test_fixture.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"value": {"type": "number"}, "label": {"type": "string"}},
                "required": ["value"],
            }
        ),
        encoding="utf-8",
    )
    try:
        normalized = normalize_and_validate(document, schema_path)
        assert normalized == document
    finally:
        schema_path.unlink(missing_ok=True)


def test_normalize_and_validate_rejects_schema_violation() -> None:
    from app.contracts import ContractValidationError

    document = {"value": "not-a-number"}
    schema_path = Path(__file__).parents[1] / "app" / "contracts_test_fixture.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"value": {"type": "number"}},
                "required": ["value"],
            }
        ),
        encoding="utf-8",
    )
    try:
        with pytest.raises(ContractValidationError):
            normalize_and_validate(document, schema_path)
    finally:
        schema_path.unlink(missing_ok=True)


def test_normalize_and_validate_records_non_finite_paths() -> None:
    document = {
        "value": 1.0,
        "label": "x",
        "warnings": [],
        "provenance": {"engine": "test"},
        "result": {"a/b": [float("inf"), None, float("nan")]},
    }
    schema_path = Path(__file__).parents[1] / "app" / "contracts_test_fixture.json"
    schema_path.write_text(json.dumps({"type": "object"}), encoding="utf-8")
    try:
        normalized = normalize_and_validate(document, schema_path)
        provenance = normalized["provenance"]
        assert isinstance(provenance, dict)
        assert provenance["nonFiniteValues"] == [
            {"path": "/result/a~1b/0", "originalKind": "Inf"},
            {"path": "/result/a~1b/2", "originalKind": "NaN"},
        ]
        warnings = normalized["warnings"]
        assert isinstance(warnings, list)
        assert warnings[-1]["code"] == "NON_FINITE_RESULT_VALUE"
    finally:
        schema_path.unlink(missing_ok=True)
