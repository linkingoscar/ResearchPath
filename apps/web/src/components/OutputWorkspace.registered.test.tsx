import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { DatasetVersion } from '../types'
import { registerOutputRun } from './analyses/outputRunRegistry'
import { OutputWorkspace } from './OutputWorkspace'

const indexMocks = vi.hoisted(() => ({
  getServerAnalysisIndex: vi.fn(),
  registerServerAnalysisRun: vi.fn(),
  upsertServerAnalysisDocument: vi.fn(),
  patchServerAnalysisDocument: vi.fn(),
}))
const outputMocks = vi.hoisted(() => ({
  registeredDetail: vi.fn(),
}))

vi.mock('../api/analysis-index', () => indexMocks)
vi.mock('./analyses/useOutputRunJobs', () => ({ useOutputRunJobs: () => new Map() }))
vi.mock('./OutputRegisteredRunDetail', () => ({
  OutputRegisteredRunDetail: (props: {
    run: { runId: string }
    isPrimary: boolean
    onTogglePrimary?: () => void
  }) => {
    outputMocks.registeredDetail(props)
    return <button type="button" onClick={props.onTogglePrimary}>toggle-primary:{props.run.runId}</button>
  },
}))

const dataset = {
  id: 'dataset_current',
  projectId: 'project_demo',
  originalFile: { name: 'demo.csv' },
  dictionary: { version: 1 },
} as DatasetVersion

function renderOutput() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <OutputWorkspace dataset={dataset} measurement={null} onOpenProcedure={vi.fn()} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  indexMocks.getServerAnalysisIndex.mockResolvedValue({
    schemaVersion: '1.0.0',
    projectId: dataset.projectId,
    documents: [],
    runs: [],
    rebuiltFromServerJobs: true,
  })
  indexMocks.registerServerAnalysisRun.mockResolvedValue({})
  indexMocks.patchServerAnalysisDocument.mockResolvedValue({})
})

describe('OutputWorkspace registered model and advanced runs', () => {
  it('shows project-level model and advanced run references even without empirical documents', () => {
    registerOutputRun({
      runId: 'run_process_1',
      projectId: dataset.projectId,
      datasetVersionId: dataset.id,
      measurementVersionId: null,
      source: 'model',
      label: '简单中介（PROCESS Model 4）',
      methodId: 'model.process',
      modelId: 'model_demo',
      createdAt: '2026-09-03T10:00:00Z',
    })
    registerOutputRun({
      runId: 'run_anova_1',
      projectId: dataset.projectId,
      datasetVersionId: 'dataset_old',
      measurementVersionId: null,
      source: 'advanced',
      label: '组间析因方差分析',
      methodId: 'experimental_design.factorial_anova.long.single_outcome',
      family: 'experimental_design',
      createdAt: '2026-09-03T11:00:00Z',
    })

    renderOutput()

    expect(screen.getByRole('heading', { name: '输出索引' })).toBeInTheDocument()
    expect(screen.getByText('简单中介（PROCESS Model 4）')).toBeInTheDocument()
    expect(screen.getByText('组间析因方差分析')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '还没有运行任何分析' })).not.toBeInTheDocument()
    expect(screen.getAllByText('基于非当前设置')).toHaveLength(1)
  })

  it('searches registered runs together with the project output index', () => {
    registerOutputRun({
      runId: 'run_sem_1',
      projectId: dataset.projectId,
      datasetVersionId: dataset.id,
      measurementVersionId: null,
      source: 'model',
      label: '结构方程模型（SEM）',
      methodId: 'model.sem',
      modelId: 'model_sem',
      createdAt: '2026-09-03T10:00:00Z',
    })
    registerOutputRun({
      runId: 'run_lmm_1',
      projectId: dataset.projectId,
      datasetVersionId: dataset.id,
      measurementVersionId: null,
      source: 'advanced',
      label: '两层 Gaussian LMM',
      methodId: 'multilevel_model.gaussian.two_level',
      family: 'multilevel_model',
      createdAt: '2026-09-03T11:00:00Z',
    })

    renderOutput()
    fireEvent.change(screen.getByLabelText('搜索输出'), { target: { value: 'LMM' } })

    expect(screen.getByText('两层 Gaussian LMM')).toBeInTheDocument()
    expect(screen.queryByText('结构方程模型（SEM）')).not.toBeInTheDocument()
    expect(screen.getByText('显示 1 / 2 项输出')).toBeInTheDocument()
  })

  it('groups repeated model runs and persists document metadata and a primary run', () => {
    const firstIndex = registerOutputRun({
      runId: 'run_process_1',
      projectId: dataset.projectId,
      datasetVersionId: dataset.id,
      measurementVersionId: null,
      source: 'model',
      label: '简单中介（PROCESS Model 4）',
      methodId: 'model.process',
      modelId: 'model_same',
      createdAt: '2026-09-03T10:00:00Z',
    })
    registerOutputRun({
      runId: 'run_process_2',
      projectId: dataset.projectId,
      datasetVersionId: dataset.id,
      measurementVersionId: null,
      source: 'model',
      label: '简单中介（PROCESS Model 4）',
      methodId: 'model.process',
      modelId: 'model_same',
      createdAt: '2026-09-03T11:00:00Z',
    })
    const analysisId = firstIndex[0].analysisId
    vi.spyOn(window, 'prompt').mockReturnValue('核心中介模型')

    renderOutput()

    expect(screen.getByText(/项模型\/高级分析/)).toHaveTextContent('1 项模型/高级分析')
    expect(screen.getAllByText(/2 次运行/)).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: '固定分析' }))
    expect(indexMocks.patchServerAnalysisDocument).toHaveBeenCalledWith(
      dataset.projectId,
      analysisId,
      { pinned: true },
    )

    fireEvent.click(screen.getByRole('button', { name: '重命名' }))
    expect(indexMocks.patchServerAnalysisDocument).toHaveBeenCalledWith(
      dataset.projectId,
      analysisId,
      { title: '核心中介模型' },
    )

    fireEvent.click(screen.getByText('查看运行历史'))
    fireEvent.click(screen.getAllByRole('button', { name: /run_process_/ })[0])
    fireEvent.click(screen.getByRole('button', { name: /toggle-primary/ }))
    expect(indexMocks.patchServerAnalysisDocument).toHaveBeenCalledWith(
      dataset.projectId,
      analysisId,
      expect.objectContaining({ primaryRunId: expect.stringMatching(/^run_process_/) }),
    )
  })

  it('rolls back optimistic registered-document metadata when the server rejects it', async () => {
    registerOutputRun({
      runId: 'run_sem_failed_patch',
      projectId: dataset.projectId,
      datasetVersionId: dataset.id,
      measurementVersionId: null,
      source: 'model',
      label: '结构方程模型（SEM）',
      methodId: 'model.sem',
      modelId: 'model_failed_patch',
      createdAt: '2026-09-03T10:00:00Z',
    })
    indexMocks.patchServerAnalysisDocument.mockRejectedValue(new Error('offline'))

    renderOutput()
    fireEvent.click(screen.getByRole('button', { name: '固定分析' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('保存失败')
    expect(screen.getByRole('button', { name: '固定分析' })).toBeInTheDocument()
    expect(screen.queryByText('已固定')).not.toBeInTheDocument()
  })
})
