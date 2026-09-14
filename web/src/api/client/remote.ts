/**
 * EvoFlux API client — remote access (connection CRUD, pairing, status).
 *
 * Token fields are write-only: accepted on create/replace, never returned.
 * Every response carries `token_configured: boolean` instead.
 */

import { apiBaseUrl } from '../base-url'
import { parseDetailOrThrow } from './_shared'

// ── Types ────────────────────────────────────────────────────────────────────

export type RemoteConnectionState =
  | 'disabled'
  | 'starting'
  | 'pairing'
  | 'polling'
  | 'backoff'
  | 'rate_limited'
  | 'used_elsewhere'
  | 'invalid_token'
  | 'phone_unreachable'
  | 'credential_missing'
  | 'error'

export type RemoteErrorClass =
  | 'none'
  | 'invalid_token'
  | 'used_elsewhere'
  | 'rate_limited'
  | 'transport'
  | 'phone_unreachable'
  | 'credential_missing'
  | 'unknown'

export type RemoteConnectionStatus = {
  connection_id: string
  state: RemoteConnectionState
  last_error_class: RemoteErrorClass
  last_successful_poll_at: string | null
  paired: boolean
  phone_reachable: boolean | null
  informational_drop_count: number
  high_priority_drop_count: number
}

export type RemoteConnection = {
  id: string
  adapter: string
  label: string
  enabled: boolean
  adapter_principal_id: string
  adapter_username: string
  token_configured: boolean
  created_at: string
  updated_at: string
  status: RemoteConnectionStatus
}

export type RemotePairingLink = {
  url: string
  qr_payload: string
  expires_at: string
}

export type RemotePairing = {
  id: string
  label: string
  display: string
  created_at: string
  last_seen_at: string
}

export type RemoteSettings = {
  outbound_data_policy: 'block' | 'redact' | 'off'
  outbound_pii_policy: 'off' | 'standard' | 'strict'
}

// ── Client calls ─────────────────────────────────────────────────────────────

/** GET /api/settings/remote */
export async function getRemoteSettings(): Promise<RemoteSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/remote`)
  if (!res.ok) await parseDetailOrThrow(res, 'GET /settings/remote')
  return res.json()
}

/** PUT /api/settings/remote */
export async function updateRemoteSettings(body: RemoteSettings): Promise<RemoteSettings> {
  const res = await fetch(`${apiBaseUrl()}/settings/remote`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'PUT /settings/remote')
  return res.json()
}

/** GET /api/remote/connections — returns 0 or 1 connections (v1 limit). */
export async function listConnections(): Promise<RemoteConnection[]> {
  const res = await fetch(`${apiBaseUrl()}/remote/connections`)
  if (!res.ok) await parseDetailOrThrow(res, 'GET /remote/connections')
  return res.json()
}

/** POST /api/remote/connections — create a new connection. */
export async function createConnection(body: {
  label: string
  token: string
}): Promise<RemoteConnection> {
  const res = await fetch(`${apiBaseUrl()}/remote/connections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, 'POST /remote/connections')
  return res.json()
}

/** PATCH /api/remote/connections/{id} — update label or enabled state. */
export async function patchConnection(
  id: string,
  body: { label?: string; enabled?: boolean },
): Promise<RemoteConnection> {
  const res = await fetch(`${apiBaseUrl()}/remote/connections/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, `PATCH /remote/connections/${id}`)
  return res.json()
}

/** PUT /api/remote/connections/{id}/token — replace the bot token. */
export async function replaceToken(
  id: string,
  body: { token: string },
): Promise<RemoteConnection> {
  const res = await fetch(`${apiBaseUrl()}/remote/connections/${id}/token`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) await parseDetailOrThrow(res, `PUT /remote/connections/${id}/token`)
  return res.json()
}

/** DELETE /api/remote/connections/{id} — remove connection and vault credential. */
export async function removeConnection(id: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/remote/connections/${id}`, {
    method: 'DELETE',
  })
  if (!res.ok) await parseDetailOrThrow(res, `DELETE /remote/connections/${id}`)
}

/** POST /api/remote/connections/{id}/pairing-links — issue a one-tap pairing link. */
export async function issuePairingLink(id: string): Promise<RemotePairingLink> {
  const res = await fetch(`${apiBaseUrl()}/remote/connections/${id}/pairing-links`, {
    method: 'POST',
  })
  if (!res.ok)
    await parseDetailOrThrow(res, `POST /remote/connections/${id}/pairing-links`)
  return res.json()
}

/** GET /api/remote/connections/{id}/pairing — read current pairing state. */
export async function getPairing(id: string): Promise<RemotePairing | null> {
  const res = await fetch(`${apiBaseUrl()}/remote/connections/${id}/pairing`)
  if (res.status === 404) return null
  if (!res.ok) await parseDetailOrThrow(res, `GET /remote/connections/${id}/pairing`)
  return res.json()
}

/** DELETE /api/remote/connections/{id}/pairing — revoke pairing. */
export async function revokePairing(id: string): Promise<void> {
  const res = await fetch(`${apiBaseUrl()}/remote/connections/${id}/pairing`, {
    method: 'DELETE',
  })
  if (!res.ok)
    await parseDetailOrThrow(res, `DELETE /remote/connections/${id}/pairing`)
}
