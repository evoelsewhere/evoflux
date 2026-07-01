import { Activity, BarChart3, List } from 'lucide-react'

export type TelemetryTab = 'summary' | 'traces'

const NAV_ITEMS: { id: TelemetryTab; label: string; icon: React.ComponentType<{ size?: number; className?: string }> }[] = [
  { id: 'summary', label: 'Summary', icon: BarChart3 },
  { id: 'traces', label: 'Traces', icon: List },
]

export function TelemetrySidebar({
  active,
  onSelect,
}: {
  active: TelemetryTab
  onSelect: (tab: TelemetryTab) => void
}) {
  return (
    <aside className="hidden w-56 shrink-0 border-r border-(--color-border) bg-(--bg-sidebar) md:flex md:flex-col">
      <div className="flex items-center gap-2 px-4 py-3">
        <Activity size={16} className="text-(--color-accent)" />
        <span className="text-sm font-semibold text-(--color-text)">Telemetry</span>
      </div>
      <nav className="flex-1 overflow-y-auto px-2 pb-4">
        <ul className="flex flex-col gap-0.5">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon
            const isActive = active === item.id
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onSelect(item.id)}
                  className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                    isActive
                      ? 'bg-(--bg-key) font-medium text-(--color-text)'
                      : 'text-(--color-text-muted) hover:bg-(--bg-key) hover:text-(--color-text)'
                  }`}
                >
                  <Icon size={15} className={isActive ? 'text-(--color-accent)' : ''} />
                  {item.label}
                </button>
              </li>
            )
          })}
        </ul>
      </nav>
    </aside>
  )
}
