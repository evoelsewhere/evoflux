/**
 * useWorkspaceFileWatcher — watches for file changes using native Tauri filesystem watcher.
 *
 * Desktop-only implementation that:
 * 1. Starts a native file watcher for every given workspace (a Coding
 *    session's repositories — the project may have several)
 * 2. Listens for file-change events
 * 3. Invalidates TanStack Query caches (files, diff, status)
 *
 * The native events carry root-relative paths without their root, so any
 * change refreshes every watched repository.
 *
 * Replaces the HTTP SSE-based watcher for desktop-only mode.
 */
import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { queryKeys } from '@/queries'
import {
  isTauriAvailable,
  tauriStartFileWatcher,
  tauriStopFileWatcher,
  tauriOnFileChange,
  type FileChangeEvent,
} from '@/api/tauri-workspace'

export function useWorkspaceFileWatcher(workspaces: readonly string[]) {
  const queryClient = useQueryClient()
  const unlistenRef = useRef<(() => void) | null>(null)
  // Re-run only when the set of repositories changes, not on every render's
  // fresh array.
  const key = workspaces.join('\0')

  useEffect(() => {
    const roots = key ? key.split('\0') : []
    if (roots.length === 0) return
    if (!isTauriAvailable()) return

    let cancelled = false

    async function startWatching() {
      try {
        // Start the native file watchers
        await Promise.all(roots.map((root) => tauriStartFileWatcher(root)))

        if (cancelled) return

        // Listen for file change events
        unlistenRef.current = tauriOnFileChange((_events: FileChangeEvent[]) => {
          for (const root of roots) {
            // Invalidate file list and status
            queryClient.invalidateQueries({ queryKey: queryKeys.coding.files(root) })
            queryClient.invalidateQueries({ queryKey: queryKeys.coding.status(root) })

            // Invalidate diff for changed paths
            queryClient.invalidateQueries({ queryKey: queryKeys.coding.diff(root) })
            queryClient.invalidateQueries({ queryKey: queryKeys.git.changes(root) })
          }
        })
      } catch (err) {
        console.error('Failed to start file watcher:', err)
      }
    }

    void startWatching()

    return () => {
      cancelled = true
      unlistenRef.current?.()
      unlistenRef.current = null

      // Stop the watchers (best-effort)
      for (const root of roots) {
        void tauriStopFileWatcher(root).catch(() => {})
      }
    }
  }, [key, queryClient])
}
