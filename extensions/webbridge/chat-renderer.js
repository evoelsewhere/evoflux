/* Typed, chronological chat blocks for the EvoFlux WebBridge Side Panel. */

(() => {
  const DESKTOP_REASONING_NOTE = "Reasoning remains in EvoFlux Desktop.";
  const DESKTOP_TOOL_OUTPUT_NOTE = "Full output available in EvoFlux Desktop";
  const BLOCKED_WIDGET_ELEMENTS = "script,iframe,object,embed,meta,base,link,form";
  const WIDGET_URL_ATTRIBUTES = new Set([
    "action", "archive", "background", "cite", "code", "codebase", "data", "download",
    "formaction", "href", "longdesc", "lowsrc", "manifest", "ping", "poster", "profile",
    "src", "srcdoc", "srcset", "target", "usemap", "xlink:href",
  ]);
  const text = (value) => typeof value === "string" ? value : value == null ? "" : String(value);

  function charDelta(value) {
    const count = Number(value);
    return Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0;
  }

  function prettyJson(value) {
    const raw = text(value).trim();
    if (!raw) return "";
    try { return JSON.stringify(JSON.parse(raw), null, 2); }
    catch { return raw; }
  }

  function blockKey(data) {
    return text(data?.tool_call_id || data?.id || `${data?.agent || "EvoFlux"}:${data?.name || "tool"}`);
  }

  function makeDisclosure(className, summaryText, open = false) {
    const details = document.createElement("details");
    details.className = className;
    details.open = open;
    const summary = document.createElement("summary");
    summary.textContent = summaryText;
    const body = document.createElement("div");
    body.className = `${className}-body`;
    details.append(summary, body);
    return { details, summary, body };
  }

  function safeWidgetImageSource(value) {
    return /^data:image\/(?:avif|bmp|gif|jpe?g|png|webp);base64,[a-z\d+/=\s]+$/i.test(text(value).trim());
  }

  function sanitizeWidgetHtml(html) {
    const raw = text(html);
    if (typeof globalThis.DOMParser !== "function") return "";
    try {
      const parsed = new globalThis.DOMParser().parseFromString(raw, "text/html");
      const root = parsed?.body;
      if (!root || typeof root.querySelectorAll !== "function") return "";
      for (const element of root.querySelectorAll(BLOCKED_WIDGET_ELEMENTS)) element.remove();
      for (const element of root.querySelectorAll("*")) {
        for (const attribute of [...element.attributes]) {
          const name = text(attribute.name).toLowerCase();
          if (name.startsWith("on")) {
            element.removeAttribute(attribute.name);
            continue;
          }
          if (!WIDGET_URL_ATTRIBUTES.has(name)) continue;
          const isSafeImage = name === "src"
            && text(element.tagName).toLowerCase() === "img"
            && safeWidgetImageSource(attribute.value);
          if (!isSafeImage) element.removeAttribute(attribute.name);
        }
      }
      return text(root.innerHTML);
    } catch {
      // DOMParser is defense-in-depth on top of the unique-origin sandbox and
      // CSP. If it exists but cannot parse, fail closed instead of forwarding.
      return "";
    }
  }

  function widgetDocument(html) {
    // Widgets are useful output, but they are not trusted extension code.  A
    // unique-origin iframe plus this CSP keeps scripts, navigation, forms and
    // network requests out while still allowing a static visual to render.
    return [
      "<!doctype html><html><head>",
      "<meta charset=\"utf-8\">",
      "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; img-src data: blob:; style-src 'unsafe-inline'; font-src data:; form-action 'none'; base-uri 'none'; navigate-to 'none'\">",
      "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
      "<style>html{color-scheme:light dark}body{margin:0;padding:12px;overflow:auto;font:13px/1.45 system-ui,sans-serif;color:CanvasText;background:Canvas}*{box-sizing:border-box;max-width:100%}pre{overflow:auto;white-space:pre-wrap}table{border-collapse:collapse}td,th{border:1px solid GrayText;padding:4px 6px}</style>",
      "</head><body>",
      sanitizeWidgetHtml(html),
      "</body></html>",
    ].join("");
  }

  class TypedBlockRenderer {
    constructor(options) {
      this.options = options;
      this.turn = null;
      this.tools = new Map();
      this.widgets = new Map();
      this.widgetFrames = new Map();
    }

    hasTurn() { return Boolean(this.turn); }

    currentItem() { return this.turn?.item || null; }

    begin(agent = "EvoFlux") {
      const name = text(agent) || "EvoFlux";
      if (this.turn?.agent === name) return this.turn;
      if (this.turn) this.finish();
      const created = this.options.createTurn(name);
      created.content.replaceChildren();
      created.content.classList.add("typed-blocks");
      this.turn = { ...created, agent: name, blocks: [] };
      return this.turn;
    }

    _append(type, agent, element, fields = {}) {
      if (type !== "text") this.options.flushText?.();
      const turn = this.begin(agent);
      const block = { type, element, agent: text(agent) || "EvoFlux", ...fields };
      turn.blocks.push(block);
      turn.content.append(element);
      this.options.scroll?.();
      return block;
    }

    appendText(data) {
      const agent = text(data?.agent) || "EvoFlux";
      const turn = this.begin(agent);
      let block = turn.blocks.at(-1);
      if (!block || block.type !== "text") {
        const body = document.createElement("div");
        body.className = "message-body typed-text-block";
        block = this._append("text", agent, body, {
          content: body,
          rawContent: "",
          displayedContent: "",
        });
      }
      block.rawContent += text(data?.text);
      this.options.textChanged?.(block);
      return block;
    }

    appendThinking(data) {
      const agent = text(data?.agent) || "EvoFlux";
      const turn = this.begin(agent);
      let block = turn.blocks.at(-1);
      if (!block || block.type !== "thinking") {
        const ui = makeDisclosure("thinking-block", "Thinking", false);
        block = this._append("thinking", agent, ui.details, {
          body: ui.body,
          summary: ui.summary,
          rawContent: "",
          chars: 0,
          redactedChars: 0,
          desktopOnly: false,
        });
      }
      const chunk = text(data?.text);
      const desktopOnly = !chunk && Object.prototype.hasOwnProperty.call(data || {}, "chars");
      const redactedChars = desktopOnly ? charDelta(data?.chars) : 0;
      block.rawContent += chunk;
      block.chars += chunk.length + redactedChars;
      block.redactedChars += redactedChars;
      block.desktopOnly ||= desktopOnly;
      block.summary.textContent = block.chars
        ? `Thinking · ${block.chars.toLocaleString()} chars`
        : "Thinking";
      if (block.rawContent) {
        this.options.renderMarkdown?.(block.body, block.rawContent);
        this.options.hydrate?.(block.body);
      } else if (block.desktopOnly) {
        block.body.textContent = DESKTOP_REASONING_NOTE;
        block.body.dataset.desktopOnly = "reasoning";
      } else {
        this.options.renderMarkdown?.(block.body, block.rawContent);
        this.options.hydrate?.(block.body);
      }
      this.options.scroll?.();
      return block;
    }

    _ensureTool(data) {
      const key = blockKey(data);
      const existing = this.tools.get(key);
      if (existing) return existing;
      const agent = text(data?.agent) || "EvoFlux";
      const ui = makeDisclosure("tool-block", text(data?.name) || "Tool", true);
      const status = document.createElement("span");
      status.className = "tool-block-status";
      status.textContent = "Pending";
      ui.summary.append(status);

      const argumentsSection = document.createElement("section");
      argumentsSection.className = "tool-section tool-arguments";
      const argumentsLabel = document.createElement("strong");
      argumentsLabel.textContent = "Arguments";
      const argumentsCode = document.createElement("pre");
      const argumentsBody = document.createElement("code");
      argumentsCode.append(argumentsBody);
      argumentsSection.append(argumentsLabel, argumentsCode);
      argumentsSection.hidden = true;

      const outputSection = document.createElement("section");
      outputSection.className = "tool-section tool-live-output";
      const outputLabel = document.createElement("strong");
      outputLabel.textContent = "Live output";
      const outputCode = document.createElement("pre");
      const outputBody = document.createElement("code");
      outputCode.append(outputBody);
      outputSection.append(outputLabel, outputCode);
      outputSection.hidden = true;

      const resultSection = document.createElement("section");
      resultSection.className = "tool-section tool-result";
      const resultLabel = document.createElement("strong");
      resultLabel.textContent = "Result";
      const resultCode = document.createElement("pre");
      const resultBody = document.createElement("code");
      resultCode.append(resultBody);
      resultSection.append(resultLabel, resultCode);
      resultSection.hidden = true;
      ui.body.append(argumentsSection, outputSection, resultSection);

      const block = this._append("tool", agent, ui.details, {
        key,
        name: text(data?.name) || "tool",
        summary: ui.summary,
        status,
        argumentsSection,
        argumentsBody,
        outputSection,
        outputBody,
        resultSection,
        resultBody,
        output: "",
        outputChars: 0,
        redactedOutputChars: 0,
        desktopOnlyOutput: false,
      });
      this.tools.set(key, block);
      return block;
    }

    toolCall(data) {
      const block = this._ensureTool(data);
      block.status.textContent = "Pending";
      return block;
    }

    toolStart(data) {
      const block = this._ensureTool(data);
      block.status.textContent = "Running";
      const args = prettyJson(data?.arguments);
      block.argumentsSection.hidden = !args;
      block.argumentsBody.textContent = args;
      return block;
    }

    toolOutput(data) {
      const block = this._ensureTool(data);
      const chunk = text(data?.text);
      const desktopOnly = !chunk && data?.redacted === true;
      const redactedChars = desktopOnly ? charDelta(data?.chars) : 0;
      block.output += chunk;
      block.outputChars += chunk.length + redactedChars;
      block.redactedOutputChars += redactedChars;
      block.desktopOnlyOutput ||= desktopOnly;
      const streamStatus = data?.stream === "stderr" ? "Running · stderr" : "Running";
      block.status.textContent = block.desktopOnlyOutput
        ? `${streamStatus} · ${block.redactedOutputChars.toLocaleString()} chars`
        : streamStatus;
      block.outputSection.hidden = false;
      const desktopProgress = `${block.redactedOutputChars.toLocaleString()} chars received\n${DESKTOP_TOOL_OUTPUT_NOTE}`;
      block.outputBody.textContent = block.desktopOnlyOutput
        ? `${block.output}${block.output ? "\n\n" : ""}${desktopProgress}`
        : block.output;
      if (desktopOnly) block.outputSection.dataset.desktopOnly = "tool-output";
      block.outputSection.dataset.stream = text(data?.stream || "combined");
      this.options.scroll?.();
      return block;
    }

    toolEnd(data) {
      const block = this._ensureTool(data);
      const duration = Number(data?.duration_ms ?? data?.metadata?.duration_ms);
      block.status.textContent = Number.isFinite(duration)
        ? `Done · ${(Math.max(0, duration) / 1000).toFixed(1)}s`
        : "Done";
      const result = text(data?.result);
      block.resultSection.hidden = !result;
      block.resultBody.textContent = result;
      block.element.classList.add("done");
      return block;
    }

    appendWidget(data) {
      const key = blockKey(data);
      let block = this.widgets.get(key);
      if (!block) {
        const agent = text(data?.agent) || "EvoFlux";
        const section = document.createElement("section");
        section.className = "widget-block";
        const heading = document.createElement("div");
        heading.className = "widget-heading";
        heading.textContent = text(data?.metadata?.title || data?.title || "Widget");
        const iframe = document.createElement("iframe");
        iframe.className = "widget-frame";
        iframe.title = heading.textContent;
        iframe.setAttribute("sandbox", "");
        iframe.referrerPolicy = "no-referrer";
        section.append(heading, iframe);
        block = this._append("widget", agent, section, { key, iframe, heading, html: "" });
        this.widgets.set(key, block);
      }
      block.html += text(data?.html);
      block.element.classList.toggle("streaming", !data?.is_final);
      this._scheduleWidget(block);
      return block;
    }

    appendEvent(type, data = {}) {
      const agent = text(data.agent) || this.turn?.agent || "EvoFlux";
      const labels = {
        usage: "Token usage",
        inbox: "Inbox message",
        handoff: "Agent handoff",
        delegation: "Delegation",
        workflow_progress: "Workflow progress",
        goal_status: "Goal status",
        desktop_notification: "Notification",
        rate_limit: "Rate limit",
        summarization_start: "Compaction started",
        summarization_content: "Compaction progress",
        summarization_end: "Compaction completed",
        summarization_started: "Compaction started",
        summarization_progress: "Compaction progress",
        summarization_completed: "Compaction completed",
        browser_session: "Browser session",
        turn_changes: "Turn changes",
        provider_status: "Provider status",
        permission_asked: "Permission request",
        plan_approval_requested: "Plan review",
        error: "Error",
      };
      const label = labels[type] || text(type).replace(/_/g, " ");
      const ui = makeDisclosure(`event-block event-${text(type)}`, label, false);
      const payload = { ...data };
      delete payload.type;
      delete payload.agent;
      const preferred = payload.message || payload.content || payload.status;
      if (typeof preferred === "string" && Object.keys(payload).length <= 2) {
        ui.body.textContent = preferred;
      } else {
        try { ui.body.textContent = JSON.stringify(payload, null, 2); }
        catch { ui.body.textContent = text(preferred || label); }
      }
      return this._append("event", agent, ui.details, { eventType: type, body: ui.body });
    }

    _scheduleWidget(block) {
      if (this.widgetFrames.has(block.key)) return;
      const schedule = globalThis.requestAnimationFrame || ((callback) => setTimeout(callback, 16));
      const id = schedule(() => {
        this.widgetFrames.delete(block.key);
        block.iframe.srcdoc = widgetDocument(block.html);
        this.options.scroll?.();
      });
      this.widgetFrames.set(block.key, id);
    }

    finish() {
      this.options.flushText?.();
      this.turn?.item.classList.remove("live", "live-turn");
      for (const block of this.tools.values()) {
        if (!block.element.classList.contains("done")) block.status.textContent = "Stopped";
      }
    }

    reset() {
      this.options.flushText?.();
      const cancel = globalThis.cancelAnimationFrame || clearTimeout;
      for (const frame of this.widgetFrames.values()) cancel(frame);
      this.widgetFrames.clear();
      this.turn = null;
      this.tools.clear();
      this.widgets.clear();
    }

    renderHistory(target, blocks) {
      if (!Array.isArray(blocks) || !blocks.length) return false;
      target.replaceChildren();
      target.classList.add("typed-blocks");
      const previousTurn = this.turn;
      const previousTools = this.tools;
      const previousWidgets = this.widgets;
      const historyAgent = text(blocks.find((entry) => entry?.agent)?.agent) || "EvoFlux";
      this.turn = { item: target.closest?.(".message") || target, content: target, agent: historyAgent, blocks: [] };
      this.tools = new Map();
      this.widgets = new Map();
      for (const entry of blocks) {
        const type = text(entry?.type);
        if (type === "text" || type === "message") {
          const body = document.createElement("div");
          body.className = "message-body typed-text-block";
          this.options.renderMarkdown?.(body, text(entry.content ?? entry.text));
          this.options.hydrate?.(body);
          this._append("text", historyAgent, body, { content: body });
        } else if (type === "thinking") {
          this.appendThinking({ ...entry, agent: historyAgent, text: entry.content ?? entry.text });
        } else if (type === "tool") {
          const payload = {
            ...entry,
            agent: historyAgent,
            name: entry.name ?? entry.tool_name ?? entry.toolName,
            tool_call_id: entry.tool_call_id ?? entry.toolCallId,
            arguments: entry.arguments ?? entry.tool_args ?? entry.toolArgs,
            result: entry.result ?? entry.tool_result ?? entry.toolResult,
          };
          this.toolStart(payload);
          if (entry.output ?? entry.tool_output ?? entry.toolOutput) {
            this.toolOutput({ ...payload, text: entry.output ?? entry.tool_output ?? entry.toolOutput });
          }
          this.toolEnd(payload);
        } else if (type === "widget") {
          this.appendWidget({
            ...entry,
            agent: historyAgent,
            html: entry.html ?? entry.widget_html ?? entry.widgetHtml,
            is_final: true,
          });
        }
      }
      this.turn = previousTurn;
      this.tools = previousTools;
      this.widgets = previousWidgets;
      return true;
    }
  }

  globalThis.WebBridgeTypedBlocks = {
    create: (options) => new TypedBlockRenderer(options),
    prettyJson,
    sanitizeWidgetHtml,
    widgetDocument,
  };
})();
