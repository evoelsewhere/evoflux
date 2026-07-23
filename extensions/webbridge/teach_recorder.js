(() => {
  if (globalThis.__evofluxTeachRecorder) return;

  let enabled = false;
  const SECRET_PATTERN = /\b(pass(word)?|passcode|secret|token|api[-_ ]?key|credit|card|cvv|cvc|csc|ssn|otp|mfa|2fa|pin|security[-_ ]?answer|recovery[-_ ]?code)\b/i;
  const SECRET_AUTOCOMPLETE = new Set([
    "current-password",
    "new-password",
    "one-time-code",
    "cc-number",
    "cc-exp",
    "cc-exp-month",
    "cc-exp-year",
    "cc-csc",
  ]);

  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();

  function selectorFor(element) {
    for (const attribute of ["data-testid", "data-test", "data-qa"]) {
      const value = element.getAttribute(attribute);
      if (value) return `[${attribute}=${JSON.stringify(value)}]`;
    }
    if (element.id) return `#${CSS.escape(element.id)}`;
    const name = element.getAttribute("name");
    if (name) return `${element.tagName.toLowerCase()}[name=${JSON.stringify(name)}]`;
    const label = element.getAttribute("aria-label");
    if (label) return `${element.tagName.toLowerCase()}[aria-label=${JSON.stringify(label)}]`;

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

  function isSecretField(element) {
    if (!(element instanceof HTMLInputElement) && !(element instanceof HTMLTextAreaElement)) {
      return false;
    }
    const details = [
      element instanceof HTMLInputElement ? element.type : "",
      element.name,
      element.id,
      element.autocomplete,
      element.getAttribute("aria-label"),
      element.placeholder,
    ]
      .join(" ")
      .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ");
    const autocompleteTokens = String(element.autocomplete || "")
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean);
    return (
      (element instanceof HTMLInputElement && element.type === "password") ||
      autocompleteTokens.some((token) => SECRET_AUTOCOMPLETE.has(token)) ||
      SECRET_PATTERN.test(details)
    );
  }

  function parameterName(element) {
    const raw = normalize(
      element.name || element.id || element.getAttribute("aria-label") || "secret"
    ).replace(/[^A-Za-z0-9_]+/g, "_").replace(/^([^A-Za-z])/, "secret_");
    return (raw || "secret").slice(0, 64);
  }

  function send(action) {
    if (!enabled) return;
    chrome.runtime.sendMessage({ type: "teach_action", action }).catch(() => {
      // A navigation can tear down the service worker or page between event and send.
    });
  }

  function onClick(event) {
    if (!enabled || !event.isTrusted || !(event.target instanceof Element)) return;
    const element = event.target.closest("a[href],button,[role=button],[role=link],input[type=button],input[type=submit]");
    if (!element || element instanceof HTMLInputElement) return;
    send({ kind: "click", selector: selectorFor(element) });
  }

  function onChange(event) {
    if (!enabled || !event.isTrusted || !(event.target instanceof Element)) return;
    const element = event.target;
    if (element instanceof HTMLSelectElement) {
      send({
        kind: "select",
        selector: selectorFor(element),
        values: [...element.selectedOptions].map((option) => option.value).filter(Boolean),
      });
      return;
    }
    if (element instanceof HTMLInputElement) {
      if (["hidden", "file", "button", "submit", "reset"].includes(element.type)) return;
      if (["checkbox", "radio"].includes(element.type)) {
        send({ kind: "set_checked", selector: selectorFor(element), checked: element.checked });
        return;
      }
      if (isSecretField(element)) {
        send({
          kind: "fill",
          selector: selectorFor(element),
          secret: true,
          parameter: parameterName(element),
        });
        return;
      }
      send({ kind: "fill", selector: selectorFor(element), value: element.value });
      return;
    }
    if (element instanceof HTMLTextAreaElement) {
      if (isSecretField(element)) {
        send({
          kind: "fill",
          selector: selectorFor(element),
          secret: true,
          parameter: parameterName(element),
        });
        return;
      }
      send({ kind: "fill", selector: selectorFor(element), value: element.value });
    }
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "webbridge_teach_recording") return;
    enabled = Boolean(message.enabled);
    sendResponse({ ok: true });
  });
  document.addEventListener("click", onClick, true);
  document.addEventListener("change", onChange, true);
  globalThis.__evofluxTeachRecorder = true;
})();