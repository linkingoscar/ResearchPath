import { patchServerAnalysisDocument, upsertServerAnalysisDocument } from '../../api/analysis-index'
import type { DatasetVersion, MeasurementVersion } from '../../types'
import type { EmpiricalProcedure } from '../../types/empirical-types'
import { methodDefinitions } from '../../methods/methodDefinitions'
import { expandMethodForLibrary } from '../../methods/methodLibraryPresets'
import { empiricalProcedures } from '../empirical/empiricalProcedures'
import { readEmpiricalHistory } from '../empirical/empiricalRunHistory'

export type AnalysisFreshness = 'current' | 'stale'

export interface AnalysisDocumentIndexEntry {
  id: string
  projectId: string
  title: string
  methodId: string
  categoryId: string
  createdAt: string
  updatedAt: string
  pinned: boolean
  currentDraftId: string
  latestRunId?: string
  primaryRunId?: string
  archived?: boolean
  source: 'empirical'
  datasetVersionId: string
  measurementVersionId: string | null
  procedure: EmpiricalProcedure
}

export interface AnalysisRunIndexEntry {
  id: string
  analysisId: string
  draftRevision: number
  submittedSpec: null
  datasetVersionId: string
  measurementVersionId: string | null
  runStatus: 'recovered_indexed'
  freshness: AnalysisFreshness
  resultId?: string
  warningCodes: string[]
  createdAt: string
}

export interface AnalysisDocumentIndex {
  schemaVersion: '1.0.0'
  migrationVersion: 1
  documents: AnalysisDocumentIndexEntry[]
  runs: AnalysisRunIndexEntry[]
}

export interface AnalysisDocumentMetadataPatch {
  title?: string
  pinned?: boolean
}

const INDEX_PREFIX = 'researchpath.analysis.index.v1'
const MAX_DOCUMENTS = 500
const MAX_RUNS = 3000
const ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/
const expandedMethods = methodDefinitions.flatMap(expandMethodForLibrary)

function emptyIndex(): AnalysisDocumentIndex {
  return { schemaVersion: '1.0.0', migrationVersion: 1, documents: [], runs: [] }
}

function stableHash(value: string): string {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

function indexKey(projectId: string): string {
  return `${INDEX_PREFIX}:${projectId}`
}

function measurementIdentity(measurement: MeasurementVersion | null): string {
  return measurement?.id ?? 'raw'
}

function analysisIdentity(
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  procedure: EmpiricalProcedure,
  methodId: string,
): string {
  return `${dataset.projectId}:${dataset.id}:${measurementIdentity(measurement)}:${procedure}:${methodId}`
}

function defaultAnalysisId(
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  procedure: EmpiricalProcedure,
  methodId: string,
): string {
  return `analysis_${stableHash(analysisIdentity(dataset, measurement, procedure, methodId))}`
}

function methodIdentity(procedure: EmpiricalProcedure, requestedMethodId?: string) {
  if (requestedMethodId) {
    const requested = expandedMethods.find((method) => method.libraryId === requestedMethodId || method.id === requestedMethodId)
    if (requested) return { methodId: requested.libraryId, title: requested.label, categoryId: requested.categoryId }
    const registered = methodDefinitions.find((method) => method.id === requestedMethodId)
    if (registered) return { methodId: registered.id, title: registered.label, categoryId: registered.categoryId }
  }

  const expanded = expandedMethods.find((method) => method.procedure === procedure)
  if (expanded) return { methodId: expanded.libraryId, title: expanded.label, categoryId: expanded.categoryId }

  const procedureDefinition = empiricalProcedures.find((definition) => definition.id === procedure)
  const exact = procedureDefinition
    ? methodDefinitions.find((method) => method.capabilitySliceIds.includes(procedureDefinition.slice))
    : undefined
  if (exact) return { methodId: exact.id, title: exact.label, categoryId: exact.categoryId }

  return {
    methodId: `empirical.${procedure}`,
    title: procedureDefinition?.label ?? procedure,
    categoryId: procedure === 'longitudinal' ? 'longitudinal' : procedure === 'diary' ? 'diary' : 'descriptives-relations',
  }
}

function mirrorDocument(document: AnalysisDocumentIndexEntry): void {
  void upsertServerAnalysisDocument({
    id: document.id,
    projectId: document.projectId,
    title: document.title,
    methodId: document.methodId,
    categoryId: document.categoryId,
    source: 'empirical',
    datasetVersionId: document.datasetVersionId,
    measurementVersionId: document.measurementVersionId,
    procedure: document.procedure,
    createdAt: document.createdAt,
    updatedAt: document.updatedAt,
    currentDraftId: document.currentDraftId,
    latestRunId: document.latestRunId,
    primaryRunId: document.primaryRunId,
    pinned: document.pinned,
    archived: document.archived,
  }).catch(() => {
    // Local compatibility cache remains usable; Output later retries via the server index.
  })
}

function isStoredIndex(value: unknown): value is AnalysisDocumentIndex {
  if (!value || typeof value !== 'object') return false
  const index = value as Partial<AnalysisDocumentIndex>
  return index.schemaVersion === '1.0.0'
    && index.migrationVersion === 1
    && Array.isArray(index.documents)
    && Array.isArray(index.runs)
    && index.documents.length <= MAX_DOCUMENTS
    && index.runs.length <= MAX_RUNS
}

function readIndex(projectId: string): AnalysisDocumentIndex {
  try {
    const raw = localStorage.getItem(indexKey(projectId))
    if (!raw || raw.length > 2_000_000) return emptyIndex()
    const value: unknown = JSON.parse(raw)
    return isStoredIndex(value) ? value : emptyIndex()
  } catch {
    return emptyIndex()
  }
}

function saveIndex(projectId: string, index: AnalysisDocumentIndex) {
  try {
    localStorage.setItem(indexKey(projectId), JSON.stringify({
      ...index,
      documents: index.documents.slice(0, MAX_DOCUMENTS),
      runs: index.runs.slice(0, MAX_RUNS),
    }))
  } catch {
    // Server AnalysisIndex and existing job history remain the recovery source.
  }
}

function runHistoryKey(dataset: DatasetVersion, measurement: MeasurementVersion | null): string {
  return `researchpath.empirical.runs.v1:${dataset.id}:${measurement?.version ?? null}`
}

function documentBaseMatches(
  document: AnalysisDocumentIndexEntry,
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  procedure: EmpiricalProcedure,
) {
  return document.projectId === dataset.projectId
    && document.datasetVersionId === dataset.id
    && document.measurementVersionId === (measurement?.id ?? null)
    && document.procedure === procedure
}

function documentMatches(
  document: AnalysisDocumentIndexEntry,
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  procedure: EmpiricalProcedure,
  methodId?: string,
) {
  return documentBaseMatches(document, dataset, measurement, procedure)
    && (!methodId || document.methodId === methodId)
}

function ensureDocument(
  index: AnalysisDocumentIndex,
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  procedure: EmpiricalProcedure,
  createdAt: string,
  requestedId?: string,
  requestedMethodId?: string,
): AnalysisDocumentIndexEntry {
  const method = methodIdentity(procedure, requestedMethodId)

  if (!requestedId) {
    const compatible = index.documents.find((document) =>
      documentMatches(document, dataset, measurement, procedure, method.methodId))
    if (compatible) return compatible
  }

  const fallbackId = defaultAnalysisId(dataset, measurement, procedure, method.methodId)
  let id = requestedId && ID_PATTERN.test(requestedId) ? requestedId : fallbackId
  const requested = index.documents.find((document) => document.id === id)
  if (requested && documentMatches(requested, dataset, measurement, procedure, requestedMethodId ? method.methodId : undefined)) return requested

  if (requested && id !== fallbackId) id = fallbackId
  const existing = index.documents.find((document) => document.id === id)
  if (existing && documentMatches(existing, dataset, measurement, procedure, method.methodId)) return existing

  const document: AnalysisDocumentIndexEntry = {
    id,
    projectId: dataset.projectId,
    title: method.title,
    methodId: method.methodId,
    categoryId: method.categoryId,
    createdAt,
    updatedAt: createdAt,
    pinned: false,
    currentDraftId: `draft_${stableHash(`${id}:current`)}`,
    source: 'empirical',
    datasetVersionId: dataset.id,
    measurementVersionId: measurement?.id ?? null,
    procedure,
  }
  index.documents.unshift(document)
  return document
}

function uniqueAnalysisId(index: AnalysisDocumentIndex): string {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const token = `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 12)}_${attempt}`
    const id = `analysis_${token}`
    if (ID_PATTERN.test(id) && !index.documents.some((document) => document.id === id)) return id
  }
  return `analysis_${Date.now().toString(36)}_${stableHash(String(Math.random()))}`
}

export function ensureEmpiricalAnalysisDocument(
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  procedure: EmpiricalProcedure,
  requestedMethodId?: string,
): AnalysisDocumentIndexEntry {
  const index = readIndex(dataset.projectId)
  const method = methodIdentity(procedure, requestedMethodId)
  const existingByMethod = index.documents.find((document) =>
    documentMatches(document, dataset, measurement, procedure, method.methodId))
  if (existingByMethod) {
    mirrorDocument(existingByMethod)
    return existingByMethod
  }

  const document = ensureDocument(
    index,
    dataset,
    measurement,
    procedure,
    new Date().toISOString(),
    undefined,
    method.methodId,
  )
  saveIndex(dataset.projectId, index)
  mirrorDocument(document)
  return document
}

export function createEmpiricalAnalysisDocument(
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
  procedure: EmpiricalProcedure,
  title?: string,
  requestedMethodId?: string,
): AnalysisDocumentIndexEntry {
  const index = readIndex(dataset.projectId)
  const now = new Date().toISOString()
  const document = ensureDocument(
    index,
    dataset,
    measurement,
    procedure,
    now,
    uniqueAnalysisId(index),
    requestedMethodId,
  )
  const requestedTitle = title?.trim()
  if (requestedTitle) document.title = requestedTitle
  saveIndex(dataset.projectId, index)
  mirrorDocument(document)
  return document
}

export function loadEmpiricalAnalysisIndex(
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
): AnalysisDocumentIndex {
  const index = readIndex(dataset.projectId)
  const history = readEmpiricalHistory(runHistoryKey(dataset, measurement))
  let changed = false

  history.forEach((entry) => {
    const beforeDocuments = index.documents.length
    const document = ensureDocument(
      index,
      dataset,
      measurement,
      entry.procedure,
      entry.createdAt,
      entry.analysisId,
      entry.methodId,
    )
    if (index.documents.length !== beforeDocuments) changed = true

    let runReference = index.runs.find((run) => run.id === entry.id)
    if (!runReference) {
      runReference = {
        id: entry.id,
        analysisId: document.id,
        draftRevision: 0,
        submittedSpec: null,
        datasetVersionId: dataset.id,
        measurementVersionId: measurement?.id ?? null,
        runStatus: 'recovered_indexed',
        freshness: 'current',
        warningCodes: [],
        createdAt: entry.createdAt,
      }
      index.runs.unshift(runReference)
      changed = true
    } else if (entry.analysisId && runReference.analysisId !== document.id) {
      runReference.analysisId = document.id
      changed = true
    }
  })

  index.documents
    .filter((document) => documentBaseMatches(document, dataset, measurement, document.procedure))
    .forEach((document) => {
      const runs = index.runs
        .filter((run) => run.analysisId === document.id)
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      const latestRunId = runs[0]?.id
      if (document.latestRunId !== latestRunId) {
        document.latestRunId = latestRunId
        changed = true
      }
      if (document.primaryRunId && !runs.some((run) => run.id === document.primaryRunId)) {
        document.primaryRunId = undefined
        changed = true
      }
      if (runs[0] && runs[0].createdAt > document.updatedAt) {
        document.updatedAt = runs[0].createdAt
        changed = true
      }
    })

  if (changed) saveIndex(dataset.projectId, index)
  return index
}

export function updateAnalysisDocumentMetadata(
  projectId: string,
  analysisId: string,
  patch: AnalysisDocumentMetadataPatch,
): AnalysisDocumentIndex {
  const index = readIndex(projectId)
  const document = index.documents.find((entry) => entry.id === analysisId)
  if (!document) return index

  let changed = false
  if (patch.title !== undefined) {
    const title = patch.title.trim()
    if (title && title !== document.title) {
      document.title = title
      changed = true
    }
  }
  if (patch.pinned !== undefined && patch.pinned !== document.pinned) {
    document.pinned = patch.pinned
    changed = true
  }

  if (changed) {
    document.updatedAt = new Date().toISOString()
    saveIndex(projectId, index)
    void patchServerAnalysisDocument(projectId, analysisId, patch).catch(() => {
      mirrorDocument(document)
    })
  }
  return index
}

export function setAnalysisPrimaryRun(
  projectId: string,
  analysisId: string,
  runId: string | null,
): AnalysisDocumentIndex {
  const index = readIndex(projectId)
  const document = index.documents.find((entry) => entry.id === analysisId)
  if (!document) return index
  if (runId && !index.runs.some((run) => run.id === runId && run.analysisId === analysisId)) return index

  const nextPrimaryRunId = runId ?? undefined
  if (document.primaryRunId === nextPrimaryRunId) return index
  document.primaryRunId = nextPrimaryRunId
  document.updatedAt = new Date().toISOString()
  saveIndex(projectId, index)
  void patchServerAnalysisDocument(projectId, analysisId, { primaryRunId: runId }).catch(() => {
    mirrorDocument(document)
  })
  return index
}

export function analysisRunFreshness(
  run: AnalysisRunIndexEntry,
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
): AnalysisFreshness {
  return run.datasetVersionId === dataset.id
    && run.measurementVersionId === (measurement?.id ?? null)
    ? 'current'
    : 'stale'
}

export function analysisDocumentFreshness(
  document: AnalysisDocumentIndexEntry,
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
): AnalysisFreshness {
  return document.datasetVersionId === dataset.id
    && document.measurementVersionId === (measurement?.id ?? null)
    ? 'current'
    : 'stale'
}

export function analysisDocumentsForProject(
  index: AnalysisDocumentIndex,
  projectId: string,
): AnalysisDocumentIndexEntry[] {
  return index.documents
    .filter((document) => !document.archived && document.projectId === projectId)
    .sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.updatedAt.localeCompare(a.updatedAt))
}

export function analysisDocumentsForDataset(
  index: AnalysisDocumentIndex,
  dataset: DatasetVersion,
  measurement: MeasurementVersion | null,
): AnalysisDocumentIndexEntry[] {
  const measurementVersionId = measurement?.id ?? null
  return analysisDocumentsForProject(index, dataset.projectId)
    .filter((document) => document.datasetVersionId === dataset.id
      && document.measurementVersionId === measurementVersionId)
}

export function analysisRunsForDocument(
  index: AnalysisDocumentIndex,
  analysisId: string,
): AnalysisRunIndexEntry[] {
  return index.runs
    .filter((run) => run.analysisId === analysisId)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
}
