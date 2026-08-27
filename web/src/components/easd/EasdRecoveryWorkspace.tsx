import { useState } from 'react'
import { AlertTriangle, History, Loader2, RefreshCw } from 'lucide-react'

import type { EasdRecoveryAction, EasdRecoveryPreview } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

export function EasdRecoveryWorkspace({
  preview,
  loading,
  error,
  busy,
  actionError,
  onRetry,
  onExecute,
}: {
  preview?: EasdRecoveryPreview
  loading: boolean
  error: unknown
  busy: boolean
  actionError: unknown
  onRetry: () => void
  onExecute: (action: EasdRecoveryAction) => Promise<boolean>
}) {
  const [selectedAction, setSelectedAction] = useState<EasdRecoveryAction | null>(null)

  if (loading) return <div className="flex min-h-64 items-center justify-center"><Loader2 className="animate-spin text-(--color-accent)" /></div>
  if (!preview || error) {
    return (
      <div className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-(--color-error)/30 p-6 text-center">
        <AlertTriangle className="text-(--color-error)" />
        <p className="text-xs text-(--color-error)">{error instanceof Error ? error.message : 'Recovery state is unavailable.'}</p>
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>Retry recovery state</Button>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <section className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
        <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-(--color-accent)">Recovery workspace</p>
        <h2 className="mt-1 text-sm font-semibold text-(--color-text)">Retry without losing history</h2>
        <p className="mt-1 text-[10px] leading-4 text-(--color-text-muted)">Every action is computed from persisted Run state. Prior revisions, attempts, evidence, deviations, and Trace events remain visible.</p>
        <p className="mt-2 text-[9px] text-(--color-text-subtle)">Repository generation {preview.store_generation ?? 'local'}</p>
      </section>

      {preview.actions.length === 0 ? (
        <section className="rounded-xl border border-dashed border-(--color-border) p-5 text-center">
          <History className="mx-auto text-(--color-text-subtle)" />
          <p className="mt-2 text-xs text-(--color-text-muted)">{preview.unavailable_reason}</p>
        </section>
      ) : preview.actions.map((action) => (
        <article key={action.id} className="rounded-xl border border-(--color-border) bg-(--bg-card) p-4">
          <div className="flex flex-col gap-3 @2xl/easd:flex-row @2xl/easd:items-start @2xl/easd:justify-between">
            <div className="min-w-0">
              <p className="text-xs font-semibold text-(--color-text)">{action.label}</p>
              <p className="mt-1 text-[10px] leading-4 text-(--color-text-muted)">{action.summary}</p>
              <p className="mt-2 font-mono text-[9px] text-(--color-accent)">{action.from_status} → {action.to_status}</p>
            </div>
            <Button type="button" size="sm" disabled={busy} onClick={() => setSelectedAction(action)}><RefreshCw /> {action.label}</Button>
          </div>
          <div className="mt-3 grid gap-2 @3xl/easd:grid-cols-2">
            <div className="rounded-lg bg-(--bg-key)/45 p-2.5"><p className="text-[9px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Reuse</p><ul className="mt-1 space-y-1 text-[10px] text-(--color-text-2)">{action.reuses.map((item) => <li key={item}>• {item}</li>)}</ul></div>
            <div className="rounded-lg bg-(--bg-key)/45 p-2.5"><p className="text-[9px] font-semibold uppercase tracking-wide text-(--color-text-subtle)">Preserve</p><ul className="mt-1 space-y-1 text-[10px] text-(--color-text-2)">{action.preserves.map((item) => <li key={item}>• {item}</li>)}</ul></div>
          </div>
        </article>
      ))}

      <Dialog open={selectedAction !== null} onOpenChange={(open) => { if (!open && !busy) setSelectedAction(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{selectedAction?.label}?</DialogTitle>
            <DialogDescription>{selectedAction?.summary}</DialogDescription>
          </DialogHeader>
          {selectedAction && (
            <div className="rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-xs">
              <p><span className="text-(--color-text-subtle)">Phase:</span> {selectedAction.from_status} → {selectedAction.to_status}</p>
              <p className="mt-1"><span className="text-(--color-text-subtle)">History:</span> preserved in Trace</p>
              <p className="mt-1"><span className="text-(--color-text-subtle)">After persistence:</span> open {selectedAction.prompt_phase} chat</p>
            </div>
          )}
          {actionError != null && <p role="alert" className="text-xs text-(--color-error)">{actionError instanceof Error ? actionError.message : 'Recovery failed.'}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={busy} onClick={() => setSelectedAction(null)}>Cancel</Button>
            <Button type="button" disabled={busy || !selectedAction} onClick={() => {
              if (!selectedAction) return
              void onExecute(selectedAction).then((succeeded) => { if (succeeded) setSelectedAction(null) })
            }}>{busy && <Loader2 className="animate-spin" />}Confirm retry</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
