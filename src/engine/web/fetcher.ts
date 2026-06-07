import { parseHTML, type ParsedContent } from './parser'

export interface FetchedPage {
  url: string
  status: number
  contentType: string
  content: ParsedContent
  fetchedAt: number
}

export async function fetchPage(
  url: string,
  options: { timeoutMs?: number; maxLength?: number } = {}
): Promise<FetchedPage> {
  const { timeoutMs = 10000, maxLength = 50000 } = options

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en,vi;q=0.9',
      },
      signal: controller.signal,
      redirect: 'follow',
    })

    const contentType = response.headers.get('content-type') || ''

    if (!contentType.includes('text/html') && !contentType.includes('application/xhtml')) {
      return {
        url,
        status: response.status,
        contentType,
        content: { title: '', description: '', text: '', mainContent: '' },
        fetchedAt: Date.now()
      }
    }

    const html = await response.text()
    const content = parseHTML(html.substring(0, maxLength))

    return {
      url,
      status: response.status,
      contentType,
      content,
      fetchedAt: Date.now()
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Fetch failed'
    return {
      url,
      status: 0,
      contentType: '',
      content: { title: '', description: '', text: `Error: ${message}`, mainContent: '' },
      fetchedAt: Date.now()
    }
  } finally {
    clearTimeout(timeout)
  }
}

export async function fetchPages(
  urls: string[],
  options: { timeoutMs?: number; maxPages?: number; concurrency?: number } = {}
): Promise<FetchedPage[]> {
  const { maxPages = 5, concurrency = 3 } = options
  const toFetch = urls.slice(0, maxPages)

  const results: FetchedPage[] = []
  for (let i = 0; i < toFetch.length; i += concurrency) {
    const batch = toFetch.slice(i, i + concurrency)
    const batchResults = await Promise.all(batch.map(url => fetchPage(url, options)))
    results.push(...batchResults)
  }

  return results
}
