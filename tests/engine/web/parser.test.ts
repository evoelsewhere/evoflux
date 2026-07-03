import { describe, it, expect } from 'vitest'
import { parseHTML } from '../../../src/engine/web/parser'

describe('HTML Parser', () => {
  it('should extract title from <title> tag', () => {
    const result = parseHTML('<html><head><title>Hello World</title></head><body><p>Content</p></body></html>')
    expect(result.title).toBe('Hello World')
  })

  it('should extract title from og:title meta', () => {
    const html = '<html><head><meta property="og:title" content="OG Title"></head><body></body></html>'
    expect(parseHTML(html).title).toBe('OG Title')
  })

  it('should extract meta description', () => {
    const html = '<html><head><meta name="description" content="A test page"></head><body></body></html>'
    expect(parseHTML(html).description).toBe('A test page')
  })

  it('should extract clean text from HTML', () => {
    const html = '<html><body><p>Hello <strong>world</strong></p><p>Second paragraph with enough text to be included in output.</p></body></html>'
    const result = parseHTML(html)
    expect(result.text).toContain('Hello world')
    expect(result.text).toContain('Second paragraph')
  })

  it('should remove script and style tags', () => {
    const html = '<html><body><script>var x = 1;</script><p>Visible content here with enough text to pass the filter threshold.</p><style>body { color: red; }</style></body></html>'
    const result = parseHTML(html)
    expect(result.text).not.toContain('var x')
    expect(result.text).not.toContain('color: red')
    expect(result.text).toContain('Visible content')
  })

  it('should decode HTML entities', () => {
    const html = '<html><body><p>Hello &amp; goodbye &lt;test&gt; &quot;quoted&quot;</p></body></html>'
    const result = parseHTML(html)
    expect(result.text).toContain('Hello & goodbye')
    expect(result.text).toContain('<test>')
    expect(result.text).toContain('"quoted"')
  })

  it('should handle empty HTML', () => {
    const result = parseHTML('')
    expect(result.title).toBe('')
    expect(result.text).toBe('')
  })
})
