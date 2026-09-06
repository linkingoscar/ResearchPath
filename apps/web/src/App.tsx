import { lazy, Suspense, useState } from 'react'
import type { EmpiricalProcedure } from './types/empirical-types'
import type { MethodRequest } from './components/context/workbenchNavigation'

import { AppHydratingScreen } from './AppHydratingScreen'
import { AppWorkspaceTabs } from './AppWorkspaceTabs'
import {
  createEmpiricalAnalysisDocument,
  ensureEmpiricalAnalysisDocument,
  loadEmpiricalAnalysisIndex,
} from './components/analyses/analysisDocuments'
import { cloneEmpiricalDraftToAnalysis } from './components/empirical/empiricalDrafts'
import { CommandPalette } from './components/shared/CommandPalette'
import { LocalPrivacyBadge } from './components/shared/LocalPrivacyBadge'
import { ResearchStart } from './components/shared/ResearchStart'
import { StudyContextSwitcher } from './components/shared/StudyContextSwitcher'
import { SectionErrorBoundary } from './components/shared/SectionErrorBoundary'
import { ToastContainer } from './components/shared/Toast'
import { procedureDefinition } from './components/empirical/empiricalProcedures'
import { methodDefinitions } from './methods/methodDefinitions'
import { useTheme } from './hooks/useTheme'
import { useWorkspaceState } from './hooks/useWorkspaceState'

const EmpiricalAnalysis = lazy(() => import('./components/EmpiricalAnalysis').then((module) => ({ default: module.EmpiricalAnalysis })))
const ModelBuilder = lazy(() => import('./components/ModelBuilder').then((module) => ({ default: module.ModelBuilder })))
const DataWorkspace = lazy(() => import('./components/DataWorkspace').then((module) => ({ default: module.DataWorkspace })))
const ContextCapabilityCatalog = lazy(() => import('./components/context/ContextCapabilityCatalog').then((module) => ({ default: module.ContextCapabilityCatalog })))
const PlanningWorkspace = lazy(() => import('./components/PlanningWorkspace').then((module) => ({ default: module.PlanningWorkspace })))
const OutputWorkspace = lazy(() => import('./components/OutputWorkspace').then((module) => ({ default: module.OutputWorkspace })))

type AnalysisSurface = 'library' | 'empirical' | 'model'

export function App() {
  const { theme, setTheme } = useTheme()
  const [modelMethodRequest, setModelMethodRequest] = useState<MethodRequest | null>(null)
  const [analysisSurface, setAnalysisSurface] = useState<AnalysisSurface>('library')
  const [activeAnalysisId, setActiveAnalysisId] = useState<string | null>(null)
  const [activeRunRequestId, setActiveRunRequestId] = useState<string | null>(null)
  const {
    workspaceNavRef,
    studyIntent,
    effectiveStudyContext,
    studyContextSaveError,
    studyContextPersistence,
    activeView,
    setActiveView,
    loadingDemo,
    activeDataset,
    modelContext,
    hydrating,
    isCommandPaletteOpen,
    setIsCommandPaletteOpen,
    empiricalTabRequest,
    setEmpiricalTabRequest,
    resolvedContextQuery,
    resolvedContext,
    researchParadigm,
    workspaceSteps,
    handleMeasurementReady,
    handleDatasetReady,
    handleStructureSaved,
    handleLoadDemo,
    handleIntentSelect,
    handleStudyContextChange,
    handleReturnToStart,
    handleClearWorkspace,
  } = useWorkspaceState()

  if (hydrating && !activeDataset) return <AppHydratingScreen />

  const openEmpiricalProcedure = (
    procedure: EmpiricalProcedure,
    analysisId?: string,
    runId?: string,
    methodId?: string,
  ) => {
    const definition = procedureDefinition(procedure)
    const storedMethod = methodId ? methodDefinitions.find((entry) => entry.id === methodId) : undefined
    const document = activeDataset && !analysisId
      ? ensureEmpiricalAnalysisDocument(activeDataset, modelContext?.measurement ?? null, procedure, methodId)
      : null
    const method = {
      sliceId: storedMethod?.capabilitySliceIds[0] ?? definition.slice,
      methodId,
      label: storedMethod?.label ?? definition.label,
      contextHash: resolvedContext?.contextHash ?? '',
      key: Date.now(),
      procedure,
    }
    setActiveAnalysisId(analysisId ?? document?.id ?? null)
    setActiveRunRequestId(runId ?? null)
    setEmpiricalTabRequest({ tab: definition.tab, key: method.key, method })
    setAnalysisSurface('empirical')
    setActiveView('analyze')
  }

  const duplicateActiveEmpiricalAnalysis = () => {
    const procedure = empiricalTabRequest?.method?.procedure
    if (!activeDataset || !resolvedContext || !activeAnalysisId || !procedure) return

    const measurement = modelContext?.measurement ?? null
    const source = loadEmpiricalAnalysisIndex(activeDataset, measurement).documents.find(
      (document) => document.id === activeAnalysisId,
    )
    const definition = procedureDefinition(procedure)
    const duplicate = createEmpiricalAnalysisDocument(
      activeDataset,
      measurement,
      procedure,
      `${source?.title ?? definition.label} 副本`,
      source?.methodId,
    )
    cloneEmpiricalDraftToAnalysis(
      activeDataset,
      measurement,
      resolvedContext,
      activeAnalysisId,
      duplicate.id,
      procedure,
    )

    const sourceMethod = source?.methodId
      ? methodDefinitions.find((entry) => entry.id === source.methodId)
      : undefined
    const method = {
      sliceId: sourceMethod?.capabilitySliceIds[0] ?? empiricalTabRequest.method?.sliceId ?? definition.slice,
      methodId: source?.methodId,
      label: sourceMethod?.label ?? empiricalTabRequest.method?.label ?? definition.label,
      contextHash: resolvedContext.contextHash,
      key: Date.now(),
      procedure,
    }
    setActiveRunRequestId(null)
    setActiveAnalysisId(duplicate.id)
    setEmpiricalTabRequest({ tab: definition.tab, key: method.key, method })
  }

  return (
    <div className="app-shell">
      {studyIntent === 'analyze' ? (
        <a className="skip-link" href={`#workspace-panel-${activeView}`}>跳到主要工作区</a>
      ) : null}
      <header className="app-header">
        <div>
          <p className="brand">研径 <span>ResearchPath</span></p>
          <p className="project-name">{activeDataset?.originalFile.name ?? '本地实证研究工作台'}</p>
        </div>
        <div className="header-meta">
          <button
            type="button"
            className="theme-toggle-button"
            onClick={() => setTheme((t) => (t === 'light' ? 'dark' : 'light'))}
          >
            <span>{theme === 'dark' ? '暗色模式' : '明亮模式'}</span>
          </button>
          {studyIntent === 'analyze' ? (
            <button type="button" className="command-palette-trigger" onClick={() => setIsCommandPaletteOpen(true)}>
              <span>搜索 / 命令</span>
              <kbd>Ctrl+K</kbd>
            </button>
          ) : null}
          {studyIntent ? <button type="button" className="header-path-button" onClick={handleReturnToStart}>项目首页</button> : null}
          <LocalPrivacyBadge datasetName={activeDataset?.originalFile.name} datasetSha256={activeDataset?.originalFile.sha256} />
        </div>
      </header>

      {studyIntent === null ? (
        <main className="start-shell">
          <ResearchStart onSelect={handleIntentSelect} />
        </main>
      ) : null}

      {studyIntent === 'plan' ? (
        <Suspense fallback={<main className="centered-state" aria-live="polite"><p>正在加载规划工具…</p></main>}>
          <SectionErrorBoundary resetKey="planning-view" title="功效与研究规划">
            <PlanningWorkspace
              context={effectiveStudyContext}
              onContextChange={handleStudyContextChange}
              datasetId={activeDataset?.id}
              datasetVariables={activeDataset?.variables}
            />
          </SectionErrorBoundary>
        </Suspense>
      ) : null}

      {studyIntent === 'analyze' ? (
        <section className="context-banner">
          <StudyContextSwitcher
            value={effectiveStudyContext}
            hasDataset={Boolean(activeDataset)}
            persistence={studyContextPersistence}
            onChange={handleStudyContextChange}
          />
          {studyContextSaveError ? <p className="context-save-error" role="alert">{studyContextSaveError}</p> : null}
        </section>
      ) : null}

      {studyIntent === 'analyze' ? (
        <AppWorkspaceTabs
          navRef={workspaceNavRef}
          workspaceSteps={workspaceSteps}
          activeView={activeView}
          onSelect={(view) => {
            setActiveView(view)
            if (view === 'analyze') {
              setAnalysisSurface('library')
              setActiveAnalysisId(null)
              setActiveRunRequestId(null)
            }
          }}
        />
      ) : null}

      {studyIntent === 'analyze' ? (
        <div
          role="tabpanel"
          id={`workspace-panel-${activeView}`}
          aria-labelledby={`workspace-tab-${activeView}`}
          tabIndex={-1}
        >
          <Suspense fallback={<main className="centered-state" aria-live="polite"><p>正在加载工作区…</p></main>}>
            {activeView === 'data' ? (
              <SectionErrorBoundary resetKey="data-view" title="数据">
                <DataWorkspace
                  activeDataset={activeDataset}
                  activeMeasurement={modelContext?.measurement}
                  onDatasetReady={handleDatasetReady}
                  onClearWorkspace={() => {
                    const cleared = handleClearWorkspace()
                    if (cleared) {
                      setModelMethodRequest(null)
                      setActiveAnalysisId(null)
                      setActiveRunRequestId(null)
                      setAnalysisSurface('library')
                    }
                    return cleared
                  }}
                  onMeasurementReady={handleMeasurementReady}
                  onStructureSaved={handleStructureSaved}
                  onContinueToAnalysis={() => {
                    setActiveAnalysisId(null)
                    setActiveRunRequestId(null)
                    setAnalysisSurface('library')
                    setActiveView('analyze')
                  }}
                  onLoadDemo={handleLoadDemo}
                  loadingDemo={loadingDemo}
                  studyContext={effectiveStudyContext}
                  resolvedContext={resolvedContext}
                />
              </SectionErrorBoundary>
            ) : activeView === 'analyze' && !activeDataset ? (
              <main className="centered-state">
                <h2>请先导入数据</h2>
                <p>有活动数据后即可进入统一方法库；不需要先完成全部变量、量表或研究结构确认。</p>
                <button type="button" className="secondary-button" onClick={() => setActiveView('data')}>返回数据</button>
              </main>
            ) : activeView === 'analyze' && analysisSurface === 'empirical' && activeDataset && resolvedContext ? (
              <SectionErrorBoundary resetKey="empirical-view" title="分析">
                <div className="analysis-shell">
                  <div className="analysis-inline-actions">
                    <button type="button" className="secondary-button" onClick={() => {
                      setActiveAnalysisId(null)
                      setActiveRunRequestId(null)
                      setAnalysisSurface('library')
                    }}>← 返回方法库</button>
                    {activeAnalysisId && empiricalTabRequest?.method?.procedure ? (
                      <button type="button" className="secondary-button" onClick={duplicateActiveEmpiricalAnalysis}>复制分析</button>
                    ) : null}
                  </div>
                  <EmpiricalAnalysis
                    key={`${activeDataset.id}:${activeDataset.dictionary.version}:${modelContext?.measurement.version ?? 'raw'}:${resolvedContext.contextHash}:${activeAnalysisId ?? 'unscoped'}:${activeRunRequestId ?? 'current'}`}
                    dataset={activeDataset}
                    measurement={modelContext?.measurement ?? null}
                    researchParadigm={researchParadigm}
                    analysisContext={resolvedContext}
                    tabRequest={empiricalTabRequest ?? undefined}
                    analysisId={activeAnalysisId}
                    analysisProcedure={empiricalTabRequest?.method?.procedure}
                    initialRunId={activeRunRequestId}
                  />
                </div>
              </SectionErrorBoundary>
            ) : activeView === 'analyze' && analysisSurface === 'model' && modelContext && resolvedContext ? (
              <SectionErrorBoundary resetKey="model-view" title="高级模型编辑器">
                <div className="analysis-shell">
                  <button type="button" className="secondary-button" onClick={() => setAnalysisSurface('library')}>← 返回方法库</button>
                  <ModelBuilder
                    dataset={modelContext.dataset}
                    measurement={modelContext.measurement}
                    analysisContext={resolvedContext}
                    methodRequest={modelMethodRequest}
                    onMethodHandled={() => setModelMethodRequest(null)}
                  />
                </div>
              </SectionErrorBoundary>
            ) : activeView === 'analyze' && analysisSurface === 'model' && activeDataset ? (
              <main className="centered-state">
                <h2>该模型还需要量表/测量设置</h2>
                <p>高级 PROCESS/SEM 编辑器继续保留，但只在满足当前模型实际前提后打开。你可以先回方法库选择无需量表的分析。</p>
                <button type="button" className="secondary-button" onClick={() => setAnalysisSurface('library')}>返回方法库</button>
              </main>
            ) : activeView === 'analyze' && activeDataset && resolvedContext ? (
              <SectionErrorBoundary resetKey="context-methods-view" title="分析方法库">
                <ContextCapabilityCatalog
                  context={resolvedContext}
                  variables={activeDataset.variables}
                  onPrepare={() => setActiveView('data')}
                  onNavigate={({ view, tab, sliceId, methodId, label, procedure, processModelNumber, processMediatorCount }) => {
                    const method = {
                      sliceId,
                      methodId,
                      label,
                      contextHash: resolvedContext.contextHash,
                      key: Date.now(),
                      procedure,
                      processModelNumber,
                      processMediatorCount,
                    }
                    if (view === 'model') {
                      setActiveAnalysisId(null)
                      setActiveRunRequestId(null)
                      setModelMethodRequest(method)
                      setAnalysisSurface('model')
                    } else {
                      const document = procedure
                        ? ensureEmpiricalAnalysisDocument(activeDataset, modelContext?.measurement ?? null, procedure, methodId)
                        : null
                      setActiveAnalysisId(document?.id ?? null)
                      setActiveRunRequestId(null)
                      setAnalysisSurface('empirical')
                    }
                    if (tab) setEmpiricalTabRequest({ tab, key: method.key, method })
                  }}
                />
              </SectionErrorBoundary>
            ) : activeView === 'analyze' && activeDataset ? (
              <main className="centered-state" aria-live="polite">
                <h2>分析方法库正在准备</h2>
                <p>{resolvedContextQuery.isError ? '当前分析上下文读取失败。你仍可返回数据查看或修改当前数据结构。' : '正在读取当前数据的最小分析条件…'}</p>
                <button type="button" className="secondary-button" onClick={() => setActiveView('data')}>查看数据</button>
              </main>
            ) : activeView === 'output' && activeDataset ? (
              <SectionErrorBoundary resetKey="output-view" title="输出">
                <OutputWorkspace dataset={activeDataset} measurement={modelContext?.measurement ?? null} onOpenProcedure={openEmpiricalProcedure} />
              </SectionErrorBoundary>
            ) : activeView === 'output' ? (
              <main className="centered-state">
                <h2>还没有活动数据</h2>
                <p>导入数据并运行分析后，结果会集中显示在输出工作区。</p>
                <button type="button" className="secondary-button" onClick={() => setActiveView('data')}>导入数据</button>
              </main>
            ) : null}
          </Suspense>
        </div>
      ) : null}

      {studyIntent === 'analyze' ? (
        <CommandPalette
          isOpen={isCommandPaletteOpen}
          onClose={() => setIsCommandPaletteOpen(false)}
          onSelectView={(view) => {
            setActiveView(view)
            if (view === 'analyze') {
              setActiveAnalysisId(null)
              setActiveRunRequestId(null)
              setAnalysisSurface('library')
            }
          }}
          onLoadDemo={handleLoadDemo}
          variables={
            modelContext?.measurement?.constructs.flatMap((construct) =>
              construct.itemIds.map((itemId) => ({ id: itemId, label: itemId })),
            ) ?? activeDataset?.variables?.map((v) => ({ id: v.id, label: v.label })) ?? []
          }
        />
      ) : null}
      <ToastContainer />
    </div>
  )
}
