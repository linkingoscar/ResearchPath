from __future__ import annotations

from collections.abc import Callable


def migrate_v1(
    payload: dict[str, object],
    context_payload: Callable[[dict[str, object]], dict[str, object]],
    role_key: Callable[[dict[str, object]], str],
    string_list: Callable[[object], list[str]],
) -> dict[str, object]:
    context = context_payload(payload)
    primary_source = payload.get("primaryAnalysis")
    primary = dict(primary_source) if isinstance(primary_source, dict) else {}
    slice_id = str(primary.get("sliceId", payload.get("sliceId", ""))).strip()
    family = str(primary.get("family", slice_id.split(".", 1)[0] if slice_id else "")).strip()
    primary_parameters = primary.get("parameters")
    if not isinstance(primary_parameters, dict):
        primary_parameters = payload.get("parameters", {})
    if not isinstance(primary_parameters, dict):
        primary_parameters = {}

    raw_roles = payload.get("plannedRoles", [])
    roles: list[dict[str, object]] = []
    if isinstance(raw_roles, list):
        for index, item in enumerate(raw_roles):
            if not isinstance(item, dict):
                continue
            key = role_key(item) or f"role_{index + 1}"
            accepted = item.get("acceptedTypes", item.get("accepted_types", []))
            roles.append(
                {
                    "key": key,
                    "label": str(item.get("label", item.get("role", key))).strip() or key,
                    "role": str(item.get("role", key)).strip() or key,
                    "level": int(item.get("level", 1) or 1),
                    "variableId": item.get("variableId"),
                    "acceptedTypes": string_list(accepted),
                    "structureRole": item.get("structureRole"),
                }
            )

    raw_constructs = payload.get("constructs", [])
    constructs: list[dict[str, object]] = []
    if isinstance(raw_constructs, list):
        for index, item in enumerate(raw_constructs):
            if not isinstance(item, dict):
                continue
            construct_id = str(item.get("id", f"construct_{index + 1}")).strip()
            constructs.append(
                {
                    "id": construct_id or f"construct_{index + 1}",
                    "label": str(item.get("label", construct_id)).strip() or f"构念 {index + 1}",
                    "itemIds": string_list(item.get("itemIds", item.get("item_ids", []))),
                }
            )

    estimand_label = str(payload.get("estimand", "")).strip()
    estimand_id = "estimand_recovered"
    robustness_declarations: list[dict[str, object]] = []
    robustness_ids: list[str] = []
    raw_robustness = payload.get("robustnessAnalyses", [])
    if isinstance(raw_robustness, list):
        for index, item in enumerate(raw_robustness):
            if not isinstance(item, dict):
                continue
            robustness_id = str(item.get("id", f"analysis_robustness_{index + 1}")).strip()
            robustness_slice = str(item.get("sliceId", item.get("capabilitySliceId", ""))).strip()
            if not robustness_slice:
                continue
            robustness_ids.append(robustness_id)
            parameters = item.get("parameters")
            if not isinstance(parameters, dict):
                parameters = {}
            if item.get("rationale") is not None:
                parameters = {**parameters, "rationale": str(item["rationale"])}
            robustness_declarations.append(
                {
                    "id": robustness_id,
                    "role": "robustness",
                    "estimandIds": [estimand_id],
                    "capabilitySliceId": robustness_slice,
                    "requestedMethod": str(item.get("requestedMethod", robustness_slice.split(".", 1)[0])),
                    "parameters": parameters,
                }
            )

    normalized: dict[str, object] = {
        "schemaVersion": "2.0.0",
        "title": str(payload.get("title", "未命名研究计划")).strip(),
        "researchQuestion": str(payload.get("researchQuestion", "")).strip(),
        "hypotheses": [],
        "estimands": [
            {
                "id": estimand_id,
                "quantity": estimand_label,
                "outcomeScale": "original",
                "population": "analysis_sample",
                "contrast": None,
                "conditioning": None,
                "causalTarget": False,
            }
        ],
        "analysisDeclarations": [
            {
                "id": "analysis_primary",
                "role": "primary",
                "estimandIds": [estimand_id],
                "capabilitySliceId": slice_id,
                "requestedMethod": str(primary.get("requestedMethod", family)),
                "robustnessAnalysisIds": robustness_ids,
                "parameters": primary_parameters,
            },
            *robustness_declarations,
        ],
        "multiplicityFamilies": [],
        "sampleDefinition": {"roles": roles},
        "measurementPlan": {"constructs": constructs},
        "missingDataPlan": {
            "strategy": str(payload.get("missingDataStrategy", "未声明")).strip(),
            "sensitivityAnalysisIds": robustness_ids,
            "reportMissingness": True,
        },
        "powerPlan": payload.get("powerSpec"),
        "context": context,
        "migration": {"fromSchemaVersion": "1.0.0", "mode": "automatic_draft"},
    }
    return normalized
