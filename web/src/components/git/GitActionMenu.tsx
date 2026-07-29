import {
  useEffect,
  useState,
  type CSSProperties,
  type MouseEventHandler,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { MoreHorizontal } from 'lucide-react'

import { cn } from '@/lib/utils'

export interface GitAction {
  label: string
  icon: ReactNode
  onSelect: () => void
  disabled?: boolean
  danger?: boolean
  separatorBefore?: boolean
  hint?: string
}

interface GitActionSurfaceProps {
  label: string
  actions: GitAction[]
  children: ReactNode
  className?: string
  style?: CSSProperties
  onClick?: MouseEventHandler<HTMLDivElement>
  onOpenMenu?: () => void
  triggerClassName?: string
  dataReviewKey?: string
}

/**
 * Shared Git row interaction: regular click keeps the row's primary action,
 * while right-click and the trailing ellipsis expose the exact same commands.
 */
export function GitActionSurface({
  label,
  actions,
  children,
  className,
  style,
  onClick,
  onOpenMenu,
  triggerClassName,
  dataReviewKey,
}: GitActionSurfaceProps) {
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null)

  useEffect(() => {
    if (!anchor) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAnchor(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [anchor])

  const openAt = (x: number, y: number) => {
    onOpenMenu?.()
    setAnchor({ x, y })
  }

  return (
    <>
      <div
        className={cn('group relative', className)}
        data-review-key={dataReviewKey}
        style={style}
        onClick={onClick}
        onContextMenu={(event) => {
          event.preventDefault()
          event.stopPropagation()
          openAt(event.clientX, event.clientY)
        }}
      >
        {children}
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            const rect = event.currentTarget.getBoundingClientRect()
            openAt(rect.right, rect.bottom + 2)
          }}
          className={cn(
            'flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) opacity-0 transition-opacity hover:bg-(--bg-key) hover:text-(--color-text) focus-visible:opacity-100 group-hover:opacity-100',
            triggerClassName,
          )}
          aria-label={`More actions for ${label}`}
          title="More actions"
        >
          <MoreHorizontal size={13} />
        </button>
      </div>

      {anchor &&
        createPortal(
          <div
            className="fixed inset-0 z-(--z-modal)"
            onClick={() => setAnchor(null)}
            onContextMenu={(event) => {
              event.preventDefault()
              setAnchor(null)
            }}
          >
            <div
              role="menu"
              aria-label={`Git actions for ${label}`}
              className="fixed max-h-[min(28rem,calc(100dvh-1rem))] w-56 overflow-y-auto rounded-lg border border-(--color-border) bg-(--bg-card) p-1 text-[11px] text-(--color-text) shadow-xl"
              style={{
                left: Math.min(anchor.x, Math.max(8, window.innerWidth - 232)),
                top: Math.min(
                  anchor.y,
                  Math.max(8, window.innerHeight - Math.min(420, actions.length * 34 + 16)),
                ),
              }}
              onClick={(event) => event.stopPropagation()}
            >
              {actions.map((action) => (
                <div key={action.label}>
                  {action.separatorBefore && <div className="my-1 h-px bg-(--color-border)" />}
                  <button
                    type="button"
                    role="menuitem"
                    disabled={action.disabled}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left outline-none hover:bg-(--bg-key) focus-visible:bg-(--bg-key) disabled:pointer-events-none disabled:opacity-40',
                      action.danger && 'text-(--color-error) hover:bg-(--color-error-subtle) focus-visible:bg-(--color-error-subtle)',
                    )}
                    onClick={() => {
                      setAnchor(null)
                      action.onSelect()
                    }}
                  >
                    <span className="flex w-4 shrink-0 items-center justify-center">{action.icon}</span>
                    <span className="min-w-0 flex-1 truncate">{action.label}</span>
                    {action.hint && <span className="text-[9px] text-(--color-text-subtle)">{action.hint}</span>}
                  </button>
                </div>
              ))}
            </div>
          </div>,
          document.body,
        )}
    </>
  )
}
