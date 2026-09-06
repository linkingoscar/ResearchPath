from __future__ import annotations

import json
from pathlib import Path

from app.capability_catalog import ACTIVE_CAPABILITIES
from app.services.advanced_analysis import advanced_analysis_registry

ROOT = Path(__file__).resolve().parents[3]


def test_unified_empirical_catalog_covers_every_executable_advanced_slice() -> None:
    catalog = (ROOT / "docs" / "07-能力矩阵与路线图.md").read_text(encoding="utf-8")
    assert "specs/capability-evidence.json" in catalog
    assert "not_formally_frozen" in catalog
    assert all(
        key in catalog
        for key in (
            "`executionAvailable`",
            "`validationLevel`",
            "`validationEvidence`",
            "`maturityLevel`",
            "`publicationEligibility`",
            "`publication_ready`",
            "`reviewer_ready`",
            "`conditional`",
        )
    )

    executable_slice_ids = {
        capability_slice["id"]
        for capability in advanced_analysis_registry.capabilities()
        for capability_slice in capability["slices"]
        if capability_slice["executionAvailable"]
    }
    undocumented = sorted(slice_id for slice_id in executable_slice_ids if slice_id not in catalog)
    assert undocumented == []


def test_unified_empirical_catalog_covers_the_complete_activity_source_without_ghost_entries() -> None:
    catalog = (ROOT / "docs" / "07-能力矩阵与路线图.md").read_text(
        encoding="utf-8"
    )
    undocumented = sorted(
        definition.slice_id
        for definition in ACTIVE_CAPABILITIES
        if definition.execution_available and definition.slice_id not in catalog
    )
    assert undocumented == []
    assert len(ACTIVE_CAPABILITIES) == 39
    assert sum(definition.product_visible for definition in ACTIVE_CAPABILITIES) == 38
    assert "LongitudinalAnalysisWorkspace" not in catalog
    assert "DiaryEsmAnalysisWorkspace" not in catalog
    assert "longitudinal_model.observed_growth" in catalog
    assert "longitudinal_model.ri_clpm" in catalog
    assert "longitudinal_model.longitudinal_invariance" in catalog
    assert all(
        component in catalog
        for component in (
            "EmpiricalAnalysis",
            "LongitudinalPanelConfig",
            "DiaryMultilevelConfig",
            "LongitudinalMethodsSection",
        )
    )
    assert "不提供准实验因果识别" in catalog


def test_catalog_method_claims_match_registry_schema_and_manifest() -> None:
    catalog = (ROOT / "docs" / "07-能力矩阵与路线图.md").read_text(encoding="utf-8")
    schema = json.loads(
        (ROOT / "specs" / "advanced-analysis-spec.schema.json").read_text(encoding="utf-8")
    )
    measurement = next(
        capability
        for capability in advanced_analysis_registry.capabilities()
        if capability["family"] == "questionnaire_measurement"
    )
    measurement_boundary = next(
        item["supportBoundary"]
        for item in measurement["slices"]
        if item["id"] == "questionnaire_measurement.esem_bifactor_irt"
    )

    schema_text = json.dumps(schema, ensure_ascii=False)
    assert all(token in schema_text for token in ('"MML"', '"target"', '"2PL"', '"GRM"'))
    assert all(token in measurement_boundary for token in ("MML", "2PL", "GRM", "有序 ESEM 尚未开放"))
    assert all(
        token in catalog
        for token in (
            "pValueRaw",
            "pValueAdjusted",
            "当前未接入操纵检验、基线平衡结论和 CONSORT 样本流",
        )
    )
    assert not (ROOT / "engine" / "R" / "lib" / "experiment_protocol.R").exists()
    manifest = json.loads((ROOT / "project.manifest.json").read_text(encoding="utf-8"))
    assert any(
        "quasi-experimental causal identification" in item
        for item in manifest["productScope"]["deferred"]
    )


def test_oracle_matrix_disclaimer_prevents_registry_validation_inflation() -> None:
    methods_doc = (ROOT / "docs" / "02-统计方法与报告规范.md").read_text(encoding="utf-8")
    assert "上表 ✅ 只表示" in methods_doc
    assert "同库装配或内部契约对照" in methods_doc
    assert "不得用本矩阵的 ✅ 推导" in methods_doc


def test_base_empirical_runner_never_auto_executes_advanced_measurement_models() -> None:
    runner = (ROOT / "engine" / "R" / "run_empirical_analysis.R").read_text(
        encoding="utf-8"
    )
    assert '"esem_bifactor.R"' not in runner
    assert "fit_bifactor_model(" not in runner
    assert "fit_esem_model(" not in runner
    assert "fit_irt_dif_model(" not in runner
    assert 'availableThrough = "advanced_workbench"' in runner


def test_observational_workflow_entry_labels_do_not_predeclare_causality_or_mechanisms() -> None:
    workspace = (ROOT / "apps" / "web" / "src" / "hooks" / "workspaceStateSelectors.ts").read_text(
        encoding="utf-8"
    )
    toolbar = (
        ROOT
        / "apps"
        / "web"
        / "src"
        / "components"
        / "model-builder"
        / "ModelBuilderToolbar.tsx"
    ).read_text(encoding="utf-8")
    assert "纵向因果模型图" not in workspace
    assert "label: '分析'" in workspace
    assert "label: '路径与 SEM'" not in workspace
    assert "中介机制" not in toolbar
    assert "影响通过什么机制发生" not in toolbar
    assert "中介分析" in toolbar
    assert "变量之间的间接关联如何分解" in toolbar


def test_local_privacy_copy_matches_localhost_api_and_r_process_architecture() -> None:
    privacy = (
        ROOT
        / "apps"
        / "web"
        / "src"
        / "components"
        / "shared"
        / "LocalPrivacyBadge.tsx"
    ).read_text(encoding="utf-8")
    assert "WebAssembly" not in privacy
    assert "完全在浏览器本地内存" not in privacy
    assert "没有任何数据通过网络传输" not in privacy
    assert "localhost HTTP API" in privacy
    assert "本机 FastAPI" in privacy
    assert "本机 R worker / 子进程" in privacy
    assert "本机网络栈" in privacy
    assert "不会把研究数据上传到远端云服务" in privacy
    assert "工作区结果可持久化" in privacy
