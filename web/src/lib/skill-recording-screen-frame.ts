import type { SkillRecordingEvent } from '@/api/client/skillRecordings'

export const MAX_AUTO_SCREENSHOTS = 12
export const MIN_SCREENSHOT_INTERVAL_MS = 900

export function shouldCaptureActionFrame(
  event: SkillRecordingEvent,
  lastScreenshotAt: number,
  screenshotCount: number,
): boolean {
  const spacing = MIN_SCREENSHOT_INTERVAL_MS * 2 ** Math.min(Math.max(screenshotCount - 1, 0), 8)
  return ['click', 'double_click', 'scroll', 'value_changed'].includes(event.kind) &&
    event.elapsed_ms - lastScreenshotAt >= spacing &&
    screenshotCount < MAX_AUTO_SCREENSHOTS
}

export function createActionScreenFrame(
  action: SkillRecordingEvent,
  screenshot: string,
): SkillRecordingEvent {
  const actionName = action.kind === 'value_changed'
    ? `After input${action.target?.label ? ` in ${action.target.label}` : ''}`
    : action.kind === 'scroll'
      ? `After scroll at (${action.point?.x ?? '?'}, ${action.point?.y ?? '?'})`
      : `After ${action.button ?? 'mouse'} click at (${action.point?.x ?? '?'}, ${action.point?.y ?? '?'})`
  return {
    sequence: 100_000 + action.sequence,
    elapsed_ms: action.elapsed_ms + 1,
    kind: 'screenshot',
    window: action.window ?? null,
    target: { automation_id: null, control_type: 'screen frame', name: actionName },
    value_state: 'not_captured',
    value: null,
    screenshot,
  }
}
