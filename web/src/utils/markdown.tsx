/**
 * Shared markdown rendering utilities.
 *
 * Used by AgentView (single-agent) and AgentPane (split/unified).
 * Keeps syntax highlighting, CodeBlock styling, and fixNestedFences in sync
 * across all views.
 */

import { memo, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeHighlight from 'rehype-highlight'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize from 'rehype-sanitize'
import 'katex/dist/katex.min.css'
import { Copy, Check, ImageOff, FileVideo } from 'lucide-react'
import { resolveApiUrl } from '@/api/client'
import { apiUrl } from '@/api/base-url'
import { withTokenParam } from '@/api/auth'
import { ImageLightbox } from '@/components/ImageLightbox'
import { useStreamingReveal } from '@/hooks/useStreamingReveal'
import { cn } from '@/lib/utils'
import {
  openWorkspaceFileLink,
  workspaceFilePathFromHref,
} from '@/lib/workspace-file-link'

// Me: extensions we render as ``<video>`` instead of ``<img>``. The backend
// `generate_video` tool writes ``.mp4`` files today, but keep the list
// open to future codecs so users who upload ``.webm`` / ``.mov`` also get
// inline playback for free.
const _VIDEO_EXTENSIONS = ['.mp4', '.webm', '.mov', '.m4v'] as const

/** Return true if ``src`` references a file with a video extension. */
// eslint-disable-next-line react-refresh/only-export-components
export function isVideoSrc(src: string | undefined): boolean {
  if (!src) return false
  // Strip query string / fragment before extension check so
  // ``/api/team/abc/media/clip.mp4?cache=123`` still matches.
  const cleaned = src.split(/[?#]/, 1)[0].toLowerCase()
  return _VIDEO_EXTENSIONS.some((ext) => cleaned.endsWith(ext))
}

// ── fixNestedFences ───────────────────────────────────────────────────────────

/**
 * Fix nested fenced code blocks for CommonMark.
 *
 * Problem: a ```markdown outer fence gets closed by the first bare ``` inside
 * (e.g. closing ```python inner block) because they're the same length.
 *
 * Fix: walk line-by-line, track nesting depth per fence length, and
 * re-fence any outer block whose body contains backtick runs long enough
 * to close it — using one more backtick than the longest inner run.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function fixNestedFences(content: string): string {
  const lines = content.split('\n')
  const result: string[] = []
  let i = 0

  while (i < lines.length) {
    const openMatch = lines[i].match(/^(`{3,})(\w*)(.*)$/)
    if (openMatch) {
      const openFence = openMatch[1]
      const lang = openMatch[2]
      const rest = openMatch[3]
      const openLen = openFence.length

      // Me scan forward tracking depth — a bare close fence of same length closes the block
      const bodyLines: string[] = []
      let j = i + 1
      let depth = 1
      while (j < lines.length) {
        const fenceMatch = lines[j].match(/^(`{3,})\s*(\w*).*$/)
        if (fenceMatch) {
          const fLen = fenceMatch[1].length
          if (fLen === openLen) {
            if (fenceMatch[2] === '') {
              depth--
              if (depth === 0) break  // Me found true closer
            } else {
              depth++  // Me nested opener of same length
            }
          }
        }
        bodyLines.push(lines[j])
        j++
      }

      if (depth !== 0 || j >= lines.length) {
        // Me unclosed — emit as-is and move on
        result.push(lines[i])
        i++
        continue
      }

      const body = bodyLines.join('\n')
      // Me find longest backtick run inside body
      const backtickRuns = [...body.matchAll(/`+/g)].map((m) => m[0].length)
      const maxInner = backtickRuns.length > 0 ? Math.max(...backtickRuns) : 0
      if (maxInner >= openLen) {
        // Me re-fence with enough backticks so inner fences can't close the outer block
        const newFence = '`'.repeat(maxInner + 1)
        result.push(newFence + lang + rest)
        result.push(...bodyLines)
        result.push(newFence)
      } else {
        result.push(lines[i])
        result.push(...bodyLines)
        result.push(lines[j])
      }
      i = j + 1
    } else {
      result.push(lines[i])
      i++
    }
  }

  return result.join('\n')
}

// ── extractText ───────────────────────────────────────────────────────────────

// Me rehype-highlight wraps code in spans — recursively collect text nodes
// eslint-disable-next-line react-refresh/only-export-components
export function extractText(node: unknown): string {
  if (typeof node === 'string') return node
  if (Array.isArray(node)) return (node as unknown[]).map(extractText).join('')
  if (node !== null && typeof node === 'object' && 'props' in node) {
    const el = node as { props: { children?: unknown } }
    return extractText(el.props.children)
  }
  return ''
}

// ── CodeBlock ─────────────────────────────────────────────────────────────────

export function CodeBlock({
  children,
  language,
  rawText,
}: {
  children: React.ReactNode
  language?: string
  rawText: string
}) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(rawText)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // ignore
    }
  }

  const copyButton = (
    <button
      onClick={handleCopy}
      className="flex h-8 w-8 items-center justify-center rounded-md text-(--color-text-muted) opacity-100 transition-[opacity,background-color,color] duration-(--motion-fast) hover:bg-(--bg-key) hover:text-(--color-text-2) md:h-6 md:w-6 md:opacity-0 md:group-hover:opacity-100"
      aria-label="Copy code"
      title="Copy"
    >
      {copied ? (
        <Check size={13} className="text-(--color-success)" />
      ) : (
        <Copy size={13} />
      )}
    </button>
  )

  return (
    <div className="group relative my-1.5 overflow-hidden rounded-md border border-(--color-border) bg-(--bg-card)">
      <div className="absolute top-1.5 right-1.5 z-(--z-panel)">{copyButton}</div>
      <pre
        className="m-0 overflow-x-auto px-3 py-2.5 pr-11 font-mono text-[13px] leading-5 text-(--color-text)"
      >
        <code className={cn('hljs block min-w-max bg-transparent p-0', language && `language-${language}`)}>
          {children}
        </code>
      </pre>
    </div>
  )
}

// ── resolveImageSrc ───────────────────────────────────────────────────────────

/**
 * Rewrite a markdown media ``src`` for rendering.
 *
 * Used for both images and videos — videos reach this helper through the
 * same ``![alt](file.ext)`` markdown path as images, because browsers don't
 * natively embed ``<video>`` from markdown. The downstream renderer
 * (``MarkdownImage``) inspects the extension via ``isVideoSrc`` and swaps in
 * a ``<video controls>`` element when appropriate.
 *
 * Rules:
 * - Absolute URLs (http/https), data:, blob:, and protocol-relative (`//...`)
 *   pass through unchanged.
 * - Bare relative paths are resolved against the agent workspace via the
 *   backend media proxy: ``/api/team/{sessionId}/media/{src}``.
 * - When no ``sessionId`` is available (e.g. standalone previews), the raw
 *   src is returned — the browser will show a broken image, which is the
 *   correct signal that the renderer lacks a session context.
 *
 * Exported for direct unit testing.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function resolveImageSrc(src: string | undefined, sessionId?: string): string | undefined {
  if (!src) return src
  // Absolute / external / inline — passthrough.
  if (/^(https?:)?\/\//i.test(src)) return src
  if (src.startsWith('data:') || src.startsWith('blob:')) return src
  // Already points at our API — passthrough (avoid double-prefixing).
  if (src.startsWith('/api/')) return resolveApiUrl(src)
  // Bare path but no session to anchor against — passthrough (broken image).
  if (!sessionId) return src
  // Strip any leading ``./`` and any leading ``/`` to keep the proxy URL clean.
  const cleaned = src.replace(/^\.\//, '').replace(/^\/+/, '')
  return withTokenParam(apiUrl(`/team/${encodeURIComponent(sessionId)}/media/${cleaned}`))
}

// ── MarkdownVideo ─────────────────────────────────────────────────────────────

/** Inline video inside markdown prose.
 *
 * Rendered when ``resolveImageSrc`` points at a workspace file with a video
 * extension (``.mp4`` / ``.webm`` / ``.mov`` / ``.m4v``). Uses the native
 * HTML5 video player with controls; no click-to-enlarge (controls already
 * expose fullscreen). On permanent load failure, shows a compact
 * placeholder with the alt text so paragraph flow isn't broken — same UX
 * as the broken-image fallback.
 *
 * **Why ``React.memo``**: during SSE streaming, the parent ``MarkdownBlock``
 * re-renders on every content chunk. Without memo-ing by ``src``, React
 * reconciliation recreates the ``<video>`` element enough to re-trigger
 * buffering/decoding each render, which the browser (plus our own
 * ``onError`` fallback swap) amplifies into a visible flicker loop. Image
 * elements don't suffer from this because the browser caches the decoded
 * bitmap; video elements restart their media element state machine when
 * attributes change.
 *
 * **Why the ``onError`` guard**: media elements fire transient ``error``
 * events during normal loading (e.g. source resolution races, network
 * hiccups) that resolve on their own. Unconditionally flipping to the
 * fallback creates a render cycle where the next render remounts the
 * video, fires another transient error, swaps back, and so on. We only
 * treat an error as permanent once the element's ``networkState`` has
 * settled on ``NETWORK_NO_SOURCE`` — the actual terminal "this URL
 * won't load" signal.
 */
const MarkdownVideo = memo(function MarkdownVideo({
  src,
  alt,
  title,
}: {
  src: string
  alt: string
  title?: string
}) {
  const [errored, setErrored] = useState(false)

  if (errored) {
    return (
      <span
        className="my-2 inline-flex items-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-card) px-3 py-2 text-xs text-(--color-text-muted)"
        title={alt || 'Video unavailable'}
      >
        <FileVideo size={14} />
        {alt || 'Video unavailable'}
      </span>
    )
  }

  return (
    <video
      src={src}
      title={title ?? alt}
      controls
      preload="metadata"
      playsInline
      onError={(e) => {
        // Only treat as terminal when the element reports NO_SOURCE.
        // Transient errors during buffering/codec negotiation are otherwise
        // ignored to avoid a flicker loop with the fallback placeholder.
        const el = e.currentTarget
        if (el.networkState === el.NETWORK_NO_SOURCE) {
          setErrored(true)
        }
      }}
      className="my-2 max-h-[80vh] max-w-full rounded-lg border border-(--color-border) bg-black"
    >
      {/* Fallback text for environments without <video> support (rare). */}
      {alt || 'Video content'}
    </video>
  )
})

// ── MarkdownImage ─────────────────────────────────────────────────────────────

/** Inline image (or video) inside markdown prose.
 *
 * Clicks open the shared ``ImageLightbox`` for a full-screen preview —
 * identical UX to user-uploaded ``ImageAttachment`` thumbnails.  On load
 * failure, renders a compact broken-image placeholder instead of leaving
 * a blank alt-text gap that breaks paragraph flow.
 *
 * When ``src`` ends in a known video extension, delegates to ``MarkdownVideo``
 * so agents using ``generate_video`` (``![prompt](clip.mp4)``) get an inline
 * HTML5 player without a new markdown syntax.
 */
function MarkdownImage({
  src,
  alt,
  title,
}: {
  src: string | undefined
  alt: string
  title?: string
}) {
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [errored, setErrored] = useState(false)

  if (!src || errored) {
    return (
      <span
        className="my-2 inline-flex items-center gap-2 rounded-lg border border-(--color-border) bg-(--bg-card) px-3 py-2 text-xs text-(--color-text-muted)"
        title={alt || 'Image unavailable'}
      >
        <ImageOff size={14} />
        {alt || 'Image unavailable'}
      </span>
    )
  }

  // Videos travel through the same ``![alt](path)`` markdown as images but
  // render as <video> — extension-based routing keeps the markdown authoring
  // contract identical for image and video tools.
  if (isVideoSrc(src)) {
    return <MarkdownVideo src={src} alt={alt} title={title} />
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setLightboxOpen(true)}
        className="my-2 block focus-visible:ring-2 focus-visible:ring-(--focus-ring)/40 focus-visible:outline-none"
        aria-label={alt ? `Open image preview: ${alt}` : 'Open image preview'}
      >
        <img
          src={src}
          alt={alt}
          title={title}
          loading="lazy"
          decoding="async"
          onError={() => setErrored(true)}
          className="max-h-[80vh] max-w-full cursor-zoom-in object-contain transition-opacity hover:opacity-90"
        />
      </button>
      <ImageLightbox
        src={src}
        alt={alt}
        isOpen={lightboxOpen}
        onClose={() => setLightboxOpen(false)}
      />
    </>
  )
}

// ── Incremental streaming markdown ──────────────────────────────────────────

const LIST_MARKER = /^\s{0,3}(?:[-+*]|\d+[.)])\s+/
const INDENTED_CONTINUATION = /^\s{2,}\S/

/**
 * Split a growing Markdown document only at completed block boundaries.
 *
 * Each returned string keeps its trailing blank-line separator. React can
 * therefore retain already-parsed segments while only the live tail changes.
 * Fenced code/math and loose lists stay together so their temporary streaming
 * representation remains structurally correct.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function splitStreamingMarkdown(content: string): string[] {
  if (!content) return [content]

  const chunks: string[] = []
  let segmentStart = 0
  let cursor = 0
  let pendingBoundary: number | null = null
  let fence: { marker: '`' | '~'; length: number } | null = null
  let inDisplayMath = false
  let segmentHasList = false
  let lastNonBlankLine = ''
  const lines = content.match(/[^\n]*(?:\n|$)/g) ?? []

  for (const rawLine of lines) {
    if (!rawLine) continue
    cursor += rawLine.length
    const line = rawLine.endsWith('\n') ? rawLine.slice(0, -1) : rawLine
    const trimmed = line.trim()

    if (!trimmed) {
      if (!fence && !inDisplayMath) pendingBoundary = cursor
      continue
    }

    if (pendingBoundary !== null && !fence && !inDisplayMath) {
      const continuesLooseList = segmentHasList && (
        LIST_MARKER.test(line) || INDENTED_CONTINUATION.test(line)
      )
      const continuesBlockquote = /^\s{0,3}>/.test(lastNonBlankLine)
        && /^\s{0,3}>/.test(line)
      if (!continuesLooseList && !continuesBlockquote && pendingBoundary > segmentStart) {
        chunks.push(content.slice(segmentStart, pendingBoundary))
        segmentStart = pendingBoundary
        segmentHasList = false
      }
      pendingBoundary = null
    }

    const fenceMatch = line.match(/^\s{0,3}(`{3,}|~{3,})(.*)$/)
    if (fenceMatch) {
      const run = fenceMatch[1]
      const marker = run[0] as '`' | '~'
      if (!fence) {
        fence = { marker, length: run.length }
      } else if (
        fence.marker === marker
        && run.length >= fence.length
        && fenceMatch[2].trim() === ''
      ) {
        fence = null
      }
    } else if (!fence && trimmed === '$$') {
      inDisplayMath = !inDisplayMath
    }

    if (!fence && !inDisplayMath && LIST_MARKER.test(line)) segmentHasList = true
    lastNonBlankLine = line
  }

  if (segmentStart < content.length || chunks.length === 0) {
    chunks.push(content.slice(segmentStart))
  }
  return chunks
}

type MarkdownComponents = NonNullable<React.ComponentProps<typeof ReactMarkdown>['components']>

function markdownSegmentsWithOffsets(chunks: string[]): Array<{ content: string; offset: number }> {
  const segments: Array<{ content: string; offset: number }> = []
  let offset = 0
  for (const content of chunks) {
    segments.push({ content, offset })
    offset += content.length
  }
  return segments
}

const MarkdownSegment = memo(function MarkdownSegment({
  content,
  components,
  allowHtml,
  streamingTail,
}: {
  content: string
  components: MarkdownComponents
  allowHtml?: boolean
  streamingTail: boolean
}) {
  const fixedContent = useMemo(() => fixNestedFences(content), [content])
  const rehypePlugins = streamingTail
    ? allowHtml
      ? _REHYPE_STREAMING_PLUGINS_WITH_HTML
      : _REHYPE_STREAMING_PLUGINS
    : allowHtml
      ? _REHYPE_PLUGINS_WITH_HTML
      : _REHYPE_PLUGINS

  return (
    <ReactMarkdown
      remarkPlugins={_REMARK_PLUGINS}
      rehypePlugins={rehypePlugins}
      components={components}
    >
      {fixedContent}
    </ReactMarkdown>
  )
})

function useNearViewport(
  ref: React.RefObject<HTMLDivElement | null>,
  enabled: boolean,
): boolean {
  const [nearViewport, setNearViewport] = useState(true)

  useEffect(() => {
    const element = ref.current
    if (!enabled || !element || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      ([entry]) => setNearViewport(entry?.isIntersecting ?? true),
      // Start catching up before the user actually reaches the live tail.
      { rootMargin: '800px 0px' },
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [enabled, ref])

  return !enabled || nearViewport
}

// ── MarkdownBlock ─────────────────────────────────────────────────────────────

/** Shared prose markdown renderer — handles nested fences with math and syntax highlighting.
 *
 * When ``sessionId`` is provided, bare image paths in ``![alt](path)`` are
 * rewritten to the backend media proxy so agents can reference files they
 * wrote into the workspace (e.g. ``![chart](chart.png)``).  All rendered
 * images open a full-screen lightbox on click.
 *
 * Pass ``isStreaming`` for the actively-growing tail block. Provider bursts
 * are revealed over short visual frames so text advances continuously while
 * finalized content still flushes immediately.
 */
export const MarkdownBlock = memo(function MarkdownBlock({
  content,
  sessionId,
  isStreaming,
  onLinkClick,
  allowHtml,
  transformImageSrc,
}: {
  content: string
  sessionId?: string
  isStreaming?: boolean
  onLinkClick?: (href: string) => boolean
  allowHtml?: boolean
  transformImageSrc?: (src: string) => string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const isNearViewport = useNearViewport(containerRef, Boolean(isStreaming))
  const displayedContent = useStreamingReveal(
    content,
    Boolean(isStreaming),
    isNearViewport,
  )
  // Me: the ``components`` map MUST be referentially stable across renders.
  // If we rebuild it inline every render, ReactMarkdown treats each call
  // as a new custom-component type and unmounts+remounts every ``<img>`` /
  // ``<MarkdownVideo>`` subtree — which restarts ``<video>`` buffering and
  // causes a visible flicker whenever the parent re-renders (e.g. on every
  // wheel/touchmove tick from ``AgentView``'s scroll-position tracker).
  // Memoizing on ``sessionId`` — the only captured value — keeps the same
  // function identities as long as the session doesn't change.
  const components = useMemo(
    () => ({
      pre: (props: React.HTMLAttributes<HTMLPreElement>) => {
        const codeEl = props.children as React.ReactElement<{
          children?: unknown
          className?: string
        }>
        const codeText = extractText(codeEl?.props?.children)
        const language = codeEl?.props?.className?.match(/(?:^|\s)language-([^\s]+)/)?.[1]
        return (
          <CodeBlock language={language} rawText={codeText}>
            {codeEl?.props?.children as React.ReactNode}
          </CodeBlock>
        )
      },
      a: ({ onClick, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => {
        if (
          allowHtml &&
          typeof props.href === 'string' &&
          transformImageSrc &&
          transformImageSrc(props.href) !== props.href
        ) {
          return <>{children}</>
        }
        const workspaceFilePath =
          typeof props.href === 'string' && sessionId
            ? workspaceFilePathFromHref(props.href, sessionId)
            : null
        return (
          <a
            {...props}
            target={workspaceFilePath ? undefined : '_blank'}
            rel={workspaceFilePath ? undefined : 'noopener noreferrer'}
            title={workspaceFilePath ? `Preview ${workspaceFilePath} in Files` : props.title}
            data-workspace-file-link={workspaceFilePath || undefined}
            onClick={(event) => {
              onClick?.(event)
              if (
                !event.defaultPrevented &&
                typeof props.href === 'string' &&
                (onLinkClick?.(props.href) || openWorkspaceFileLink(props.href, sessionId))
              ) {
                event.preventDefault()
              }
            }}
          >
            {children}
          </a>
        )
      },
      img: ({ src, alt, title }: React.ImgHTMLAttributes<HTMLImageElement>) => {
        const resolvedSrc = resolveImageSrc(
          typeof src === 'string' ? src : undefined,
          sessionId,
        )
        return (
          <MarkdownImage
            src={resolvedSrc && transformImageSrc ? transformImageSrc(resolvedSrc) : resolvedSrc}
            alt={alt ?? ''}
            title={typeof title === 'string' ? title : undefined}
          />
        )
      },
    }),
    [allowHtml, onLinkClick, sessionId, transformImageSrc],
  )

  const segments = useMemo(
    () => markdownSegmentsWithOffsets(
      isStreaming ? splitStreamingMarkdown(displayedContent) : [displayedContent],
    ),
    [displayedContent, isStreaming],
  )

  return (
    <div
      ref={containerRef}
      data-i18n-ignore
      className={cn('oa-prose text-sm', isStreaming && 'oa-streaming-prose')}
      aria-busy={isStreaming || undefined}
    >
      {segments.map((segment, index) => (
        <MarkdownSegment
          key={segment.offset}
          content={segment.content}
          components={components}
          allowHtml={allowHtml}
          streamingTail={Boolean(isStreaming && index === segments.length - 1)}
        />
      ))}
    </div>
  )
})

// Me: module-level constants so ReactMarkdown sees the same plugin array
// identity across every ``MarkdownBlock`` instance and every render — it
// shallow-compares plugins to decide whether to rebuild its processor.
const _REMARK_PLUGINS = [remarkGfm, remarkMath]
const _REHYPE_PLUGINS: React.ComponentProps<typeof ReactMarkdown>['rehypePlugins'] = [
  // Highlight only explicitly-labelled fences. Auto-detection gives prose
  // diagrams false languages (often SQL) and colors ordinary words as code.
  rehypeHighlight,
  rehypeKatex,
]
const _REHYPE_PLUGINS_WITH_HTML: React.ComponentProps<typeof ReactMarkdown>['rehypePlugins'] = [
  rehypeRaw,
  rehypeSanitize,
  ..._REHYPE_PLUGINS,
]
// Syntax highlighting is the expensive pass and its output is unstable while
// a code fence is still growing. The live tail keeps math/HTML semantics, then
// receives full highlighting once it becomes a frozen segment or the turn ends.
const _REHYPE_STREAMING_PLUGINS: React.ComponentProps<typeof ReactMarkdown>['rehypePlugins'] = [
  rehypeKatex,
]
const _REHYPE_STREAMING_PLUGINS_WITH_HTML: React.ComponentProps<typeof ReactMarkdown>['rehypePlugins'] = [
  rehypeRaw,
  rehypeSanitize,
  ..._REHYPE_STREAMING_PLUGINS,
]
