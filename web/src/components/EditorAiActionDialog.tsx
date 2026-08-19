import { useEffect, useState } from 'react'
import { AlertCircle, Check, Loader2, Sparkles, X } from 'lucide-react'

import { previewEditorContext, runEditorAction } from '@/api/client'
import type {
  EditorActionRequest,
  EditorActionResponse,
  EditorAiAction,
} from '@/api/types'
import { useChangeSetStore } from '@/stores/useChangeSetStore'
import { useToastStore } from '@/stores/useToastStore'

const ACTION_LABELS: Record<EditorAiAction, string> = {
  explain_code: 'Explain code or symbol',
  fix_diagnostic: 'Fix diagnostic',
  refactor_selection: 'Refactor selection',
  generate_tests: 'Generate tests',
  generate_documentation: 'Generate documentation',
  find_problems: 'Find potential problems',
  simplify_code: 'Simplify code',
  convert_pattern: 'Convert implementation pattern',
  propagate_api_change: 'Propagate API change',
  explain_failure: 'Explain build or test failure',
}

export function EditorAiActionDialog({
  workspace,
  request,
  onClose,
  onOpenProblems,
}: {
  workspace: string
  request: EditorActionRequest
  onClose: () => void
  onOpenProblems?: () => void
}) {
  const [context, setContext] = useState<Record<string, unknown> | null>(null)
  const [contextDigest, setContextDigest] = useState<string | null>(null)
  const [loadingContext, setLoadingContext] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [instruction, setInstruction] = useState(request.instruction ?? '')
  const [mentionText, setMentionText] = useState(
    (request.mention_paths ?? []).map((path) => `@${path}`).join(' '),
  )
  const [result, setResult] = useState<EditorActionResponse | null>(null)
  const setChangeSet = useChangeSetStore((state) => state.setActive)
  const pushToast = useToastStore((state) => state.push)

  const mentionPaths = () => mentionText
    .split(/\s+/)
    .map((value) => value.trim().replace(/^@/, ''))
    .filter(Boolean)

  const loadContext = (controller: AbortController) => {
    setLoadingContext(true)
    setError(null)
    setContext(null)
    setContextDigest(null)
    return previewEditorContext(
      workspace,
      { ...request, mention_paths: mentionPaths() },
      controller.signal,
    )
      .then((response) => {
        if (!controller.signal.aborted) {
          setContext(response.context)
          setContextDigest(response.context_sha256)
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : 'Unable to assemble editor context.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingContext(false)
      })
  }

  useEffect(() => {
    const controller = new AbortController()
    void loadContext(controller)
    return () => controller.abort()
  // Initial preview only. Mention edits explicitly invalidate and refresh it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request, workspace])

  const run = async () => {
    if (running || loadingContext || !context || !contextDigest) return
    setRunning(true)
    setError(null)
    try {
      const response = await runEditorAction(workspace, {
        ...request,
        instruction: instruction.trim() || undefined,
        mention_paths: mentionPaths(),
        expected_context_sha256: contextDigest,
      })
      setResult(response)
      if (response.change_set) {
        setChangeSet(response.change_set)
        pushToast({ tone: 'success', title: 'AI changes ready for review' })
        onClose()
      } else if (response.kind === 'findings') {
        pushToast({
          tone: 'info',
          title: response.findings.length
            ? `${response.findings.length} problem${response.findings.length === 1 ? '' : 's'} found`
            : 'No concrete problems found',
        })
        onOpenProblems?.()
        onClose()
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'AI editor action failed.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="fixed inset-0 z-(--z-modal) flex items-center justify-center bg-(--color-overlay) p-3 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={ACTION_LABELS[request.action]}>
      <div className="flex max-h-[min(48rem,calc(100vh-1.5rem))] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-page) shadow-2xl">
        <header className="flex shrink-0 items-center gap-3 border-b border-(--color-border) px-4 py-3">
          <Sparkles size={16} className="text-(--color-accent)" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-(--color-text)">{ACTION_LABELS[request.action]}</p>
            <p className="truncate font-mono text-[10px] text-(--color-text-muted)">{request.active_file}</p>
          </div>
          <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-(--color-text-muted) hover:bg-(--bg-key)" aria-label="Close AI editor action"><X size={14} /></button>
        </header>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          <section>
            <h3 className="text-xs font-semibold text-(--color-text)">Instruction</h3>
            <textarea
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              rows={3}
              placeholder="Optional constraints for this action…"
              className="mt-2 w-full resize-y rounded-xl border border-(--color-border) bg-(--bg-card) px-3 py-2 text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
            />
          </section>
          <section>
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-xs font-semibold text-(--color-text)">Additional file or folder context</h3>
              <button
                type="button"
                disabled={loadingContext}
                onClick={() => {
                  const controller = new AbortController()
                  void loadContext(controller)
                }}
                className="text-[11px] text-(--color-accent) disabled:opacity-50"
              >
                Refresh context
              </button>
            </div>
            <input
              value={mentionText}
              onChange={(event) => {
                setMentionText(event.target.value)
                setContext(null)
                setContextDigest(null)
              }}
              placeholder="@src/auth.py @tests/"
              className="mt-2 w-full rounded-xl border border-(--color-border) bg-(--bg-card) px-3 py-2 font-mono text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
            />
          </section>
          <section>
            <h3 className="text-xs font-semibold text-(--color-text)">AI will receive</h3>
            {loadingContext ? (
              <div className="mt-2 flex items-center gap-2 rounded-xl border border-(--color-border) bg-(--bg-card) p-3 text-xs text-(--color-text-muted)"><Loader2 size={13} className="animate-spin" /> Assembling bounded context…</div>
            ) : context ? (
              <div className="mt-2 space-y-2 rounded-xl border border-(--color-border) bg-(--bg-card) p-3">
                <div className="flex flex-wrap gap-1.5">
                  {Array.isArray(context.provenance) && context.provenance.map((item, index) => {
                    const record = item as Record<string, unknown>
                    return <span key={`${String(record.kind)}:${index}`} className="rounded-md bg-(--bg-key) px-2 py-1 text-[10px] text-(--color-text-muted)">{String(record.kind)} · {String(record.source)}</span>
                  })}
                </div>
                <details>
                  <summary className="cursor-pointer text-[11px] text-(--color-accent)">Inspect exact context payload</summary>
                  <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-(--bg-page) p-2 font-mono text-[10px] leading-4 text-(--color-text-muted)">{JSON.stringify(context, null, 2)}</pre>
                </details>
              </div>
            ) : null}
          </section>
          {error && <div className="flex items-start gap-2 rounded-xl border border-(--color-error)/35 bg-(--color-error-subtle) p-3 text-xs text-(--color-error)"><AlertCircle size={14} className="mt-0.5 shrink-0" /> {error}</div>}
          {result?.kind === 'explanation' && (
            <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-3">
              <h3 className="text-xs font-semibold text-(--color-text)">{result.summary}</h3>
              <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-(--color-text-2)">{result.explanation}</p>
            </section>
          )}
        </div>
        <footer className="flex shrink-0 items-center justify-end gap-2 border-t border-(--color-border) px-4 py-3">
          {result?.kind === 'explanation' ? (
            <button type="button" onClick={onClose} className="rounded-lg bg-(--color-accent) px-3 py-2 text-xs font-medium text-(--color-text-on-accent)">Done</button>
          ) : (
            <>
              <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-xs text-(--color-text-muted) hover:bg-(--bg-key)">Cancel</button>
              <button type="button" onClick={() => { void run() }} disabled={running || loadingContext || !context || !contextDigest} className="flex items-center gap-1.5 rounded-lg bg-(--color-accent) px-3 py-2 text-xs font-medium text-(--color-text-on-accent) disabled:opacity-50">
                {running ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                {running ? 'Working…' : 'Run explicit action'}
              </button>
            </>
          )}
        </footer>
      </div>
    </div>
  )
}
