/**
 * useGeneratedDocumentWatcher — live previews for Office files an agent writes.
 *
 * Subscribes to the session workspace's file-change stream (the backend
 * watcher, so it works in the browser and in Tauri, and sees files written by
 * a `shell` script mid-run, long before its `tool_end`). For Office files it:
 *
 * 1. refreshes the workspace file list, so an open preview picks up each save
 *    while the agent is still working (a deck built slide by slide redraws
 *    after every slide);
 * 2. opens the preview of a document the agent just created, once per file,
 *    while a turn is running — unless the user is busy in another workbench
 *    tool or turned the behaviour off.
 */
import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { withTokenParam } from '@/api/auth'
import { apiUrl } from '@/api/base-url'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { queryKeys } from '@/queries/keys'
import { useTeamStore } from '@/stores/useTeamStore'
import { useUIStore } from '@/stores/useUIStore'

const OFFICE_DOCUMENT = /\.(pptx|docx|xlsx)$/i

interface FsChange {
  type: 'added' | 'modified' | 'deleted'
  path: string
}

export function autoOpenGeneratedDocumentsEnabled(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEYS.autoOpenGeneratedDocuments) !== 'false'
  } catch {
    return true
  }
}

/** Decide whether a newly created document should take over the workbench. */
export function shouldOpenGeneratedDocument(sessionId: string): boolean {
  const team = useTeamStore.getState()
  if (team.sessionId !== sessionId || !team.isTeamWorking) return false
  if (!autoOpenGeneratedDocumentsEnabled()) return false
  const ui = useUIStore.getState()
  // Never pull the user out of another tool they are looking at.
  return !ui.workbenchOpen || ui.activeWorkbenchTool === null || ui.activeWorkbenchTool === 'files'
}

export function useGeneratedDocumentWatcher(sessionId: string | null) {
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!sessionId || typeof EventSource === 'undefined') return
    const opened = new Set<string>()
    const source = new EventSource(
      withTokenParam(apiUrl(`/team/${encodeURIComponent(sessionId)}/files/watch`)),
    )
    const handleChange = (event: MessageEvent<string>) => {
      let changes: FsChange[]
      try {
        changes = JSON.parse(event.data) as FsChange[]
      } catch {
        return
      }
      const documents = changes.filter(
        (change) => change.type !== 'deleted' && OFFICE_DOCUMENT.test(change.path),
      )
      if (documents.length === 0) return
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.files(sessionId) })
      const created = documents.find(
        (change) => change.type === 'added' && !opened.has(change.path),
      )
      if (!created || !shouldOpenGeneratedDocument(sessionId)) return
      opened.add(created.path)
      useUIStore.getState().requestWorkspaceFile(sessionId, created.path)
    }
    source.addEventListener('fs_change', handleChange as EventListener)
    return () => {
      source.removeEventListener('fs_change', handleChange as EventListener)
      source.close()
    }
  }, [queryClient, sessionId])
}
