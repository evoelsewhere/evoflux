import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const { removeViewer, initializeViewer } = vi.hoisted(() => {
  const remove = vi.fn()
  return {
    removeViewer: remove,
    initializeViewer: vi.fn(() => ({ remove })),
  }
})

vi.mock('@embedpdf/snippet', () => ({
  default: { init: initializeViewer },
}))

vi.mock('@/api/client', () => ({
  workspaceMediaUrl: (sessionId: string, path: string) => `/media/${sessionId}/${path}`,
}))

import { PdfPreview } from '@/components/workspace-pdf-preview'

afterEach(() => {
  initializeViewer.mockClear()
  removeViewer.mockClear()
})

describe('PdfPreview', () => {
  it('mounts a local-first, read-only EmbedPDF viewer and disposes it', () => {
    const { unmount } = render(
      <PdfPreview
        sessionId="session-1"
        file={{ path: 'reports/q2.pdf', name: 'q2.pdf', mime: 'application/pdf', size: 10, mtime: 2 }}
      />,
    )

    expect(screen.getByTestId('pdf-preview-host')).toBeInTheDocument()
    expect(initializeViewer).toHaveBeenCalledWith(expect.objectContaining({
      src: '/media/session-1/reports/q2.pdf',
      worker: true,
      fontFallback: null,
      disabledCategories: expect.arrayContaining(['annotation', 'redaction', 'signature']),
    }))

    unmount()
    expect(removeViewer).toHaveBeenCalledOnce()
  })
})
