from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from app.capability_evidence import capability_evidence

ValidationLevel = Literal[
    "unvalidated", "internally_validated", "externally_validated"
]
MaturityLevel = Literal[
    "experimental", "validated", "reviewer_ready", "publication_ready"
]
PublicationEligibility = Literal["ineligible", "conditional", "eligible"]


@dataclass(frozen=True)
class ValidationEvidence:
    """Evidence inputs for the capability maturity gate.

    The fields describe reproducible evidence classes, not a slice allowlist.
    An external oracle and numeric golden are intentionally separate: a frozen
    product fixture is not promoted to an external oracle merely because it is
    versioned.
    """

    contract_tests: bool = False
    applicability_tests: bool = False
    failure_fixtures: bool = False
    external_oracle: str | None = None
    numeric_golden_id: str | None = None
    oracle_independence: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "contractTests": self.contract_tests,
            "applicabilityTests": self.applicability_tests,
            "failureFixtures": self.failure_fixtures,
            "externalOracle": self.external_oracle,
            "numericGoldenId": self.numeric_golden_id,
            "oracleIndependence": self.oracle_independence,
        }


def _manifest_validation_evidence(slice_id: str) -> ValidationEvidence:
    entry = capability_evidence(slice_id)
    tests = cast(dict[str, object], entry["tests"])
    oracle = cast(dict[str, object], entry["oracle"])
    return ValidationEvidence(
        contract_tests=tests.get("contract") is True,
        applicability_tests=tests.get("applicability") is True,
        failure_fixtures=tests.get("failureFixtures") is True,
        external_oracle=cast(str | None, oracle.get("name")),
        numeric_golden_id=cast(str | None, tests.get("numericGoldenId")),
        oracle_independence=cast(str | None, oracle.get("independence")),
    )


@dataclass(frozen=True)
class CapabilityGateResult:
    validation_level: ValidationLevel
    maturity_level: MaturityLevel
    publication_eligibility: PublicationEligibility
    publication_eligibility_reason: str
    validation_evidence: ValidationEvidence

    def to_dict(self) -> dict[str, object]:
        return {
            "validationLevel": self.validation_level,
            "maturityLevel": self.maturity_level,
            "publicationEligibility": self.publication_eligibility,
            "publicationEligibilityReason": self.publication_eligibility_reason,
            "validationEvidence": self.validation_evidence.to_dict(),
        }


def derive_capability_gates(
    evidence: ValidationEvidence,
    *,
    publication_gate_passed: bool = False,
) -> CapabilityGateResult:
    """Derive capability status from evidence, never from a slice ID.

    The publication gate is deliberately separate from validation evidence.
    Until the later evidence-manifest/publication gate exists, externally
    validated slices are reviewer-ready and remain conditionally eligible.
    """

    internal_complete = all(
        (
            evidence.contract_tests,
            evidence.applicability_tests,
            evidence.failure_fixtures,
        )
    )
    external_complete = internal_complete and bool(
        evidence.external_oracle and evidence.numeric_golden_id
    )
    if not internal_complete:
        return CapabilityGateResult(
            validation_level="unvalidated",
            maturity_level="experimental",
            publication_eligibility="ineligible",
            publication_eligibility_reason=(
                "当前能力尚未通过完整的 contract、适用性和失败边界证据门禁；"
                "executionAvailable 不代表已验证。"
            ),
            validation_evidence=evidence,
        )
    if not external_complete:
        return CapabilityGateResult(
            validation_level="internally_validated",
            maturity_level="validated",
            publication_eligibility="conditional",
            publication_eligibility_reason=(
                "当前能力已通过内部 contract、适用性和失败边界测试；"
                "仍需外部 oracle/数值金标准及论文级证据编排。"
            ),
            validation_evidence=evidence,
        )
    if publication_gate_passed:
        return CapabilityGateResult(
            validation_level="externally_validated",
            maturity_level="publication_ready",
            publication_eligibility="eligible",
            publication_eligibility_reason="已通过外部数值验证及后续论文级证据发布门禁。",
            validation_evidence=evidence,
        )
    return CapabilityGateResult(
        validation_level="externally_validated",
        maturity_level="reviewer_ready",
        publication_eligibility="conditional",
        publication_eligibility_reason=(
            "当前能力已通过内部测试、外部 oracle 和数值金标准；"
            "仍需论文级 evidence manifest/publication gate 才能作为主分析发布。"
        ),
        validation_evidence=evidence,
    )


@dataclass(frozen=True)
class CapabilityDefinition:
    family: str
    slice_id: str
    label: str
    status: str
    execution_available: bool
    validation_level: ValidationLevel
    maturity_level: MaturityLevel
    publication_eligibility: PublicationEligibility
    publication_eligibility_reason: str
    validation_evidence: ValidationEvidence
    product_visible: bool
    time_structures: tuple[str, ...]
    dependence_structures: tuple[str, ...]
    designs: tuple[str, ...]
    required_roles: tuple[str, ...]
    optional_roles: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    support_boundary: str
    profile_requirement: str | None = None
    supports_causal_target: bool = False


ALL_DESIGNS = ("observational", "randomized", "quasi_experimental")

def _definition(
    slice_id: str,
    label: str,
    time_structures: tuple[str, ...],
    dependence_structures: tuple[str, ...],
    designs: tuple[str, ...],
    required_roles: tuple[str, ...],
    required_artifacts: tuple[str, ...],
    boundary: str,
    *,
    product_visible: bool = True,
    profile_requirement: str | None = None,
    supports_causal_target: bool = False,
) -> CapabilityDefinition:
    evidence = _manifest_validation_evidence(slice_id)
    gates = derive_capability_gates(evidence)
    if slice_id.startswith("experimental_design.") and gates.validation_level == "unvalidated":
        reason = (
            "当前仅提供受限实验统计估计；尚无完整验证证据协议，"
            "也不提供准实验因果识别。"
        )
    elif slice_id.startswith("questionnaire_measurement.") and gates.validation_level == "unvalidated":
        reason = "当前高级测量切片仍需补齐内部失败边界和外部数值验证。"
    elif slice_id.startswith("empirical.diary.") and gates.validation_level == "unvalidated":
        reason = "当前日记/ESM 切片仍需按模型补齐失败边界、外部验证和论文级证据编排。"
    else:
        reason = gates.publication_eligibility_reason
    gates = CapabilityGateResult(
        validation_level=gates.validation_level,
        maturity_level=gates.maturity_level,
        publication_eligibility=gates.publication_eligibility,
        publication_eligibility_reason=reason,
        validation_evidence=gates.validation_evidence,
    )
    return CapabilityDefinition(
        family=slice_id.split(".", 1)[0],
        slice_id=slice_id,
        label=label,
        status="supported" if slice_id.startswith(("empirical.", "model.")) else "experimental",
        execution_available=True,
        validation_level=gates.validation_level,
        maturity_level=gates.maturity_level,
        publication_eligibility=gates.publication_eligibility,
        publication_eligibility_reason=gates.publication_eligibility_reason,
        validation_evidence=gates.validation_evidence,
        product_visible=product_visible,
        time_structures=time_structures,
        dependence_structures=dependence_structures,
        designs=designs,
        required_roles=required_roles,
        optional_roles=(),
        required_artifacts=required_artifacts,
        support_boundary=boundary,
        profile_requirement=profile_requirement,
        supports_causal_target=supports_causal_target,
    )


def A(
    slice_id: str,
    label: str,
    time: tuple[str, ...],
    dependence: tuple[str, ...],
    roles: tuple[str, ...],
    artifacts: tuple[str, ...],
    boundary: str,
    *,
    designs: tuple[str, ...] = ALL_DESIGNS,
    visible: bool = True,
    profile: str | None = None,
    supports_causal_target: bool = False,
) -> CapabilityDefinition:
    return _definition(
        slice_id, label, time, dependence, designs, roles, artifacts, boundary,
        product_visible=visible, profile_requirement=profile,
        supports_causal_target=supports_causal_target,
    )


ACTIVE_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    A("experimental_design.factorial_anova.long.single_outcome", "随机实验：组间 factorial ANOVA", ("cross_sectional",), ("independent",), ("groupId", "treatmentId"), ("dataset", "sample"), "仅随机分配的横截面单 outcome；不提供准实验因果识别", designs=("randomized",)),
    A("experimental_design.ancova.long.single_outcome", "随机实验：组间 ANCOVA", ("cross_sectional",), ("independent",), ("groupId", "treatmentId"), ("dataset", "sample"), "仅随机分配的横截面单 outcome；协变量调整不构成准实验识别", designs=("randomized",)),
    A("experimental_design.repeated_measures.single_within", "随机实验：单一组内因子重复测量", ("panel",), ("independent",), ("subjectId", "timeId"), ("dataset", "sample"), "仅随机实验；额外 cluster 阻塞", designs=("randomized",)),
    A("experimental_design.mixed_design.single_within", "随机实验：单一组内因子混合设计", ("panel",), ("independent",), ("subjectId", "timeId", "groupId"), ("dataset", "sample"), "仅随机实验；额外 cluster 阻塞", designs=("randomized",)),
    A("experimental_design.glm_cluster.long.single_outcome", "随机实验：cluster-robust Gaussian GLM", ("cross_sectional",), ("nested",), ("clusterId", "groupId", "treatmentId"), ("dataset", "sample"), "仅随机分配、两层、单 outcome 的 CR0 线性模型；不冒充 CR2/GLMM 或准实验识别", designs=("randomized",), profile="two_level"),
    A("multilevel_model.aggregation.icc_rwg", "ICC(1)/ICC(2)/rwg 聚合证据", ("cross_sectional",), ("nested",), ("clusterId",), ("dataset",), "不替代多层测量模型", profile="two_level"),
    A("multilevel_model.gaussian.two_level", "两层 Gaussian LMM", ("cross_sectional",), ("nested",), ("clusterId",), ("dataset", "sample"), "单一 cluster、Gaussian", profile="two_level"),
    A("power_analysis.analytic.regression", "回归解析功效", ("cross_sectional", "panel", "intensive_longitudinal"), ("independent", "nested"), (), ("dataset",), "Cohen f²/R² change"),
    A("power_analysis.analytic.t_test", "t 检验解析功效", ("cross_sectional",), ("independent",), (), ("dataset",), "不冒充配对/重复测量 t"),
    A("power_analysis.analytic.factorial_anova", "随机组间 ANOVA 功效", ("cross_sectional",), ("independent",), ("groupId", "treatmentId"), ("dataset",), "仅预先声明的均衡随机组间设计；不替代准实验识别功效分析", designs=("randomized",)),
    A("power_analysis.monte_carlo", "登记 DGP 的 Monte Carlo 功效", ("cross_sectional", "panel", "intensive_longitudinal"), ("independent", "nested"), (), ("dataset",), "受资源预算与登记 DGP 约束"),
    A("multiple_imputation.mice_dataset_generation", "MICE 插补数据集生成", ("cross_sectional",), ("independent",), (), ("dataset", "sample"), "API 兼容；不作为正式入口", visible=False),
    A("multiple_imputation.rubin_pooling", "Rubin 合并推断", ("cross_sectional",), ("independent",), (), ("dataset", "sample"), "仅冻结线性回归消费者；独立横截面不强制虚构结构角色"),
    A("questionnaire_measurement.reliability", "Ordinal reliability", ("cross_sectional",), ("independent",), (), ("dataset", "measurement"), "横截面独立测量准备"),
    A("questionnaire_measurement.efa", "Polychoric EFA/MAP", ("cross_sectional",), ("independent",), (), ("dataset", "measurement"), "显式题项和旋转"),
    A("questionnaire_measurement.cfa", "CFA ML/MLR/WLSMV", ("cross_sectional",), ("independent",), (), ("dataset", "measurement"), "收敛/Heywood 显式返回"),
    A("questionnaire_measurement.measurement_invariance", "多组测量等值性", ("cross_sectional",), ("independent",), ("groupId",), ("dataset", "measurement"), "纵向等值性走 panel 专属流程"),
    A("questionnaire_measurement.esem_bifactor_irt", "ESEM/Bifactor/IRT/DIF", ("cross_sectional",), ("independent",), (), ("dataset", "measurement"), "不适用于 panel/ESM"),
    A("questionnaire_measurement.common_method_bias", "Marker/ULMC CMB 诊断", ("cross_sectional",), ("independent",), (), ("dataset", "measurement"), "需 marker 或 ULMC 规格"),
    A("empirical.cross_sectional.overview", "横截面描述与缺失诊断", ("cross_sectional",), ("independent", "nested"), (), ("dataset", "sample"), "nested 时仅描述，不使用逐行独立性推断"),
    A("empirical.cross_sectional.measurement", "横截面基础测量准备", ("cross_sectional",), ("independent", "nested"), (), ("dataset", "measurement", "sample"), "nested 时测量结果仅作准备，确认性推断需多层测量模型"),
    A("empirical.cross_sectional.group_comparison", "横截面组间比较", ("cross_sectional",), ("independent",), (), ("dataset", "sample"), "groupVariableId 由分析规格显式绑定，且不自动等同 cluster；构念得分需要测量版本，原始变量不需要"),
    A("empirical.cross_sectional.hierarchical_regression", "横截面分层回归", ("cross_sectional",), ("independent",), (), ("dataset", "sample"), "X/Y 由规格声明；构念得分需要测量版本，原始变量不需要"),
    A("empirical.cross_sectional.response_surface", "横截面响应面分析", ("cross_sectional",), ("independent",), (), ("dataset", "sample"), "Y/X/Z 由规格声明；构念得分需要测量版本，原始变量不需要"),
    A("model.process_catalog", "PROCESS 过程模型", ("cross_sectional",), ("independent",), (), ("dataset", "measurement", "sample"), "topology 由模型规格声明；X 仅支持连续或 0/1 二分类，M 仅支持连续（二分类中介不支持），多类别 X（mcx）不执行"),
    A("model.sem", "结构方程模型", ("cross_sectional",), ("independent",), (), ("dataset", "measurement", "sample"), "模型图通过 family contract"),
    A("empirical.panel.clpm", "传统 CLPM", ("panel",), ("independent",), ("subjectId", "timeId"), ("dataset", "measurement", "sample"), "至少 3 波"),
    A("empirical.panel.ri_clpm", "RI-CLPM", ("panel",), ("independent",), ("subjectId", "timeId"), ("dataset", "measurement", "sample"), "至少 3 波", profile="panel_min_3"),
    A("empirical.panel.lcm_sr", "LCM-SR", ("panel",), ("independent",), ("subjectId", "timeId"), ("dataset", "measurement", "sample"), "至少 5 波", profile="panel_min_5"),
    A("empirical.panel.invariance", "纵向测量等值性", ("panel",), ("independent",), ("subjectId", "timeId"), ("dataset", "measurement", "sample"), "等值性层级和释放记录"),
    A("empirical.panel.ulmc_sensitivity", "纵向 ULMC 敏感性", ("panel",), ("independent",), ("subjectId", "timeId"), ("dataset", "measurement", "sample"), "仅敏感性分析"),
    A("empirical.diary.quality", "日记/ESM 数据质量", ("intensive_longitudinal",), ("independent",), ("subjectId", "timeId"), ("dataset", "sample"), "依从性、排序和滞后可用性"),
    A("empirical.diary.lmm", "日记/ESM Gaussian LMM", ("intensive_longitudinal",), ("independent",), ("subjectId", "timeId"), ("dataset", "sample"), "within/between 和 AR(1) 显式声明"),
    A("empirical.diary.glmm", "日记/ESM GLMM", ("intensive_longitudinal",), ("independent",), ("subjectId", "timeId"), ("dataset", "sample"), "分布和零过程显式声明"),
    A("empirical.diary.cross_classified_gaussian", "ESM cross-classified Gaussian", ("intensive_longitudinal",), ("nested",), ("subjectId", "timeId", "clusterId"), ("dataset", "sample"), "仅 cross_classified", profile="cross_classified"),
    A("empirical.diary.multilevel_mediation", "日记/ESM 多层中介", ("intensive_longitudinal",), ("independent",), ("subjectId", "timeId"), ("dataset", "sample"), "仅登记的 1-1-1/2-1-1"),
    A("empirical.diary.dsem", "观测变量 Bayesian DSEM", ("intensive_longitudinal",), ("independent",), ("subjectId", "timeId"), ("dataset", "sample"), "至少 T≥20", profile="diary_min_20"),
    A("empirical.diary.mi", "日记/ESM 二层 MI", ("intensive_longitudinal",), ("independent",), ("subjectId", "timeId"), ("dataset", "sample"), "不与通用横截面 MI 混用"),
    A("empirical.diary.power", "日记/ESM person-by-occasion 功效", ("intensive_longitudinal",), ("independent", "nested"), ("subjectId", "timeId"), ("dataset", "sample"), "由计划/分析参数决定"),
)


def capability_gate_metadata(slice_id: str) -> CapabilityGateResult:
    definition = next(
        (item for item in ACTIVE_CAPABILITIES if item.slice_id == slice_id), None
    )
    if definition is not None:
        return CapabilityGateResult(
            validation_level=definition.validation_level,
            maturity_level=definition.maturity_level,
            publication_eligibility=definition.publication_eligibility,
            publication_eligibility_reason=definition.publication_eligibility_reason,
            validation_evidence=definition.validation_evidence,
        )
    return CapabilityGateResult(
        validation_level="unvalidated",
        maturity_level="experimental",
        publication_eligibility="ineligible",
        publication_eligibility_reason="当前切片未进入统一活动能力目录，因此不具备论文主分析资格。",
        validation_evidence=ValidationEvidence(),
    )


def capability_maturity_metadata(slice_id: str) -> tuple[MaturityLevel, PublicationEligibility, str]:
    gate = capability_gate_metadata(slice_id)
    return (
        gate.maturity_level,
        gate.publication_eligibility,
        gate.publication_eligibility_reason,
    )


def capability_family_gate_metadata(slice_ids: tuple[str, ...]) -> CapabilityGateResult:
    definitions = [
        next((item for item in ACTIVE_CAPABILITIES if item.slice_id == slice_id), None)
        for slice_id in slice_ids
    ]
    evidence = [item.validation_evidence for item in definitions if item is not None]
    if not evidence:
        return derive_capability_gates(ValidationEvidence())
    external_oracles = {item.external_oracle for item in evidence if item.external_oracle}
    numeric_goldens = {item.numeric_golden_id for item in evidence if item.numeric_golden_id}
    oracle_independence = {
        item.oracle_independence for item in evidence if item.oracle_independence
    }
    oracle_independence_complete = bool(external_oracles) and all(
        item.external_oracle is None or item.oracle_independence
        for item in evidence
    )
    aggregate = ValidationEvidence(
        contract_tests=all(item.contract_tests for item in evidence),
        applicability_tests=all(item.applicability_tests for item in evidence),
        failure_fixtures=all(item.failure_fixtures for item in evidence),
        external_oracle=next(iter(external_oracles)) if len(external_oracles) == 1 else None,
        numeric_golden_id=next(iter(numeric_goldens)) if len(numeric_goldens) == 1 else None,
        oracle_independence=(
            " | ".join(sorted(oracle_independence))
            if oracle_independence_complete
            else None
        ),
    )
    return derive_capability_gates(aggregate)


def capability_family_maturity_metadata(
    slice_ids: tuple[str, ...]
) -> tuple[MaturityLevel, PublicationEligibility, str]:
    gate = capability_family_gate_metadata(slice_ids)
    return (
        gate.maturity_level,
        gate.publication_eligibility,
        gate.publication_eligibility_reason,
    )
