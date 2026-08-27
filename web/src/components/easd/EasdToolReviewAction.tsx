import { ArrowRight, FileCheck2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useUIStore } from '@/stores/useUIStore'
import type { EasdToolReviewTarget } from './easdToolReviewTarget'

export function EasdToolReviewAction({ target }: { target: EasdToolReviewTarget }) {
  const requestEasdRunOpen = useUIStore((state) => state.requestEasdRunOpen)
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => requestEasdRunOpen(target.runId)}
      className="h-8"
    >
      <FileCheck2 aria-hidden />
      {target.label}
      <ArrowRight aria-hidden />
    </Button>
  )
}
