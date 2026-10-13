/**
 * mermaid.render appends a temp container (`#d{id}`) to document.body and
 * only removes it on success — a failed render leaves it (and any partial
 * SVG) behind, which can poison later renders and leak DOM nodes. Sweep
 * both the temp container and the element mermaid rendered into.
 */
export function cleanupMermaidTempNodes(id: string): void {
  if (typeof document === 'undefined') return
  for (const tempId of [`d${id}`, id]) {
    document.getElementById(tempId)?.remove()
  }
}
