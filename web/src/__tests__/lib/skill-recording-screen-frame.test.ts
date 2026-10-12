import { describe, expect, it } from 'vitest'

import {
  createActionScreenFrame,
  MAX_AUTO_SCREENSHOTS,
  MIN_SCREENSHOT_INTERVAL_MS,
  shouldCaptureActionFrame,
} from '@/lib/skill-recording-screen-frame'
import type { SkillRecordingEvent } from '@/api/client/skillRecordings'

const click: SkillRecordingEvent = {
  sequence: 8,
  elapsed_ms: 2400,
  kind: 'click',
  window: { app: 'browser.exe', title: 'Article page' },
  point: { x: -12, y: 42, display_id: 'DISPLAY1' },
  button: 'left',
  target: null,
  value_state: 'not_captured',
  value: null,
  screenshot: null,
}

describe('skill recording screen frames', () => {
  it('samples only spaced pointer actions up to the recording cap', () => {
    expect(shouldCaptureActionFrame(click, 2400 - MIN_SCREENSHOT_INTERVAL_MS + 1, 0)).toBe(false)
    expect(shouldCaptureActionFrame(click, 2400 - MIN_SCREENSHOT_INTERVAL_MS, 0)).toBe(true)
    expect(shouldCaptureActionFrame(click, 2400 - 2 * MIN_SCREENSHOT_INTERVAL_MS + 1, 2)).toBe(false)
    expect(shouldCaptureActionFrame(click, 2400 - 2 * MIN_SCREENSHOT_INTERVAL_MS, 2)).toBe(true)
    expect(shouldCaptureActionFrame(click, 0, MAX_AUTO_SCREENSHOTS)).toBe(false)
    expect(shouldCaptureActionFrame({ ...click, kind: 'focus' }, 0, 0)).toBe(false)
  })

  it('captures an image after input changes without copying typed text into its label', () => {
    const input: SkillRecordingEvent = {
      ...click,
      kind: 'value_changed',
      target: { automation_id: 'search', control_type: 'edit', name: null, label: 'Search query' },
      value_state: 'captured',
      value: 'private text',
    }

    expect(shouldCaptureActionFrame(input, 0, 1)).toBe(true)
    expect(createActionScreenFrame(input, 'cG5n').target?.name).toBe('After input in Search query')
    expect(createActionScreenFrame(input, 'cG5n').target?.name).not.toContain('private text')
  })

  it('links a screen frame to the action timing and pointer in the review label', () => {
    expect(createActionScreenFrame(click, 'cG5n')).toEqual({
      sequence: 100_008,
      elapsed_ms: 2401,
      kind: 'screenshot',
      window: { app: 'browser.exe', title: 'Article page' },
      target: {
        automation_id: null,
        control_type: 'screen frame',
        name: 'After left click at (-12, 42)',
      },
      value_state: 'not_captured',
      value: null,
      screenshot: 'cG5n',
    })
  })
})
