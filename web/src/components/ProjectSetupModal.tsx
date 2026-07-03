/**
 * ProjectSetupModal — multi-step wizard for creating a CodingProject.
 *
 * Step 1: Name the project.
 * Step 2: Add repository folders (using native folder picker on desktop,
 *         path text input on web/mobile).
 * Step 3: Review + create.
 *
 * Calls createProject → addWorkspaceToProject for each repo path.
 */

import { useState, useCallback } from 'react'
import { FolderPlus, FolderOpen, X, Plus, Check, Loader2, GitBranch } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useCreateProjectMutation } from '@/queries/useProjectsQuery'
import { validateWorkspace } from '@/api/client'
import { getAppBackendStatus } from '@/lib/app-backend'
import { apiBaseUrl } from '@/api/base-url'
import { usePlatform } from '@/hooks/use-platform'
import { useIsMobile } from '@/hooks/use-mobile'

function isLocalUrl(value: string): boolean {
  try {
    const h = new URL(value).hostname.toLowerCase()
    return h === 'localhost' || h === '127.0.0.1' || h === '::1' || h === '[::1]'
  } catch {
    return false
  }
}

interface AddedRepo {
  path: string
  name: string
  valid: boolean
}

interface ProjectSetupModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (projectId: string) => void
}

// ── Step indicator ─────────────────────────────────────────────────────────

function StepIndicator({ step, total }: { step: number; total: number }) {
  return (
    <div className="flex items-center gap-2">
      {Array.from({ length: total }).map((_, i) => (
        <div
          key={i}
          className={cn(
            'h-1.5 rounded-full transition-all duration-300',
            i < step - 1
              ? 'w-4 bg-(--color-success)'
              : i === step - 1
                ? 'w-6 bg-(--color-accent)'
                : 'w-4 bg-(--border-subtle)',
          )}
        />
      ))}
    </div>
  )
}

// ── Repo row ───────────────────────────────────────────────────────────────

function RepoRow({
  repo,
  onRemove,
}: {
  repo: AddedRepo
  onRemove: () => void
}) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-(--color-border) bg-(--bg-subtle) px-3 py-2">
      <GitBranch size={13} className="shrink-0 text-(--color-text-muted)" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium text-(--color-text)">{repo.name}</p>
        <p className="truncate text-[10px] text-(--color-text-muted)">{repo.path}</p>
      </div>
      {repo.valid ? (
        <Check size={12} className="shrink-0 text-green-500" />
      ) : (
        <span className="text-[10px] text-amber-400">?</span>
      )}
      <button
        type="button"
        onClick={onRemove}
        className="shrink-0 rounded p-0.5 text-(--color-text-muted) hover:text-(--color-text)"
        aria-label="Remove repo"
      >
        <X size={12} />
      </button>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────

export function ProjectSetupModal({ open, onOpenChange, onCreated }: ProjectSetupModalProps) {
  const { isTauri } = usePlatform()
  const isTauriMobile = useIsMobile()
  const [step, setStep] = useState(1)
  const [name, setName] = useState('')
  const [repos, setRepos] = useState<AddedRepo[]>([])
  const [pathInput, setPathInput] = useState('')
  const [addingRepo, setAddingRepo] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const createProject = useCreateProjectMutation()

  const reset = useCallback(() => {
    setStep(1)
    setName('')
    setRepos([])
    setPathInput('')
    setAddError(null)
    setSubmitError(null)
    setSubmitting(false)
  }, [])

  const handleClose = useCallback(() => {
    onOpenChange(false)
    setTimeout(reset, 300)
  }, [onOpenChange, reset])

  // ── Folder picker ──────────────────────────────────────────────────────────

  const pickFolder = useCallback(async (): Promise<string | null> => {
    if (!isTauri || isTauriMobile) return null

    const backendBase = apiBaseUrl().replace(/\/api\/?$/, '')
    const backend = await getAppBackendStatus()
    const activeBase = backend?.base_url ?? backendBase
    if ((backend?.external || !backend) && !isLocalUrl(activeBase)) return null

    try {
      const { open } = await import('@tauri-apps/plugin-dialog')
      const selected = await open({ directory: true, multiple: false, title: 'Add repository' })
      return typeof selected === 'string' ? selected : null
    } catch {
      return null
    }
  }, [isTauri, isTauriMobile])

  const addRepoByPath = useCallback(async (path: string) => {
    if (!path.trim()) return
    if (repos.some((r) => r.path === path)) {
      setAddError('This repo is already added.')
      return
    }
    setAddingRepo(true)
    setAddError(null)
    try {
      // validateWorkspace returns { workspace: string } — the resolved absolute
      // path. Derive the repo display name from its last path segment.
      const result = await validateWorkspace(path)
      const resolved = result.workspace
      const name = resolved.split(/[\\/]/).filter(Boolean).pop() || path
      setRepos((prev) => [...prev, { path, name, valid: true }])
      setPathInput('')
    } catch {
      // Workspace validation failed but we still allow adding it
      const name = path.split(/[\\/]/).pop() || path
      setRepos((prev) => [...prev, { path, name, valid: false }])
      setPathInput('')
    } finally {
      setAddingRepo(false)
    }
  }, [repos])

  const handlePickFolder = useCallback(async () => {
    setAddError(null)
    const selected = await pickFolder()
    if (selected) {
      await addRepoByPath(selected)
    } else if (!isTauri || isTauriMobile) {
      // Show path input on web builds
      setPathInput('')
    }
  }, [pickFolder, addRepoByPath, isTauri, isTauriMobile])

  const handlePathSubmit = useCallback(async () => {
    await addRepoByPath(pathInput.trim())
  }, [pathInput, addRepoByPath])

  // ── Create project ─────────────────────────────────────────────────────────

  const handleCreate = useCallback(async () => {
    if (!name.trim() || repos.length === 0) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const project = await createProject.mutateAsync({
        name: name.trim(),
        workspace_paths: repos.map((r) => r.path),
      })
      onCreated?.(project.id)
      handleClose()
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to create project')
    } finally {
      setSubmitting(false)
    }
  }, [name, repos, createProject, onCreated, handleClose])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md gap-0 p-0 overflow-hidden">
        <DialogHeader className="border-b border-(--color-border) px-5 pt-5 pb-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FolderPlus size={16} className="text-(--color-accent)" />
              <DialogTitle className="text-sm font-semibold">New Project</DialogTitle>
            </div>
            <StepIndicator step={step} total={3} />
          </div>
          <DialogDescription className="text-xs text-(--color-text-muted) mt-1">
            {step === 1 && 'Give your multi-repo project a name.'}
            {step === 2 && 'Add the repositories that belong to this project.'}
            {step === 3 && 'Review and create your project.'}
          </DialogDescription>
        </DialogHeader>

        {/*
          min-w-0: DialogContent is a CSS grid with an implicit auto-sized
          column. Without this, a long un-wrapped repo path (`truncate` sets
          white-space:nowrap) contributes its full un-truncated max-content
          width to the grid track's intrinsic sizing, stretching the whole
          dialog's column — and with it the footer below — wider than the
          dialog itself, clipping the trailing footer button.
        */}
        <div className="min-w-0 px-5 py-4">
          {/* Step 1 — Name */}
          {step === 1 && (
            <div className="space-y-3">
              <label className="block text-xs font-medium text-(--color-text)">
                Project name
              </label>
              <input
                autoFocus
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && name.trim()) setStep(2) }}
                placeholder="e.g. Auth Platform"
                className={cn(
                  'w-full rounded-md border border-(--color-border) bg-(--bg-subtle)',
                  'px-3 py-2 text-sm text-(--color-text) placeholder:text-(--color-text-muted)',
                  'outline-none focus:border-(--color-accent) focus:ring-1 focus:ring-(--color-accent)/30',
                )}
              />
              <p className="text-[11px] text-(--color-text-muted)">
                A project groups 2–20 repositories that belong to the same product or service.
              </p>
            </div>
          )}

          {/* Step 2 — Repos */}
          {step === 2 && (
            <div className="space-y-3">
              {repos.length > 0 && (
                <div className="space-y-1.5 max-h-48 overflow-y-auto">
                  {repos.map((repo, i) => (
                    <RepoRow
                      key={repo.path}
                      repo={repo}
                      onRemove={() => setRepos((prev) => prev.filter((_, j) => j !== i))}
                    />
                  ))}
                </div>
              )}

              {/* Add by folder picker (desktop) or path input (web) */}
              {(!isTauri || isTauriMobile) ? (
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={pathInput}
                    onChange={(e) => setPathInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') void handlePathSubmit() }}
                    placeholder="/absolute/path/to/repo"
                    className={cn(
                      'flex-1 rounded-md border border-(--color-border) bg-(--bg-subtle)',
                      'px-3 py-2 text-xs text-(--color-text) placeholder:text-(--color-text-muted)',
                      'outline-none focus:border-(--color-accent)',
                    )}
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void handlePathSubmit()}
                    disabled={!pathInput.trim() || addingRepo}
                  >
                    {addingRepo ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                  </Button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => void handlePickFolder()}
                  disabled={addingRepo}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-md border border-dashed border-(--color-border)',
                    'px-3 py-2.5 text-xs text-(--color-text-muted) transition-colors',
                    'hover:border-(--color-accent)/40 hover:bg-(--bg-hover) hover:text-(--color-text)',
                    'disabled:opacity-50',
                  )}
                >
                  {addingRepo ? (
                    <Loader2 size={13} className="shrink-0 animate-spin" />
                  ) : (
                    <FolderOpen size={13} className="shrink-0" />
                  )}
                  Add repository…
                </button>
              )}

              {addError && (
                <p className="text-[11px] text-red-400">{addError}</p>
              )}

              {repos.length === 0 && (
                <p className="text-[11px] text-(--color-text-muted)">
                  Add at least one repository. You can add more later.
                </p>
              )}
            </div>
          )}

          {/* Step 3 — Review */}
          {step === 3 && (
            <div className="space-y-3">
              <div className="rounded-md border border-(--color-border) bg-(--bg-subtle) px-4 py-3 space-y-2">
                <div className="flex items-center gap-2">
                  <FolderPlus size={14} className="text-(--color-accent)" />
                  <span className="text-sm font-semibold text-(--color-text)">{name}</span>
                </div>
                <p className="text-[11px] text-(--color-text-muted)">
                  {repos.length} {repos.length === 1 ? 'repository' : 'repositories'}
                </p>
                <div className="space-y-1 pt-1">
                  {repos.map((repo) => (
                    <div key={repo.path} className="flex items-center gap-2">
                      <GitBranch size={11} className="shrink-0 text-(--color-text-muted)" />
                      <span className="text-xs text-(--color-text-muted) truncate">{repo.name}</span>
                    </div>
                  ))}
                </div>
              </div>
              {submitError && (
                <p className="text-[11px] text-red-400">{submitError}</p>
              )}
            </div>
          )}
        </div>

        <DialogFooter
          className={cn(
            // Cancel DialogFooter's default edge-to-edge bleed (-mx-4 -mb-4,
            // meant to offset DialogContent's own padding) — this dialog uses
            // p-0 on DialogContent instead, so nothing needs offsetting, and
            // left uncancelled the negative margin pushes the footer wider
            // than the dialog. Also force row/justify-between at every size
            // (not just sm:) so it wins outright over the default's
            // sm:justify-end rather than depending on cascade/source order.
            'mx-0 mb-0 flex-row items-center justify-between sm:justify-between',
            'border-t border-(--color-border) px-5 py-3',
          )}
        >
          <div className="flex items-center gap-2">
            {step > 1 && (
              <Button variant="ghost" size="sm" onClick={() => setStep((s) => s - 1)} disabled={submitting}>
                Back
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={handleClose} disabled={submitting}>
              Cancel
            </Button>
            {step < 3 ? (
              <Button
                size="sm"
                onClick={() => setStep((s) => s + 1)}
                disabled={
                  (step === 1 && !name.trim()) ||
                  (step === 2 && repos.length === 0)
                }
              >
                Next
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={() => void handleCreate()}
                disabled={submitting}
              >
                {submitting ? (
                  <>
                    <Loader2 size={12} className="mr-1.5 animate-spin" />
                    Creating…
                  </>
                ) : (
                  'Create project'
                )}
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
