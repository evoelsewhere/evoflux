/**
 * useGlobalSearch — the asynchronous half of the command palette.
 *
 * The palette's own `commands` array covers actions the app can perform.
 * This hook covers the app's *content*: sessions and the dialogue inside
 * them, Coding projects and repositories, Memory pages, scheduled tasks,
 * agent and skill definitions (`POST /team/search-app`), plus the active
 * repository's files, symbols, Git refs and Problems (`search-everywhere`)
 * when a Coding workspace is open.
 *
 * Both requests run in parallel and share the palette's abort signal, so a
 * fast typist never pays for a stale keystroke. A failing source degrades to
 * no rows rather than emptying the palette.
 *
 * Group conventions (the palette renders one header per group):
 *   `Chats`, `Mentioned in chats`, `Memory`, `Projects`, `Repositories`,
 *   `Scheduled tasks`, `Agents`, `Skills` — application-wide;
 *   `Recent files`, `Files`, `Code`, `Git`, `Problems`, `Workflows` — repository.
 */
import { useCallback } from 'react'
import type { useNavigate } from '@tanstack/react-router'

import { searchApp, searchEverywhere } from '@/api/client'
import type { AppSearchItem, TurnChangesPending, WorkspaceFileInfo } from '@/api/types'
import { useUIStore } from '@/stores/useUIStore'
import { formatRelativeDate } from '@/utils/format'
import { codingFocusId } from '@/utils/workspace'
import type { Command } from '../CommandPalette'

interface UseGlobalSearchArgs {
  mode: 'work' | 'coding'
  workspace: string | null
  /** Files the latest agent turn touched — offered ahead of a repository scan. */
  turnChanges: TurnChangesPending | null
  navigate: ReturnType<typeof useNavigate>
  /** Open a workspace file in the standalone viewer. */
  openFile: (file: WorkspaceFileInfo) => void
  /** Put text in the composer and focus it (used by skill/workflow hits). */
  fillComposer: (text: string) => void
}

export type GlobalSearch = (query: string, signal: AbortSignal) => Promise<Command[]>

function fileInfo(path: string, metadata?: Record<string, unknown> | null): WorkspaceFileInfo {
  const size = metadata?.size
  const mtime = metadata?.mtime
  const mime = metadata?.mime
  return {
    path,
    name: path.split('/').pop() ?? path,
    size: typeof size === 'number' ? size : 0,
    mtime: typeof mtime === 'number' ? mtime : 0,
    mime: typeof mime === 'string' ? mime : 'text/plain',
  }
}

const APP_GROUPS: Record<AppSearchItem['kind'], string> = {
  // "Chats" matches the sidebar's own word for a session; the message group
  // says why those rows are here, since both open a chat.
  session: 'Chats',
  message: 'Mentioned in chats',
  memory: 'Memory',
  project: 'Projects',
  workspace: 'Repositories',
  scheduled_task: 'Scheduled tasks',
  agent: 'Agents',
  skill: 'Skills',
}

export function useGlobalSearch({
  mode,
  workspace,
  turnChanges,
  navigate,
  openFile,
  fillComposer,
}: UseGlobalSearchArgs): GlobalSearch {
  /**
   * Open a session under the shell that owns it. A Coding session lives at
   * `/coding/$focusId/$sessionId` — sending it to the Work route `/$sessionId`
   * loads the chat with Work chrome, no workspace, and none of the repository
   * tools, which is what a palette hit used to do for every session.
   */
  const openSession = useCallback((item: AppSearchItem) => {
    const sessionId = item.session_id
    if (!sessionId) return
    const metadata = item.metadata ?? {}
    const focusId = metadata.mode === 'coding'
      ? codingFocusId({
        project_id: typeof metadata.project_id === 'string' ? metadata.project_id : null,
        workspace: typeof metadata.workspace === 'string' ? metadata.workspace : null,
      })
      : null
    if (focusId) {
      navigate({ to: '/coding/$focusId/$sessionId', params: { focusId, sessionId } })
      return
    }
    navigate({ to: '/$sessionId', params: { sessionId } })
  }, [navigate])

  /**
   * Focus a project or repository the way its sidebar row does: `$focusId` is
   * the project id or the repository path, and it anchors the Coding page even
   * before a chat is picked. The store request keeps the sidebar's own
   * selection in step; navigation alone leaves it on the previous scope.
   */
  const openCodingScope = useCallback(
    (scope: { projectId?: string | null; workspace?: string | null }) => {
      useUIStore.getState().requestCodingScope(scope)
      const focusId = codingFocusId({
        project_id: scope.projectId ?? null,
        workspace: scope.workspace ?? null,
      })
      if (focusId) {
        navigate({ to: '/coding/$focusId', params: { focusId } })
        return
      }
      navigate({ to: '/coding' })
    },
    [navigate],
  )

  const appCommand = useCallback((item: AppSearchItem): Command => {
    const ui = useUIStore.getState
    const metadata = item.metadata ?? {}
    const action = () => {
      switch (item.kind) {
        case 'session':
        case 'message':
          openSession(item)
          return
        case 'project':
          openCodingScope({ projectId: String(metadata.project_id ?? '') || null })
          return
        case 'workspace':
          openCodingScope({ workspace: item.path })
          return
        case 'memory':
          if (item.path) ui().requestWikiFile(item.path)
          return
        case 'scheduled_task':
          ui().openWorkbenchTool('scheduler')
          return
        case 'agent':
          ui().openSettings(`agents/${String(metadata.name ?? item.label)}`)
          return
        case 'skill':
          ui().openSettings(`skills/${String(metadata.name ?? item.label)}`)
          return
      }
    }
    // Sessions and messages are the two kinds where "when" is part of telling
    // one result from another, so they carry a date the way sidebar rows do.
    const when = metadata.updated_at ?? metadata.created_at
    return {
      id: `app:${item.id}`,
      group: APP_GROUPS[item.kind],
      label: item.label,
      description: item.description,
      meta: typeof when === 'string' ? formatRelativeDate(when) : undefined,
      action,
    }
  }, [openCodingScope, openSession])

  return useCallback(async (query: string, signal: AbortSignal): Promise<Command[]> => {
    const normalized = query.trim().toLowerCase()
    const recent: Command[] = (turnChanges?.files ?? [])
      .filter((file) => file.path.toLowerCase().includes(normalized))
      .slice(0, 8)
      .map((file) => ({
        id: `recent:${file.path}`,
        group: 'Recent files',
        label: file.path,
        description: 'Changed in the latest agent turn',
        action: () => openFile(fileInfo(file.path)),
      }))

    // One dead source must not blank the palette: settle both and keep
    // whatever came back.
    const [appResult, repoResult] = await Promise.allSettled([
      searchApp(query, 40, signal),
      mode === 'coding' && workspace
        ? searchEverywhere(workspace, query, 50, signal)
        : Promise.resolve({ items: [] }),
    ])

    const app: Command[] = appResult.status === 'fulfilled'
      ? appResult.value.items.map(appCommand)
      : []

    const repo: Command[] = repoResult.status === 'fulfilled'
      ? repoResult.value.items.map<Command>((item) => ({
        id: `search:${item.id}`,
        group: item.kind === 'git_branch' || item.kind === 'git_commit'
          ? 'Git'
          : item.kind === 'problem'
            ? 'Problems'
            : item.kind === 'skill'
              ? 'Skills'
              : item.kind === 'workflow'
                ? 'Workflows'
                : item.kind === 'file' || item.kind === 'folder'
                  ? 'Files'
                  : 'Code',
        label: item.label,
        description: item.description,
        action: () => {
          const ui = useUIStore.getState()
          if (item.kind === 'problem') {
            ui.openWorkbenchTool('problems')
            return
          }
          if (item.kind === 'git_branch' || item.kind === 'git_commit') {
            ui.openWorkbenchTool('source-control')
            return
          }
          if (item.kind === 'skill') {
            fillComposer(`$${String(item.metadata?.name ?? item.label)} `)
            return
          }
          if (item.kind === 'workflow') {
            fillComposer(`/workflow ${String(item.metadata?.name ?? item.label)} `)
            return
          }
          if (item.kind === 'folder') {
            ui.openWorkbenchTool('files')
            return
          }
          if (item.path) openFile(fileInfo(item.path, item.metadata))
        },
      }))
      : []

    return [...recent, ...app, ...repo]
  }, [appCommand, fillComposer, mode, openFile, turnChanges?.files, workspace])
}
