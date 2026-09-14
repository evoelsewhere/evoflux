/**
 * TanStack Query hooks for remote access connections and pairing.
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
    staleTime: 10_000,
  })
}

export function useCreateConnectionMutation() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: { label: string; token: string }) => createConnection(body),
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
    staleTime: 10_000,
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
