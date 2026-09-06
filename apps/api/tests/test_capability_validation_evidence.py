"""Guard: every declared numeric_golden_id must have real evidence.

The capability registry derives validationLevel/maturity from
ValidationEvidence. An external oracle must declare why it is independent of
the engine implementation, and its golden must be referenced by a testthat
file that actually executes and asserts against the product runner.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from app.capability_catalog import ACTIVE_CAPABILITIES
from app.capability_evidence import capability_evidence_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_DIR = PROJECT_ROOT / "engine" / "R" / "tests" / "reference"
TESTTHAT_DIR = PROJECT_ROOT / "engine" / "R" / "tests" / "testthat"
RUNNER_TOKENS = (
    "run_analysis",
    "run_advanced_analysis",
    "run_empirical_analysis",
)


def test_capability_evidence_manifest_is_schema_valid_and_covers_registry() -> None:
    manifest_path = PROJECT_ROOT / "specs" / "capability-evidence.json"
    schema_path = PROJECT_ROOT / "specs" / "capability-evidence.schema.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)

    evidence = capability_evidence_manifest()
    registered = {item.slice_id for item in ACTIVE_CAPABILITIES}
    assert set(evidence) == registered
    assert len(evidence) == len(registered) == 39


def test_registry_structure_and_maturity_do_not_drift_from_evidence_manifest() -> None:
    evidence = capability_evidence_manifest()
    for capability in ACTIVE_CAPABILITIES:
        entry = evidence[capability.slice_id]
        supported = entry["supportedData"]
        tests = entry["tests"]
        oracle = entry["oracle"]
        estimand = entry["estimand"]
        limitations = entry["limitations"]
        assert isinstance(supported, dict)
        assert isinstance(tests, dict)
        assert isinstance(oracle, dict)
        assert isinstance(estimand, dict)
        assert isinstance(limitations, list)
        assert supported["timeStructures"] == list(capability.time_structures)
        assert supported["dependenceStructures"] == list(capability.dependence_structures)
        assert supported["designs"] == list(capability.designs)
        assert capability.support_boundary in limitations
        assert tests["contract"] is capability.validation_evidence.contract_tests
        assert tests["applicability"] is capability.validation_evidence.applicability_tests
        assert tests["failureFixtures"] is capability.validation_evidence.failure_fixtures
        assert tests["numericGoldenId"] == capability.validation_evidence.numeric_golden_id
        assert oracle["name"] == capability.validation_evidence.external_oracle
        assert oracle["independence"] == capability.validation_evidence.oracle_independence
        if capability.validation_level == "unvalidated":
            assert estimand["status"] == "not_formally_frozen"
            assert capability.publication_eligibility == "ineligible"
        else:
            assert estimand["status"] in {"declared_at_run", "frozen"}


def test_declared_numeric_goldens_exist_and_have_executable_assertions() -> None:
    problems: list[str] = []
    test_texts = {
        path.name: path.read_text(encoding="utf-8", errors="replace")
        for path in TESTTHAT_DIR.glob("*.R")
    }
    for capability in ACTIVE_CAPABILITIES:
        evidence = capability.validation_evidence
        golden_id = evidence.numeric_golden_id
        if golden_id is None:
            continue
        golden_file = REFERENCE_DIR / f"{golden_id}.json"
        if not golden_file.exists():
            problems.append(
                f"{capability.slice_id}: numeric_golden_id '{golden_id}' has no "
                f"reference file at {golden_file.name}"
            )
            continue
        matching = {
            name: text for name, text in test_texts.items() if golden_id in text
        }
        if not matching:
            problems.append(
                f"{capability.slice_id}: golden '{golden_id}' is not referenced "
                f"by any testthat test"
            )
            continue
        executable = {
            name: text
            for name, text in matching.items()
            if "expect_" in text and any(token in text for token in RUNNER_TOKENS)
        }
        if not executable:
            problems.append(
                f"{capability.slice_id}: golden '{golden_id}' is only referenced "
                "by string matching, not by a test that executes the runner and "
                "asserts results"
            )
    assert not problems, (
        "Validation evidence must be backed by a reference file and an "
        "executable assertion:\n" + "\n".join(problems)
    )


def test_external_oracle_requires_golden_and_independence_declaration() -> None:
    problems: list[str] = []
    for capability in ACTIVE_CAPABILITIES:
        evidence = capability.validation_evidence
        if evidence.external_oracle is None:
            continue
        if evidence.numeric_golden_id is None:
            problems.append(
                f"{capability.slice_id}: external oracle without numeric golden"
            )
        if not evidence.oracle_independence:
            problems.append(
                f"{capability.slice_id}: external oracle without an independence "
                "declaration proving the generator does not share the engine estimator"
            )
        elif "runner" not in evidence.oracle_independence.lower():
            problems.append(
                f"{capability.slice_id}: oracle independence must explain the "
                "generator/runner relationship"
            )
    assert not problems, (
        "An external oracle must be backed by a golden and an independence "
        "declaration:\n" + "\n".join(problems)
    )


def test_process_golden_generator_does_not_call_the_product_runner() -> None:
    generator = REFERENCE_DIR / "generate-process-goldens.R"
    assert generator.exists()
    text = generator.read_text(encoding="utf-8", errors="replace")
    assert "RESEARCHPATH_PROCESS_MACRO" in text
    assert "PROCESS for R" in text
    assert "run_analysis.R" not in text


def test_analytic_power_uses_an_independent_scipy_oracle() -> None:
    analytic_power = [
        capability
        for capability in ACTIVE_CAPABILITIES
        if capability.slice_id.startswith("power_analysis.analytic.")
    ]
    assert len(analytic_power) == 3
    for capability in analytic_power:
        evidence = capability.validation_evidence
        assert evidence.external_oracle is not None
        assert "SciPy" in evidence.external_oracle
        assert evidence.numeric_golden_id == "power-goldens-v1"
        assert evidence.oracle_independence is not None
        assert "product runner" in evidence.oracle_independence
        assert "does not call the R pwr package" in evidence.oracle_independence
        assert capability.validation_level == "externally_validated"
        assert capability.maturity_level == "reviewer_ready"
        assert capability.publication_eligibility != "eligible"

    generator = REFERENCE_DIR / "generate-power-independent-goldens.py"
    assert generator.exists()
    text = generator.read_text(encoding="utf-8", errors="replace")
    assert "from scipy.stats import" in text
    assert "run_advanced_analysis.R" not in text
    assert "library(pwr)" not in text
