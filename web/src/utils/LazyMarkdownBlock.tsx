import { lazy, Suspense } from 'react'

const MarkdownBlockImpl = lazy(() =>
  import('@/utils/markdown').then((m) => ({ default: m.MarkdownBlock })),
)

interface LazyMarkdownBlockProps {
  content: string
  sessionId?: string
  isStreaming?: boolean
  onLinkClick?: (href: string) => boolean
  allowHtml?: boolean
  transformImageSrc?: (src: string) => string
}

export function LazyMarkdownBlock({
  content,
  sessionId,
  isStreaming,
  onLinkClick,
  allowHtml,
  transformImageSrc,
}: LazyMarkdownBlockProps) {
  return (
    <Suspense fallback={<div data-i18n-ignore className="oa-prose text-sm whitespace-pre-wrap">{content}</div>}>
      <MarkdownBlockImpl
        content={content}
        sessionId={sessionId}
        isStreaming={isStreaming}
        onLinkClick={onLinkClick}
        allowHtml={allowHtml}
        transformImageSrc={transformImageSrc}
      />
    </Suspense>
  )
}
