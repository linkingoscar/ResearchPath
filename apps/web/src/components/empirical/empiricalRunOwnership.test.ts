import { describe, expect, it } from 'vitest'

import type { EmpiricalRunEntry } from './empiricalRunHistory'
import { filterEmpiricalRunHistoryForAnalysis } from './empiricalRunOwnership'

const runs: EmpiricalRunEntry[] = [
  { id: 'run_recovered_desc', procedure: 'descriptives', createdAt: '2026-09-03T10:00:00Z' },
  { id: 'run_explicit_a', procedure: 'descriptives', analysisId: 'analysis_a', createdAt: '2026-09-03T11:00:00Z' },
  { id: 'run_explicit_b', procedure: 'descriptives', analysisId: 'analysis_b', createdAt: '2026-09-03T12:00:00Z' },
  { id: 'run_corr', procedure: 'correlation', createdAt: '2026-09-03T13:00:00Z' },
]

describe('filterEmpiricalRunHistoryForAnalysis', () => {
  it('uses recovery-index ownership for unscoped runs without broadcasting them to every duplicate', () => {
    expect(filterEmpiricalRunHistoryForAnalysis(
      runs,
      'descriptives',
      'analysis_a',
      new Set(['run_recovered_desc', 'run_explicit_a']),
    ).map((run) => run.id)).toEqual([
      'run_recovered_desc',
      'run_explicit_a',
    ])

    expect(filterEmpiricalRunHistoryForAnalysis(
      runs,
      'descriptives',
      'analysis_b',
      new Set(['run_explicit_b']),
    ).map((run) => run.id)).toEqual(['run_explicit_b'])
  })

  it('always respects explicit analysisId ownership over compatibility fallback', () => {
    expect(filterEmpiricalRunHistoryForAnalysis(
      runs,
      'descriptives',
      'analysis_a',
      new Set(['run_explicit_b']),
    ).map((run) => run.id)).toEqual(['run_explicit_a'])
  })

  it('keeps the procedure-level view unchanged when no AnalysisDocument is active', () => {
    expect(filterEmpiricalRunHistoryForAnalysis(runs, 'descriptives').map((run) => run.id)).toEqual([
      'run_recovered_desc',
      'run_explicit_a',
      'run_explicit_b',
    ])
  })
})
