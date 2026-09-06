import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { getServerAnalysisIndex, patchServerAnalysisDocument } from '../api/analysis-index'
import { downloadWithSession } from '../api/client'
import { empiricalAnalysisExportUrl } from '../api/empirical-analysis'
import { analysisExportUrl } from '../api/analyses'
import { advancedAnalysisExportUrl } from '../api/advanced'
import type { DatasetVersion, MeasurementVersion } from '../types'
import type { EmpiricalProcedure } from '../types/empirical-types'
import { OutputRegisteredRunDetail } from './OutputRegisteredRunDetail'
import { empiricalDraftStatusForOutput } from './analyses/analysisDraftStatus'
import {
  analysisDocumentFreshness,
  analysisDocumentsForProject,
  analysisRunFreshness,
  analysisRunsForDocument,
  createEmpiricalAnalysisDocument,
  loadEmpiricalAnalysisIndex,
  setAnalysisPrimaryRun,
  updateAnalysisDocumentMetadata,
} from './analyses/analysisDocuments'
import { readAnalysisRunDetails } from './analyses/analysisRunDetails'
import {
  readRegisteredOutputRuns,
  registeredOutputFreshness,
} from './analyses/outputRunRegistry'
import {
  mergeEmpiricalServerIndex,
  mergeRegisteredServerDocuments,
  mergeRegisteredServerRuns,
  registeredRunsForDocument,
  type RegisteredOutputDocument,
} from './analyses/serverAnalysisIndexBridge'
import { useOutputRunJobs } from './analyses/useOutputRunJobs'
import { cloneEmpiricalDraftsToAnalysis } from './empirical/empiricalDrafts'

const OutputEmpiricalRunPreview = lazy(async () => {
  const module = await import('./OutputEmpiricalRunPreview')
  return { default: module.OutputEmpiricalRunPreview }
})

interface OutputWorkspaceProps {
  dataset: DatasetVersion
  measurement: MeasurementVersion | null
  onOpenProcedure: (procedure: EmpiricalProcedure, analysisId?: string, runId?: string, methodId?: string) => void
}

function runStatusLabel(status?: string) {
  if (status === 'queued') return '排队中'
  if (status === 'running') return '运行中'
  if (status === 'cancelling') return '取消中'
  if (status === 'succeeded') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'cancelled') return '已取消'
  return '历史状态待服务端结果索引确认'
}

function registeredSourceLabel(source: 'model' | 'advanced', methodId: string) {
  if (source === 'model') return methodId === 'model.sem' ? 'SEM' : 'PROCESS / 模型'
  return '高级 / 结构化分析'
}

export function OutputWorkspace({ dataset, measurement, onOpenProcedure }: OutputWorkspaceProps) {
  const [localIndex, setIndex] = useState(() => loadEmpiricalAnalysisIndex(dataset, measurement))
  const [localRegisteredRuns, setRegisteredRuns] = useState(() => readRegisteredOutputRuns(dataset.projectId))
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedRegisteredRunId, setSelectedRegisteredRunId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [selectedExports, setSelectedExports] = useState<Set<string>>(new Set())
  const [exportStatus, setExportStatus] = useState<string | null>(null)
  const [registeredDocumentOverrides, setRegisteredDocumentOverrides] = useState<Record<string, {
    title?: string
    pinned?: boolean
    primaryRunId?: string
  }>>({})
  const [registeredMetadataStatus, setRegisteredMetadataStatus] = useState<string | null>(null)
  const serverIndexQuery = useQuery({
    queryKey: ['server-analysis-index', dataset.projectId],
    queryFn: () => getServerAnalysisIndex(dataset.projectId),
    staleTime: 5_000,
    retry: false,
  })
  const index = useMemo(
    () => mergeEmpiricalServerIndex(localIndex, serverIndexQuery.data),
    [localIndex, serverIndexQuery.data],
  )
  const registeredRuns = useMemo(
    () => mergeRegisteredServerRuns(localRegisteredRuns, serverIndexQuery.data),
    [localRegisteredRuns, serverIndexQuery.data],
  )
  const registeredDocuments = useMemo(
    () => mergeRegisteredServerDocuments(registeredRuns, serverIndexQuery.data).map((document) => ({
      ...document,
      ...registeredDocumentOverrides[document.id],
    })),
    [registeredDocumentOverrides, registeredRuns, serverIndexQuery.data],
  )

  useEffect(() => {
    setIndex(loadEmpiricalAnalysisIndex(dataset, measurement))
    setRegisteredRuns(readRegisteredOutputRuns(dataset.projectId))
    setSelectedRunId(null)
    setSelectedRegisteredRunId(null)
    setRegisteredDocumentOverrides({})
    setRegisteredMetadataStatus(null)
    setSelectedExports(new Set())
    setExportStatus(null)
  }, [dataset, measurement])

  const runDetails = readAnalysisRunDetails(dataset.projectId)
  const detailsByRun = useMemo(
    () => new Map(runDetails.map((detail) => [detail.runId, detail])),
    [runDetails],
  )
  const documents = useMemo(
    () => analysisDocumentsForProject(index, dataset.projectId),
    [dataset.projectId, index],
  )
  const normalizedSearch = search.trim().toLocaleLowerCase()
  const filteredDocuments = useMemo(() => documents.filter((document) => {
    if (!normalizedSearch) return true
    const runText = analysisRunsForDocument(index, document.id).map((run) => run.id).join(' ')
    return `${document.title} ${document.methodId} ${document.procedure} ${runText}`
      .toLocaleLowerCase()
      .includes(normalizedSearch)
  }), [documents, index, normalizedSearch])
  const filteredRegisteredDocuments = useMemo(() => registeredDocuments.filter((document) => {
    if (!normalizedSearch) return true
    const runText = registeredRunsForDocument(registeredRuns, document.id)
      .map((run) => `${run.label} ${run.methodId} ${run.runId} ${run.family ?? ''} ${run.modelId ?? ''}`)
      .join(' ')
    return `${document.title} ${document.methodId} ${document.categoryId} ${runText}`
      .toLocaleLowerCase()
      .includes(normalizedSearch)
  }), [normalizedSearch, registeredDocuments, registeredRuns])

  const allRuns = documents.flatMap((document) => analysisRunsForDocument(index, document.id))
  const recoveryRunIds = selectedRunId
    ? [selectedRunId, ...allRuns.map((run) => run.id)]
    : allRuns.map((run) => run.id)
  const serverJobsByRun = useOutputRunJobs(recoveryRunIds)
  const runCount = allRuns.length
  const totalOutputCount = documents.length + registeredDocuments.length
  const filteredOutputCount = filteredDocuments.length + filteredRegisteredDocuments.length

  const selectedRun = selectedRunId ? index.runs.find((run) => run.id === selectedRunId) : undefined
  const selectedDocument = selectedRun ? documents.find((document) => document.id === selectedRun.analysisId) : undefined
  const selectedDetail = selectedRun ? detailsByRun.get(selectedRun.id) : undefined
  const selectedServerJob = selectedRun ? serverJobsByRun.get(selectedRun.id) : undefined
  const selectedFreshness = selectedRun ? analysisRunFreshness(selectedRun, dataset, measurement) : undefined
  const selectedStatus = selectedServerJob?.status ?? selectedDetail?.runStatus
  const selectedReportId = selectedServerJob?.reportId ?? selectedDetail?.resultId ?? undefined
  const selectedOptions = selectedServerJob?.options ?? selectedDetail?.submittedSpec
  const selectedPreviewDatasetId = selectedServerJob?.datasetId
    ?? (selectedFreshness === 'current' ? dataset.id : undefined)
  const selectedPreviewMeasurementVersion = selectedServerJob
    ? selectedServerJob.measurementVersion
    : selectedFreshness === 'current'
      ? measurement?.version ?? null
      : undefined
  const selectedRegisteredRun = selectedRegisteredRunId
    ? registeredRuns.find((run) => run.runId === selectedRegisteredRunId)
    : undefined
  const selectedRegisteredDocument = selectedRegisteredRun
    ? registeredDocuments.find((document) => (
      registeredRunsForDocument(registeredRuns, document.id)
        .some((run) => run.runId === selectedRegisteredRun.runId)
    ))
    : undefined

  const toggleExport = (key: string) => {
    setSelectedExports((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const exportSelected = async () => {
    setExportStatus('正在导出…')
    let completed = 0
    try {
      for (const key of selectedExports) {
        if (key.startsWith('empirical:')) {
          const runId = key.slice('empirical:'.length)
          const job = serverJobsByRun.get(runId)
          if (!job?.reportId) continue
          await downloadWithSession(
            empiricalAnalysisExportUrl(job.datasetId, job.measurementVersion, job.reportId),
            `researchpath-${runId}.xlsx`,
          )
          completed += 1
        } else {
          const runId = key.slice('registered:'.length)
          const run = registeredRuns.find((candidate) => candidate.runId === runId)
          if (!run) continue
          await downloadWithSession(
            run.source === 'model' ? analysisExportUrl(runId, false) : advancedAnalysisExportUrl(runId),
            `researchpath-${runId}.zip`,
          )
          completed += 1
        }
      }
      setExportStatus(`已导出 ${completed} 项结果。`)
      setSelectedExports(new Set())
    } catch (error) {
      setExportStatus(`已导出 ${completed} 项；其余导出失败：${error instanceof Error ? error.message : '未知错误'}`)
    }
  }

  const updateDocument = (analysisId: string, patch: { title?: string; pinned?: boolean }) => {
    setIndex(updateAnalysisDocumentMetadata(dataset.projectId, analysisId, patch))
  }
  const updatePrimaryRun = (analysisId: string, runId: string | null) => {
    setIndex(setAnalysisPrimaryRun(dataset.projectId, analysisId, runId))
  }
  const duplicateDocument = (document: (typeof documents)[number]) => {
    if (analysisDocumentFreshness(document, dataset, measurement) !== 'current') return
    const duplicate = createEmpiricalAnalysisDocument(
      dataset,
      measurement,
      document.procedure,
      `${document.title} 副本`,
      document.methodId,
    )
    cloneEmpiricalDraftsToAnalysis(
      dataset,
      measurement,
      document.id,
      duplicate.id,
      document.procedure,
    )
    setIndex(loadEmpiricalAnalysisIndex(dataset, measurement))
    onOpenProcedure(duplicate.procedure, duplicate.id, undefined, duplicate.methodId)
  }
  const updateRegisteredDocument = (
    document: RegisteredOutputDocument,
    patch: { title?: string; pinned?: boolean; primaryRunId?: string | null },
  ) => {
    const localPatch: { title?: string; pinned?: boolean; primaryRunId?: string } = {}
    if (patch.title !== undefined) localPatch.title = patch.title
    if (patch.pinned !== undefined) localPatch.pinned = patch.pinned
    if ('primaryRunId' in patch) localPatch.primaryRunId = patch.primaryRunId ?? undefined
    const previous = registeredDocumentOverrides[document.id]
    setRegisteredDocumentOverrides((current) => ({
      ...current,
      [document.id]: { ...current[document.id], ...localPatch },
    }))
    setRegisteredMetadataStatus('正在保存分析对象…')
    void patchServerAnalysisDocument(dataset.projectId, document.id, patch)
      .then(() => setRegisteredMetadataStatus('分析对象已保存。'))
      .catch(() => {
        setRegisteredDocumentOverrides((current) => {
          const next = { ...current }
          if (previous) next[document.id] = previous
          else delete next[document.id]
          return next
        })
        setRegisteredMetadataStatus('保存失败；名称、固定状态或主要结果没有写入服务端。')
      })
  }

  return (
    <main className="analysis-shell" aria-labelledby="output-workspace-heading">
      <header className="analysis-shell-header">
        <div>
          <p className="eyebrow">分析对象与运行</p>
          <h1 id="output-workspace-heading">输出</h1>
          <p>统一查看、比较和导出当前项目的全部分析结果。</p>
        </div>
        <span className="status-badge">{serverIndexQuery.isError ? '部分历史暂不可用' : '结果已恢复'}</span>
      </header>

      {totalOutputCount ? (
        <section className="context-catalog" aria-label="项目输出索引">
          <div className="section-heading-row">
            <div>
              <p className="eyebrow">当前项目</p>
              <h2>输出索引</h2>
            </div>
            <span className="status-badge">{documents.length} 项实证分析 · {registeredDocuments.length} 项模型/高级分析</span>
          </div>
          <div className="method-catalog-filters">
            <label>
              搜索输出
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="分析名称、方法或运行 ID"
              />
            </label>
            <button type="button" className="secondary-button" disabled={!search} onClick={() => setSearch('')}>清除搜索</button>
          </div>
          <p className="catalog-result-count" role="status">显示 {filteredOutputCount} / {totalOutputCount} 项输出</p>
          <div className="method-card-actions">
            <button type="button" className="secondary-button" disabled={!selectedExports.size} onClick={() => void exportSelected()}>
              批量导出（{selectedExports.size}）
            </button>
            {exportStatus ? <span role="status">{exportStatus}</span> : null}
          </div>
        </section>
      ) : null}

      {registeredMetadataStatus ? (
        <p
          className={registeredMetadataStatus.startsWith('保存失败') ? 'validation-error' : 'method-note'}
          role={registeredMetadataStatus.startsWith('保存失败') ? 'alert' : 'status'}
        >
          {registeredMetadataStatus}
        </p>
      ) : null}

      {selectedRegisteredRun ? (
        <OutputRegisteredRunDetail
          run={selectedRegisteredRun}
          onClose={() => setSelectedRegisteredRunId(null)}
          isPrimary={selectedRegisteredDocument?.primaryRunId === selectedRegisteredRun.runId}
          onTogglePrimary={selectedRegisteredDocument
            ? () => updateRegisteredDocument(selectedRegisteredDocument, {
              primaryRunId: selectedRegisteredDocument.primaryRunId === selectedRegisteredRun.runId
                ? null
                : selectedRegisteredRun.runId,
            })
            : undefined}
        />
      ) : null}

      {selectedRun && selectedDocument ? (
        <section className="context-catalog" aria-label="选中的运行">
          <div className="section-heading-row">
            <div>
              <p className="eyebrow">当前运行</p>
              <h2>{selectedDocument.title}</h2>
              <p className="muted">{new Date(selectedRun.createdAt).toLocaleString()} · {runStatusLabel(selectedStatus)}</p>
            </div>
            <button type="button" className="secondary-button" onClick={() => setSelectedRunId(null)}>关闭详情</button>
          </div>
          <div className="method-card-status-row">
            <span className="context-method-status">运行 {selectedRun.id.slice(0, 12)}</span>
            <span className={`context-method-status${selectedFreshness === 'stale' ? ' method-status-needs-setup' : ''}`}>
              {selectedFreshness === 'stale' ? '基于非当前设置' : '当前数据/量表'}
            </span>
            {selectedDocument.primaryRunId === selectedRun.id ? <span className="context-method-status">主要结果</span> : null}
            {selectedDetail ? <span className="context-method-status">草稿修订 {selectedDetail.draftRevision}</span> : null}
            {selectedServerJob ? <span className="context-method-status">服务端已确认</span> : null}
            {selectedDetail?.qualityStatus === 'warning' ? <span className="context-method-status method-status-needs-setup">含警告</span> : null}
          </div>
          {selectedDetail ? (
            <div>
              <p>结果 ID：{selectedDetail.resultId ?? '当前运行尚未产生结果 ID'}</p>
              <p>警告：{selectedDetail.warningCodes.length ? selectedDetail.warningCodes.join('、') : '无已记录警告'}</p>
              <p className="muted">冻结规格和任务状态继续来自权威 job/result 服务；OutputIndex 只保存分析身份、运行引用和上游版本。</p>
            </div>
          ) : (
            <p className="muted">该运行由服务端索引恢复。若浏览器没有旧草稿快照，仍可查看权威任务/结果，但不会补造不存在的编辑历史。</p>
          )}

          {selectedStatus === 'succeeded'
            && selectedReportId
            && selectedOptions
            && selectedPreviewDatasetId
            && selectedPreviewMeasurementVersion !== undefined ? (
            <Suspense fallback={<p role="status">正在加载只读结果渲染器…</p>}>
              <OutputEmpiricalRunPreview
                datasetId={selectedPreviewDatasetId}
                measurementVersion={selectedPreviewMeasurementVersion}
                reportId={selectedReportId}
                options={selectedOptions}
              />
            </Suspense>
          ) : null}

          <div className="method-card-actions">
            <button
              type="button"
              className="secondary-button"
              onClick={() => updatePrimaryRun(
                selectedDocument.id,
                selectedDocument.primaryRunId === selectedRun.id ? null : selectedRun.id,
              )}
            >
              {selectedDocument.primaryRunId === selectedRun.id ? '取消主要结果' : '设为主要结果'}
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => selectedFreshness === 'stale'
                ? onOpenProcedure(selectedDocument.procedure, undefined, undefined, selectedDocument.methodId)
                : onOpenProcedure(selectedDocument.procedure, selectedDocument.id, selectedRun.id, selectedDocument.methodId)}
            >
              {selectedFreshness === 'stale' ? '用当前数据新建配置' : '打开该运行结果 / 设置'}
            </button>
          </div>
        </section>
      ) : null}

      {registeredDocuments.length ? (
        <section className="context-catalog" aria-label="模型与高级运行">
          <div className="section-heading-row">
            <div>
              <p className="eyebrow">统一分析对象</p>
              <h2>PROCESS / SEM / 高级分析</h2>
              <p className="muted">每项分析保留独立运行历史，可以固定或指定主要结果。</p>
            </div>
            <span className="status-badge">{registeredDocuments.length} 项分析 · {registeredRuns.length} 次运行</span>
          </div>
          {filteredRegisteredDocuments.length ? (
            <div className="method-grid">
              {filteredRegisteredDocuments.map((document) => {
                const runs = registeredRunsForDocument(registeredRuns, document.id)
                const latestRun = runs[0]
                const freshness = latestRun
                  ? registeredOutputFreshness(latestRun, dataset, measurement)
                  : document.datasetVersionId === dataset.id ? 'current' : 'stale'
                return (
                  <article className="method-card" key={document.id}>
                    <div>
                      <p className="eyebrow">{registeredSourceLabel(document.source, document.methodId)}</p>
                      <h3>{document.title}</h3>
                      <p>{runs.length} 次运行{latestRun ? ` · 最近 ${new Date(latestRun.createdAt).toLocaleString()}` : ''}</p>
                      <div className="method-card-status-row">
                        {document.pinned ? <span className="context-method-status">已固定</span> : null}
                        {document.primaryRunId ? <span className="context-method-status">已指定主要结果</span> : null}
                        <span className={`context-method-status${freshness === 'stale' ? ' method-status-needs-setup' : ''}`}>
                          {freshness === 'stale' ? '基于非当前设置' : '当前数据/量表'}
                        </span>
                      </div>
                      {latestRun ? (
                        <label><input type="checkbox" checked={selectedExports.has(`registered:${latestRun.runId}`)} onChange={() => toggleExport(`registered:${latestRun.runId}`)} /> 选择最新结果用于批量导出</label>
                      ) : null}
                      <details><summary>技术详情</summary><p className="muted">方法 {document.methodId} · 分析 {document.id.slice(0, 12)}</p></details>
                    </div>
                    {runs.length ? (
                      <details>
                        <summary>查看运行历史</summary>
                        <ol>
                          {runs.map((run) => (
                            <li key={run.runId}>
                              <button
                                type="button"
                                className="text-button"
                                onClick={() => {
                                  setSelectedRunId(null)
                                  setSelectedRegisteredRunId(run.runId)
                                }}
                              >
                                <code>{run.runId.slice(0, 12)}</code>
                                {' · '}{new Date(run.createdAt).toLocaleString()}
                                {document.primaryRunId === run.runId ? ' · 主要结果' : ''}
                              </button>
                            </li>
                          ))}
                        </ol>
                      </details>
                    ) : null}
                    <div className="method-card-actions">
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => updateRegisteredDocument(document, { pinned: !document.pinned })}
                      >
                        {document.pinned ? '取消固定' : '固定分析'}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => {
                          const nextTitle = window.prompt('分析名称', document.title)
                          const title = nextTitle?.trim()
                          if (title) updateRegisteredDocument(document, { title })
                        }}
                      >
                        重命名
                      </button>
                    </div>
                  </article>
                )
              })}
            </div>
          ) : <p className="muted">当前搜索没有匹配的 PROCESS、SEM 或高级分析。</p>}
        </section>
      ) : null}

      {documents.length ? (
        <section className="context-catalog" aria-label="实证分析对象">
          <div className="section-heading-row">
            <div>
              <p className="eyebrow">实证分析对象</p>
              <h2>分析与运行</h2>
            </div>
            <span className="status-badge">{documents.length} 项分析 · {runCount} 次运行</span>
          </div>

          {filteredDocuments.length ? (
            <div className="method-grid">
              {filteredDocuments.map((document) => {
                const runs = analysisRunsForDocument(index, document.id)
                const latestRun = runs[0]
                const latestFreshness = latestRun ? analysisRunFreshness(latestRun, dataset, measurement) : analysisDocumentFreshness(document, dataset, measurement)
                const latestDetail = latestRun ? detailsByRun.get(latestRun.id) : undefined
                const latestServerJob = latestRun ? serverJobsByRun.get(latestRun.id) : undefined
                const draft = latestFreshness === 'current'
                  ? empiricalDraftStatusForOutput(dataset, measurement, document.procedure, latestRun?.id, document.id)
                  : { dirtySinceLastRun: false, hasSavedDraft: false }
                return (
                  <article className="method-card" key={document.id}>
                    <div>
                      <p className="eyebrow">{document.categoryId.replaceAll('-', ' ')}</p>
                      <h3>{document.title}</h3>
                      <p>{runs.length} 次运行{latestRun ? ` · 最近 ${new Date(latestRun.createdAt).toLocaleString()}` : ''}</p>
                      <div className="method-card-status-row">
                        {document.pinned ? <span className="context-method-status">已固定</span> : null}
                        {document.primaryRunId ? <span className="context-method-status">已指定主要结果</span> : null}
                        <span className={`context-method-status${latestFreshness === 'stale' ? ' method-status-needs-setup' : ''}`}>
                          {latestFreshness === 'stale' ? '基于非当前设置' : '当前数据/量表'}
                        </span>
                        {latestRun ? <span className="context-method-status">{runStatusLabel(latestServerJob?.status ?? latestDetail?.runStatus)}</span> : null}
                        {latestServerJob ? <span className="context-method-status">服务端已确认</span> : null}
                        {draft.dirtySinceLastRun ? <span className="context-method-status method-status-needs-setup">有未运行更改</span> : null}
                        {draft.hasSavedDraft ? <span className="context-method-status">草稿已保存</span> : null}
                      </div>
                      {latestDetail ? (
                        <details><summary>技术详情</summary><p className="muted">运行 {latestDetail.runId.slice(0, 12)} · 草稿修订 {latestDetail.draftRevision} · {latestDetail.qualityStatus === 'warning' ? '含警告' : '无已记录警告'}</p></details>
                      ) : latestRun ? (
                        <details><summary>技术详情</summary><p className="muted">最新运行 {latestRun.id.slice(0, 12)}</p></details>
                      ) : null}
                      {latestRun && (latestServerJob?.status ?? latestDetail?.runStatus) === 'succeeded' ? (
                        <label><input type="checkbox" checked={selectedExports.has(`empirical:${latestRun.id}`)} onChange={() => toggleExport(`empirical:${latestRun.id}`)} /> 选择最新结果用于批量导出</label>
                      ) : null}
                    </div>

                    {runs.length ? (
                      <details>
                        <summary>查看运行历史</summary>
                        <ol>
                          {runs.map((run) => {
                            const detail = detailsByRun.get(run.id)
                            const serverJob = serverJobsByRun.get(run.id)
                            const freshness = analysisRunFreshness(run, dataset, measurement)
                            return (
                              <li key={run.id}>
                                <button type="button" className="text-button" onClick={() => {
                                  setSelectedRegisteredRunId(null)
                                  setSelectedRunId(run.id)
                                }}>
                                  <code>{run.id.slice(0, 12)}</code>
                                  {' · '}{new Date(run.createdAt).toLocaleString()}
                                  {' · '}{runStatusLabel(serverJob?.status ?? detail?.runStatus)}
                                  {freshness === 'stale' ? ' · 基于非当前设置' : ''}
                                  {document.primaryRunId === run.id ? ' · 主要结果' : ''}
                                  {detail ? ` · 修订 ${detail.draftRevision}` : ''}
                                  {serverJob ? ' · 服务端已确认' : ''}
                                </button>
                              </li>
                            )
                          })}
                        </ol>
                      </details>
                    ) : null}

                    <div className="method-card-actions">
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => updateDocument(document.id, { pinned: !document.pinned })}
                      >
                        {document.pinned ? '取消固定' : '固定分析'}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => {
                          const nextTitle = window.prompt('分析名称', document.title)
                          if (nextTitle !== null) updateDocument(document.id, { title: nextTitle })
                        }}
                      >
                        重命名
                      </button>
                      {latestFreshness === 'current' ? (
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => duplicateDocument(document)}
                        >
                          复制分析
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => latestFreshness === 'stale'
                          ? onOpenProcedure(document.procedure, undefined, undefined, document.methodId)
                          : onOpenProcedure(document.procedure, document.id, undefined, document.methodId)}
                      >
                        {latestFreshness === 'stale' ? '用当前数据新建配置' : '编辑设置 / 打开当前结果'}
                      </button>
                    </div>
                  </article>
                )
              })}
            </div>
          ) : <p className="muted">当前搜索没有匹配的实证分析。</p>}
        </section>
      ) : null}

      {!totalOutputCount && serverIndexQuery.isLoading ? (
        <section className="centered-state" aria-live="polite">
          <h2>正在恢复项目输出</h2>
          <p>正在从服务端 AnalysisIndex 和已有任务记录重建分析历史。</p>
        </section>
      ) : !totalOutputCount ? (
        <section className="centered-state">
          <h2>还没有运行任何分析</h2>
          <p>从“分析”选择一个方法并显式运行后，这里会记录 AnalysisDocument 与不可变运行引用。</p>
        </section>
      ) : null}
    </main>
  )
}
