import { useEffect, useRef, useState } from 'react'
import { FileText, Loader2 } from 'lucide-react'

import { workspaceMediaUrl } from '@/api/client'
import type { WorkspaceFileInfo } from '@/api/types'
import { formatBytes } from '@/utils/format'
import slideRuntimeCss from './artifacts/slide-runtime.css?inline'

const MAX_HTML_PREVIEW_BYTES = 512 * 1024
const PREVIEW_PADDING = 24

type SlideProjectEntry = {
  html_path?: unknown
  style_paths?: unknown
  assets?: unknown
}

type SlideProject = {
  width?: unknown
  height?: unknown
  slides?: unknown
}

type PreparedHtml = {
  srcDoc: string
  canvas: { width: number; height: number } | null
}

type WorkspaceReference = {
  path: string
  suffix: string
}

function dirname(path: string): string {
  const index = path.lastIndexOf('/')
  return index < 0 ? '' : path.slice(0, index)
}

function joinWorkspacePath(directory: string, path: string): string {
  return directory ? `${directory}/${path}` : path
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

function installPreviewPolicy(document: Document, sessionId: string, filePath: string): void {
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

async function fetchWorkspaceText(sessionId: string, path: string): Promise<string> {
  const response = await fetch(workspaceMediaUrl(sessionId, path), { cache: 'no-store' })
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.text()
}

function candidateProjectPaths(filePath: string, files: WorkspaceFileInfo[]): string[] {
  const available = new Set(files.map((file) => file.path))
  const candidates: string[] = []
  let directory = dirname(filePath)
  while (true) {
    const candidate = joinWorkspacePath(directory, 'project.json')
    if (available.has(candidate)) candidates.push(candidate)
    if (!directory) break
    directory = dirname(directory)
  }
  return candidates
}

function slideCanvas(project: SlideProject): { width: number; height: number } {
  const width = typeof project.width === 'number' && project.width > 0 ? project.width : 1280
  const height = typeof project.height === 'number' && project.height > 0 ? project.height : 720
  return { width, height }
}

function isSlideEntry(value: unknown): value is SlideProjectEntry {
  return Boolean(value && typeof value === 'object')
}

function replaceAssetReferences(
  value: string,
  assets: Record<string, string>,
  sessionId: string,
  projectPath: string,
): string {
  let result = value
  for (const [key, relativePath] of Object.entries(assets)) {
    const resolved = resolveWorkspaceReference(projectPath, relativePath)
    if (!resolved) continue
    result = result.split(`asset://${key}`).join(workspaceMediaUrl(sessionId, resolved.path))
  }
  return result
}

async function prepareSlideProject(
  sessionId: string,
  file: WorkspaceFileInfo,
  files: WorkspaceFileInfo[],
  source: string,
): Promise<PreparedHtml | null> {
  for (const projectPath of candidateProjectPaths(file.path, files)) {
    let project: SlideProject
    try {
      project = JSON.parse(await fetchWorkspaceText(sessionId, projectPath)) as SlideProject
    } catch {
      continue
    }
    if (!Array.isArray(project.slides)) continue

    const slide = project.slides.filter(isSlideEntry).find((entry) => {
      if (typeof entry.html_path !== 'string') return false
      return resolveWorkspaceReference(projectPath, entry.html_path)?.path === file.path
    })
    if (!slide) continue

    const assets = slide.assets && typeof slide.assets === 'object' && !Array.isArray(slide.assets)
      ? Object.fromEntries(
          Object.entries(slide.assets).filter((entry): entry is [string, string] => typeof entry[1] === 'string'),
        )
      : {}
    const stylePaths = Array.isArray(slide.style_paths)
      ? slide.style_paths.filter((value): value is string => typeof value === 'string')
      : []
    const cssParts = await Promise.all(stylePaths.map(async (stylePath) => {
      const resolved = resolveWorkspaceReference(projectPath, stylePath)
      if (!resolved) return ''
      try {
        const css = await fetchWorkspaceText(sessionId, resolved.path)
        return replaceAssetReferences(
          rewriteCssUrls(css, sessionId, resolved.path),
          assets,
          sessionId,
          projectPath,
        )
      } catch {
        return ''
      }
    }))
    const canvas = slideCanvas(project)
    const document = new DOMParser().parseFromString('<!doctype html><html><head></head><body></body></html>', 'text/html')
    const runtimeStyle = document.createElement('style')
    runtimeStyle.textContent = slideRuntimeCss
    document.head.append(runtimeStyle)
    const projectStyle = document.createElement('style')
    projectStyle.textContent = cssParts.join('\n')
    document.head.append(projectStyle)
    const frameStyle = document.createElement('style')
    frameStyle.textContent = `html,body{margin:0;width:${canvas.width}px;height:${canvas.height}px;overflow:hidden;background:transparent}*{box-sizing:border-box}[data-slide-root]{width:${canvas.width}px;height:${canvas.height}px;overflow:hidden}`
    document.head.append(frameStyle)
    document.body.innerHTML = replaceAssetReferences(source, assets, sessionId, projectPath)
    installPreviewPolicy(document, sessionId, file.path)
    return { srcDoc: `<!doctype html>${document.documentElement.outerHTML}`, canvas }
  }
  return null
}

async function prepareRegularHtml(
  sessionId: string,
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
  installPreviewPolicy(document, sessionId, file.path)
  return { srcDoc: `<!doctype html>${document.documentElement.outerHTML}`, canvas: null }
}

function SlideFrame({ prepared, title }: { prepared: PreparedHtml; title: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [availableSize, setAvailableSize] = useState<{ width: number; height: number } | null>(null)
  const canvas = prepared.canvas!

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const update = () => {
      const bounds = container.getBoundingClientRect()
      setAvailableSize({ width: bounds.width, height: bounds.height })
    }
    update()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', update)
      return () => window.removeEventListener('resize', update)
    }
    const observer = new ResizeObserver(update)
    observer.observe(container)
    return () => observer.disconnect()
  }, [])

  const scale = availableSize
    ? Math.min(
        1,
        Math.max(0.05, (availableSize.width - PREVIEW_PADDING * 2) / canvas.width),
        Math.max(0.05, (availableSize.height - PREVIEW_PADDING * 2) / canvas.height),
      )
    : 1

  return (
    <div ref={containerRef} className="flex h-full items-center justify-center overflow-auto bg-(--bg-page) p-6">
      <div
        className="shrink-0 overflow-hidden rounded border border-(--color-border) bg-white shadow-lg"
        style={{ width: canvas.width * scale, height: canvas.height * scale }}
      >
        <iframe
          srcDoc={prepared.srcDoc}
          title={`${title} preview`}
          sandbox=""
          referrerPolicy="no-referrer"
          className="block border-0 bg-white"
          style={{
            width: canvas.width,
            height: canvas.height,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
          }}
        />
      </div>
    </div>
  )
}

export function WorkspaceHtmlPreview({
  sessionId,
  file,
  files,
}: {
  sessionId: string
  file: WorkspaceFileInfo
  files: WorkspaceFileInfo[]
}) {
  const tooLarge = file.size > MAX_HTML_PREVIEW_BYTES
  const [prepared, setPrepared] = useState<PreparedHtml | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!tooLarge)

  useEffect(() => {
    if (tooLarge) return
    let cancelled = false
    void fetchWorkspaceText(sessionId, file.path)
      .then(async (source) => (
        await prepareSlideProject(sessionId, file, files, source)
        ?? await prepareRegularHtml(sessionId, file, source)
      ))
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
  }, [file, files, sessionId, tooLarge])

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

  if (prepared.canvas) return <SlideFrame prepared={prepared} title={file.name} />
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
