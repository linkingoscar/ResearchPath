from __future__ import annotations

import time
from io import BytesIO

from starlette.testclient import TestClient

from app.main import app

client = TestClient(
    app,
    headers={"X-ResearchPath-Token": app.state.services.settings.session_token},
)


def _ensure_independent_context(dataset: dict) -> dict:
    """Bind fixture datasets to the current workflow context contract."""
    project_id = dataset["projectId"]
    current = client.get(f"/api/v1/projects/{project_id}/study-context")
    expected_revision = current.json()["revision"] if current.status_code == 200 else None
    saved = client.put(
        f"/api/v1/projects/{project_id}/study-context",
        json={
            "expectedRevision": expected_revision,
            "context": {
                "schemaVersion": "1.0.0",
                "timeStructure": "cross_sectional",
                "dependenceStructure": "independent",
                "design": "observational",
            },
        },
    )
    assert saved.status_code == 200, saved.text
    resolved = client.get(
        f"/api/v1/datasets/{dataset['id']}/resolved-analysis-context"
    )
    assert resolved.status_code == 200, resolved.text
    return resolved.json()


def _await_analysis(response, timeout: float = 30.0) -> dict:
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state_response = client.get(f"/api/v1/analyses/{run_id}")
        assert state_response.status_code == 200, state_response.text
        state = state_response.json()
        if state["status"] in {"succeeded", "failed", "cancelled"}:
            if state["status"] != "succeeded":
                import json

                print("JOB FAILED STATE:", json.dumps(state, indent=2))
            assert state["status"] == "succeeded", state
            res_response = client.get(f"/api/v1/analyses/{run_id}/result")
            assert res_response.status_code == 200, res_response.text
            state["result"] = res_response.json()
            return state
        time.sleep(0.05)
    raise AssertionError(f"分析任务 {run_id} 未在 {timeout} 秒内完成")


def _model_dataset(
    group_count: int = 2,
    row_count: int = 40,
    missing_pattern: bool = False,
) -> tuple[dict, dict]:
    columns = ["respondent_id", "x1", "x2", "m1", "m2", "y1", "y2", "w1", "w2", "group", "age"]
    rows = [",".join(columns)]
    for index in range(1, row_count + 1):
        values = [
            index,
            10 + (index * 7) % 31,
            12 + (index * 11) % 29,
            8 + (index * 13) % 37,
            9 + (index * 17) % 41,
            15 + (index * 19) % 43,
            11 + (index * 23) % 47,
            7 + (index * 5) % 27,
            6 + (index * 3) % 25,
            chr(ord("A") + (index - 1) % group_count),
            20 + index,
        ]
        if missing_pattern:
            if index % 5 == 0:
                values[1] = ""
            if index % 7 == 0:
                values[4] = ""
            if index % 11 == 0:
                values[5] = ""
        rows.append(",".join(str(value) for value in values))
    payload = ("\n".join(rows) + "\n").encode("utf-8")
    imported = client.post(
        "/api/v1/datasets/import",
        files={"file": ("m3.csv", BytesIO(payload), "text/csv")},
    )
    assert imported.status_code == 201, imported.text
    dataset = imported.json()
    updates = [
        {
            "id": variable["id"],
            "confirmed_type": (
                "id"
                if variable["originalName"] == "respondent_id"
                else ("binary" if group_count == 2 else "nominal")
                if variable["originalName"] == "group"
                else "continuous"
            ),
        }
        for variable in dataset["variables"]
    ]
    confirmed = client.put(
        f"/api/v1/datasets/{dataset['id']}/dictionary",
        json={"variables": updates},
    )
    assert confirmed.status_code == 200
    dataset = confirmed.json()
    item_ids = {variable["originalName"]: variable["id"] for variable in dataset["variables"]}
    constructs = []
    for role in ("x", "m", "y", "w"):
        constructs.append(
            {
                "id": f"construct_{role}",
                "name": role.upper(),
                "item_ids": [item_ids[f"{role}1"], item_ids[f"{role}2"]],
                "reverse_item_ids": [],
                "theoretical_minimum": 1,
                "theoretical_maximum": 100,
                "aggregation": "mean",
                "minimum_valid_proportion": 0.8,
            }
        )
    measured = client.put(
        f"/api/v1/datasets/{dataset['id']}/measurement",
        json={"constructs": constructs},
    )
    assert measured.status_code == 200, measured.text
    _ensure_independent_context(dataset)
    return dataset, measured.json()


def _spec(template: str, dataset: dict, measurement: dict) -> dict:
    age = next(variable for variable in dataset["variables"] if variable["originalName"] == "age")

    if template in {"model_2", "model_3"}:
        nodes = [
            {
                "id": "node_x",
                "variableId": "scale_x",
                "label": "X",
                "kind": "scale_score",
                "role": "x",
                "dataType": "continuous",
            },
            {
                "id": "node_y",
                "variableId": "scale_y",
                "label": "Y",
                "kind": "scale_score",
                "role": "y",
                "dataType": "continuous",
            },
            {
                "id": "node_w",
                "variableId": "scale_w",
                "label": "W",
                "kind": "scale_score",
                "role": "w",
                "dataType": "continuous",
            },
            {
                "id": "node_z",
                "variableId": age["id"],
                "label": "Z",
                "kind": "observed",
                "role": "z",
                "dataType": "continuous",
            },
        ]
        edges = [
            {
                "id": "edge_x_y",
                "from": "node_x",
                "to": "node_y",
                "kind": "regression",
                "label": "c",
            }
        ]
        moderations = [
            {
                "id": "moderation_w",
                "moderatorNodeId": "node_w",
                "targetEdgeId": "edge_x_y",
                "productTermId": "term_x_w",
            },
            {
                "id": "moderation_z",
                "moderatorNodeId": "node_z",
                "targetEdgeId": "edge_x_y",
                "productTermId": "term_x_z",
            },
        ]
        if template == "model_3":
            moderations.append(
                {
                    "id": "moderation_w_z",
                    "moderatorNodeId": "node_w",
                    "secondaryModeratorNodeId": "node_z",
                    "targetEdgeId": "edge_x_y",
                    "productTermId": "term_x_w_z",
                    "moderatorProductTermId": "term_w_z",
                }
            )
        outcome_ids = ["node_y"]
        centering = {"method": "mean", "nodeIds": ["node_x", "node_w", "node_z"]}
    elif template == "model_6":
        nodes = [
            {
                "id": "node_x",
                "variableId": "scale_x",
                "label": "X",
                "kind": "scale_score",
                "role": "x",
                "dataType": "continuous",
            },
            {
                "id": "node_m1",
                "variableId": "scale_m",
                "label": "M1",
                "kind": "scale_score",
                "role": "m",
                "dataType": "continuous",
            },
            {
                "id": "node_m2",
                "variableId": "scale_y",
                "label": "M2",
                "kind": "scale_score",
                "role": "m",
                "dataType": "continuous",
            },  # Reuse Y scale as M2 for testing
            {
                "id": "node_y",
                "variableId": "scale_w",
                "label": "Y",
                "kind": "scale_score",
                "role": "y",
                "dataType": "continuous",
            },  # Reuse W scale as Y for testing
            {
                "id": "node_age",
                "variableId": age["id"],
                "label": "年龄",
                "kind": "observed",
                "role": "covariate",
                "dataType": "continuous",
            },
        ]
        edges = [
            {
                "id": "edge_x_m1",
                "from": "node_x",
                "to": "node_m1",
                "kind": "regression",
                "label": "a1",
            },
            {
                "id": "edge_x_m2",
                "from": "node_x",
                "to": "node_m2",
                "kind": "regression",
                "label": "a2",
            },
            {
                "id": "edge_m1_m2",
                "from": "node_m1",
                "to": "node_m2",
                "kind": "regression",
                "label": "d",
            },
            {
                "id": "edge_m1_y",
                "from": "node_m1",
                "to": "node_y",
                "kind": "regression",
                "label": "b1",
            },
            {
                "id": "edge_m2_y",
                "from": "node_m2",
                "to": "node_y",
                "kind": "regression",
                "label": "b2",
            },
            {
                "id": "edge_x_y",
                "from": "node_x",
                "to": "node_y",
                "kind": "regression",
                "label": "c_prime",
            },
        ]
        moderations = []
        outcome_ids = ["node_m1", "node_m2", "node_y"]
        centering = {"method": "none", "nodeIds": []}
    elif template in {
        "model_8",
        "model_15",
        "model_21",
        "model_22",
        "model_58",
        "model_59",
    }:
        uses_z = template in {"model_21", "model_22"}
        nodes = [
            {
                "id": "node_x",
                "variableId": "scale_x",
                "label": "X",
                "kind": "scale_score",
                "role": "x",
                "dataType": "continuous",
            },
            {
                "id": "node_m",
                "variableId": "scale_m",
                "label": "M",
                "kind": "scale_score",
                "role": "m",
                "dataType": "continuous",
            },
            {
                "id": "node_y",
                "variableId": "scale_y",
                "label": "Y",
                "kind": "scale_score",
                "role": "y",
                "dataType": "continuous",
            },
            {
                "id": "node_w",
                "variableId": "scale_w",
                "label": "W",
                "kind": "scale_score",
                "role": "w",
                "dataType": "continuous",
            },
            {
                "id": "node_z" if uses_z else "node_age",
                "variableId": age["id"],
                "label": "Z" if uses_z else "年龄",
                "kind": "observed",
                "role": "z" if uses_z else "covariate",
                "dataType": "continuous",
            },
        ]
        edges = [
            {
                "id": "edge_x_m",
                "from": "node_x",
                "to": "node_m",
                "kind": "regression",
                "label": "a",
            },
            {
                "id": "edge_x_y",
                "from": "node_x",
                "to": "node_y",
                "kind": "regression",
                "label": "c_prime",
            },
            {
                "id": "edge_m_y",
                "from": "node_m",
                "to": "node_y",
                "kind": "regression",
                "label": "b",
            },
        ]
        if template == "model_8":
            moderations = [
                {
                    "id": "moderation_w1",
                    "moderatorNodeId": "node_w",
                    "targetEdgeId": "edge_x_m",
                    "productTermId": "term_interaction_m",
                },
                {
                    "id": "moderation_w2",
                    "moderatorNodeId": "node_w",
                    "targetEdgeId": "edge_x_y",
                    "productTermId": "term_interaction_y",
                },
            ]
            center_nodes = ["node_x", "node_w"]
        elif template == "model_15":
            moderations = [
                {
                    "id": "moderation_w1",
                    "moderatorNodeId": "node_w",
                    "targetEdgeId": "edge_m_y",
                    "productTermId": "term_interaction_m_y",
                },
                {
                    "id": "moderation_w2",
                    "moderatorNodeId": "node_w",
                    "targetEdgeId": "edge_x_y",
                    "productTermId": "term_interaction_x_y",
                },
            ]
            center_nodes = ["node_m", "node_x", "node_w"]
        elif template in {"model_21", "model_22"}:
            moderations = [
                {
                    "id": "moderation_w1",
                    "moderatorNodeId": "node_w",
                    "targetEdgeId": "edge_x_m",
                    "productTermId": "term_interaction_x_m",
                },
                {
                    "id": "moderation_z1",
                    "moderatorNodeId": "node_z",
                    "targetEdgeId": "edge_m_y",
                    "productTermId": "term_interaction_m_y",
                },
            ]
            if template == "model_22":
                moderations.append(
                    {
                        "id": "moderation_w2",
                        "moderatorNodeId": "node_w",
                        "targetEdgeId": "edge_x_y",
                        "productTermId": "term_interaction_x_y",
                    }
                )
            center_nodes = ["node_x", "node_m", "node_w", "node_z"]
        else:
            moderations = [
                {
                    "id": "moderation_w1",
                    "moderatorNodeId": "node_w",
                    "targetEdgeId": "edge_x_m",
                    "productTermId": "term_interaction_x_m",
                },
                {
                    "id": "moderation_w2",
                    "moderatorNodeId": "node_w",
                    "targetEdgeId": "edge_m_y",
                    "productTermId": "term_interaction_m_y",
                },
            ]
            if template == "model_59":
                moderations.append(
                    {
                        "id": "moderation_w3",
                        "moderatorNodeId": "node_w",
                        "targetEdgeId": "edge_x_y",
                        "productTermId": "term_interaction_x_y",
                    }
                )
            center_nodes = ["node_x", "node_m", "node_w"]
        outcome_ids = ["node_m", "node_y"]
        centering = {"method": "mean", "nodeIds": center_nodes}
    else:
        roles = ["x", "y"]
        if template != "model_1":
            roles.insert(1, "m")
        if template in {"model_1", "model_5", "model_7", "model_14"}:
            roles.append("w")
        nodes = [
            {
                "id": f"node_{role}",
                "variableId": f"scale_{role}",
                "label": role.upper(),
                "kind": "scale_score",
                "role": role,
                "dataType": "continuous",
            }
            for role in roles
        ]
        nodes.append(
            {
                "id": "node_age",
                "variableId": age["id"],
                "label": "年龄",
                "kind": "observed",
                "role": "covariate",
                "dataType": "continuous",
            }
        )
        if template == "model_1":
            edges = [
                {
                    "id": "edge_x_y",
                    "from": "node_x",
                    "to": "node_y",
                    "kind": "regression",
                    "label": "c",
                }
            ]
            target_edge = "edge_x_y"
        else:
            edges = [
                {
                    "id": "edge_x_m",
                    "from": "node_x",
                    "to": "node_m",
                    "kind": "regression",
                    "label": "a",
                },
                {
                    "id": "edge_x_y",
                    "from": "node_x",
                    "to": "node_y",
                    "kind": "regression",
                    "label": "c_prime",
                },
                {
                    "id": "edge_m_y",
                    "from": "node_m",
                    "to": "node_y",
                    "kind": "regression",
                    "label": "b",
                },
            ]
            if template == "model_5":
                target_edge = "edge_x_y"
            elif template == "model_7":
                target_edge = "edge_x_m"
            else:
                target_edge = "edge_m_y"
        moderations = []
        if "w" in roles:
            moderations = [
                {
                    "id": "moderation_w",
                    "moderatorNodeId": "node_w",
                    "targetEdgeId": target_edge,
                    "productTermId": "term_interaction",
                }
            ]
        outcome_ids = ["node_y"] + (["node_m"] if "m" in roles else [])
        centering = {"method": "mean", "nodeIds": ["node_x"] + (["node_w"] if "w" in roles else [])}

    spec = {
        "schemaVersion": "1.0.0",
        "modelId": f"model_{template}_{dataset['id'][-8:]}",
        "name": f"{template} 测试",
        "datasetVersionId": measurement["derivedDataset"]["id"],
        "design": {
            "timeStructure": "cross_sectional",
            "clustering": "none",
            "claimMode": "associational",
        },
        "nodes": nodes,
        "edges": edges,
        "moderations": moderations,
        "covariates": (
            []
            if template in {"model_2", "model_3", "model_21", "model_22"}
            else [{"nodeId": "node_age", "outcomeNodeIds": outcome_ids}]
        ),
        "estimation": {
            "family": "ols",
            "standardErrors": "hc3",
            "confidenceLevel": 0.95,
            "bootstrap": {
                "enabled": True,
                "replicates": 5000,
                "method": "percentile",
                "seed": 20260713,
            },
            "missing": "complete_cases_per_model",
            "centering": centering,
            "reportScale": "unstandardized_primary",
        },
        "canvas": {
            "positions": {
                node["id"]: {"x": index * 180, "y": 100} for index, node in enumerate(nodes)
            }
        },
    }
    context = client.get(
        f"/api/v1/datasets/{dataset['id']}/resolved-analysis-context"
    ).json()
    spec.update(
        {
            "contextHash": context["contextHash"],
            "datasetSha256": context["dataset"]["sha256"],
            "sampleVersionId": context["sample"]["id"],
            "sampleHash": context["sample"]["hash"],
            "structureVersionId": context["structure"]["id"] if context.get("structure") else None,
            "structureHash": context["structure"]["hash"] if context.get("structure") else None,
            "measurementVersionId": context["measurement"]["id"] if context.get("measurement") else None,
            "measurementHash": context["measurement"]["hash"] if context.get("measurement") else None,
        }
    )
    return spec
