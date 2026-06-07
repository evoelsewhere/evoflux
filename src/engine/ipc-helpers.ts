export async function withRetry<T>(
  fn: () => Promise<T>,
  options: { maxRetries?: number; delayMs?: number; backoff?: boolean; signal?: AbortSignal } = {}
): Promise<T> {
  const { maxRetries = 3, delayMs = 1000, backoff = true, signal } = options
  const retries = Math.max(0, maxRetries)
  let lastError: Error | undefined

  for (let attempt = 0; attempt <= retries; attempt++) {
    if (signal?.aborted) {
      throw lastError ?? new Error('Operation aborted')
    }
    try {
      return await fn()
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error))
      if (attempt < retries) {
        const delay = backoff ? delayMs * Math.pow(2, attempt) : delayMs
        await new Promise((resolve, reject) => {
          const timer = setTimeout(resolve, delay)
          signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new Error('Aborted')) }, { once: true })
        })
      }
    }
  }

  throw lastError!
}

export function isRetryableError(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  const msg = error.message.toLowerCase()
  return /\b(timeout|timed?\s*out|econnrefused|econnreset|etimedout|rate\s*limit|network\s*error)\b/.test(msg)
}

export function wrapIPCError(error: unknown, context: string): Error {
  const message = error instanceof Error ? error.message : String(error)
  const wrapped = new Error(`${context}: ${message}`)
  if (error instanceof Error) {
    wrapped.cause = error
  }
  return wrapped
}
