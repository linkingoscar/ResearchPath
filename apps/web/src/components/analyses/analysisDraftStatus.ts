import type { DatasetVersion, MeasurementVersion } from '../../types'
import type { EmpiricalProcedure } from '../../types/empirical-types'
import {
  empiricalDraftKey,
  empiricalDraftStoragePrefix,
  readEmpiricalDraft,
  type EmpiricalDraft,
} from '../empirical/empiricalDrafts'

export interface OutputDraftStatus {
  activeRunId: string | null
  dirtySinceLastRun: boolean
  hasSavedDraft: boolean
}

function toStatus(draft: EmpiricalDraft | null): OutputDraftStatus {
  if (!draft) return { activeRunId: null, dirtySinceLastRun: false, hasSavedDraft: false }
  return {
    activeRunId: draft.activeRunId,
    dirtySinceLastRun: Boolean(
      draft.lastRunConfig && JSON.stringify(draft.config) !== JSON.stringify(draft.lastRunConfig),
    ),
    hasSavedDraft: true,
  }
}

function collectDraftCandidates(
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  procedure: EmpiricalProcedure,
  analysisId?: string,
): EmpiricalDraft[] {
  const prefix = empiricalDraftStoragePrefix(dataset, measurement)
  const suffix = analysisId ? `:analysis:${analysisId}:${procedure}` : `:${procedure}`
  const candidates: EmpiricalDraft[] = []

  for (let index = 0; index < localStorage.length; index += 1) {
    const storageKey = localStorage.key(index)
    if (!storageKey?.startsWith(prefix) || !storageKey.endsWith(suffix)) continue
    if (!analysisId && storageKey.includes(':analysis:')) continue
    const draftKey = storageKey.slice(0, -(`:${procedure}`.length))
    const draft = readEmpiricalDraft(draftKey, procedure)
    if (draft) candidates.push(draft)
  }
  return candidates
}

function selectDraft(candidates: EmpiricalDraft[], latestRunId?: string): OutputDraftStatus | null {
  if (latestRunId) {
    const matching = candidates.find((draft) => draft.activeRunId === latestRunId)
    return matching ? toStatus(matching) : null
  }
  return candidates.length === 1 ? toStatus(candidates[0]) : null
}

export function empiricalDraftStatusForOutput(
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  procedure: EmpiricalProcedure,
  latestRunId?: string,
  analysisId?: string,
): OutputDraftStatus {
  if (analysisId) {
    const pendingKey = empiricalDraftKey(dataset, measurement, undefined, analysisId)
    const pendingDraft = readEmpiricalDraft(pendingKey, procedure)
    if (pendingDraft && (!latestRunId || pendingDraft.activeRunId === latestRunId)) return toStatus(pendingDraft)

    const scoped = selectDraft(collectDraftCandidates(dataset, measurement, procedure, analysisId), latestRunId)
    if (scoped) return scoped
  }

  const recoveryKey = empiricalDraftKey(dataset, measurement)
  const recoveredDraft = readEmpiricalDraft(recoveryKey, procedure)
  if (recoveredDraft && (!latestRunId || recoveredDraft.activeRunId === latestRunId)) return toStatus(recoveredDraft)

  return selectDraft(collectDraftCandidates(dataset, measurement, procedure), latestRunId) ?? toStatus(null)
}
