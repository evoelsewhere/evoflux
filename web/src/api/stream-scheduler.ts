export interface StreamEvent {
  type: string
  data: unknown
}

type DispatchStreamEvent = (type: string, data: unknown) => void

const VISUAL_DELTA_EVENTS = new Set([
  'message',
  'thinking',
  'tool_output_delta',
  'widget_delta',
])

function eventRecord(data: unknown): Record<string, unknown> | null {
  return data !== null && typeof data === 'object'
    ? data as Record<string, unknown>
    : null
}

function sameDeltaTarget(a: StreamEvent, b: StreamEvent): boolean {
  if (a.type !== b.type) return false
  const left = eventRecord(a.data)
  const right = eventRecord(b.data)
  if (!left || !right) return false
  return left.agent === right.agent
    && left.tool_call_id === right.tool_call_id
    && (left.metadata as Record<string, unknown> | undefined)?.model
      === (right.metadata as Record<string, unknown> | undefined)?.model
}

function mergeDelta(previous: StreamEvent, next: StreamEvent): StreamEvent | null {
  if (!sameDeltaTarget(previous, next)) return null
  const left = eventRecord(previous.data)
  const right = eventRecord(next.data)
  if (!left || !right) return null

  if (next.type === 'widget_delta') {
    return {
      type: next.type,
      data: {
        ...left,
        ...right,
        html: `${typeof left.html === 'string' ? left.html : ''}${typeof right.html === 'string' ? right.html : ''}`,
        is_final: Boolean(left.is_final || right.is_final),
      },
    }
  }

  return {
    type: next.type,
    data: {
      ...left,
      ...right,
      text: `${typeof left.text === 'string' ? left.text : ''}${typeof right.text === 'string' ? right.text : ''}`,
    },
  }
}

/**
 * Coalesces token-like SSE events to the browser's paint cadence.
 *
 * State transitions (tool start/end, approvals, errors, done, etc.) remain
 * synchronous and flush any preceding text first, preserving wire order.
 */
export function createStreamScheduler(dispatch: DispatchStreamEvent) {
  let queue: StreamEvent[] = []
  let frame: number | null = null

  const flush = () => {
    if (frame !== null) cancelAnimationFrame(frame)
    frame = null
    if (queue.length === 0) return
    const pending = queue
    queue = []
    for (const event of pending) dispatch(event.type, event.data)
  }

  const schedule = () => {
    if (frame !== null) return
    frame = requestAnimationFrame(() => {
      frame = null
      flush()
    })
  }

  const push = (type: string, data: unknown) => {
    if (!VISUAL_DELTA_EVENTS.has(type)) {
      flush()
      dispatch(type, data)
      return
    }

    const event = { type, data }
    const previous = queue.at(-1)
    const merged = previous ? mergeDelta(previous, event) : null
    if (merged) queue[queue.length - 1] = merged
    else queue.push(event)
    schedule()
  }

  const cancel = () => {
    if (frame !== null) cancelAnimationFrame(frame)
    frame = null
    queue = []
  }

  return { cancel, flush, push }
}
