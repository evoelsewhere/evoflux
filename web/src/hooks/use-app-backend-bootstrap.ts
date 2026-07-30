import { useEffect, useState } from 'react'
import { installDesktopAuth } from '@/api/auth'
import { onApiBaseUrlChange, setApiBaseUrl } from '@/api/base-url'
import {
  type BackendStartupStatus,
  getAppBackendStatus,
  isTauriContext,
  retryAppBackend,
  revealAppBackendLog,
} from '@/lib/app-backend'
import { queryClient } from '@/lib/query-client'

const SIDECAR_BOOT_TIMEOUT_MS = 210_000
const STATUS_POLL_INTERVAL_MS = 1_000

const INITIAL_STATUS: BackendStartupStatus = {
  phase: 'preparing',
  message: 'Preparing the local engine…',
  attempt: 0,
  max_attempts: 3,
  elapsed_ms: 0,
  error: null,
  fatal: false,
}

interface BackendErrorPayload {
  message: string
  fatal: boolean
  attempt: number
  max_attempts: number
}

export interface AppBackendBootstrap {
  ready: boolean
  startup: BackendStartupStatus
  retry: () => Promise<void>
  revealLog: () => Promise<void>
}

function applyBackend(baseUrl: string, token?: string | null): void {
  if (token) {
    Object.defineProperty(window, '__OAD_TOKEN__', {
      value: token,
      writable: true,
      configurable: true,
    })
    installDesktopAuth()
  }
  setApiBaseUrl(baseUrl)
}

export function useAppBackendBootstrap(): AppBackendBootstrap {
  const [ready, setReady] = useState(false)
  const [startup, setStartup] = useState<BackendStartupStatus>(INITIAL_STATUS)

  useEffect(() => {
    let cancelled = false
    let finished = false
    let pollTimer: ReturnType<typeof setInterval> | undefined
    let elapsedTimer: ReturnType<typeof setInterval> | undefined
    let bootTimeout: ReturnType<typeof setTimeout> | undefined
    const unlisteners: Array<() => void> = []
    const mountedAt = Date.now()

    const finish = () => {
      if (cancelled || finished) return
      finished = true
      if (pollTimer) clearInterval(pollTimer)
      if (elapsedTimer) clearInterval(elapsedTimer)
      if (bootTimeout) clearTimeout(bootTimeout)
      setReady(true)
    }

    const applyStatus = (status: BackendStartupStatus) => {
      if (cancelled || finished) return
      setStartup(status)
    }

    const pollStatus = () => {
      void getAppBackendStatus().then((status) => {
        if (cancelled || finished || !status) return
        if (status.startup) applyStatus(status.startup)
        if (!status.base_url) return
        applyBackend(status.base_url, status.token)
        finish()
      })
    }

    const startWaiting = () => {
      if (cancelled || finished || pollTimer) return
      pollTimer = setInterval(pollStatus, STATUS_POLL_INTERVAL_MS)
      elapsedTimer = setInterval(() => {
        setStartup((current) => ({
          ...current,
          elapsed_ms: Math.max(current.elapsed_ms, Date.now() - mountedAt),
        }))
      }, STATUS_POLL_INTERVAL_MS)
      bootTimeout = setTimeout(() => {
        setStartup((current) => ({
          ...current,
          phase: 'error',
          message: 'The local engine is taking longer than expected.',
          error: current.error || 'Startup exceeded 210 seconds. You can retry or inspect the backend log.',
          fatal: false,
        }))
      }, SIDECAR_BOOT_TIMEOUT_MS)
    }

    if (!isTauriContext()) {
      finish()
    } else {
      startWaiting()
      void import('@tauri-apps/api/event').then(({ listen }) => {
        if (cancelled) return
        void listen<{ base_url: string; token?: string | null }>('backend-ready', (event) => {
          if (cancelled || !event.payload.base_url) return
          applyBackend(event.payload.base_url, event.payload.token)
          finish()
        }).then((unlisten) => {
          if (cancelled) unlisten()
          else unlisteners.push(unlisten)
        }).catch(() => {})
        void listen<BackendStartupStatus>('backend-progress', (event) => {
          applyStatus(event.payload)
        }).then((unlisten) => {
          if (cancelled) unlisten()
          else unlisteners.push(unlisten)
        }).catch(() => {})
        // Keep the splash mounted after an error. Native startup may still
        // recover, and status polling catches a late backend-ready event.
        void listen<BackendErrorPayload>('backend-error', (event) => {
          applyStatus({
            phase: 'error',
            message: event.payload.fatal
              ? 'The local engine needs attention.'
              : 'The local engine could not start.',
            attempt: event.payload.attempt,
            max_attempts: event.payload.max_attempts,
            elapsed_ms: Date.now() - mountedAt,
            error: event.payload.message,
            fatal: event.payload.fatal,
          })
        }).then((unlisten) => {
          if (cancelled) unlisten()
          else unlisteners.push(unlisten)
        }).catch(() => {})
      }).catch(() => {})

      pollStatus()
    }

    const unsubscribe = onApiBaseUrlChange(() => {
      queryClient.clear()
    })
    return () => {
      cancelled = true
      if (pollTimer) clearInterval(pollTimer)
      if (elapsedTimer) clearInterval(elapsedTimer)
      if (bootTimeout) clearTimeout(bootTimeout)
      for (const unlisten of unlisteners) unlisten()
      unsubscribe()
    }
  }, [])

  const retry = async () => {
    setStartup((current) => ({
      ...current,
      phase: 'launching',
      message: 'Restarting the local engine…',
      error: null,
      fatal: false,
    }))
    try {
      await retryAppBackend()
    } catch (error) {
      setStartup((current) => ({
        ...current,
        phase: 'error',
        message: 'Could not request an engine restart.',
        error: error instanceof Error ? error.message : String(error),
        fatal: false,
      }))
    }
  }

  return {
    ready,
    startup,
    retry,
    revealLog: revealAppBackendLog,
  }
}
