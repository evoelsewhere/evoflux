import { describe, it, expect } from 'vitest'
import { parseMarkdownToText, parseMarkdownToStructured } from '../../../src/engine/file-reader/markdown-parser'

describe('MarkdownParser', () => {
  it('should strip markdown formatting', () => {
    const input = '# Hello\n\nThis is **bold** and *italic* text.\n\n- Item 1\n- Item 2'
    const result = parseMarkdownToText(input)
    expect(result).toContain('# Hello')
    expect(result).toContain('This is bold and italic text.')
    expect(result).toContain('- Item 1')
  })

  it('should strip links to plain text', () => {
    const result = parseMarkdownToText('Check [this link](https://example.com) out.')
    expect(result).toBe('Check this link out.')
  })

  it('should strip images to alt text', () => {
    const result = parseMarkdownToText('![alt text](image.png)')
    expect(result).toBe('alt text')
  })

  it('should preserve code block content', () => {
    const input = '```typescript\nconst x = 1\n```'
    const result = parseMarkdownToText(input)
    expect(result).toContain('const x = 1')
  })

  it('should strip inline code', () => {
    const result = parseMarkdownToText('Use `console.log()` for debugging.')
    expect(result).toBe('Use console.log() for debugging.')
  })

  it('should strip frontmatter', () => {
    const input = '---\ntitle: Hello\n---\n\nContent here'
    const result = parseMarkdownToText(input)
    expect(result).not.toContain('title')
    expect(result).toContain('Content here')
  })

  it('should extract structured data', () => {
    const input = `---
title: Test
---

# Heading 1

## Heading 2

Some text with [a link](https://example.com).

\`\`\`typescript
const x = 1
\`\`\`

| A | B |
|---|---|
| 1 | 2 |
`
    const result = parseMarkdownToStructured(input)
    expect(result.headings).toHaveLength(2)
    expect(result.headings[0]).toEqual({ level: 1, text: 'Heading 1' })
    expect(result.headings[1]).toEqual({ level: 2, text: 'Heading 2' })
    expect(result.codeBlocks).toHaveLength(1)
    expect(result.codeBlocks[0].lang).toBe('typescript')
    expect(result.links).toHaveLength(1)
    expect(result.links[0].url).toBe('https://example.com')
    expect(result.frontmatter).toEqual({ title: 'Test' })
  })
})
