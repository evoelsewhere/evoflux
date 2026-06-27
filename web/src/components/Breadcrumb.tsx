/**
 * Breadcrumb — Apple-style path navigation.
 *
 * Renders: Home › Label1 › Label2 (last item is non-clickable, bold)
 * Designed for the 40 px app header; all items are compact and truncate
 * gracefully at narrow widths.
 */
import { Link } from '@tanstack/react-router'
import { ChevronRight, Home } from 'lucide-react'

import { cn } from '@/lib/utils'

export interface BreadcrumbItem {
  label: string
  /** Provide a `to` path to make this crumb a navigation link. */
  to?: string
}

interface BreadcrumbProps {
  items: BreadcrumbItem[]
  className?: string
}

export function Breadcrumb({ items, className }: BreadcrumbProps) {
  if (items.length === 0) return null

  return (
    <nav
      aria-label="Breadcrumb"
      className={cn(
        'flex min-w-0 items-center gap-0.5 text-xs text-(--color-text-muted)',
        className,
      )}
    >
      <Link
        to="/"
        aria-label="Home"
        className="flex shrink-0 items-center rounded px-0.5 py-0.5 transition-colors hover:text-(--color-text)"
      >
        <Home size={11} aria-hidden="true" />
      </Link>

      {items.map((item, i) => {
        const isLast = i === items.length - 1
        return (
          <span key={i} className="flex min-w-0 shrink-0 items-center gap-0.5">
            <ChevronRight
              size={9}
              aria-hidden="true"
              className="shrink-0 opacity-30"
            />
            {!isLast && item.to ? (
              <Link
                to={item.to}
                className="shrink-0 truncate rounded px-0.5 py-0.5 transition-colors hover:text-(--color-text)"
              >
                {item.label}
              </Link>
            ) : (
              <span
                className={cn(
                  'min-w-0 truncate px-0.5',
                  isLast && 'font-medium text-(--color-text-2)',
                )}
                title={item.label}
              >
                {item.label}
              </span>
            )}
          </span>
        )
      })}
    </nav>
  )
}
