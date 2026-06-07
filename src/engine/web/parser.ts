const NOISE_SELECTORS = [
  'script', 'style', 'noscript', 'iframe', 'object', 'embed',
  'svg', 'canvas', 'video', 'audio', 'map', 'form',
  'nav', 'footer', 'header', 'aside'
]

export interface ParsedContent {
  title: string
  description: string
  text: string
  mainContent: string
}

export function parseHTML(html: string): ParsedContent {
  const title = extractTitle(html)
  const description = extractMetaDescription(html)

  let text = html
  for (const tag of NOISE_SELECTORS) {
    text = removeTag(text, tag)
  }

  text = removeTags(text, 'script')
  text = removeTags(text, 'style')
  text = removeTags(text, 'noscript')

  text = text.replace(/<!--[\s\S]*?-->/g, '')
  text = text.replace(/<br\s*\/?>/gi, '\n')
  text = text.replace(/<\/?(p|div|h[1-6]|li|blockquote|pre|tr|article|section)[^>]*>/gi, '\n')
  text = text.replace(/<[^>]+>/g, ' ')
  text = decodeEntities(text)
  text = text.replace(/[ \t]+/g, ' ')
  text = text.replace(/\n\s*\n\s*\n/g, '\n\n')
  text = text.replace(/^\s+|\s+$/gm, '')

  const mainContent = extractMainContent(text)

  return {
    title,
    description,
    text: text.trim(),
    mainContent: mainContent.trim()
  }
}

function extractTitle(html: string): string {
  const ogMatch = html.match(/<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']/i)
  if (ogMatch) return decodeEntities(ogMatch[1])

  const titleMatch = html.match(/<title[^>]*>([^<]+)<\/title>/i)
  if (titleMatch) return decodeEntities(titleMatch[1])

  const h1Match = html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i)
  if (h1Match) return decodeEntities(stripTags(h1Match[1]))

  return ''
}

function extractMetaDescription(html: string): string {
  const ogMatch = html.match(/<meta[^>]+property=["']og:description["'][^>]+content=["']([^"']+)["']/i)
  if (ogMatch) return decodeEntities(ogMatch[1])

  const metaMatch = html.match(/<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)["']/i)
  if (metaMatch) return decodeEntities(metaMatch[1])

  return ''
}

function extractMainContent(text: string): string {
  const paragraphs = text.split(/\n\s*\n/).filter(p => {
    const trimmed = p.trim()
    return trimmed.length > 40 && !/^[\s\d.]+$/.test(trimmed)
  })

  if (paragraphs.length === 0) return text.substring(0, 2000)

  const scored = paragraphs.map((p, i) => ({
    text: p,
    score: scoreParagraph(p, i, paragraphs.length)
  }))

  scored.sort((a, b) => b.score - a.score)
  const top = scored.slice(0, Math.max(5, Math.ceil(scored.length * 0.3)))
  top.sort((a, b) => text.indexOf(a.text) - text.indexOf(b.text))

  return top.map(p => p.text).join('\n\n').substring(0, 5000)
}

function scoreParagraph(text: string, index: number, total: number): number {
  let score = 0
  const len = text.length
  if (len > 100) score += 2
  if (len > 200) score += 2
  if (len > 500) score += 1
  if (len < 30) score -= 3

  const pos = index / Math.max(1, total)
  if (pos > 0.1 && pos < 0.8) score += 2

  const linkDensity = (text.match(/https?:\/\//g) || []).length / Math.max(1, len / 50)
  if (linkDensity > 0.5) score -= 3

  const wordCount = text.split(/\s+/).length
  if (wordCount > 20) score += 1
  if (wordCount > 50) score += 1

  return score
}

function removeTag(html: string, tag: string): string {
  const regex = new RegExp(`<${tag}[^>]*>[\\s\\S]*?<\\/${tag}>`, 'gi')
  return html.replace(regex, '')
}

function removeTags(html: string, tag: string): string {
  return removeTag(html, tag)
}

function stripTags(html: string): string {
  return html.replace(/<[^>]+>/g, '')
}

function decodeEntities(text: string): string {
  return text
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#x27;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(parseInt(code)))
    .replace(/&#x([0-9a-f]+);/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
}
