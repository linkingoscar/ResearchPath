from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import jsonschema

from app.services.publication_assurance import ensure_publication_assurance
from app.services.publication_gate import build_publication_gate
from app.services.replay_package import write_replay_metadata

ROOT = Path(__file__).resolve().parents[3]


def _profile(profile_id: str) -> dict[str, object]:
    return {
        "profileId": profile_id,
        "applicable": True,
        "completeness": 1,
    }


def _externally_validated_result() -> dict[str, object]:
    return {
        "run": {"id": "run_gate", "status": "succeeded", "template": "model_4"},
        "jobStatus": "completed",
        "estimationStatus": "succeeded",
        "inferenceStatus": "reliable",
        "provenance": {"dataSha256": "a" * 64},
        "warnings": [],
        "diagnostics": [],
        "reportingProfileAssessments": [
            _profile("apa_jars_quant"),
            _profile("strobe_observational"),
            _profile("aea_data_code"),
        ],
        "replay": {
            "packageGenerated": True,
            "cleanRoomVerified": True,
        },
    }


def test_publication_assurance_schema_and_default_gate_fail_closed() -> None:
    schema = json.loads(
        (ROOT / "specs" / "publication-assurance.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    result: dict[str, object] = {
        "run": {"id": "run_default", "status": "succeeded", "template": "model_4"},
        "jobStatus": "completed",
        "estimationStatus": "succeeded",
        "inferenceStatus": "reliable",
        "provenance": {"dataSha256": "a" * 64},
        "warnings": [],
        "diagnostics": [],
        "reportFacts": [],
    }
    ensure_publication_assurance(
        result,
        replay_command="pwsh -NoProfile -File reproducibility/reproduce.ps1",
    )
    jsonschema.validate(
        {"replay": result["replay"], "publicationGate": result["publicationGate"]},
        schema,
    )
    gate = result["publicationGate"]
    assert isinstance(gate, dict)
    assert gate["finalEligible"] is False
    assert gate["humanConfirmation"] == {
        "confirmed": False,
        "confirmedBy": None,
        "confirmedAt": None,
    }
    assert gate["runEvidenceLayer"]["status"] == "failed"  # type: ignore[index]


def test_all_three_layers_and_named_human_confirmation_are_jointly_required() -> None:
    result = _externally_validated_result()
    without_human = build_publication_gate(result)
    assert without_human["capabilityLayer"]["status"] == "passed"  # type: ignore[index]
    assert without_human["runEvidenceLayer"]["status"] == "passed"  # type: ignore[index]
    assert without_human["reportingLayer"]["status"] == "passed"  # type: ignore[index]
    assert without_human["finalStatus"] == "requires_human_confirmation"
    assert without_human["finalEligible"] is False

    confirmed = build_publication_gate(
        result,
        confirmed_by="reviewer@example.org",
        confirmed_at="2026-08-24T00:00:00Z",
    )
    assert confirmed["finalStatus"] == "eligible"
    assert confirmed["finalEligible"] is True

    result["provenance"] = {"sliceId": "model.sem", "dataSha256": "a" * 64}
    internal_only = build_publication_gate(
        result,
        confirmed_by="reviewer@example.org",
        confirmed_at="2026-08-24T00:00:00Z",
    )
    assert internal_only["capabilityLayer"]["status"] == "conditional"  # type: ignore[index]
    assert internal_only["finalEligible"] is False


def test_unavailable_empirical_replay_is_disclosed_and_does_not_satisfy_aea_profile() -> None:
    result: dict[str, object] = {
        "reportId": "empirical_0123456789abcdef",
        "sample": {"rowCount": 40},
        "options": {},
        "warnings": [],
        "provenance": {"engine": "R", "dataSha256": "a" * 64},
        "reportFacts": [],
    }
    ensure_publication_assurance(result, replay_command=None)
    replay = result["replay"]
    assert isinstance(replay, dict)
    assert replay["available"] is False
    assert replay["command"] is None
    profiles = result["reportingProfileAssessments"]
    assert isinstance(profiles, list)
    aea = next(item for item in profiles if item["profileId"] == "aea_data_code")
    replay_item = next(item for item in aea["items"] if item["id"] == "replay")
    assert replay_item["satisfied"] is False


def test_replay_verifier_passes_in_clean_directory_and_detects_tampering(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    payload = package / "result.json"
    payload.write_text('{"estimate": 1.25}\n', encoding="utf-8")
    write_replay_metadata(
        package,
        run_id="run_replay",
        command="pwsh -NoProfile -File reproduction/reproduce.ps1",
        include_data=False,
        manifest_path="manifest.json",
    )
    crate = json.loads(
        (package / "ro-crate-metadata.json").read_text(encoding="utf-8")
    )
    assert crate["@context"] == "https://w3id.org/ro/crate/1.3/context"
    files = []
    for path in sorted(item for item in package.rglob("*") if item.is_file()):
        files.append({
            "path": path.relative_to(package).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    (package / "manifest.json").write_text(
        json.dumps({"files": files}, indent=2) + "\n",
        encoding="utf-8",
    )
    verifier = package / "replay" / "verify-package.py"
    passed = subprocess.run(
        [sys.executable, str(verifier), str(package)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert passed.returncode == 0
    assert "hashes verified" in passed.stdout

    payload.write_text('{"estimate": 9.99}\n', encoding="utf-8")
    failed = subprocess.run(
        [sys.executable, str(verifier), str(package)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode == 1
    assert "sha256 mismatch: result.json" in failed.stdout
