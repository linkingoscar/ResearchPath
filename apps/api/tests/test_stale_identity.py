from __future__ import annotations

from model_test_helpers import client

from app.main import app


def _identity_bound_result() -> dict[str, object]:
    binding = {
        "studyPlanVersionId": "study_plan_" + "a" * 32,
        "studyPlanHash": "b" * 64,
        "hypothesisId": "hypothesis_primary",
        "hypothesisIds": ["hypothesis_primary"],
        "estimandId": "estimand_primary",
        "analysisDeclarationId": "analysis_primary",
        "datasetSha256": "c" * 64,
        "sampleVersionId": "sample_v1",
        "sampleHash": "d" * 64,
        "measurementVersionId": "measurement_v1",
        "measurementHash": "e" * 64,
        "specHash": "f" * 64,
        "declarationStatus": "declared",
        "deviationReason": None,
        "publicationEligible": True,
    }
    return {
        "run": {"status": "succeeded"},
        "provenance": {"dataSha256": "c" * 64},
        "studyPlanBinding": binding,
        "evidenceGraph": {"resultBinding": dict(binding)},
    }


def test_result_binding_invalidates_sample_and_measurement_identity_drift() -> None:
    binding_service = app.state.services.workflow_services.study_plan.binding
    current_plan = {"id": "study_plan_" + "a" * 32, "planHash": "b" * 64}

    sample_version_changed = _identity_bound_result()
    binding_service.refresh_result_binding(
        sample_version_changed,
        current_plan=current_plan,
        current_data_sha256="c" * 64,
        current_sample_version_id="sample_v2",
        current_sample_hash="g" * 64,
        current_measurement_version_id="measurement_v1",
        current_measurement_hash="e" * 64,
    )
    changed_binding = sample_version_changed["studyPlanBinding"]
    assert isinstance(changed_binding, dict)
    assert changed_binding["status"] == "stale"
    assert changed_binding["currentEvidence"] is False
    assert changed_binding["publicationEligible"] is False
    assert "SAMPLE_VERSION_CHANGED" in changed_binding["staleReasons"]
    assert "SAMPLE_HASH_CHANGED" in changed_binding["staleReasons"]
    provenance = sample_version_changed["provenance"]
    evidence_graph = sample_version_changed["evidenceGraph"]
    assert isinstance(provenance, dict)
    assert isinstance(evidence_graph, dict)
    assert provenance["studyPlanBinding"] == changed_binding
    assert evidence_graph["resultBinding"] == changed_binding
    assert sample_version_changed["requiresManualReview"] is True

    sample_hash_changed = _identity_bound_result()
    binding_service.refresh_result_binding(
        sample_hash_changed,
        current_plan=current_plan,
        current_data_sha256="c" * 64,
        current_sample_version_id="sample_v1",
        current_sample_hash="g" * 64,
        current_measurement_version_id="measurement_v1",
        current_measurement_hash="e" * 64,
    )
    sample_hash_binding = sample_hash_changed["studyPlanBinding"]
    assert isinstance(sample_hash_binding, dict)
    assert sample_hash_binding["staleReasons"] == ["SAMPLE_HASH_CHANGED"]

    measurement_version_changed = _identity_bound_result()
    binding_service.refresh_result_binding(
        measurement_version_changed,
        current_plan=current_plan,
        current_data_sha256="c" * 64,
        current_sample_version_id="sample_v1",
        current_sample_hash="d" * 64,
        current_measurement_version_id="measurement_v2",
        current_measurement_hash="h" * 64,
    )
    measurement_version_binding = measurement_version_changed["studyPlanBinding"]
    assert isinstance(measurement_version_binding, dict)
    assert "MEASUREMENT_VERSION_CHANGED" in measurement_version_binding["staleReasons"]
    assert "MEASUREMENT_HASH_CHANGED" in measurement_version_binding["staleReasons"]

    measurement_hash_changed = _identity_bound_result()
    binding_service.refresh_result_binding(
        measurement_hash_changed,
        current_plan=current_plan,
        current_data_sha256="c" * 64,
        current_sample_version_id="sample_v1",
        current_sample_hash="d" * 64,
        current_measurement_version_id="measurement_v1",
        current_measurement_hash="h" * 64,
    )
    measurement_hash_binding = measurement_hash_changed["studyPlanBinding"]
    assert isinstance(measurement_hash_binding, dict)
    assert measurement_hash_binding["staleReasons"] == ["MEASUREMENT_HASH_CHANGED"]

    current = _identity_bound_result()
    binding_service.refresh_result_binding(
        current,
        current_plan=current_plan,
        current_data_sha256="c" * 64,
        current_sample_version_id="sample_v1",
        current_sample_hash="d" * 64,
        current_measurement_version_id="measurement_v1",
        current_measurement_hash="e" * 64,
    )
    current_binding = current["studyPlanBinding"]
    assert isinstance(current_binding, dict)
    assert current_binding["status"] == "current"
    assert current_binding["currentEvidence"] is True
    assert current_binding["publicationEligible"] is True


def test_reader_resolves_current_sample_and_measurement_identity_from_repository() -> None:
    dataset = client.post("/api/v1/demo/load").json()["dataset"]
    context = client.get(f"/api/v1/datasets/{dataset['id']}/resolved-analysis-context").json()
    binding_service = app.state.services.workflow_services.study_plan.binding
    current = binding_service.current_artifact_identity(
        dataset["id"], {"sampleVersionId": context["sample"]["id"]}
    )
    assert current["datasetSha256"] == context["dataset"]["sha256"]
    assert current["sampleVersionId"] == context["sample"]["id"]
    assert current["sampleHash"] == context["sample"]["hash"]
    assert current["measurementVersionId"] == context["measurement"]["id"]
    assert current["measurementHash"] == context["measurement"]["hash"]
