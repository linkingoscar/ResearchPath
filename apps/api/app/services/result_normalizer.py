"""R-to-Python result normalization.

Every R result document flows through :func:`normalize_result_document`
before contract validation, so the four R entrypoints (model analysis, SEM,
empirical analysis, advanced analysis) share one normalization policy:

* non-finite floats (``NaN``/``Infinity`` from ``json.loads``) become ``None``
  so schema validation rejects or accepts them consistently instead of
  tripping on IEEE edge cases;
* the document must be a JSON object (mapping) at the top level.

Schema gating itself stays at the call sites via ``validate_contract``
against ``specs/*.schema.json`` — this module only guarantees the document
shape the schemas can reason about. Types stay free of explicit ``Any`` so
the repository's explicit-Any budget is untouched.
"""

from __future__ import annotations

import math

from app.contracts import ContractValidationError, validate_contract
from app.services.repository_io import JsonObject


def _pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _normalize_with_diagnostics(
    document: object, path: str = ""
) -> tuple[object, list[dict[str, str]]]:
    if isinstance(document, float):
        if math.isfinite(document):
            return document, []
        kind = "NaN" if math.isnan(document) else "Inf" if document > 0 else "-Inf"
        return None, [{"path": path or "/", "originalKind": kind}]
    if isinstance(document, list):
        list_values: list[object] = []
        diagnostics: list[dict[str, str]] = []
        for index, item in enumerate(document):
            value, item_diagnostics = _normalize_with_diagnostics(item, f"{path}/{index}")
            list_values.append(value)
            diagnostics.extend(item_diagnostics)
        return list_values, diagnostics
    if isinstance(document, dict):
        mapped_values: dict[object, object] = {}
        diagnostics: list[dict[str, str]] = []
        for key, item in document.items():
            item_path = f"{path}/{_pointer_segment(str(key))}"
            value, item_diagnostics = _normalize_with_diagnostics(item, item_path)
            mapped_values[key] = value
            diagnostics.extend(item_diagnostics)
        return mapped_values, diagnostics
    return document, []


def normalize_result_document(document: object) -> object:
    """Recursively replace non-finite floats with ``None``."""
    return _normalize_with_diagnostics(document)[0]


def normalize_and_validate(document: JsonObject, schema_path) -> JsonObject:
    """Normalize the document and return the normalized document.

    Raises ContractValidationError when the normalized document is not a
    JSON object or does not satisfy the schema at ``schema_path``.
    """
    normalized, diagnostics = _normalize_with_diagnostics(document)
    if not isinstance(normalized, dict):
        raise ContractValidationError(["result document must be a JSON object"])
    if diagnostics:
        provenance = normalized.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
            normalized["provenance"] = provenance
        provenance["nonFiniteValues"] = diagnostics
        warnings = normalized.get("warnings")
        if not isinstance(warnings, list):
            warnings = []
            normalized["warnings"] = warnings
        warnings.append(
            {
                "code": "NON_FINITE_RESULT_VALUE",
                "severity": "warning",
                "message": (
                    f"{len(diagnostics)} non-finite result values became null; "
                    "paths and original kinds are recorded in provenance.nonFiniteValues."
                ),
            }
        )
    validate_contract(normalized, schema_path)
    return normalized
