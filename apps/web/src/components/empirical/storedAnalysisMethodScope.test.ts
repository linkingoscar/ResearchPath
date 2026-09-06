import { describe, expect, it } from 'vitest'

import { storedAnalysisMethodSlice } from './storedAnalysisMethodScope'

describe('storedAnalysisMethodSlice', () => {
  it('restores a longitudinal analysis to its concrete capability slice', () => {
    expect(storedAnalysisMethodSlice('longitudinal.ri-clpm')).toBe('empirical.panel.ri_clpm')
    expect(storedAnalysisMethodSlice('longitudinal.lcm-sr')).toBe('empirical.panel.lcm_sr')
  })

  it('restores a diary analysis to its concrete capability slice', () => {
    expect(storedAnalysisMethodSlice('diary.glmm')).toBe('empirical.diary.glmm')
    expect(storedAnalysisMethodSlice('diary.dsem')).toBe('empirical.diary.dsem')
  })

  it('does not invent method scope for unscoped or expanded empirical ids', () => {
    expect(storedAnalysisMethodSlice('empirical.longitudinal')).toBeUndefined()
    expect(storedAnalysisMethodSlice('empirical.overview.descriptives')).toBeUndefined()
    expect(storedAnalysisMethodSlice(undefined)).toBeUndefined()
  })
})
