import { describe, expect, it } from 'vitest'
import type { DatasetVersion } from '../types'
import { buildWorkspaceSteps } from './workspaceStateSelectors'
import { normalizeStoredWorkspaceView } from './workspaceStateStorage'

describe('workspace navigation reorganization', () => {
  it('normalizes stored analysis views to the unified analysis workspace', () => {
    expect(normalizeStoredWorkspaceView('empirical')).toBe('analyze')
    expect(normalizeStoredWorkspaceView('model')).toBe('analyze')
    expect(normalizeStoredWorkspaceView('methods')).toBe('analyze')
    expect(normalizeStoredWorkspaceView('advanced')).toBe('analyze')
    expect(normalizeStoredWorkspaceView('output')).toBe('output')
  })

  it('always exposes only data, analysis and output as primary workspaces', () => {
    const steps = buildWorkspaceSteps({ activeDataset: { id: 'dataset_1' } as DatasetVersion, analysisReady: false })
    expect(steps.map((step) => step.view)).toEqual(['data', 'analyze', 'output'])
    expect(steps.find((step) => step.view === 'analyze')?.badge).toBe('按方法检查')
  })
})
