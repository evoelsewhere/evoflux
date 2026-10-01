import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  scanLocalSources: vi.fn(),
  getImportHistory: vi.fn(),
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
  SOURCE_LABELS: { generic: 'Generic' },
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
        { id: 'old-2', kind: 'skill', label: 'Old 2', preview: '', action: 'skip', conflicts: ['Already exists'], target_name: 'Old 2' },
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
    fireEvent.click(screen.getByRole('button', { name: 'Select all conflicts (2)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Re-import selected (2)' }))

    await waitFor(() => expect(api.updateItemsAction).toHaveBeenCalledWith('preview-1', [0, 1], 'reimport'))
    expect(screen.getByRole('button', { name: 'Import 1 new + re-import 2 existing' })).toBeInTheDocument()
    expect(api.updateItemAction).not.toHaveBeenCalledWith('preview-1', 2, 'reimport')
  })
})
