import type { StatisticalMethodExecution } from './datasets'

// Machine-readable disclosure of any numerical fallback that changes
// the meaning of an EFA estimator (inversion, communality init, rotation,
// extraction, correlation world).
export interface EfaNumericalFallback {
  stage: string
  requested: string
  used: string
  reason: string
}

// Parallel analysis metadata. The correlationType/simulationType pair
// proves the null distribution lived in the same statistical world as the
// main EFA (ordinal data never silently degrades to Pearson).
export interface EfaParallelAnalysis {
  available: boolean
  reason?: string
  sampleEigenvalues?: number[]
  simulatedEigenvalues?: number[]
  recommendedFactorCount?: number | null
  iterations?: number
  quantile?: number
  seed?: number
  correlationType?: 'pearson' | 'polychoric'
  simulationType?: 'continuous_pearson' | 'ordinal_threshold_preserving'
}

// Split-sample validation reuses the user's estimator pipeline, or
// reports unavailable instead of silently switching estimators.
export interface EfaSplitValidation {
  available: boolean
  reason?: string
  method?: string
  correlationType?: 'pearson' | 'polychoric' | null
  extractionMethod?: string | null
  rotation?: string
  requestedCorrelationType?: 'pearson' | 'polychoric' | null
  executedCorrelationType?: 'pearson' | 'polychoric' | null
  requestedExtractionMethod?: string | null
  executedExtractionMethod?: string | null
  requestedRotation?: string | null
  executedRotation?: string | null
  executionFingerprints?: Record<string, {
    correlationType: string
    extractionMethod: string
    rotation: string
    factorCount: number
  } | null>
  trainSampleCount?: number
  validationSampleCount?: number
  tuckerCongruence?: number | null
  numericalFallbacks?: EfaNumericalFallback[]
}

export interface EfaDiagnostics {
  items: Array<{
    itemId: string
    communality: number | null
    primaryFactor: number
    crossLoading: boolean
    complexity: number | null
  }>
  numericalFallbacks: EfaNumericalFallback[]
}

export interface EfaResult {
  available: boolean
  reason?: string | null
  factorCount: number
  factorLabels: string[]
  method: string
  rotation: string
  correlationType?: 'pearson' | 'polychoric'
  requestedCorrelationType?: 'pearson' | 'polychoric'
  executedCorrelationType?: 'pearson' | 'polychoric'
  requestedExtractionMethod?: string
  executedExtractionMethod?: string
  requestedRotation?: string
  executedRotation?: string
  methodExecution?: StatisticalMethodExecution
  eigenvalues: number[]
  loadings: Array<{
    itemId: string
    label: string
    loadings: number[]
    communality: number | null
  }>
  factorCorrelations?: number[][] | null
  structureMatrix?: number[][] | null
  diagnostics?: EfaDiagnostics
  parallelAnalysis?: EfaParallelAnalysis | null
  splitValidation?: EfaSplitValidation | null
}
