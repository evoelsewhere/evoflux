/**
 * Settings → Import — import data from external AI tools.
 *
 * On load: auto-scans local machine for known AI tool data.
 * Shows discovered sources as SettingsRow items with item counts.
 * Manual picker available as fallback.
 * Preview table shows exactly what will be imported.
 */
import { useCallback, useEffect, useState } from 'react'
import { Import, Loader2, CheckCircle2, AlertTriangle, RefreshCw } from 'lucide-react'

import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import {
  type DetectResponse,
  type ExecuteResponse,
  type ImportSource,
  type ScanResult,
  type HistoryEntry,
  SOURCE_LABELS,
  pickImportSource,
  detectImport,
  executeImport,
  cancelImport,
  updateItemAction,
  scanLocalSources,
  getImportHistory,
} from '@/api/import'
import { Button } from '@/components/ui/button'
import { SelectControl } from '@/components/ui/select'
import { cn } from '@/lib/utils'

type Phase = 'scanning' | 'idle' | 'detecting' | 'preview' | 'executing' | 'done'

export function ImportSettingsPage() {
  const [phase, setPhase] = useState<Phase>('scanning')
  const [error, setError] = useState<string | null>(null)
  const [discovered, setDiscovered] = useState<ScanResult[]>([])
  const [detectResult, setDetectResult] = useState<DetectResponse | null>(null)
  const [executeResult, setExecuteResult] = useState<ExecuteResponse | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)

  // Auto-scan on mount
  useEffect(() => {
    scanLocalSources()
      .then((res) => {
        setDiscovered(res.discovered)
        setPhase('idle')
      })
      .catch(() => setPhase('idle'))
  }, [])

  // Load history
  useEffect(() => {
    getImportHistory()
      .then((res) => setHistory(res.imports))
      .catch(() => {})
      .finally(() => setHistoryLoading(false))
  }, [])

  const handleDetect = useCallback(async (path: string, source?: string) => {
    setError(null)
    setExecuteResult(null)
    setPhase('detecting')
    try {
      const result = await detectImport(path, source as ImportSource | undefined)
      setDetectResult(result)
      setPhase('preview')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPhase('idle')
    }
  }, [])

  const handlePickFile = useCallback(async (source: ImportSource) => {
    const path = await pickImportSource(source)
    if (path) handleDetect(path, source)
  }, [handleDetect])

  const handleExecute = useCallback(async () => {
    if (!detectResult) return
    setPhase('executing')
    setError(null)
    try {
      const result = await executeImport(detectResult.import_id)
      setExecuteResult(result)
      setPhase('done')
      // Refresh history
      getImportHistory().then((res) => setHistory(res.imports)).catch(() => {})
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPhase('preview')
    }
  }, [detectResult])

  const handleCancel = useCallback(async () => {
    if (detectResult) await cancelImport(detectResult.import_id).catch(() => {})
    setDetectResult(null)
    setExecuteResult(null)
    setError(null)
    setPhase('idle')
  }, [detectResult])

  const handleActionChange = useCallback(
    async (index: number, action: 'import' | 'skip' | 'replace' | 'rename') => {
      if (!detectResult) return
      try {
        await updateItemAction(detectResult.import_id, index, action)
        setDetectResult((prev) => {
          if (!prev) return prev
          const items = [...prev.items]
          items[index] = { ...items[index], action }
          return { ...prev, items }
        })
      } catch { /* ignore */ }
    },
    [detectResult],
  )

  const handleRescan = useCallback(() => {
    setPhase('scanning')
    scanLocalSources()
      .then((res) => {
        setDiscovered(res.discovered)
        setPhase('idle')
      })
      .catch(() => setPhase('idle'))
  }, [])

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <SettingsPage
      icon={Import}
      title="Import"
      lede="Bring data from Claude, ChatGPT, Codex, Cursor, and other AI tools into EvoFlux."
    >
      {/* ── Error ──────────────────────────────────────────────────────── */}
      {error && (
        <SettingsCallout tone="error">
          <div className="flex items-start justify-between gap-2">
            <span>{error}</span>
            <button type="button" onClick={() => setError(null)} className="shrink-0 text-(--color-text-muted) hover:text-(--color-text)">
              <span className="sr-only">Dismiss</span>
              &times;
            </button>
          </div>
        </SettingsCallout>
      )}

      {/* ── Preview (when active) ──────────────────────────────────────── */}
      {phase === 'preview' && detectResult && (
        <ImportPreview
          result={detectResult}
          onActionChange={handleActionChange}
          onExecute={handleExecute}
          onCancel={handleCancel}
        />
      )}

      {/* ── Executing ──────────────────────────────────────────────────── */}
      {phase === 'executing' && (
        <SettingsCallout tone="info">
          <span className="flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" />
            Importing...
          </span>
        </SettingsCallout>
      )}

      {/* ── Done ───────────────────────────────────────────────────────── */}
      {phase === 'done' && executeResult && (
        <ImportResult result={executeResult} onReset={handleCancel} />
      )}

      {/* ── Discovered sources ─────────────────────────────────────────── */}
      {(phase === 'idle' || phase === 'scanning') && (
        <>
          <SettingsGroup
            title="Discovered on this machine"
            actions={
              <Button variant="ghost" size="sm" onClick={handleRescan} disabled={phase === 'scanning'}>
                <RefreshCw size={14} className={phase === 'scanning' ? 'animate-spin' : ''} />
              </Button>
            }
          >
            {phase === 'scanning' && (
              <div className="flex items-center gap-2 px-4 py-6 text-[13px] text-(--color-text-muted)">
                <Loader2 size={14} className="animate-spin" />
                Scanning for AI tool data...
              </div>
            )}
            {phase === 'idle' && discovered.length === 0 && (
              <div className="px-4 py-6 text-[13px] text-(--color-text-muted)">
                No AI tool data found automatically. Use the manual import below.
              </div>
            )}
            {phase === 'idle' && discovered.map((item) => (
              <SettingsRow
                key={`${item.source}:${item.path}`}
                label={item.label}
                description={
                  <>
                    {item.description || item.path}
                    {item.estimated_items > 0 && (
                      <span className="ml-2 text-[11px] text-(--color-accent)">
                        ({item.estimated_items} item{item.estimated_items !== 1 ? 's' : ''})
                      </span>
                    )}
                  </>
                }
                control={
                  <Button size="sm" onClick={() => handleDetect(item.path, item.source)}>
                    Import
                  </Button>
                }
              />
            ))}
          </SettingsGroup>

          <SettingsGroup title="Manual import">
            <SettingsRow
              label="Select a file or folder"
              description="Pick an export file or AI tool directory from anywhere on your machine."
              control={
                <div className="flex flex-wrap gap-1.5">
                  {(Object.keys(SOURCE_LABELS) as ImportSource[]).map((source) => (
                    <Button
                      key={source}
                      variant="outline"
                      size="sm"
                      onClick={() => handlePickFile(source)}
                    >
                      {SOURCE_LABELS[source]}
                    </Button>
                  ))}
                </div>
              }
            />
          </SettingsGroup>
        </>
      )}

      {/* ── Detecting spinner ──────────────────────────────────────────── */}
      {phase === 'detecting' && (
        <SettingsCallout tone="info">
          <span className="flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" />
            Analysing source...
          </span>
        </SettingsCallout>
      )}

      {/* ── History ────────────────────────────────────────────────────── */}
      {!historyLoading && history.length > 0 && (
        <SettingsGroup title="Previous imports">
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-(--color-border-subtle) text-left text-(--color-text-muted)">
                  <th className="px-4 py-2 font-medium">Source</th>
                  <th className="px-4 py-2 font-medium">Items</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Date</th>
                </tr>
              </thead>
              <tbody>
                {history.slice(0, 10).map((entry) => {
                  const label = SOURCE_LABELS[entry.source as ImportSource] ?? entry.source
                  const total = Object.values(entry.imported).reduce((a, b) => a + b, 0)
                  const date = entry.created_at ? new Date(entry.created_at).toLocaleDateString() : '—'
                  return (
                    <tr key={entry.import_id} className="border-b border-(--color-border-subtle) last:border-0">
                      <td className="px-4 py-2 font-medium">{label}</td>
                      <td className="px-4 py-2 text-(--color-text-muted)">
                        {total} imported
                        {entry.error_count > 0 && (
                          <span className="ml-1 text-(--color-error)">, {entry.error_count} errors</span>
                        )}
                      </td>
                      <td className="px-4 py-2">
                        <span className={cn(
                          'rounded-full px-2 py-0.5 text-[11px] font-medium',
                          entry.status === 'completed'
                            ? 'bg-(--color-success)/10 text-(--color-success)'
                            : 'bg-(--color-warning)/10 text-(--color-warning)',
                        )}>
                          {entry.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-(--color-text-muted)">{date}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </SettingsGroup>
      )}
    </SettingsPage>
  )
}

// ── Preview sub-component ───────────────────────────────────────────────────

function ImportPreview({
  result,
  onActionChange,
  onExecute,
  onCancel,
}: {
  result: DetectResponse
  onActionChange: (index: number, action: 'import' | 'skip' | 'replace' | 'rename') => void
  onExecute: () => void
  onCancel: () => void
}) {
  const importCount = result.items.filter((it) => it.action === 'import').length
  const conflictCount = result.items.filter((it) => it.conflicts.length > 0).length

  // Group items by kind for summary
  const kindCounts: Record<string, number> = {}
  for (const item of result.items) {
    kindCounts[item.kind] = (kindCounts[item.kind] || 0) + 1
  }

  return (
    <SettingsGroup title={`Preview — ${SOURCE_LABELS[result.detected_source as ImportSource] ?? result.detected_source}`}>
      {/* Summary badges */}
      <div className="flex flex-wrap gap-2 px-4 py-3">
        {Object.entries(kindCounts).map(([kind, count]) => (
          <span key={kind} className="rounded-full bg-(--bg-key) px-2.5 py-1 text-[12px] font-medium text-(--color-text-muted)">
            {count} {kind}{count !== 1 ? 's' : ''}
          </span>
        ))}
        {conflictCount > 0 && (
          <span className="rounded-full bg-(--color-warning)/10 px-2.5 py-1 text-[12px] font-medium text-(--color-warning)">
            {conflictCount} conflict{conflictCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Items table */}
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-(--color-border-subtle) text-left text-(--color-text-muted)">
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Details</th>
              <th className="px-4 py-2 font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {result.items.map((item, i) => (
              <PreviewRow key={item.id} item={item} index={i} onActionChange={onActionChange} />
            ))}
          </tbody>
        </table>
      </div>

      {result.warnings.length > 0 && (
        <div className="px-4 py-2 text-[12px] text-(--color-warning)">
          {result.warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 px-4 py-3 border-t border-(--color-border-subtle)">
        <Button onClick={onExecute} disabled={importCount === 0}>
          Import {importCount} item{importCount !== 1 ? 's' : ''}
        </Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </SettingsGroup>
  )
}

function PreviewRow({
  item,
  index,
  onActionChange,
}: {
  item: { id: string; kind: string; label: string; preview: string; action: string; conflicts: string[]; target_name: string }
  index: number
  onActionChange: (index: number, action: 'import' | 'skip' | 'replace' | 'rename') => void
}) {
  const hasConflict = item.conflicts.length > 0

  return (
    <tr className={cn('border-b border-(--color-border-subtle) last:border-0', hasConflict && 'bg-(--color-warning)/5')}>
      <td className="px-4 py-2">
        <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-[11px] font-medium text-(--color-text-muted)">
          {item.kind}
        </span>
      </td>
      <td className="px-4 py-2 font-medium">{item.target_name}</td>
      <td className="px-4 py-2 text-(--color-text-muted)">
        {item.preview}
        {hasConflict && (
          <div className="mt-0.5 flex items-center gap-1 text-[11px] text-(--color-warning)">
            <AlertTriangle size={11} />
            {item.conflicts[0]}
          </div>
        )}
      </td>
      <td className="px-4 py-2">
        <SelectControl
          value={item.action}
          onValueChange={(v) => onActionChange(index, v as 'import' | 'skip' | 'replace' | 'rename')}
          size="sm"
          options={[
            { value: 'import', label: 'Import' },
            { value: 'skip', label: 'Skip' },
            { value: 'replace', label: 'Replace' },
            { value: 'rename', label: 'Rename' },
          ]}
        />
      </td>
    </tr>
  )
}

// ── Result sub-component ────────────────────────────────────────────────────

function ImportResult({
  result,
  onReset,
}: {
  result: ExecuteResponse
  onReset: () => void
}) {
  const totalImported = Object.values(result.imported).reduce((a, b) => a + b, 0)
  const totalSkipped = Object.values(result.skipped).reduce((a, b) => a + b, 0)
  const hasErrors = result.errors.length > 0

  return (
    <SettingsCallout tone={hasErrors ? 'warning' : 'success'}>
      <div className="flex items-start justify-between gap-3">
        <span className="flex items-center gap-2">
          <CheckCircle2 size={14} />
          <span>
            {totalImported} item{totalImported !== 1 ? 's' : ''} imported
            {totalSkipped > 0 && `, ${totalSkipped} skipped`}
            {hasErrors && `, ${result.errors.length} error${result.errors.length !== 1 ? 's' : ''}`}
          </span>
        </span>
        <Button variant="ghost" size="sm" onClick={onReset}>Import more</Button>
      </div>
      {hasErrors && (
        <div className="mt-2 space-y-1 text-[12px] text-(--color-error)">
          {result.errors.map((err, i) => (
            <div key={i}><strong>{err.item}</strong>: {err.error}</div>
          ))}
        </div>
      )}
    </SettingsCallout>
  )
}
