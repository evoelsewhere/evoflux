/**
 * EvoFlux API client — remote-use group: /remote-use.
 *
 * Embedded Tailscale / external Serve phone access. Every route returns the same uniform
 * payload { tailscale, serve, lock }; a second device claiming the lock
 * receives HTTP 409 with { detail, current, live_window_minutes }.
 * Auth is automatic: the embedded proxy verifies peers with WhoIs and the
 * backend attributes sessions from its signed identity headers.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiBaseUrl } from '../base-url'
import { ApiValidationError, parseDetailOrThrow } from './_shared'

// ── /remote-use contract ─────────────────────────────────────────────────────

export interface RemoteUseTailscaleState {
  provider?: 'embedded' | 'external'
  installed: boolean
  logged_in: boolean
  https_certs: boolean | null
  auth_url?: string | null
  error: string | null
}

export interface RemoteUseServeState {
  enabled: boolean
  url: string | null
}

export interface RemoteUseLock {
  user_login: string
  device_label: string
  claimed_at: string
  last_seen_at: string
}

/** Uniform payload returned by GET /status and every POST action. */
export interface RemoteUseStatus {
  tailscale: RemoteUseTailscaleState
  serve: RemoteUseServeState
  lock: RemoteUseLock | null
}

/** HTTP 409 body when another device already holds the remote-use lock. */
export interface RemoteUseLockConflict {
  detail: string
  current: RemoteUseLock
  live_window_minutes: number
}

const UNKNOWN_LOCK: RemoteUseLock = {
  user_login: '',
  device_label: 'another device',
  claimed_at: '',
  last_seen_at: '',
}

/** Thrown for HTTP 409 so callers can render who holds the lock. */
export class RemoteUseLockError extends Error {
  readonly current: RemoteUseLock
  readonly liveWindowMinutes: number

  constructor(conflict: RemoteUseLockConflict) {
    super(conflict.detail)
    this.name = 'RemoteUseLockError'
    this.current = conflict.current
    this.liveWindowMinutes = conflict.live_window_minutes
  }
}

/** Friendly one-liner for any remote-use failure (409s read naturally). */
export function formatRemoteUseError(error: unknown): string {
  if (error instanceof RemoteUseLockError) {
    const device = error.current.device_label || error.current.user_login || 'another device'
    return `device ${device} holds the lock`
  }
  if (error instanceof ApiValidationError) return error.message
  if (error instanceof Error && error.message) return error.message
  return 'Remote access request failed. Please try again.'
}

async function readLockConflict(res: Response): Promise<RemoteUseLockError> {
  try {
    const body = (await res.json()) as Partial<RemoteUseLockConflict>
    if (typeof body?.detail === 'string' && body.current && typeof body.current === 'object') {
      return new RemoteUseLockError({
        detail: body.detail,
        current: { ...UNKNOWN_LOCK, ...body.current },
        live_window_minutes: typeof body.live_window_minutes === 'number' ? body.live_window_minutes : 0,
      })
    }
  } catch {
    // Unreadable body — fall through to the generic conflict below.
  }
  return new RemoteUseLockError({
    detail: 'Another device holds the lock.',
    current: UNKNOWN_LOCK,
    live_window_minutes: 0,
  })
}

// ── client ───────────────────────────────────────────────────────────────────

export async function getRemoteUseStatus(): Promise<RemoteUseStatus> {
  const res = await fetch(`${apiBaseUrl()}/remote-use/status`)
  if (!res.ok) await parseDetailOrThrow(res, 'GET /remote-use/status')
  return res.json()
}

type RemoteUseAction = 'connect' | 'enable' | 'disable' | 'release'

async function postRemoteUseAction(action: RemoteUseAction): Promise<RemoteUseStatus> {
  const res = await fetch(`${apiBaseUrl()}/remote-use/${action}`, { method: 'POST' })
  if (res.status === 409) throw await readLockConflict(res)
  if (!res.ok) await parseDetailOrThrow(res, `POST /remote-use/${action}`)
  return res.json()
}

export function enableRemoteUse(): Promise<RemoteUseStatus> {
  return postRemoteUseAction('enable')
}

export function connectRemoteUse(): Promise<RemoteUseStatus> {
  return postRemoteUseAction('connect')
}

export function disableRemoteUse(): Promise<RemoteUseStatus> {
  return postRemoteUseAction('disable')
}

export function releaseRemoteUseLock(): Promise<RemoteUseStatus> {
  return postRemoteUseAction('release')
}

// ── TanStack Query hooks ─────────────────────────────────────────────────────

export const remoteUseKeys = {
  status: () => ['remote-use', 'status'] as const,
}

/** Live status for the Phone access settings page (30s poll mirrors health). */
export function useRemoteUseStatusQuery() {
  return useQuery({
    queryKey: remoteUseKeys.status(),
    queryFn: getRemoteUseStatus,
    refetchInterval: (query) => {
      const status = query.state.data
      return status?.tailscale.provider === 'embedded' && !status.tailscale.logged_in ? 3_000 : 30_000
    },
    refetchIntervalInBackground: false,
  })
}

function useRemoteUseActionMutation(action: RemoteUseAction) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => postRemoteUseAction(action),
    onSuccess: (status) => {
      queryClient.setQueryData(remoteUseKeys.status(), status)
      queryClient.invalidateQueries({ queryKey: remoteUseKeys.status() })
    },
  })
}

export function useEnableRemoteUseMutation() {
  return useRemoteUseActionMutation('enable')
}

export function useConnectRemoteUseMutation() {
  return useRemoteUseActionMutation('connect')
}

export function useDisableRemoteUseMutation() {
  return useRemoteUseActionMutation('disable')
}

export function useReleaseRemoteUseLockMutation() {
  return useRemoteUseActionMutation('release')
}
