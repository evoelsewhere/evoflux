(() => {
  const snapshots = new Map();
  const MAX_SNAPSHOTS = 20;
  const ADAPTER_REVISION = "1";

  const bounded = (value, max) => String(value || "").replace(/\s+/g, " ").trim().slice(0, max);
  const randomId = (prefix) => `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  const axValue = (value) => value && typeof value === "object" && "value" in value ? value.value : value;

  function safePageUrl(url) {
    try {
      const parsed = new URL(url || "");
      return ["http:", "https:"].includes(parsed.protocol) ? `${parsed.origin}${parsed.pathname}` : "";
    } catch {
      return "";
    }
  }

  function originOf(url) {
    try {
      const parsed = new URL(url || "");
      return ["http:", "https:"].includes(parsed.protocol) ? parsed.origin : "";
    } catch {
      return "";
    }
  }

  function axProperties(node) {
    const properties = {};
    for (const property of node.properties || []) properties[property.name] = axValue(property.value);
    return properties;
  }

  function semanticKind(role) {
    const normalized = String(role || "").toLowerCase();
    if (["grid", "table", "row", "gridcell", "cell", "columnheader", "rowheader"].includes(normalized)) return "grid";
    if (["document", "paragraph", "heading", "statictext", "inlinetextbox", "textbox"].includes(normalized)) return "text";
    if (["list", "listitem", "tree", "treeitem"].includes(normalized)) return "slide";
    return "control";
  }

  function adapterFrom(tab, nodes) {
    const url = String(tab?.url || tab?.pendingUrl || "");
    const haystack = nodes.map((node) => `${bounded(axValue(node.role), 80)} ${bounded(axValue(node.name), 200)}`).join("\n").toLowerCase();
    if (/docs\.google\.com\/document\//i.test(url) && /(document content|editable|textbox|document)/i.test(haystack)) return "google_docs";
    if (/docs\.google\.com\/spreadsheets\//i.test(url) && /(grid|cell|formula bar|name box|sheet)/i.test(haystack)) return "google_sheets";
    if (/(excel|officeapps|microsoft365|sharepoint|onedrive)/i.test(url) && /(excel|formula bar|name box|gridcell)/i.test(haystack)) return "microsoft_excel";
    if (/(powerpoint|officeapps|microsoft365|sharepoint|onedrive)/i.test(url) && /(powerpoint|slide|notes|thumbnail)/i.test(haystack)) return "microsoft_powerpoint";
    return "generic";
  }

  function knownAppHint(tab) {
    const url = String(tab?.url || tab?.pendingUrl || "");
    if (/docs\.google\.com\/document\//i.test(url)) return "Google Docs semantic surface was not exposed. Enable screen reader support and focus the editor.";
    if (/docs\.google\.com\/spreadsheets\//i.test(url)) return "Google Sheets semantic grid was not exposed. Focus the sheet and enable accessibility support.";
    if (/(excel|officeapps|microsoft365|sharepoint|onedrive)/i.test(url)) return "Microsoft 365 semantic surface was not positively identified. Focus the document editor and retry.";
    return "";
  }

  async function frameEntries(tabId) {
    try {
      const tree = await cdpSend(tabId, "Page.getFrameTree");
      const entries = [];
      const visit = (entry) => {
        if (entry?.frame?.id) {
          entries.push({ id: entry.frame.id, url: entry.frame.url || "" });
        }
        for (const child of entry?.childFrames || []) visit(child);
      };
      visit(tree.frameTree);
      return entries;
    } catch {
      return [];
    }
  }

  async function readAxTrees(tabId, topUrl = "") {
    await cdpSend(tabId, "Accessibility.enable");
    const frames = await frameEntries(tabId);
    const nodes = [];
    const warnings = [];
    if (!frames.length) {
      const tree = await cdpSend(tabId, "Accessibility.getFullAXTree", {});
      return { nodes: tree.nodes || [], warnings };
    }
    const topOrigin = originOf(topUrl);
    for (const frame of frames) {
      const frameOrigin = originOf(frame.url);
      if (topOrigin && frameOrigin && frameOrigin !== topOrigin) {
        warnings.push(`Cross-origin frame ${frameOrigin} was skipped by sharing policy.`);
        continue;
      }
      try {
        const tree = await cdpSend(tabId, "Accessibility.getFullAXTree", { frameId: frame.id });
        for (const node of tree.nodes || []) nodes.push({ ...node, frameId: node.frameId || frame.id });
      } catch {
        warnings.push(`Accessibility tree unavailable for frame ${frame.id}.`);
      }
    }
    return { nodes, warnings };
  }

  function trimSnapshots() {
    while (snapshots.size > MAX_SNAPSHOTS) snapshots.delete(snapshots.keys().next().value);
  }

  async function snapshot(params = {}) {
    const tab = await resolveTab(params);
    const pageUrl = safePageUrl(tab.url || tab.pendingUrl || "");
    const maxItems = Math.max(1, Math.min(200, Number(params.max_items) || 80));
    const maxChars = Math.max(100, Math.min(50000, Number(params.max_chars) || 20000));
    const includeValues = Boolean(params.include_values);
    const requestedKinds = new Set(Array.isArray(params.kinds) ? params.kinds : ["text", "grid", "slide", "control"]);
    const { nodes, warnings } = await readAxTrees(tab.id, tab.url || tab.pendingUrl || "");
    const adapterId = adapterFrom(tab, nodes);
    const hint = knownAppHint(tab);
    if (adapterId === "generic" && hint) warnings.push(hint);
    const snapshotId = randomId("snapshot");
    const refs = new Map();
    const items = [];
    let chars = 0;
    for (const node of nodes) {
      if (items.length >= maxItems || node.ignored) continue;
      const role = bounded(axValue(node.role), 80);
      const kind = semanticKind(role);
      if (!requestedKinds.has(kind)) continue;
      const name = bounded(axValue(node.name), 500);
      const value = includeValues ? bounded(axValue(node.value), 500) : "";
      const properties = axProperties(node);
      if (!name && !value && !node.backendDOMNodeId) continue;
      const targetId = randomId("target");
      const item = {
        target: { kind: "ref", snapshot_id: snapshotId, target_id: targetId },
        kind,
        role: role || "unknown",
        name,
        ...(includeValues && value ? { value } : {}),
        state: {
          focused: Boolean(properties.focused),
          editable: Boolean(properties.editable),
          selected: Boolean(properties.selected),
          disabled: Boolean(properties.disabled),
        },
      };
      const size = JSON.stringify(item).length;
      if (chars + size > maxChars) break;
      chars += size;
      refs.set(targetId, {
        backendDOMNodeId: node.backendDOMNodeId || null,
        frameId: node.frameId || null,
        role,
        name,
        value,
      });
      items.push(item);
    }
    snapshots.set(snapshotId, {
      tabId: tab.id,
      pageUrl,
      adapterId,
      refs,
      createdAt: Date.now(),
    });
    trimSnapshots();
    return {
      status: "ok",
      adapter: { id: adapterId, revision: ADAPTER_REVISION },
      snapshot_id: snapshotId,
      page_generation: `${tab.id}:${pageUrl}:${snapshotId}`,
      capabilities: {
        active_text: true,
        document_read: true,
        range: ["google_sheets", "microsoft_excel"].includes(adapterId),
        slides: adapterId === "microsoft_powerpoint",
      },
      items,
      warnings,
      persistence: "not_checked",
    };
  }

  async function resolveSnapshotRef(tab, target) {
    const state = snapshots.get(target?.snapshot_id);
    if (!state || state.tabId !== tab.id) throw new Error("stale_target: take a new semantic snapshot.");
    if (safePageUrl(tab.url || tab.pendingUrl || "") !== state.pageUrl) {
      snapshots.delete(target.snapshot_id);
      throw new Error("stale_target: the page navigated; take a new semantic snapshot.");
    }
    const ref = state.refs.get(target?.target_id);
    if (!ref) throw new Error("stale_target: semantic target is unavailable.");
    return { state, ref };
  }

  async function resolveObject(tabId, ref) {
    if (!ref.backendDOMNodeId) return null;
    const resolved = await cdpSend(tabId, "DOM.resolveNode", {
      backendNodeId: ref.backendDOMNodeId,
      objectGroup: "webbridge-semantic",
    });
    return resolved.object?.objectId || null;
  }

  async function callObject(tabId, objectId, functionDeclaration, args = []) {
    const result = await cdpSend(tabId, "Runtime.callFunctionOn", {
      objectId,
      functionDeclaration,
      arguments: args.map((value) => ({ value })),
      returnByValue: true,
      awaitPromise: true,
      objectGroup: "webbridge-semantic",
    });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Semantic page operation failed.");
    return result.result?.value;
  }

  const READ_OBJECT = `function(maxChars) {
    const normalize = (value) => String(value || "").replace(/\\r\\n?/g, "\\n").trim();
    const type = String(this.type || "").toLowerCase();
    const autocomplete = String(this.autocomplete || "").toLowerCase();
    const secret = type === "password" || /(password|one-time-code|otp|pin|cc-number|token)/.test(autocomplete + " " + String(this.name || ""));
    if (secret) return { status: "unsupported", code: "secret_value_refused", message: "Secret field values are never read." };
    const text = this instanceof HTMLInputElement || this instanceof HTMLTextAreaElement || this instanceof HTMLSelectElement
      ? this.value
      : (this.innerText || this.textContent || "");
    return { status: "ok", text: normalize(text).slice(0, maxChars), editable: !this.readOnly && !this.disabled && (this.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(this.tagName)) };
  }`;

  async function readRef(tab, target, maxChars) {
    const { state, ref } = await resolveSnapshotRef(tab, target);
    const objectId = await resolveObject(tab.id, ref);
    if (!objectId) {
      return {
        status: "ok",
        adapter: { id: state.adapterId, revision: ADAPTER_REVISION },
        target,
        text: bounded(ref.value || ref.name, maxChars),
        warnings: ["DOM node unavailable; returning accessibility text."],
        persistence: "not_checked",
      };
    }
    const value = await callObject(tab.id, objectId, READ_OBJECT, [maxChars]);
    return {
      ...value,
      adapter: { id: state.adapterId, revision: ADAPTER_REVISION },
      target,
      persistence: "not_checked",
    };
  }

  async function activeText(tab, scope, maxChars) {
    const expression = `(() => {
      const maxChars = ${JSON.stringify(maxChars)};
      const scope = ${JSON.stringify(scope)};
      const normalize = (value) => String(value || "").replace(/\\r\\n?/g, "\\n").trim();
      const selection = normalize(window.getSelection()?.toString());
      if (scope === "selection" && selection) return { status: "ok", text: selection.slice(0, maxChars), source: "selection" };
      const element = document.activeElement;
      if (!element) return { status: "unsupported", code: "active_text_unavailable", message: "No active editor surface." };
      const type = String(element.type || "").toLowerCase();
      const secret = type === "password" || /(password|one-time-code|otp|pin|token)/i.test(String(element.autocomplete || "") + " " + String(element.name || ""));
      if (secret) return { status: "unsupported", code: "secret_value_refused", message: "Secret field values are never read." };
      const text = element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement
        ? element.value
        : (element.innerText || element.textContent || selection);
      return { status: text ? "ok" : "unsupported", code: text ? null : "active_text_unavailable", text: normalize(text).slice(0, maxChars), source: "active_element" };
    })()`;
    return evalInPage(tab.id, expression);
  }

  async function documentText(tab, maxChars) {
    const { nodes, warnings } = await readAxTrees(tab.id, tab.url || tab.pendingUrl || "");
    const adapterId = adapterFrom(tab, nodes);
    const text = [];
    for (const node of nodes) {
      if (node.ignored) continue;
      const role = String(axValue(node.role) || "").toLowerCase();
      if (!["statictext", "inlinetextbox", "heading", "paragraph", "textbox", "document"].includes(role)) continue;
      const value = bounded(axValue(node.value) || axValue(node.name), 2000);
      if (value && text[text.length - 1] !== value) text.push(value);
      if (text.join("\n").length >= maxChars) break;
    }
    if (!text.length && adapterId === "generic") {
      const fallback = await evalInPage(tab.id, `(() => String((document.body || document.documentElement).innerText || "").slice(0, ${JSON.stringify(maxChars)}))()`);
      if (fallback) text.push(fallback);
    }
    if (!text.length) return { status: "unsupported", code: "readback_unavailable", message: "The editor did not expose readable semantic text.", adapter: { id: adapterId, revision: ADAPTER_REVISION }, warnings };
    return { status: "ok", adapter: { id: adapterId, revision: ADAPTER_REVISION }, text: text.join("\n").slice(0, maxChars), warnings, persistence: "not_checked" };
  }

  async function rangeProbe(tab, target, action) {
    const adapterId = action.adapterId;
    if (!["google_sheets", "microsoft_excel"].includes(adapterId)) {
      return { status: "unsupported", code: "adapter_not_detected", message: "A supported spreadsheet editor was not positively identified.", adapter: { id: adapterId, revision: ADAPTER_REVISION } };
    }
    if (target.sheet) {
      return { status: "unsupported", code: "sheet_target_unverified", message: "Named-sheet targeting is unavailable until the editor exposes an exact active-sheet identity.", adapter: { id: adapterId, revision: ADAPTER_REVISION } };
    }
    const expression = `(() => {
      const adapter = ${JSON.stringify(adapterId)};
      const address = ${JSON.stringify(target.address)};
      const selectors = adapter === "google_sheets"
        ? ["[aria-label*=\\"Name box\\" i]", ".waffle-name-box"]
        : ["[aria-label*=\\"Name Box\\" i]", "input[aria-label*=\\"Name box\\" i]"];
      const box = selectors.map((selector) => document.querySelector(selector)).find(Boolean);
      if (!box || !(box instanceof HTMLInputElement)) return { status: "unsupported", code: "range_selector_unavailable", message: "Spreadsheet Name Box was not exposed." };
      box.focus();
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (setter) setter.call(box, address); else box.value = address;
      box.dispatchEvent(new Event("input", { bubbles: true }));
      box.dispatchEvent(new Event("change", { bubbles: true }));
      return { status: "ok", box_value: String(box.value || "") };
    })()`;
    const probe = await evalInPage(tab.id, expression);
    if (probe?.status !== "ok") return { ...probe, adapter: { id: adapterId, revision: ADAPTER_REVISION } };
    await cdpSend(tab.id, "Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    await cdpSend(tab.id, "Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    const verified = await evalInPage(tab.id, `(() => {
      const adapter = ${JSON.stringify(adapterId)};
      const selectors = adapter === "google_sheets"
        ? ["[aria-label*=\\"Name box\\" i]", ".waffle-name-box"]
        : ["[aria-label*=\\"Name Box\\" i]", "input[aria-label*=\\"Name box\\" i]"];
      const box = selectors.map((selector) => document.querySelector(selector)).find(Boolean);
      return box instanceof HTMLInputElement ? String(box.value || "").replace(/\\$/g, "").toUpperCase() : "";
    })()`);
    if (String(verified || "").toUpperCase() !== String(target.address || "").toUpperCase()) {
      return { status: "unsupported", code: "range_verification_failed", message: "The editor did not confirm the requested active range.", adapter: { id: adapterId, revision: ADAPTER_REVISION } };
    }
    return { status: "ok", adapter: { id: adapterId, revision: ADAPTER_REVISION }, target: { ...target, sheet: null } };
  }

  function exactSlideNode(nodes, target) {
    const byId = new Map(nodes.map((node) => [node.nodeId, node]));
    const slideRoots = nodes.filter((node) => {
      const name = bounded(axValue(node.name), 500);
      return new RegExp(`^slide\\s*${target.slide_index}(?:\\b|$)`, "i").test(name);
    });
    if (slideRoots.length !== 1) return null;
    const descendants = [];
    const queue = [...(slideRoots[0].childIds || [])];
    while (queue.length) {
      const node = byId.get(queue.shift());
      if (!node) continue;
      descendants.push(node);
      queue.push(...(node.childIds || []));
    }
    const rolePattern = target.role === "text"
      ? /\b(text|textbox|statictext)\b/i
      : new RegExp(`\\b${target.role}\\b`, "i");
    const matches = descendants.filter((node) => rolePattern.test(
      `${axValue(node.role) || ""} ${axValue(node.name) || ""}`
    ));
    return matches[target.ordinal || 0] || null;
  }

  async function adapterForTab(tab) {
    const { nodes, warnings } = await readAxTrees(tab.id, tab.url || tab.pendingUrl || "");
    return { adapterId: adapterFrom(tab, nodes), nodes, warnings };
  }

  async function read(params = {}) {
    const tab = await resolveTab(params);
    const target = params.target || {};
    const maxChars = Math.max(100, Math.min(50000, Number(params.max_chars) || 20000));
    if (target.kind === "ref") return readRef(tab, target, maxChars);
    if (target.kind === "active_text") {
      const value = await activeText(tab, target.scope || "selection", maxChars);
      const { adapterId } = await adapterForTab(tab);
      return { ...value, adapter: { id: adapterId, revision: ADAPTER_REVISION }, target, persistence: "not_checked" };
    }
    if (target.kind === "document") return documentText(tab, maxChars);
    if (target.kind === "range") {
      const action = await adapterForTab(tab);
      const selected = await rangeProbe(tab, target, action);
      if (selected.status !== "ok") return selected;
      const { nodes, warnings } = await readAxTrees(tab.id, tab.url || tab.pendingUrl || "");
      const cells = nodes.filter((node) => ["gridcell", "cell"].includes(String(axValue(node.role) || "").toLowerCase()) && (axProperties(node).selected || axProperties(node).focused)).slice(0, Math.max(1, Math.min(500, Number(params.max_cells) || 500))).map((node) => ({ name: bounded(axValue(node.name), 500), value: bounded(axValue(node.value), 500) }));
      if (!cells.length) return { status: "unsupported", code: "readback_unavailable", message: "The selected range was not exposed through accessibility read-back.", adapter: selected.adapter, target, warnings };
      return { status: "ok", adapter: selected.adapter, target, cells, warnings, persistence: "not_checked" };
    }
    if (["slide", "slide_object"].includes(target.kind)) {
      const action = await adapterForTab(tab);
      if (action.adapterId !== "microsoft_powerpoint") return { status: "unsupported", code: "adapter_not_detected", message: "PowerPoint Online was not positively identified.", adapter: { id: action.adapterId, revision: ADAPTER_REVISION } };
      const node = target.kind === "slide"
        ? action.nodes.find((candidate) => new RegExp(`^slide\\s*${target.index}(?:\\b|$)`, "i").test(bounded(axValue(candidate.name), 500)))
        : exactSlideNode(action.nodes, target);
      if (!node) return { status: "unsupported", code: "slide_target_unavailable", message: "The requested slide target was not exposed through accessibility." };
      const syntheticSnapshot = randomId("snapshot");
      const targetId = randomId("target");
      snapshots.set(syntheticSnapshot, { tabId: tab.id, pageUrl: safePageUrl(tab.url), adapterId: action.adapterId, refs: new Map([[targetId, { backendDOMNodeId: node.backendDOMNodeId || null, frameId: node.frameId || null, role: bounded(axValue(node.role), 80), name: bounded(axValue(node.name), 500), value: bounded(axValue(node.value), 500) }]]), createdAt: Date.now() });
      return readRef(tab, { kind: "ref", snapshot_id: syntheticSnapshot, target_id: targetId }, maxChars);
    }
    return { status: "unsupported", code: "operation_not_supported", message: `Unsupported semantic target: ${target.kind || "unknown"}.` };
  }

  async function select(params = {}) {
    const tab = await resolveTab(params);
    const target = params.target || {};
    if (target.kind === "ref") {
      const { state, ref } = await resolveSnapshotRef(tab, target);
      const objectId = await resolveObject(tab.id, ref);
      if (!objectId) return { status: "unsupported", code: "target_not_actionable", message: "Semantic target has no DOM action surface." };
      const result = await callObject(tab.id, objectId, `function() { this.scrollIntoView?.({ block: "center", inline: "center" }); this.focus?.(); this.click?.(); return { status: "ok" }; }`);
      return { ...result, adapter: { id: state.adapterId, revision: ADAPTER_REVISION }, target, persistence: "not_checked" };
    }
    if (target.kind === "range") return rangeProbe(tab, target, await adapterForTab(tab));
    if (["slide", "slide_object"].includes(target.kind)) {
      const readable = await read({ ...params, max_chars: 1000 });
      if (readable.status !== "ok" || !readable.target) return readable;
      return select({ ...params, target: readable.target });
    }
    if (target.kind === "active_text") return { status: "ok", target, persistence: "not_checked" };
    return { status: "unsupported", code: "operation_not_supported", message: "This semantic target cannot be selected." };
  }

  const PREPARE_WRITE = `function(change) {
    const type = String(this.type || "").toLowerCase();
    const autocomplete = String(this.autocomplete || "").toLowerCase();
    if (type === "password" || /(password|one-time-code|otp|pin|token)/.test(autocomplete + " " + String(this.name || ""))) return { status: "unsupported", code: "secret_value_refused", message: "Secret fields require direct user entry." };
    const input = this instanceof HTMLInputElement || this instanceof HTMLTextAreaElement;
    const editable = input || this.isContentEditable;
    if (!editable || this.readOnly || this.disabled) return { status: "unsupported", code: "view_only", message: "Target is not editable." };
    this.focus();
    if (input) {
      const length = String(this.value || "").length;
      if (change.mode === "replace") this.setSelectionRange(0, length);
      else if (change.at === "start") this.setSelectionRange(0, 0);
      else this.setSelectionRange(length, length);
    } else {
      const range = document.createRange();
      range.selectNodeContents(this);
      if (change.mode !== "replace") range.collapse(change.at === "start");
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
    return { status: "ok" };
  }`;

  async function objectForTarget(tab, target) {
    if (target.kind === "ref") {
      const resolved = await resolveSnapshotRef(tab, target);
      return { ...resolved, objectId: await resolveObject(tab.id, resolved.ref) };
    }
    if (target.kind === "active_text") {
      const result = await cdpSend(tab.id, "Runtime.evaluate", { expression: "document.activeElement", returnByValue: false, objectGroup: "webbridge-semantic" });
      return { state: { adapterId: (await adapterForTab(tab)).adapterId }, ref: null, objectId: result.result?.objectId || null };
    }
    return null;
  }

  function matrixText(rows) {
    return rows.map((row) => row.map((cell) => {
      if (cell.kind === "skip") throw new Error("skip cells are unsafe in matrix paste");
      if (cell.kind === "blank") return "";
      if (cell.kind === "formula") return String(cell.formula || "");
      return String(cell.value ?? "");
    }).join("\t")).join("\n");
  }

  async function writeTextToObject(tab, target, change, verify) {
    const resolved = await objectForTarget(tab, target);
    if (!resolved?.objectId) return { status: "unsupported", code: "target_not_actionable", message: "Semantic target has no editable DOM surface." };
    const prepared = await callObject(tab.id, resolved.objectId, PREPARE_WRITE, [change]);
    if (prepared?.status !== "ok") return { ...prepared, adapter: { id: resolved.state.adapterId, revision: ADAPTER_REVISION }, target };
    if (change.kind === "clear") {
      await cdpSend(tab.id, "Input.dispatchKeyEvent", { type: "keyDown", key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 });
      await cdpSend(tab.id, "Input.dispatchKeyEvent", { type: "keyUp", key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8 });
    } else {
      await cdpSend(tab.id, "Input.insertText", { text: String(change.text || "") });
    }
    const readback = await callObject(tab.id, resolved.objectId, READ_OBJECT, [50000]);
    const expected = change.kind === "clear" ? "" : String(change.text || "").replace(/\r\n?/g, "\n").trim();
    const actual = String(readback?.text || "").replace(/\r\n?/g, "\n").trim();
    const verified = verify === "none" || (change.mode === "insert" ? actual.includes(expected) : actual === expected);
    return {
      status: verified ? "ok" : "verification_failed",
      code: verified ? null : "verification_failed",
      mutation_may_have_occurred: !verified,
      adapter: { id: resolved.state.adapterId, revision: ADAPTER_REVISION },
      target,
      readback: actual,
      persistence: "not_checked",
    };
  }

  async function write(params = {}) {
    const tab = await resolveTab(params);
    const target = params.target || {};
    const change = params.change || {};
    const verify = params.verify || "normalized";
    if (change.kind === "matrix") {
      if (target.kind !== "range") return { status: "unsupported", code: "operation_not_supported", message: "Matrix writes require a spreadsheet range target." };
      const cells = (change.rows || []).reduce((count, row) => count + row.length, 0);
      if (!cells || cells > 100) return { status: "unsupported", code: "matrix_size_refused", message: "Matrix writes support 1 to 100 cells." };
      if ((change.rows || []).some((row) => row.some((cell) => cell.kind === "skip"))) return { status: "unsupported", code: "skip_cell_refused", message: "Skip cells require a read/merge operation and cannot be represented by safe TSV paste." };
      const selected = await rangeProbe(tab, target, await adapterForTab(tab));
      if (selected.status !== "ok") return selected;
      const text = matrixText(change.rows);
      await cdpSend(tab.id, "Input.insertText", { text });
      if (verify === "none") return { status: "ok", adapter: selected.adapter, target, written_cells: cells, persistence: "not_checked", warnings: ["Cloud persistence was not checked."] };
      const readback = await read({ ...params, target, max_cells: cells });
      if (readback.status !== "ok") return { status: "verification_failed", code: "readback_unavailable", mutation_may_have_occurred: true, adapter: selected.adapter, target, written_cells: cells, readback };
      const expected = change.rows.flat().filter((cell) => !["blank", "skip"].includes(cell.kind)).map((cell) => String(cell.kind === "formula" ? cell.formula || "" : cell.value ?? ""));
      const actual = JSON.stringify(readback.cells || []);
      const verified = expected.every((value) => actual.includes(value));
      return { status: verified ? "ok" : "verification_failed", code: verified ? null : "verification_failed", mutation_may_have_occurred: !verified, adapter: selected.adapter, target, written_cells: cells, readback, persistence: "not_checked" };
    }
    if (["ref", "active_text"].includes(target.kind) && ["text", "clear"].includes(change.kind)) {
      return writeTextToObject(tab, target, change, verify);
    }
    if (target.kind === "slide_object" && ["text", "clear"].includes(change.kind)) {
      const readable = await read({ ...params, target, max_chars: 1000 });
      if (readable.status !== "ok" || !readable.target) return readable;
      return writeTextToObject(tab, readable.target, change, verify);
    }
    return { status: "unsupported", code: "operation_not_supported", message: "This semantic write is not supported by the detected adapter." };
  }

  globalThis.WebBridgeSemantic = { snapshot, read, select, write };
})();
