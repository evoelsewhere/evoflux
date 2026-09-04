import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { saveFile } = vi.hoisted(() => ({
  saveFile: vi.fn(async (_url: string, _filename: string) => undefined),
}))
vi.mock('@/lib/workspace-file-save', () => ({ saveWorkspaceFileFromUrl: saveFile }))

import { ToolAttachments } from '@/components/ToolCall'

describe('ToolAttachments', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve(
        '<!doctype html><html><body><article data-preview-item data-preview-label="Slide 1">Decision</article></body></html>',
      ),
    }))
    saveFile.mockClear()
  })

  it('saves an attachment through the host, from the media URL alone', async () => {
    // ``download_url`` is a server hint the backend does not send today; the
    // action has to work off the plain media URL, and must not hand that
    // token-bearing URL to another application.
    render(
      <ToolAttachments
        attachments={[
          {
            filename: 'notes.csv',
            original_name: 'notes.csv',
            media_type: 'text/csv',
            category: 'document',
            url: '/api/team/session/media/notes.csv',
          },
        ]}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Download notes.csv' }))
    await waitFor(() => expect(saveFile).toHaveBeenCalledTimes(1))
    expect(saveFile.mock.calls[0][1]).toBe('notes.csv')
    expect(saveFile.mock.calls[0][0]).toContain('/team/session/media/notes.csv')
  })

  it('opens generated presentations in the shared in-app document viewer', async () => {
    render(
      <ToolAttachments
        attachments={[
          {
            filename: 'decision-deck.pptx',
            original_name: 'decision-deck.pptx',
            media_type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            category: 'document',
            url: '/api/team/session/media/decision-deck.pptx',
            preview_url: '/api/team/session/document-preview/decision-deck.pptx',
            download_url: '/api/team/session/media/decision-deck.pptx?download=1',
            workspace_path: 'decision-deck.pptx',
          },
        ]}
      />,
    )

    expect(screen.getByRole('button', { name: 'decision-deck.pptx' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Download decision-deck.pptx' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'decision-deck.pptx' }))

    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(await screen.findByLabelText('PowerPoint document viewer')).toBeInTheDocument()
  })

  it('navigates through every generated image, including hidden overflow items', () => {
    render(
      <ToolAttachments
        limit={2}
        attachments={Array.from({ length: 4 }, (_, index) => ({
          filename: `image-${index + 1}.png`,
          original_name: `Image ${index + 1}`,
          media_type: 'image/png',
          category: 'image',
          url: `/api/team/session/media/image-${index + 1}.png`,
        }))}
      />,
    )

    expect(screen.getByText('+2 more')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open Image 1 preview' }))

    const lightbox = screen.getByRole('dialog', { name: 'Image lightbox' })
    expect(lightbox).toBeInTheDocument()
    expect(within(lightbox).getByRole('img', { name: 'Image 1' })).toBeInTheDocument()
    expect(screen.getByText('1 / 4')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous image' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Next image' }))
    expect(within(lightbox).getByRole('img', { name: 'Image 2' })).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'ArrowRight' })
    fireEvent.keyDown(document, { key: 'ArrowRight' })
    expect(within(lightbox).getByRole('img', { name: 'Image 4' })).toBeInTheDocument()
    expect(screen.getByText('4 / 4')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next image' })).toBeDisabled()
  })
})
