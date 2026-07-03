export interface SearchResult {
  title: string
  url: string
  snippet: string
  source: string
}

export async function searchWeb(
  query: string,
  options: { maxResults?: number; language?: string; region?: string } = {}
): Promise<SearchResult[]> {
  const { maxResults = 10, language = 'en', region } = options

  const results = await searchDuckDuckGo(query, { maxResults, language, region })

  return results.slice(0, maxResults)
}

async function searchDuckDuckGo(
  query: string,
  options: { maxResults: number; language: string; region?: string }
): Promise<SearchResult[]> {
  const params = new URLSearchParams({
    q: query,
    kl: options.region ? `${options.region}-${options.language}` : options.language,
  })

  const url = `https://html.duckduckgo.com/html/?${params.toString()}`

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 15000)

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': `${options.language},en;q=0.9`,
      },
      signal: controller.signal,
    })

    if (!response.ok) {
      throw new Error(`DuckDuckGo returned ${response.status}`)
    }

    const html = await response.text()
    return parseDuckDuckGoResults(html)
  } finally {
    clearTimeout(timeout)
  }
}

function parseDuckDuckGoResults(html: string): SearchResult[] {
  const results: SearchResult[] = []

  const resultBlocks = html.split(/class="result\s/)
  for (let i = 1; i < resultBlocks.length; i++) {
    const block = resultBlocks[i]

    const linkMatch = block.match(/class="result__a"[^>]*href="([^"]+)"/)
    if (!linkMatch) continue

    let url = linkMatch[1]
    if (url.includes('uddg=')) {
      const uddgMatch = url.match(/uddg=([^&]+)/)
      if (uddgMatch) url = decodeURIComponent(uddgMatch[1])
    }

    const titleMatch = block.match(/class="result__a"[^>]*>([\s\S]*?)<\/a>/)
    const title = titleMatch ? stripHTMLEntities(titleMatch[1]) : ''

    const snippetMatch = block.match(/class="result__snippet"[^>]*>([\s\S]*?)<\/(?:a|td|div)/)
    const snippet = snippetMatch ? stripHTMLEntities(snippetMatch[1]) : ''

    if (url && title) {
      results.push({
        title: title.trim(),
        url: url.trim(),
        snippet: snippet.trim(),
        source: 'duckduckgo'
      })
    }
  }

  if (results.length === 0) {
    return parseDuckDuckGoFallback(html)
  }

  return results
}

function parseDuckDuckGoFallback(html: string): SearchResult[] {
  const results: SearchResult[] = []

  const linkRegex = /<a[^>]+class="[^"]*result[^"]*"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi
  let match

  while ((match = linkRegex.exec(html)) !== null && results.length < 20) {
    let url = match[1]
    if (url.includes('uddg=')) {
      const uddgMatch = url.match(/uddg=([^&]+)/)
      if (uddgMatch) url = decodeURIComponent(uddgMatch[1])
    }

    const title = stripHTMLEntities(match[2])
    if (url.startsWith('http') && title.length > 3) {
      results.push({ title: title.trim(), url, snippet: '', source: 'duckduckgo' })
    }
  }

  return results
}

function stripHTMLEntities(text: string): string {
  return text
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(parseInt(code)))
    .replace(/\s+/g, ' ')
}
