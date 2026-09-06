import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { EmpiricalAnalysisSegmentMap } from '../../types'
import { EmpiricalRegressionTab } from './EmpiricalRegressionTab'
import type { SegmentQueryState } from './segmentQuery'

type RegressionData = EmpiricalAnalysisSegmentMap['regression']

const readyQuery = (data: RegressionData): SegmentQueryState<RegressionData> => ({
  data,
  isLoading: false,
  isError: false,
  error: null,
})

const regressionData = (confidenceLevel: number, pValue: number, pValueRaw: number): RegressionData => ({
  groupComparison: null,
  aggregationDiagnostics: null,
  responseSurface: null,
  multiplicity: {
    adjustment: 'BH',
    familyId: 'inferred',
    scope: ['test'],
    globalAdjustmentApplied: false,
    components: ['regression'],
  },
  hierarchicalRegression: {
    outcomeVariableId: 'y',
    outcomeLabel: 'Y',
    n: 120,
    primaryAnalysis: {
      method: 'ordinary OLS',
      role: 'primary',
      confidenceLevel,
      selectionRule: 'pre-declared',
    },
    blocks: [
      {
        block: 2,
        formula: 'y ~ x',
        rSquared: 0.2,
        adjustedRSquared: 0.19,
        coefficients: [
          {
            term: 'x',
            label: 'X',
            estimate: 0.4,
            standardError: 0.2,
            statistic: 2,
            pValue,
            lower: 0.01,
            upper: 0.8,
            vif: null,
            pValueRaw,
            pValueAdjusted: pValue,
          },
        ],
      },
    ],
    change: { deltaRSquared: 0.2, statistic: 4, df1: 1, df2: 118, pValue: 0.05 },
  },
})

describe('EmpiricalRegressionTab multiplicity and confidence display', () => {
  it('uses the adjusted p value for stars, not the raw p', () => {
    render(
      <EmpiricalRegressionTab
        activeTab="regression"
        query={readyQuery(regressionData(0.95, 0.06, 0.01))}
      />,
    )
    expect(screen.getByText('X')).toBeInTheDocument()
    expect(screen.queryByTitle('p < 0.05')).not.toBeInTheDocument()
  })

  it('shows a star only when the displayed adjusted p crosses the threshold', () => {
    render(
      <EmpiricalRegressionTab
        activeTab="regression"
        query={readyQuery(regressionData(0.95, 0.03, 0.09))}
      />,
    )
    expect(screen.getByTitle('p < 0.05')).toBeInTheDocument()
  })

  it('labels confidence intervals with the result confidence level', () => {
    const first = render(
      <EmpiricalRegressionTab
        activeTab="regression"
        query={readyQuery(regressionData(0.9, 0.03, 0.03))}
      />,
    )
    expect(first.getByText(/90%/i)).toBeInTheDocument()
    first.unmount()

    const second = render(
      <EmpiricalRegressionTab
        activeTab="regression"
        query={readyQuery(regressionData(0.99, 0.03, 0.03))}
      />,
    )
    expect(second.getByText(/99%/i)).toBeInTheDocument()
    second.unmount()
  })
})
