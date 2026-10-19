import { Children, cloneElement, isValidElement, useState } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'

import { Input } from '@/components/ui/input'

// ── MarkdownTable ─────────────────────────────────────────────────────────────
//
// Interactive markdown table (Intelligent UI tier-3 upgrade).
//
// react-markdown renders ``<table>`` through this override so large, settled
// tables gain sortable headers (numeric-aware comparison) and — from ten body
// rows up — a quick filter, all inside the existing ``.oa-prose`` table tokens
// (border, header background, contained horizontal scroll).
//
// Anything this parser does not recognise, any table still streaming, and any
// table below the thresholds (6 body rows / 3 columns) falls straight through
// to the plain ``<table>`` output react-markdown would have produced —
// unwrapped, so the ``.oa-streaming-prose > table:last-child`` cursor selector
// keeps matching while streaming.

const MIN_SORTABLE_BODY_ROWS = 6
const MIN_SORTABLE_COLUMNS = 3
const FILTER_MIN_BODY_ROWS = 10

type SortState = { column: number; direction: 'asc' | 'desc' }

type HeaderCell = ReactElement<React.ThHTMLAttributes<HTMLTableCellElement>>
type RowElement = ReactElement<React.HTMLAttributes<HTMLTableRowElement>>

interface ParsedRow {
  element: RowElement
  cells: string[]
}

interface ParsedTable {
  thead: ReactElement
  tbody: ReactElement
  headerRow: RowElement
  headerCells: HeaderCell[]
  rows: ParsedRow[]
}

export interface MarkdownTableProps
  extends React.TableHTMLAttributes<HTMLTableElement> {
  /** react-markdown's hast node — never reaches the DOM. */
  node?: unknown
  /** True while the message streams — interactive affordances stay off. */
  streaming?: boolean
}

function isElement(node: ReactNode): node is ReactElement {
  return isValidElement(node)
}

function childrenOf(element: ReactElement): ReactNode {
  return (element.props as { children?: ReactNode }).children ?? []
}

function elementChildren(element: ReactElement): ReactElement[] {
  return Children.toArray(childrenOf(element)).filter(isElement)
}

/** Plain-text form of a rendered cell — links, emphasis and code collapse to their text. */
function cellText(node: ReactNode): string {
  if (typeof node === 'string') return node
  if (Array.isArray(node)) return node.map(cellText).join('')
  if (isElement(node)) return cellText(childrenOf(node))
  return ''
}

/** GFM ``:---:`` alignment reaches the cell as ``align`` or ``style.textAlign``. */
function textAlignOf(cell: ReactElement): 'center' | 'right' | 'left' {
  const props = cell.props as {
    align?: string
    style?: { textAlign?: string }
  }
  const align = props.align ?? props.style?.textAlign
  if (align === 'center') return 'center'
  if (align === 'right') return 'right'
  return 'left'
}

/**
 * Derive header/body structure from react-markdown's rendered children.
 * Returns ``null`` for anything but a well-formed single-header-row table —
 * the caller then renders the plain default markup.
 */
function parseTable(children: ReactNode): ParsedTable | null {
  const parts = Children.toArray(children).filter(isElement)
  const thead = parts.find((element) => element.type === 'thead')
  const tbody = parts.find((element) => element.type === 'tbody')
  if (!thead || !tbody) return null

  const headerRows = elementChildren(thead).filter(
    (element) => element.type === 'tr',
  )
  // Multi-row raw-HTML headers are beyond the interactive scope — stay plain.
  if (headerRows.length !== 1) return null
  const headerRow = headerRows[0] as RowElement

  const headerCells = elementChildren(headerRow) as HeaderCell[]
  const rows = elementChildren(tbody)
    .filter((element) => element.type === 'tr')
    .map<ParsedRow>((element) => ({
      element: element as RowElement,
      cells: elementChildren(element).map((cell) => cellText(childrenOf(cell))),
    }))
  if (headerCells.length === 0 || rows.length === 0) return null

  return { thead, tbody, headerRow, headerCells, rows }
}

/** ``"1,230"``/``"$9.5"``/``"90%"`` → numbers; anything else → ``null``. */
function toNumber(text: string): number | null {
  const normalized = text.trim().replace(/[$%\s,]/g, '')
  if (normalized === '' || !/^-?\d+(\.\d+)?$/.test(normalized)) return null
  return Number(normalized)
}

/**
 * A column sorts numerically only when every non-empty cell parses, so the
 * comparator stays transitive for mixed columns ("7", "n/a").
 */
function isNumericColumn(rows: ParsedRow[], column: number): boolean {
  return rows.every((row) => {
    const text = row.cells[column] ?? ''
    return text.trim() === '' || toNumber(text) !== null
  })
}

function compareCells(a: string, b: string, numeric: boolean): number {
  if (numeric) {
    const na = toNumber(a)
    const nb = toNumber(b)
    if (na !== null && nb !== null) return na === nb ? 0 : na < nb ? -1 : 1
  }
  // Case-insensitive text — a numeric column never reaches this branch, so
  // ``9`` only sorts after ``10`` when the column is genuinely non-numeric.
  return a.trim().toLowerCase().localeCompare(b.trim().toLowerCase())
}

function toggleSortState(previous: SortState | null, column: number): SortState {
  if (previous && previous.column === column) {
    return { column, direction: previous.direction === 'asc' ? 'desc' : 'asc' }
  }
  return { column, direction: 'asc' }
}

const JUSTIFY_BY_ALIGNMENT = {
  center: 'justify-center',
  right: 'justify-end',
  left: 'justify-start',
} as const

export default function MarkdownTable({
  node: _node,
  streaming = false,
  children,
  ...rest
}: MarkdownTableProps) {
  const [sort, setSort] = useState<SortState | null>(null)
  const [filter, setFilter] = useState('')

  const parsed = parseTable(children)
  const interactive =
    parsed !== null &&
    !streaming &&
    parsed.rows.length >= MIN_SORTABLE_BODY_ROWS &&
    parsed.headerCells.length >= MIN_SORTABLE_COLUMNS

  // Plain fallback — byte-identical to react-markdown's default output, and
  // unwrapped so the streaming cursor CSS keeps matching during generation.
  if (!interactive || !parsed) {
    return <table {...rest}>{children}</table>
  }

  const { thead, tbody, headerRow, headerCells, rows } = parsed
  const activeSort = sort && sort.column < headerCells.length ? sort : null
  const query = filter.trim().toLowerCase()
  const visibleRows = query
    ? rows.filter((row) =>
        row.cells.some((text) => text.toLowerCase().includes(query)),
      )
    : rows

  const orderedRows = (() => {
    if (!activeSort) return visibleRows
    const { column, direction } = activeSort
    const numeric = isNumericColumn(rows, column)
    const factor = direction === 'asc' ? 1 : -1
    return [...visibleRows].sort(
      (a, b) =>
        factor * compareCells(a.cells[column] ?? '', b.cells[column] ?? '', numeric),
    )
  })()

  const ariaSortFor = (column: number): 'ascending' | 'descending' | 'none' => {
    if (!activeSort || activeSort.column !== column) return 'none'
    return activeSort.direction === 'asc' ? 'ascending' : 'descending'
  }

  const sortableHeaderCells = headerCells.map((cell, column) => {
    const ariaSort = ariaSortFor(column)
    // Full-cell click target that still honours ``:---:`` column alignment.
    const justify = JUSTIFY_BY_ALIGNMENT[textAlignOf(cell)]
    return cloneElement(
      cell,
      { 'aria-sort': ariaSort },
      <button
        type="button"
        onClick={() => setSort((previous) => toggleSortState(previous, column))}
        aria-sort={ariaSort}
        className={`group flex w-full cursor-pointer items-center gap-1 ${justify} transition-colors hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--focus-ring)`}
      >
        {cell.props.children}
        <span aria-hidden="true" className="shrink-0">
          {activeSort?.column === column ? (
            activeSort.direction === 'asc' ? (
              <ArrowUp size={12} />
            ) : (
              <ArrowDown size={12} />
            )
          ) : (
            <ChevronsUpDown size={12} className="opacity-40 group-hover:opacity-100" />
          )}
        </span>
      </button>,
    )
  })

  return (
    <div className="max-w-full">
      {rows.length >= FILTER_MIN_BODY_ROWS && (
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
      <div className="max-w-full overflow-x-auto">
        <table {...rest}>
          {cloneElement(
            thead,
            undefined,
            cloneElement(headerRow, undefined, sortableHeaderCells),
          )}
          {cloneElement(
            tbody,
            undefined,
            orderedRows.length === 0 ? (
              <tr>
                <td colSpan={headerCells.length} className="text-(--color-text-muted)">
                  No matches
                </td>
              </tr>
            ) : (
              orderedRows.map((row) => row.element)
            ),
          )}
        </table>
      </div>
    </div>
  )
}
