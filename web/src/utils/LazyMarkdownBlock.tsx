import { lazy, Suspense } from 'react'

const MarkdownBlockImpl = lazy(() =>
  import('@/utils/markdown').then((m) => ({ default: m.MarkdownBlock })),
)

interface LazyMarkdownBlockProps {
  content: string
  sessionId?: string
}

export function LazyMarkdownBlock({ content, sessionId }: LazyMarkdownBlockProps) {
  return (
    <Suspense fallback={<div className="oa-prose text-sm whitespace-pre-wrap">{content}</div>}>
      <MarkdownBlockImpl content={content} sessionId={sessionId} />
    </Suspense>
  )
}
