from __future__ import annotations

from typing import Any

from app.process_catalog import match_process_model


class SemanticValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _has_cycle(nodes: set[str], edges: list[dict[str, Any]]) -> bool:
    adjacency = {node_id: [] for node_id in nodes}
    for edge in edges:
        if edge.get("from") in nodes and edge.get("to") in nodes:
            adjacency[edge["from"]].append(edge["to"])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        if any(visit(target) for target in adjacency[node_id]):
            return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in nodes)


def validate_model_semantics(model_spec: dict[str, Any]) -> dict[str, Any]:
    """Validate the ModelSpec graph independently from a concrete dataset."""

    errors: list[str] = []
    warnings: list[dict[str, str]] = []
    nodes = model_spec.get("nodes", [])
    edges = model_spec.get("edges", [])
    moderations = model_spec.get("moderations", [])
    covariates = model_spec.get("covariates", [])
    node_ids = [str(node.get("id", "")) for node in nodes]
    node_by_id = {node.get("id"): node for node in nodes}

    duplicate_node_ids = _duplicates(node_ids)
    if duplicate_node_ids:
        errors.append("节点 ID 重复: " + ", ".join(duplicate_node_ids))
    duplicate_variables = _duplicates(
        [str(node.get("variableId")) for node in nodes if node.get("variableId")]
    )
    if duplicate_variables:
        errors.append("同一变量不能重复进入模型: " + ", ".join(duplicate_variables))

    role_nodes: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        role_nodes.setdefault(node.get("role", ""), []).append(node)

    family = model_spec.get("estimation", {}).get("family", "ols")
    if family == "sem":
        latents = model_spec.get("latents", [])
        if not latents:
            errors.append("SEM 模型必须定义至少一个潜变量 (latents)")
        latent_ids = {str(lat.get("id", "")) for lat in latents}
        if _duplicates([str(lat.get("id", "")) for lat in latents]):
            errors.append("潜变量 ID 重复")
        for node in nodes:
            if node.get("kind") == "latent":
                if node.get("id") not in latent_ids:
                    errors.append(f"潜变量节点 {node.get('id')} 缺少测量定义")
                if node.get("variableId"):
                    errors.append(f"潜变量节点 {node.get('id')} 不能同时绑定观测变量")
            elif node.get("id") in latent_ids:
                errors.append(f"观测节点 {node.get('id')} 与潜变量测量定义冲突")
        higher_order_edges: list[dict[str, Any]] = []
        for lat in latents:
            indicators = lat.get("indicators", [])
            if _duplicates(indicators):
                errors.append(f"潜变量 {lat.get('id')} 的测量指标重复")
            if len(indicators) < 2:
                errors.append(f"潜变量“{lat.get('name', lat.get('id'))}”至少需要 2 个测量指标")
            level = lat.get("level", "first_order")
            latent_indicators = [indicator for indicator in indicators if indicator in latent_ids]
            if level == "higher_order":
                if len(indicators) < 3:
                    errors.append(
                        f"高阶潜变量“{lat.get('name', lat.get('id'))}”至少需要 3 个低阶潜变量以满足当前识别切片"
                    )
                if len(latent_indicators) != len(indicators):
                    errors.append(
                        f"高阶潜变量“{lat.get('name', lat.get('id'))}”的指标必须全部是一阶或低阶潜变量"
                    )
                for indicator in latent_indicators:
                    higher_order_edges.append({"from": indicator, "to": lat.get("id")})
            elif latent_indicators:
                errors.append(
                    f"一阶潜变量“{lat.get('name', lat.get('id'))}”不能把其他潜变量作为测量指标"
                )
        if _has_cycle(latent_ids, higher_order_edges):
            errors.append("高阶潜变量测量层级中存在循环引用")
        estimation = model_spec.get("estimation", {})
        multi_group = estimation.get("multiGroup", {})
        if (
            multi_group.get("compareStructuralPaths")
            or multi_group.get("estimateLatentMeans")
        ) and not estimation.get("invariance"):
            errors.append("结构路径跨组比较和潜均值估计需要先启用多组测量等值性")
        releases = multi_group.get("partialInvarianceReleases", [])
        if releases and (
            not estimation.get("invariance") or not estimation.get("groupVariableId")
        ):
            errors.append("部分等值释放需要分组变量并启用多组测量等值性")
        latent_by_id = {str(latent.get("id")): latent for latent in latents}
        observed_indicators = {
            str(indicator)
            for latent in latents
            if latent.get("level", "first_order") == "first_order"
            for indicator in latent.get("indicators", [])
        }
        release_keys: set[tuple[str, str, str, str]] = set()
        expected_stage = {
            "loading": "metric",
            "intercept_or_threshold": "scalar",
            "residual": "strict",
        }
        for release in releases:
            stage = str(release.get("stage", ""))
            constraint = str(release.get("constraint", ""))
            latent_id = str(release.get("latentId") or "")
            indicator_id = str(release.get("indicatorId", ""))
            key = (stage, constraint, latent_id, indicator_id)
            if key in release_keys:
                errors.append(f"部分等值释放重复: {constraint} {latent_id} {indicator_id}")
            release_keys.add(key)
            if expected_stage.get(constraint) != stage:
                errors.append(f"释放参数 {constraint} 必须位于 {expected_stage.get(constraint, '对应')} 阶段")
            if constraint == "loading":
                latent = latent_by_id.get(latent_id)
                if latent is None or indicator_id not in latent.get("indicators", []):
                    errors.append(f"载荷释放必须引用有效测量关系: {latent_id}=~{indicator_id}")
            elif latent_id:
                errors.append("截距/阈值和残差释放不应指定潜变量")
            if constraint in {"intercept_or_threshold", "residual"} and indicator_id not in observed_indicators:
                errors.append(f"释放参数引用的观测指标不存在: {indicator_id}")
    else:
        for role in ("x", "y"):
            if len(role_nodes.get(role, [])) != 1:
                errors.append(f"模型要求恰好一个 {role.upper()} 节点")
        if len(role_nodes.get("m", [])) > 10:
            errors.append("PROCESS 5.0 最多允许十个 M 节点")
        if len(role_nodes.get("w", [])) > 1:
            errors.append("PROCESS 核心最多允许一个 W 节点")
        if len(role_nodes.get("z", [])) > 1:
            errors.append("PROCESS 核心最多允许一个 Z 节点")

    for node in nodes:
        role = node.get("role")
        data_type = node.get("dataType")
        encoding_method = node.get("encoding", {}).get("method")
        if data_type == "nominal" and role != "covariate":
            errors.append(
                f"节点“{node.get('label', node.get('id'))}”是无序分类变量；当前仅支持将其作为虚拟编码控制变量"
            )
        if (
            data_type == "nominal"
            and role == "covariate"
            and encoding_method not in {None, "treatment"}
        ):
            errors.append(f"分类控制变量“{node.get('label')}”必须使用处理/虚拟编码")
        if encoding_method == "binary_indicator" and data_type != "binary":
            errors.append(f"节点“{node.get('label')}”不是二分类变量，不能使用二元指示编码")
        if family == "ols" and role in {"m", "y"} and data_type not in {"continuous", "binary"}:
            errors.append(f"{role.upper()} 节点必须是连续或二分类变量")

    edge_ids = [str(edge.get("id", "")) for edge in edges]
    duplicate_edge_ids = _duplicates(edge_ids)
    if duplicate_edge_ids:
        errors.append("路径 ID 重复: " + ", ".join(duplicate_edge_ids))
    endpoint_pairs = [f"{edge.get('from')}→{edge.get('to')}" for edge in edges]
    duplicate_endpoints = _duplicates(endpoint_pairs)
    if duplicate_endpoints:
        errors.append("回归路径重复: " + ", ".join(duplicate_endpoints))
    valid_node_ids = set(node_ids)
    for edge in edges:
        source = edge.get("from")
        target = edge.get("to")
        if source not in valid_node_ids or target not in valid_node_ids:
            errors.append(f"路径 {edge.get('id')} 包含悬空节点引用")
            continue
        if source == target:
            errors.append(f"路径 {edge.get('id')} 不允许自回归环")
        source_role = node_by_id[source].get("role")
        target_role = node_by_id[target].get("role")
        if family == "ols":
            if source_role == "covariate" or target_role == "covariate":
                errors.append(f"控制变量 {source} 应通过方程分配，不应创建普通路径")
            if source_role not in {"x", "m"}:
                errors.append(f"路径 {edge.get('id')} 的起点必须是 X 或 M")
            if target_role not in {"m", "y"}:
                errors.append(f"路径 {edge.get('id')} 的目标必须是 M 或 Y")
    if _has_cycle(valid_node_ids, edges):
        errors.append("回归路径中存在循环")

    edge_by_id = {edge.get("id"): edge for edge in edges}
    moderation_ids = [str(item.get("id", "")) for item in moderations]
    if _duplicates(moderation_ids):
        errors.append("调节关系 ID 重复")
    for moderation in moderations:
        moderator = node_by_id.get(moderation.get("moderatorNodeId"))
        secondary_moderator_id = moderation.get("secondaryModeratorNodeId")
        secondary_moderator = node_by_id.get(secondary_moderator_id)
        target_edge = edge_by_id.get(moderation.get("targetEdgeId"))
        if moderator is None:
            errors.append(f"调节关系 {moderation.get('id')} 的调节节点不存在")
        elif moderator.get("role") not in {"w", "z"}:
            errors.append(f"调节关系 {moderation.get('id')} 必须引用 W 或 Z 节点")
        if secondary_moderator_id is not None:
            if secondary_moderator is None:
                errors.append(f"调节关系 {moderation.get('id')} 的第二调节节点不存在")
            elif moderator is not None and {
                moderator.get("role"),
                secondary_moderator.get("role"),
            } != {"w", "z"}:
                errors.append("三阶交互必须同时引用 W 和 Z")
            if not moderation.get("moderatorProductTermId"):
                errors.append("三阶交互必须声明 W×Z 的低阶乘积项")
        if target_edge is None:
            errors.append(f"调节关系 {moderation.get('id')} 的目标路径不存在")
        elif target_edge.get("from") in {
            moderation.get("moderatorNodeId"),
            secondary_moderator_id,
        }:
            errors.append("调节变量的主效应路径不能作为被调节路径")
    if family == "ols":
        if role_nodes.get("w") and not moderations:
            errors.append("W 必须绑定到一条具体回归路径，不能仅作为普通主效应")
        if role_nodes.get("z") and not moderations:
            errors.append("Z 必须绑定到一条具体回归路径，不能仅作为普通主效应")
        if moderations and not (role_nodes.get("w") or role_nodes.get("z")):
            errors.append("存在调节关系但模型缺少 W/Z 节点")
        used_moderator_ids = {
            moderator_id
            for item in moderations
            for moderator_id in (
                item.get("moderatorNodeId"),
                item.get("secondaryModeratorNodeId"),
            )
            if moderator_id
        }
        for role in ("w", "z"):
            for node in role_nodes.get(role, []):
                if node.get("id") not in used_moderator_ids:
                    errors.append(f"{role.upper()} 必须绑定到至少一条具体回归路径")

    assigned_covariates: set[str] = set()
    for assignment in covariates:
        node = node_by_id.get(assignment.get("nodeId"))
        if node is None:
            errors.append(f"控制变量分配包含悬空节点 {assignment.get('nodeId')}")
            continue
        if node.get("role") != "covariate":
            errors.append(f"{assignment.get('nodeId')} 不是控制变量节点")
        if assignment.get("nodeId") in assigned_covariates:
            errors.append(f"控制变量 {assignment.get('nodeId')} 被重复分配")
        assigned_covariates.add(assignment.get("nodeId"))
        if family == "sem":
            if node.get("kind") == "latent":
                errors.append("SEM 控制变量必须是观测节点")
            for outcome_id in assignment.get("outcomeNodeIds", []):
                if outcome_id not in node_by_id or outcome_id == node.get("id"):
                    errors.append(f"控制变量引用了无效目标: {outcome_id}")
        if family == "ols":
            for outcome_id in assignment.get("outcomeNodeIds", []):
                outcome = node_by_id.get(outcome_id)
                if outcome is None or outcome.get("role") not in {"m", "y"}:
                    errors.append(f"控制变量只能进入现有的 M/Y 方程: {outcome_id}")
    if family == "ols":
        for node in role_nodes.get("covariate", []):
            if node.get("id") not in assigned_covariates:
                errors.append(f"控制变量“{node.get('label')}”尚未指定进入哪个方程")

    centering = model_spec.get("estimation", {}).get("centering", {})
    for node_id in centering.get("nodeIds", []):
        node = node_by_id.get(node_id)
        if node is None:
            errors.append(f"中心化设置包含悬空节点 {node_id}")
        elif node.get("dataType") not in {"continuous", "ordinal"}:
            errors.append(f"节点“{node.get('label')}”的数据类型不适合均值中心化")

    catalog_error_offset = len(errors)
    template: str | None = None
    if family == "sem":
        template = "sem"
    elif not any("恰好一个" in error for error in errors):
        x_id = role_nodes.get("x", [{}])[0].get("id")
        y_id = role_nodes.get("y", [{}])[0].get("id")
        m_nodes = role_nodes.get("m", [])
        actual_edges = {(edge.get("from"), edge.get("to")) for edge in edges}

        if len(m_nodes) == 0:
            expected = {(x_id, y_id)}
            if actual_edges != expected:
                errors.append("Model 1/2/3 必须且只能包含 X→Y 路径")
            else:
                direct_edge_ids = {
                    edge.get("id")
                    for edge in edges
                    if edge.get("from") == x_id and edge.get("to") == y_id
                }
                targets_direct = all(
                    item.get("targetEdgeId") in direct_edge_ids for item in moderations
                )
                simple = [
                    item for item in moderations if not item.get("secondaryModeratorNodeId")
                ]
                joint = [
                    item for item in moderations if item.get("secondaryModeratorNodeId")
                ]
                simple_roles = {
                    node_by_id.get(item.get("moderatorNodeId"), {}).get("role")
                    for item in simple
                }
                if (
                    targets_direct
                    and len(moderations) == 1
                    and simple_roles == {"w"}
                    and not role_nodes.get("z")
                ):
                    template = "model_1"
                elif (
                    targets_direct
                    and len(simple) == 2
                    and not joint
                    and simple_roles == {"w", "z"}
                ):
                    template = "model_2"
                elif (
                    targets_direct
                    and len(simple) == 2
                    and len(joint) == 1
                    and simple_roles == {"w", "z"}
                    and {
                        node_by_id.get(joint[0].get("moderatorNodeId"), {}).get("role"),
                        node_by_id.get(
                            joint[0].get("secondaryModeratorNodeId"), {}
                        ).get("role"),
                    }
                    == {"w", "z"}
                ):
                    template = "model_3"
                else:
                    errors.append(
                        "无中介调节结构必须匹配 Model 1、Model 2 或 Model 3"
                    )
        elif len(m_nodes) == 2:
            m1_id, m2_id = None, None
            m_ids = [n.get("id") for n in m_nodes]
            if (m_ids[0], m_ids[1]) in actual_edges:
                m1_id, m2_id = m_ids[0], m_ids[1]
            elif (m_ids[1], m_ids[0]) in actual_edges:
                m1_id, m2_id = m_ids[1], m_ids[0]

            if m1_id is None or m2_id is None:
                errors.append("链式中介模型两个中介变量之间必须有单向路径 M1→M2")
            else:
                expected = {
                    (x_id, m1_id),
                    (x_id, m2_id),
                    (m1_id, m2_id),
                    (m1_id, y_id),
                    (m2_id, y_id),
                    (x_id, y_id),
                }
                if actual_edges != expected:
                    errors.append(
                        "Model 6 链式中介必须包含 X→M1、X→M2、M1→M2、M1→Y、M2→Y、X→Y 六条路径"
                    )
                elif moderations:
                    errors.append("Model 6 链式中介模型中不允许有调节变量")
                else:
                    template = "model_6"
        elif len(m_nodes) == 1:
            m_id = m_nodes[0].get("id")
            expected = {(x_id, m_id), (x_id, y_id), (m_id, y_id)}
            if actual_edges != expected:
                errors.append("中介结构必须且只能包含 X→M、X→Y、M→Y 三条路径")
            elif not moderations and not role_nodes.get("w"):
                template = "model_4"
            elif len(moderations) == 1:
                target = edge_by_id.get(moderations[0].get("targetEdgeId"), {})
                pair = (target.get("from"), target.get("to"))
                if pair == (x_id, m_id):
                    template = "model_7"
                elif pair == (m_id, y_id):
                    template = "model_14"
                elif pair == (x_id, y_id):
                    template = "model_5"
                else:
                    errors.append(
                        "单调节中介只允许 W 调节 X→Y（Model 5）、X→M（Model 7）或 M→Y（Model 14）"
                    )
            elif len(moderations) == 2:
                moderation_by_pair = {
                    (
                        edge_by_id.get(item.get("targetEdgeId"), {}).get("from"),
                        edge_by_id.get(item.get("targetEdgeId"), {}).get("to"),
                    ): node_by_id.get(item.get("moderatorNodeId"), {}).get("role")
                    for item in moderations
                }
                pairs = set(moderation_by_pair)
                if pairs == {(x_id, m_id), (x_id, y_id)}:
                    if set(moderation_by_pair.values()) == {"w"}:
                        template = "model_8"
                    else:
                        errors.append("Model 8 必须由同一 W 调节 X→M 和 X→Y")
                elif pairs == {(m_id, y_id), (x_id, y_id)}:
                    if set(moderation_by_pair.values()) == {"w"}:
                        template = "model_15"
                    else:
                        errors.append("Model 15 必须由同一 W 调节 M→Y 和 X→Y")
                elif pairs == {(x_id, m_id), (m_id, y_id)}:
                    a_role = moderation_by_pair.get((x_id, m_id))
                    b_role = moderation_by_pair.get((m_id, y_id))
                    if (a_role, b_role) == ("w", "z"):
                        template = "model_21"
                    elif (a_role, b_role) == ("w", "w"):
                        template = "model_58"
                    else:
                        errors.append(
                            "两阶段调节中介必须是 Model 21（W 调节 X→M、Z 调节 M→Y）"
                            "或 Model 58（同一 W 调节两段）"
                        )
                else:
                    errors.append(
                        "双调节中介只允许 Model 8（X→M、X→Y）、Model 15（M→Y、X→Y）"
                        "、Model 21（W 调节 X→M、Z 调节 M→Y）"
                        "或 Model 58（同一 W 调节 X→M、M→Y）"
                    )
            elif len(moderations) == 3:
                moderation_by_pair = {
                    (
                        edge_by_id.get(item.get("targetEdgeId"), {}).get("from"),
                        edge_by_id.get(item.get("targetEdgeId"), {}).get("to"),
                    ): node_by_id.get(item.get("moderatorNodeId"), {}).get("role")
                    for item in moderations
                }
                pairs = set(moderation_by_pair)
                if pairs == {(x_id, m_id), (m_id, y_id), (x_id, y_id)}:
                    roles = (
                        moderation_by_pair.get((x_id, m_id)),
                        moderation_by_pair.get((m_id, y_id)),
                        moderation_by_pair.get((x_id, y_id)),
                    )
                    if roles == ("w", "z", "w"):
                        template = "model_22"
                    elif roles == ("w", "w", "w"):
                        template = "model_59"
                    else:
                        errors.append(
                            "三路径调节中介必须是 Model 22（W/Z/W 分别调节 a/b/直接路径）"
                            "或 Model 59（同一 W 调节全部路径）"
                        )
                else:
                    errors.append(
                        "三路径调节中介必须匹配 Model 22 或 Model 59 的全部三条路径"
                    )
            else:
                errors.append(
                    "中介模型只允许绑定 Model 5/7/8/14/15/21/22/58/59 对应的调节路径"
                )
        else:
            errors.append("中介变量个数不能超过 2 个")

    # The fast recognizer above handles 14 predefined estimators. Its
    # template-mismatch messages are not structural errors: PROCESS 5.0 also
    # contains numbered and custom topologies classified by the catalog.
    del errors[catalog_error_offset:]
    catalog_match = match_process_model(model_spec)
    catalog_fields = catalog_match.as_dict()
    if errors:
        catalog_fields = {
            **catalog_fields,
            "matchStatus": "invalid",
            "executionAvailable": False,
            "unsupportedReason": "请先修正模型结构，再进行 PROCESS 5.0 编号识别",
        }
    template_value = catalog_fields["template"]
    template = template_value if isinstance(template_value, str) else None

    if (
        family == "ols"
        and model_spec.get("design", {}).get("timeStructure") == "cross_sectional"
        and role_nodes.get("m")
    ):
        warnings.append(
            {
                "code": "CROSS_SECTIONAL_MEDIATION",
                "severity": "warning",
                "message": "横截面中介不能仅凭时间顺序支持因果解释；冻结前需记录研究依据。",
            }
        )
    if family == "ols":
        ordinal_nodes = [node.get("label") for node in nodes if node.get("dataType") == "ordinal"]
        if ordinal_nodes:
            warnings.append(
                {
                    "code": "ORDINAL_AS_NUMERIC",
                    "severity": "warning",
                    "message": "以下有序变量将按数值变量处理: " + "、".join(ordinal_nodes),
                }
            )

    return {
        "valid": not errors,
        "structuralStatus": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        **catalog_fields,
        "template": template,
    }


def validate_m0_mediation(model_spec: dict[str, Any]) -> None:
    errors: list[str] = []
    nodes = model_spec["nodes"]
    role_nodes: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        role_nodes.setdefault(node["role"], []).append(node)

    for role in ("x", "m", "y"):
        if len(role_nodes.get(role, [])) != 1:
            errors.append(f"M0 单一中介要求恰好一个 {role.upper()} 节点")

    unsupported_roles = {node["role"] for node in nodes} - {"x", "m", "y"}
    if unsupported_roles:
        errors.append("M0 纵向切片暂不接受以下角色: " + ", ".join(sorted(unsupported_roles)))

    if model_spec["moderations"]:
        errors.append("M0 纵向切片暂不接受调节关系")
    if model_spec["covariates"]:
        errors.append("M0 纵向切片暂不接受控制变量")

    if not errors:
        role_to_id = {role: role_nodes[role][0]["id"] for role in ("x", "m", "y")}
        actual_edges = {(edge["from"], edge["to"]) for edge in model_spec["edges"]}
        expected_edges = {
            (role_to_id["x"], role_to_id["m"]),
            (role_to_id["x"], role_to_id["y"]),
            (role_to_id["m"], role_to_id["y"]),
        }
        if actual_edges != expected_edges:
            errors.append("单一中介必须且只能包含 X→M、X→Y、M→Y 三条路径")

    if model_spec["estimation"]["family"] != "ols":
        errors.append("M0 单一中介仅支持 OLS")

    if errors:
        raise SemanticValidationError(errors)
