import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { DatasetVersion } from '../../types'
import {
  analysisDocumentFreshness,
  analysisDocumentsForDataset,
  analysisDocumentsForProject,
  analysisRunFreshness,
  analysisRunsForDocument,
  ensureEmpiricalAnalysisDocument,
  loadEmpiricalAnalysisIndex,
  setAnalysisPrimaryRun,
  updateAnalysisDocumentMetadata,
} from './analysisDocuments'

const dataset: DatasetVersion = {
  schemaVersion: '1.0.0',
  id: 'dataset_demo',
  projectId: 'project_demo',
  createdAt: '2026-09-03T00:00:00Z',
  originalFile: {
    name: 'survey.csv',
    format: 'csv',
    sizeBytes: 128,
    sha256: 'a'.repeat(64),
  },
  storage: { raw: 'raw', normalized: 'normalized' },
  rowCount: 10,
  columnCount: 1,
  variables: [],
  preview: [],
  warnings: [],
  dictionary: {
    version: 1,
    confirmedCount: 0,
    totalCount: 0,
    status: 'draft',
  },
}

const nextDataset: DatasetVersion = {
  ...dataset,
  id: 'dataset_next',
  createdAt: '2026-09-03T06:00:00Z',
  originalFile: {
    ...dataset.originalFile,
    name: 'survey-v2.csv',
    sha256: 'b'.repeat(64),
  },
}

const recoveryKey = 'researchpath.empirical.runs.v1:dataset_demo:null'
const nextRecoveryKey = 'researchpath.empirical.runs.v1:dataset_next:null'

beforeEach(() => {
  localStorage.clear()
  vi.useRealTimers()
})

describe('analysis document recovery index', () => {
  it('groups repeated recovered procedure runs under one stable analysis document', () => {
    localStorage.setItem(recoveryKey, JSON.stringify([
      { id: 'run_desc_2', procedure: 'descriptives', createdAt: '2026-09-03T02:00:00Z' },
      { id: 'run_corr_1', procedure: 'correlation', createdAt: '2026-09-03T01:30:00Z' },
      { id: 'run_desc_1', procedure: 'descriptives', createdAt: '2026-09-03T01:00:00Z' },
    ]))

    const index = loadEmpiricalAnalysisIndex(dataset, null)
    const documents = analysisDocumentsForDataset(index, dataset, null)

    expect(documents).toHaveLength(2)
    expect(index.runs).toHaveLength(3)

    const descriptives = documents.find((document) => document.procedure === 'descriptives')
    expect(descriptives).toMatchObject({
      title: '描述统计',
      methodId: 'empirical.overview.descriptives',
      latestRunId: 'run_desc_2',
      datasetVersionId: dataset.id,
      measurementVersionId: null,
    })
    expect(analysisRunsForDocument(index, descriptives?.id ?? '').map((run) => run.id)).toEqual([
      'run_desc_2',
      'run_desc_1',
    ])
  })

  it('creates the stable analysis document when a method is opened before its first run', () => {
    const document = ensureEmpiricalAnalysisDocument(dataset, null, 'descriptives')
    const index = loadEmpiricalAnalysisIndex(dataset, null)

    expect(index.documents).toContainEqual(document)
    expect(document).toMatchObject({ procedure: 'descriptives' })
    expect(document.latestRunId).toBeUndefined()
    expect(index.runs).toHaveLength(0)
  })

  it('uses an explicit analysis id from new run history instead of grouping only by procedure', () => {
    localStorage.setItem(recoveryKey, JSON.stringify([
      { id: 'run_a', procedure: 'descriptives', analysisId: 'analysis_a', createdAt: '2026-09-03T02:00:00Z' },
      { id: 'run_b', procedure: 'descriptives', analysisId: 'analysis_b', createdAt: '2026-09-03T01:00:00Z' },
    ]))

    const index = loadEmpiricalAnalysisIndex(dataset, null)
    expect(index.documents.filter((document) => document.procedure === 'descriptives').map((document) => document.id).sort()).toEqual([
      'analysis_a',
      'analysis_b',
    ])
    expect(index.runs.find((run) => run.id === 'run_a')?.analysisId).toBe('analysis_a')
    expect(index.runs.find((run) => run.id === 'run_b')?.analysisId).toBe('analysis_b')
  })

  it('is idempotent and keeps the recovery index intact', () => {
    localStorage.setItem(recoveryKey, JSON.stringify([
      { id: 'run_freq_1', procedure: 'frequencies', createdAt: '2026-09-03T01:00:00Z' },
    ]))

    const first = loadEmpiricalAnalysisIndex(dataset, null)
    const second = loadEmpiricalAnalysisIndex(dataset, null)

    expect(first.documents).toHaveLength(1)
    expect(second.documents).toHaveLength(1)
    expect(second.runs).toHaveLength(1)
    expect(second.runs[0]).toMatchObject({
      id: 'run_freq_1',
      submittedSpec: null,
      runStatus: 'recovered_indexed',
      draftRevision: 0,
    })
    expect(localStorage.getItem(recoveryKey)).toContain('run_freq_1')
  })

  it('persists user-facing analysis metadata without changing run ownership', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-03T05:00:00Z'))
    localStorage.setItem(recoveryKey, JSON.stringify([
      { id: 'run_desc_1', procedure: 'descriptives', createdAt: '2026-09-03T01:00:00Z' },
      { id: 'run_corr_1', procedure: 'correlation', createdAt: '2026-09-03T02:00:00Z' },
    ]))

    const initial = loadEmpiricalAnalysisIndex(dataset, null)
    const descriptives = initial.documents.find((document) => document.procedure === 'descriptives')
    expect(descriptives).toBeDefined()

    const updated = updateAnalysisDocumentMetadata(dataset.projectId, descriptives?.id ?? '', {
      title: '核心变量描述',
      pinned: true,
    })
    const reloaded = loadEmpiricalAnalysisIndex(dataset, null)
    const updatedDocument = reloaded.documents.find((document) => document.id === descriptives?.id)

    expect(updatedDocument).toMatchObject({
      title: '核心变量描述',
      pinned: true,
      latestRunId: 'run_desc_1',
      updatedAt: '2026-09-03T05:00:00.000Z',
    })
    expect(analysisRunsForDocument(updated, descriptives?.id ?? '').map((run) => run.id)).toEqual(['run_desc_1'])
    expect(analysisDocumentsForDataset(reloaded, dataset, null)[0]?.id).toBe(descriptives?.id)
  })

  it('keeps the newest run identity even when analysis metadata was edited later', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-03T05:00:00Z'))
    localStorage.setItem(recoveryKey, JSON.stringify([
      { id: 'run_desc_1', procedure: 'descriptives', createdAt: '2026-09-03T01:00:00Z' },
    ]))
    const initial = loadEmpiricalAnalysisIndex(dataset, null)
    const descriptives = initial.documents[0]
    updateAnalysisDocumentMetadata(dataset.projectId, descriptives.id, { title: '描述统计 A' })

    localStorage.setItem(recoveryKey, JSON.stringify([
      { id: 'run_desc_2', procedure: 'descriptives', createdAt: '2026-09-03T04:00:00Z' },
      { id: 'run_desc_1', procedure: 'descriptives', createdAt: '2026-09-03T01:00:00Z' },
    ]))
    const reloaded = loadEmpiricalAnalysisIndex(dataset, null)

    expect(reloaded.documents[0]).toMatchObject({
      title: '描述统计 A',
      latestRunId: 'run_desc_2',
      updatedAt: '2026-09-03T05:00:00.000Z',
    })
  })

  it('keeps non-current dataset analyses discoverable and marks their runs stale', () => {
    localStorage.setItem(recoveryKey, JSON.stringify([
      { id: 'run_old', procedure: 'correlation', createdAt: '2026-09-03T01:00:00Z' },
    ]))
    const oldIndex = loadEmpiricalAnalysisIndex(dataset, null)
    expect(oldIndex.documents).toHaveLength(1)

    localStorage.setItem(nextRecoveryKey, JSON.stringify([
      { id: 'run_current', procedure: 'descriptives', createdAt: '2026-09-03T07:00:00Z' },
    ]))
    const index = loadEmpiricalAnalysisIndex(nextDataset, null)
    const projectDocuments = analysisDocumentsForProject(index, dataset.projectId)
    const oldDocument = projectDocuments.find((document) => document.datasetVersionId === dataset.id)
    const currentDocument = projectDocuments.find((document) => document.datasetVersionId === nextDataset.id)
    const oldRun = index.runs.find((run) => run.id === 'run_old')
    const currentRun = index.runs.find((run) => run.id === 'run_current')

    expect(projectDocuments).toHaveLength(2)
    expect(analysisDocumentsForDataset(index, nextDataset, null)).toHaveLength(1)
    expect(oldDocument && analysisDocumentFreshness(oldDocument, nextDataset, null)).toBe('stale')
    expect(currentDocument && analysisDocumentFreshness(currentDocument, nextDataset, null)).toBe('current')
    expect(oldRun && analysisRunFreshness(oldRun, nextDataset, null)).toBe('stale')
    expect(currentRun && analysisRunFreshness(currentRun, nextDataset, null)).toBe('current')
  })

  it('sets and clears a primary run only within its owning analysis', () => {
    localStorage.setItem(recoveryKey, JSON.stringify([
      { id: 'run_desc_2', procedure: 'descriptives', createdAt: '2026-09-03T02:00:00Z' },
      { id: 'run_desc_1', procedure: 'descriptives', createdAt: '2026-09-03T01:00:00Z' },
      { id: 'run_corr_1', procedure: 'correlation', createdAt: '2026-09-03T01:30:00Z' },
    ]))
    const initial = loadEmpiricalAnalysisIndex(dataset, null)
    const descriptives = initial.documents.find((document) => document.procedure === 'descriptives')
    const correlation = initial.documents.find((document) => document.procedure === 'correlation')

    const selected = setAnalysisPrimaryRun(dataset.projectId, descriptives?.id ?? '', 'run_desc_1')
    expect(selected.documents.find((document) => document.id === descriptives?.id)?.primaryRunId).toBe('run_desc_1')

    const rejected = setAnalysisPrimaryRun(dataset.projectId, descriptives?.id ?? '', 'run_corr_1')
    expect(rejected.documents.find((document) => document.id === descriptives?.id)?.primaryRunId).toBe('run_desc_1')
    expect(rejected.documents.find((document) => document.id === correlation?.id)?.primaryRunId).toBeUndefined()

    const cleared = setAnalysisPrimaryRun(dataset.projectId, descriptives?.id ?? '', null)
    expect(cleared.documents.find((document) => document.id === descriptives?.id)?.primaryRunId).toBeUndefined()
  })
})
