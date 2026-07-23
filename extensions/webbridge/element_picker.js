(() => {
  if (globalThis.__evofluxElementPicker) return;

  let enabled = false;
  let highlighted = null;
  let previousOutline = "";
  let previousOffset = "";

  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();

  function selectorFor(element) {
    for (const attribute of ["data-testid", "data-test", "data-qa"]) {
      const value = element.getAttribute(attribute);
      if (value) return `[${attribute}=${JSON.stringify(value)}]`;
    }
    if (element.id) return `#${CSS.escape(element.id)}`;
    const name = element.getAttribute("name");
    if (name) return `${element.tagName.toLowerCase()}[name=${JSON.stringify(name)}]`;
    const parts = [];
    let current = element;
    for (let depth = 0; current && depth < 4; depth += 1) {
      let part = current.tagName.toLowerCase();
      const parent = current.parentElement;
      if (parent) {
        const siblings = [...parent.children].filter((candidate) => candidate.tagName === current.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
      }
      parts.unshift(part);
      current = parent;
    }
    return parts.join(" > ");
  }

  function accessibleName(element) {
    const aria = normalize(element.getAttribute("aria-label"));
    if (aria) return aria;
    const labels = element.labels ? normalize([...element.labels].map((label) => label.textContent).join(" ")) : "";
    if (labels) return labels;
    return normalize(element.getAttribute("alt") || element.getAttribute("title") || element.textContent).slice(0, 200);
  }

  function clearHighlight() {
    if (!highlighted) return;
    highlighted.style.outline = previousOutline;
    highlighted.style.outlineOffset = previousOffset;
    highlighted = null;
  }

  function highlight(element) {
    if (highlighted === element) return;
    clearHighlight();
    highlighted = element;
    previousOutline = element.style.outline;
    previousOffset = element.style.outlineOffset;
    element.style.outline = "2px solid #6d6af6";
    element.style.outlineOffset = "2px";
  }

  function stop() {
    enabled = false;
    clearHighlight();
  }

  function onMove(event) {
    if (!enabled || !(event.target instanceof Element)) return;
    highlight(event.target);
  }

  function onClick(event) {
    if (!enabled || !event.isTrusted || !(event.target instanceof Element)) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    const element = event.target;
    const isFormControl = element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement;
    const payload = {
      page_url: `${location.origin}${location.pathname}`,
      selector: selectorFor(element),
      tag: element.tagName.toLowerCase(),
      role: normalize(element.getAttribute("role")),
      name: accessibleName(element),
      // Never read form-control values. Text content is safe only for non-controls.
      text: isFormControl ? "" : normalize(element.textContent).slice(0, 500),
    };
    stop();
    chrome.runtime.sendMessage({ type: "element_picked", element: payload }).catch(() => {});
  }

  function onKey(event) {
    if (enabled && event.key === "Escape") stop();
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "webbridge_element_picker") return;
    enabled = Boolean(message.enabled);
    if (!enabled) clearHighlight();
    sendResponse({ ok: true });
  });
  document.addEventListener("mousemove", onMove, true);
  document.addEventListener("click", onClick, true);
  document.addEventListener("keydown", onKey, true);
  globalThis.__evofluxElementPicker = true;
})();