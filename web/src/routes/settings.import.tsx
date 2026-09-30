/**
 * Settings → Import — import data from external AI tools.
 *
 * Provides source selection buttons, Tauri dialog integration,
 * preview table with conflict resolution, and execution progress.
 */
import { useCallback, useEffect, useState } from 'react'
import { Import, Loader2, CheckCircle2, AlertTriangle, X } from 'lucide-react'

import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
} from '@/components/settings/SettingsLayout'
import {
  type DetectResponse,
  type ExecuteResponse,
  type ImportSource,
  type ImportItemPreview,
  type HistoryEntry,
  SOURCE_LABELS,
  pickImportSource,
  detectImport,
  executeImport,
  cancelImport,
  updateItemAction,
  getImportHistory,
} from '@/api/import'
import { Button } from '@/components/ui/button'
import { SelectControl } from '@/components/ui/select'
import { cn } from '@/lib/utils'

// ── Source quick-import buttons ─────────────────────────────────────────────

const IMPORT_SOURCES: ImportSource[] = [
  'claude_web',
  'claude_code',
  'chatgpt',
  'codex',
  'cursor',
  'generic',
]

// ── Main page ───────────────────────────────────────────────────────────────

export function ImportSettingsPage() {
  const [phase, setPhase] = useState<'idle' | 'detecting' | 'preview' | 'executing' | 'done'>(
    'idle',
  )
  const [error, setError] = useState<string | null>(null)
  const [detectResult, setDetectResult] = useState<DetectResponse | null>(null)
  const [executeResult, setExecuteResult] = useState<ExecuteResponse | null>(null)

  const handlePick = useCallback(async (source: ImportSource) => {
    setError(null)
    setExecuteResult(null)

    const path = await pickImportSource(source)
    if (!path) return

    setPhase('detecting')
    try {
      const result = await detectImport(path, source)
      setDetectResult(result)
      setPhase('preview')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPhase('idle')
    }
  }, [])

  const handleExecute = useCallback(async () => {
    if (!detectResult) return
    setPhase('executing')
    setError(null)

    try {
      const result = await executeImport(detectResult.import_id)
      setExecuteResult(result)
      setPhase('done')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPhase('preview')
    }
  }, [detectResult])

  const handleCancel = useCallback(async () => {
    if (detectResult) {
      await cancelImport(detectResult.import_id).catch(() => {})
    }
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
        // Update local state
        setDetectResult((prev) => {
          if (!prev) return prev
          const items = [...prev.items]
          items[index] = { ...items[index], action }
          return { ...prev, items }
        })
      } catch {
        // ignore — will be caught on execute
      }
    },
    [detectResult],
  )

  return (
    <SettingsPage
      icon={Import}
      title="Import"
      lede="Import data from Claude, ChatGPT, Codex, Cursor, and other AI tools."
    >
      {/* ── Source buttons ─────────────────────────────────────────────── */}
      <SettingsGroup title="Import from">
        <div className="flex flex-wrap gap-2">
          {IMPORT_SOURCES.map((source) => (
            <Button
              key={source}
              variant="outline"
              size="sm"
              disabled={phase !== 'idle' && phase !== 'done'}
              onClick={() => handlePick(source)}
            >
              {SOURCE_LABELS[source]}
            </Button>
          ))}
        </div>
      </SettingsGroup>

      {/* ── Error ──────────────────────────────────────────────────────── */}
      {error && (
        <SettingsCallout tone="error">
          <div className="flex items-start justify-between gap-2">
            <span>{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              className="shrink-0 text-(--color-text-muted) hover:text-(--color-text)"
            >
              <X size={14} />
            </button>
          </div>
        </SettingsCallout>
      )}

      {/* ── Detecting spinner ──────────────────────────────────────────── */}
      {phase === 'detecting' && (
        <SettingsCallout tone="info">
          <span className="flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" />
            Detecting source format...
          </span>
        </SettingsCallout>
      )}

      {/* ── Preview table ──────────────────────────────────────────────── */}
      {phase === 'preview' && detectResult && (
        <ImportPreview
          result={detectResult}
          onActionChange={handleActionChange}
          onExecute={handleExecute}
          onCancel={handleCancel}
        />
      )}

      {/* ── Executing spinner ──────────────────────────────────────────── */}
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

      {/* ── History ──────────────────────────────────────────────────────── */}
      <ImportHistory />
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

  return (
    <>
      <SettingsGroup title={`Preview — ${result.detected_source}`}>
        <div className="text-[13px] text-(--color-text-muted) mb-3">
          {result.summary.total_items} items detected from{' '}
          <code className="text-[12px]">{result.path}</code>
          {conflictCount > 0 && (
            <span className="ml-2 text-(--color-warning)">
              ({conflictCount} conflict{conflictCount !== 1 ? 's' : ''})
            </span>
          )}
        </div>

        <div className="overflow-x-auto rounded-lg border border-(--color-border-subtle)">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-b border-(--color-border-subtle) bg-(--bg-key)/50 text-left text-(--color-text-muted)">
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Details</th>
                <th className="px-3 py-2 font-medium">Action</th>
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
          <div className="mt-2 text-[12px] text-(--color-warning)">
            {result.warnings.map((w, i) => (
              <div key={i}>{w}</div>
            ))}
          </div>
        )}
      </SettingsGroup>

      <div className="flex items-center gap-3 pt-2">
        <Button onClick={onExecute} disabled={importCount === 0}>
          Import {importCount} item{importCount !== 1 ? 's' : ''}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </>
  )
}

function PreviewRow({
  item,
  index,
  onActionChange,
}: {
  item: ImportItemPreview
  index: number
  onActionChange: (index: number, action: 'import' | 'skip' | 'replace' | 'rename') => void
}) {
  const hasConflict = item.conflicts.length > 0

  return (
    <tr
      className={cn(
        'border-b border-(--color-border-subtle) last:border-0',
        hasConflict && 'bg-(--color-warning)/5',
      )}
    >
      <td className="px-3 py-2 text-(--color-text-muted)">
        <span className="rounded-full bg-(--bg-key) px-2 py-0.5 text-[11px] font-medium">
          {item.kind}
        </span>
      </td>
      <td className="px-3 py-2 font-medium">{item.target_name}</td>
      <td className="px-3 py-2 text-(--color-text-muted)">
        {item.preview}
        {hasConflict && (
          <div className="mt-0.5 flex items-center gap-1 text-[11px] text-(--color-warning)">
            <AlertTriangle size={11} />
            {item.conflicts[0]}
          </div>
        )}
      </td>
      <td className="px-3 py-2">
        <SelectControl
          value={item.action}
          onValueChange={(v) =>
            onActionChange(index, v as 'import' | 'skip' | 'replace' | 'rename')
          }
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
    <SettingsGroup title="Import complete">
      <SettingsCallout tone={hasErrors ? 'warning' : 'success'}>
        <span className="flex items-center gap-2">
          <CheckCircle2 size={14} />
          {totalImported} item{totalImported !== 1 ? 's' : ''} imported
          {totalSkipped > 0 && `, ${totalSkipped} skipped`}
          {hasErrors && `, ${result.errors.length} error${result.errors.length !== 1 ? 's' : ''}`}
        </span>
      </SettingsCallout>

      {result.errors.length > 0 && (
        <div className="mt-2 space-y-1 text-[12px] text-(--color-error)">
          {result.errors.map((err, i) => (
            <div key={i}>
              <strong>{err.item}</strong>: {err.error}
            </div>
          ))}
        </div>
      )}

      <div className="pt-3">
        <Button variant="outline" onClick={onReset}>
          Import more
        </Button>
      </div>
    </SettingsGroup>
  )
}

// ── History sub-component ───────────────────────────────────────────────────

function ImportHistory() {
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getImportHistory()
      .then((res) => setHistory(res.imports))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <SettingsGroup title="Import History">
        <div className="text-[13px] text-(--color-text-muted)">Loading...</div>
      </SettingsGroup>
    )
  }

  if (history.length === 0) {
    return (
      <SettingsGroup title="Import History">
        <div className="text-[13px] text-(--color-text-muted)">
          No imports yet.
        </div>
      </SettingsGroup>
    )
  }

  return (
    <SettingsGroup title="Import History">
      <div className="overflow-x-auto rounded-lg border border-(--color-border-subtle)">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-(--color-border-subtle) bg-(--bg-key)/50 text-left text-(--color-text-muted)">
              <th className="px-3 py-2 font-medium">Source</th>
              <th className="px-3 py-2 font-medium">Items</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Date</th>
            </tr>
          </thead>
          <tbody>
            {history.map((entry) => {
              const sourceLabel =
                SOURCE_LABELS[entry.source as ImportSource] ?? entry.source
              const totalImported = Object.values(entry.imported).reduce(
                (a, b) => a + b,
                0,
              )
              const date = entry.created_at
                ? new Date(entry.created_at).toLocaleDateString()
                : '—'

              return (
                <tr
                  key={entry.import_id}
                  className="border-b border-(--color-border-subtle) last:border-0"
                >
                  <td className="px-3 py-2 font-medium">{sourceLabel}</td>
                  <td className="px-3 py-2 text-(--color-text-muted)">
                    {totalImported} imported
                    {entry.error_count > 0 && (
                      <span className="ml-1 text-(--color-error)">
                        , {entry.error_count} errors
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={cn(
                        'rounded-full px-2 py-0.5 text-[11px] font-medium',
                        entry.status === 'completed'
                          ? 'bg-(--color-success)/10 text-(--color-success)'
                          : 'bg-(--color-warning)/10 text-(--color-warning)',
                      )}
                    >
                      {entry.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-(--color-text-muted)">{date}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </SettingsGroup>
  )
}
