/**
 * Settings → Import — import data from external AI tools.
 *
 * On load: auto-scans local machine for known AI tool data.
 * Shows discovered sources as SettingsRow items with item counts.
 * Manual picker available as fallback.
 * Preview table shows exactly what will be imported.
 */
import { useCallback, useEffect, useState } from 'react'
import { Import, Loader2, CheckCircle2, AlertTriangle, RefreshCw, Search, ChevronLeft, ChevronRight } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

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
  type ImportJobDetail,
  type AutoSyncSettings,
  type ImportItemAction,
  type BulkImportItemAction,
  type ImportItemKind,
  IMPORT_ITEM_KIND_OPTIONS,
  SOURCE_LABELS,
  pickImportSource,
  detectImport,
  executeImport,
  cancelImport,
  updateItemAction,
  scanLocalSources,
  getImportHistory,
  getImportJob,
  getAutoSyncSettings,
  updateAutoSyncSettings,
  updateItemsAction,
  undoImport,
} from '@/api/import'
import { queryKeys } from '@/queries/keys'
import { Button } from '@/components/ui/button'
import { SelectControl } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import {
  IMPORT_WELCOME_SELECTION_EVENT,
  takeWelcomeImportKinds,
} from '@/lib/import-selection'
import { notifyImportAutoSyncSettingsChanged } from '@/lib/import-auto-sync'

type Phase = 'scanning' | 'idle' | 'detecting' | 'preview' | 'executing' | 'done'

export function ImportSettingsPage() {
  const queryClient = useQueryClient()
  const [phase, setPhase] = useState<Phase>('scanning')
  const [error, setError] = useState<string | null>(null)
  const [discovered, setDiscovered] = useState<ScanResult[]>([])
  const [detectResult, setDetectResult] = useState<DetectResponse | null>(null)
  const [executeResult, setExecuteResult] = useState<ExecuteResponse | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyDetail, setHistoryDetail] = useState<ImportJobDetail | null>(null)
  const [historyDetailLoading, setHistoryDetailLoading] = useState(false)
  const [manualImportSource, setManualImportSource] = useState<ImportSource | null>(null)
  const [manualImportPath, setManualImportPath] = useState('')
  const [autoSync, setAutoSync] = useState<AutoSyncSettings | null>(null)
  const [undoingImportId, setUndoingImportId] = useState<string | null>(null)
  const [undoMessage, setUndoMessage] = useState<string | null>(null)
  const [welcomeImportKinds, setWelcomeImportKinds] = useState<ImportItemKind[] | null>(null)

  useEffect(() => {
    const applyWelcomeSelection = () => {
      const selectedKinds = takeWelcomeImportKinds()
      if (selectedKinds) setWelcomeImportKinds(selectedKinds)
    }
    applyWelcomeSelection()
    window.addEventListener(IMPORT_WELCOME_SELECTION_EVENT, applyWelcomeSelection)
    return () => window.removeEventListener(IMPORT_WELCOME_SELECTION_EVENT, applyWelcomeSelection)
  }, [])

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

  // Load auto-sync settings
  useEffect(() => {
    getAutoSyncSettings()
      .then((res) => setAutoSync(res))
      .catch(() => {})
  }, [])

  const handleDetect = useCallback(async (path: string, source?: string) => {
    setError(null)
    setExecuteResult(null)
    setPhase('detecting')
    try {
      const detected = await detectImport(path, source as ImportSource | undefined)
      let result = detected
      if (welcomeImportKinds) {
        const selectedKinds = new Set<string>(welcomeImportKinds)
        const skippedIndexes = detected.items.flatMap((item, index) =>
          selectedKinds.has(item.kind) ? [] : [index],
        )
        if (skippedIndexes.length > 0) {
          try {
            await updateItemsAction(detected.import_id, skippedIndexes, 'skip')
          } catch (err) {
            await cancelImport(detected.import_id).catch(() => {})
            throw err
          }
          const skipped = new Set(skippedIndexes)
          result = {
            ...detected,
            items: detected.items.map((item, index) =>
              skipped.has(index) ? { ...item, action: 'skip' } : item,
            ),
          }
        }
      }
      setDetectResult(result)
      setPhase('preview')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPhase('idle')
    }
  }, [welcomeImportKinds])

  const handlePickFile = useCallback(async (source: ImportSource) => {
    setManualImportSource(source)
    setManualImportPath('')
    try {
      const path = await pickImportSource(source)
      if (path) {
        setManualImportSource(null)
        handleDetect(path, source)
      }
    } catch {
      // Browser builds do not have the native picker; expose the path field.
    }
  }, [handleDetect])

  const handleManualPathImport = useCallback(() => {
    const path = manualImportPath.trim()
    if (!path || !manualImportSource) return
    handleDetect(path, manualImportSource)
  }, [handleDetect, manualImportPath, manualImportSource])

  const handleExecute = useCallback(async () => {
    if (!detectResult) return
    const reimportCount = detectResult.items.filter((item) => item.action === 'reimport' || item.action === 'replace').length
    if (reimportCount && !window.confirm(`Re-import ${reimportCount} existing item${reimportCount === 1 ? '' : 's'} and replace the currently imported content?`)) return
    setPhase('executing')
    setError(null)
    try {
      const result = await executeImport(detectResult.import_id)
      setExecuteResult(result)
      setPhase('done')
      // Refresh sidebar sessions and history
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
      getImportHistory().then((res) => setHistory(res.imports)).catch(() => {})
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPhase('preview')
    }
  }, [detectResult, queryClient])

  const handleBulkAction = useCallback(async (indexes: number[], action: BulkImportItemAction) => {
    if (!detectResult) return
    try {
      await updateItemsAction(detectResult.import_id, indexes, action)
      setDetectResult((previous) => {
        if (!previous) return previous
        const items = [...previous.items]
        for (const index of indexes) items[index] = { ...items[index], action }
        return { ...previous, items }
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [detectResult])

  const handleUndo = useCallback(async (entry: HistoryEntry) => {
    if (!entry.undo_available || undoingImportId) return
    const count = entry.undoable_count ?? 0
    if (!window.confirm(`Undo this import? Up to ${count} unchanged EvoFlux item${count === 1 ? '' : 's'} will be removed or restored. Items edited since import will be kept. Source files are not changed.`)) return
    setUndoingImportId(entry.import_id)
    setUndoMessage(null)
    try {
      const result = await undoImport(entry.import_id)
      const skippedDetails = result.items
        .filter((item) => item.outcome === 'undo_skipped')
        .map((item) => `${item.label}: ${item.reason ?? 'left untouched'}`)
      const summary = result.skipped
        ? `Undo completed partially: ${result.undone} changed, ${result.skipped} left untouched.`
        : `Undo complete: ${result.undone} item${result.undone === 1 ? '' : 's'} restored or removed.`
      setUndoMessage([summary, ...skippedDetails].join(' '))
      const updated = await getImportHistory()
      setHistory(updated.imports)
      setHistoryDetail(await getImportJob(entry.import_id))
      void queryClient.invalidateQueries({ queryKey: queryKeys.team.sessions.all() })
    } catch (err) {
      setUndoMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setUndoingImportId(null)
    }
  }, [queryClient, undoingImportId])

  const toggleHistoryDetail = useCallback(async (entry: HistoryEntry) => {
    if (historyDetail?.import_id === entry.import_id) {
      setHistoryDetail(null)
      return
    }
    setHistoryDetailLoading(true)
    setUndoMessage(null)
    try {
      setHistoryDetail(await getImportJob(entry.import_id))
    } catch (err) {
      setUndoMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setHistoryDetailLoading(false)
    }
  }, [historyDetail])

  const handleCancel = useCallback(async () => {
    if (detectResult) await cancelImport(detectResult.import_id).catch(() => {})
    setDetectResult(null)
    setExecuteResult(null)
    setError(null)
    setPhase('idle')
  }, [detectResult])

  const handleActionChange = useCallback(
    async (index: number, action: ImportItemAction) => {
      if (!detectResult) return
      try {
        const updated = await updateItemAction(detectResult.import_id, index, action)
        setDetectResult((prev) => {
          if (!prev) return prev
          const items = [...prev.items]
          items[index] = { ...items[index], action, target_name: updated.target_name }
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

  const handleAutoSyncToggle = useCallback(async (enabled: boolean) => {
    try {
      const updated = await updateAutoSyncSettings({ enabled })
      setAutoSync(updated)
      notifyImportAutoSyncSettingsChanged(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
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
          welcomeImportKinds={welcomeImportKinds}
          onActionChange={handleActionChange}
          onBulkAction={handleBulkAction}
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
            {manualImportSource && (phase === 'idle' || phase === 'scanning') && (
              <div className="flex flex-col gap-2 border-t border-(--color-border-subtle) px-4 py-3 sm:flex-row sm:items-end">
                <label className="min-w-0 flex-1 text-xs text-(--color-text-muted)">
                  Local export path · {SOURCE_LABELS[manualImportSource]}
                  <input
                    aria-label="Local export path"
                    value={manualImportPath}
                    onChange={(event) => setManualImportPath(event.target.value)}
                    onKeyDown={(event) => { if (event.key === 'Enter') handleManualPathImport() }}
                    placeholder="Paste the local file or folder path"
                    className="mt-1.5 h-9 w-full rounded-md border border-(--color-border) bg-(--bg-card) px-2.5 text-sm text-(--color-text) outline-none focus:border-(--color-accent)"
                    autoFocus
                  />
                </label>
                <Button size="sm" onClick={handleManualPathImport} disabled={!manualImportPath.trim()}>
                  Preview local import
                </Button>
              </div>
            )}
          </SettingsGroup>
        </>
      )}

      {/* ── Auto-sync ──────────────────────────────────────────────────── */}
      {autoSync && (phase === 'idle' || phase === 'scanning') && (
        <SettingsGroup title="Auto-sync">
          <SettingsRow
            label="Automatically detect new items"
            description="Import new sessions, skills, and agents while EvoFlux is open. Existing conflicts and MCP configuration stay under manual review."
            control={
              <button
                type="button"
                role="switch"
                aria-checked={autoSync.enabled}
                onClick={() => handleAutoSyncToggle(!autoSync.enabled)}
                className={cn(
                  'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                  autoSync.enabled ? 'bg-(--color-accent)' : 'bg-(--color-border)',
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    'pointer-events-none inline-block size-4 rounded-full bg-white shadow-sm transition-transform',
                    autoSync.enabled ? 'translate-x-4' : 'translate-x-0',
                  )}
                />
              </button>
            }
          />
          {autoSync.enabled && (
            <SettingsRow
              label="Scan interval"
              description={`Scan every ${autoSync.scan_interval_seconds} seconds`}
              control={
                <SelectControl
                  value={String(autoSync.scan_interval_seconds)}
                  onValueChange={(v) =>
                    updateAutoSyncSettings({ scan_interval_seconds: Number(v) })
                      .then((updated) => {
                        setAutoSync(updated)
                        notifyImportAutoSyncSettingsChanged(updated)
                      })
                      .catch(() => {})
                  }
                  size="sm"
                  options={[
                    { value: '60', label: '1 minute' },
                    { value: '300', label: '5 minutes' },
                    { value: '600', label: '10 minutes' },
                    { value: '1800', label: '30 minutes' },
                    { value: '3600', label: '1 hour' },
                  ]}
                />
              }
            />
          )}
        </SettingsGroup>
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
          {undoMessage && <div className="px-4 py-2 text-xs text-(--color-text-muted)" role="status">{undoMessage}</div>}
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-(--color-border-subtle) text-left text-(--color-text-muted)">
                  <th className="px-4 py-2 font-medium">Source</th>
                  <th className="px-4 py-2 font-medium">Items</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Date</th>
                  <th className="px-4 py-2 font-medium">Action</th>
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
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-2">
                          <Button size="sm" variant="outline" disabled={historyDetailLoading} aria-expanded={historyDetail?.import_id === entry.import_id} onClick={() => void toggleHistoryDetail(entry)}>
                            {historyDetailLoading && historyDetail?.import_id !== entry.import_id ? 'Loading…' : historyDetail?.import_id === entry.import_id ? 'Hide details' : 'Details'}
                          </Button>
                          {entry.undo_available ? (
                            <Button size="sm" variant="outline" disabled={undoingImportId !== null} onClick={() => void handleUndo(entry)}>
                              {undoingImportId === entry.import_id ? 'Undoing…' : 'Undo'}
                            </Button>
                          ) : (
                            <span className="text-xs text-(--color-text-muted)">{entry.undo_state === 'undone' ? 'Undone' : entry.undo_state === 'partially_undone' ? 'Partially undone' : 'Undo unavailable'}</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {historyDetail && (
            <div className="border-t border-(--color-border-subtle) px-4 py-3" aria-label="Import item outcomes">
              <h3 className="mb-2 text-sm font-medium">Import item outcomes</h3>
              {historyDetail.items.length === 0 ? (
                <p className="text-xs text-(--color-text-muted)">No item details are available for this import.</p>
              ) : (
                <ul className="space-y-1">
                  {historyDetail.items.map((item) => (
                    <li key={`${item.source_item_id}-${item.operation}`} className="text-xs">
                      <span className="font-medium">{item.label}</span>
                      <span className="ml-2 text-(--color-text-muted)">{item.outcome.replaceAll('_', ' ')} · {item.operation.replaceAll('_', ' ')}</span>
                      {item.reason && <p className="ml-1 text-(--color-text-muted)">{item.reason}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </SettingsGroup>
      )}
    </SettingsPage>
  )
}

// ── Preview sub-component ───────────────────────────────────────────────────

function ImportPreview({
  result,
  welcomeImportKinds,
  onActionChange,
  onBulkAction,
  onExecute,
  onCancel,
}: {
  result: DetectResponse
  welcomeImportKinds: ImportItemKind[] | null
  onActionChange: (index: number, action: ImportItemAction) => void
  onBulkAction: (indexes: number[], action: BulkImportItemAction) => void
  onExecute: () => void
  onCancel: () => void
}) {
  const [itemQuery, setItemQuery] = useState('')
  const [kindFilter, setKindFilter] = useState('all')
  const [page, setPage] = useState(0)
  const [selectedConflicts, setSelectedConflicts] = useState<Set<number>>(() => new Set())
  const pageSize = 100
  const newImportCount = result.items.filter((it) => it.action === 'import' || it.action === 'rename').length
  const reimportCount = result.items.filter((it) => it.action === 'reimport' || it.action === 'replace').length
  const importCount = newImportCount + reimportCount
  const conflictCount = result.items.filter((it) => it.conflicts.length > 0).length
  const canReimport = (item: DetectResponse['items'][number]) =>
    item.conflicts.length > 0 && !(item.kind === 'skill' && item.conflicts.some((conflict) => conflict.startsWith('Skill already exists in ')))
  const allConflictIndexes = result.items.flatMap((item, index) => canReimport(item) ? [index] : [])

  const selectConflicts = (indexes: number[], selected: boolean) => {
    setSelectedConflicts((previous) => {
      const next = new Set(previous)
      for (const index of indexes) {
        if (selected) next.add(index)
        else next.delete(index)
      }
      return next
    })
  }

  // Group items by kind for summary
  const kindCounts: Record<string, number> = {}
  for (const item of result.items) {
    kindCounts[item.kind] = (kindCounts[item.kind] || 0) + 1
  }
  const filteredItems = result.items
    .map((item, index) => ({ item, index }))
    .filter(({ item }) => {
      if (kindFilter !== 'all' && item.kind !== kindFilter) return false
      const query = itemQuery.trim().toLocaleLowerCase()
      return !query || [item.kind, item.label, item.target_name, item.preview, ...item.conflicts]
        .some((field) => field.toLocaleLowerCase().includes(query))
    })
  const pageCount = Math.max(1, Math.ceil(filteredItems.length / pageSize))
  const visibleItems = filteredItems.slice(page * pageSize, (page + 1) * pageSize)
  const visibleConflictIndexes = visibleItems.flatMap(({ item, index }) => canReimport(item) ? [index] : [])

  return (
    <SettingsGroup title={`Preview — ${SOURCE_LABELS[result.detected_source as ImportSource] ?? result.detected_source}`}>
      {welcomeImportKinds && welcomeImportKinds.length < IMPORT_ITEM_KIND_OPTIONS.length && (
        <div role="status" className="border-b border-(--color-border-subtle) px-4 py-2 text-xs text-(--color-text-muted)">
          Items outside your selected categories are marked Skip. You can review and change each item below.
        </div>
      )}
      {/* Summary badges */}
      <div className="flex flex-wrap gap-2 px-4 py-3">
        {Object.entries(kindCounts).map(([kind, count]) => (
          <span key={kind} className="rounded-full bg-(--bg-key) px-2.5 py-1 text-[12px] font-medium text-(--color-text-muted)">
            {count} {kind}{count !== 1 ? 's' : ''}
          </span>
        ))}
        {result.summary.new_items > 0 && (
          <span className="rounded-full bg-(--color-success)/10 px-2.5 py-1 text-[12px] font-medium text-(--color-success)">
            {result.summary.new_items} new
          </span>
        )}
        {result.summary.already_imported > 0 && (
          <span className="rounded-full bg-(--color-text-subtle)/10 px-2.5 py-1 text-[12px] font-medium text-(--color-text-muted)">
            {result.summary.already_imported} already imported
          </span>
        )}
        {result.summary.not_importable > 0 && (
          <span className="rounded-full bg-(--color-text-subtle)/10 px-2.5 py-1 text-[12px] font-medium text-(--color-text-muted)">
            {result.summary.not_importable} unsupported
          </span>
        )}
        {conflictCount > 0 && (
          <span className="rounded-full bg-(--color-warning)/10 px-2.5 py-1 text-[12px] font-medium text-(--color-warning)">
            {conflictCount} conflict{conflictCount !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 border-y border-(--color-border-subtle) px-3 py-2">
        <div className="flex h-9 min-w-48 flex-1 items-center gap-2 rounded-md border border-(--color-border) px-2.5">
          <Search size={14} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
          <input
            value={itemQuery}
            onChange={(event) => { setItemQuery(event.target.value); setPage(0) }}
            placeholder="Find a session, skill, or item…"
            aria-label="Find an import item"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-(--color-text-muted)"
          />
        </div>
        <SelectControl
          value={kindFilter}
          onValueChange={(value) => { setKindFilter(value); setPage(0) }}
          ariaLabel="Filter import items by type"
          size="sm"
          options={[
            { value: 'all', label: `All types (${result.items.length})` },
            ...Object.entries(kindCounts).map(([kind, count]) => ({
              value: kind,
              label: `${kind} (${count})`,
            })),
          ]}
        />
        <span className="w-full text-right text-xs text-(--color-text-muted) sm:w-auto">
          {filteredItems.length === result.items.length
            ? `${result.items.length} items`
            : `${filteredItems.length} of ${result.items.length} items`}
        </span>
      </div>

      {conflictCount > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-(--color-border-subtle) px-3 py-2">
          <Button size="sm" variant="outline" onClick={() => selectConflicts(visibleConflictIndexes, true)} disabled={!visibleConflictIndexes.length}>
            Select visible re-importable conflicts
          </Button>
          <Button size="sm" variant="outline" onClick={() => selectConflicts(allConflictIndexes, true)} disabled={!allConflictIndexes.length}>
            Select re-importable conflicts ({allConflictIndexes.length})
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelectedConflicts(new Set())} disabled={!selectedConflicts.size}>
            Clear selection
          </Button>
          <Button size="sm" onClick={() => onBulkAction([...selectedConflicts], 'reimport')} disabled={!selectedConflicts.size}>
            Re-import selected ({selectedConflicts.size})
          </Button>
        </div>
      )}

      {/* Items table */}
      <div className="max-h-[55vh] overflow-auto overscroll-contain">
        <table className="w-full text-[13px]">
          <thead className="sticky top-0 z-10 bg-(--bg-card)">
            <tr className="border-b border-(--color-border-subtle) text-left text-(--color-text-muted)">
              <th className="px-3 py-2 font-medium" aria-label="Select"></th>
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Details</th>
              <th className="px-4 py-2 font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {visibleItems.map(({ item, index }) => (
              <PreviewRow
                key={item.id}
                item={item}
                index={index}
                selected={selectedConflicts.has(index)}
                onSelect={(selected) => selectConflicts([index], selected)}
                onActionChange={onActionChange}
              />
            ))}
          </tbody>
        </table>
        {visibleItems.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-(--color-text-muted)">No import items match this filter.</p>
        )}
      </div>

      {filteredItems.length > pageSize && (
        <div className="flex items-center justify-between border-t border-(--color-border-subtle) px-3 py-2 text-xs text-(--color-text-muted)">
          <span>Page {page + 1} of {pageCount}</span>
          <div className="flex gap-1">
            <Button variant="ghost" size="sm" onClick={() => setPage((current) => Math.max(0, current - 1))} disabled={page === 0} aria-label="Previous page">
              <ChevronLeft size={14} /> Previous
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))} disabled={page >= pageCount - 1} aria-label="Next page">
              Next <ChevronRight size={14} />
            </Button>
          </div>
        </div>
      )}

      {result.warnings.length > 0 && (
        <div className="px-4 py-2 text-[12px] text-(--color-warning)">
          {result.warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-3 px-4 py-3 border-t border-(--color-border-subtle)">
        <Button onClick={onExecute} disabled={importCount === 0}>
          {reimportCount === 0
            ? `Import ${newImportCount} new item${newImportCount !== 1 ? 's' : ''}`
            : newImportCount === 0
              ? `Re-import ${reimportCount} existing item${reimportCount !== 1 ? 's' : ''}`
              : `Import ${newImportCount} new + re-import ${reimportCount} existing`}
        </Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </SettingsGroup>
  )
}

function PreviewRow({
  item,
  index,
  selected,
  onSelect,
  onActionChange,
}: {
  item: { id: string; kind: string; label: string; preview: string; action: string; conflicts: string[]; target_name: string; origin?: string | null; reason?: string | null }
  index: number
  selected: boolean
  onSelect: (selected: boolean) => void
  onActionChange: (index: number, action: ImportItemAction) => void
}) {
  const hasConflict = item.conflicts.length > 0
  const externalSkillConflict = item.kind === 'skill' && item.conflicts.some((conflict) => conflict.startsWith('Skill already exists in '))

  return (
    <tr className={cn('border-b border-(--color-border-subtle) last:border-0', hasConflict && 'bg-(--color-warning)/5')}>
      <td className="px-3 py-2">
        {hasConflict && <input type="checkbox" checked={selected} disabled={externalSkillConflict} onChange={(event) => onSelect(event.target.checked)} aria-label={`Select conflict ${item.target_name}`} />}
      </td>
      <td className="px-4 py-2">
        <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-[11px] font-medium text-(--color-text-muted)">
          {item.kind}
        </span>
      </td>
      <td className="px-4 py-2 font-medium">{item.target_name}</td>
      <td className="px-4 py-2 text-(--color-text-muted)">
        {item.preview}
        {item.origin && (
          <div className="mt-0.5 text-[11px] text-(--color-text-subtle)">
            {item.origin}
          </div>
        )}
        {item.reason && (
          <div className="mt-0.5 text-[11px] text-(--color-text-subtle)">
            {item.reason}
          </div>
        )}
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
          onValueChange={(v) => onActionChange(index, v as ImportItemAction)}
          size="sm"
          options={[
            { value: 'skip', label: 'Skip' },
            ...(item.reason
              ? []
              : hasConflict
              ? [
                ...(!externalSkillConflict ? [{ value: 'reimport', label: 'Re-import' }] : []),
                ...(externalSkillConflict
                  ? [{ value: 'rename', label: 'Keep both (EvoFlux copy)' }]
                  : []),
              ]
              : [{ value: 'import', label: 'Import' }]),
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
  const hasImportedSessions = (result.imported.session ?? 0) > 0

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
        <div className="flex gap-2">
          {hasImportedSessions && (
            <Button variant="outline" size="sm" onClick={() => window.location.href = '/'}>
              View sessions
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={onReset}>Import more</Button>
        </div>
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
