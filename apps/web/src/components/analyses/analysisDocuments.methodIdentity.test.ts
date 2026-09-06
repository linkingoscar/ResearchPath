import { beforeEach, describe, expect, it } from 'vitest'

import type { DatasetVersion } from '../../types'
import {
  createEmpiricalAnalysisDocument,
  ensureEmpiricalAnalysisDocument,
  loadEmpiricalAnalysisIndex,
} from './analysisDocuments'

const dataset = {
  schemaVersion: '1.0.0',
  id: 'dataset_method_identity',
  projectId: 'project_method_identity',
  createdAt: '2026-09-03T00:00:00Z',
  originalFile: { name: 'panel.csv', format: 'csv', sizeBytes: 10, sha256: 'a'.repeat(64) },
  storage: { raw: 'raw', normalized: 'normalized' },
  rowCount: 20,
  columnCount: 2,
  variables: [],
  preview: [],
  warnings: [],
  dictionary: { version: 1, confirmedCount: 0, totalCount: 0, status: 'draft' },
} as DatasetVersion

const recoveryKey = 'researchpath.empirical.runs.v1:dataset_method_identity:null'

beforeEach(() => localStorage.clear())

describe('method-scoped empirical AnalysisDocuments', () => {
  it('creates distinct stable documents for longitudinal methods sharing one procedure', () => {
    const clpm = ensureEmpiricalAnalysisDocument(dataset, null, 'longitudinal', 'longitudinal.clpm')
    const riClpm = ensureEmpiricalAnalysisDocument(dataset, null, 'longitudinal', 'longitudinal.ri-clpm')
    const lcmSr = ensureEmpiricalAnalysisDocument(dataset, null, 'longitudinal', 'longitudinal.lcm-sr')

    expect(new Set([clpm.id, riClpm.id, lcmSr.id]).size).toBe(3)
    expect(clpm).toMatchObject({ methodId: 'longitudinal.clpm', title: '传统 CLPM' })
    expect(riClpm.methodId).toBe('longitudinal.ri-clpm')
    expect(lcmSr.methodId).toBe('longitudinal.lcm-sr')
    expect(ensureEmpiricalAnalysisDocument(dataset, null, 'longitudinal', 'longitudinal.clpm').id).toBe(clpm.id)
  })

  it('separates diary LMM, GLMM and DSEM under the shared diary procedure', () => {
    const lmm = ensureEmpiricalAnalysisDocument(dataset, null, 'diary', 'diary.lmm')
    const glmm = ensureEmpiricalAnalysisDocument(dataset, null, 'diary', 'diary.glmm')
    const dsem = ensureEmpiricalAnalysisDocument(dataset, null, 'diary', 'diary.dsem')

    expect(new Set([lmm.id, glmm.id, dsem.id]).size).toBe(3)
    expect([lmm.methodId, glmm.methodId, dsem.methodId]).toEqual(['diary.lmm', 'diary.glmm', 'diary.dsem'])
  })

  it('reuses a recovered empirical document when its stored method identity already matches', () => {
    localStorage.setItem(recoveryKey, JSON.stringify([
      { id: 'run_desc_1', procedure: 'descriptives', createdAt: '2026-09-03T01:00:00Z' },
    ]))
    const recovered = loadEmpiricalAnalysisIndex(dataset, null).documents[0]
    const reopened = ensureEmpiricalAnalysisDocument(dataset, null, 'descriptives', 'empirical.overview.descriptives')

    expect(recovered.methodId).toBe('empirical.overview.descriptives')
    expect(reopened.id).toBe(recovered.id)
    expect(loadEmpiricalAnalysisIndex(dataset, null).documents.filter((document) => document.procedure === 'descriptives')).toHaveLength(1)
  })

  it('duplicates within the same method identity without inheriting run identity', () => {
    const source = ensureEmpiricalAnalysisDocument(dataset, null, 'longitudinal', 'longitudinal.clpm')
    const duplicate = createEmpiricalAnalysisDocument(dataset, null, 'longitudinal', 'CLPM 副本', source.methodId)

    expect(duplicate.id).not.toBe(source.id)
    expect(duplicate.methodId).toBe(source.methodId)
    expect(duplicate.title).toBe('CLPM 副本')
    expect(duplicate.latestRunId).toBeUndefined()
    expect(duplicate.primaryRunId).toBeUndefined()
  })
})
