import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SkillRecordingTimeline } from '@/components/settings/SkillRecordingTimeline'

const event = {
  sequence: 4,
  elapsed_ms: 1250,
    kind: 'value_changed' as const,
  target: { automation_id: 'customer', control_type: 'edit', name: 'Customer name' },
  value_state: 'captured' as const,
  value: 'Acme Ltd',
  screenshot: null,
}

describe('SkillRecordingTimeline', () => {
  it('lets the user exclude an event and replace its captured text', () => {
    const onToggleEvent = vi.fn()
    const onVariableChange = vi.fn()
    const onTargetLabelChange = vi.fn()

    render(
      <SkillRecordingTimeline
        recordingId="recording-1"
        events={[event]}
        selectedIds={[4]}
        variables={{}}
        targetLabels={{}}
        onToggleEvent={onToggleEvent}
        onVariableChange={onVariableChange}
        onTargetLabelChange={onTargetLabelChange}
      />,
    )

    fireEvent.click(screen.getByRole('checkbox', { name: 'Include event 4' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'Value for event 4' }), {
      target: { value: '{customer_name}' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'Label for event 4' }), {
      target: { value: 'Customer field' },
    })

    expect(onToggleEvent).toHaveBeenCalledWith(4)
    expect(onVariableChange).toHaveBeenCalledWith(4, '{customer_name}')
    expect(onTargetLabelChange).toHaveBeenCalledWith(4, 'Customer field')
  })
})
