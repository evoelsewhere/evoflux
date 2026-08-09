/**
 * /settings/mcp — inline list of MCP servers in the detail pane.
 */
import { AlertCircle, Plug } from 'lucide-react'
import { useMemo } from 'react'

import { type ServerStatus } from '@/api/client'
import { SettingsListView, type ListViewRow } from '@/components/settings/SettingsListView'
import { cn } from '@/lib/utils'
import { useMcpServersQuery } from '@/queries'
import { useSettingsParams } from '@/contexts/SettingsContext'

const STATE_COLOR: Record<ServerStatus['state'], string> = {
  ready: 'bg-(--accent-green)',
  starting: 'bg-(--accent-orange)',
  auth_required: 'bg-(--accent-orange)',
  error: 'bg-(--color-error)',
  stopped: 'bg-(--color-text-muted)/40',
}

function StatusDot({ server }: { server: ServerStatus }) {
  if (server.state === 'error') {
    return (
      <span
        className="flex shrink-0 items-center text-(--color-error)"
        title={server.error ?? 'Server failed to start'}
        aria-label={`Error: ${server.error ?? 'unknown'}`}
      >
        <AlertCircle size={13} />
      </span>
    )
  }
  return (
    <span
      className={cn('h-2 w-2 shrink-0 rounded-full', STATE_COLOR[server.state])}
      title={server.state}
      aria-label={`State: ${server.state}`}
    />
  )
}

export function McpListPage() {
  const { data, isLoading, isFetching, isError, error, refetch } = useMcpServersQuery()
  const { name: selected } = useSettingsParams() as { name?: string }

  const rows = useMemo<ListViewRow[]>(
    () =>
      (data?.servers ?? []).map((srv): ListViewRow => ({
        key: srv.name,
        to: '/settings/mcp/$name',
        params: { name: srv.name },
        active: selected === srv.name,
        title: srv.source === 'plugin'
          ? `${srv.plugin_name ?? 'plugin'} / ${srv.plugin_server_name ?? srv.name}`
          : srv.name,
        badge: srv.source === 'plugin' ? 'plugin' : srv.enabled ? undefined : 'disabled',
        description: `${srv.transport === 'stdio' ? 'Local stdio process' : 'HTTP server'} · ${srv.tool_names.length} ${srv.tool_names.length === 1 ? 'tool' : 'tools'}${srv.source === 'plugin' ? ` · runtime ${srv.name}` : ''}`,
        trailing: (
          <div className="flex items-center gap-2">
            <StatusDot server={srv} />
            <span
              className="flex h-7 w-7 items-center justify-center rounded-md bg-(--bg-key) text-(--color-text-muted) ring-1 ring-(--color-border)"
              aria-hidden="true"
            >
              <Plug size={13} />
            </span>
          </div>
        ),
      })),
    [data?.servers, selected],
  )

  return (
    <SettingsListView
      title="MCP servers"
      icon={Plug}
      lede="External tool providers over Model Context Protocol. Stdio servers run locally as a child process, HTTP servers are remote."
      newTo="/settings/mcp/new"
      newLabel="New server"
      filterPlaceholder="Filter servers…"
      rows={rows}
      isLoading={isLoading}
      isFetching={isFetching}
      isError={isError}
      error={error}
      onRetry={() => void refetch()}
      emptyTitle="No MCP servers yet"
      emptyBody="MCP servers expose tools and resources to your agents over stdio or HTTP."
    />
  )
}
