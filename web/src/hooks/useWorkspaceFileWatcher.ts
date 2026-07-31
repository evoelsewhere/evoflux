/**
 * useWorkspaceFileWatcher — watches for file changes using native Tauri filesystem watcher.
 *
 * Desktop-only implementation that:
 * 1. Starts the native file watcher when workspace is provided
 * 2. Listens for file-change events
 * 3. Invalidates TanStack Query caches (files, diff, status)
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

export function useWorkspaceFileWatcher(workspace: string | null) {
  const queryClient = useQueryClient()
  const unlistenRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    if (!workspace) return
    if (!isTauriAvailable()) return

    let cancelled = false

    async function startWatching() {
      try {
        // Start the native file watcher
        await tauriStartFileWatcher(workspace!)

        if (cancelled) return

        // Listen for file change events
        unlistenRef.current = tauriOnFileChange((_events: FileChangeEvent[]) => {
          // Invalidate file list and status
          queryClient.invalidateQueries({ queryKey: queryKeys.coding.files(workspace!) })
          queryClient.invalidateQueries({ queryKey: queryKeys.coding.status(workspace!) })

          // Invalidate diff for changed paths
          queryClient.invalidateQueries({ queryKey: queryKeys.coding.diff(workspace!) })
          queryClient.invalidateQueries({ queryKey: queryKeys.git.changes(workspace!) })
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

      // Stop the watcher (best-effort)
      if (workspace) {
        void tauriStopFileWatcher(workspace).catch(() => {})
      }
    }
  }, [workspace, queryClient])
}
