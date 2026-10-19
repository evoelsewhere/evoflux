import { useState } from 'react'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { Input } from '@/components/ui/input'
import type { UiTableBlock } from './ui-block-types'

/** Server shape: `columns` is a list of key → header-label mappings. */
function columnEntries(columns: Record<string, string>[]): [string, string][] {
  return columns.flatMap((column) =>
    Object.entries(column).map(([key, label]) => [key, label] as [string, string]),
  )
}

export function UiTable({ block }: { block: UiTableBlock }) {
  const entries = columnEntries(block.columns)
  const [sort, setSort] = useState<{ key: string; direction: 'asc' | 'desc' } | null>(null)
  const [filter, setFilter] = useState('')
  const query = filter.trim().toLocaleLowerCase()
  const visibleRows = query
    ? block.rows.filter((row) =>
        entries.some(([key]) => String(row[key] ?? '').toLocaleLowerCase().includes(query)),
      )
    : block.rows
  const orderedRows = (() => {
    if (!sort) return visibleRows
    const nonEmpty = block.rows
      .map((row) => String(row[sort.key] ?? '').trim())
      .filter(Boolean)
    const numeric = nonEmpty.length > 0 && nonEmpty.every((value) => {
      const normalized = value.replace(/[$%\s,]/g, '')
      return /^-?\d+(\.\d+)?$/.test(normalized) && Number.isFinite(Number(normalized))
    })
    const factor = sort.direction === 'asc' ? 1 : -1
    return [...visibleRows].sort((left, right) => {
      const a = String(left[sort.key] ?? '').trim()
      const b = String(right[sort.key] ?? '').trim()
      const comparison = numeric
        ? Number(a.replace(/[$%\s,]/g, '')) - Number(b.replace(/[$%\s,]/g, ''))
        : a.toLocaleLowerCase().localeCompare(b.toLocaleLowerCase())
      return factor * comparison
    })
  })()

  return (
    <div className="max-w-full">
      {block.rows.length >= 10 && (
        <div className="mb-1.5 flex items-center gap-1.5">
          <Input
            type="text"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter rows…"
            aria-label="Filter table rows"
            className="h-7 w-44 text-xs md:h-7"
          />
        </div>
      )}
      <div className="max-w-full overflow-x-auto rounded-md border border-(--color-border)">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-(--color-border) bg-(--bg-key)">
              {entries.map(([key, label]) => {
                const direction = sort?.key === key ? sort.direction : null
                const ariaSort = direction === 'asc'
                  ? 'ascending'
                  : direction === 'desc'
                    ? 'descending'
                    : 'none'
                return (
                  <th
                    key={key}
                    scope="col"
                    aria-sort={ariaSort}
                    className="px-3 py-1.5 text-left font-medium"
                  >
                    <button
                      type="button"
                      aria-sort={ariaSort}
                      onClick={() => setSort((previous) => ({
                        key,
                        direction: previous?.key === key && previous.direction === 'asc'
                          ? 'desc'
                          : 'asc',
                      }))}
                      className="group flex w-full cursor-pointer items-center gap-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)"
                    >
                      {label || key}
                      <span aria-hidden="true" className="shrink-0">
                        {direction === 'asc' ? <ArrowUp size={12} /> : direction === 'desc' ? <ArrowDown size={12} /> : <ChevronsUpDown size={12} className="opacity-40 group-hover:opacity-100" />}
                      </span>
                    </button>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {orderedRows.length === 0 ? (
              <tr>
                <td colSpan={entries.length} className="px-3 py-1.5 text-(--color-text-muted)">
                  No matches
                </td>
              </tr>
            ) : orderedRows.map((row, i) => (
              <tr key={i} className="border-b border-(--color-border) last:border-0">
                {entries.map(([key]) => (
                  <td key={key} className="px-3 py-1.5 align-top">
                    {String(row[key] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
