import { lazy, Suspense } from 'react'

const MarkdownBlockImpl = lazy(() =>
  import('@/utils/markdown').then((m) => ({ default: m.MarkdownBlock })),
)

interface LazyMarkdownBlockProps {
  content: string
  sessionId?: string
  isStreaming?: boolean
}

export function LazyMarkdownBlock({ content, sessionId, isStreaming }: LazyMarkdownBlockProps) {
  return (
    <Suspense fallback={<div data-i18n-ignore className="oa-prose text-sm whitespace-pre-wrap">{content}</div>}>
      <MarkdownBlockImpl content={content} sessionId={sessionId} isStreaming={isStreaming} />
    </Suspense>
  )
}
