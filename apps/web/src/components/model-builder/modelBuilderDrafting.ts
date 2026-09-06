import { useEffect } from 'react'
import { useMutation, useQuery, type UseMutationResult } from '@tanstack/react-query'

import { getModelDraft, saveModelDraft, validateDatasetModel } from '../../api'
import type {
  DatasetVersion,
  ModelDraftVersion,
  ModelSpec,
  ModelValidation,
} from '../../types'
import type { ResolvedAnalysisContext } from '../../types/analysis-context'
import { isModelTemplate } from './modelTemplates'
import type { ModelTemplate } from './modelTemplates'

interface UseModelBuilderDraftingOptions {
  dataset: DatasetVersion
  analysisContext?: ResolvedAnalysisContext | null
  contextModelId: string
  latestModel: { current: ModelSpec }
  setModel: (next: ModelSpec) => void
  setValidation: (next: ModelValidation | null) => void
  setTemplate: (next: ModelTemplate) => void
  setCustomMode: (next: boolean) => void
  setDraftState: (next: 'saving' | 'saved' | 'error') => void
  setBuilderError: (next: string | null) => void
  setDraftHydrated: (next: boolean) => void
}

export function useModelBuilderDrafting({
  dataset,
  analysisContext,
  contextModelId,
  latestModel,
  setModel,
  setValidation,
  setTemplate,
  setCustomMode,
  setDraftState,
  setBuilderError,
  setDraftHydrated,
}: UseModelBuilderDraftingOptions): {
    draftMutation: UseMutationResult<ModelDraftVersion, Error, ModelSpec, unknown>
  } {
  const draftQuery = useQuery({
    queryKey: ['model-draft', dataset.id, contextModelId, analysisContext?.contextHash ?? 'unresolved'],
    queryFn: () => getModelDraft(dataset.id, contextModelId),
    enabled: Boolean(analysisContext?.contextHash),
    retry: false,
    staleTime: Infinity,
    refetchOnMount: 'always',
  })

  useEffect(() => {
    // Re-entering the workbench must hydrate the saved server draft, not an older query cache.
    if (!draftQuery.isFetchedAfterMount) return
    if (draftQuery.isSuccess) {
      const restored = draftQuery.data
      const matchesCurrentContext = Boolean(
        restored
        && analysisContext?.contextHash
        && restored.modelSpec.contextHash === analysisContext.contextHash
        && restored.modelSpec.modelId === contextModelId,
      )
      if (restored && matchesCurrentContext) {
        setModel(restored.modelSpec)
        setValidation(restored.validation)
        const restoredTemplate = restored.validation.template
        if (isModelTemplate(restoredTemplate)) {
          setTemplate(restoredTemplate)
          setCustomMode(restored.modelSpec.name === '自定义 PROCESS 结构')
        } else {
          setCustomMode(restored.modelSpec.name === '自定义 PROCESS 结构' || restored.validation.matchStatus === 'custom')
        }
        setDraftState('saved')
      } else if (restored) {
        setBuilderError('发现非当前上下文的模型草稿；已保留为运行记录，不会混入当前数据。当前模型将按新 contextHash 重新保存。')
      }
      setDraftHydrated(true)
    } else if (draftQuery.isError) {
      setBuilderError(draftQuery.error instanceof Error ? draftQuery.error.message : '草稿加载失败')
      setDraftHydrated(true)
    }
  }, [analysisContext?.contextHash, contextModelId, draftQuery.data, draftQuery.error, draftQuery.isError, draftQuery.isSuccess, draftQuery.isFetchedAfterMount, setBuilderError, setCustomMode, setDraftHydrated, setDraftState, setModel, setTemplate, setValidation])

  const draftMutation = useMutation({
    mutationFn: (submitted: ModelSpec) => saveModelDraft(dataset.id, submitted),
    onSuccess: (draft, submitted) => {
      if (latestModel.current === submitted) {
        setValidation(draft.validation)
        setDraftState('saved')
      }
    },
    onError: () => {
      setDraftState('error')
      setBuilderError('模型草稿未保存：当前上下文可能已变化，请重新确认模型后再保存。')
    },
  })
  const _validationMutation = useMutation({
    mutationFn: (submitted: ModelSpec) => validateDatasetModel(dataset.id, submitted),
    onSuccess: (result, submitted) => {
      if (latestModel.current === submitted) setValidation(result)
    },
  })

  return { draftMutation }
}

interface UseModelBuilderDraftPersistenceOptions {
  draftMutation: UseMutationResult<ModelDraftVersion, Error, ModelSpec, unknown>
  draftHydrated: boolean
  model: ModelSpec
  draftState: 'saving' | 'saved' | 'error'
  setDraftState: (next: 'saving' | 'saved' | 'error') => void
}

export function useModelBuilderDraftPersistence({
  draftMutation,
  draftHydrated,
  model,
  draftState,
  setDraftState,
}: UseModelBuilderDraftPersistenceOptions): void {
  const persistDraft = draftMutation.mutate

  useEffect(() => {
    if (!draftHydrated) return
    setDraftState('saving')
    const timer = window.setTimeout(() => persistDraft(model), 650)
    return () => window.clearTimeout(timer)
  }, [draftHydrated, model, persistDraft, setDraftState])

  useEffect(() => {
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (draftState !== 'saving') return
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [draftState])
}
