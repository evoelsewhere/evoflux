import { skillRecordingScreenshotUrl, type SkillRecordingEvent } from '@/api/client/skillRecordings'
import { Input } from '@/components/ui/input'

export interface SkillRecordingTimelineProps {
  recordingId: string
  events: SkillRecordingEvent[]
  selectedIds: number[]
  variables: Record<number, string>
  targetLabels: Record<number, string>
  windowTitles: Record<number, string>
  onToggleEvent: (sequence: number) => void
  onVariableChange: (sequence: number, value: string) => void
  onTargetLabelChange: (sequence: number, value: string) => void
  onWindowTitleChange: (sequence: number, value: string) => void
}

export function SkillRecordingTimeline({
  recordingId,
  events,
  selectedIds,
  variables,
  targetLabels,
  windowTitles,
  onToggleEvent,
  onVariableChange,
  onTargetLabelChange,
  onWindowTitleChange,
}: SkillRecordingTimelineProps) {
  const linkedActionSequence = (frame: SkillRecordingEvent) => {
    const sourceSequence = frame.source_sequence ?? frame.sequence
    return frame.kind === 'screenshot' && sourceSequence >= 100_000
      ? sourceSequence - 100_000
      : null
  }
  const actionSequence = (action: SkillRecordingEvent) => action.source_sequence ?? action.sequence
  const isInlineFrame = (frame: SkillRecordingEvent) => {
    const sourceSequence = linkedActionSequence(frame)
    return sourceSequence !== null && events.some((event) =>
      event.kind !== 'screenshot' && actionSequence(event) === sourceSequence,
    )
  }

  return (
    <ol className="divide-y divide-(--color-border-subtle)">
      {events.filter((event) => !isInlineFrame(event)).map((event) => (
        <li key={event.sequence} className="flex gap-3 p-4 sm:p-5">
          <input
            aria-label={`Include event ${event.sequence}`}
            type="checkbox"
            checked={selectedIds.includes(event.sequence)}
            onChange={() => onToggleEvent(event.sequence)}
            className="mt-1 size-4 accent-(--color-accent)"
          />
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <span>{event.kind === 'screenshot' ? (event.target?.name ?? 'screen frame') : event.kind === 'value_changed' ? 'input changed' : event.kind.replaceAll('_', ' ')}</span>
              {event.target?.control_type && (
                <span className="text-xs text-(--color-text-muted)">{event.target.control_type}</span>
              )}
            </div>
            {event.window && (event.window.app || event.window.title) && (
              <div className="space-y-1.5 rounded-md bg-(--bg-key)/50 p-2.5">
                {event.window.app && (
                  <p className="text-xs text-(--color-text-muted)">App: <span className="font-mono text-(--color-text)">{event.window.app}</span></p>
                )}
                {event.window.title && (
                  <label className="block space-y-1.5">
                    <span className="text-xs text-(--color-text-muted)">Window title (editable to redact)</span>
                    <Input
                      aria-label={`Window title for event ${event.sequence}`}
                      value={windowTitles[event.sequence] ?? event.window.title}
                      onChange={(change) => onWindowTitleChange(event.sequence, change.target.value)}
                      className="font-mono text-xs"
                    />
                  </label>
                )}
              </div>
            )}
            {event.target?.name && !event.target?.label && (
              <label className="block space-y-1.5">
                <span className="text-xs text-(--color-text-muted)">Element label</span>
                <Input
                  aria-label={`Label for event ${event.sequence}`}
                  value={targetLabels[event.sequence] ?? event.target.name}
                  onChange={(change) => onTargetLabelChange(event.sequence, change.target.value)}
                  className="font-mono text-xs"
                />
              </label>
            )}
            {event.target?.label && (
              <label className="block space-y-1.5">
                <span className="text-xs text-(--color-text-muted)">Input field label</span>
                <Input
                  aria-label={`Field label for event ${event.sequence}`}
                  value={targetLabels[event.sequence] ?? event.target.label}
                  onChange={(change) => onTargetLabelChange(event.sequence, change.target.value)}
                  className="font-mono text-xs"
                />
              </label>
            )}
            {event.value_state === 'captured' && event.value && (
              <label className="block space-y-1.5">
                <span className="text-xs text-(--color-text-muted)">Captured value</span>
                <div className="flex flex-wrap gap-2">
                  <Input
                    aria-label={`Value for event ${event.sequence}`}
                    value={variables[event.sequence] ?? event.value}
                    onChange={(change) => onVariableChange(event.sequence, change.target.value)}
                    className="min-w-48 flex-1 font-mono text-xs"
                  />
                  <span className="self-center text-xs text-(--color-text-muted)">
                    Shown in preview; edit to redact.
                  </span>
                </div>
              </label>
            )}
            {event.kind === 'screenshot' && (
              <img
                src={skillRecordingScreenshotUrl(recordingId, event.sequence)}
                alt={`Local screen frame ${event.sequence}`}
                className="max-h-56 max-w-full rounded-md border border-(--color-border)"
              />
            )}
            {event.kind !== 'screenshot' && events
              .filter((frame) => frame.kind === 'screenshot' && linkedActionSequence(frame) === actionSequence(event))
              .map((frame) => (
                <div key={frame.sequence} className="space-y-2 rounded-md border border-(--color-border-subtle) bg-(--bg-key)/30 p-2.5">
                  <label className="flex items-center gap-2 text-xs text-(--color-text-muted)">
                    <input
                      aria-label={`Include screenshot after event ${event.sequence}`}
                      type="checkbox"
                      checked={selectedIds.includes(frame.sequence)}
                      onChange={() => onToggleEvent(frame.sequence)}
                      className="size-3.5 accent-(--color-accent)"
                    />
                    <span>{frame.target?.name ?? 'Screenshot after this action'}</span>
                  </label>
                  <img
                    src={skillRecordingScreenshotUrl(recordingId, frame.sequence)}
                    alt={`Screen evidence after event ${event.sequence}`}
                    className="max-h-56 max-w-full rounded-md border border-(--color-border)"
                  />
                </div>
              ))}
            {event.value_state === 'omitted_secure' && (
              <p className="text-xs text-(--color-text-muted)">Secure value omitted.</p>
            )}
          </div>
          <span className="shrink-0 font-mono text-[11px] text-(--color-text-muted)">
            {(event.elapsed_ms / 1000).toFixed(1)}s
          </span>
        </li>
      ))}
    </ol>
  )
}
