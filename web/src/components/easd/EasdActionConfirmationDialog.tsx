import type { EasdPlanRevision, EasdRunDetail, EasdSpecRevision } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

export type EasdConfirmableAction = 'approve_specification' | 'approve_plan' | 'converge'

interface EasdActionConfirmationDialogProps {
  action: EasdConfirmableAction | null
  detail: EasdRunDetail
  draft: EasdSpecRevision | null
  planDraft: EasdPlanRevision | null
  busy: boolean
  error?: string | null
  onCancel: () => void
  onConfirm: () => void | Promise<void>
}

export function EasdActionConfirmationDialog({
  action,
  detail,
  draft,
  planDraft,
  busy,
  error,
  onCancel,
  onConfirm,
}: EasdActionConfirmationDialogProps) {
  const acceptedCriteria = detail.criteria.filter((criterion) => (
    criterion.status === 'passed' || criterion.status === 'waived'
  )).length
  const deliveryMode = draft?.spec.delivery_flow?.mode ?? 'planned'
  const title = action === 'approve_specification'
    ? 'Approve specification?'
    : action === 'approve_plan'
      ? 'Approve plan?'
      : 'Converge this Run?'
  const description = action === 'approve_specification'
    ? 'This accepts the persisted specification as the implementation contract.'
    : action === 'approve_plan'
      ? 'This accepts the mission graph and its ownership boundaries.'
      : 'The server will make the final Done decision from current evidence and gates.'
  const confirmLabel = action === 'approve_specification'
    ? 'Approve specification'
    : action === 'approve_plan'
      ? 'Approve plan'
      : 'Converge Run'

  return (
    <Dialog open={action !== null} onOpenChange={(open) => { if (!open && !busy) onCancel() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        {action === 'approve_specification' && draft && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-xs">
            <dt className="text-(--color-text-subtle)">Revision</dt><dd>Specification v{draft.version}</dd>
            <dt className="text-(--color-text-subtle)">Risk</dt><dd className="capitalize">{draft.spec.risk_tier.replace('_', '-')}</dd>
            <dt className="text-(--color-text-subtle)">Criteria</dt><dd>{draft.spec.criteria.length} acceptance criteria</dd>
            <dt className="text-(--color-text-subtle)">Flow</dt><dd className="capitalize">{deliveryMode}{deliveryMode === 'direct' ? ' · Plan will be skipped' : ' · Plan approval required'}</dd>
          </dl>
        )}

        {action === 'approve_plan' && planDraft && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-xs">
            <dt className="text-(--color-text-subtle)">Revision</dt><dd>Plan v{planDraft.version}</dd>
            <dt className="text-(--color-text-subtle)">Spec</dt><dd>Accepted specification</dd>
            <dt className="text-(--color-text-subtle)">Missions</dt><dd>{planDraft.plan.missions.length}</dd>
            <dt className="text-(--color-text-subtle)">Review</dt><dd>{planDraft.plan.review_required ? 'Independent review required' : 'Standard review required'}</dd>
          </dl>
        )}

        {action === 'converge' && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 rounded-lg border border-(--color-border) bg-(--bg-page) p-3 text-xs">
            <dt className="text-(--color-text-subtle)">Criteria</dt><dd>{acceptedCriteria} / {detail.criteria.length} satisfied</dd>
            <dt className="text-(--color-text-subtle)">Missions</dt><dd>{detail.missions.length} recorded</dd>
            <dt className="text-(--color-text-subtle)">Evidence</dt><dd>{detail.evidence.length} records</dd>
            <dt className="text-(--color-text-subtle)">Deviations</dt><dd>{detail.deviations.length} recorded</dd>
          </dl>
        )}

        {error && <p role="alert" className="text-xs text-(--color-error)">{error}</p>}

        <DialogFooter>
          <Button type="button" variant="outline" disabled={busy} onClick={onCancel}>Cancel</Button>
          <Button type="button" disabled={busy} onClick={onConfirm}>{confirmLabel}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
