(() => {
  const TOKEN_PREFIX = "\u0000WBMD";

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeHref(value) {
    try {
      const url = new URL(String(value || "").trim());
      return ["http:", "https:", "mailto:"].includes(url.protocol) ? url.href : "";
    } catch {
      return "";
    }
  }

  function renderInline(source) {
    const tokens = [];
    const hold = (html) => {
      const token = `${TOKEN_PREFIX}${tokens.length}\u0000`;
      tokens.push(html);
      return token;
    };

    let value = String(source || "");
    value = value.replace(/`([^`\n]+)`/g, (_match, code) => (
      hold(`<code>${escapeHtml(code)}</code>`)
    ));
    value = value.replace(/\[([^\]\n]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (_match, label, rawHref) => {
      const href = safeHref(rawHref);
      if (!href) return escapeHtml(label);
      return hold(
        `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`
      );
    });
    value = escapeHtml(value)
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_\n]+)__/g, "<strong>$1</strong>")
      .replace(/~~([^~\n]+)~~/g, "<del>$1</del>")
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/(^|[^\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");

    tokens.forEach((html, index) => {
      value = value.replace(`${TOKEN_PREFIX}${index}\u0000`, html);
    });
    return value;
  }

  function splitTableRow(line) {
    const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return trimmed.split("|").map((cell) => cell.trim());
  }

  function isTableDivider(line) {
    return /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  }

  function startsBlock(lines, index) {
    const line = lines[index] || "";
    const next = lines[index + 1] || "";
    return (
      /^\s*$/.test(line) ||
      /^\s{0,3}(`{3,}|~{3,})/.test(line) ||
      /^\s{0,3}#{1,6}\s+/.test(line) ||
      /^\s{0,3}>\s?/.test(line) ||
      /^\s*[-+*]\s+/.test(line) ||
      /^\s*\d+[.)]\s+/.test(line) ||
      /^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line) ||
      (line.includes("|") && isTableDivider(next))
    );
  }

  function renderMarkdown(source) {
    const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
    const output = [];
    let index = 0;

    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }

      const fence = line.match(/^\s{0,3}(`{3,}|~{3,})\s*([\w+-]*)\s*$/);
      if (fence) {
        const marker = fence[1][0];
        const minimum = fence[1].length;
        const language = fence[2];
        const body = [];
        index += 1;
        while (index < lines.length && !new RegExp(`^\\s{0,3}${marker}{${minimum},}\\s*$`).test(lines[index])) {
          body.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) index += 1;
        const languageClass = language ? ` class="language-${escapeHtml(language)}"` : "";
        output.push(`<pre><code${languageClass}>${escapeHtml(body.join("\n"))}</code></pre>`);
        continue;
      }

      const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
      if (heading) {
        const level = heading[1].length;
        output.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
        index += 1;
        continue;
      }

      if (/^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        output.push("<hr>");
        index += 1;
        continue;
      }

      if (/^\s{0,3}>\s?/.test(line)) {
        const quote = [];
        while (index < lines.length && /^\s{0,3}>\s?/.test(lines[index])) {
          quote.push(lines[index].replace(/^\s{0,3}>\s?/, ""));
          index += 1;
        }
        output.push(`<blockquote>${renderMarkdown(quote.join("\n"))}</blockquote>`);
        continue;
      }

      if (line.includes("|") && isTableDivider(lines[index + 1] || "")) {
        const headers = splitTableRow(line);
        const alignments = splitTableRow(lines[index + 1]).map((cell) => {
          const left = cell.startsWith(":");
          const right = cell.endsWith(":");
          return left && right ? "center" : right ? "right" : left ? "left" : "";
        });
        index += 2;
        const rows = [];
        while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
          rows.push(splitTableRow(lines[index]));
          index += 1;
        }
        const cells = (items, tag) => items.map((cell, cellIndex) => {
          const align = alignments[cellIndex] ? ` style="text-align:${alignments[cellIndex]}"` : "";
          return `<${tag}${align}>${renderInline(cell)}</${tag}>`;
        }).join("");
        output.push(
          `<div class="table-wrap"><table><thead><tr>${cells(headers, "th")}</tr></thead>` +
          `<tbody>${rows.map((row) => `<tr>${cells(row, "td")}</tr>`).join("")}</tbody></table></div>`
        );
        continue;
      }

      const unordered = line.match(/^\s*[-+*]\s+(.+)$/);
      const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
      if (unordered || ordered) {
        const tag = unordered ? "ul" : "ol";
        const items = [];
        const pattern = unordered ? /^\s*[-+*]\s+(.+)$/ : /^\s*\d+[.)]\s+(.+)$/;
        while (index < lines.length) {
          const item = lines[index].match(pattern);
          if (!item) break;
          const task = item[1].match(/^\[([ xX])\]\s+(.+)$/);
          items.push(task
            ? `<li class="task"><input type="checkbox" disabled${task[1].toLowerCase() === "x" ? " checked" : ""}>${renderInline(task[2])}</li>`
            : `<li>${renderInline(item[1])}</li>`
          );
          index += 1;
        }
        output.push(`<${tag}>${items.join("")}</${tag}>`);
        continue;
      }

      const paragraph = [line];
      index += 1;
      while (index < lines.length && !startsBlock(lines, index)) {
        paragraph.push(lines[index]);
        index += 1;
      }
      output.push(`<p>${paragraph.map(renderInline).join("<br>")}</p>`);
    }
    return output.join("");
  }

  function render(target, markdown) {
    target.innerHTML = renderMarkdown(markdown);
  }

  globalThis.WebBridgeMarkdown = { render, toSafeHtml: renderMarkdown };
})();