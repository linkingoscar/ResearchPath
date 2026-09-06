import type { DatasetVersion, MeasurementVersion } from '../../types'
import type { ResolvedAnalysisContext } from '../../types/analysis-context'
import type { EmpiricalProcedure } from '../../types/empirical-types'
import type { EmpiricalConfigValue } from './empiricalConfigTypes'
import { empiricalProcedures } from './empiricalProcedures'

export interface EmpiricalDraft {
  config: EmpiricalConfigValue
  activeRunId: string | null
  lastRunConfig: EmpiricalConfigValue | null
  tabRequestKey?: number
  serverRevision?: number
}

const ANALYSIS_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/

export function empiricalDraftStoragePrefix(dataset: DatasetVersion, measurement: MeasurementVersion | null): string {
  return `researchpath.empirical.draft.v1:${dataset.id}:${dataset.originalFile?.sha256 ?? ''}:${dataset.dictionary?.version ?? 0}:${(measurement?.version ?? null)}:${measurement?.derivedDataset.sha256 ?? ''}:`
}

export function empiricalDraftKey(
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  context?: ResolvedAnalysisContext | null,
  analysisId?: string | null,
): string {
  const base = `${empiricalDraftStoragePrefix(dataset, measurement)}${context?.contextHash ?? 'pending'}`
  if (!analysisId) return base
  if (!ANALYSIS_ID_PATTERN.test(analysisId)) throw new Error('Invalid analysis id')
  return `${base}:analysis:${analysisId}`
}

function validConfig(value: unknown): value is EmpiricalConfigValue {
  if (!value || typeof value !== 'object') return false
  const config = value as Record<string, unknown>
  return empiricalProcedures.some(p => p.id === config.procedure)
    && ['analysisVariableIds', 'constructIds', 'predictorVariableIds', 'controlVariableIds', 'responseSurfacePredictorIds'].every(key =>
      Array.isArray(config[key]) && config[key].length <= 10000 && config[key].every((id: unknown) => typeof id === 'string'))
    && ['correlationPAdjust', 'groupOmnibusPAdjust', 'multiplicityPAdjust'].every(key => ['BH', 'holm', 'none'].includes(String(config[key])))
    && typeof config.factorCount === 'number' && typeof config.confidenceLevel === 'number'
}

export function readEmpiricalDraft(key: string, procedure?: EmpiricalProcedure): EmpiricalDraft | null {
  try {
    const selected = procedure ?? localStorage.getItem(`${key}:selected`)
    if (!empiricalProcedures.some(p => p.id === selected)) return null
    const raw = localStorage.getItem(`${key}:${selected}`)
    if (!raw || raw.length > 500000) return null
    const value = JSON.parse(raw) as EmpiricalDraft
    if (!validConfig(value.config) || value.config.procedure !== selected
      || (value.lastRunConfig !== null && !validConfig(value.lastRunConfig))
      || (value.activeRunId !== null && (typeof value.activeRunId !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(value.activeRunId)))) return null
    return value
  } catch { return null }
}

export function saveEmpiricalDraft(key: string, draft: EmpiricalDraft): boolean {
  try {
    localStorage.setItem(`${key}:${draft.config.procedure}`, JSON.stringify(draft))
    localStorage.setItem(`${key}:selected`, draft.config.procedure)
    return true
  } catch { return false }
}

export function isEmpiricalDraft(value: unknown): value is EmpiricalDraft {
  if (!value || typeof value !== 'object') return false
  const draft = value as Partial<EmpiricalDraft>
  return validConfig(draft.config)
    && (draft.lastRunConfig === null || validConfig(draft.lastRunConfig))
    && (draft.activeRunId === null || typeof draft.activeRunId === 'string')
    && (draft.serverRevision === undefined || Number.isSafeInteger(draft.serverRevision))
}

export function migrateEmpiricalDraftToAnalysis(
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  context: ResolvedAnalysisContext | null | undefined,
  analysisId: string,
  procedure: EmpiricalProcedure,
): EmpiricalDraft | null {
  const scopedKey = empiricalDraftKey(dataset, measurement, context, analysisId)
  const scopedDraft = readEmpiricalDraft(scopedKey, procedure)
  if (scopedDraft) return scopedDraft

  const recoveryKey = empiricalDraftKey(dataset, measurement, context)
  const recoveredDraft = readEmpiricalDraft(recoveryKey, procedure)
  if (!recoveredDraft) return null

  saveEmpiricalDraft(scopedKey, recoveredDraft)
  return recoveredDraft
}

export function cloneEmpiricalDraftToAnalysis(
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  context: ResolvedAnalysisContext | null | undefined,
  sourceAnalysisId: string,
  targetAnalysisId: string,
  procedure: EmpiricalProcedure,
): EmpiricalDraft | null {
  if (!ANALYSIS_ID_PATTERN.test(sourceAnalysisId) || !ANALYSIS_ID_PATTERN.test(targetAnalysisId)) return null
  if (sourceAnalysisId === targetAnalysisId) return null

  const source = readEmpiricalDraft(empiricalDraftKey(dataset, measurement, context, sourceAnalysisId), procedure)
  if (!source) return null
  const cloned: EmpiricalDraft = {
    config: source.config,
    activeRunId: null,
    lastRunConfig: null,
  }
  return saveEmpiricalDraft(empiricalDraftKey(dataset, measurement, context, targetAnalysisId), cloned) ? cloned : null
}

export function cloneEmpiricalDraftsToAnalysis(
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  sourceAnalysisId: string,
  targetAnalysisId: string,
  procedure: EmpiricalProcedure,
): number {
  if (!ANALYSIS_ID_PATTERN.test(sourceAnalysisId) || !ANALYSIS_ID_PATTERN.test(targetAnalysisId)) return 0
  if (sourceAnalysisId === targetAnalysisId) return 0

  const prefix = empiricalDraftStoragePrefix(dataset, measurement)
  const sourceMarker = `:analysis:${sourceAnalysisId}:`
  const targetMarker = `:analysis:${targetAnalysisId}:`
  const suffix = `:${procedure}`
  const sourceDraftKeys: string[] = []

  for (let index = 0; index < localStorage.length; index += 1) {
    const storageKey = localStorage.key(index)
    if (!storageKey?.startsWith(prefix) || !storageKey.endsWith(suffix) || !storageKey.includes(sourceMarker)) continue
    sourceDraftKeys.push(storageKey.slice(0, -suffix.length))
  }

  let clonedCount = 0
  sourceDraftKeys.forEach((sourceKey) => {
    const source = readEmpiricalDraft(sourceKey, procedure)
    if (!source) return
    const targetKey = sourceKey.replace(sourceMarker.slice(0, -1), targetMarker.slice(0, -1))
    if (readEmpiricalDraft(targetKey, procedure)) return
    const cloned: EmpiricalDraft = {
      config: source.config,
      activeRunId: null,
      lastRunConfig: null,
    }
    if (saveEmpiricalDraft(targetKey, cloned)) clonedCount += 1
  })

  return clonedCount
}
