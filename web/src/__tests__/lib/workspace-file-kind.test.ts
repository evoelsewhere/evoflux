import { describe, expect, it } from 'vitest'

import type { WorkspaceFileInfo } from '@/api/types'
import { workspaceFileKind } from '@/lib/workspace-file-kind'

function file(name: string, mime = 'application/octet-stream'): WorkspaceFileInfo {
  return { path: name, name, mime, size: 1, mtime: 1 }
}

describe('workspaceFileKind', () => {
  it('routes PDF by extension or MIME type to the PDF engine', () => {
    expect(workspaceFileKind(file('report.PDF'))).toBe('pdf')
    expect(workspaceFileKind(file('download', 'application/pdf'))).toBe('pdf')
  })

  it('routes XLSX to the workbook engine instead of the Office HTML renderer', () => {
    expect(workspaceFileKind(file('forecast.xlsx'))).toBe('xlsx')
  })

  it('keeps existing image, text, and binary routing intact', () => {
    expect(workspaceFileKind(file('diagram.svg', 'text/xml'))).toBe('image')
    expect(workspaceFileKind(file('notes.md'))).toBe('text')
    expect(workspaceFileKind(file('archive.zip'))).toBe('binary')
  })
})
