// Injected into every page of the in-app browser (src/browser.rs) before its
// own scripts. It keeps the page's console and errors, and gives the agent a
// readable outline of the page with stable element refs (`ref_N`) to act on.
// The page cannot reach the app: these pages have no IPC.
(() => {
  if (window.__evo) return;
  const logs = [];
  let logSeq = 0;
  const text = (value) => {
    try {
      if (typeof value === "string") return value;
      if (value instanceof Error) return value.stack || value.message;
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  };
  const push = (level, args) => {
    logs.push({ seq: ++logSeq, level, at: Date.now(), text: args.map(text).join(" ").slice(0, 4000) });
    if (logs.length > 500) logs.shift();
  };
  for (const level of ["log", "info", "warn", "error", "debug"]) {
    const original = console[level];
    console[level] = function (...args) {
      try {
        push(level, args);
      } catch {}
      return original.apply(this, args);
    };
  }
  addEventListener("error", (event) => {
    // Resource load failures (img, script) reach here too, without a message.
    if (!event.message && event.target && event.target !== window) {
      const target = event.target;
      push("error", [`Failed to load ${target.tagName?.toLowerCase() || "resource"} ${target.src || target.href || ""}`.trim()]);
      return;
    }
    push("error", [`${event.message}${event.filename ? ` (${event.filename}:${event.lineno})` : ""}`]);
  }, true);
  addEventListener("unhandledrejection", (event) => {
    push("error", [`Unhandled rejection: ${text(event.reason?.stack || event.reason)}`]);
  });

  let seq = 0;
  const refs = new Map();
  const refOf = (el) => {
    if (!el.__evoRef) {
      el.__evoRef = `ref_${++seq}`;
      refs.set(el.__evoRef, new WeakRef(el));
    }
    return el.__evoRef;
  };
  const byRef = (ref) => {
    const el = refs.get(String(ref))?.deref();
    if (!el || !el.isConnected) throw new Error(`${ref} is no longer on the page; read the page again`);
    return el;
  };
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "HEAD", "META", "LINK"]);
  const shown = (el) => {
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
    if (style.display === "contents") return true;
    const rect = el.getBoundingClientRect();
    // An empty box can still hold visible content (absolutely placed children).
    return rect.width > 0 || rect.height > 0 || (style.overflow === "visible" && !!el.firstElementChild);
  };
  const INTERACTIVE =
    'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[role=checkbox],[role=radio],[role=switch],[role=tab],[role=menuitem],[role=option],[role=combobox],[role=textbox],[role=slider],[contenteditable=""],[contenteditable=true],[tabindex]:not([tabindex="-1"])';
  const inputRole = (el) =>
    ({ checkbox: "checkbox", radio: "radio", button: "button", submit: "button", reset: "button", image: "button", range: "slider", search: "searchbox", file: "file" })[
      (el.type || "").toLowerCase()
    ] || "textbox";
  const roleOf = (el) => {
    const explicit = el.getAttribute("role");
    if (explicit) return explicit;
    const tag = el.tagName;
    if (tag === "A") return el.hasAttribute("href") ? "link" : "";
    if (tag === "BUTTON" || tag === "SUMMARY") return "button";
    if (tag === "INPUT") return inputRole(el);
    if (tag === "SELECT") return "combobox";
    if (tag === "TEXTAREA") return "textbox";
    if (tag === "IMG") return "img";
    if (/^H[1-6]$/.test(tag)) return "heading";
    if (el.isContentEditable) return "textbox";
    return "";
  };
  const clean = (value, max = 120) => {
    const flat = (value || "").replace(/\s+/g, " ").trim();
    return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
  };
  const nameOf = (el) => {
    const labelled = el.getAttribute("aria-labelledby");
    if (labelled) {
      const label = labelled
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.innerText || "")
        .join(" ");
      if (clean(label)) return clean(label);
    }
    return clean(
      el.getAttribute("aria-label") ||
        el.getAttribute("alt") ||
        el.labels?.[0]?.innerText ||
        el.getAttribute("title") ||
        el.getAttribute("placeholder") ||
        (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA" ? "" : el.innerText) ||
        el.getAttribute("name") ||
        el.getAttribute("value") ||
        "",
    );
  };
  const typeOf = (el) => {
    if (el.tagName !== "INPUT") return "";
    const type = (el.type || "text").toLowerCase();
    return ["text", "checkbox", "radio", "button", "submit", "reset", "image", "range", "search"].includes(type) ? "" : type;
  };
  const describe = (el) => {
    const role = roleOf(el) || el.tagName.toLowerCase();
    const name = nameOf(el);
    const parts = [`${role}${name ? ` "${name}"` : ""}`];
    if (typeOf(el)) parts.push(`type=${typeOf(el)}`);
    if (el.tagName === "A" && el.href) parts.push(`href=${clean(el.getAttribute("href"), 80)}`);
    if (el.tagName === "SELECT") parts.push(`value="${clean(el.selectedOptions?.[0]?.text, 80)}"`);
    else if ("value" in el && el.value && el.type !== "password" && el.tagName !== "BUTTON") parts.push(`value="${clean(el.value, 80)}"`);
    if (el.type === "password" && el.value) parts.push("value=••••");
    if (el.isContentEditable && el.textContent) parts.push(`value="${clean(el.textContent, 80)}"`);
    if (el.checked || el.getAttribute("aria-checked") === "true") parts.push("checked");
    if (el.disabled || el.getAttribute("aria-disabled") === "true") parts.push("disabled");
    if (el.getAttribute("aria-expanded")) parts.push(`expanded=${el.getAttribute("aria-expanded")}`);
    if (el.getAttribute("aria-selected") === "true") parts.push("selected");
    if (document.activeElement === el) parts.push("focused");
    return `${parts.join(" ")} [${refOf(el)}]`;
  };
  const isInline = (el) => ["inline", "contents", "inline-block", "inline-flex"].includes(getComputedStyle(el).display);

  /** Walk the page into lines: headings, text with inline links, and elements with refs. */
  const outline = (filter, maxChars) => {
    const lines = [];
    let size = 0;
    let full = false;
    let line = "";
    const add = (value) => {
      if (full || !value) return;
      const room = maxChars - size;
      if (value.length + 1 > room) {
        if (room > 200) lines.push(`${value.slice(0, room - 1)}…`);
        full = true;
        return;
      }
      lines.push(value);
      size += value.length + 1;
    };
    const flush = () => {
      const value = line.replace(/\s+/g, " ").replace(/ ([,.;:!?)])/g, "$1").trim();
      line = "";
      if (filter === "all") add(value);
    };
    const visit = (el, inline) => {
      for (const node of el.childNodes) {
        if (full) return;
        if (node.nodeType === 3) {
          line += node.nodeValue;
          continue;
        }
        if (node.nodeType !== 1 || SKIP.has(node.tagName.toUpperCase())) continue;
        const child = node;
        if (!shown(child)) continue;
        const tag = child.tagName;
        if (/^H[1-6]$/.test(tag)) {
          flush();
          add(`${"#".repeat(Number(tag[1]))} ${clean(child.innerText, 300)} [${refOf(child)}]`);
          for (const inner of child.querySelectorAll(INTERACTIVE)) if (shown(inner)) add(`- ${describe(inner)}`);
          continue;
        }
        if (tag === "PRE") {
          flush();
          if (filter === "all") add(child.innerText.replace(/\n+$/, ""));
          continue;
        }
        if (tag === "BR") {
          if (inline) line += " ";
          else flush();
          continue;
        }
        if (child.matches(INTERACTIVE)) {
          const nested = child.querySelector(`${INTERACTIVE},h1,h2,h3,h4,h5,h6,p,li,table`);
          if (filter === "all" && isInline(child) && !nested) {
            // A link or control inside text stays in its sentence.
            line += roleOf(child) === "link" ? ` [${clean(child.innerText, 200) || nameOf(child)}](${refOf(child)}) ` : ` {${describe(child)}} `;
            continue;
          }
          flush();
          add(`- ${describe(child)}`);
          // Containers (a clickable card, a scroll area) still show what they hold.
          if (nested || child.children.length > 3) visit(child, false);
          flush();
          continue;
        }
        if (tag === "IMG") {
          const alt = nameOf(child);
          if (filter === "all" && alt) {
            if (isInline(child)) line += ` [img "${alt}"] `;
            else {
              flush();
              add(`- img "${alt}"`);
            }
          }
          continue;
        }
        if (tag === "IFRAME") {
          flush();
          add(`- iframe ${clean(child.getAttribute("title") || child.src, 120)} (its content is not read)`);
          continue;
        }
        if (isInline(child)) {
          visit(child, true);
          continue;
        }
        // A table row stays on one line: cells joined with " | ".
        if (tag === "TD" || tag === "TH") {
          if (line.trim()) line += " | ";
          visit(child, true);
          continue;
        }
        flush();
        visit(child, false);
        flush();
      }
    };
    visit(document.body || document.documentElement, false);
    flush();
    return { lines, full };
  };

  /**
   * The innermost visible elements whose text contains `needle`, in page
   * order (a phrase can span inline tags: "<b>Workflows</b> are").
   */
  const textMatches = (needle, limit) => {
    const hits = [];
    const has = (el) => (el.textContent || "").replace(/\s+/g, " ").toLowerCase().includes(needle);
    const visit = (el) => {
      let inChild = false;
      for (const child of el.children) {
        if (hits.length >= limit) return true;
        if (SKIP.has(child.tagName.toUpperCase()) || !has(child)) continue;
        if (visit(child)) inChild = true;
      }
      if (inChild || hits.length >= limit) return inChild;
      if (!shown(el)) return false;
      hits.push({ parent: el });
      return true;
    };
    const root = document.body || document.documentElement;
    if (needle && has(root)) visit(root);
    return hits;
  };

  window.__evo = {
    /** An outline: headings, text (filter "all") and interactive elements with refs. */
    readPage({ filter = "all", maxChars = 30000 } = {}) {
      const head = [
        `URL: ${location.href}`,
        `Title: ${document.title || "(none)"}`,
        `Viewport: ${innerWidth}x${innerHeight}, scrolled ${Math.round(scrollY)} of ${Math.max(0, document.documentElement.scrollHeight - innerHeight)}`,
        document.readyState !== "complete" ? `Still loading (${document.readyState})` : "",
        "",
      ].filter((l, i, all) => l || i === all.length - 1);
      const { lines, full } = outline(filter, maxChars - head.join("\n").length);
      if (full) lines.push(`… (truncated at ${maxChars} characters; raise maxChars, or use find, scroll with text, or filter "interactive")`);
      if (!lines.length) lines.push(filter === "interactive" ? "(no interactive elements)" : "(the page shows no text)");
      return [...head, ...lines].join("\n");
    },
    /** Elements whose role, name or text contains `query`. */
    find(query, limit = 20) {
      const needle = String(query).toLowerCase();
      const hits = [];
      const seen = new Set();
      for (const el of document.querySelectorAll(INTERACTIVE)) {
        if (hits.length >= limit) break;
        if (!shown(el)) continue;
        if (`${roleOf(el)} ${nameOf(el)} ${el.value || ""}`.toLowerCase().includes(needle)) {
          seen.add(el);
          hits.push(describe(el));
        }
      }
      for (const { parent } of textMatches(needle, limit * 3)) {
        if (hits.length >= limit) break;
        const target = parent.closest(INTERACTIVE) || parent;
        if (seen.has(target)) continue;
        seen.add(target);
        hits.push(target.matches(INTERACTIVE) ? describe(target) : `text "${clean(target.innerText, 160)}" [${refOf(target)}]`);
      }
      return hits.length ? hits.join("\n") : `Nothing on the page matches "${query}".`;
    },
    /**
     * Scroll `ref` into view; its centre in viewport CSS pixels, and whether a
     * click there reaches it (or what covers it).
     */
    point(ref) {
      const el = byRef(ref);
      el.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
      const rects = [...el.getClientRects()].filter((r) => r.width > 0 && r.height > 0);
      const rect = rects[0] || el.getBoundingClientRect();
      const x = rect.left + rect.width / 2;
      const y = rect.top + rect.height / 2;
      const top = document.elementFromPoint(x, y);
      const label = top?.closest("label");
      const hits = !!top && (top === el || el.contains(top) || top.contains(el) && top.tagName === "LABEL" || (label && label.control === el));
      return { x, y, width: rect.width, height: rect.height, hits, covered: hits || !top ? null : describe(top) };
    },
    /** What `ref` looks like now (after a click), or that it is gone. */
    state(ref) {
      const el = refs.get(String(ref))?.deref();
      if (!el || !el.isConnected) return null;
      return describe(el);
    },
    /** For script fallbacks: did the element take the action? */
    took(ref, action) {
      const el = byRef(ref);
      if (action === "check") return el.checked === true;
      if (action === "focus") return document.activeElement === el || el.contains(document.activeElement);
      return true;
    },
    /** Whether a click is expected to check or focus `ref`. */
    clickEffect(ref) {
      const el = byRef(ref);
      if (el.disabled) return "none";
      if (el.tagName === "INPUT" && el.type === "radio") return "check";
      if (el.tagName === "INPUT" && ["text", "search", "email", "url", "tel", "password", "number", "date", "time", "datetime-local", "month", "week"].includes(el.type)) return "focus";
      if (el.tagName === "TEXTAREA" || el.isContentEditable) return "focus";
      return "none";
    },
    focus(ref) {
      const el = byRef(ref);
      el.scrollIntoView({ block: "center", behavior: "instant" });
      el.focus();
      if (document.activeElement !== el && !el.contains(document.activeElement)) throw new Error(`${ref} (${describe(el)}) cannot take focus`);
      // Type at the end of what is there.
      if (typeof el.setSelectionRange === "function" && /^(text|search|url|tel|password|email)?$/.test(el.type || "") || el.tagName === "TEXTAREA") {
        try {
          el.setSelectionRange(el.value.length, el.value.length);
        } catch {}
      }
      return true;
    },
    /** Click without real input (platforms without the DevTools protocol, or a fallback). */
    click(ref) {
      const el = byRef(ref);
      el.scrollIntoView({ block: "center", behavior: "instant" });
      el.focus?.();
      el.click();
      return true;
    },
    /** The element typing goes to: its ref, description, and whether keys can fill it. */
    typingTarget(ref) {
      const el = ref ? byRef(ref) : document.activeElement;
      if (!el || el === document.body || el === document.documentElement) return null;
      const type = el.tagName === "INPUT" ? (el.type || "text").toLowerCase() : "";
      const kind =
        ["date", "time", "datetime-local", "month", "week", "color", "range"].includes(type) || el.tagName === "SELECT"
          ? "set"
          : ["text", "search", "email", "url", "tel", "password", "number"].includes(type) || el.tagName === "TEXTAREA" || el.isContentEditable
            ? "keys"
            : "other";
      return { ref: refOf(el), kind, value: el.isContentEditable ? el.textContent : "value" in el ? String(el.value ?? "") : "" };
    },
    /** Insert text at the caret the way an editor does (fallback when real input is lost). */
    insert(ref, value) {
      const el = byRef(ref);
      el.focus();
      if (!document.execCommand("insertText", false, value)) {
        if (el.isContentEditable) el.textContent += value;
        else {
          const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto, "value").set.call(el, `${el.value}${value}`);
          el.dispatchEvent(new Event("input", { bubbles: true }));
        }
      }
      return true;
    },
    /** Set a field's value the way typing would (input + change events). */
    setValue(ref, value) {
      const el = byRef(ref);
      el.scrollIntoView({ block: "center", behavior: "instant" });
      el.focus();
      if (el.tagName === "SELECT") {
        const option = [...el.options].find((o) => o.value === value || clean(o.text) === value);
        if (!option) throw new Error(`No option "${value}"; options: ${[...el.options].map((o) => clean(o.text)).join(", ")}`);
        el.value = option.value;
      } else if (el.type === "checkbox" || el.type === "radio") {
        el.checked = value === true || value === "true" || value === "on";
      } else if (el.isContentEditable) {
        el.textContent = value;
      } else {
        const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
        if (value && el.value === "" && el.tagName === "INPUT") throw new Error(`"${value}" is not a valid value for ${describe(el)}`);
      }
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return describe(el);
    },
    /** Scroll an element or the first text matching `query` to the middle of the view. */
    scrollTo({ ref, query }) {
      let target;
      let label;
      if (ref) {
        target = byRef(ref);
        label = describe(target);
      } else {
        const [hit] = textMatches(String(query).toLowerCase(), 1);
        if (!hit) throw new Error(`No text on the page matches "${query}"`);
        target = hit.parent;
        label = `text "${clean(target.innerText, 160)}" [${refOf(target)}]`;
      }
      target.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
      return label;
    },
    text(maxChars = 30000) {
      return (document.body?.innerText || "").slice(0, maxChars);
    },
    logSeq() {
      return logSeq;
    },
    console(limit = 100, onlyErrors = false, after = 0) {
      return logs.filter((l) => l.seq > after && (!onlyErrors || l.level === "error")).slice(-limit);
    },
    network(limit = 100) {
      return performance
        .getEntriesByType("navigation")
        .concat(performance.getEntriesByType("resource"))
        .slice(-limit)
        .map((e) => ({
          url: e.name,
          type: e.initiatorType || e.entryType,
          status: e.responseStatus || undefined,
          ms: Math.round(e.duration),
          bytes: e.transferSize || undefined,
        }));
    },
  };
})();
