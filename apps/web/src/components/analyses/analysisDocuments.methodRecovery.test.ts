import { beforeEach, describe, expect, it } from 'vitest'

import type { DatasetVersion } from '../../types'
import { loadEmpiricalAnalysisIndex } from './analysisDocuments'

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

const historyKey = 'researchpath.empirical.runs.v1:dataset_demo:null'

beforeEach(() => localStorage.clear())

describe('analysis document recovery from empirical run history', () => {
  it('rebuilds a method-scoped longitudinal document when the analysis index is missing', () => {
    localStorage.setItem(historyKey, JSON.stringify([
      {
        id: 'run_ri_clpm',
        procedure: 'longitudinal',
        analysisId: 'analysis_ri_clpm',
        methodId: 'longitudinal.ri-clpm',
        createdAt: '2026-09-03T12:00:00Z',
      },
    ]))

    const index = loadEmpiricalAnalysisIndex(dataset, null)
    const document = index.documents.find((entry) => entry.id === 'analysis_ri_clpm')

    expect(document).toMatchObject({
      id: 'analysis_ri_clpm',
      procedure: 'longitudinal',
      methodId: 'longitudinal.ri-clpm',
      title: 'RI-CLPM',
      latestRunId: 'run_ri_clpm',
    })
    expect(index.runs.find((run) => run.id === 'run_ri_clpm')?.analysisId).toBe('analysis_ri_clpm')
  })

  it('keeps procedure-only history recoverable without inventing a concrete method', () => {
    localStorage.setItem(historyKey, JSON.stringify([
      {
        id: 'run_recovered_longitudinal',
        procedure: 'longitudinal',
        analysisId: 'analysis_recovered_longitudinal',
        createdAt: '2026-09-03T10:00:00Z',
      },
    ]))

    const index = loadEmpiricalAnalysisIndex(dataset, null)
    const document = index.documents.find((entry) => entry.id === 'analysis_recovered_longitudinal')

    expect(document).toMatchObject({
      id: 'analysis_recovered_longitudinal',
      procedure: 'longitudinal',
      methodId: 'empirical.longitudinal',
    })
  })
})
