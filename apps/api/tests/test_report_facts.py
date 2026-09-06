from __future__ import annotations

import copy

import pytest

from app.advanced_contracts import EffectSize, PowerAnalysisSpec
from app.contracts import ContractValidationError, validate_contract
from app.services.advanced_export import build_advanced_paper_report, build_advanced_paper_tables
from app.services.report_facts import ensure_report_facts, resolve_report_facts
from app.settings import get_settings


def _bundle(estimate: float = 1.45) -> dict[str, object]:
    return {
        "schemaVersion": "0.1.0",
        "run": {
            "id": "run_report_facts",
            "status": "succeeded",
            "analysisId": "report_facts",
            "family": "experimental_design",
            "specHash": "a" * 64,
            "durationMilliseconds": 120,
        },
        "sampleFlow": {"original": 100, "included": 95, "excluded": 5, "missingMethod": "complete_cases"},
        "estimates": [
            {
                "id": "b1",
                "label": "FactorA",
                "estimate": estimate,
                "standardError": 0.2,
                "statistic": 7.25,
                "degreesOfFreedom": 1,
                "pValue": 0.008,
                "scale": "raw",
            }
        ],
        "diagnostics": [],
        "warnings": [],
        "reportFacts": [
            {
                "factId": "fact_1",
                "kind": "estimate",
                "sourceResultId": "run_report_facts",
                "sourcePaths": ["/estimates/0/estimate"],
                "semanticRole": "primary_hypothesis_result",
                "presentationHints": {"preferredLabel": "H1"},
                "templates": {"zh-CN": "{preferredLabel} = {estimate}"},
            }
        ],
        "provenance": {
            "engine": "R",
            "engineVersion": "4.3.0",
            "softwareVersions": {},
            "dataSha256": "b" * 64,
            "seed": 12345,
            "specVersion": "0.1.0",
            "family": "experimental_design",
            "specHash": "a" * 64,
        },
        "familyResult": {
            "family": "experimental_design",
            "omnibusTests": [],
            "estimatedMarginalMeans": [],
            "contrasts": [],
        },
    }


def test_report_facts_are_reference_only_and_follow_changed_source_values() -> None:
    result = _bundle()
    validate_contract(result, get_settings().advanced_result_schema_path)
    initial = next(table for table in build_advanced_paper_tables(result) if table["title"] == "报告事实")
    assert initial["rows"][0]["value"] == 1.45

    result["estimates"][0]["estimate"] = 2.75  # type: ignore[index]
    updated = next(table for table in build_advanced_paper_tables(result) if table["title"] == "报告事实")
    assert updated["rows"][0]["value"] == 2.75
    spec = PowerAnalysisSpec(
        analysis_id="report_facts",
        name="Report facts",
        family="power_analysis",
        design_family="regression",
        effect_size=EffectSize(metric="cohens_f2", value=0.15),
    )
    report = build_advanced_paper_report(
        spec, result, build_advanced_paper_tables(result), include_data=False
    )
    assert "2.75" in report
    assert "1.45" not in report


def test_report_fact_values_are_rejected_and_missing_pointers_fail_closed() -> None:
    with_values = _bundle()
    with_values["reportFacts"][0]["values"] = {"estimate": 1.45}  # type: ignore[index]
    with pytest.raises(ContractValidationError):
        validate_contract(with_values, get_settings().advanced_result_schema_path)

    broken = copy.deepcopy(_bundle())
    broken["reportFacts"][0]["sourcePaths"] = ["/estimates/4/estimate"]  # type: ignore[index]
    with pytest.raises(ValueError, match="REPORT_FACT_SOURCE_PATH_NOT_FOUND"):
        resolve_report_facts(broken)


def test_generated_report_facts_have_no_copied_values() -> None:
    result = _bundle()
    result.pop("reportFacts")
    ensure_report_facts(result)
    facts = result["reportFacts"]
    assert isinstance(facts, list) and facts
    assert all("values" not in fact for fact in facts)
    assert all(str(fact["sourceResultId"]) == "run_report_facts" for fact in facts)


def test_result_without_report_facts_remains_resolvable() -> None:
    assert resolve_report_facts({"estimates": []}) == []
