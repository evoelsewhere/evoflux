import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ToolAttachments } from '@/components/ToolCall'

describe('ToolAttachments', () => {
  it('renders generated presentations as previewable, downloadable artifacts', () => {
    render(
      <ToolAttachments
        attachments={[
          {
            filename: 'decision-deck.pptx',
            original_name: 'decision-deck.pptx',
            media_type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            category: 'document',
            url: '/api/team/session/media/decision-deck.pptx',
            preview_url: '/api/team/session/office-preview/decision-deck.pptx',
            download_url: '/api/team/session/media/decision-deck.pptx?download=1',
            workspace_path: 'decision-deck.pptx',
          },
        ]}
      />,
    )

    expect(screen.getByRole('button', { name: 'decision-deck.pptx' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Download decision-deck.pptx' })).toBeInTheDocument()
  })
})
