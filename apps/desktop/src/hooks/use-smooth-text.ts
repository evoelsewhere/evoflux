import * as React from "react";

// A streamed reply arrives in bursts: one network chunk may carry a word or a
// whole paragraph, and deltas publish once per animation frame. Drawn as they
// come, the text jumps and the thread scrolls in steps. This reveals what has
// arrived at a steady pace instead, a few characters per frame, speeding up
// when it falls behind so it never lags the stream by much.

/** The reveal closes the gap to what has arrived in about this long (ms). */
const CATCH_UP_MS = 250;
/** Once the stream ended, the rest is drawn in about this long (ms). */
const FLUSH_MS = 120;
/** The slowest reveal (characters per ms), so a trickle still moves. */
const MIN_RATE = 0.04;
/** Never more than this many characters left to reveal (a chat opened mid-stream, a hidden window). */
const MAX_BACKLOG = 600;
/** A long gap between frames (the window was hidden) counts as this much (ms). */
const MAX_FRAME_MS = 50;

const reducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Keep a cut from splitting a surrogate pair (an emoji). */
function cut(text: string, at: number): number {
  const code = text.charCodeAt(at - 1);
  return code >= 0xd800 && code <= 0xdbff && at < text.length ? at + 1 : at;
}

/**
 * The part of `text` to draw now. Text already there when the component
 * mounts shows at once (a finished reply, a restored chat); text that streams
 * in afterwards is revealed smoothly. `revealing` stays true until the reveal
 * caught up, so a caller can keep its streaming affordances until then.
 */
export function useSmoothText(text: string, streaming: boolean): { text: string; revealing: boolean } {
  const [shown, setShown] = React.useState(() => (streaming && !reducedMotion() ? Math.max(0, text.length - MAX_BACKLOG) : text.length));
  const latest = React.useRef({ text, streaming, shown });
  latest.current.text = text;
  latest.current.streaming = streaming;

  const visible = Math.min(shown, text.length);
  const behind = visible < text.length;

  React.useEffect(() => {
    if (!behind) return;
    if (reducedMotion()) {
      latest.current.shown = latest.current.text.length;
      setShown(latest.current.shown);
      return;
    }
    let last = performance.now();
    let carry = 0;
    let frame = requestAnimationFrame(function tick(now) {
      const { text, streaming } = latest.current;
      const current = Math.min(latest.current.shown, text.length);
      const dt = Math.min(now - last, MAX_FRAME_MS);
      last = now;
      const backlog = text.length - current;
      carry += Math.max(backlog / (streaming ? CATCH_UP_MS : FLUSH_MS), MIN_RATE) * dt;
      const step = Math.floor(carry);
      carry -= step;
      const next = cut(text, Math.max(Math.min(text.length, current + step), text.length - MAX_BACKLOG));
      if (next !== current) {
        latest.current.shown = next;
        setShown(next);
      }
      // Runs until a render sees the reveal caught up (more text may arrive first).
      frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [behind]);

  return { text: behind ? text.slice(0, visible) : text, revealing: behind };
}
