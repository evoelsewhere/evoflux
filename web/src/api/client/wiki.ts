/**
 * EvoFlux API client — knowledge group: /wiki + /dream.
 */

import { apiBaseUrl } from '../base-url'
import type {
  WikiTree,
  WikiFile,
} from '../types'

export async function getWikiTree(unprocessedOnly = false): Promise<WikiTree> {
  const url = unprocessedOnly ? `${apiBaseUrl()}/wiki/tree?unprocessed_only=true` : `${apiBaseUrl()}/wiki/tree`
  const res = await fetch(url)
  if (!res.ok) throw new Error(`GET /wiki/tree failed: ${res.status}`)
  return res.json()
}

export async function getWikiFile(path: string): Promise<WikiFile> {
  const res = await fetch(`${apiBaseUrl()}/wiki/file?path=${encodeURIComponent(path)}`)
  if (!res.ok) throw new Error(`GET /wiki/file failed: ${res.status}`)
  return res.json()
}

export async function putWikiFile(path: string, content: string): Promise<WikiFile> {
  const res = await fetch(`${apiBaseUrl()}/wiki/file`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, content }),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`PUT /wiki/file failed: ${res.status} ${detail}`)
  }
  return res.json()
}

export async function deleteWikiFile(path: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/wiki/file?path=${encodeURIComponent(path)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(`DELETE /wiki/file failed: ${res.status}`)
}

// ── /dream ────────────────────────────────────────────────────────────────────

export interface DreamConfig {
  enabled: boolean
  model: string
  schedule: string
}

export async function getDreamConfig(): Promise<DreamConfig> {
  const res = await fetch(`${apiBaseUrl()}/dream/config`)
  if (!res.ok) throw new Error(`GET /dream/config failed: ${res.status}`)
  return res.json()
}

export async function putDreamConfig(config: DreamConfig): Promise<DreamConfig> {
  const res = await fetch(`${apiBaseUrl()}/dream/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`PUT /dream/config failed: ${res.status} ${detail}`)
  }
  return res.json()
}

export interface DreamRunResult {
  sessions_processed: number
  notes_processed: number
  remaining: number
  failed: number
  skipped?: string
}

interface DreamRunStatus {
  running: boolean
  result: DreamRunResult | null
  error: string | null
}

async function getDreamRunStatus(): Promise<DreamRunStatus> {
  const res = await fetch(`${apiBaseUrl()}/dream/run/status`)
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`GET /dream/run/status failed: ${res.status} ${detail}`)
  }
  return res.json()
}

const DREAM_RUN_POLL_INTERVAL_MS = 1200

/**
 * Kick off a dream drain and wait for it to finish.
 *
 * The backend runs the drain (one LLM call per pending session/note, can
 * take minutes) as a background task and returns immediately — this polls
 * ``GET /dream/run/status`` until it completes so callers keep the previous
 * "await and get the final counts" contract without holding the HTTP
 * connection open for the whole drain.
 */
export async function triggerDreamRun(): Promise<DreamRunResult> {
  const res = await fetch(`${apiBaseUrl()}/dream/run`, { method: 'POST' })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`POST /dream/run failed: ${res.status} ${detail}`)
  }
  await res.json() // { status: 'started' | 'already_running' } — polling below covers both.

  for (;;) {
    const status = await getDreamRunStatus()
    if (!status.running) {
      if (status.error) throw new Error(status.error)
      if (status.result) return status.result
    }
    await new Promise((resolve) => setTimeout(resolve, DREAM_RUN_POLL_INTERVAL_MS))
  }
}
