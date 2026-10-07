import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  scanLocalSources: vi.fn(),
  getImportHistory: vi.fn(),
  getImportJob: vi.fn(),
  getAutoSyncSettings: vi.fn(),
  detectImport: vi.fn(),
  updateItemAction: vi.fn(),
  updateItemsAction: vi.fn(),
  executeImport: vi.fn(),
  cancelImport: vi.fn(),
  pickImportSource: vi.fn(),
  updateAutoSyncSettings: vi.fn(),
  undoImport: vi.fn(),
}))

vi.mock('@/api/import', () => ({
  ...api,
  SOURCE_LABELS: { generic: 'Generic', chatgpt: 'ChatGPT' },
}))

import { ImportSettingsPage } from '@/routes/settings.import'

describe('ImportSettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.matchMedia = vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }) as unknown as typeof window.matchMedia
    api.scanLocalSources.mockResolvedValue({ discovered: [{ source: 'generic', path: '/export', label: 'Local export', description: 'Local source', estimated_items: 3 }] })
    api.getImportHistory.mockResolvedValue({ imports: [] })
    api.getAutoSyncSettings.mockResolvedValue({ enabled: false, scan_interval_seconds: 300, notify_new_items: true })
    api.detectImport.mockResolvedValue({
      import_id: 'preview-1', detected_source: 'generic', path: '/export', summary: {}, warnings: [],
      items: [
        { id: 'old-1', kind: 'session', label: 'Old 1', preview: '', action: 'skip', conflicts: ['Already imported'], target_name: 'Old 1' },
        { id: 'old-2', kind: 'skill', label: 'Old 2', preview: '', action: 'skip', conflicts: ['Already exists'], target_name: 'Old 2', origin: 'Claude Code plugin · release-helper' },
        { id: 'new-1', kind: 'agent', label: 'New', preview: '', action: 'import', conflicts: [], target_name: 'New' },
      ],
    })
    api.updateItemAction.mockResolvedValue(undefined)
    api.updateItemsAction.mockResolvedValue(undefined)
    api.cancelImport.mockResolvedValue(undefined)
  })

  it('bulk re-imports only selected conflicts and leaves new-item actions separate', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <ImportSettingsPage />
      </QueryClientProvider>,
    )

    fireEvent.click(await screen.findByRole('button', { name: 'Import' }))
    await screen.findByText(/Preview — Generic/)
    expect(screen.getByText('Claude Code plugin · release-helper')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Select re-importable conflicts (2)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Re-import selected (2)' }))

    await waitFor(() => expect(api.updateItemsAction).toHaveBeenCalledWith('preview-1', [0, 1], 'reimport'))
    expect(screen.getByRole('button', { name: 'Import 1 new + re-import 2 existing' })).toBeInTheDocument()
    expect(api.updateItemAction).not.toHaveBeenCalledWith('preview-1', 2, 'reimport')
  })

  it('loads persistent item-level undo outcomes from import history', async () => {
    api.getImportHistory.mockResolvedValue({ imports: [{
      import_id: 'job-1', source: 'generic', path: '/export', detected_format: 'generic',
      status: 'completed', imported: { session: 1 }, skipped: {}, error_count: 0, item_count: 1,
      undo_state: 'partially_undone', undo_available: false, undoable_count: 0,
      created_at: '2026-10-06T00:00:00Z', completed_at: '2026-10-06T00:00:01Z',
    }] })
    api.getImportJob.mockResolvedValue({
      import_id: 'job-1', origin: 'manual', undo_state: 'partially_undone',
      items: [{ source_item_id: 'session:one', kind: 'session', label: 'Session one', operation: 'created', outcome: 'undo_skipped', reason: 'Target changed after import' }],
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><ImportSettingsPage /></QueryClientProvider>)

    fireEvent.click(await screen.findByRole('button', { name: 'Details' }))

    expect(await screen.findByText('Import item outcomes')).toBeInTheDocument()
    expect(screen.getByText('Session one')).toBeInTheDocument()
    expect(screen.getByText('Target changed after import')).toBeInTheDocument()
    expect(api.getImportJob).toHaveBeenCalledWith('job-1')
  })

  it('offers a separately named EvoFlux copy for a Skill from another local source', async () => {
    api.detectImport.mockResolvedValue({
      import_id: 'preview-skill', detected_source: 'claude_code', path: '/source', summary: {}, warnings: [],
      items: [{
        id: 'skill-1', kind: 'skill', label: 'Skill: release-notes', preview: 'A release helper',
        action: 'skip', conflicts: ['Skill already exists in Claude Code skills'], target_name: 'release-notes',
        origin: 'Claude Code global Skill',
      }],
    })
    api.updateItemAction.mockResolvedValue({ target_name: 'release-notes-evoflux' })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><ImportSettingsPage /></QueryClientProvider>)

    fireEvent.click(await screen.findByRole('button', { name: 'Import' }))
    const selectors = await screen.findAllByRole('combobox')
    fireEvent.click(selectors.at(-1)!)
    expect(screen.queryByRole('option', { name: 'Re-import' })).not.toBeInTheDocument()
    const keepBoth = await screen.findByRole('option', { name: 'Keep both (EvoFlux copy)' })
    fireEvent.mouseMove(keepBoth)
    fireEvent.pointerDown(keepBoth, { pointerType: 'mouse' })
    fireEvent.mouseUp(keepBoth)
    fireEvent.click(keepBoth)

    await waitFor(() => expect(api.updateItemAction).toHaveBeenCalledWith('preview-skill', 0, 'rename'))
    expect(screen.getByText('release-notes-evoflux')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import 1 new item' })).toBeInTheDocument()
  })

  it('shows unsupported settings as read-only and never offers Import', async () => {
    api.detectImport.mockResolvedValue({
      import_id: 'preview-setting', detected_source: 'generic', path: '/export',
      summary: { total_items: 1, new_items: 0, already_imported: 0, not_importable: 1 }, warnings: [],
      items: [{
        id: 'setting-1', kind: 'setting', label: 'Credential: EXAMPLE_API_KEY',
        preview: 'Setting', action: 'skip', conflicts: [],
        target_name: 'Credential: EXAMPLE_API_KEY', reason: 'Settings and credentials are not imported',
      }],
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><ImportSettingsPage /></QueryClientProvider>)

    fireEvent.click(await screen.findByRole('button', { name: 'Import' }))
    expect(await screen.findByText('Settings and credentials are not imported')).toBeInTheDocument()
    expect(screen.getByText('1 unsupported')).toBeInTheDocument()
    const actionSelector = screen.getAllByRole('combobox').at(-1)!
    fireEvent.click(actionSelector)
    expect(await screen.findByRole('option', { name: 'Skip' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Import' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import 0 new items' })).toBeDisabled()
  })

  it('provides a visible local path field when the native picker is unavailable', async () => {
    api.pickImportSource.mockRejectedValue(new Error('prompt() is not supported'))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><ImportSettingsPage /></QueryClientProvider>)

    fireEvent.click(await screen.findByRole('button', { name: 'ChatGPT' }))

    const pathInput = await screen.findByRole('textbox', { name: 'Local export path' })
    fireEvent.change(pathInput, { target: { value: 'D:/synthetic/conversations.json' } })
    fireEvent.click(screen.getByRole('button', { name: 'Preview local import' }))

    await waitFor(() => expect(api.detectImport).toHaveBeenCalledWith(
      'D:/synthetic/conversations.json', 'chatgpt',
    ))
    expect(await screen.findByText(/Preview — Generic/)).toBeInTheDocument()
  })
})
