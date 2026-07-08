import { useEffect, useState } from 'react'
import { installDesktopAuth } from '@/api/auth'
import { onApiBaseUrlChange, setApiBaseUrl } from '@/api/base-url'
import { getAppBackendStatus } from '@/lib/app-backend'
import { queryClient } from '@/lib/query-client'

// The bundled sidecar takes a few seconds to boot (CPython + handshake +
// health poll, up to ~30s on cold start). While it boots the Tauri shell
// reports an empty base_url — the app must keep showing the splash screen
// instead of rendering with a dead backend and popping a connection error.
// Hard ceiling so a crashed sidecar can't strand the user on the splash:
// after this, render anyway and let the in-app error dialog take over.
const SIDECAR_BOOT_TIMEOUT_MS = 60_000
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
    let pollTimer: ReturnType<typeof setInterval> | undefined
    let bootTimeout: ReturnType<typeof setTimeout> | undefined
    const unlisteners: Array<() => void> = []

    const finish = () => {
      if (cancelled) return
      if (pollTimer) clearInterval(pollTimer)
      if (bootTimeout) clearTimeout(bootTimeout)
      setReady(true)
    }

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
      if (!status) {
        // Not running inside the desktop shell (browser/dev) — nothing to wait for.
        finish()
        return
      }
      if (status.base_url) {
        applyBackend(status.base_url, status.token)
        finish()
        return
      }
      // Desktop shell with the sidecar still booting: stay on the splash
      // screen. The backend-ready event releases it; poll as a safety net
      // for races around listener registration and window reloads.
      pollTimer = setInterval(() => {
        void getAppBackendStatus().then((polled) => {
          if (cancelled || !polled?.base_url) return
          applyBackend(polled.base_url, polled.token)
          finish()
        }).catch(() => {})
      }, STATUS_POLL_INTERVAL_MS)
      bootTimeout = setTimeout(finish, SIDECAR_BOOT_TIMEOUT_MS)
    }).catch(() => {
      if (!cancelled) finish()
    })

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
