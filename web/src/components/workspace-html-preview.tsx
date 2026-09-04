/**
 * WorkspaceHtmlPreview — renders a workspace HTML file as an inert page.
 *
 * The file is parsed, its relative references are rewritten to the API that
 * serves the workspace, and the result is handed to a fully sandboxed iframe
 * with a restrictive CSP: no scripts, no network, images and fonts only from
 * the workspace itself. Previewing a page with `allow-scripts allow-same-origin`
 * instead would let a generated file reach into the app's own origin.
 *
 * Serves both modes: Work mode passes ``sessionId`` (session workspace media
 * proxy), Code mode passes ``workspace`` (coding workspace file endpoint).
 */
import { useEffect, useState } from 'react'
import { FileText, Loader2 } from 'lucide-react'

import { codingWorkspaceFileUrl, workspaceMediaUrl } from '@/api/client'
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

/** Resolves a workspace-relative path to the URL that serves its bytes. */
type UrlResolver = (path: string) => string

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

function referenceToMediaUrl(
  resolve: UrlResolver,
  baseFilePath: string,
  reference: string,
): string | null {
  const resolved = resolveWorkspaceReference(baseFilePath, reference)
  if (!resolved) return null
  return appendReferenceSuffix(resolve(resolved.path), resolved.suffix)
}

function rewriteCssUrls(css: string, resolve: UrlResolver, baseFilePath: string): string {
  const rewrite = (reference: string): string => (
    referenceToMediaUrl(resolve, baseFilePath, reference) ?? reference
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

function rewriteSrcset(resolve: UrlResolver, baseFilePath: string, value: string): string {
  if (/^\s*data:/i.test(value)) return value
  return value.split(',').map((candidate) => {
    const match = /^(\s*)(\S+)(.*)$/.exec(candidate)
    if (!match) return candidate
    const rewritten = referenceToMediaUrl(resolve, baseFilePath, match[2])
    return rewritten ? `${match[1]}${rewritten}${match[3]}` : candidate
  }).join(',')
}

function mediaOrigin(resolve: UrlResolver, filePath: string): string {
  try {
    return new URL(resolve(filePath), window.location.href).origin
  } catch {
    return window.location.origin
  }
}

function installPreviewPolicy(document: Document, resolve: UrlResolver, filePath: string): void {
  document.querySelectorAll('meta[http-equiv="Content-Security-Policy" i]').forEach((meta) => meta.remove())
  const meta = document.createElement('meta')
  meta.httpEquiv = 'Content-Security-Policy'
  const origin = mediaOrigin(resolve, filePath)
  meta.content = [
    "default-src 'none'",
    `img-src data: blob: ${origin}`,
    `media-src data: blob: ${origin}`,
    `font-src data: blob: ${origin}`,
    `style-src 'unsafe-inline' ${origin}`,
    "script-src 'none'",
    "connect-src 'none'",
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

async function fetchWorkspaceText(resolve: UrlResolver, path: string): Promise<string> {
  const response = await fetch(resolve(path), { cache: 'no-store' })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.text()
}

async function prepareRegularHtml(
  resolve: UrlResolver,
  file: WorkspaceFileInfo,
  source: string,
): Promise<PreparedHtml> {
  const document = new DOMParser().parseFromString(source, 'text/html')

  const stylesheetLinks = Array.from(document.querySelectorAll<HTMLLinkElement>('link[rel~="stylesheet"][href]'))
  await Promise.all(stylesheetLinks.map(async (link) => {
    const href = link.getAttribute('href') ?? ''
    const resolved = resolveWorkspaceReference(file.path, href)
    if (!resolved) return
    try {
      const css = await fetchWorkspaceText(resolve, resolved.path)
      const style = document.createElement('style')
      style.textContent = rewriteCssUrls(css, resolve, resolved.path)
      style.dataset.workspacePreviewResolved = 'true'
      link.replaceWith(style)
    } catch {
      const rewritten = referenceToMediaUrl(resolve, file.path, href)
      if (rewritten) link.setAttribute('href', rewritten)
    }
  }))

  document.querySelectorAll<HTMLElement>('[src], [href], [poster], [data]').forEach((element) => {
    for (const attribute of ['src', 'href', 'poster', 'data']) {
      const value = element.getAttribute(attribute)
      if (!value) continue
      const rewritten = referenceToMediaUrl(resolve, file.path, value)
      if (rewritten) element.setAttribute(attribute, rewritten)
    }
  })
  document.querySelectorAll<HTMLElement>('[srcset]').forEach((element) => {
    const value = element.getAttribute('srcset')
    if (value) element.setAttribute('srcset', rewriteSrcset(resolve, file.path, value))
  })
  document.querySelectorAll<HTMLStyleElement>('style:not([data-workspace-preview-resolved])').forEach((style) => {
    style.textContent = rewriteCssUrls(style.textContent ?? '', resolve, file.path)
  })
  document.querySelectorAll<HTMLElement>('[style]').forEach((element) => {
    const value = element.getAttribute('style')
    if (value) element.setAttribute('style', rewriteCssUrls(value, resolve, file.path))
  })
  installPreviewPolicy(document, resolve, file.path)
  return { srcDoc: `<!doctype html>${document.documentElement.outerHTML}` }
}

export function WorkspaceHtmlPreview({
  sessionId,
  workspace,
  file,
}: {
  /** Session workspace the file belongs to (Work mode). */
  sessionId?: string
  /** Coding workspace root the file belongs to (Code mode). */
  workspace?: string
  file: WorkspaceFileInfo
}) {
  const tooLarge = file.size > MAX_HTML_PREVIEW_BYTES
  const [prepared, setPrepared] = useState<PreparedHtml | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!tooLarge)

  useEffect(() => {
    if (tooLarge) return
    let cancelled = false
    const resolve: UrlResolver = workspace
      ? (path) => codingWorkspaceFileUrl(workspace, path)
      : (path) => workspaceMediaUrl(sessionId ?? '', path)

    void fetchWorkspaceText(resolve, file.path)
      .then((source) => prepareRegularHtml(resolve, file, source))
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
  }, [file, sessionId, tooLarge, workspace])

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
    <iframe
      srcDoc={prepared.srcDoc}
      title={`${file.name} preview`}
      sandbox=""
      referrerPolicy="no-referrer"
      className="h-full w-full border-0 bg-white"
    />
  )
}
