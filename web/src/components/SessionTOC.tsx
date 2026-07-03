/**
 * SessionTOC — session table of contents dropdown.
 *
 * Shows the ordered list of chapters for the current session. Clicking a
 * chapter scrolls to the message block that started it via the
 * `data-chapter-anchor` attribute on user bubbles in AgentView.
 */

import { BookOpen, ChevronDown, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useSessionChapters, useDeleteChapter } from '@/hooks/useSessionChapters'
import type { Chapter } from '@/api/types'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

interface SessionTOCProps {
  sessionId: string | null | undefined
  className?: string
}

function scrollToChapter(chapter: Chapter) {
  if (!chapter.message_id) return
  const el = document.querySelector(`[data-chapter-anchor="${chapter.message_id}"]`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

export function SessionTOC({ sessionId, className }: SessionTOCProps) {
  const { data: chapters = [], isLoading } = useSessionChapters(sessionId)
  const deleteMutation = useDeleteChapter(sessionId)

  if (!sessionId) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          'inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs',
          'text-(--color-text-muted) transition-colors',
          'hover:bg-(--bg-hover) hover:text-(--color-text)',
          'disabled:cursor-not-allowed disabled:opacity-40',
          className,
        )}
        title="Session chapters (table of contents)"
        disabled={isLoading}
        aria-label="Session chapters"
      >
        <BookOpen size={14} />
        {chapters.length > 0 && (
          <span className="tabular-nums">{chapters.length}</span>
        )}
        <ChevronDown size={11} className="opacity-60" />
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-72 max-h-80 overflow-y-auto">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-xs font-medium text-(--color-text-muted)">
            Session chapters
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />

        {chapters.length === 0 ? (
          <div className="px-3 py-4 text-center text-xs text-(--color-text-muted)">
            No chapters yet. The assistant will create chapters automatically as the
            conversation shifts topics.
          </div>
        ) : (
          chapters.map((chapter, i) => (
            <DropdownMenuItem
              key={chapter.id}
              className="group flex items-start gap-2 py-2 cursor-pointer"
              onSelect={(e) => {
                e.preventDefault()
                scrollToChapter(chapter)
              }}
            >
              <span className="mt-0.5 shrink-0 text-xs tabular-nums text-(--color-text-muted) w-4 text-right">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium leading-tight">
                  {chapter.title}
                </div>
                {chapter.summary && (
                  <div className="truncate text-xs text-(--color-text-muted) mt-0.5">
                    {chapter.summary}
                  </div>
                )}
              </div>
              <button
                className={cn(
                  'shrink-0 rounded p-0.5 opacity-0 group-hover:opacity-100',
                  'text-(--color-text-muted) hover:text-red-500 transition-all',
                )}
                title="Delete chapter"
                onClick={(e) => {
                  e.stopPropagation()
                  deleteMutation.mutate(chapter.id)
                }}
                aria-label={`Delete chapter "${chapter.title}"`}
              >
                <Trash2 size={13} />
              </button>
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
