import { useMemo, useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import { createAnalysisSample, runDataQuality } from '../api'
import type { AnalysisSampleVersion, DataQualityRun, DatasetVersion, ExclusionRuleInput } from '../types'
import { DataQualityDashboard } from './DataQualityDashboard'
import { metric, metricNumber, parseExpectedValue, variableLabel } from './dataQualityUtils'

interface DataQualityWorkspaceProps {
  dataset: DatasetVersion
}

export function DataQualityWorkspace({ dataset }: DataQualityWorkspaceProps) {
  const numericVariables = useMemo(
    () => dataset.variables.filter(variable => ['continuous', 'binary', 'ordinal', 'likert'].includes(variable.confirmedType ?? variable.inferredType)),
    [dataset.variables],
  )
  const responseVariables = useMemo(
    () => dataset.variables.filter(variable => /response.?id|respondent|participant|subject|被试|受访/i.test(variable.originalName)),
    [dataset.variables],
  )
  const durationVariables = useMemo(
    () => dataset.variables.filter(variable => /duration|time.?spent|时长|答题时间/i.test(variable.originalName)),
    [dataset.variables],
  )
  const ipVariables = useMemo(
    () => dataset.variables.filter(variable => /(^|[_\s-])ip([_\s-]|$)|ip.?address|IP地址/i.test(variable.originalName)),
    [dataset.variables],
  )
  const deviceVariables = useMemo(
    () => dataset.variables.filter(variable => /device|fingerprint|设备/i.test(variable.originalName)),
    [dataset.variables],
  )
  const [qualityVariableIds, setQualityVariableIds] = useState<string[]>(() => numericVariables.filter(variable => !/id|code|编号/i.test(variable.originalName)).map(variable => variable.id))
  const [responseIdVariableId, setResponseIdVariableId] = useState<string>(responseVariables[0]?.id ?? '')
  const [durationVariableId, setDurationVariableId] = useState<string>(durationVariables[0]?.id ?? '')
  const [ipVariableId, setIpVariableId] = useState<string>(ipVariables[0]?.id ?? '')
  const [deviceVariableId, setDeviceVariableId] = useState<string>(deviceVariables[0]?.id ?? '')
  const [textVariableIds, setTextVariableIds] = useState<string[]>([])
  const [structuralMissingVariableIds, setStructuralMissingVariableIds] = useState<string[]>([])
  const [attentionVariableId, setAttentionVariableId] = useState<string>('')
  const [attentionExpected, setAttentionExpected] = useState<string>('')
  const [durationCutoff, setDurationCutoff] = useState('30')
  const [missingCutoff, setMissingCutoff] = useState('0.2')
  const [straightlineCutoff, setStraightlineCutoff] = useState('0.8')
  const [qualityRun, setQualityRun] = useState<DataQualityRun | null>(null)
  const [sample, setSample] = useState<AnalysisSampleVersion | null>(null)

  const runMutation = useMutation({
    mutationFn: () => runDataQuality(dataset.id, {
      qualityVariableIds: qualityVariableIds.length ? qualityVariableIds : undefined,
      responseIdVariableId: responseIdVariableId || null,
      durationVariableId: durationVariableId || null,
      ipVariableId: ipVariableId || null,
      deviceVariableId: deviceVariableId || null,
      textVariableIds: textVariableIds.length ? textVariableIds : undefined,
      structuralMissingVariableIds: structuralMissingVariableIds.length ? structuralMissingVariableIds : undefined,
      attentionChecks: attentionVariableId ? [{ variableId: attentionVariableId, expectedValue: parseExpectedValue(attentionExpected), label: '用户配置的注意力检查' }] : undefined,
    }),
    onSuccess: result => {
      setQualityRun(result)
      setSample(null)
    },
  })

  const sampleMutation = useMutation({
    mutationFn: (request: { qualityRunId: string; rules: ExclusionRuleInput[] }) => createAnalysisSample(dataset.id, {
      qualityRunId: request.qualityRunId,
      combineOperator: 'or',
      label: '主分析样本',
      rules: request.rules,
    }),
    onSuccess: result => setSample(result),
  })

  const buildRules = (): ExclusionRuleInput[] => {
    const rules: ExclusionRuleInput[] = []
    if (durationVariableId && Number.isFinite(Number(durationCutoff))) {
      rules.push({ id: 'rule_speed', metric: 'duration_seconds', operator: 'lt', threshold: Number(durationCutoff), logicGroup: 'default', source: 'preregistered_primary', description: `答题时长低于 ${durationCutoff} 秒`, enabled: true })
    }
    if (Number.isFinite(Number(missingCutoff))) {
      rules.push({ id: 'rule_missing_rate', metric: 'missing_rate', operator: 'gt', threshold: Number(missingCutoff), logicGroup: 'default', source: 'preregistered_primary', description: `质量题项缺失率高于 ${missingCutoff}`, enabled: true })
    }
    if (Number.isFinite(Number(straightlineCutoff))) {
      rules.push({ id: 'rule_straightline', metric: 'straightline_ratio', operator: 'gte', threshold: Number(straightlineCutoff), logicGroup: 'default', source: 'planned_not_preregistered', description: `连续同值比例达到 ${straightlineCutoff}`, enabled: true })
    }
    if (responseIdVariableId) {
      rules.push({ id: 'rule_duplicate_response_id', metric: 'duplicate_response_id', operator: 'eq', threshold: true, logicGroup: 'default', source: 'preregistered_primary', description: 'ResponseId 重复', enabled: true })
    }
    if (ipVariableId) {
      rules.push({ id: 'rule_duplicate_ip', metric: 'duplicate_ip', operator: 'eq', threshold: true, logicGroup: 'default', source: 'planned_not_preregistered', description: 'IP 地址重复', enabled: true })
    }
    if (deviceVariableId) {
      rules.push({ id: 'rule_duplicate_device', metric: 'duplicate_device', operator: 'eq', threshold: true, logicGroup: 'default', source: 'planned_not_preregistered', description: '设备指纹重复', enabled: true })
    }
    if (attentionVariableId) {
      rules.push({ id: 'rule_attention_check', metric: 'attention_check_failed', operator: 'eq', threshold: true, logicGroup: 'default', source: 'preregistered_primary', description: '注意力检查失败', enabled: true })
    }
    return rules
  }

  const error = runMutation.error ?? sampleMutation.error
  const durationSummary = metric(qualityRun ?? undefined, 'duration')
  const missingRate = metricNumber(qualityRun ?? undefined, 'missing_rate', 'mean')
  const straightlineRatio = metricNumber(qualityRun ?? undefined, 'straightline_ratio', 'mean')
  const duplicateCount = metricNumber(qualityRun ?? undefined, 'duplicates', 'count')
  return (
    <section aria-labelledby="quality-heading" style={{ marginTop: '24px', padding: '18px', border: '1px solid rgba(148, 163, 184, 0.25)', borderRadius: '12px' }}>
      <p className="eyebrow">数据质量</p>
      <h2 id="quality-heading">案例级数据质量与分析样本</h2>
      <p className="muted">质量运行只生成审计指标和标记，不生成未经预注册的单一总分，也不修改原始数据；排除规则会创建不可变 AnalysisSampleVersion。</p>

      <DataQualityDashboard
        qualityRun={qualityRun}
        missingRate={missingRate}
        straightlineRatio={straightlineRatio}
        duplicateCount={duplicateCount}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
        <label>
          质量题项（可多选）
          <select multiple value={qualityVariableIds} onChange={event => setQualityVariableIds(Array.from(event.currentTarget.selectedOptions, option => option.value))} style={{ minHeight: '108px', width: '100%' }}>
            {numericVariables.map(variable => <option key={variable.id} value={variable.id}>{variableLabel(variable)}</option>)}
          </select>
        </label>
        <label>
          ResponseId / 被试 ID
          <select value={responseIdVariableId} onChange={event => setResponseIdVariableId(event.target.value)} style={{ width: '100%' }}>
            <option value="">不指定</option>
            {responseVariables.map(variable => <option key={variable.id} value={variable.id}>{variableLabel(variable)}</option>)}
          </select>
        </label>

        <label>
          时长变量
          <select value={durationVariableId} onChange={event => setDurationVariableId(event.target.value)} style={{ width: '100%' }}>
            <option value="">不指定</option>
            {durationVariables.map(variable => <option key={variable.id} value={variable.id}>{variableLabel(variable)}</option>)}
          </select>
        </label>
        <label>
          文本变量（可多选）
          <select multiple value={textVariableIds} onChange={event => setTextVariableIds(Array.from(event.currentTarget.selectedOptions, option => option.value))} style={{ minHeight: '72px', width: '100%' }}>
            {dataset.variables.filter(variable => variable.inferredType === 'text').map(variable => <option key={variable.id} value={variable.id}>{variableLabel(variable)}</option>)}
          </select>
        </label>
        <label>
          结构性缺失变量（可多选）
          <select multiple value={structuralMissingVariableIds} onChange={event => setStructuralMissingVariableIds(Array.from(event.currentTarget.selectedOptions, option => option.value))} style={{ minHeight: '72px', width: '100%' }}>
            {dataset.variables.map(variable => <option key={variable.id} value={variable.id}>{variableLabel(variable)}</option>)}
          </select>
        </label>
        <label>
          IP 地址变量
          <select value={ipVariableId} onChange={event => setIpVariableId(event.target.value)} style={{ width: '100%' }}>
            <option value="">不指定</option>
            {ipVariables.map(variable => <option key={variable.id} value={variable.id}>{variableLabel(variable)}</option>)}
          </select>
        </label>
        <label>
          设备指纹变量
          <select value={deviceVariableId} onChange={event => setDeviceVariableId(event.target.value)} style={{ width: '100%' }}>
            <option value="">不指定</option>
            {deviceVariables.map(variable => <option key={variable.id} value={variable.id}>{variableLabel(variable)}</option>)}
          </select>
        </label>
        <label>
          注意力检查变量
          <select value={attentionVariableId} onChange={event => setAttentionVariableId(event.target.value)} style={{ width: '100%' }}>
            <option value="">不指定</option>
            {numericVariables.map(variable => <option key={variable.id} value={variable.id}>{variableLabel(variable)}</option>)}
          </select>
        </label>
        <label>
          注意力期望值
          <input value={attentionExpected} onChange={event => setAttentionExpected(event.target.value)} placeholder="例如 3" style={{ width: '100%' }} />
        </label>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginTop: '12px' }}>
        <label>极速阈值（秒） <input type="number" min="0" value={durationCutoff} onChange={event => setDurationCutoff(event.target.value)} style={{ width: '80px' }} /></label>
        <label>缺失率阈值 <input type="number" min="0" max="1" step="0.05" value={missingCutoff} onChange={event => setMissingCutoff(event.target.value)} style={{ width: '80px' }} /></label>
        <label>直线作答阈值 <input type="number" min="0" max="1" step="0.05" value={straightlineCutoff} onChange={event => setStraightlineCutoff(event.target.value)} style={{ width: '80px' }} /></label>
      </div>
      <div style={{ display: 'flex', gap: '8px', marginTop: '14px' }}>
        <button type="button" className="run-button" onClick={() => runMutation.mutate()} disabled={runMutation.isPending || qualityVariableIds.length === 0}>
          {runMutation.isPending ? '正在计算质量指标…' : '运行案例级质量检查'}
        </button>
        {qualityRun && <button type="button" className="run-button" onClick={() => sampleMutation.mutate({ qualityRunId: qualityRun.id, rules: buildRules() })} disabled={sampleMutation.isPending}>{sampleMutation.isPending ? '正在生成样本版本…' : '生成主分析样本版本'}</button>}
      </div>
      {error ? <p className="error-message" role="alert">{error.message}</p> : null}
      {qualityRun ? (
        <section style={{ marginTop: '16px' }} aria-label="质量运行摘要">
          <strong>质量运行 {qualityRun.id}</strong>
          <div className="dataset-summary" style={{ marginTop: '10px' }}>
            <div><span>案例数</span><strong>{qualityRun.rowCount}</strong></div>
            <div><span>重复 ResponseId</span><strong>{metricNumber(qualityRun, 'duplicateResponseId', 'duplicateRowCount') ?? '—'}</strong></div>
            <div><span>注意力失败</span><strong>{metricNumber(qualityRun, 'attentionChecks', 'failedRowCount') ?? '—'}</strong></div>
            <div><span>时长中位数</span><strong>{String(durationSummary.median ?? '—')}</strong></div>
          </div>
        </section>
      ) : null}
      {sample ? <p className="method-warning" role="status">已生成 {sample.id}：纳入 {sample.includedCount}，排除 {sample.excludedCount}，边界案例 {sample.boundaryCount}，sample hash <code>{sample.sampleHash}</code>。</p> : null}
    </section>
  )
}
