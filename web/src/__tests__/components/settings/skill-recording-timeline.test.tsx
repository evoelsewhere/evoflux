import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SkillRecordingTimeline } from '@/components/settings/SkillRecordingTimeline'

const event = {
  sequence: 4,
  elapsed_ms: 1250,
  kind: 'value_changed' as const,
  window: { app: 'browser.exe', title: 'Article page' },
  target: { automation_id: 'customer', control_type: 'edit', name: null, label: 'Customer name' },
  value_state: 'captured' as const,
  value: 'Acme International',
  screenshot: null,
}

describe('SkillRecordingTimeline', () => {
  it('shows app/window context and lets the user redact the window title', () => {
    const onToggleEvent = vi.fn()
    const onVariableChange = vi.fn()
    const onTargetLabelChange = vi.fn()
    const onWindowTitleChange = vi.fn()

    render(
      <SkillRecordingTimeline
        recordingId="recording-1"
        events={[event]}
        selectedIds={[4]}
        variables={{}}
        targetLabels={{}}
        windowTitles={{}}
        onToggleEvent={onToggleEvent}
        onVariableChange={onVariableChange}
        onTargetLabelChange={onTargetLabelChange}
        onWindowTitleChange={onWindowTitleChange}
      />,
    )

    expect(screen.getByText('App:')).toBeVisible()
    expect(screen.getByText('browser.exe')).toBeVisible()
    expect(screen.getByText('input changed')).toBeVisible()
    expect(screen.getByRole('textbox', { name: 'Field label for event 4' })).toHaveValue('Customer name')
    expect(screen.getByRole('textbox', { name: 'Value for event 4' })).toHaveValue('Acme International')
    fireEvent.change(screen.getByRole('textbox', { name: 'Field label for event 4' }), {
      target: { value: 'Account name' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'Window title for event 4' }), {
      target: { value: '{window_title}' },
    })
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include event 4' }))

    expect(onToggleEvent).toHaveBeenCalledWith(4)
    expect(onWindowTitleChange).toHaveBeenCalledWith(4, '{window_title}')
    expect(onVariableChange).not.toHaveBeenCalled()
    expect(onTargetLabelChange).toHaveBeenCalledWith(4, 'Account name')
  })
})
