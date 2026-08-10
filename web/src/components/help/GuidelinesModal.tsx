/**
 * GuidelinesModal — searchable in-app tips covering every major EvoFlux surface.
 * Opened from the sidebar Help button; Command Palette stays on Ctrl+P.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ArrowLeft,
  BookOpen,
  CornerDownLeft,
  ExternalLink,
  Search,
  X,
} from 'lucide-react'

import {
  filterArticlesByCategory,
  getHelpArticle,
  getHelpArticles,
  getHelpCategories,
  searchHelpArticles,
  type HelpArticle,
  type HelpBlock,
  type HelpCategoryId,
} from '@/help'
import { useI18n, useLocale } from '@/i18n'
import { useModalFocus } from '@/hooks/useModalFocus'
import { usePlatform } from '@/hooks/use-platform'
import { useIsMobile } from '@/hooks/use-mobile'
import { useReducedMotion } from '@/hooks/useReducedMotion'
import { reducedMotionTransition, useMotionPreset } from '@/lib/motion'
import { useUIStore } from '@/stores/useUIStore'
import { cn } from '@/lib/utils'

function dispatchCtrlKey(key: string): void {
  window.dispatchEvent(
    new KeyboardEvent('keydown', {
      key,
      ctrlKey: true,
      metaKey: false,
      bubbles: true,
    }),
  )
}

function BlockView({ block }: { block: HelpBlock }) {
  if (block.type === 'p') {
    return <p className="text-sm leading-relaxed text-(--color-text-2)">{block.text}</p>
  }
  if (block.type === 'heading') {
    return (
      <h3 className="border-b border-(--color-border) pb-1.5 pt-2 text-sm font-semibold text-(--color-text)">
        {block.text}
      </h3>
    )
  }
  if (block.type === 'code') {
    return (
      <figure className="overflow-hidden rounded-lg border border-(--color-border) bg-(--bg-page)">
        {(block.caption || block.language) && (
          <figcaption className="flex items-center justify-between gap-3 border-b border-(--color-border) px-3 py-1.5 text-[11px] text-(--color-text-muted)">
            <span>{block.caption}</span>
            {block.language && <span className="font-mono uppercase">{block.language}</span>}
          </figcaption>
        )}
        <pre className="overflow-x-auto p-3 text-xs leading-relaxed text-(--color-text-2)">
          <code>{block.code}</code>
        </pre>
      </figure>
    )
  }
  if (block.type === 'table') {
    return (
      <div className="overflow-x-auto rounded-lg border border-(--color-border)">
        <table className="w-full min-w-lg border-collapse text-left text-xs">
          <thead className="bg-(--bg-key)">
            <tr>
              {block.columns.map((column) => (
                <th key={column} className="border-b border-(--color-border) px-3 py-2 font-semibold text-(--color-text)">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={`${rowIndex}-${row.join('-')}`} className="border-b border-(--color-border) last:border-b-0">
                {block.columns.map((_, columnIndex) => (
                  <td key={columnIndex} className="align-top px-3 py-2 leading-relaxed text-(--color-text-2)">
                    {row[columnIndex] ?? ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }
  if (block.type === 'callout') {
    return (
      <div
        className={cn(
          'rounded-lg border px-3 py-2.5',
          block.tone === 'warning'
            ? 'border-(--color-warning)/30 bg-(--color-warning-subtle)'
            : 'border-(--color-accent)/25 bg-(--color-accent-soft)/35',
        )}
      >
        <p className="text-xs font-semibold text-(--color-text)">{block.title}</p>
        <p className="mt-1 text-sm leading-relaxed text-(--color-text-2)">{block.text}</p>
      </div>
    )
  }
  if (block.type === 'tips') {
    return (
      <ul className="space-y-1.5 rounded-lg border border-(--color-border) bg-(--bg-key)/40 px-3 py-2.5">
        {block.items.map((item) => (
          <li key={item} className="text-sm leading-relaxed text-(--color-text-2)">
            <span className="mr-1.5 text-(--color-accent)">·</span>
            {item}
          </li>
        ))}
      </ul>
    )
  }
  if (block.type === 'shortcuts') {
    return (
      <div className="overflow-hidden rounded-lg border border-(--color-border)">
        {block.rows.map((row) => (
          <div
            key={`${row.keys}-${row.action}`}
            className="flex items-center justify-between gap-3 border-b border-(--color-border) px-3 py-2 last:border-b-0"
          >
            <span className="text-sm text-(--color-text-2)">{row.action}</span>
            <kbd className="shrink-0 rounded-md border border-(--color-border) bg-(--bg-page) px-1.5 py-0.5 font-mono text-[11px] text-(--color-text-muted)">
              {row.keys}
            </kbd>
          </div>
        ))}
      </div>
    )
  }
  return (
    <div className="overflow-hidden rounded-lg border border-(--color-border)">
      {block.commands.map((row) => (
        <div
          key={row.cmd}
          className="flex items-start gap-3 border-b border-(--color-border) px-3 py-2 last:border-b-0"
        >
          <code className="shrink-0 rounded-md bg-(--bg-key) px-1.5 py-0.5 font-mono text-[11px] text-(--color-accent)">
            {row.cmd}
          </code>
          <span className="text-sm text-(--color-text-2)">{row.desc}</span>
        </div>
      ))}
    </div>
  )
}

function ArticleBody({
  article,
  locale,
  onOpenRelated,
  onOpenAction,
}: {
  article: HelpArticle
  locale: ReturnType<typeof useLocale>
  onOpenRelated: (id: string) => void
  onOpenAction: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-(--color-text)">{article.title}</h2>
        <p className="mt-1 text-sm text-(--color-text-muted)">{article.summary}</p>
      </div>
      {article.setup && (
        <div className="rounded-lg border border-(--color-border) bg-(--color-accent-soft)/40 px-3 py-2">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-(--color-text-muted)">
            {t('Setup')}
          </p>
          <p className="mt-1 text-sm text-(--color-text-2)">{article.setup}</p>
        </div>
      )}
      <div className="space-y-3">
        {article.blocks.map((block, index) => (
          <BlockView key={index} block={block} />
        ))}
      </div>
      {article.tricks && article.tricks.length > 0 && (
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-(--color-text-muted)">
            {t('Tricks')}
          </p>
          <ul className="space-y-1.5">
            {article.tricks.map((trick) => (
              <li key={trick} className="flex gap-2 text-sm text-(--color-text-2)">
                <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-(--color-accent)" />
                <span>{trick}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {article.openAction && (
        <button
          type="button"
          onClick={onOpenAction}
          className="focus-ring-control inline-flex items-center gap-1.5 rounded-lg border border-(--color-border) bg-(--bg-key) px-3 py-2 text-sm font-medium text-(--color-text) transition-colors hover:bg-(--bg-key)/80"
        >
          <ExternalLink size={13} aria-hidden="true" />
          {t('Open in app')}
        </button>
      )}
      {article.related && article.related.length > 0 && (
        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-(--color-text-muted)">
            {t('Related')}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {article.related.map((id) => {
              const related = getHelpArticle(id, locale)
              if (!related) return null
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => onOpenRelated(id)}
                  className="rounded-full border border-(--color-border) bg-(--bg-page) px-2.5 py-1 text-xs text-(--color-text-2) transition-colors hover:border-(--color-accent)/40 hover:text-(--color-text)"
                >
                  {related.title}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export function GuidelinesModal() {
  const { t } = useI18n()
  const locale = useLocale()
  const navigate = useNavigate()
  const topicId = useUIStore((state) => state.guidelinesTopicId)
  const closeGuidelines = useUIStore((state) => state.closeGuidelines)
  const openGuidelines = useUIStore((state) => state.openGuidelines)
  const openSettings = useUIStore((state) => state.openSettings)
  const openWorkbenchTool = useUIStore((state) => state.openWorkbenchTool)

  const [query, setQuery] = useState('')
  const [categoryId, setCategoryId] = useState<HelpCategoryId | null>(null)
  const [activeIdx, setActiveIdx] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const prefersReducedMotion = useReducedMotion()
  const preset = useMotionPreset()
  const isMobile = useIsMobile()
  const { isTauri, os } = usePlatform()
  const isTauriMobile = isMobile && isTauri && (os === 'ios' || os === 'android')

  const articles = useMemo(() => getHelpArticles(locale), [locale])
  const categories = useMemo(() => getHelpCategories(locale), [locale])

  useModalFocus(true, closeGuidelines)

  const selected = topicId ? getHelpArticle(topicId, locale) ?? null : null

  const list = useMemo(() => {
    const q = query.trim()
    if (q) return searchHelpArticles(articles, q).map((hit) => hit.article)
    return filterArticlesByCategory(articles, categoryId)
  }, [articles, query, categoryId])

  useEffect(() => {
    const timer = window.setTimeout(() => inputRef.current?.focus(), 0)
    return () => window.clearTimeout(timer)
  }, [])

  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${activeIdx}"]`) as HTMLElement | null
    el?.scrollIntoView?.({ block: 'nearest' })
  }, [activeIdx, list])

  const runOpenAction = (article: HelpArticle) => {
    const action = article.openAction
    if (!action) return
    closeGuidelines()
    if (action.type === 'settings') {
      openSettings(action.path)
      return
    }
    if (action.type === 'workbench') {
      openWorkbenchTool(action.tool)
      return
    }
    if (action.type === 'palette') {
      window.setTimeout(() => dispatchCtrlKey('p'), 0)
      return
    }
    void navigate({ to: action.to })
  }

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      if (selected && !query.trim()) {
        event.preventDefault()
        openGuidelines()
        return
      }
      closeGuidelines()
      return
    }
    if (selected) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIdx((index) => Math.min(index + 1, Math.max(list.length - 1, 0)))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIdx((index) => Math.max(index - 1, 0))
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      const article = list[activeIdx]
      if (article) openGuidelines(article.id)
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        key="guidelines-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className={cn(
          'fixed inset-0 z-(--z-modal) flex items-start justify-center bg-(--color-overlay) px-3 backdrop-blur-sm sm:px-4',
          isTauriMobile
            ? 'pt-[max(5rem,calc(env(safe-area-inset-top)+3.5rem))]'
            : 'pt-4 sm:pt-[8vh]',
        )}
        onClick={closeGuidelines}
      >
        <motion.div
          key="guidelines-panel"
          initial={
            prefersReducedMotion
              ? { opacity: 0 }
              : { opacity: 0, scale: 0.97, y: -8 * preset.distance }
          }
          animate={prefersReducedMotion ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
          exit={
            prefersReducedMotion
              ? { opacity: 0 }
              : { opacity: 0, scale: 0.97, y: -8 * preset.distance }
          }
          transition={reducedMotionTransition(Boolean(prefersReducedMotion), preset.spring)}
          onClick={(event) => event.stopPropagation()}
          className="flex h-[min(720px,calc(100dvh-env(safe-area-inset-top,0px)-env(safe-area-inset-bottom,0px)-2rem))] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card) shadow-2xl"
          role="dialog"
          aria-modal="true"
          aria-label={t('Guidelines')}
          data-modal-focus="true"
          data-testid="guidelines-modal"
          data-i18n-ignore="true"
          onKeyDown={handleKeyDown}
        >
          <div className="flex items-center gap-3 border-b border-(--color-border) px-4 py-3">
            <BookOpen size={15} className="shrink-0 text-(--color-accent)" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-(--color-text)">{t('Guidelines')}</p>
              <p className="truncate text-xs text-(--color-text-muted)">
                {t('Setup tips and tricks — search by keyword')}
              </p>
            </div>
            <button
              type="button"
              onClick={closeGuidelines}
              className="focus-ring-control flex size-8 items-center justify-center rounded-md text-(--color-text-muted) transition-colors hover:bg-(--bg-key) hover:text-(--color-text)"
              aria-label={t('Close')}
            >
              <X size={14} aria-hidden="true" />
            </button>
          </div>

          <div className="flex items-center gap-3 border-b border-(--color-border) px-4 py-2.5">
            <Search size={15} className="shrink-0 text-(--color-text-muted)" aria-hidden="true" />
            <input
              ref={inputRef}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value)
                setActiveIdx(0)
                if (selected) openGuidelines()
              }}
              placeholder={t('Search guidelines…')}
              className="flex-1 bg-transparent text-sm text-(--color-text) placeholder-(--color-text-muted) outline-none"
              aria-label={t('Search guidelines')}
              data-testid="guidelines-search"
            />
            {query && (
              <button
                type="button"
                onClick={() => {
                  setQuery('')
                  setActiveIdx(0)
                }}
                className="text-xs text-(--color-text-muted) hover:text-(--color-text-2)"
              >
                {t('Clear')}
              </button>
            )}
          </div>

          <div className="flex min-h-0 flex-1">
            {!isMobile && (
              <nav
                className="hidden w-48 shrink-0 overflow-y-auto border-r border-(--color-border) py-2 md:block"
                aria-label={t('Categories')}
              >
                <button
                  type="button"
                  onClick={() => {
                    setCategoryId(null)
                    setActiveIdx(0)
                    openGuidelines()
                  }}
                  className={cn(
                    'mx-2 flex w-[calc(100%-1rem)] rounded-lg px-2.5 py-2 text-left text-xs font-medium transition-colors',
                    !categoryId && !selected
                      ? 'bg-(--color-accent-soft) text-(--color-text)'
                      : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                  )}
                >
                  {t('All topics')}
                </button>
                {categories.map((category) => (
                  <button
                    key={category.id}
                    type="button"
                    onClick={() => {
                      setCategoryId(category.id)
                      setQuery('')
                      setActiveIdx(0)
                      openGuidelines()
                    }}
                    className={cn(
                      'mx-2 flex w-[calc(100%-1rem)] flex-col rounded-lg px-2.5 py-2 text-left transition-colors',
                      categoryId === category.id && !selected
                        ? 'bg-(--color-accent-soft) text-(--color-text)'
                        : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)',
                    )}
                  >
                    <span className="text-xs font-medium">{category.label}</span>
                  </button>
                ))}
              </nav>
            )}

            <div className="flex min-w-0 flex-1 flex-col">
              {selected ? (
                <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
                  <button
                    type="button"
                    onClick={() => openGuidelines()}
                    className="mb-3 inline-flex items-center gap-1 text-xs font-medium text-(--color-text-muted) transition-colors hover:text-(--color-text)"
                  >
                    <ArrowLeft size={12} aria-hidden="true" />
                    {t('Back to list')}
                  </button>
                  <ArticleBody
                    article={selected}
                    locale={locale}
                    onOpenRelated={(id) => openGuidelines(id)}
                    onOpenAction={() => runOpenAction(selected)}
                  />
                </div>
              ) : (
                <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto py-1.5">
                  {list.length === 0 ? (
                    <p className="px-4 py-8 text-center text-sm text-(--color-text-muted)">
                      {t('No guidelines match')} “{query}”
                    </p>
                  ) : (
                    list.map((article, index) => {
                      const active = index === activeIdx
                      return (
                        <button
                          key={article.id}
                          type="button"
                          data-idx={index}
                          data-testid={`guidelines-article-${article.id}`}
                          onClick={() => openGuidelines(article.id)}
                          onMouseEnter={() => setActiveIdx(index)}
                          className={cn(
                            'flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors',
                            active
                              ? 'bg-(--bg-key) text-(--color-text)'
                              : 'text-(--color-text-2) hover:bg-(--bg-key)',
                          )}
                        >
                          <div className="min-w-0 flex-1">
                            <span className="block text-sm font-medium">{article.title}</span>
                            <span className="mt-0.5 block truncate text-xs text-(--color-text-muted)">
                              {article.summary}
                            </span>
                          </div>
                          {active && (
                            <CornerDownLeft
                              size={12}
                              className="mt-1 shrink-0 text-(--color-text-muted)"
                              aria-hidden="true"
                            />
                          )}
                        </button>
                      )
                    })
                  )}
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2 border-t border-(--color-border) px-4 py-2">
                <kbd className="rounded-xs border border-(--color-border) bg-(--bg-page) px-1 py-0.5 font-mono text-xs text-(--color-text-muted)">
                  ↑↓
                </kbd>
                <span className="text-xs text-(--color-text-muted)">{t('navigate')}</span>
                <kbd className="rounded-xs border border-(--color-border) bg-(--bg-page) px-1 py-0.5 font-mono text-xs text-(--color-text-muted)">
                  ↵
                </kbd>
                <span className="text-xs text-(--color-text-muted)">{t('open')}</span>
                <kbd className="rounded-xs border border-(--color-border) bg-(--bg-page) px-1 py-0.5 font-mono text-xs text-(--color-text-muted)">
                  Esc
                </kbd>
                <span className="text-xs text-(--color-text-muted)">{t('close')}</span>
                <button
                  type="button"
                  onClick={() => {
                    closeGuidelines()
                    window.setTimeout(() => dispatchCtrlKey('p'), 0)
                  }}
                  className="ml-auto text-xs font-medium text-(--color-accent) hover:underline"
                >
                  {t('Open command palette')} (Ctrl+P)
                </button>
              </div>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
