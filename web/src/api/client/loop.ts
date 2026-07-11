/**
 * EvoFlux API client — loop group: /loop/config.
 */

import { apiBaseUrl } from '../base-url'

export interface LoopConfig {
  default_max_iterations: number
  default_evolve_prompt: boolean
  default_verify_command: string
  default_max_total_tokens: number | null
  default_no_progress_threshold: number
  default_max_consecutive_errors: number
  default_delay_between_iterations: number
}

export async function getLoopConfig(): Promise<LoopConfig> {
  const res = await fetch(`${apiBaseUrl()}/loop/config`)
  if (!res.ok) throw new Error(`GET /loop/config failed: ${res.status}`)
  return res.json()
}

export async function putLoopConfig(config: LoopConfig): Promise<LoopConfig> {
  const res = await fetch(`${apiBaseUrl()}/loop/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`PUT /loop/config failed: ${res.status} ${detail}`)
  }
  return res.json()
}
