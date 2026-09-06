from __future__ import annotations

import time

from model_test_helpers import _model_dataset, _spec
from starlette.testclient import TestClient
from study_plan_test_helpers import typed_plan_payload

from app.main import app
from app.services import analysis_jobs as analysis_jobs_module

client = TestClient(
    app,
    headers={"X-ResearchPath-Token": app.state.services.settings.session_token},
)

def test_imputation_plan_hashes_context_and_rejects_client_drift() -> None:
    dataset = client.post("/api/v1/demo/load").json()["dataset"]
    project_id = dataset["projectId"]
    current = client.get(f"/api/v1/projects/{project_id}/study-context")
    context = {
        "schemaVersion": "1.0.0",
        "timeStructure": "cross_sectional",
        "dependenceStructure": "independent",
        "design": "observational",
    }
    saved = client.put(
        f"/api/v1/projects/{project_id}/study-context",
        json={
            "expectedRevision": current.json()["revision"] if current.status_code == 200 else None,
            "context": context,
        },
    )
    structure = client.post(
        f"/api/v1/datasets/{dataset['id']}/study-structures",
        json={
            "expectedRevision": None,
            "studyContextVersionId": saved.json()["id"],
            "roles": {
                "subjectId": None,
                "clusterId": None,
                "timeId": None,
            },
        },
    )
    assert structure.status_code == 201
    resolved = client.get(f"/api/v1/datasets/{dataset['id']}/resolved-analysis-context")
    payload = resolved.json()
    numeric = [
        variable["id"]
        for variable in dataset["variables"]
        if variable["originalName"] in {"age", "autonomy_1"}
    ]
    plan_request = {
        "contextHash": payload["contextHash"],
        "sampleVersionId": payload["sample"]["id"],
        "measurementVersionId": payload["measurement"]["id"] if payload["measurement"] else None,
        "structureVersionId": structure.json()["id"],
        "substantiveModel": {
            "modelType": "linear_regression",
            "outcomeId": numeric[0],
            "predictorIds": [numeric[1]],
            "includeIntercept": True,
        },
        "variables": [
            {"variableId": numeric[0], "method": "pmm", "predictorIds": [numeric[1]]},
            {"variableId": numeric[1], "method": "pmm", "predictorIds": [numeric[0]]},
        ],
        "imputations": 5,
        "iterations": 5,
        "seed": 42,
        "diagnostics": ["trace"],
    }
    created = client.post(
        f"/api/v1/datasets/{dataset['id']}/imputation-plans", json=plan_request
    )
    assert created.status_code == 201
    assert len(created.json()["planHash"]) == 64

    drifted = client.post(
        f"/api/v1/datasets/{dataset['id']}/imputation-plans",
        json={**plan_request, "planHash": "0" * 64},
    )
    assert drifted.status_code == 409
    assert drifted.json()["detail"]["code"] == "IMPUTATION_PLAN_HASH_MISMATCH"


def test_v1_study_plan_migrates_to_draft_and_requires_explicit_v2_freeze() -> None:
    dataset = client.post("/api/v1/demo/load").json()["dataset"]
    project_id = dataset["projectId"]
    context = {
        "schemaVersion": "1.0.0",
        "timeStructure": "cross_sectional",
        "dependenceStructure": "independent",
        "design": "observational",
    }
    power_spec = {
        "schemaVersion": "0.1.0",
        "analysisId": "plan-power-migration",
        "name": "Migrated plan power",
        "family": "power_analysis",
        "designFamily": "regression",
        "method": "analytic",
        "solveFor": "sample_size",
        "alpha": 0.05,
        "targetPower": 0.8,
        "effectSize": {"metric": "cohens_f2", "value": 0.15},
        "predictors": 3,
        "groups": 1,
        "simulations": 5000,
        "alternative": "two_sided",
        "roundingRule": "ceil",
    }
    version_one = client.post(
        f"/api/v1/projects/{project_id}/study-plans",
        json={
            "payload": {
                "title": "Version one plan",
                "researchQuestion": "How large should the study be for the planned analysis?",
                "estimand": "R2 change",
                "context": context,
                "primaryAnalysis": {
                    "family": "power_analysis",
                    "sliceId": "power_analysis.analytic.regression",
                    "parameters": {},
                },
                "plannedRoles": [{"key": "outcome", "label": "结果变量"}],
                "constructs": [],
                "missingDataStrategy": "完整案例分析并报告缺失比例",
                "powerSpec": power_spec,
            }
        },
    )
    assert version_one.status_code == 201, version_one.text
    migrated = version_one.json()
    assert migrated["schemaVersion"] == "2.0.0"
    assert migrated["status"] == "draft"
    assert migrated["migration"] == {"fromSchemaVersion": "1.0.0", "mode": "automatic_draft"}
    assert migrated["hypotheses"] == []
    rejected = client.post(f"/api/v1/study-plans/{migrated['id']}/freeze")
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "STUDY_PLAN_MIGRATION_REQUIRES_REVIEW"

    revised = client.post(
        f"/api/v1/study-plans/{migrated['id']}/revisions",
        json={
            "expectedRevision": migrated["revision"],
            "payload": typed_plan_payload(context, power_spec=power_spec),
        },
    )
    assert revised.status_code == 200, revised.text
    explicit_v2 = revised.json()
    assert explicit_v2["status"] == "draft"
    assert explicit_v2.get("migration") is None
    frozen = client.post(f"/api/v1/study-plans/{explicit_v2['id']}/freeze")
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["status"] == "frozen"


def test_study_plan_versions_freeze_and_map_dataset() -> None:
    dataset = client.post("/api/v1/demo/load").json()["dataset"]
    project_id = dataset["projectId"]
    context = {
        "schemaVersion": "1.0.0",
        "timeStructure": "cross_sectional",
        "dependenceStructure": "independent",
        "design": "observational",
    }
    current_context = client.get(f"/api/v1/projects/{project_id}/study-context")
    saved_context = client.put(
        f"/api/v1/projects/{project_id}/study-context",
        json={
            "expectedRevision": current_context.json()["revision"] if current_context.status_code == 200 else None,
            "context": context,
        },
    )
    assert saved_context.status_code == 200, saved_context.text
    power_spec = {
        "schemaVersion": "0.1.0",
        "analysisId": "plan-power-demo",
        "name": "Plan power",
        "family": "power_analysis",
        "designFamily": "regression",
        "method": "analytic",
        "solveFor": "sample_size",
        "alpha": 0.05,
        "targetPower": 0.8,
        "effectSize": {"metric": "cohens_f2", "value": 0.15},
        "predictors": 3,
        "groups": 1,
        "simulations": 5000,
        "alternative": "two_sided",
        "roundingRule": "ceil",
    }
    created = client.post(
        f"/api/v1/projects/{project_id}/study-plans",
        json={
            "payload": typed_plan_payload(
                context,
                title="Demo power plan",
                research_question="How many observations are needed for the planned analysis?",
                slice_id="power_analysis.analytic.regression",
                power_spec=power_spec,
            )
        },
    )
    assert created.status_code == 201
    plan = created.json()
    assert plan["title"] == "Demo power plan"
    primary = next(item for item in plan["analysisDeclarations"] if item["role"] == "primary")
    assert primary["capabilitySliceId"] == "power_analysis.analytic.regression"
    updated = client.put(
        f"/api/v1/study-plans/{plan['id']}",
        json={
            "expectedRevision": plan["revision"],
            "payload": typed_plan_payload(
                context,
                title="Demo t-test power plan",
                research_question="How many observations are needed for the planned contrast?",
                slice_id="power_analysis.analytic.t_test",
                power_spec={
                    **power_spec,
                    "analysisId": "plan-power-t-test",
                    "designFamily": "t_test",
                    "effectSize": {"metric": "cohens_d", "value": 0.5},
                    "groups": 2,
                    "predictors": 1,
                },
            ),
        },
    )
    assert updated.status_code == 200, updated.text
    frozen = client.post(f"/api/v1/study-plans/{updated.json()['id']}/freeze")
    assert frozen.status_code == 200
    assert frozen.json()["status"] == "frozen"
    incomplete = client.post(
        f"/api/v1/study-plans/{frozen.json()['id']}/map-dataset",
        json={"datasetVersionId": dataset["id"], "mapping": {}, "status": "ready"},
    )
    assert incomplete.status_code == 409
    assert incomplete.json()["detail"]["code"] == "PLAN_MAPPING_INCOMPLETE"
    unknown = client.post(
        f"/api/v1/study-plans/{frozen.json()['id']}/map-dataset",
        json={"datasetVersionId": dataset["id"], "mapping": {"outcome": "not_a_dataset_variable"}, "status": "ready"},
    )
    assert unknown.status_code == 409
    assert unknown.json()["detail"]["code"] == "PLAN_DATASET_VARIABLE_UNKNOWN"
    mapping = client.post(
        f"/api/v1/study-plans/{frozen.json()['id']}/map-dataset",
        json={"datasetVersionId": dataset["id"], "mapping": {"outcome": dataset["variables"][0]["id"]}, "status": "ready"},
    )
    assert mapping.status_code == 200, mapping.text
    assert mapping.json()["datasetVersionId"] == dataset["id"]

    rejected = client.put(
        f"/api/v1/study-plans/{frozen.json()['id']}",
        json={"expectedRevision": 2, "payload": {"sliceId": "power_analysis.analytic.regression"}},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "STUDY_PLAN_FROZEN"


def test_study_plan_freeze_and_mapping_validate_context_roles_types_and_robustness() -> None:
    dataset = client.post("/api/v1/demo/load").json()["dataset"]
    project_id = dataset["projectId"]
    age = next(variable for variable in dataset["variables"] if variable["originalName"] == "age")
    context = {
        "schemaVersion": "1.0.0",
        "timeStructure": "cross_sectional",
        "dependenceStructure": "independent",
        "design": "observational",
    }
    current_context = client.get(f"/api/v1/projects/{project_id}/study-context")
    saved_context = client.put(
        f"/api/v1/projects/{project_id}/study-context",
        json={
            "expectedRevision": current_context.json()["revision"] if current_context.status_code == 200 else None,
            "context": context,
        },
    )
    assert saved_context.status_code == 200, saved_context.text
    power_spec = {
        "schemaVersion": "0.1.0",
        "analysisId": "plan-power-semantic-boundary",
        "name": "Plan semantic boundary",
        "family": "power_analysis",
        "designFamily": "t_test",
        "method": "analytic",
        "solveFor": "sample_size",
        "alpha": 0.05,
        "targetPower": 0.8,
        "effectSize": {"metric": "cohens_d", "value": 0.5},
        "predictors": 1,
        "groups": 2,
        "simulations": 5000,
        "alternative": "two_sided",
        "roundingRule": "ceil",
    }
    created = client.post(
        f"/api/v1/projects/{project_id}/study-plans",
        json={
            "payload": typed_plan_payload(
                context,
                title="Semantic study plan",
                research_question="Does the planned contrast differ between groups?",
                hypothesis_label="The planned contrast differs between groups.",
                slice_id="power_analysis.analytic.t_test",
                power_spec=power_spec,
                roles=[
                    {
                        "key": "outcome",
                        "label": "结果变量",
                        "role": "outcome",
                        "acceptedTypes": ["continuous"],
                    }
                ],
                robustness=[
                    {
                        "sliceId": "power_analysis.analytic.regression",
                        "rationale": "检查在回归调整协变量后结论是否保持一致",
                    }
                ],
            ),
        },
    )
    assert created.status_code == 201, created.text
    frozen = client.post(f"/api/v1/study-plans/{created.json()['id']}/freeze")
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["status"] == "frozen"

    mapped = client.post(
        f"/api/v1/study-plans/{created.json()['id']}/map-dataset",
        json={
            "datasetVersionId": dataset["id"],
            "mapping": {"outcome": age["id"]},
            "status": "ready",
        },
    )
    assert mapped.status_code == 200, mapped.text
    assert mapped.json()["status"] == "ready"


def test_study_plan_binding_survives_result_read_and_marks_old_evidence_stale(
    monkeypatch,
) -> None:
    dataset, measurement = _model_dataset()
    project_id = dataset["projectId"]
    context = {
        "schemaVersion": "1.0.0",
        "timeStructure": "cross_sectional",
        "dependenceStructure": "independent",
        "design": "observational",
    }
    power_spec = {
        "schemaVersion": "0.1.0",
        "analysisId": "plan-power-binding",
        "name": "Plan binding power",
        "family": "power_analysis",
        "designFamily": "regression",
        "method": "analytic",
        "solveFor": "sample_size",
        "alpha": 0.05,
        "targetPower": 0.8,
        "effectSize": {"metric": "cohens_f2", "value": 0.15},
        "predictors": 3,
        "groups": 1,
        "simulations": 5000,
        "alternative": "two_sided",
        "roundingRule": "ceil",
    }
    plan_response = client.post(
        f"/api/v1/projects/{project_id}/study-plans",
        json={"payload": typed_plan_payload(context, power_spec=power_spec)},
    )
    assert plan_response.status_code == 201, plan_response.text
    plan = plan_response.json()
    frozen_response = client.post(f"/api/v1/study-plans/{plan['id']}/freeze")
    assert frozen_response.status_code == 200, frozen_response.text
    frozen = frozen_response.json()
    binding = {
        "studyPlanVersionId": frozen["id"],
        "studyPlanHash": frozen["planHash"],
        "hypothesisId": "hypothesis_primary",
        "estimandId": "estimand_primary",
        "analysisDeclarationId": "analysis_primary",
    }
    model = _spec("model_1", dataset, measurement)
    model_freeze = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/freeze",
        json={"model_spec": model},
    )
    assert model_freeze.status_code == 200, model_freeze.text

    def fake_execute(*args: object) -> dict[str, object]:
        run_id = str(args[4])
        return {
            "run": {"id": run_id, "status": "succeeded"},
            "provenance": {"dataSha256": dataset["originalFile"]["sha256"]},
        }

    monkeypatch.setattr(analysis_jobs_module, "execute_cancellable_analysis", fake_execute)
    started = client.post(
        f"/api/v1/datasets/{dataset['id']}/models/{model['modelId']}/versions/{model_freeze.json()['version']}/analysis",
        json={"studyPlanBinding": binding},
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["id"]
    manager = app.state.services.analysis_job_manager
    deadline = time.monotonic() + 10
    state = manager.get(run_id)
    while state["status"] not in {"succeeded", "failed", "cancelled"} and time.monotonic() < deadline:
        time.sleep(0.02)
        state = manager.get(run_id)
    assert state["status"] == "succeeded", state
    result = manager.get_result(run_id)
    result_binding = result["studyPlanBinding"]
    assert isinstance(result_binding, dict)
    assert result_binding["status"] == "current"
    assert result_binding["currentEvidence"] is True
    assert result_binding["hypothesisIds"] == ["hypothesis_primary"]
    for identity_key in (
        "datasetSha256",
        "sampleVersionId",
        "sampleHash",
        "measurementVersionId",
        "measurementHash",
        "specHash",
    ):
        assert result_binding[identity_key]
    assert result_binding["declarationStatus"] == "declared"
    assert result_binding["publicationEligible"] is True
    graph = result["evidenceGraph"]
    assert graph["schemaVersion"] == "2.0.0"
    assert graph["studyPlanVersion"]["id"] == frozen["id"]
    assert graph["hypotheses"][0]["id"] == "hypothesis_primary"
    assert graph["estimands"][0]["id"] == "estimand_primary"
    assert graph["analysisDeclarations"][0]["id"] == "analysis_primary"
    assert graph["resultBinding"] == result_binding

    changed_data_result = {
        "provenance": {"dataSha256": "f" * 64},
        "studyPlanBinding": result_binding,
    }
    app.state.services.workflow_services.study_plan.binding.refresh_result_binding(
        changed_data_result,
        current_plan=frozen,
        current_data_sha256=dataset["originalFile"]["sha256"],
    )
    changed_binding = changed_data_result["studyPlanBinding"]
    assert isinstance(changed_binding, dict)
    assert changed_binding["status"] == "stale"
    assert "DATASET_HASH_CHANGED" in changed_binding["staleReasons"]

    revision_response = client.post(
        f"/api/v1/study-plans/{frozen['id']}/revisions",
        json={
            "expectedRevision": frozen["revision"],
            "payload": typed_plan_payload(
                context,
                title="Typed study plan revision",
                power_spec=power_spec,
            ),
        },
    )
    assert revision_response.status_code == 200, revision_response.text
    revision = revision_response.json()
    assert revision["status"] == "draft"
    assert revision["id"] != frozen["id"]
    stale_result = manager.get_result(run_id)
    stale_binding = stale_result["studyPlanBinding"]
    assert isinstance(stale_binding, dict)
    assert stale_binding["status"] == "stale"
    assert stale_binding["currentEvidence"] is False
    assert "STUDY_PLAN_NEWER_REVISION" in stale_binding["staleReasons"]
