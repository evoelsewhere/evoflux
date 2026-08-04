/**
 * Page-local text watch runtime.
 *
 * Detects a configured phrase without sending page text to the extension.
 * Only the opaque watch id and current URL cross the isolated-world boundary.
 */
(() => {
  if (globalThis.__evofluxTextWatchRuntime) return;

  let observer = null;
  let timer = null;
  let activeWatch = null;
  let matched = false;

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
  }

  function stop() {
    observer?.disconnect();
    observer = null;
    clearTimeout(timer);
    timer = null;
    activeWatch = null;
    matched = false;
  }

  function check() {
    timer = null;
    if (!activeWatch || matched) return;
    const root = document.body || document.documentElement;
    const text = normalize(root?.innerText || root?.textContent || "");
    if (!text.includes(normalize(activeWatch.needle))) return;
    matched = true;
    observer?.disconnect();
    chrome.runtime.sendMessage({
      type: "webbridge_text_watch_matched",
      watch_id: activeWatch.id,
      page_url: location.href,
    }).catch(() => {});
  }

  function scheduleCheck() {
    if (!activeWatch || matched || timer != null) return;
    timer = setTimeout(check, 200);
  }

  function start(watch) {
    stop();
    if (!watch?.id || !normalize(watch.needle)) return false;
    activeWatch = { id: String(watch.id), needle: String(watch.needle) };
    observer = new MutationObserver(scheduleCheck);
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    check();
    return true;
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "webbridge_text_watch") return;
    const watching = message.enabled ? start(message.watch) : (stop(), false);
    sendResponse({ ok: true, watching });
  });

  globalThis.__evofluxTextWatchRuntime = { start, stop, check };
})();
