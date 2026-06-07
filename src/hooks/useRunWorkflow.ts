import { useState, useCallback, useEffect } from 'react'
import type { RunEvent } from '../components/workflow/RunMonitor'

interface RunWorkflowOptions {
  dsl: unknown
  inputs?: Record<string, unknown>
  maxSteps?: number
  maxTimeMs?: number
}

interface RunWorkflowResult {
  success: boolean
  results?: unknown[]
  error?: string
}

export function useRunWorkflow() {
  const [isRunning, setIsRunning] = useState(false)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [result, setResult] = useState<RunWorkflowResult | null>(null)

  useEffect(() => {
    const unsubscribe = window.api.workflow.onEvent?.((event: unknown) => {
      const e = event as RunEvent
      setEvents(prev => [...prev, e])

      if (e.type === 'graph:complete' || e.type === 'graph:error' || e.type === 'graph:aborted') {
        setIsRunning(false)
      }
    })

    return () => { unsubscribe?.() }
  }, [])

  const run = useCallback(async (options: RunWorkflowOptions) => {
    setIsRunning(true)
    setEvents([])
    setResult(null)

    try {
      const res = await window.api.workflow.run(options.dsl, {
        inputs: options.inputs,
        maxSteps: options.maxSteps,
        maxTimeMs: options.maxTimeMs
      })
      setResult(res)
      return res
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Run failed'
      const failResult = { success: false, error: message }
      setResult(failResult)
      return failResult
    } finally {
      setIsRunning(false)
    }
  }, [])

  const stop = useCallback(async () => {
    try {
      await window.api.workflow.stop()
    } catch {
      // Best effort
    }
    setIsRunning(false)
  }, [])

  const clearEvents = useCallback(() => {
    setEvents([])
    setResult(null)
  }, [])

  return { isRunning, events, result, run, stop, clearEvents }
}
