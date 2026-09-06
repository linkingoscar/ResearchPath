import type {
  ConfidenceInterval,
  Effect,
  InvarianceResult,
  JohnsonNeymanResult,
  SemResult,
} from './result-types'
import type { StudyPlanEvidenceGraph, StudyPlanResultBinding } from './workflows'

export interface ReportFact {
  factId: string
  kind: 'estimate' | 'fit' | 'diagnostic' | 'warning' | 'sample_flow'
  sourceResultId: string
  sourcePaths: string[]
  semanticRole: string
  presentationHints?: Record<string, unknown>
  templates?: Record<string, string>
}

export interface ReportingProfileAssessment {
  profileId: 'apa_jars_quant' | 'strobe_observational' | 'consort_2025_randomized' | 'aea_data_code'
  profileVersion: string
  label: string
  scopeNote: string
  purpose: 'disclosure_completeness_only'
  applicable: boolean
  satisfiedCount: number
  totalCount: number
  completeness: number | null
  items: Array<{ id: string; label: string; satisfied: boolean; evidencePaths: string[] }>
  qualityCertified: false
  causalCertified: false
  publicationEligibilityGranted: false
}

export interface ReplayDescriptor {
  schemaVersion: '1.0.0'
  packageFormat: 'ResearchPath Replay Package'
  packageVersion: '1.0.0'
  available: boolean
  command: string | null
  verificationCommand: string | null
  hashAlgorithm: 'sha256'
  packageGenerated: boolean
  cleanRoomVerified: boolean
  dataIncluded: boolean | null
  licenses: { code: string; data: string }
  limitations: string[]
}

export interface PublicationGateLayer {
  status: 'passed' | 'conditional' | 'failed'
  checks: Array<{ id: string; passed: boolean; evidence: string }>
  reasons: string[]
}

export interface PublicationGate {
  schemaVersion: '1.0.0'
  capabilityLayer: PublicationGateLayer & {
    sliceIds: string[]
    validationLevels: Record<string, 'unvalidated' | 'internally_validated' | 'externally_validated'>
  }
  runEvidenceLayer: PublicationGateLayer
  reportingLayer: PublicationGateLayer
  humanConfirmation: { confirmed: boolean; confirmedBy: string | null; confirmedAt: string | null }
  finalStatus: 'ineligible' | 'requires_human_confirmation' | 'eligible'
  finalEligible: boolean
  reasons: string[]
}

export interface ResultBundle {
  schemaVersion: string
  studyPlanBinding?: StudyPlanResultBinding
  jobStatus: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  estimationStatus: 'not_run' | 'succeeded' | 'failed' | 'non_converged' | 'boundary_solution'
  inferenceStatus: 'not_available' | 'reliable' | 'needs_review' | 'not_reliable'
  publicationEligibility: 'ineligible' | 'conditional' | 'eligible'
  reportFacts?: ReportFact[]
  reportingProfileAssessments?: ReportingProfileAssessment[]
  replay?: ReplayDescriptor
  publicationGate?: PublicationGate
  run: {
    id: string
    status: 'succeeded'
    modelId: string
    modelHash: string
    modelVersionId?: string
    template?: `model_${1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 28 | 29 | 58 | 59 | 60 | 61 | 62 | 63 | 64 | 65 | 66 | 67 | 68 | 69 | 70 | 71 | 72 | 73 | 75 | 76 | 80 | 81 | 82 | 83 | 84 | 85 | 86 | 87 | 88 | 89 | 90 | 91 | 92}` | 'sem'
    durationMilliseconds?: number
  }
  sampleFlow: {
    original: number
    included: number
    excluded: number
    missingMethod: string
    variableMissingCounts?: Record<string, number>
    missingPatterns?: Array<{ pattern: string; count: number }>
  }
  equations: Array<{
    id: string
    outcomeRole: 'm' | 'y'
    formula: string
    rSquared: number
    adjustedRSquared: number
    nagelkerkeRSquared?: number | null
    rSquaredType?: 'r_squared' | 'mcfadden_pseudo_r_squared'
    modelFamily?: 'linear' | 'binomial_logit'
    coefficients?: Array<{
      equationId: string
      term: string
      estimate: number
      standardError: number
      statistic: number
      pValue: number
      confidenceInterval: ConfidenceInterval
      oddsRatio?: number
      oddsRatioConfidenceInterval?: ConfidenceInterval
      averageMarginalEffect?: number | null
      marginalEffectType?: 'discrete' | 'categorical_contrast' | 'continuous_derivative' | 'not_applicable_interaction_term'
      marginalEffectEstimand?: string
      marginalEffectReason?: string
      marginalEffectReferenceLevel?: string
      marginalEffectContrastLevel?: string
      marginalEffectStandardError?: number
      marginalEffectConfidenceInterval?: ConfidenceInterval
    }>
  }>
  effects: Effect[]
  diagnostics?: Array<{
    equationId: string
    residualStandardError: number
    maximumLeverage: number
    maximumCooksDistance: number
    heteroskedasticity: {
      method: string
      statistic: number
      degreesOfFreedom: number
      pValue: number
    }
  }>
  probes?: Array<{
    moderationId?: string
    targetEdgeId?: string
    predictorLabel?: string
    moderatorLabel?: string
    secondaryModeratorLabel?: string
    label: string
    moderatorValue: number
    secondaryModeratorValue?: number
    effect: number
    standardError: number
    statistic: number
    pValue: number
    confidenceInterval: ConfidenceInterval
  }>
  moderationPlots?: Array<{
    id: string
    targetEdgeId: string
    equationId: string
    predictorId: string
    predictorLabel: string
    outcomeId: string
    outcomeLabel: string
    moderatorId: string
    moderatorLabel: string
    outcomeScale: 'outcome' | 'probability'
    lines: Array<{
      label: string
      moderatorValue: number
      xValues: [number, number]
      predictedValues: [number, number]
      confidenceLower?: [number, number]
      confidenceUpper?: [number, number]
    }>
  }>
  johnsonNeyman?: JohnsonNeymanResult | null
  johnsonNeymanResults?: Array<{
    moderationId: string
    targetEdgeId: string
    predictorId: string
    predictorLabel: string
    moderatorId: string
    moderatorLabel: string
    result: JohnsonNeymanResult
  }>
  moderator?: {
    id: string
    mean: number
    standardDeviation: number
    minimum: number
    maximum: number
  } | null
  semResult?: SemResult | null
  publicationEligible?: boolean
  requiresManualReview?: boolean
  publicationEligibilityReasons?: string[]
  claimBoundary?: {
    claimMode: 'association' | 'temporal_precedence' | 'experimental_effect'
    causalLanguageAllowed: boolean
    temporalPrecedenceEstablished: boolean
    experimentalEffectEstablished: boolean
  }
  bootstrap?: {
    familyId: string
    method: string
    replicatesRequested: number
    replicatesValid: number
    invalidReplications: number
    invalidRate: number
    seed: number
    confidenceLevel: number
    failureAction: string
  }
  evidenceGraph?: StudyPlanEvidenceGraph
  invarianceResult?: InvarianceResult | null
  academicInterpretation?: string
  apaTables?: string
  warnings: Array<{
    code: string
    severity: 'info' | 'warning' | 'error'
    message: string
  }>
  provenance: {
    engine: string
    engineVersion: string
    rVersion: string
    jsonliteVersion: string
    dataSha256: string
    standardErrors?: 'classical' | 'hc3' | 'standard' | 'robust' | 'bootstrap'
    confidenceLevel?: number
    hc3FallbackApplied?: boolean
    estimator?: string
    missingMethodExecuted?: string
    bootstrapReplicates?: number
    /** 仅在 bootstrap 实际执行时有值；否则为 null */
    seed?: number | null
    studyPlanBinding?: StudyPlanResultBinding
  }
}
