import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { WidgetRenderer } from '@/components/WidgetRenderer'

afterEach(() => {
  document.documentElement.style.removeProperty('--bg-page')
  document.documentElement.style.removeProperty('--color-text')
  document.documentElement.style.removeProperty('--color-accent')
})

describe('WidgetRenderer theme bridge', () => {
  it('seeds the iframe document with the current EvoFlux theme tokens', () => {
    document.documentElement.style.setProperty('--bg-page', '#222222')
    document.documentElement.style.setProperty('--color-text', '#f2f2f2')
    document.documentElement.style.setProperty('--color-accent', '#d97757')

    render(<WidgetRenderer title="Diagram preview" html="<svg aria-label='Preview'></svg>" />)

    const frame = screen.getByTitle('Diagram preview') as HTMLIFrameElement
    expect(frame.srcdoc).toContain('--bg-page: #222222')
    expect(frame.srcdoc).toContain('--color-text: #f2f2f2')
    expect(frame.srcdoc).toContain('--color-accent: #d97757')
  })

  it('syncs updated appearance tokens into an already open widget', async () => {
    render(<WidgetRenderer title="Live diagram" html="<svg aria-label='Preview'></svg>" />)
    const frame = screen.getByTitle('Live diagram') as HTMLIFrameElement

    document.documentElement.style.setProperty('--color-accent', '#2563eb')

    await waitFor(() => {
      expect(frame.contentDocument?.documentElement.style.getPropertyValue('--color-accent')).toBe('#2563eb')
    })
  })
})
