(() => {
  if (globalThis.__evofluxRegionPicker) {
    globalThis.__evofluxRegionPicker.start();
    return;
  }

  const host = document.createElement("div");
  host.style.cssText = "all:initial;position:fixed;inset:0;z-index:2147483647;display:none;cursor:crosshair;touch-action:none";
  const root = host.attachShadow({ mode: "closed" });
  const shade = document.createElement("div");
  shade.style.cssText = "position:absolute;inset:0;background:rgba(7,10,14,.28)";
  const selection = document.createElement("div");
  selection.style.cssText = "position:absolute;display:none;border:2px solid #7774ff;background:rgba(119,116,255,.12);box-shadow:0 0 0 9999px rgba(7,10,14,.34);pointer-events:none";
  const badge = document.createElement("div");
  badge.textContent = "Drag to capture · Esc to cancel";
  badge.style.cssText = "position:absolute;top:14px;left:50%;transform:translateX(-50%);border:1px solid rgba(255,255,255,.18);border-radius:8px;padding:7px 10px;background:#17191c;color:#f4f5f6;box-shadow:0 8px 28px rgba(0,0,0,.28);font:600 12px/1.2 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;letter-spacing:0;white-space:nowrap;pointer-events:none";
  root.append(shade, selection, badge);
  document.documentElement.append(host);

  let active = false;
  let pointerId = null;
  let startPoint = null;

  const pageUrl = () => `${location.origin}${location.pathname}`;
  const viewport = () => ({
    width: Math.round(window.visualViewport?.width || window.innerWidth),
    height: Math.round(window.visualViewport?.height || window.innerHeight),
    page_x: window.visualViewport?.pageLeft || window.scrollX || 0,
    page_y: window.visualViewport?.pageTop || window.scrollY || 0,
    scale: window.visualViewport?.scale || 1,
    dpr: window.devicePixelRatio || 1,
  });

  function normalizedRect(first, second) {
    const metrics = viewport();
    const left = Math.max(0, Math.min(first.x, second.x, metrics.width));
    const top = Math.max(0, Math.min(first.y, second.y, metrics.height));
    const right = Math.max(0, Math.min(Math.max(first.x, second.x), metrics.width));
    const bottom = Math.max(0, Math.min(Math.max(first.y, second.y), metrics.height));
    return { x: left, y: top, width: right - left, height: bottom - top };
  }

  function draw(rect) {
    selection.style.display = "block";
    selection.style.left = `${rect.x}px`;
    selection.style.top = `${rect.y}px`;
    selection.style.width = `${rect.width}px`;
    selection.style.height = `${rect.height}px`;
  }

  function stop() {
    active = false;
    pointerId = null;
    startPoint = null;
    selection.style.display = "none";
    host.style.display = "none";
  }

  function start() {
    active = true;
    host.style.display = "block";
  }

  function cancel(reason = null) {
    if (!active) return;
    stop();
    chrome.runtime.sendMessage({ type: "region_picker_cancelled", reason }).catch(() => {});
  }

  function onPointerDown(event) {
    if (!active || !event.isTrusted || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    pointerId = event.pointerId;
    startPoint = { x: event.clientX, y: event.clientY };
    host.setPointerCapture?.(pointerId);
    draw({ x: event.clientX, y: event.clientY, width: 0, height: 0 });
  }

  function onPointerMove(event) {
    if (!active || pointerId !== event.pointerId || !startPoint) return;
    event.preventDefault();
    draw(normalizedRect(startPoint, { x: event.clientX, y: event.clientY }));
  }

  async function onPointerUp(event) {
    if (!active || pointerId !== event.pointerId || !startPoint || !event.isTrusted) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = normalizedRect(startPoint, { x: event.clientX, y: event.clientY });
    const capturedViewport = viewport();
    stop();
    if (rect.width < 8 || rect.height < 8) {
      chrome.runtime.sendMessage({ type: "region_picker_cancelled", reason: "too_small" }).catch(() => {});
      return;
    }
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    chrome.runtime.sendMessage({
      type: "region_selected",
      selection: { page_url: pageUrl(), clip: rect, viewport: capturedViewport },
    }).catch(() => {});
  }

  function onKeyDown(event) {
    if (active && event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      cancel();
    }
  }

  host.addEventListener("pointerdown", onPointerDown, true);
  host.addEventListener("pointermove", onPointerMove, true);
  host.addEventListener("pointerup", onPointerUp, true);
  document.addEventListener("keydown", onKeyDown, true);
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "webbridge_region_picker") return;
    if (message.enabled) start();
    else stop();
    sendResponse({ ok: true });
  });

  globalThis.__evofluxRegionPicker = { start, stop };
  start();
})();
