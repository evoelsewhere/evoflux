import { useState } from 'react'
import { Check, FileDiff, Loader2, X } from 'lucide-react'
import { DiffEditor } from '@monaco-editor/react'
import { useQuery } from '@tanstack/react-query'

import {
  applyChangeSet,
  codingWorkspaceFileUrl,
  getChangeSetFileContent,
  rejectChangeSet,
} from '@/api/client'
import type { ChangeSetFile, ChangeSetResponse, EditorActionRequest } from '@/api/types'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { cn } from '@/lib/utils'
import { useChangeSetStore } from '@/stores/useChangeSetStore'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'
import { SidePanel } from './shell/SidePanel'
import { languageForExt, useMonacoTheme, useSafeMonaco } from '@/hooks/useMonacoTheme'
import { EditorAiActionDialog } from './EditorAiActionDialog'
import { useUIStore } from '@/stores/useUIStore'

function DiffLine({ line }: { line: string }) {
  const tone = line.startsWith('+++') || line.startsWith('---')
    ? 'text-(--color-accent)'
    : line.startsWith('@@')
      ? 'bg-(--color-accent)/10 text-(--color-accent)'
      : line.startsWith('+')
        ? 'bg-(--color-diff-add-bg) text-(--color-diff-add-text)'
        : line.startsWith('-')
          ? 'bg-(--color-diff-del-bg) text-(--color-diff-del-text)'
          : 'text-(--color-text-2)'
  return <span className={cn('block whitespace-pre-wrap break-all px-2', tone)}>{line || ' '}</span>
}

function FileProposal({
  file,
  busy,
  onDecision,
  selected,
  onSelect,
}: {
  file: ChangeSetFile
  busy: boolean
  onDecision: (decision: 'apply' | 'reject', paths: string[]) => void
  selected: boolean
  onSelect: () => void
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card)">
      <header className="flex items-center gap-2 border-b border-(--color-border) px-3 py-2">
        <button type="button" onClick={onSelect} className={selected ? 'min-w-0 flex-1 truncate text-left font-mono text-xs text-(--color-accent)' : 'min-w-0 flex-1 truncate text-left font-mono text-xs text-(--color-text)'}>{file.path}</button>
        <span className="font-mono text-[10px] tabular-nums text-(--color-text-muted)">
          <span className="text-(--color-success)">+{file.additions}</span>{' '}
          <span className="text-(--color-error)">−{file.deletions}</span>
        </span>
        {file.status === 'pending' ? (
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={busy}
              onClick={() => onDecision('reject', [file.path])}
              className="flex h-7 items-center gap-1 rounded-md px-2 text-[11px] text-(--color-error) hover:bg-(--color-error-subtle) disabled:opacity-50"
            >
              <X size={11} /> Reject
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onDecision('apply', [file.path])}
              className="flex h-7 items-center gap-1 rounded-md bg-(--color-success)/15 px-2 text-[11px] text-(--color-success) hover:bg-(--color-success)/25 disabled:opacity-50"
            >
              <Check size={11} /> Accept
            </button>
          </div>
        ) : (
          <span className="rounded-md bg-(--bg-key) px-2 py-1 text-[10px] uppercase text-(--color-text-muted)">
            {file.status}
          </span>
        )}
      </header>
      <pre className="max-h-72 overflow-auto bg-(--bg-page) py-2 font-mono text-[11px] leading-5">
        {file.diff.split('\n').map((line, index) => <DiffLine key={`${index}:${line}`} line={line} />)}
      </pre>
    </section>
  )
}

export function ChangeSetReviewPanel() {
  const active = useChangeSetStore((state) => state.active)
  const busy = useChangeSetStore((state) => state.busy)
  const setActive = useChangeSetStore((state) => state.setActive)
  const setBusy = useChangeSetStore((state) => state.setBusy)
  const sessionId = useTeamStore((state) => state.sessionId)
  const pushToast = useToastStore((state) => state.push)
  const [selectedPath, setSelectedPath] = useState<string | null>(active?.files[0]?.path ?? null)
  const [followupRequest, setFollowupRequest] = useState<EditorActionRequest | null>(null)
  const openWorkbenchTool = useUIStore((state) => state.openWorkbenchTool)
  const monaco = useSafeMonaco()
  const theme = useMonacoTheme(monaco)
  const selected = active?.files.find((file) => file.path === selectedPath) ?? active?.files[0]
  const contentQuery = useQuery({
    queryKey: ['change-set-file', active?.id, selected?.path],
    queryFn: () => {
      if (!active || !selected) throw new Error('No ChangeSet file selected.')
      return getChangeSetFileContent(active.workspace, active.id, selected.path)
    },
    enabled: Boolean(active && selected),
    staleTime: Infinity,
  })

  if (!active) return null
  const pendingPaths = active.files.filter((file) => file.status === 'pending').map((file) => file.path)
  const failedVerification = active.verification.find((item) => item.status === 'failed')

  const decide = async (decision: 'apply' | 'reject', paths: string[]) => {
    if (busy || paths.length === 0) return
    setBusy(true)
    try {
      const updated: ChangeSetResponse = decision === 'apply'
        ? await applyChangeSet(active.workspace, active.id, paths, sessionId)
        : await rejectChangeSet(active.workspace, active.id, paths)
      setActive(updated)
      pushToast({
        tone: decision === 'apply' ? 'success' : 'info',
        title: decision === 'apply' ? 'Changes applied' : 'Changes rejected',
        description: `${paths.length} file${paths.length === 1 ? '' : 's'}`,
      })
    } catch (error) {
      pushToast({
        tone: 'error',
        title: decision === 'apply' ? 'Could not apply changes' : 'Could not reject changes',
        description: error instanceof Error ? error.message : undefined,
      })
    } finally {
      setBusy(false)
    }
  }

  const proposeFollowup = async () => {
    const path = active.files.find((file) => file.status === 'applied')?.path
    if (!path || !sessionId || !failedVerification || busy) return
    setBusy(true)
    try {
      const fileResponse = await fetch(codingWorkspaceFileUrl(active.workspace, path))
      if (!fileResponse.ok) throw new Error(`HTTP ${fileResponse.status}`)
      setFollowupRequest({
        session_id: sessionId,
        action: 'fix_diagnostic',
        active_file: path,
        content: await fileResponse.text(),
        relevant_terminal_failure: String(failedVerification.output ?? failedVerification.message ?? ''),
        instruction: 'Verification failed after applying the previous ChangeSet. Analyze the evidence and propose the next minimal guarded fix.',
      })
    } catch (error) {
      pushToast({
        tone: 'error',
        title: 'Could not propose follow-up fix',
        description: error instanceof Error ? error.message : undefined,
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <SidePanel
      storageKey={STORAGE_KEYS.panels.changeSet}
      defaultWidth={520}
      minWidth={360}
      maxWidth={760}
      ariaLabel="ChangeSet review"
      resizeLabel="Resize ChangeSet review"
      onClose={() => setActive(null)}
      className="bg-(--bg-page)"
    >
      <header className="flex shrink-0 items-center gap-3 border-b border-(--color-border) px-4 py-3">
        <FileDiff size={16} className="text-(--color-accent)" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-(--color-text)">{active.title}</p>
          <p className="text-[11px] text-(--color-text-muted)">{active.origin} · {active.status}</p>
        </div>
        {busy && <Loader2 size={14} className="animate-spin text-(--color-text-muted)" aria-label="Applying changes" />}
      </header>
      {active.description && <p className="border-b border-(--color-border) px-4 py-2 text-xs text-(--color-text-muted)">{active.description}</p>}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {active.verification_commands.length > 0 && (
          <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3">
            <h3 className="text-xs font-semibold text-(--color-text)">Verification after apply</h3>
            <p className="mt-1 text-[11px] text-(--color-text-muted)">
              Deterministically discovered from the existing project; model-supplied commands are not executed.
            </p>
            <div className="mt-2 space-y-1">
              {active.verification_commands.map((command) => (
                <code key={command} className="block break-all rounded-md bg-(--bg-key) px-2 py-1 font-mono text-[10px] text-(--color-text-2)">
                  {command}
                </code>
              ))}
            </div>
          </section>
        )}
        {selected && (
          <section className="overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card)">
            <div className="flex items-center justify-between border-b border-(--color-border) px-3 py-2">
              <span className="truncate font-mono text-xs text-(--color-text)">{selected.path}</span>
              <span className="text-[10px] text-(--color-text-muted)">Monaco diff preview</span>
            </div>
            <div className="h-96 min-h-72">
              {contentQuery.isLoading ? (
                <div className="flex h-full items-center justify-center"><Loader2 size={14} className="animate-spin text-(--color-text-muted)" /></div>
              ) : contentQuery.data ? (
                <DiffEditor
                  theme={theme}
                  language={languageForExt(selected.path.split('.').pop() ?? '')}
                  original={contentQuery.data.original_content}
                  modified={contentQuery.data.proposed_content}
                  options={{
                    readOnly: true,
                    renderSideBySide: false,
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    fontSize: 12,
                    lineHeight: 20,
                    automaticLayout: true,
                  }}
                />
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-(--color-error)">Unable to load Monaco diff preview.</div>
              )}
            </div>
          </section>
        )}
        {active.files.map((file) => (
          <FileProposal
            key={file.path}
            file={file}
            busy={busy}
            selected={file.path === selected?.path}
            onSelect={() => setSelectedPath(file.path)}
            onDecision={(decision, paths) => { void decide(decision, paths) }}
          />
        ))}
        {active.verification.length > 0 && (
          <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3">
            <h3 className="text-xs font-semibold text-(--color-text)">Verification</h3>
            <div className="mt-2 space-y-1.5">
              {active.verification.map((item, index) => (
                <div key={`${String(item.kind)}:${index}`} className="flex items-start gap-2 text-[11px]">
                  <span className={item.status === 'passed' ? 'text-(--color-success)' : item.status === 'failed' ? 'text-(--color-error)' : 'text-(--color-text-muted)'}>
                    {item.status === 'passed' ? 'Passed' : item.status === 'failed' ? 'Failed' : 'Unavailable'}
                  </span>
                  <span className="min-w-0 flex-1 break-all font-mono text-(--color-text-muted)">
                    {String(item.command ?? item.path ?? item.kind ?? 'verification')}
                  </span>
                </div>
              ))}
            </div>
            {failedVerification && (
              <button
                type="button"
                disabled={busy || !sessionId}
                onClick={() => { void proposeFollowup() }}
                className="mt-3 rounded-md bg-(--color-accent)/12 px-2.5 py-1.5 text-[11px] font-medium text-(--color-accent) hover:bg-(--color-accent)/20 disabled:opacity-50"
              >
                Analyze failure and propose next fix
              </button>
            )}
          </section>
        )}
      </div>
      {pendingPaths.length > 0 && (
        <footer className="flex shrink-0 items-center justify-end gap-2 border-t border-(--color-border) px-3 py-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => { void decide('reject', pendingPaths) }}
            className="rounded-md px-3 py-1.5 text-xs text-(--color-error) hover:bg-(--color-error-subtle) disabled:opacity-50"
          >
            Reject all
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => { void decide('apply', pendingPaths) }}
            className="rounded-md bg-(--color-accent) px-3 py-1.5 text-xs font-medium text-(--color-text-on-accent) hover:opacity-90 disabled:opacity-50"
          >
            Accept all
          </button>
        </footer>
      )}
      {followupRequest && (
        <EditorAiActionDialog
          workspace={active.workspace}
          request={followupRequest}
          onClose={() => setFollowupRequest(null)}
          onOpenProblems={() => openWorkbenchTool('problems')}
        />
      )}
    </SidePanel>
  )
}
