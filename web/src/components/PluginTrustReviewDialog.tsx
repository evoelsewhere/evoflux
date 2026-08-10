import { Braces, KeyRound, Network, ShieldCheck, TerminalSquare } from 'lucide-react'

import type { PluginTrustReview } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

function EmptyDisclosure() {
  return <p className="text-xs text-(--color-text-subtle)">None declared</p>
}

export function PluginTrustReviewDialog({
  pluginName,
  review,
  busy,
  onCancel,
  onConfirm,
}: {
  pluginName: string | null
  review: PluginTrustReview | null
  busy: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <Dialog
      open={review !== null}
      onOpenChange={(open) => {
        if (!open && !busy) onCancel()
      }}
    >
      <DialogContent showCloseButton={false} className="max-w-xl gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-(--color-border) px-5 py-4">
          <div className="flex items-center gap-2">
            <ShieldCheck size={19} className="text-(--color-warning)" />
            <DialogTitle>Review before enabling {pluginName}</DialogTitle>
          </div>
          <DialogDescription>
            Enabling starts declared MCP processes and makes plugin Skills available. Verify this package and its access first.
          </DialogDescription>
        </DialogHeader>

        {review && (
          <div className="grid max-h-[60vh] gap-4 overflow-y-auto p-5 sm:grid-cols-2">
            <section className="rounded-lg border border-(--color-border) bg-(--bg-page) p-3">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-(--color-text)">
                <TerminalSquare size={15} /> Executable commands
              </h3>
              {review.executable_commands.length ? (
                <div className="space-y-2">
                  {review.executable_commands.map((command) => (
                    <div key={command.server}>
                      <p className="text-xs text-(--color-text-muted)">{command.server}</p>
                      <code className="mt-1 block break-all rounded bg-(--bg-key) p-2 text-[11px] text-(--color-text)">
                        {[command.executable, ...command.args].map((value) => JSON.stringify(value)).join(' ')}
                      </code>
                    </div>
                  ))}
                </div>
              ) : <EmptyDisclosure />}
            </section>

            <section className="rounded-lg border border-(--color-border) bg-(--bg-page) p-3">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-(--color-text)">
                <Network size={15} /> Remote hosts
              </h3>
              {review.remote_hosts.length ? (
                <div className="space-y-2">
                  {review.remote_hosts.map((remote) => (
                    <div key={`${remote.server}:${remote.url}`}>
                      <p className="break-all font-mono text-xs text-(--color-text)">{remote.host}</p>
                      <p className="break-all text-[11px] text-(--color-text-subtle)">{remote.server} · {remote.transport} · {remote.url}</p>
                    </div>
                  ))}
                </div>
              ) : <EmptyDisclosure />}
            </section>

            <section className="rounded-lg border border-(--color-border) bg-(--bg-page) p-3">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-(--color-text)">
                <KeyRound size={15} /> Environment fields
              </h3>
              {review.environment_fields.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {review.environment_fields.map((field) => (
                    <code key={field} className="rounded bg-(--bg-key) px-2 py-1 text-[11px] text-(--color-text)">{field}</code>
                  ))}
                </div>
              ) : <EmptyDisclosure />}
              <p className="mt-2 text-[11px] text-(--color-text-subtle)">Only field names are shown; values and secrets are never disclosed here.</p>
            </section>

            <section className="rounded-lg border border-(--color-border) bg-(--bg-page) p-3">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-(--color-text)">
                <Braces size={15} /> Capabilities
              </h3>
              {review.capabilities.length ? (
                <div className="space-y-1">
                  {review.capabilities.map((capability, index) => (
                    <p key={`${capability.source}:${capability.name}:${index}`} className="text-xs text-(--color-text)">
                      <code>{capability.name}</code> <span className="text-(--color-text-subtle)">from {capability.source}</span>
                    </p>
                  ))}
                </div>
              ) : <EmptyDisclosure />}
            </section>
          </div>
        )}

        <DialogFooter className="m-0 px-5 py-4">
          <Button type="button" variant="outline" disabled={busy} onClick={onCancel}>Keep disabled</Button>
          <Button type="button" disabled={busy} onClick={onConfirm}>Trust and enable</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
