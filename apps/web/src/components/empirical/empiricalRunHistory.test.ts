import { beforeEach, describe, expect, it } from 'vitest'

import { readEmpiricalHistory, saveEmpiricalHistory } from './empiricalRunHistory'

const key = 'researchpath.empirical.runs.v1:dataset_demo:null'

beforeEach(() => localStorage.clear())

describe('empiricalRunHistory method identity compatibility', () => {
  it('persists an optional method id for method-scoped recovery', () => {
    saveEmpiricalHistory(key, [{
      id: 'run_ri_clpm',
      procedure: 'longitudinal',
      analysisId: 'analysis_ri_clpm',
      methodId: 'longitudinal.ri-clpm',
      createdAt: '2026-09-03T12:00:00Z',
    }])

    expect(readEmpiricalHistory(key)).toEqual([
      expect.objectContaining({
        id: 'run_ri_clpm',
        analysisId: 'analysis_ri_clpm',
        methodId: 'longitudinal.ri-clpm',
      }),
    ])
  })

  it('keeps stored history entries without methodId readable', () => {
    localStorage.setItem(key, JSON.stringify([
      {
        id: 'run_recovered',
        procedure: 'descriptives',
        createdAt: '2026-09-03T10:00:00Z',
      },
    ]))

    expect(readEmpiricalHistory(key)).toEqual([
      expect.objectContaining({ id: 'run_recovered', procedure: 'descriptives' }),
    ])
    expect(readEmpiricalHistory(key)[0].methodId).toBeUndefined()
  })

  it('drops malformed optional recovery metadata without dropping the run itself', () => {
    localStorage.setItem(key, JSON.stringify([
      {
        id: 'run_recoverable',
        procedure: 'longitudinal',
        analysisId: '../bad-analysis',
        methodId: '../longitudinal.ri-clpm',
        createdAt: '2026-09-03T10:00:00Z',
      },
    ]))

    expect(readEmpiricalHistory(key)).toEqual([
      {
        id: 'run_recoverable',
        procedure: 'longitudinal',
        createdAt: '2026-09-03T10:00:00Z',
      },
    ])
  })
})
