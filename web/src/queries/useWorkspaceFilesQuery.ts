/**
 * TanStack Query hook for the per-session workspace file listing.
 *
 * Mirrors the pattern in ``useMemoryQuery`` — the list is invalidated by the
 * team store whenever a write/edit/rm tool targets the agent workspace so the
 * panel reflects changes as soon as a turn finishes producing them.
 *
 * When running inside the Tauri desktop shell and `workspaceRoot` is provided,
 * file listing is handled natively by Rust (no HTTP round-trip to Python).
 * Falls back to the HTTP API otherwise. The workspace root is cached from the
 * first HTTP response so subsequent calls can use the fast native path.
 */
import { useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listWorkspaceFiles } from '@/api/client'
import { isTauriAvailable, tauriListWorkspaceFiles } from '@/api/tauri-workspace'
import { queryKeys } from './keys'

export function useWorkspaceFilesQuery(
  sessionId: string | null | undefined,
  workspaceRoot?: string | null,
) {
  // Cache the workspace root from the first successful API response so
  // subsequent re-fetches (invalidated by the team store) can use the
  // native Tauri path without waiting for another HTTP round-trip.
  const cachedRootRef = useRef<string | null>(null)
  const effectiveRoot = workspaceRoot ?? cachedRootRef.current

  return useQuery({
    queryKey: queryKeys.team.files(sessionId ?? ''),
    queryFn: async () => {
      // Native Rust path — fast, no HTTP overhead.
      if (isTauriAvailable() && effectiveRoot) {
        return tauriListWorkspaceFiles(effectiveRoot, sessionId as string)
      }
      // HTTP API fallback (web browser or missing workspace root).
      const result = await listWorkspaceFiles(sessionId as string)
      // Cache the root for next time.
      if (result.workspace_root) {
        cachedRootRef.current = result.workspace_root
      }
      return result
    },
    enabled: !!sessionId,
    // Short stale time — the panel is visible only on demand and we also
    // invalidate explicitly from the team store, so a small window is fine.
    staleTime: 5_000,
  })
}
