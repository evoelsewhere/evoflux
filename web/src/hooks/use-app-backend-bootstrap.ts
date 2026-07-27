import { useEffect, useState } from 'react'
import { installDesktopAuth } from '@/api/auth'
import { onApiBaseUrlChange, setApiBaseUrl } from '@/api/base-url'
import { getAppBackendStatus, isTauriContext } from '@/lib/app-backend'
import { queryClient } from '@/lib/query-client'

// The bundled sidecar takes a few seconds to boot (CPython + handshake +
// health poll, and potentially much longer on a cold Windows install). While it boots the Tauri shell
// reports an empty base_url — the app must keep showing the splash screen
// instead of rendering with a dead backend and popping a connection error.
// Keep this above Rust's 120s handshake budget so native startup gets to emit
// backend-ready/backend-error before the UI falls back to its error screen.
const SIDECAR_BOOT_TIMEOUT_MS = 150_000
const STATUS_POLL_INTERVAL_MS = 1_000

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

export function useAppBackendBootstrap(): boolean {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    let finished = false
    let pollTimer: ReturnType<typeof setInterval> | undefined
    let bootTimeout: ReturnType<typeof setTimeout> | undefined
    const unlisteners: Array<() => void> = []

    const finish = () => {
      if (cancelled || finished) return
      finished = true
      if (pollTimer) clearInterval(pollTimer)
      if (bootTimeout) clearTimeout(bootTimeout)
      setReady(true)
    }

    const startPolling = () => {
      if (cancelled || finished || pollTimer) return
      pollTimer = setInterval(() => {
        void getAppBackendStatus().then((status) => {
          if (cancelled || !status?.base_url) return
          applyBackend(status.base_url, status.token)
          finish()
        })
      }, STATUS_POLL_INTERVAL_MS)
      bootTimeout = setTimeout(finish, SIDECAR_BOOT_TIMEOUT_MS)
    }

    if (!isTauriContext()) {
      finish()
    } else {
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
        // Sidecar failed to start — render the app so the existing
        // "Backend connection failed" dialog offers Retry / Configure.
        void listen('backend-error', () => finish()).then((unlisten) => {
          if (cancelled) unlisten()
          else unlisteners.push(unlisten)
        }).catch(() => {})
      }).catch(() => {})

      void getAppBackendStatus().then((status) => {
        if (cancelled) return
        if (status?.base_url) {
          applyBackend(status.base_url, status.token)
          finish()
          return
        }
        // A null status inside Tauri can be a transient IPC failure during
        // first-window startup. Keep waiting instead of treating it as a
        // browser runtime and rendering against an unavailable backend.
        startPolling()
      })
    }

    const unsubscribe = onApiBaseUrlChange(() => {
      queryClient.clear()
    })
    return () => {
      cancelled = true
      if (pollTimer) clearInterval(pollTimer)
      if (bootTimeout) clearTimeout(bootTimeout)
      for (const unlisten of unlisteners) unlisten()
      unsubscribe()
    }
  }, [])

  return ready
}
