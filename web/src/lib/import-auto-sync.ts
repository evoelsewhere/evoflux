import {
  cancelImport,
  detectImport,
  executeImport,
  getAutoSyncSettings,
  scanLocalSources,
  updateItemsAction,
  type AutoSyncSettings,
  type ImportSource,
} from '@/api/import'
import { sendDesktopNotification } from '@/lib/desktop-notifications'

const AUTO_IMPORT_KINDS = new Set(['session', 'skill', 'agent'])
const SETTINGS_EVENT = 'evoflux:import-auto-sync-changed'

export function notifyImportAutoSyncSettingsChanged(settings: AutoSyncSettings): void {
  window.dispatchEvent(new CustomEvent<AutoSyncSettings>(SETTINGS_EVENT, { detail: settings }))
}

export interface ImportSyncSummary {
  imported: number
  failed: number
  review: number
}

export function startImportAutoSync(options: {
  onResult?: (summary: ImportSyncSummary) => void
} = {}): () => void {
  let stopped = false
  let enabled = false
  let intervalSeconds = 300
  let notifyNewItems = true
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined
  let inFlight = false
  let pendingImportId: string | undefined

  const clearTimer = () => {
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
  }

  const schedule = (delaySeconds: number) => {
    clearTimer()
    if (stopped || !enabled) return
    timer = setTimeout(() => void runCycle(), Math.max(1, delaySeconds) * 1000)
  }

  const notify = async (summary: ImportSyncSummary) => {
    options.onResult?.(summary)
    if (!notifyNewItems || (!summary.imported && !summary.failed && !summary.review)) return
    const body = [
      summary.imported ? `${summary.imported} imported` : '',
      summary.failed ? `${summary.failed} failed` : '',
      summary.review ? `${summary.review} need review` : '',
    ].filter(Boolean).join(' · ')
    await sendDesktopNotification({
      kind: 'import_sync',
      title: 'Import sync update',
      body,
      actionTarget: 'settings_import',
    })
  }

  const runCycle = async () => {
    if (stopped || !enabled || inFlight) return
    inFlight = true
    const cycleController = new AbortController()
    controller = cycleController
    const summary: ImportSyncSummary = { imported: 0, failed: 0, review: 0 }
    try {
      const scan = await scanLocalSources(cycleController.signal)
      for (const source of scan.discovered) {
        if (stopped || cycleController.signal.aborted) break
        let importId: string | undefined
        try {
          const preview = await detectImport(source.path, source.source as ImportSource, cycleController.signal)
          importId = preview.import_id
          pendingImportId = importId
          const skipIndexes: number[] = []
          let safeCount = 0
          for (const [index, item] of preview.items.entries()) {
            if (item.conflicts.length || !AUTO_IMPORT_KINDS.has(item.kind)) {
              skipIndexes.push(index)
              summary.review += 1
            } else {
              safeCount += 1
            }
          }
          if (skipIndexes.length) {
            await updateItemsAction(importId, skipIndexes, 'skip', cycleController.signal)
          }
          if (stopped || cycleController.signal.aborted) {
            await cancelImport(importId).catch(() => undefined)
            pendingImportId = undefined
            break
          }
          if (!safeCount) {
            await cancelImport(importId)
            pendingImportId = undefined
            continue
          }
          const result = await executeImport(importId, {
            origin: 'auto_sync',
            signal: cycleController.signal,
          })
          pendingImportId = undefined
          summary.imported += Object.values(result.imported).reduce((total, count) => total + count, 0)
          summary.failed += result.errors.length
        } catch (error) {
          if (!cycleController.signal.aborted) {
            summary.failed += 1
            console.warn('import auto-sync source failed', source.path, error)
          }
          if (importId) await cancelImport(importId).catch(() => undefined)
          if (pendingImportId === importId) pendingImportId = undefined
        }
      }
      if (!stopped && !cycleController.signal.aborted) await notify(summary)
    } catch (error) {
      if (!cycleController.signal.aborted && !stopped) {
        console.warn('import auto-sync scan failed', error)
        await notify({ imported: 0, failed: 1, review: 0 })
      }
    } finally {
      if (controller === cycleController) controller = undefined
      inFlight = false
      if (!stopped && enabled) schedule(intervalSeconds)
    }
  }

  const applySettings = (settings: AutoSyncSettings, runNow = false) => {
    const wasEnabled = enabled
    const intervalChanged = intervalSeconds !== settings.scan_interval_seconds
    enabled = settings.enabled
    intervalSeconds = settings.scan_interval_seconds
    notifyNewItems = settings.notify_new_items
    if (!enabled) {
      clearTimer()
      controller?.abort()
    } else if (runNow || !wasEnabled || intervalChanged) {
      schedule(runNow || !wasEnabled ? 1 : intervalSeconds)
    }
  }

  const handleSettingsChanged = (event: Event) => {
    const settings = (event as CustomEvent<AutoSyncSettings>).detail
    if (settings) applySettings(settings, !enabled && settings.enabled)
  }
  window.addEventListener(SETTINGS_EVENT, handleSettingsChanged)
  void getAutoSyncSettings()
    .then((settings) => applySettings(settings, settings.enabled))
    .catch((error: unknown) => console.warn('could not load import auto-sync settings', error))

  return () => {
    stopped = true
    clearTimer()
    controller?.abort()
    if (pendingImportId) void cancelImport(pendingImportId).catch(() => undefined)
    window.removeEventListener(SETTINGS_EVENT, handleSettingsChanged)
  }
}
