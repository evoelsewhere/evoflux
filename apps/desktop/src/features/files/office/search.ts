// Find in a preview document (port of v3 workspace-document-preview.tsx):
// matches are wrapped in `<mark data-evo-search>` inside the frame document.

export function clearSearchMarks(document: Document): void {
  document.querySelectorAll<HTMLElement>("mark[data-evo-search]").forEach((mark) => {
    mark.replaceWith(document.createTextNode(mark.textContent ?? ""));
  });
  document.body?.normalize();
}

/** Mark every case-insensitive occurrence of `query`; the marks in document order. */
export function markSearchMatches(document: Document, query: string): HTMLElement[] {
  clearSearchMarks(document);
  const needle = query.trim().toLocaleLowerCase();
  if (!needle || !document.body) return [];

  const showText = document.defaultView?.NodeFilter.SHOW_TEXT ?? NodeFilter.SHOW_TEXT;
  const walker = document.createTreeWalker(document.body, showText);
  const textNodes: Text[] = [];
  let node = walker.nextNode();
  while (node) {
    const parent = node.parentElement;
    if (parent && !["STYLE", "SCRIPT", "NOSCRIPT"].includes(parent.tagName)) textNodes.push(node as Text);
    node = walker.nextNode();
  }

  const matches: HTMLElement[] = [];
  textNodes.forEach((textNode) => {
    const source = textNode.data;
    const lower = source.toLocaleLowerCase();
    let cursor = 0;
    let matchIndex = lower.indexOf(needle);
    if (matchIndex < 0 || !textNode.parentNode) return;

    const fragment = document.createDocumentFragment();
    while (matchIndex >= 0) {
      if (matchIndex > cursor) fragment.append(document.createTextNode(source.slice(cursor, matchIndex)));
      const mark = document.createElement("mark");
      mark.dataset.evoSearch = "true";
      mark.textContent = source.slice(matchIndex, matchIndex + needle.length);
      mark.style.cssText = "background:#fde68a;color:inherit;padding:0;border-radius:2px;";
      fragment.append(mark);
      matches.push(mark);
      cursor = matchIndex + needle.length;
      matchIndex = lower.indexOf(needle, cursor);
    }
    if (cursor < source.length) fragment.append(document.createTextNode(source.slice(cursor)));
    textNode.parentNode.replaceChild(fragment, textNode);
  });
  return matches;
}

/** The cell next to `name` ("B3") in the direction of an arrow key, or `null` at the edge. */
export function adjacentCellName(name: string, key: string): string | null {
  const match = /^([A-Z]+)([1-9]\d*)$/.exec(name);
  if (!match) return null;
  let column = 0;
  for (const character of match[1]) column = column * 26 + character.charCodeAt(0) - 64;
  let row = Number(match[2]);
  if (key === "ArrowLeft") column -= 1;
  else if (key === "ArrowRight") column += 1;
  else if (key === "ArrowUp") row -= 1;
  else if (key === "ArrowDown") row += 1;
  else return null;
  if (column < 1 || row < 1) return null;
  let label = "";
  while (column > 0) {
    column -= 1;
    label = String.fromCharCode(65 + (column % 26)) + label;
    column = Math.floor(column / 26);
  }
  return `${label}${row}`;
}
