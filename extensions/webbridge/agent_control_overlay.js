/**
 * EvoFlux agent-control overlay.
 *
 * Injected on demand into the top frame while WebBridge owns the tab. The
 * closed-over state is intentionally page-local: navigation removes it, and
 * the service worker restores it only when the debugger is still attached.
 */
(() => {
  if (globalThis.__evofluxAgentControlOverlay) return;

  const HOST_ID = "__evoflux-agent-control-overlay";
  let host = null;
  let cursor = null;
  let cursorPulse = null;
  let enabled = false;
  let suspended = false;
  let lastX = null;
  let lastY = null;
  let pulseTimer = null;

  function mount() {
    if (host?.isConnected) return;
    host = document.getElementById(HOST_ID);
    if (host) {
      cursor = host.shadowRoot?.querySelector(".cursor") || null;
      cursorPulse = host.shadowRoot?.querySelector(".cursor-pulse") || null;
      return;
    }

    host = document.createElement("div");
    host.id = HOST_ID;
    host.setAttribute("aria-hidden", "true");
    host.style.cssText = "all:initial;position:fixed;inset:0;pointer-events:none;z-index:2147483647;contain:layout style;";
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { all: initial; }
        .layer { position: fixed; inset: 0; overflow: hidden; pointer-events: none; }
        .frame {
          position: absolute; inset: 0;
          border: 2px solid rgba(121, 247, 255, .92);
          box-shadow:
            inset 0 0 12px rgba(0, 238, 255, .95),
            inset 0 0 34px rgba(45, 205, 224, .24),
            inset 0 0 70px rgba(0, 224, 255, .18);
          animation: evoflux-frame-bloom 1.8s ease-in-out infinite;
        }
        .frame::after {
          content: ""; position: absolute; inset: 0;
          border: 1px solid rgba(198, 255, 255, .7);
          box-shadow: inset 0 0 18px rgba(82, 247, 255, .42);
          animation: evoflux-frame-wave 1.8s ease-out infinite;
        }
        .badge {
          position: absolute; top: 11px; left: 50%; transform: translateX(-50%);
          display: flex; align-items: center; gap: 7px; padding: 6px 11px;
          border: 1px solid rgba(133, 249, 255, .72); border-radius: 999px;
          background: rgba(5, 11, 28, .82); color: #eaffff;
          box-shadow: 0 0 12px rgba(55, 240, 255, .5), 0 0 24px rgba(55, 210, 228, .18);
          font: 700 10px/1.1 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          letter-spacing: .13em; text-transform: uppercase; backdrop-filter: blur(8px);
        }
        .badge-dot { width: 7px; height: 7px; border-radius: 50%; background: #7ffcff; box-shadow: 0 0 9px #5effff; animation: evoflux-dot 1s ease-in-out infinite alternate; }
        .cursor {
          position: absolute; left: 0; top: 0; width: 17px; height: 18px;
          transform: translate3d(var(--cursor-x, 72vw), var(--cursor-y, 34vh), 0);
          transform-origin: 3px 2.5px;
          transition: transform 28ms linear;
          will-change: transform;
        }
        .cursor-aura {
          position: absolute; left: -2px; top: -2px; width: 14px; height: 14px;
          border-radius: 50%; opacity: .34;
          background: radial-gradient(circle, rgba(255, 255, 255, .38) 0 8%, rgba(91, 221, 239, .14) 34%, transparent 72%);
          filter: blur(2px);
        }
        .cursor svg {
          position: relative; display: block; width: 100%; height: 100%; overflow: visible;
          filter: drop-shadow(0 1px 1px rgba(0, 0, 0, .38)) drop-shadow(0 0 3px rgba(72, 202, 224, .42));
        }
        .cursor-outline { fill: none; stroke: rgba(255, 255, 255, .96); stroke-width: 2.7; stroke-linejoin: round; stroke-linecap: round; }
        .cursor-core { fill: url(#evoflux-cursor-fill); stroke: #10151a; stroke-width: .85; stroke-linejoin: round; stroke-linecap: round; }
        .cursor-pulse {
          position: absolute; left: -4px; top: -4px; width: 14px; height: 14px;
          border: 1.5px solid rgba(105, 229, 241, .78); border-radius: 50%; opacity: 0; transform: scale(.25);
        }
        .cursor.pressed { transform: translate3d(var(--cursor-x), var(--cursor-y), 0) scale(.9); transition-duration: 55ms; }
        .cursor.pressed .cursor-aura { opacity: .78; filter: blur(2px); }
        .cursor.pulsing .cursor-pulse { animation: evoflux-click .42s ease-out; }
        @keyframes evoflux-frame-bloom {
          0%, 100% { opacity: .68; }
          50% { opacity: 1; }
        }
        @keyframes evoflux-frame-wave {
          0% { opacity: .8; box-shadow: inset 0 0 8px rgba(82, 247, 255, .48); }
          70%, 100% { opacity: .12; box-shadow: inset 0 0 54px rgba(82, 247, 255, .08); }
        }
        @keyframes evoflux-dot { from { opacity: .55; transform: scale(.82); } to { opacity: 1; transform: scale(1.2); } }
        @keyframes evoflux-click { 0% { opacity: 1; transform: scale(.25); } 100% { opacity: 0; transform: scale(2.2); } }
        @media (prefers-reduced-motion: reduce) {
          .frame, .frame::after, .badge-dot { animation: none; }
          .cursor { transition-duration: 0ms; }
        }
      </style>
      <div class="layer">
        <div class="frame"></div>
        <div class="badge"><span class="badge-dot"></span><span>EvoFlux control</span></div>
        <div class="cursor">
          <span class="cursor-aura"></span>
          <span class="cursor-pulse"></span>
          <svg viewBox="0 0 17 18" aria-hidden="true">
            <defs>
              <linearGradient id="evoflux-cursor-fill" x1="3" y1="2.5" x2="9" y2="13" gradientUnits="userSpaceOnUse">
                <stop offset="0" stop-color="#20272d"/>
                <stop offset=".55" stop-color="#0d1115"/>
                <stop offset="1" stop-color="#020405"/>
              </linearGradient>
            </defs>
            <path class="cursor-outline" d="M3 2.7 14.1 10.4 7.6 12.2Z"/>
            <path class="cursor-core" d="M3 2.7 14.1 10.4 7.6 12.2Z"/>
          </svg>
        </div>
      </div>`;
    cursor = root.querySelector(".cursor");
    cursorPulse = root.querySelector(".cursor-pulse");
    if (lastX == null || lastY == null) {
      lastX = Math.max(0, Math.min(innerWidth - 1, innerWidth * 0.72));
      lastY = Math.max(0, Math.min(innerHeight - 1, innerHeight * 0.34));
    }
    cursor.style.setProperty("--cursor-x", `${lastX - 3}px`);
    cursor.style.setProperty("--cursor-y", `${lastY - 2.5}px`);
    (document.documentElement || document).appendChild(host);
    host.style.visibility = suspended ? "hidden" : "visible";
  }

  function unmount() {
    clearTimeout(pulseTimer);
    pulseTimer = null;
    host?.remove();
    host = null;
    cursor = null;
    cursorPulse = null;
  }

  function movePointer(x, y, phase = "move") {
    if (!cursor || !Number.isFinite(x) || !Number.isFinite(y)) return;
    lastX = Math.max(0, Math.min(innerWidth - 1, x));
    lastY = Math.max(0, Math.min(innerHeight - 1, y));
    // The SVG pointer tip is at (3, 2.7); offset the visual so its tip is the
    // exact CSS-pixel coordinate sent to CDP.
    cursor.style.setProperty("--cursor-x", `${lastX - 3}px`);
    cursor.style.setProperty("--cursor-y", `${lastY - 2.5}px`);
    cursor.classList.toggle("pressed", phase === "press" || phase === "drag");
    if (phase !== "release" && phase !== "click") return;
    cursor.classList.remove("pressed");
    cursor.classList.remove("pulsing");
    void cursorPulse?.offsetWidth;
    cursor.classList.add("pulsing");
    clearTimeout(pulseTimer);
    pulseTimer = setTimeout(() => cursor?.classList.remove("pulsing"), 460);
  }

  function setEnabled(nextEnabled) {
    enabled = Boolean(nextEnabled);
    if (!enabled) {
      unmount();
      return;
    }
    mount();
    if (lastX != null && lastY != null) movePointer(lastX, lastY);
  }

  function setSuspended(nextSuspended) {
    suspended = Boolean(nextSuspended);
    if (!host) return;
    host.style.visibility = suspended ? "hidden" : "visible";
    // Force style resolution before acknowledging a capture suspension so the
    // following CDP screenshot command cannot reuse the previous visible frame.
    void host.offsetHeight;
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "webbridge_agent_control") return;
    if (typeof message.enabled === "boolean") setEnabled(message.enabled);
    if (typeof message.suspended === "boolean") setSuspended(message.suspended);
    if (enabled && message.pointer) {
      movePointer(Number(message.pointer.x), Number(message.pointer.y), message.pointer.phase);
    }
    sendResponse({
      ok: true,
      enabled,
      suspended,
      pointer: lastX == null || lastY == null ? null : { x: lastX, y: lastY },
    });
  });

  globalThis.__evofluxAgentControlOverlay = { setEnabled, setSuspended, movePointer };
})();
