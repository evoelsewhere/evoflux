import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { sheet, workbook, createWorkbook } = vi.hoisted(() => {
  const mockedSheet = {
    options: {
      isProtected: false,
      protectionOptions: {} as Record<string, boolean>,
    },
  }
  const mockedWorkbook = {
    options: {} as Record<string, boolean>,
    bind: vi.fn(),
    destroy: vi.fn(),
    getSheetCount: vi.fn(() => 1),
    getSheet: vi.fn(() => mockedSheet),
    import: vi.fn((_file: File, success: () => void, _error: (reason: unknown) => void, _options: { fileType: number }) => success()),
    invalidateLayout: vi.fn(),
    repaint: vi.fn(),
  }
  return {
    sheet: mockedSheet,
    workbook: mockedWorkbook,
    createWorkbook: vi.fn(function MockWorkbook() {
      return mockedWorkbook
    }),
  }
})

vi.mock('@mescius/spread-sheets', () => ({
  Spread: {
    Sheets: {
      Workbook: createWorkbook,
      Events: { EditStarting: 'EditStarting' },
      FileType: { excel: 0 },
      LicenseKey: '',
    },
  },
}))
vi.mock('@mescius/spread-sheets-io', () => ({}))
vi.mock('@/api/client', () => ({
  workspaceMediaUrl: (sessionId: string, path: string) => `/media/${sessionId}/${path}`,
}))

import { XlsxPreview } from '@/components/workspace-xlsx-preview'

beforeEach(() => {
  vi.clearAllMocks()
  sheet.options.isProtected = false
  sheet.options.protectionOptions = {}
  vi.stubGlobal('ResizeObserver', class {
    observe = vi.fn()
    disconnect = vi.fn()
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    blob: () => Promise.resolve(new Blob(['xlsx'])),
  }))
})

describe('XlsxPreview', () => {
  it('imports the original XLSX and makes the in-memory workbook read-only', async () => {
    render(
      <XlsxPreview
        sessionId="session-1"
        file={{
          path: 'models/forecast.xlsx',
          name: 'forecast.xlsx',
          mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          size: 10,
          mtime: 2,
        }}
      />,
    )

    expect(screen.getByTestId('xlsx-preview-host')).toBeInTheDocument()
    await waitFor(() => expect(workbook.import).toHaveBeenCalledOnce())

    expect(fetch).toHaveBeenCalledWith('/media/session-1/models/forecast.xlsx', expect.any(Object))
    const [source, , , options] = workbook.import.mock.calls[0]!
    expect(source).toBeInstanceOf(File)
    expect(source.name).toBe('forecast.xlsx')
    expect(options).toEqual({ fileType: 0 })
    expect(workbook.options).toEqual(expect.objectContaining({
      allowUndo: false,
      allowUserDragDrop: false,
      allowUserDragFill: false,
      allowUserEditFormula: false,
    }))
    expect(sheet.options.isProtected).toBe(true)
    expect(sheet.options.protectionOptions).toEqual(expect.objectContaining({
      allowSelectLockedCells: true,
      allowFilter: true,
      allowUsePivotTable: true,
    }))
  })
})
