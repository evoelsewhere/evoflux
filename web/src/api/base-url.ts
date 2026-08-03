declare global {
  interface Window {
    __OAD_API_BASE_URL__?: string
    __OAD_BACKEND_UNAVAILABLE__?: boolean
  }
}

const listeners = new Set<() => void>()

function normalizeBaseUrl(value: string | undefined): string {
  const trimmed = value?.trim()
  if (!trimmed) return '/api'
  const withoutTrailingSlash = trimmed.replace(/\/+$/, '')
  return withoutTrailingSlash.endsWith('/api')
    ? withoutTrailingSlash
    : `${withoutTrailingSlash}/api`
}

export function apiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    if (window.__OAD_BACKEND_UNAVAILABLE__) return 'oad-backend-unavailable://api'
    if (window.__OAD_API_BASE_URL__) return normalizeBaseUrl(window.__OAD_API_BASE_URL__)
  }
  return normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL)
}

export function setApiBaseUrl(baseUrl: string): void {
  if (typeof window === 'undefined') return
  const previous = apiBaseUrl()
  Object.defineProperty(window, '__OAD_BACKEND_UNAVAILABLE__', {
    value: false,
    writable: true,
    configurable: true,
  })
  Object.defineProperty(window, '__OAD_API_BASE_URL__', {
    value: baseUrl,
    writable: true,
    configurable: true,
  })
  if (apiBaseUrl() === previous) return
  for (const listener of listeners) listener()
}

export function onApiBaseUrlChange(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function apiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${apiBaseUrl()}${normalizedPath}`
}

/**
 * WebSocket counterpart of `apiBaseUrl()`.
 *
 * When the API base is relative (`/api`) the socket must stay same-origin so
 * the Vite dev proxy, the packaged desktop server, and any HTTPS deployment all
 * resolve to whatever port is actually serving the page. Hardcoding a port here
 * breaks as soon as the backend is not on its default one.
 */
export function apiWsBaseUrl(): string {
  const base = apiBaseUrl()
  if (/^https?:/i.test(base)) return base.replace(/^http/i, 'ws')
  if (!base.startsWith('/')) return base.replace(/^[a-z0-9.+-]+:/i, 'ws:')
  if (typeof window === 'undefined') return `ws://127.0.0.1:4082${base}`
  const { protocol, host } = window.location
  return `${protocol === 'https:' ? 'wss:' : 'ws:'}//${host}${base}`
}
