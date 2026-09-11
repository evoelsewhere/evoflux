/**
 * Empty-state launcher for the browser pane.
 *
 * The new-tab page is the natural place to start the app you are about to
 * verify, so it lists the workspace's launch.json entries instead of an
 * inert "start browsing" card. It reads the same registry the agent's
 * `preview` tool uses: a row already serving shows as running — whoever
 * started it — and opens instead of spawning a second copy.
 */

import { useCallback, useState } from 'react'
import { CircleStop, Loader2, Play, Server, SquareArrowOutUpRight } from 'lucide-react'

import type { PreviewTarget } from '@/api/types'
import { cn } from '@/lib/utils'
import {
  usePreviewStartMutation,
  usePreviewStopMutation,
  usePreviewTargetsQuery,
} from '@/queries/usePreviewTargetsQuery'

interface BrowserLauncherProps {
  workspace: string
  /** Stop polling while the workbench tab is in the background. */
  paused?: boolean
  onOpen: (url: string) => void
}

export function BrowserLauncher({ workspace, paused = false, onOpen }: BrowserLauncherProps) {
  const targets = usePreviewTargetsQuery(workspace, !paused)
  const start = usePreviewStartMutation(workspace)
  const stop = usePreviewStopMutation(workspace)
  const [busy, setBusy] = useState<string | null>(null)
  const [failure, setFailure] = useState<{ name: string; message: string } | null>(null)

  const data = targets.data
  const rows = data?.targets ?? []
  const source = data?.source ?? null

  const handleStart = useCallback(async (target: PreviewTarget) => {
    if (target.running) {
      onOpen(target.url)
      return
    }
    setBusy(target.name)
    setFailure(null)
    try {
      const result = await start.mutateAsync(target.name)
      // A start that reused an existing server reports no fresh URL; the
      // configured one is still the right place to go.
      if (result.ok) onOpen(result.url ?? target.url)
      else setFailure({ name: target.name, message: result.message })
    } catch (error) {
      setFailure({
        name: target.name,
        message: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(null)
    }
  }, [onOpen, start])

  const handleStop = useCallback(async (target: PreviewTarget) => {
    setBusy(target.name)
    setFailure(null)
    try {
      await stop.mutateAsync(target.name)
    } catch (error) {
      setFailure({
        name: target.name,
        message: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(null)
    }
  }, [stop])

  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 overflow-auto bg-(--bg-page) px-6 py-8">
      {rows.length > 0 && (
        <ul className="w-full max-w-sm overflow-hidden rounded-xl border border-(--color-border) bg-(--bg-card) shadow-sm">
          {rows.map((target) => (
            <LauncherRow
              key={target.name}
              target={target}
              busy={busy === target.name}
              disabled={busy !== null && busy !== target.name}
              onStart={() => void handleStart(target)}
              onStop={() => void handleStop(target)}
            />
          ))}
        </ul>
      )}

      {failure && (
        <pre className="max-h-40 w-full max-w-sm overflow-auto whitespace-pre-wrap rounded-lg border border-(--color-error)/30 bg-(--color-error)/5 p-2.5 font-mono text-[10px] leading-4 text-(--color-text-muted)">
          {failure.message}
        </pre>
      )}

      {data?.error && (
        <p className="max-w-sm text-center text-xs leading-5 text-(--color-error)">
          {data.error}
        </p>
      )}

      <p className="max-w-sm text-center text-xs leading-5 text-(--color-text-muted)">
        {rows.length > 0
          ? 'Run a server to preview your app, or enter a URL.'
          : 'Enter a URL in the address bar, or declare a dev server to run from here.'}
        <br />
        <span className="text-(--color-text-subtle)">
          {source
            ? `Edit this list in ${shortenSource(source, data?.workspace ?? workspace)}.`
            : `Create ${data?.suggested_source ?? '.evoflux/launch.json'} to list your dev servers.`}
        </span>
      </p>
    </div>
  )
}

function LauncherRow({
  target,
  busy,
  disabled,
  onStart,
  onStop,
}: {
  target: PreviewTarget
  busy: boolean
  disabled: boolean
  onStart: () => void
  onStop: () => void
}) {
  // An external server is not ours to stop — the tool only untracks it, which
  // would read as a broken button here.
  const stoppable = target.running && !target.reused
  const actionLabel = busy
    ? `Starting ${target.name}`
    : target.running
      ? `Open ${target.name}`
      : `Start ${target.name}`
  return (
    <li className="group flex items-center gap-2.5 border-b border-(--color-border) px-3 py-2 last:border-b-0">
      <span className="relative flex size-5 shrink-0 items-center justify-center text-(--color-text-muted)">
        <Server size={14} />
        {target.running && (
          <span
            className="absolute -bottom-0.5 -right-0.5 size-1.5 rounded-full bg-(--color-success) ring-2 ring-(--bg-card)"
            aria-hidden="true"
          />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-medium text-(--color-text)">
          {target.name}
          {!target.configured && (
            <span className="ml-1.5 text-[10px] font-normal text-(--color-text-subtle)">
              (not in launch.json)
            </span>
          )}
        </span>
        {target.running && target.reused && (
          <span className="block truncate text-[10px] leading-4 text-(--color-text-subtle)">
            already running outside EvoFlux
          </span>
        )}
      </span>
      <span className="shrink-0 font-mono text-[11px] tabular-nums text-(--color-text-muted)">
        :{target.port}
      </span>
      {stoppable && (
        <button
          type="button"
          onClick={onStop}
          disabled={busy || disabled}
          className="flex size-6 shrink-0 items-center justify-center rounded-md text-(--color-text-muted) opacity-0 transition-opacity hover:bg-(--bg-key) hover:text-(--color-error) focus-visible:opacity-100 disabled:opacity-40 group-hover:opacity-100"
          aria-label={`Stop ${target.name}`}
          title={`Stop ${target.name}`}
        >
          <CircleStop size={14} />
        </button>
      )}
      <button
        type="button"
        onClick={onStart}
        disabled={busy || disabled}
        className={cn(
          'flex h-6 w-7 shrink-0 items-center justify-center rounded-md border border-(--color-border) text-(--color-text-muted) transition-colors hover:border-(--color-border-strong) hover:bg-(--bg-key) hover:text-(--color-text) disabled:opacity-40',
          target.running && 'border-transparent bg-(--color-success)/10 text-(--color-success)',
        )}
        aria-label={actionLabel}
        title={actionLabel}
      >
        {busy
          ? <Loader2 size={13} className="animate-spin" />
          : target.running
            ? <SquareArrowOutUpRight size={13} />
            : <Play size={13} />}
      </button>
    </li>
  )
}

/** Show the config path relative to the workspace it belongs to. */
function shortenSource(source: string, workspace: string): string {
  const sep = '\\'
  const normalized = source.split(sep).join('/')
  const root = workspace.split(sep).join('/').replace(/[/]$/, '')
  return normalized.startsWith(`${root}/`)
    ? normalized.slice(root.length + 1)
    : normalized
}
