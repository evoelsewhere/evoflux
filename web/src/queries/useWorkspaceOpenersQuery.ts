/**
 * TanStack Query hook for the "Open with" topbar menu.
 *
 * Fetches the list of desktop apps that can open the workspace root from
 * the Rust opener catalog (only apps actually installed are returned).
 * App availability almost never changes during a session, so the result
 * is cached indefinitely.
 */
import { useQuery } from '@tanstack/react-query'
import { tauriListWorkspaceOpeners } from '@/api/tauri-workspace'
import { usePlatform } from '@/hooks/use-platform'

export function useWorkspaceOpenersQuery(enabled: boolean) {
  const { os } = usePlatform()

  return useQuery({
    queryKey: ['desktop', 'workspace-openers', os],
    queryFn: tauriListWorkspaceOpeners,
    enabled,
    staleTime: Infinity,
  })
}
