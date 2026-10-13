import type { UiTableBlock } from './ui-block-types'

/** Server shape: `columns` is a list of key → header-label mappings. */
function columnEntries(columns: Record<string, string>[]): [string, string][] {
  return columns.flatMap((column) =>
    Object.entries(column).map(([key, label]) => [key, label] as [string, string]),
  )
}

export function UiTable({ block }: { block: UiTableBlock }) {
  const entries = columnEntries(block.columns)
  return (
    <div className="overflow-x-auto rounded-md border border-(--color-border)">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-(--color-border) bg-(--bg-key)">
            {entries.map(([key, label]) => (
              <th key={key} scope="col" className="px-3 py-1.5 text-left font-medium">
                {label || key}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, i) => (
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
  )
}
