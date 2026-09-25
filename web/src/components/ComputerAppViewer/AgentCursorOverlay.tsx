import { cn } from '@/lib/utils'
import { pointerPosition, type Size } from './computerAppGeometry'
import './agentCursor.css'

export type PointerPhase = 'move' | 'press' | 'drag' | 'click'

export interface AgentPointer {
  /** Fraction of the app window, 0..1. */
  x: number
  y: number
  phase: PointerPhase
  /** Increments per event so a repeated click at one spot still pulses. */
  seq: number
}

/** Where the SVG's arrow tip (4, 2.7 of 24×27) sits inside its 7×8 box. */
const TIP = { x: 1.2, y: 0.8 }

/**
 * The agent's presence over the app picture: a frame that glows while the
 * agent is acting, and a virtual cursor that travels to each point before
 * the input lands there — the "someone else is driving" cue from screen
 * sharing, drawn in the card rather than on the user's desktop.
 */
export function AgentCursorOverlay({
  box,
  content,
  pointer,
  active,
}: {
  box: Size
  content: Size
  pointer: AgentPointer | null
  active: boolean
}) {
  const position = pointer ? pointerPosition(box, content, pointer) : null
  // Keyed by the event so every click remounts the ring and replays its
  // animation, even two clicks in a row at the same spot.
  const pulseKey = pointer?.phase === 'click' ? `click-${pointer.seq}` : 'idle'

  return (
    <div className="agent-control-layer" aria-hidden>
      <div className={cn('agent-control-frame', !active && 'is-idle')} />
      {position && pointer && (
        <div
          className={cn(
            'agent-control-cursor',
            (pointer.phase === 'press' || pointer.phase === 'drag') && 'is-pressed',
            pointer.phase === 'drag' && 'is-dragging',
          )}
          style={{
            '--cursor-x': `${position.x - TIP.x}px`,
            '--cursor-y': `${position.y - TIP.y}px`,
          } as React.CSSProperties}
        >
          <span className="agent-control-cursor-aura" />
          <span
            key={pulseKey}
            className={cn('agent-control-cursor-pulse', pulseKey !== 'idle' && 'is-pulsing')}
          />
          <svg viewBox="0 0 24 27">
            <path
              className="agent-control-cursor-glow"
              d="M4 2.7v18.5c0 2.6 3.2 3.8 4.9 1.8l4.35-5.2h5.95c2.55 0 3.7-3.2 1.75-4.82L7.75 1.35C6.25.1 4 1.17 4 2.7Z"
            />
            <path
              className="agent-control-cursor-outline"
              d="M4 2.7v18.5c0 2.6 3.2 3.8 4.9 1.8l4.35-5.2h5.95c2.55 0 3.7-3.2 1.75-4.82L7.75 1.35C6.25.1 4 1.17 4 2.7Z"
            />
            <path
              className="agent-control-cursor-core"
              d="M4 2.7v18.5c0 2.6 3.2 3.8 4.9 1.8l4.35-5.2h5.95c2.55 0 3.7-3.2 1.75-4.82L7.75 1.35C6.25.1 4 1.17 4 2.7Z"
            />
          </svg>
        </div>
      )}
    </div>
  )
}
