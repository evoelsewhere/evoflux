import { useCallback, useEffect, useState } from 'react'
import { FileText, Loader2, ShieldAlert, ShieldCheck } from 'lucide-react'

import { workspaceMediaUrl } from '@/api/client'
import type { WorkspaceFileInfo } from '@/api/types'
import { formatBytes } from '@/utils/format'

const MAX_HTML_PREVIEW_BYTES = 512 * 1024

type PreparedHtml = {
  srcDoc: string
}

type WorkspaceReference = {
  path: string
  suffix: string
}

function dirname(path: string): string {
  const index = path.lastIndexOf('/')
  return index < 0 ? '' : path.slice(0, index)
}

function splitReferenceSuffix(reference: string): { pathname: string; suffix: string } {
  const queryIndex = reference.indexOf('?')
  const hashIndex = reference.indexOf('#')
  const suffixIndex = [queryIndex, hashIndex]
    .filter((index) => index >= 0)
    .sort((left, right) => left - right)[0]
  return suffixIndex === undefined
    ? { pathname: reference, suffix: '' }
    : { pathname: reference.slice(0, suffixIndex), suffix: reference.slice(suffixIndex) }
}

function resolveWorkspaceReference(baseFilePath: string, reference: string): WorkspaceReference | null {
  const trimmed = reference.trim()
  if (
    !trimmed
    || trimmed.startsWith('#')
    || trimmed.startsWith('//')
    || /^[a-z][a-z\d+.-]*:/i.test(trimmed)
  ) {
    return null
  }

  const { pathname: encodedPathname, suffix } = splitReferenceSuffix(trimmed)
  let pathname = encodedPathname
  try {
    pathname = decodeURIComponent(encodedPathname)
  } catch {
    // Keep malformed percent escapes untouched. The media URL encoder will
    // still make the resulting path safe to place in a URL.
  }

  const parts = pathname.startsWith('/') ? [] : dirname(baseFilePath).split('/').filter(Boolean)
  for (const part of pathname.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') {
      if (parts.length === 0) return null
      parts.pop()
      continue
    }
    parts.push(part)
  }
  if (parts.length === 0) return null
  return { path: parts.join('/'), suffix }
}

function appendReferenceSuffix(url: string, suffix: string): string {
  if (!suffix) return url
  if (suffix.startsWith('#')) return `${url}${suffix}`
  const hashIndex = suffix.indexOf('#')
  const query = hashIndex >= 0 ? suffix.slice(0, hashIndex) : suffix
  const hash = hashIndex >= 0 ? suffix.slice(hashIndex) : ''
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}${query.slice(1)}${hash}`
}

function referenceToMediaUrl(sessionId: string, baseFilePath: string, reference: string): string | null {
  const resolved = resolveWorkspaceReference(baseFilePath, reference)
  if (!resolved) return null
  return appendReferenceSuffix(workspaceMediaUrl(sessionId, resolved.path), resolved.suffix)
}

function rewriteCssUrls(css: string, sessionId: string, baseFilePath: string): string {
  const rewrite = (reference: string): string => (
    referenceToMediaUrl(sessionId, baseFilePath, reference) ?? reference
  )
  const withUrls = css.replace(
    /url\(\s*(['"]?)([^'")]+)\1\s*\)/gi,
    (_match, _quote: string, reference: string) => `url("${rewrite(reference)}")`,
  )
  return withUrls.replace(
    /@import\s+(['"])([^'"]+)\1/gi,
    (_match, quote: string, reference: string) => `@import ${quote}${rewrite(reference)}${quote}`,
  )
}

function rewriteSrcset(sessionId: string, baseFilePath: string, value: string): string {
  if (/^\s*data:/i.test(value)) return value
  return value.split(',').map((candidate) => {
    const match = /^(\s*)(\S+)(.*)$/.exec(candidate)
    if (!match) return candidate
    const rewritten = referenceToMediaUrl(sessionId, baseFilePath, match[2])
    return rewritten ? `${match[1]}${rewritten}${match[3]}` : candidate
  }).join(',')
}

function mediaOrigin(sessionId: string, filePath: string): string {
  try {
    return new URL(workspaceMediaUrl(sessionId, filePath), window.location.href).origin
  } catch {
    return window.location.origin
  }
}

function installPreviewPolicy(document: Document, sessionId: string, filePath: string, scriptsEnabled: boolean): void {
  document.querySelectorAll('meta[http-equiv="Content-Security-Policy" i]').forEach((meta) => meta.remove())
  const meta = document.createElement('meta')
  meta.httpEquiv = 'Content-Security-Policy'
  const origin = mediaOrigin(sessionId, filePath)
  meta.content = [
    "default-src 'none'",
    `img-src data: blob: ${origin}`,
    `media-src data: blob: ${origin}`,
    `font-src data: blob: ${origin}`,
    `style-src 'unsafe-inline' ${origin}`,
    scriptsEnabled ? `script-src 'unsafe-inline' 'unsafe-eval' ${origin}` : "script-src 'none'",
    scriptsEnabled ? `connect-src ${origin}` : "connect-src 'none'",
    "frame-src 'none'",
    "object-src 'none'",
    "form-action 'none'",
  ].join('; ')
  document.head.prepend(meta)

  if (!document.querySelector('meta[charset]')) {
    const charset = document.createElement('meta')
    charset.setAttribute('charset', 'utf-8')
    document.head.prepend(charset)
  }
}

async function fetchWorkspaceText(sessionId: string, path: string): Promise<string> {
  const response = await fetch(workspaceMediaUrl(sessionId, path), { cache: 'no-store' })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.text()
}

async function prepareRegularHtml(
  sessionId: string,
  file: WorkspaceFileInfo,
  source: string,
  scriptsEnabled: boolean,
): Promise<PreparedHtml> {
  const document = new DOMParser().parseFromString(source, 'text/html')

  const stylesheetLinks = Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel~="stylesheet"][href]'))
  await Promise.all(stylesheetLinks.map(async (link) => {
    const href = link.getAttribute('href') ?? ''
    const resolved = resolveWorkspaceReference(file.path, href)
    if (!resolved) return
    try {
      const css = await fetchWorkspaceText(sessionId, resolved.path)
      const style = document.createElement('style')
      style.textContent = rewriteCssUrls(css, sessionId, resolved.path)
      style.dataset.workspacePreviewResolved = 'true'
      link.replaceWith(style)
    } catch {
      const rewritten = referenceToMediaUrl(sessionId, file.path, href)
      if (rewritten) link.setAttribute('href', rewritten)
    }
  }))

  if (scriptsEnabled) {
    const scriptTags = Array.from(document.querySelectorAll<HTMLScriptElement>('script[src]'))
    await Promise.all(scriptTags.map(async (script) => {
      const src = script.getAttribute('src') ?? ''
      const resolved = resolveWorkspaceReference(file.path, src)
      if (!resolved) return
      try {
        const js = await fetchWorkspaceText(sessionId, resolved.path)
        const inline = document.createElement('script')
        inline.textContent = js
        for (const attr of script.attributes) {
          if (attr.name !== 'src') inline.setAttribute(attr.name, attr.value)
        }
        script.replaceWith(inline)
      } catch {
        // keep original src — CSP will decide
      }
    }))
  }

  document.querySelectorAll<HTMLElement>('[src], [href], [poster], [data]').forEach((element) => {
    for (const attribute of ['src', 'href', 'poster', 'data']) {
      const value = element.getAttribute(attribute)
      if (!value) continue
      const rewritten = referenceToMediaUrl(sessionId, file.path, value)
      if (rewritten) element.setAttribute(attribute, rewritten)
    }
  })
  document.querySelectorAll<HTMLElement>('[srcset]').forEach((element) => {
    const value = element.getAttribute('srcset')
    if (value) element.setAttribute('srcset', rewriteSrcset(sessionId, file.path, value))
  })
  document.querySelectorAll<HTMLStyleElement>('style:not([data-workspace-preview-resolved])').forEach((style) => {
    style.textContent = rewriteCssUrls(style.textContent ?? '', sessionId, file.path)
  })
  document.querySelectorAll<HTMLElement>('[style]').forEach((element) => {
    const value = element.getAttribute('style')
    if (value) element.setAttribute('style', rewriteCssUrls(value, sessionId, file.path))
  })
  installPreviewPolicy(document, sessionId, file.path, scriptsEnabled)
  return { srcDoc: `<!doctype html>${document.documentElement.outerHTML}` }
}

export function WorkspaceHtmlPreview({
  sessionId,
  file,
}: {
  sessionId: string
  file: WorkspaceFileInfo
}) {
  const tooLarge = file.size > MAX_HTML_PREVIEW_BYTES
  const [prepared, setPrepared] = useState<PreparedHtml | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!tooLarge)
  const [scriptsEnabled, setScriptsEnabled] = useState(false)

  const toggleScripts = useCallback(() => {
    setScriptsEnabled((prev) => !prev)
  }, [])

  useEffect(() => {
    if (tooLarge) return
    let cancelled = false
    void fetchWorkspaceText(sessionId, file.path)
      .then((source) => prepareRegularHtml(sessionId, file, source, scriptsEnabled))
      .then((result) => {
        if (!cancelled) {
          setPrepared(result)
          setLoading(false)
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason))
          setLoading(false)
        }
    })
    return () => { cancelled = true }
  }, [file, sessionId, tooLarge, scriptsEnabled])

  if (tooLarge) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
        <FileText size={24} className="text-(--color-text-subtle)" />
        <p className="text-sm text-(--color-text-2)">HTML file too large to preview</p>
        <p className="text-xs text-(--color-text-subtle)">
          {formatBytes(file.size)} — limit is {formatBytes(MAX_HTML_PREVIEW_BYTES)}
        </p>
      </div>
    )
  }
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-(--color-text-subtle)">
        <Loader2 size={16} className="animate-spin" />
      </div>
    )
  }
  if (error) {
    return (
      <div className="flex h-full items-center justify-center px-4 text-center text-xs text-(--color-error)">
        Failed to load HTML preview: {error}
      </div>
    )
  }
  if (!prepared) return null

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-end gap-2 border-b border-(--color-border-subtle) px-2 py-1">
        <button
          type="button"
          onClick={toggleScripts}
          className={`flex items-center gap-1 rounded px-2 py-0.5 text-xs transition-colors ${
            scriptsEnabled
              ? 'bg-(--color-warning-bg) text-(--color-warning)'
              : 'text-(--color-text-subtle) hover:text-(--color-text-2)'
          }`}
          title={scriptsEnabled ? 'Disable JavaScript' : 'Enable JavaScript'}
        >
          {scriptsEnabled ? <ShieldAlert size={12} /> : <ShieldCheck size={12} />}
          {scriptsEnabled ? 'JS On' : 'JS Off'}
        </button>
      </div>
      <iframe
        srcDoc={prepared.srcDoc}
        title={`${file.name} preview`}
        sandbox={scriptsEnabled ? 'allow-scripts allow-same-origin' : ''}
        referrerPolicy="no-referrer"
        className="min-h-0 flex-1 border-0 bg-white"
      />
    </div>
  )
}
