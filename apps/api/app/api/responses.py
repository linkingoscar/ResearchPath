from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExtensibleResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class WarningResponse(ExtensibleResponse):
    code: str
    severity: Literal["info", "warning", "error"] = "warning"
    message: str


class StudyPlanBindingResponse(ExtensibleResponse):
    studyPlanVersionId: str
    studyPlanHash: str
    hypothesisId: str
    hypothesisIds: list[str] | None = None
    estimandId: str
    analysisDeclarationId: str
    status: Literal["current", "stale"]
    currentEvidence: bool
    staleReasons: list[str]
    datasetSha256: str | None = None
    sampleVersionId: str | None = None
    sampleHash: str | None = None
    measurementVersionId: str | None = None
    measurementHash: str | None = None
    specHash: str | None = None
    declarationStatus: Literal["declared", "deviated"] | None = None
    deviationReason: str | None = None
    publicationEligible: bool | None = None


class SessionResponse(BaseModel):
    token: str
    headerName: str


class SessionBootstrapRequest(BaseModel):
    bootstrapToken: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    apiVersion: str
    rAvailable: bool
    rExecutable: bool
    diskFreeBytes: int
    diskFreePercent: float


class DemoResponse(BaseModel):
    datasetId: str
    datasetLabel: str
    modelSpec: dict[str, object]


class DemoProjectRequest(BaseModel):
    timeStructure: Literal["cross_sectional", "panel", "intensive_longitudinal"] = "cross_sectional"


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetWarningResponse(_StrictResponse):
    code: str = Field(min_length=1)
    severity: Literal["warning"] = "warning"
    message: str = Field(min_length=1)


class DatasetOriginalFileResponse(_StrictResponse):
    name: str = Field(min_length=1, max_length=240)
    format: Literal["csv", "xlsx", "sav", "dta", "por"]
    sizeBytes: int = Field(ge=1, le=52428800)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    encoding: str | None = None
    delimiter: str | None = Field(default=None, min_length=1, max_length=1)
    sheet: str | None = None
    sheetNames: list[str] | None = None


class DatasetStorageResponse(_StrictResponse):
    raw: str = Field(min_length=1)
    normalized: str = Field(min_length=1)


class DatasetVariableResponse(_StrictResponse):
    id: str = Field(pattern=r"^var_[0-9]+_[a-f0-9]{8}$")
    originalName: str = Field(min_length=1)
    label: str = Field(min_length=1)
    storageType: str = Field(min_length=1)
    inferredType: Literal["continuous", "binary", "nominal", "ordinal", "likert", "id", "text"]
    confirmedType: (
        Literal["continuous", "binary", "nominal", "ordinal", "likert", "id", "text"] | None
    )
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)
    missingCount: int = Field(ge=0)
    missingRate: float = Field(ge=0, le=1)
    uniqueCount: int = Field(ge=0)
    sampleValues: list[str | int | float | bool | None] | None = Field(default=None, max_length=5)
    valueLabels: dict[str, str | int | float | bool] = Field(default_factory=dict)
    issues: list[Literal["constant_or_empty", "high_missing"]] = Field(default_factory=list)
    minimum: float | None = None
    maximum: float | None = None


class DatasetDictionaryResponse(_StrictResponse):
    version: int = Field(ge=0)
    confirmedCount: int = Field(ge=0)
    totalCount: int = Field(ge=1)
    status: Literal["draft", "confirmed"]


class DatasetLineageSourceResponse(_StrictResponse):
    datasetVersionId: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class DatasetLineageResponse(_StrictResponse):
    operation: Literal["outer_merge"]
    sources: list[DatasetLineageSourceResponse] = Field(min_length=2)
    subjectKey: str = Field(min_length=1)
    waveKey: str | None = None
    joinType: Literal["outer"]
    joinKeys: list[str] = Field(min_length=1)
    reportSha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class DatasetVersionResponse(_StrictResponse):
    schemaVersion: Literal["1.0.0"]
    id: str = Field(pattern=r"^dataset_[a-f0-9]{16}$")
    projectId: Literal["default"]
    createdAt: str
    originalFile: DatasetOriginalFileResponse
    storage: DatasetStorageResponse
    rowCount: int = Field(ge=1)
    columnCount: int = Field(ge=1)
    variables: list[DatasetVariableResponse] = Field(min_length=1)
    preview: list[dict[str, object]]
    warnings: list[DatasetWarningResponse]
    dictionary: DatasetDictionaryResponse
    lineage: DatasetLineageResponse | None = None


class MeasurementConstructResponse(_StrictResponse):
    id: str = Field(pattern=r"^construct_[a-z0-9_-]{1,50}$")
    name: str = Field(min_length=1, max_length=100)
    itemIds: list[str] = Field(min_length=2)
    reverseItemIds: list[str] = Field(default_factory=list)
    theoreticalMinimum: float
    theoreticalMaximum: float
    aggregation: Literal["mean", "sum"]
    minimumValidProportion: float = Field(gt=0, le=1)
    minimumValidItems: int = Field(ge=1)
    outputVariableId: str = Field(pattern=r"^scale_[a-z0-9_-]{1,50}$")


class MeasurementItemAnalysisResponse(_StrictResponse):
    itemId: str = Field(pattern=r"^var_[0-9]+_[a-f0-9]{8}$")
    label: str = Field(min_length=1)
    reversed: bool
    validCount: int = Field(ge=0)
    missingCount: int = Field(ge=0)
    mean: float | None
    standardDeviation: float | None
    floorRate: float | None = Field(default=None, ge=0, le=1)
    ceilingRate: float | None = Field(default=None, ge=0, le=1)
    correctedItemTotalCorrelation: float | None
    alphaIfDeleted: float | None
    omegaIfDeleted: float | None


class MeasurementDistributionResponse(_StrictResponse):
    validCount: int = Field(ge=0)
    missingCount: int = Field(ge=0)
    mean: float | None
    standardDeviation: float | None
    minimum: float | None
    q1: float | None
    median: float | None
    q3: float | None
    maximum: float | None


class MeasurementReportResponse(_StrictResponse):
    constructId: str = Field(pattern=r"^construct_[a-z0-9_-]{1,50}$")
    outputVariableId: str = Field(pattern=r"^scale_[a-z0-9_-]{1,50}$")
    completeCaseCount: int = Field(ge=0)
    alpha: float | None
    omega: float | None
    spearmanBrown: float | None = None
    reliabilityMethod: str | None = None
    itemAnalysis: list[MeasurementItemAnalysisResponse] = Field(min_length=2)
    scoreDistribution: MeasurementDistributionResponse


class MeasurementScoreVariableResponse(_StrictResponse):
    id: str = Field(pattern=r"^scale_[a-z0-9_-]{1,50}$")
    label: str = Field(min_length=1)
    type: Literal["scale_score"]


class MeasurementDerivedDatasetResponse(_StrictResponse):
    id: str = Field(pattern=r"^derived_[a-f0-9]{16}$")
    sourceDatasetVersionId: str = Field(pattern=r"^dataset_[a-f0-9]{16}$")
    measurementVersion: int = Field(ge=1)
    storage: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rowCount: int = Field(ge=1)
    columnCount: int = Field(ge=1)
    scoreVariables: list[MeasurementScoreVariableResponse] = Field(min_length=1)


class MeasurementTransformationLogResponse(_StrictResponse):
    constructId: str = Field(pattern=r"^construct_[a-z0-9_-]{1,50}$")
    message: str = Field(min_length=1)


class MeasurementVersionResponse(_StrictResponse):
    schemaVersion: Literal["1.0.0"]
    id: str = Field(pattern=r"^measurement_[a-f0-9]{16}$")
    datasetVersionId: str = Field(pattern=r"^dataset_[a-f0-9]{16}$")
    version: int = Field(ge=1)
    createdAt: str
    changeNote: str | None = Field(max_length=500)
    status: Literal["ready_for_model_canvas"]
    constructs: list[MeasurementConstructResponse] = Field(min_length=1)
    reports: list[MeasurementReportResponse] = Field(min_length=1)
    derivedDataset: MeasurementDerivedDatasetResponse
    transformationPreview: list[dict[str, object]]
    transformationLog: list[MeasurementTransformationLogResponse] = Field(min_length=1)
    warnings: list[WarningResponse]


class DemoProjectResponse(BaseModel):
    dataset: DatasetVersionResponse
    measurement: MeasurementVersionResponse
    modelSpec: dict[str, object]


class ModelValidationResponse(ExtensibleResponse):
    valid: bool
    structuralStatus: Literal["valid", "invalid"]
    errors: list[str]
    warnings: list[WarningResponse]
    template: str | None
    catalogVersion: str
    matchStatus: Literal["exact", "custom", "sem", "invalid"]
    processModelNumber: int | None
    displayName: str
    executionAvailable: bool
    unsupportedReason: str | None
    sampleFlow: dict[str, object] | None = None


class ModelVersionResponse(ExtensibleResponse):
    schemaVersion: str
    id: str
    status: Literal["draft", "frozen"]
    datasetId: str
    modelId: str
    validation: ModelValidationResponse
    modelSpec: dict[str, object]


class ResultRunResponse(_StrictResponse):
    id: str = Field(min_length=1)
    status: Literal["succeeded"]
    modelId: str = Field(min_length=1)
    modelHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    modelVersionId: str = Field(min_length=1)
    template: str
    durationMilliseconds: int = Field(ge=0)


class ResultSampleFlowResponse(_StrictResponse):
    original: int = Field(ge=0)
    included: int = Field(ge=0)
    excluded: int = Field(ge=0)
    missingMethod: str = Field(min_length=1)
    selected: int | None = Field(default=None, ge=0)
    missingRows: int | None = Field(default=None, ge=0)
    finalN: int | None = Field(default=None, ge=0)
    variableMissingCounts: dict[str, int] | None = None
    missingPatterns: list[dict[str, object]] | None = None


class ResultConfidenceIntervalResponse(_StrictResponse):
    level: float = Field(gt=0.5, lt=1)
    lower: float
    upper: float
    method: str = Field(min_length=1)
    replicates: int | None = Field(default=None, ge=1)
    seed: int | None = Field(default=None, ge=1)


class ResultEffectResponse(_StrictResponse):
    id: str = Field(min_length=1)
    type: Literal[
        "path", "direct", "indirect", "total", "interaction", "conditional", "index", "contrast"
    ]
    label: str = Field(min_length=1)
    estimate: float
    edgeId: str | None = None
    edgeIds: list[str] | None = None
    hypothesisIds: list[str] | None = None
    hypothesisId: str | None = None
    estimand: str | None = None
    standardError: float | None = Field(default=None, ge=0)
    confidenceInterval: ResultConfidenceIntervalResponse | None = None


class ResultProvenanceResponse(_StrictResponse):
    engine: Literal["researchpath-r"]
    engineVersion: str = Field(min_length=1)
    rVersion: str = Field(min_length=1)
    jsonliteVersion: str = Field(min_length=1)
    dataSha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    standardErrors: Literal["classical", "hc3", "standard", "robust", "bootstrap"]
    bootstrapReplicates: int = Field(ge=0)
    # 仅在 bootstrap 实际执行时为正整数种子；否则为 null（与
    # result-bundle.schema.json 同步允许 oneOf [integer>=1, null]。
    seed: int | None = Field(default=None, ge=1)
    contextHash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    sampleVersionId: str | None = None
    sampleHash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    structureVersionId: str | None = None
    structureHash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    measurementVersionId: str | None = None
    measurementHash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    datasetSha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    confidenceLevel: float | None = Field(default=None, gt=0.5, lt=1)
    hc3FallbackApplied: bool | None = None
    estimator: str | None = None
    missingMethodExecuted: str | None = None
    studyPlanBinding: StudyPlanBindingResponse | None = None
    processReference: dict[str, object] | None = None
    executionMode: Literal["rscript", "resident_pool"] | None = None
    parallelBackend: Literal["sequential", "future_multisession"] | None = None
    parallelWorkers: int | None = Field(default=None, ge=1)
    rngStrategy: str | None = None
    nonFiniteValues: list[dict[str, object]] | None = None


class ResultBundleResponse(_StrictResponse):
    schemaVersion: str
    run: ResultRunResponse
    jobStatus: Literal["queued", "running", "completed", "failed", "cancelled"]
    estimationStatus: Literal["not_run", "succeeded", "failed", "non_converged", "boundary_solution"]
    inferenceStatus: Literal["not_available", "reliable", "needs_review", "not_reliable"]
    publicationEligibility: Literal["ineligible", "conditional", "eligible"]
    sampleFlow: ResultSampleFlowResponse
    equations: list[dict[str, object]]
    diagnostics: list[dict[str, object]]
    effects: list[ResultEffectResponse]
    probes: list[dict[str, object]]
    johnsonNeyman: dict[str, object] | None
    moderator: dict[str, object] | None
    warnings: list[WarningResponse]
    provenance: ResultProvenanceResponse
    publicationEligible: bool | None = None
    requiresManualReview: bool | None = None
    publicationEligibilityReasons: list[str] | None = None
    claimBoundary: dict[str, object] | None = None
    bootstrap: dict[str, object] | None = None
    moderationPlots: list[dict[str, object]] | None = None
    johnsonNeymanResults: list[dict[str, object]] | None = None
    semResult: dict[str, object] | None = None
    invarianceResult: dict[str, object] | None = None
    academicInterpretation: str | None = None
    apaTables: str | None = None
    reportFacts: list[dict[str, object]] | None = None
    reportingProfileAssessments: list[dict[str, object]] | None = None
    replay: dict[str, object] | None = None
    publicationGate: dict[str, object] | None = None
    studyPlanBinding: StudyPlanBindingResponse | None = None
    evidenceGraph: dict[str, object] | None = None


class AnalysisJobResponse(ExtensibleResponse):
    id: str
    jobKind: Literal["model", "empirical"] = "model"
    datasetId: str
    modelId: str
    modelVersion: int
    modelVersionId: str
    status: Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]
    stage: str
    progress: float
    completedReplicates: int
    totalReplicates: int
    cancelRequested: bool
    createdAt: str
    updatedAt: str
    error: str | None
    result: ResultBundleResponse | None = None
    resultPath: str | None = None


class AdvancedJobResponse(ExtensibleResponse):
    id: str
    analysisId: str
    family: str
    specHash: str
    datasetVersionId: str | None = None
    status: Literal["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]
    stage: str
    progress: float
    cancelRequested: bool
    createdAt: str
    updatedAt: str
    error: str | None = None
    errorCode: str | None = None
    errorDetails: str | None = None
    remediation: str | None = None
    result: AdvancedResultResponse | None = None
    resultPath: str | None = None


class EmpiricalSegmentResponse(ExtensibleResponse):
    reliability: dict[str, object] | None = None
    resultAvailability: dict[str, str] | None = None
    sample: dict[str, object] | None = None
    sampleFlow: dict[str, object] | None = None
    publicationEligible: bool | None = None
    requiresManualReview: bool | None = None
    publicationEligibilityReasons: list[str] | None = None
    missingDataReport: dict[str, object] | None = None
    descriptives: list[dict[str, object]] | None = None
    frequencies: list[dict[str, object]] | None = None
    correlations: dict[str, object] | None = None
    paperSummaryTable: dict[str, object] | None = None
    efa: dict[str, object] | None = None
    cfa: dict[str, object] | None = None
    validity: dict[str, object] | None = None
    measurementInvariance: dict[str, object] | None = None
    groupComparison: dict[str, object] | None = None
    aggregationDiagnostics: dict[str, object] | None = None
    hierarchicalRegression: dict[str, object] | None = None
    responseSurface: dict[str, object] | None = None
    multiplicity: dict[str, object] | None = None
    longitudinalPanel: dict[str, object] | None = None
    diaryMultilevel: dict[str, object] | None = None


class EmpiricalReportResponse(ExtensibleResponse):
    reliability: dict[str, object] | None = None
    schemaVersion: str
    reportId: str
    datasetId: str
    measurementVersionId: str | None
    createdAt: str
    jobStatus: Literal["queued", "running", "completed", "failed", "cancelled"]
    estimationStatus: Literal["not_run", "succeeded", "failed", "non_converged", "boundary_solution"]
    inferenceStatus: Literal["not_available", "reliable", "needs_review", "not_reliable"]
    publicationEligibility: Literal["ineligible", "conditional", "eligible"]
    sample: dict[str, object]
    missingDataReport: dict[str, object] | None = None
    options: dict[str, object]
    descriptives: list[dict[str, object]]
    frequencies: list[dict[str, object]]
    correlations: dict[str, object]
    paperSummaryTable: dict[str, object] | None = None
    efa: dict[str, object]
    cfa: dict[str, object]
    validity: dict[str, object]
    measurementInvariance: dict[str, object] | None = None
    groupComparison: dict[str, object] | None = None
    aggregationDiagnostics: dict[str, object] | None = None
    hierarchicalRegression: dict[str, object] | None = None
    responseSurface: dict[str, object] | None = None
    warnings: list[WarningResponse]
    provenance: dict[str, object]
    studyPlanBinding: StudyPlanBindingResponse | None = None
    evidenceGraph: dict[str, object] | None = None
    reportFacts: list[dict[str, object]] | None = None
    reportingProfileAssessments: list[dict[str, object]] | None = None
    replay: dict[str, object] | None = None
    publicationGate: dict[str, object] | None = None


class CleanupResponse(BaseModel):
    deleted: int


class CapabilityValidationEvidenceResponse(BaseModel):
    contractTests: bool
    applicabilityTests: bool
    failureFixtures: bool
    externalOracle: str | None = None
    oracleIndependence: str | None = None
    numericGoldenId: str | None = None


class AdvancedCapabilitySliceResponse(BaseModel):
    id: str
    label: str
    status: Literal["planned", "experimental", "supported"]
    executionAvailable: bool
    validationLevel: Literal["unvalidated", "internally_validated", "externally_validated"]
    maturityLevel: Literal["experimental", "validated", "reviewer_ready", "publication_ready"]
    publicationEligibility: Literal["ineligible", "conditional", "eligible"]
    publicationEligibilityReason: str
    validationEvidence: CapabilityValidationEvidenceResponse
    supportBoundary: str


class AdvancedCapabilityResponse(BaseModel):
    family: str
    label: str
    status: str
    specVersion: str
    resultVersion: str
    plannedEngine: str
    minimumValidation: list[str]
    executionAvailable: bool
    validationLevel: Literal["unvalidated", "internally_validated", "externally_validated"]
    maturityLevel: Literal["experimental", "validated", "reviewer_ready", "publication_ready"]
    publicationEligibility: Literal["ineligible", "conditional", "eligible"]
    publicationEligibilityReason: str
    validationEvidence: CapabilityValidationEvidenceResponse
    slices: list[AdvancedCapabilitySliceResponse]


class AdvancedCapabilitiesResponse(BaseModel):
    schemaVersion: str
    capabilities: list[AdvancedCapabilityResponse]


class AdvancedValidationResponse(ExtensibleResponse):
    valid: bool
    family: str
    capabilityId: str
    sliceId: str | None = None
    sliceStatus: str
    implementationStatus: str
    executionAvailable: bool
    validationLevel: Literal["unvalidated", "internally_validated", "externally_validated"]
    maturityLevel: Literal["experimental", "validated", "reviewer_ready", "publication_ready"]
    publicationEligibility: Literal["ineligible", "conditional", "eligible"]
    publicationEligibilityReason: str
    validationEvidence: CapabilityValidationEvidenceResponse
    spec: dict[str, object]
    warnings: list[WarningResponse]


class AdvancedPlotResponse(BaseModel):
    id: str
    title: str
    format: Literal["svg"]
    data: str


class ReportFactResponse(BaseModel):
    factId: str
    kind: Literal["estimate", "fit", "diagnostic", "warning", "sample_flow"]
    sourceResultId: str
    sourcePaths: list[str]
    semanticRole: str
    presentationHints: dict[str, object] = {}
    templates: dict[str, str] = {}


class AdvancedResultResponse(ExtensibleResponse):
    schemaVersion: str
    run: dict[str, object]
    apaReports: list[str] = []
    plots: list[AdvancedPlotResponse] = []
    reportFacts: list[ReportFactResponse] | None = None
    reportingProfileAssessments: list[dict[str, object]] | None = None
    replay: dict[str, object] | None = None
    publicationGate: dict[str, object] | None = None


class DatasetMergeReport(BaseModel):
    matchedCount: int
    primaryOnlyCount: int
    targetOnlyCount: int
    primaryDuplicates: int
    targetDuplicates: int
    mergedRowCount: int = 0
    oneToManyConflictCount: int = 0
    manyToManyConflictCount: int = 0
    duplicateKeyDetails: list[dict[str, object]] = []
    joinKeys: list[str] = []
    joinType: str = "outer"
    warnings: list[str]


class DatasetMergeResponse(BaseModel):
    dataset: DatasetVersionResponse
    report: DatasetMergeReport
