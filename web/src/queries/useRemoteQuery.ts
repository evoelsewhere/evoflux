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
  switch (state) {
    case 'starting':
    case 'backoff':
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

export function useRevokePairingMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (connectionId: string) => revokePairing(connectionId),
    onSuccess: (_data, connectionId) => {
      client.setQueryData(queryKeys.remote.pairing(connectionId), null)
    },
  })
}
