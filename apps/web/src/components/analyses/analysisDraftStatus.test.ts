import { beforeEach, describe, expect, it } from 'vitest'

import type { DatasetVersion } from '../../types'
import { empiricalDraftKey, saveEmpiricalDraft } from '../empirical/empiricalDrafts'
import { empiricalDraftStatusForOutput } from './analysisDraftStatus'

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

const baseConfig = {
  procedure: 'descriptives',
  analysisVariableIds: ['score'],
  constructIds: [],
  predictorVariableIds: [],
  controlVariableIds: [],
  responseSurfacePredictorIds: [],
  correlationPAdjust: 'BH',
  groupOmnibusPAdjust: 'holm',
  multiplicityPAdjust: 'BH',
  factorCount: 1,
  confidenceLevel: 0.95,
}

beforeEach(() => {
  localStorage.clear()
})

describe('empiricalDraftStatusForOutput', () => {
  it('finds the context-specific recovered draft only when it belongs to the latest run', () => {
    const contextHash = 'c'.repeat(64)
    const key = `researchpath.empirical.draft.v1:${dataset.id}:${dataset.originalFile.sha256}:1:null::${contextHash}:descriptives`
    localStorage.setItem(key, JSON.stringify({
      config: { ...baseConfig, analysisVariableIds: ['score', 'age'] },
      activeRunId: 'run_desc_2',
      lastRunConfig: baseConfig,
    }))

    expect(empiricalDraftStatusForOutput(dataset, null, 'descriptives', 'run_desc_2')).toEqual({
      activeRunId: 'run_desc_2',
      dirtySinceLastRun: true,
      hasSavedDraft: true,
    })
    expect(empiricalDraftStatusForOutput(dataset, null, 'descriptives', 'another_run')).toEqual({
      activeRunId: null,
      dirtySinceLastRun: false,
      hasSavedDraft: false,
    })
  })

  it('prefers the requested analysis-scoped draft over another analysis using the same procedure', () => {
    const firstKey = empiricalDraftKey(dataset, null, undefined, 'analysis_a')
    const secondKey = empiricalDraftKey(dataset, null, undefined, 'analysis_b')
    saveEmpiricalDraft(firstKey, {
      config: { ...baseConfig, analysisVariableIds: ['score', 'age'] } as never,
      activeRunId: 'run_a',
      lastRunConfig: baseConfig as never,
    })
    saveEmpiricalDraft(secondKey, {
      config: { ...baseConfig, analysisVariableIds: ['other'] } as never,
      activeRunId: 'run_b',
      lastRunConfig: baseConfig as never,
    })

    expect(empiricalDraftStatusForOutput(dataset, null, 'descriptives', 'run_a', 'analysis_a')).toEqual({
      activeRunId: 'run_a',
      dirtySinceLastRun: true,
      hasSavedDraft: true,
    })
    expect(empiricalDraftStatusForOutput(dataset, null, 'descriptives', 'run_a', 'analysis_b')).toEqual({
      activeRunId: null,
      dirtySinceLastRun: false,
      hasSavedDraft: false,
    })
  })
})
