/**
 * TanStack Query hooks for remote access connections and pairing.
 *
 * Connection and status queries use adaptive polling: fast during transitional
 * states (starting, backoff) so the UI tracks adapter lifecycle in real time,
 * and slower once the connection is stable (polling, error, offline).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createConnection,
  getPairing,
  getRemoteSettings,
  issuePairingCode,
  issuePairingLink,
  listConnections,
  patchConnection,
  removeConnection,
  replaceToken,
  revokePairing,
  updateRemoteSettings,
} from '@/api/client/remote'
import type { RemoteSettings } from '@/api/client/remote'

import { queryKeys } from './keys'

// ── Adaptive polling intervals ───────────────────────────────────────────────

/** Fast poll while the adapter is transitioning between states. */
const POLL_TRANSITIONAL_MS = 2_000
/** Normal poll once the connection is stable (polling / offline). */
const POLL_STABLE_MS = 15_000
/** Relaxed poll for terminal or unconfigured states. */
const POLL_RELAXED_MS = 30_000

type ConnectionState = string

/**
 * Return the polling interval for a given adapter state.
 * Transitional states get fast polling so the UI tracks lifecycle changes
 * within seconds instead of waiting for a manual tab switch.
 */
function adaptivePollInterval(state: ConnectionState | undefined): number {
  // 'pairing' is iMessage's version of "waiting to become ready" — poll
  // fast so the UI picks up the jump to 'polling' right after the phone's
  // /pair <code> is verified, same as Telegram's 'starting'.
  switch (state) {
    case 'starting':
    case 'backoff':
    case 'pairing':
      return POLL_TRANSITIONAL_MS
    case 'polling':
    case 'offline':
      return POLL_STABLE_MS
    default:
      return POLL_RELAXED_MS
  }
}

// ── Settings ─────────────────────────────────────────────────────────────────

export function useRemoteSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.remote(),
    queryFn: getRemoteSettings,
    staleTime: 30_000,
  })
}

export function useUpdateRemoteSettingsMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: RemoteSettings) => updateRemoteSettings(body),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.settings.remote(), data)
    },
  })
}

// ── Connections ──────────────────────────────────────────────────────────────

export function useConnectionsQuery() {
  return useQuery({
    queryKey: queryKeys.remote.connections(),
    queryFn: listConnections,
    // Always allow refetch — the mutation response may contain a transitional
    // state ("starting") that must be superseded once the adapter reaches
    // "polling" in the background.
    staleTime: 0,
    // Poll adaptively based on the first (v1: only) connection's state.
    refetchInterval: (query) => {
      const connections = query.state.data
      const first = Array.isArray(connections) ? connections[0] : undefined
      return adaptivePollInterval(first?.status?.state)
    },
  })
}

export function useCreateConnectionMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      label: string
      token: string
      adapter?: 'telegram' | 'imessage'
      provider?: 'imsg' | 'bluebubbles'
      endpoint_url?: string | null
    }) => createConnection(body),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.remote.connections(), [data])
    },
  })
}

export function usePatchConnectionMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: { label?: string; enabled?: boolean } }) =>
      patchConnection(id, body),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.remote.connections(), [data])
    },
  })
}

export function useReplaceTokenMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, token }: { id: string; token: string }) =>
      replaceToken(id, { token }),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.remote.connections(), [data])
    },
  })
}

export function useRemoveConnectionMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => removeConnection(id),
    onSuccess: () => {
      client.setQueryData(queryKeys.remote.connections(), [])
      client.removeQueries({ queryKey: ['remote'] })
    },
  })
}

// ── Pairing ──────────────────────────────────────────────────────────────────

export function usePairingQuery(connectionId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.remote.pairing(connectionId ?? ''),
    queryFn: () => getPairing(connectionId!),
    enabled: !!connectionId,
    staleTime: 0,
    // Poll until pairing appears (or disappears after revoke).  Fast enough
    // that the UI updates within seconds of scanning the QR code on the phone.
    refetchInterval: 3_000,
  })
}

export function useIssuePairingLinkMutation() {
  return useMutation({
    mutationFn: (connectionId: string) => issuePairingLink(connectionId),
  })
}

/**
 * Issue (and cache) a phone-first pairing code for `connectionId`.
 *
 * Modeled as a query, not a mutation: a `useMutation`'s result lives only in
 * that hook instance and is discarded on any remount (React 18 StrictMode's
 * double-invoke in dev, Vite Fast Refresh, or a real remount) — which reads
 * to the user as "stuck loading" the instant a remount happens to land right
 * after the code was issued, since the freshly mounted instance starts a
 * brand new, still-pending mutation with no memory of the previous one's
 * result. A query's result lives in the shared `QueryClient` cache keyed by
 * `connectionId`, so it survives a remount and the same code is reused
 * instead of silently discarding a code the user may already be looking at.
 *
 * `staleTime` mirrors the server's ten-minute code TTL (with a margin) so a
 * remount within that window never issues a second, unrelated code; call
 * `refetch()` to deliberately request a fresh one (e.g. after expiry).
 */
export function usePairingCodeQuery(connectionId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.remote.pairingCode(connectionId ?? ''),
    queryFn: () => issuePairingCode(connectionId!),
    enabled: !!connectionId && enabled,
    staleTime: 9 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    retry: false,
  })
}

export function useRevokePairingMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (connectionId: string) => revokePairing(connectionId),
    onSuccess: (_data, connectionId) => {
      client.setQueryData(queryKeys.remote.pairing(connectionId), null)
    },
  })
}
