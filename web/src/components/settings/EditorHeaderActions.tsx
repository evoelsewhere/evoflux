/**
 * EditorHeaderActions — status + Save cluster for the agent / skill / MCP
 * editors, handed to `SettingsPage` as its header actions.
 *
 * Layout (left → right):
 *
 *   [Form/Raw]  ● Unsaved   [Save]
 *
 * The Form/Raw toggle is optional; the skill editor (which has only a raw
 * mode) hides it by leaving ``mode`` unset.
 */
import { AlertCircle, Code2, FormInput, Plus, Save } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

interface EditorHeaderActionsProps {
  /** Whether the editor's working copy differs from the persisted one. */
  dirty: boolean
  /** Whether the working copy has zod validation errors. */
  invalid: boolean
  /** Whether a save mutation is currently in flight. */
  saving: boolean
  /** Latest save / create error message — surfaced inline. */
  error?: string | null
  /** First validation error message (when ``invalid``) — shown as a hint. */
  validationHint?: string | null
  /** Form/Raw toggle. Hide by leaving both ``mode`` and ``onModeChange`` unset. */
  mode?: 'form' | 'raw'
  onModeChange?: (next: 'form' | 'raw') => void
  /** Optional reason to disable saving even when the draft is dirty and valid. */
  saveDisabledReason?: string | null
  /** Override the primary action label, e.g. "Create agent" on new-item pages. */
  saveLabel?: string
  /** Save handler; the button manages its own disabled state. */
  onSave: () => void
}

export function EditorHeaderActions({
  dirty,
  invalid,
  saving,
  error,
  validationHint,
  saveDisabledReason,
  saveLabel = 'Save',
  mode,
  onModeChange,
  onSave,
}: EditorHeaderActionsProps) {
  const showToggle = mode != null && onModeChange != null

  // Save is disabled when there is nothing to save, when the draft is
  // invalid, or when a save is already in flight.
  const saveDisabled = Boolean(saveDisabledReason) || !dirty || invalid || saving
  const saveTooltip = saveDisabledReason
    ? saveDisabledReason
    : invalid
      ? (validationHint ?? 'Fix validation errors')
      : !dirty
        ? 'No unsaved changes'
        : null
  const actionLabel = saving
    ? saveLabel === 'Save'
      ? 'Saving…'
      : 'Creating…'
    : saveLabel
  const ActionIcon = saveLabel === 'Save' ? Save : Plus

  return (
    <div className="flex items-center gap-2">
      {showToggle && (
        <Tabs value={mode} onValueChange={(v) => onModeChange(v as 'form' | 'raw')}>
          <TabsList className="h-7">
            <TabsTrigger value="form" className="px-2 text-xs">
              <FormInput size={11} aria-hidden="true" />
              Form
            </TabsTrigger>
            <TabsTrigger value="raw" className="px-2 text-xs">
              <Code2 size={11} aria-hidden="true" />
              Raw
            </TabsTrigger>
          </TabsList>
        </Tabs>
      )}

      {error && (
        <Tooltip>
          <TooltipTrigger
            render={
              <span className="flex items-center gap-1 rounded-md bg-(--color-error-subtle) px-2 py-1 text-xs text-(--color-error)">
                <AlertCircle size={11} />
                Error
              </span>
            }
          />
          <TooltipContent>{error}</TooltipContent>
        </Tooltip>
      )}
      {!error && invalid && validationHint && (
        <Tooltip>
          <TooltipTrigger
            render={
              <span className="flex items-center gap-1 rounded-md bg-(--color-error-subtle) px-2 py-1 text-xs text-(--color-error)">
                <AlertCircle size={11} />
                Invalid
              </span>
            }
          />
          <TooltipContent>{validationHint}</TooltipContent>
        </Tooltip>
      )}
      {!error && !invalid && dirty && (
        <span className="flex items-center gap-1.5 text-xs text-(--color-text-muted)">
          <span
            className={cn(
              'h-1.5 w-1.5 rounded-full bg-(--color-text)',
              saving ? 'animate-pulse' : '',
            )}
            aria-hidden="true"
          />
          Unsaved
        </span>
      )}

      {saveTooltip ? (
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                size="sm"
                className="min-h-11 md:min-h-0"
                onClick={onSave}
                disabled={saveDisabled}
                aria-label={actionLabel}
              >
                <ActionIcon size={12} aria-hidden="true" />
                {actionLabel}
              </Button>
            }
          />
          <TooltipContent>{saveTooltip}</TooltipContent>
        </Tooltip>
      ) : (
        <Button size="sm" className="min-h-11 md:min-h-0" onClick={onSave} disabled={saveDisabled}>
          <ActionIcon size={12} aria-hidden="true" />
          {actionLabel}
        </Button>
      )}
    </div>
  )
}
