import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'

const TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'cancelled'])

/**
 * 任务进度订阅：SSE 作为快速通知通道，GET job status 作为权威状态。
 *
 * - SSE 正常时只收推送；断连后立即启动低频率轮询兜底，同时按指数退避重连 SSE；
 * - 重连成功后停止轮询；任务进入终态时全部停止；
 * - 状态统一写入 react-query（queryKey = [...prefix, runId]），
 *   组件与 GET 查询共用同一份数据，不复制状态到组件本地。
 */
export function useJobProgress(runId: string | null, queryKeyPrefix: string[] = ['analysis-job']) {
  const queryClient = useQueryClient()
  const prefixKey = queryKeyPrefix.join(',')

  useEffect(() => {
    if (!runId) return undefined
    const jobKey = [...prefixKey.split(',').filter(Boolean), runId]
    let closed = false
    let eventSource: EventSource | null = null
    let pollingTimer: number | null = null
    let reconnectAttempts = 0

    const stopPolling = () => {
      if (pollingTimer !== null) {
        window.clearInterval(pollingTimer)
        pollingTimer = null
      }
    }
    const stop = () => {
      closed = true
      stopPolling()
      eventSource?.close()
      eventSource = null
    }

    const connect = () => {
      if (closed) return
      eventSource = new EventSource(`/api/v1/analyses/${runId}/progress`)
      eventSource.onmessage = (event) => {
        try {
          const job = JSON.parse(event.data) as { status?: string }
          // SSE 事件只携带白名单字段；合并保留 GET 查询带来的完整字段（error 文案等）。
          queryClient.setQueryData(jobKey, (current) => ({ ...(current ?? {}), ...job }))
          // SSE 再次活跃：fallback 轮询必须停止，同一时刻只允许一个 transport。
          stopPolling()
          if (TERMINAL_STATUSES.has(String(job.status))) {
            stop()
            return
          }
          reconnectAttempts = 0
        } catch {
          // 畸形事件直接忽略；轮询兜底仍活跃。
        }
      }
      eventSource.onerror = () => {
        eventSource?.close()
        eventSource = null
        if (closed) return
        if (pollingTimer === null) {
          pollingTimer = window.setInterval(() => {
            void queryClient.invalidateQueries({ queryKey: jobKey })
          }, 2000)
        }
        const delay = Math.min(1000 * 2 ** reconnectAttempts, 8000)
        reconnectAttempts += 1
        window.setTimeout(connect, delay)
      }
    }

    connect()
    return stop
  }, [runId, queryClient, prefixKey])
}
