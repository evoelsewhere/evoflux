import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
})
