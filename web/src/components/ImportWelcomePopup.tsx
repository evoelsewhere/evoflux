/**
 * ImportWelcomePopup — first-run popup asking the user if they want to import
 * data from another AI tool.
 *
 * Shown once after the backend is ready.  Dismissed permanently via
 * localStorage (`STORAGE_KEYS.import.welcomeDismissed`).
 *
 * "Import" navigates to Settings → Import.
 * "Not now" dismisses the popup.
 * "Don't show again" dismisses and sets the localStorage flag.
 */
import { useCallback, useEffect, useState } from 'react'
import { Import } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { STORAGE_KEYS } from '@/lib/storage-keys'
import { saveWelcomeImportKinds } from '@/lib/import-selection'
import { useUIStore } from '@/stores/useUIStore'
import {
  IMPORT_ITEM_KIND_OPTIONS,
  SOURCE_LABELS,
  type ImportItemKind,
  type ImportSource,
} from '@/api/import'

const SOURCES: ImportSource[] = [
  'claude_web',
  'claude_code',
  'chatgpt',
  'codex',
  'cursor',
]

export function ImportWelcomePopup() {
  const [open, setOpen] = useState(false)
  const [dontShow, setDontShow] = useState(false)
  const [selectedKinds, setSelectedKinds] = useState<Set<ImportItemKind>>(
    () => new Set(IMPORT_ITEM_KIND_OPTIONS.map(({ kind }) => kind)),
  )
  const navigateSettings = useUIStore((s) => s.navigateSettings)

  // Show on first run after backend is ready
  useEffect(() => {
    const dismissed = localStorage.getItem(STORAGE_KEYS.import.welcomeDismissed)
    if (dismissed === '1') return
    // Small delay so the popup doesn't flash during initial render
    const timer = setTimeout(() => setOpen(true), 800)
    return () => clearTimeout(timer)
  }, [])

  const close = useCallback(
    (persist: boolean) => {
      setOpen(false)
      if (persist || dontShow) {
        localStorage.setItem(STORAGE_KEYS.import.welcomeDismissed, '1')
      }
    },
    [dontShow],
  )

  const goToImport = useCallback(() => {
    setOpen(false)
    localStorage.setItem(STORAGE_KEYS.import.welcomeDismissed, '1')
    saveWelcomeImportKinds(
      IMPORT_ITEM_KIND_OPTIONS
        .filter(({ kind }) => selectedKinds.has(kind))
        .map(({ kind }) => kind),
    )
    navigateSettings('import')
  }, [navigateSettings, selectedKinds])

  const toggleKind = useCallback((kind: ImportItemKind) => {
    setSelectedKinds((previous) => {
      const next = new Set(previous)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
      return next
    })
  }, [])

  return (
    <Dialog open={open} onOpenChange={(v) => !v && close(false)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Import size={18} className="text-(--color-accent)" />
            Import your data
          </DialogTitle>
          <DialogDescription className="pt-1">
            Choose which data categories to bring into EvoFlux. You can review
            every item before it is imported.
          </DialogDescription>
        </DialogHeader>

        <div className="py-2">
          <p className="mb-3 text-[13px] text-(--color-text-muted)">
            Choose what to import:
          </p>
          <div role="group" aria-label="Data categories to import" className="grid grid-cols-2 gap-2">
            {IMPORT_ITEM_KIND_OPTIONS.map((option) => (
              <label
                key={option.kind}
                className="flex cursor-pointer items-start gap-2 rounded-md border border-(--color-border) p-2.5 hover:bg-(--bg-key)"
              >
                <input
                  type="checkbox"
                  checked={selectedKinds.has(option.kind)}
                  onChange={() => toggleKind(option.kind)}
                  className="mt-0.5 size-4 shrink-0 accent-(--color-accent)"
                />
                <span className="min-w-0">
                  <span className="block text-[13px] font-medium">{option.label}</span>
                  <span className="block text-[11px] text-(--color-text-muted)">{option.description}</span>
                </span>
              </label>
            ))}
          </div>

          <p className="mb-2 mt-4 text-[12px] text-(--color-text-muted)">
            Supported sources:
          </p>
          <div className="flex flex-wrap gap-1.5">
            {SOURCES.map((s) => (
              <span
                key={s}
                className="rounded-full bg-(--bg-key) px-2.5 py-1 text-[12px] font-medium text-(--color-text-muted)"
              >
                {SOURCE_LABELS[s]}
              </span>
            ))}
          </div>
        </div>

        <DialogFooter className="flex-col gap-2 sm:flex-col">
          <Button onClick={goToImport} className="w-full" disabled={selectedKinds.size === 0}>
            Continue to import
          </Button>
          <div className="flex w-full items-center justify-between">
            <label className="flex items-center gap-2 text-[12px] text-(--color-text-muted) cursor-pointer select-none">
              <input
                type="checkbox"
                checked={dontShow}
                onChange={(e) => setDontShow(e.target.checked)}
                className="size-3.5 rounded border-(--color-border) accent-(--color-accent)"
              />
              Don&apos;t show again
            </label>
            <Button variant="ghost" size="sm" onClick={() => close(false)}>
              Not now
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
