import { skillRecordingScreenshotUrl, type SkillRecordingEvent } from '@/api/client/skillRecordings'
import { Input } from '@/components/ui/input'

export interface SkillRecordingTimelineProps {
  recordingId: string
  events: SkillRecordingEvent[]
  selectedIds: number[]
  variables: Record<number, string>
  targetLabels: Record<number, string>
  onToggleEvent: (sequence: number) => void
  onVariableChange: (sequence: number, value: string) => void
  onTargetLabelChange: (sequence: number, value: string) => void
}

export function SkillRecordingTimeline({
  recordingId,
  events,
  selectedIds,
  variables,
  targetLabels,
  onToggleEvent,
  onVariableChange,
  onTargetLabelChange,
}: SkillRecordingTimelineProps) {
  return (
    <ol className="divide-y divide-(--color-border-subtle)">
      {events.map((event) => (
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
              <span>{event.kind.replaceAll('_', ' ')}</span>
              {event.target?.control_type && (
                <span className="text-xs text-(--color-text-muted)">{event.target.control_type}</span>
              )}
            </div>
            {event.target?.name && (
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
                alt={`Local screenshot checkpoint ${event.sequence}`}
                className="max-h-56 max-w-full rounded-md border border-(--color-border)"
              />
            )}
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
