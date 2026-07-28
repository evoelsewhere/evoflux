/**
 * AimSetupWizard — 2-step setup for an AIM migration project
 * (aim-mode-shell-ux-spec.md v2.2 §3.4/§5.4).
 *
 * Step 1: pick the project ROOT folder (convention:
 *   <name>/{aim_source_base/*, aim_<name>_document, aim_target_source})
 *   and run detection. Every 422 from detect names exactly what's missing
 *   and is shown verbatim.
 * Step 2: review what was detected. Create vs join is NOT a user choice —
 *   has_manifest decides (aim.yaml already in the document repo → join).
 */

import { useCallback, useState } from 'react'
import { Check, FolderPlus, FolderSearch, Loader2, TriangleAlert } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { previewAimManifest } from '@/api/client'
import {
  useCreateAimProjectMutation,
  useDetectAimLayoutMutation,
  useJoinAimProjectMutation,
} from '@/queries/useAimProjectsQuery'
import { usePlatform } from '@/hooks/use-platform'
import { useIsMobile } from '@/hooks/use-mobile'
import type { AimLayoutDetection, AimManifestPreview } from '@/api/types'

interface AimSetupWizardProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (projectId: string) => void
}

function StepIndicator({ step }: { step: 1 | 2 }) {
  return (
    <div className="flex items-center gap-2">
      {[1, 2].map((i) => (
        <div
          key={i}
          className={cn(
            'h-1.5 rounded-full transition-[width,background-color] duration-(--motion-base)',
            i < step
              ? 'w-4 bg-(--color-success)'
              : i === step
                ? 'w-6 bg-(--color-accent)'
                : 'w-4 bg-(--border-subtle)',
          )}
        />
      ))}
    </div>
  )
}

function RoleRow({ label, value, badge }: { label: string; value: string; badge?: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-20 shrink-0 text-(--color-text-muted)">{label}</span>
      <span className="min-w-0 flex-1 truncate text-(--color-text)" title={value}>
        {value}
      </span>
      {badge && (
        <span className="shrink-0 rounded bg-(--bg-key) px-1.5 py-0.5 text-[10px] text-(--color-text-subtle)">
          {badge}
        </span>
      )}
    </div>
  )
}

export function AimSetupWizard({ open, onOpenChange, onCreated }: AimSetupWizardProps) {
  const { isTauri } = usePlatform()
  const isMobile = useIsMobile()
  const [step, setStep] = useState<1 | 2>(1)
  const [rootPath, setRootPath] = useState('')
  const [detection, setDetection] = useState<AimLayoutDetection | null>(null)
  const [manifest, setManifest] = useState<AimManifestPreview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const detect = useDetectAimLayoutMutation()
  const createProject = useCreateAimProjectMutation()
  const joinProject = useJoinAimProjectMutation()

  const reset = useCallback(() => {
    setStep(1)
    setRootPath('')
    setDetection(null)
    setManifest(null)
    setError(null)
    setSubmitting(false)
  }, [])

  const handleClose = useCallback(() => {
    onOpenChange(false)
    setTimeout(reset, 300)
  }, [onOpenChange, reset])

  const pickFolder = useCallback(async (): Promise<string | null> => {
    if (!isTauri || isMobile) return null
    try {
      const { open: openDialog } = await import('@tauri-apps/plugin-dialog')
      const selected = await openDialog({
        directory: true,
        multiple: false,
        title: 'Select the project root folder',
      })
      return typeof selected === 'string' ? selected : null
    } catch {
      return null
    }
  }, [isTauri, isMobile])

  const handleBrowse = useCallback(async () => {
    const selected = await pickFolder()
    if (selected) setRootPath(selected)
  }, [pickFolder])

  const handleDetect = useCallback(async () => {
    if (!rootPath.trim()) return
    setError(null)
    setManifest(null)
    try {
      const result = await detect.mutateAsync(rootPath.trim())
      setDetection(result)
      if (result.has_manifest) {
        // Join review shows the manifest's rulebook rather than a picker.
        try {
          setManifest(await previewAimManifest(result.kb_path))
        } catch {
          // Detection already warned; the join call will surface real errors.
        }
      }
      setStep(2)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Folder does not match the AIM layout.')
    }
  }, [rootPath, detect])

  const handleSubmit = useCallback(async () => {
    if (!detection) return
    setSubmitting(true)
    setError(null)
    try {
      const project = detection.has_manifest
        ? await joinProject.mutateAsync({
            name: detection.project_name,
            kb_path: detection.kb_path,
            source_paths: detection.source_paths,
            target_path: detection.target_path,
          })
        : await createProject.mutateAsync({
            name: detection.project_name,
            source_paths: detection.source_paths,
            target_path: detection.target_path,
            kb_path: detection.kb_path,
          })
      onCreated?.(project.id)
      handleClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set up the AIM project.')
    } finally {
      setSubmitting(false)
    }
  }, [detection, createProject, joinProject, onCreated, handleClose])

  const mode = detection?.has_manifest ? 'join' : 'create'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-(--color-border) px-5 pb-4 pt-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FolderPlus size={16} className="text-(--color-accent)" />
              <DialogTitle className="text-sm font-semibold">
                New / Join migration project
              </DialogTitle>
            </div>
            <StepIndicator step={step} />
          </div>
          <DialogDescription className="mt-1 text-xs text-(--color-text-muted)">
            {step === 1
              ? 'Pick the project root folder — roles are detected from its layout.'
              : mode === 'join'
                ? 'Existing project detected (aim.yaml found) — review and join.'
                : 'New project — review the detected repositories and local KB.'}
          </DialogDescription>
        </DialogHeader>

        <div className="min-w-0 px-5 py-4">
          {step === 1 && (
            <div className="space-y-3">
              <label className="block text-xs font-medium text-(--color-text)">
                Project root folder
              </label>
              <div className="flex gap-2">
                <input
                  autoFocus
                  type="text"
                  value={rootPath}
                  onChange={(e) => setRootPath(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void handleDetect()
                  }}
                  placeholder="/path/to/<project_name>"
                  className={cn(
                    'flex-1 rounded-md border border-(--color-border) bg-(--bg-subtle)',
                    'px-3 py-2 text-xs text-(--color-text) placeholder:text-(--color-text-muted)',
                    'outline-none focus:border-(--color-accent)',
                  )}
                />
                {isTauri && !isMobile && (
                  <Button size="sm" variant="secondary" onClick={() => void handleBrowse()}>
                    Browse…
                  </Button>
                )}
              </div>
              <div className="rounded-md bg-(--bg-key) px-3 py-2 font-mono text-[10px] leading-4 text-(--color-text-subtle)">
                {'<project_name>/'}
                <br />
                {'├─ aim_source_base/          # legacy repos'}
                <br />
                {'├─ aim_<project_name>_document/   # shared KB repo'}
                <br />
                {'└─ aim_target_source/        # scaffolded target'}
              </div>
              {error && <p className="text-[11px] text-(--color-error)">{error}</p>}
            </div>
          )}

          {step === 2 && detection && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Check size={14} className="shrink-0 text-(--color-success)" />
                <span className="text-sm font-semibold text-(--color-text)">
                  {detection.project_name}
                </span>
                <span className="rounded bg-(--bg-key) px-1.5 py-0.5 text-[10px] uppercase text-(--color-text-subtle)">
                  {mode}
                </span>
              </div>

              <div className="space-y-1.5 rounded-md border border-(--color-border) bg-(--bg-subtle) px-3 py-2.5">
                {detection.source_paths.map((path) => (
                  <RoleRow
                    key={path}
                    label="Source"
                    value={path.split(/[\\/]/).filter(Boolean).pop() ?? path}
                    badge="read-only"
                  />
                ))}
                <RoleRow
                  label="Document"
                  value={detection.kb_path.split(/[\\/]/).filter(Boolean).pop() ?? detection.kb_path}
                  badge="KB"
                />
                <RoleRow
                  label="Target"
                  value={
                    detection.target_path.split(/[\\/]/).filter(Boolean).pop() ??
                    detection.target_path
                  }
                />
              </div>

              {mode === 'create' ? (
                <div className="space-y-1 border-l-2 border-(--color-accent) pl-3">
                  <p className="text-xs font-medium text-(--color-text)">
                    Project-owned rulebook
                  </p>
                  <p className="text-[11px] leading-4 text-(--color-text-subtle)">
                    A safe sample will be scaffolded at <code>rulebook/</code> in the document
                    repository. Adapt its stack rules there; lifecycle capabilities remain
                    blocked until the project marks them ready.
                  </p>
                </div>
              ) : (
                <div className="space-y-1.5">
                  {manifest && (
                    <p className="text-xs text-(--color-text-2)">
                      Rulebook: <span className="font-medium">{manifest.rulebook_id}</span> v
                      {manifest.rulebook_version}
                    </p>
                  )}
                  {Object.entries(detection.source_identity_map).map(([identity, path]) => (
                    <div key={identity} className="flex items-center gap-1.5 text-[11px]">
                      {path ? (
                        <Check size={11} className="shrink-0 text-(--color-success)" />
                      ) : (
                        <TriangleAlert size={11} className="shrink-0 text-(--color-error)" />
                      )}
                      <span className="truncate text-(--color-text-muted)">{identity}</span>
                      <span className="text-(--color-text-subtle)">
                        {path ? '→ matched' : '→ not found in layout'}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {detection.warnings.map((warning) => (
                <p key={warning} className="flex items-start gap-1.5 text-[11px] text-(--color-text-muted)">
                  <TriangleAlert size={11} className="mt-0.5 shrink-0" />
                  {warning}
                </p>
              ))}
              {error && <p className="text-[11px] text-(--color-error)">{error}</p>}
            </div>
          )}
        </div>

        <DialogFooter
          className={cn(
            'mx-0 mb-0 flex-row items-center justify-between sm:justify-between',
            'border-t border-(--color-border) px-5 py-3',
          )}
        >
          <div>
            {step === 2 && (
              <Button variant="ghost" size="sm" onClick={() => setStep(1)} disabled={submitting}>
                Back
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={handleClose} disabled={submitting}>
              Cancel
            </Button>
            {step === 1 ? (
              <Button
                size="sm"
                onClick={() => void handleDetect()}
                disabled={!rootPath.trim() || detect.isPending}
              >
                {detect.isPending ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <FolderSearch size={12} />
                )}
                Detect
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={() => void handleSubmit()}
                disabled={submitting}
              >
                {submitting && <Loader2 size={12} className="animate-spin" />}
                {mode === 'join' ? 'Join project' : 'Create project'}
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
