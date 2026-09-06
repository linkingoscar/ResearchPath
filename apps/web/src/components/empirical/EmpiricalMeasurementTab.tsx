import type { EmpiricalAnalysisSegmentMap } from '../../types'
import type { SegmentQueryState } from './segmentQuery'

import { metric, probability } from './resultFormatters'
import { ScreePlot } from './ScreePlot'
import { DiagnosticAlertCard } from '../shared/DiagnosticAlertCard'
import { SegmentLoader } from './EmpiricalBadges'

interface EmpiricalMeasurementTabProps {
  procedure?: 'efa' | 'cfa'
  query: SegmentQueryState<EmpiricalAnalysisSegmentMap['efa_cfa']>
  summaryQuery: SegmentQueryState<EmpiricalAnalysisSegmentMap['summary']>
}

// Parallel analysis declares which statistical world it ran in.
// The labels make the correlation/simulation choice user-visible so ordinal
// data can never silently fall back to a Pearson null distribution.
const parallelCorrelationLabel = (type?: string): string =>
  type === 'polychoric' ? 'polychoric（序数题项）' : type === 'pearson' ? 'Pearson（连续题项）' : '—'

const parallelSimulationLabel = (type?: string): string =>
  type === 'ordinal_threshold_preserving'
    ? '序数阈值保留模拟'
    : type === 'continuous_pearson'
      ? '连续正态模拟'
      : '—'

const parallelUnavailableReason = (reason?: string): string => {
  switch (reason) {
    case 'unsupported_for_ordinal_correlation':
      return '当前数据无法估计 polychoric 相关（lavaan 不可用或题项类别结构异常）'
    case 'polychoric_simulation_failed':
      return '序数模拟未能在当前样本规模上完成'
    default:
      return reason ?? '平行分析未返回可用结果'
  }
}

export function EmpiricalMeasurementTab({ query, summaryQuery, procedure }: EmpiricalMeasurementTabProps) {
if (query.isLoading) return <SegmentLoader />
if (query.isError) return <div className="error-banner">加载 EFA/CFA 数据失败: {String(query.error)}</div>
const data = query.data
if (!data) return null
const advancedBoundary = data.advancedMeasurementBoundary
const kmoVal = summaryQuery.data?.factorability?.kmo
const bartlett = summaryQuery.data?.factorability?.bartlett
const cmb = summaryQuery.data?.commonMethodBias
return (
  <section className="evidence-section" aria-labelledby="factor-heading">
    <div className="section-heading"><div><p className="eyebrow">Measurement evidence</p><h2 id="factor-heading">{procedure === 'cfa' ? '验证性因子分析' : procedure === 'efa' ? 'KMO/Bartlett 与 EFA' : '共同方法偏差、KMO/Bartlett 与 EFA'}</h2></div></div>
    {!procedure && advancedBoundary ? (
      <DiagnosticAlertCard
        type="note"
        title="高级测量方法未在基础报告中自动执行"
        subtitle={`${advancedBoundary.methods.join(' / ')} → 高级问卷测量工作台`}
        recommendation={advancedBoundary.requirement}
      >
        <p>活动能力：{advancedBoundary.sliceId}；基础报告 executedInBaseReport=false。</p>
      </DiagnosticAlertCard>
    ) : null}
    {procedure !== 'cfa' ? <dl className="run-meta factor-meta">
      {!procedure ? <div><dt>Harman 首因子解释率</dt><dd>{metric(cmb?.firstFactorVariancePercent, 2)}%</dd></div> : null}
      <div><dt>特征值 &gt; 1</dt><dd>{cmb?.eigenvaluesAboveOne ?? '—'}</dd></div>
      <div><dt>KMO</dt><dd>{metric(kmoVal)}</dd></div>
      <div><dt>Bartlett χ²(df)</dt><dd>{metric(bartlett?.statistic)} ({bartlett?.degreesOfFreedom ?? '—'})</dd></div>
      <div><dt>Bartlett p</dt><dd>{probability(bartlett?.pValue)}</dd></div>
      <div><dt>EFA 方法</dt><dd>{data.efa?.method ?? '—'}</dd></div>
    </dl> : null}
    {data.efa?.methodExecution?.fallbackApplied ? (
      <DiagnosticAlertCard
        type="warning"
        title="EFA 已使用降级方法"
        subtitle={`${data.efa.methodExecution.requestedMethod} → ${data.efa.methodExecution.executedMethod}`}
        recommendation="正式报告前请检查最大似然因子分析失败原因；当前 PCA 结果只能作为探索性诊断。"
      >
        <p>回退原因：{data.efa.methodExecution.fallbackReason ?? '最大似然 EFA 未返回可用结果。'}</p>
        <p>{data.efa.methodExecution.interpretationBoundary}</p>
      </DiagnosticAlertCard>
    ) : null}
    {data.cfa?.methodExecution ? (
      <DiagnosticAlertCard
        type={data.cfa.methodExecution.fallbackApplied ? 'warning' : 'note'}
        title={data.cfa.methodExecution.fallbackApplied ? 'CFA 发生方法回退' : 'CFA 方法执行记录'}
        subtitle={`${data.cfa.methodExecution.requestedMethod} → ${data.cfa.methodExecution.executedMethod}`}
        recommendation={data.cfa.methodExecution.interpretationBoundary ?? undefined}
      >
        {data.cfa.methodExecution.fallbackReason
          ? <p>回退原因：{data.cfa.methodExecution.fallbackReason}</p>
          : <p>请求方法与实际执行方法已随结果固化。</p>}
      </DiagnosticAlertCard>
    ) : null}
    {data.efa?.diagnostics?.numericalFallbacks && data.efa.diagnostics.numericalFallbacks.length > 0 ? (
      <DiagnosticAlertCard
        type="warning"
        title="EFA 使用了数值回退"
        subtitle={`${data.efa.diagnostics.numericalFallbacks.length} 处估计细节与请求设定不同`}
        recommendation="以下回退改变了估计的数值含义，请在正式报告中如实披露。"
      >
        {data.efa.diagnostics.numericalFallbacks.map((fallback) => (
          <p key={`${fallback.stage}-${fallback.requested}-${fallback.used}-${fallback.reason}`}>
            阶段 {fallback.stage}：请求 {fallback.requested}，实际使用 {fallback.used} —— {fallback.reason}
          </p>
        ))}
      </DiagnosticAlertCard>
    ) : null}
    {data.efa?.parallelAnalysis ? (
      data.efa.parallelAnalysis.available === false ? (
        <DiagnosticAlertCard
          type="warning"
          title="平行分析不可用"
          subtitle={parallelUnavailableReason(data.efa.parallelAnalysis.reason)}
          recommendation="序数数据下不会以 Pearson 相关静默替代 polychoric；请确认 lavaan 可用且题项类别结构完整后重试。"
        >
          <p>因子数建议未来自平行分析，请结合其他准则（如 Kaiser 或理论结构）解读。</p>
        </DiagnosticAlertCard>
      ) : data.efa.parallelAnalysis.recommendedFactorCount === 0 ? (
        <DiagnosticAlertCard
          type="warning"
          title="平行分析未支持保留共同因子"
          subtitle="本次 observed eigenvalue 均未超过模拟数据的第 95 百分位阈值"
          recommendation="系统不会把该诊断强制改写为 1 因子；如仍需拟合，请改用固定因子数并记录理论依据。"
        >
          <p>当前建议为 0 个因子，这与“EFA 拟合器至少需要 1 个因子”是两个不同结论。</p>
        </DiagnosticAlertCard>
      ) : (
        <p className="method-note" style={{ marginBottom: '1rem' }}>
          平行分析建议提取因子数：<strong>{data.efa.parallelAnalysis.recommendedFactorCount}</strong> 个（{data.efa.parallelAnalysis.iterations} 次模拟，seed={data.efa.parallelAnalysis.seed}；相关矩阵 {parallelCorrelationLabel(data.efa.parallelAnalysis.correlationType)}，模拟类型 {parallelSimulationLabel(data.efa.parallelAnalysis.simulationType)}）。
          （前 3 个模拟特征值：{data.efa.parallelAnalysis.simulatedEigenvalues?.slice(0, 3).map((v: number) => metric(v)).join('，')}）
        </p>
      )
    ) : null}
    {data.efa?.available === false && data.efa.reason === 'factor_retention_diagnostic_recommended_zero_factors' ? (
      <p className="method-note">因子保留诊断建议为 0，因此本次没有自动拟合 EFA 载荷模型。</p>
    ) : null}
    {data.efa?.eigenvalues && data.efa.eigenvalues.length > 0 && (
      <ScreePlot
        eigenvalues={data.efa.eigenvalues}
        simulatedEigenvalues={data.efa.parallelAnalysis?.simulatedEigenvalues}
      />
    )}
    {procedure !== 'cfa' ? (data.efa?.available ? (
      <>
        <div className="table-wrap">
          <strong>因子载荷矩阵 (Pattern Matrix - {data.efa.rotation})</strong>
          <table className="result-table empirical-table">
            <thead><tr><th>题项</th>{data.efa.factorLabels.map((label: string) => <th key={label}>{label}</th>)}<th>共同度</th></tr></thead>
            <tbody>{data.efa.loadings.map((row: { itemId: string; label: string; loadings: number[]; communality: number | null }) => (
              <tr key={row.itemId}>
                <th>{row.label}</th>
                {row.loadings.map((loading: number, index: number) => {
                  const absLoading = Math.abs(loading)
                  const loadingClass = absLoading >= 0.5 ? 'salient-loading is-strong' : absLoading >= 0.4 ? 'salient-loading is-moderate' : ''
                  return <td className={loadingClass} key={data.efa.factorLabels[index]}>{metric(loading)}</td>
                })}
                <td>{metric(row.communality)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        {data.efa.structureMatrix ? (
          <div className="table-wrap" style={{ marginTop: '1.5rem' }}>
            <strong>结构矩阵 (Structure Matrix)</strong>
            <table className="result-table empirical-table">
              <thead><tr><th>题项</th>{data.efa.factorLabels.map((label: string) => <th key={label}>{label}</th>)}</tr></thead>
              <tbody>{data.efa.loadings.map((row: { itemId: string; label: string; loadings: number[]; communality: number | null }, rowIndex: number) => (
                <tr key={row.itemId}>
                  <th>{row.label}</th>
                  {data.efa.structureMatrix?.[rowIndex]?.map((val: number, idx: number) => (
                    <td key={data.efa.factorLabels[idx]}>{metric(val)}</td>
                  ))}
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}
        {data.efa.factorCorrelations ? (
          <div className="table-wrap" style={{ marginTop: '1.5rem', maxWidth: '400px' }}>
            <strong>因子相关矩阵</strong>
            <table className="result-table matrix-table">
              <thead><tr><th></th>{data.efa.factorLabels.map((label: string) => <th key={label}>{label}</th>)}</tr></thead>
              <tbody>{data.efa.factorLabels.map((label: string, rowIndex: number) => (
                <tr key={label}>
                  <th>{label}</th>
                  {data.efa.factorCorrelations?.[rowIndex]?.map((val: number, idx: number) => (
                    <td key={data.efa.factorLabels[idx]}>{metric(val)}</td>
                  ))}
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}
      </>
    ) : <p className="method-warning">当前完整案例或题项变异不足，无法提取 EFA。</p>) : null}

    {procedure !== 'efa' ? <div style={{ marginTop: '32px' }}>
      <h3 style={{ marginBottom: '12px' }}>验证性因子分析 Fit 拟合指标</h3>
      {data.cfa?.available ? (
        <dl className="run-meta factor-meta">
          <div><dt>χ²(df)</dt><dd>{metric(data.cfa.chiSquare)} ({data.cfa.degreesOfFreedom})</dd></div>
          <div><dt>CFI</dt><dd>{metric(data.cfa.cfi)}</dd></div>
          <div><dt>TLI</dt><dd>{metric(data.cfa.tli)}</dd></div>
          <div><dt>RMSEA [90% CI]</dt><dd>{metric(data.cfa.rmsea)} [{metric(data.cfa.rmseaCiLower) ?? '—'}, {metric(data.cfa.rmseaCiUpper) ?? '—'}]</dd></div>
          <div><dt>SRMR</dt><dd>{metric(data.cfa.srmr)}</dd></div>
          <div><dt>估计器</dt><dd>{data.cfa.estimator}</dd></div>
        </dl>
      ) : <p className="method-warning">{data.cfa?.reason ?? 'CFA 拟合结果不可用。'}</p>}
    </div> : null}
  </section>
)
}
