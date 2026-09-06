from __future__ import annotations

from model_test_helpers import _model_dataset, client
from test_empirical_center import _await_empirical_job, _fetch_full_report


def test_nested_cross_sectional_empirical_e2e_is_descriptive_and_cluster_aware() -> None:
    dataset, measurement = _model_dataset(group_count=8, row_count=80)
    group = next(variable for variable in dataset["variables"] if variable["originalName"] == "group")
    current = client.get(f"/api/v1/projects/{dataset['projectId']}/study-context")
    saved_context = client.put(
        f"/api/v1/projects/{dataset['projectId']}/study-context",
        json={
            "expectedRevision": current.json()["revision"] if current.status_code == 200 else None,
            "context": {
                "schemaVersion": "1.0.0",
                "timeStructure": "cross_sectional",
                "dependenceStructure": "nested",
                "design": "observational",
            },
        },
    )
    assert saved_context.status_code == 200, saved_context.text
    structure = client.post(
        f"/api/v1/datasets/{dataset['id']}/study-structures",
        json={
            "expectedRevision": None,
            "studyContextVersionId": saved_context.json()["id"],
            "roles": {"subjectId": None, "clusterId": group["id"], "timeId": None},
            "overrideReason": "嵌套横截面 E2E 使用八个 cluster 验证聚合证据与 IID 阻断。",
        },
    )
    assert structure.status_code == 201, structure.text
    resolved = client.get(f"/api/v1/datasets/{dataset['id']}/resolved-analysis-context").json()
    state = _await_empirical_job(
        client.post(
            f"/api/v1/datasets/{dataset['id']}/measurements/{measurement['version']}/empirical-analysis",
            json={
                "context_hash": resolved["contextHash"],
                "aggregation_variable_id": group["id"],
                "confidence_level": 0.90,
            },
        )
    )
    report = _fetch_full_report(
        client, dataset["id"], measurement["version"], state["reportId"]
    )
    assert report["publicationEligible"] is False
    assert report["requiresManualReview"] is True
    assert "DEPENDENCE_AWARE_INFERENCE_REQUIRED" in report["publicationEligibilityReasons"]
    assert report["sampleFlow"]["original"] == 80
    assert report["sampleFlow"]["finalN"] == 80
    assert report["aggregationDiagnostics"]["constructs"]
    assert all(item["available"] is True for item in report["aggregationDiagnostics"]["constructs"])
    assert {item["clusterCount"] for item in report["aggregationDiagnostics"]["constructs"]} == {8}
    assert report.get("hierarchicalRegression") is None
    assert report.get("groupComparison") is None
    assert all(
        value is None
        for row in report["correlations"]["pValuesRaw"]
        for value in row
    )
    assert report["correlations"]["inferenceAvailable"] is False
    assert "NESTED" in report["correlations"]["inferenceReason"]
