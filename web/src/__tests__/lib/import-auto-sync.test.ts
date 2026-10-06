import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getAutoSyncSettings: vi.fn(),
  scanLocalSources: vi.fn(),
  detectImport: vi.fn(),
  updateItemsAction: vi.fn(),
  executeImport: vi.fn(),
  cancelImport: vi.fn(),
}))
const notify = vi.hoisted(() => vi.fn())

vi.mock('@/api/import', () => api)
vi.mock('@/lib/desktop-notifications', () => ({ sendDesktopNotification: notify }))

import { startImportAutoSync } from '@/lib/import-auto-sync'

describe('startImportAutoSync', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    api.getAutoSyncSettings.mockResolvedValue({ enabled: true, scan_interval_seconds: 60, notify_new_items: true })
    api.scanLocalSources.mockResolvedValue({ discovered: [{ source: 'generic', path: '/source', label: 'Source', estimated_items: 1 }] })
    api.detectImport.mockResolvedValue({
      import_id: 'preview-1',
      detected_source: 'generic',
      path: '/source',
      summary: {},
      items: [{ id: 'one', kind: 'skill', label: 'Skill', preview: '', action: 'import', conflicts: [], target_name: 'Skill' }],
      warnings: [],
    })
    api.executeImport.mockResolvedValue({ imported: { skill: 1 }, skipped: {}, errors: [] })
    api.cancelImport.mockResolvedValue(undefined)
    api.updateItemsAction.mockResolvedValue(undefined)
    notify.mockResolvedValue({ status: 'sent', message: 'sent' })
  })

  afterEach(() => vi.useRealTimers())

  it('imports supported new items and notifies with an Import settings action', async () => {
    const onResult = vi.fn()
    const stop = startImportAutoSync({ onResult })
    await vi.advanceTimersByTimeAsync(1000)

    expect(api.executeImport).toHaveBeenCalledTimes(1)

    expect(api.executeImport).toHaveBeenCalledWith('preview-1', expect.objectContaining({ origin: 'auto_sync' }))
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({
      kind: 'import_sync',
      actionTarget: 'settings_import',
    }))
    expect(onResult).toHaveBeenCalledWith(expect.objectContaining({ imported: 1, failed: 0, review: 0 }))
    stop()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(api.scanLocalSources).toHaveBeenCalledTimes(1)
  })

  it('skips MCP and conflicting items, and cancels previews with no safe imports', async () => {
    api.detectImport.mockResolvedValueOnce({
      import_id: 'review-only', detected_source: 'generic', path: '/source', summary: {}, warnings: [],
      items: [
        { id: 'mcp', kind: 'mcp_server', label: 'MCP', preview: '', action: 'import', conflicts: [], target_name: 'MCP' },
        { id: 'conflict', kind: 'session', label: 'Existing', preview: '', action: 'skip', conflicts: ['Already imported'], target_name: 'Existing' },
      ],
    })
    const stop = startImportAutoSync()
    await vi.advanceTimersByTimeAsync(1000)

    expect(api.cancelImport).toHaveBeenCalledWith('review-only')

    expect(api.updateItemsAction).toHaveBeenCalledWith('review-only', [0, 1], 'skip', expect.any(AbortSignal))
    expect(api.executeImport).not.toHaveBeenCalled()
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ actionTarget: 'settings_import' }))
    stop()
  })

  it('does not create a history job or notification for an unchanged scan', async () => {
    api.detectImport.mockResolvedValueOnce({
      import_id: 'no-change', detected_source: 'generic', path: '/source', summary: {}, warnings: [], items: [],
    })
    const stop = startImportAutoSync()
    await vi.advanceTimersByTimeAsync(1000)

    expect(api.executeImport).not.toHaveBeenCalled()
    expect(api.cancelImport).toHaveBeenCalledWith('no-change')
    expect(notify).not.toHaveBeenCalled()
    stop()
  })
})
