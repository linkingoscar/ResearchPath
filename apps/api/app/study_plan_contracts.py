from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.analysis_context_contracts import ContractBaseModel, Hash
from app.study_context_contracts import StudyContextInput

PlanScalar = str | int | float | bool


class StudyPlanCreateRequest(ContractBaseModel):
    payload: dict[str, object]


class StudyPlanMutation(ContractBaseModel):
    expected_revision: int = Field(ge=1)
    payload: dict[str, object]


class StudyPlanHypothesis(ContractBaseModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=500)
    analysis_role: Literal["primary", "robustness", "exploratory"]
    declaration_timing: Literal["preregistered", "registered", "post_hoc", "unspecified"]
    direction: Literal["positive", "negative", "two_sided", "non_directional"]
    estimand_ids: list[str]


class StudyPlanContrast(ContractBaseModel):
    type: Literal["binary_transition", "pairwise", "planned_contrast", "custom"]
    from_: PlanScalar = Field(alias="from")
    to: PlanScalar


class StudyPlanConditioning(ContractBaseModel):
    variable_id: str = Field(min_length=1)
    values: list[PlanScalar]
    value_scale: str = Field(min_length=1, max_length=100)


class StudyPlanEstimand(ContractBaseModel):
    id: str = Field(min_length=1, max_length=100)
    quantity: str = Field(min_length=1, max_length=100)
    outcome_id: str | None = None
    focal_predictor_id: str | None = None
    outcome_scale: str = Field(default="original", min_length=1, max_length=100)
    population: str = Field(default="analysis_sample", min_length=1, max_length=100)
    contrast: StudyPlanContrast | None = None
    conditioning: StudyPlanConditioning | None = None
    causal_target: bool = False


class StudyPlanAnalysisDeclaration(ContractBaseModel):
    id: str = Field(min_length=1, max_length=100)
    role: Literal["primary", "robustness", "exploratory"]
    estimand_ids: list[str]
    capability_slice_id: str = Field(min_length=1, max_length=200)
    requested_method: str = Field(min_length=1, max_length=100)
    robustness_analysis_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, object] = Field(default_factory=dict)


class StudyPlanMultiplicityFamily(ContractBaseModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    role: Literal["primary", "secondary", "robustness", "exploratory"] | None = None
    adjustment: Literal["none", "holm", "BH", "bonferroni"] | None = None
    member_estimand_ids: list[str] = Field(default_factory=list)
    member_type: Literal["hypothesis", "estimand", "analysis"] | None = None
    member_ids: list[str] = Field(default_factory=list)
    adjustment_method: Literal["none", "holm", "BH", "bonferroni"] | None = None

    @model_validator(mode="after")
    def validate_declaration_shape(self) -> "StudyPlanMultiplicityFamily":
        modern = bool(self.member_estimand_ids)
        compact = self.member_type is not None or bool(self.member_ids)
        if modern and compact:
            raise ValueError("MULTIPLICITY_FAMILY_SHAPE_AMBIGUOUS: 不得同时使用 memberEstimandIds 与 memberType/memberIds")
        if modern and self.role is None:
            raise ValueError("MULTIPLICITY_FAMILY_ROLE_REQUIRED: declaration-driven family 必须声明 role")
        if not modern and (self.member_type is None or not self.member_ids):
            raise ValueError("MULTIPLICITY_FAMILY_MEMBERS_REQUIRED: 必须声明 memberEstimandIds 或 memberType/memberIds")
        if self.adjustment is not None and self.adjustment_method is not None and self.adjustment != self.adjustment_method:
            raise ValueError("MULTIPLICITY_FAMILY_ADJUSTMENT_AMBIGUOUS: adjustment 与 adjustmentMethod 不一致")
        if self.adjustment is None and self.adjustment_method is None:
            raise ValueError("MULTIPLICITY_FAMILY_ADJUSTMENT_REQUIRED: 必须声明 adjustment")
        return self


class StudyPlanVariableRole(ContractBaseModel):
    key: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=100)
    level: int = Field(default=1, ge=1, le=3)
    variable_id: str | None = None
    accepted_types: list[str] = Field(default_factory=list)
    structure_role: Literal[
        "subjectId", "clusterId", "timeId", "groupId", "treatmentId"
    ] | None = None


class StudyPlanSampleDefinition(ContractBaseModel):
    roles: list[StudyPlanVariableRole] = Field(default_factory=list)
    unit_of_analysis: str | None = None
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)


class StudyPlanConstruct(ContractBaseModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    item_ids: list[str] = Field(default_factory=list)


class StudyPlanMeasurementPlan(ContractBaseModel):
    constructs: list[StudyPlanConstruct] = Field(default_factory=list)
    measurement_version_id: str | None = None


class StudyPlanMissingDataPlan(ContractBaseModel):
    strategy: str = Field(min_length=1, max_length=200)
    sensitivity_analysis_ids: list[str] = Field(default_factory=list)
    report_missingness: bool = True


class StudyPlanMigration(ContractBaseModel):
    from_schema_version: Literal["1.0.0"]
    mode: Literal["automatic_draft"]


class StudyPlanPayload(ContractBaseModel):
    schema_version: Literal["2.0.0"] = "2.0.0"
    title: str = Field(default="未命名研究计划", min_length=1, max_length=200)
    research_question: str = Field(default="", max_length=2000)
    hypotheses: list[StudyPlanHypothesis]
    estimands: list[StudyPlanEstimand]
    analysis_declarations: list[StudyPlanAnalysisDeclaration]
    multiplicity_families: list[StudyPlanMultiplicityFamily]
    sample_definition: StudyPlanSampleDefinition
    measurement_plan: StudyPlanMeasurementPlan
    missing_data_plan: StudyPlanMissingDataPlan
    power_plan: dict[str, object] | None = None
    context: StudyContextInput
    migration: StudyPlanMigration | None = None


class StudyPlanVersion(StudyPlanPayload):
    id: str = Field(pattern=r"^study_plan_[a-f0-9]{32}$")
    project_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    status: Literal["draft", "frozen"]
    plan_hash: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: str = Field(min_length=1)


class StudyPlanBinding(ContractBaseModel):
    study_plan_version_id: str = Field(pattern=r"^study_plan_[a-f0-9]{32}$")
    study_plan_hash: Hash = Field(pattern=r"^[a-f0-9]{64}$")
    hypothesis_id: str = Field(min_length=1, max_length=100)
    hypothesis_ids: list[str] | None = Field(default=None, min_length=1)
    estimand_id: str = Field(min_length=1, max_length=100)
    analysis_declaration_id: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_hypothesis_ids(self) -> "StudyPlanBinding":
        if self.hypothesis_ids is not None:
            if self.hypothesis_id not in self.hypothesis_ids:
                raise ValueError(
                    "STUDY_PLAN_BINDING_HYPOTHESIS_MISMATCH: hypothesisIds 必须包含 hypothesisId"
                )
            if len(set(self.hypothesis_ids)) != len(self.hypothesis_ids):
                raise ValueError(
                    "STUDY_PLAN_BINDING_HYPOTHESIS_DUPLICATE: hypothesisIds 不得重复"
                )
        return self


class StudyPlanDatasetMappingRequest(ContractBaseModel):
    dataset_version_id: str
    mapping: dict[str, object]
    status: Literal["incomplete", "ready", "deviated"] = "incomplete"


class StudyPlanDatasetMapping(ContractBaseModel):
    id: str
    study_plan_version_id: str
    dataset_version_id: str
    mapping: dict[str, object]
    mapping_hash: Hash
    status: Literal["incomplete", "ready", "deviated"]
    created_at: str
