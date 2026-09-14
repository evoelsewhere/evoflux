/**
 * New-tab page for a panel with no workspace behind it.
 *
 * Coding mode opens onto the workspace's launch targets, which is the thing
 * you are about to verify. Work mode had nothing to open onto: an empty view
 * whose only affordance was the address bar, and no record of anywhere this
 * browser had already been.
 */

import { useState } from 'react'
import { Globe2, Search } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { BrowserRecentSite } from './browserPreferences'

interface BrowserStartPageProps {
  recentSites: BrowserRecentSite[]
  /**
   * Whether this panel is the one on screen. Workbench tabs stay mounted when
   * they are not, and a hidden page that grabs focus takes it from whatever
   * the user is actually typing in.
   */
  focused: boolean
  onOpen: (target: string) => void
}

export function BrowserStartPage({ recentSites, focused, onOpen }: BrowserStartPageProps) {
  const [query, setQuery] = useState('')

  return (
    <div className="absolute inset-0 overflow-y-auto bg-(--bg-page) px-6 py-10">
      <div className="mx-auto w-full max-w-md">
        <form
          onSubmit={(event) => {
            event.preventDefault()
            const value = query.trim()
            if (value) onOpen(value)
          }}
          className="relative"
        >
          <Search
            size={14}
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-(--color-text-subtle)"
          />
          <input
            autoFocus={focused}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search or enter a URL"
            aria-label="Search or enter a URL"
            spellCheck={false}
            className="h-10 w-full rounded-full border border-(--color-border) bg-(--bg-key) pl-9 pr-3 text-sm text-(--color-text) outline-none transition-colors placeholder:text-(--color-text-subtle) hover:border-(--color-border-strong) focus:border-(--color-accent) focus:bg-(--bg-page) focus:ring-2 focus:ring-(--color-accent)/15"
          />
        </form>

        {recentSites.length > 0 && (
          <>
            <p className="mt-6 text-[10px] font-medium uppercase tracking-wide text-(--color-text-subtle)">
              Recent
            </p>
            <ul className="mt-2 grid grid-cols-2 gap-1.5">
              {recentSites.map((site) => (
                <li key={site.origin}>
                  <button
                    type="button"
                    onClick={() => onOpen(site.url)}
                    title={site.url}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-md border border-(--color-border) px-2.5 py-2',
                      'text-left text-xs text-(--color-text) transition-colors',
                      'hover:border-(--color-border-strong) hover:bg-(--bg-key)',
                    )}
                  >
                    <Globe2 size={13} className="shrink-0 text-(--color-text-subtle)" aria-hidden />
                    <span className="truncate">{site.host}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  )
}
