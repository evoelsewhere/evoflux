/**
 * Shared internals for the API client domain modules: the validation
 * error type and the response-detail parser used across every group.
 */

export class ApiValidationError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiValidationError'
  }
}

const DEFAULT_API_TIMEOUT_MS = 10_000

/** Forward caller cancellation and cap local API waits at a finite timeout. */
export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs = DEFAULT_API_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController()
  const upstream = init.signal
  const abortFromUpstream = () => controller.abort(upstream?.reason)
  if (upstream?.aborted) abortFromUpstream()
  else upstream?.addEventListener('abort', abortFromUpstream, { once: true })
  const timeout = globalThis.setTimeout(
    () => controller.abort(new DOMException('API request timed out', 'TimeoutError')),
    timeoutMs,
  )
  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } finally {
    globalThis.clearTimeout(timeout)
    upstream?.removeEventListener('abort', abortFromUpstream)
  }
}

export async function parseDetailOrThrow(res: Response, label: string): Promise<never> {
  let detail = `${label} failed: ${res.status}`
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') detail = body.detail
    else if (Array.isArray(body?.detail)) detail = body.detail.map((e: { msg: string }) => e.msg).join('; ')
  } catch {
    // Non-JSON body — keep the fallback.
  }
  throw new ApiValidationError(res.status, detail)
}

// ── /agents ──────────────────────────────────────────────────────────────────
