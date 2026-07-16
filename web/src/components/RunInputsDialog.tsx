/**
 * RunInputsDialog — the small form generated from a workflow's declared
 * inputs when `/workflow <name>` is submitted with required inputs still
 * missing (plan v5 §9.1).
 */

import { useState } from 'react'
import { Loader2, Play } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import type { WorkflowInputSpec } from '@/api/types'

export interface RunInputsRequest {
  name: string
  inputs: WorkflowInputSpec[]
  prefilled: Record<string, unknown>
}

export function RunInputsDialog({
  request,
  onCancel,
  onRun,
}: {
  request: RunInputsRequest
  onCancel: () => void
  onRun: (values: Record<string, unknown>) => Promise<void>
}) {
  const [values, setValues] = useState<Record<string, unknown>>(request.prefilled)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const missingRequired = request.inputs.some(
    (spec) =>
      spec.required &&
      (values[spec.name] === undefined || values[spec.name] === '') &&
      spec.default == null,
  )

  const handleRun = async () => {
    setSubmitting(true)
    setError(null)
    try {
      await onRun(values)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start the workflow.')
      setSubmitting(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="max-w-sm gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-(--color-border) px-5 pb-4 pt-5">
          <DialogTitle className="text-sm font-semibold">
            Run {request.name}
          </DialogTitle>
          <DialogDescription className="mt-1 text-xs text-(--color-text-muted)">
            Fill in the workflow inputs.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 px-5 py-4">
          {request.inputs.map((spec) => (
            <label key={spec.name} className="block text-xs">
              <span className="font-medium text-(--color-text)">
                {spec.name}
                {spec.required && <span className="text-(--color-error)"> *</span>}
              </span>
              {spec.description && (
                <span className="ml-1 text-(--color-text-subtle)">
                  {spec.description}
                </span>
              )}
              {spec.type === 'enum' ? (
                <select
                  value={String(values[spec.name] ?? spec.default ?? '')}
                  onChange={(e) =>
                    setValues((prev) => ({ ...prev, [spec.name]: e.target.value }))
                  }
                  className="mt-1 w-full rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text)"
                >
                  <option value="">Select…</option>
                  {(spec.options ?? []).map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              ) : spec.type === 'boolean' ? (
                <select
                  value={String(values[spec.name] ?? spec.default ?? 'false')}
                  onChange={(e) =>
                    setValues((prev) => ({
                      ...prev,
                      [spec.name]: e.target.value === 'true',
                    }))
                  }
                  className="mt-1 w-full rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text)"
                >
                  <option value="false">false</option>
                  <option value="true">true</option>
                </select>
              ) : (
                <input
                  type={spec.type === 'number' ? 'number' : 'text'}
                  value={String(values[spec.name] ?? spec.default ?? '')}
                  onChange={(e) =>
                    setValues((prev) => ({
                      ...prev,
                      [spec.name]:
                        spec.type === 'number'
                          ? e.target.value === ''
                            ? ''
                            : Number(e.target.value)
                          : e.target.value,
                    }))
                  }
                  className="mt-1 w-full rounded-md border border-(--color-border) bg-(--bg-subtle) px-2 py-1.5 text-xs text-(--color-text) outline-none focus:border-(--color-accent)"
                />
              )}
            </label>
          ))}
          {error && <p className="text-[11px] text-(--color-error)">{error}</p>}
        </div>
        <DialogFooter className="mx-0 mb-0 flex-row items-center justify-end gap-2 border-t border-(--color-border) px-5 py-3">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={submitting}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => void handleRun()}
            disabled={submitting || missingRequired}
          >
            {submitting ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Play size={12} />
            )}
            Run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
