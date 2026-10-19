import { Braces, KeyRound, Network, ShieldCheck, TerminalSquare, Webhook } from 'lucide-react'

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

function readableHookEvent(event: string): string {
  const labels: Record<string, string> = {
    'session.start': 'When a new session starts',
    'session.end': 'When a session ends',
    'prompt.submit': 'When you send a message',
    'agent.start': 'When an agent starts',
    'agent.stop': 'When an agent finishes',
    'model.before': 'Before the agent asks a model',
    'model.after': 'After the model responds',
    'tool.before': 'Before a tool runs',
    'tool.after': 'After a tool finishes',
    'completion.before': 'Before the agent completes a turn',
    'compact.before': 'Before conversation context is shortened',
    'compact.after': 'After conversation context is shortened',
    'subagent.start': 'When a subagent starts',
    'subagent.stop': 'When a subagent finishes',
  }
  return labels[event] ?? `When ${event.replaceAll('.', ' ')}`
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
  const hasMcpAccess = Boolean(review && (
    review.executable_commands.length > 0
    || review.remote_hosts.length > 0
    || review.capabilities.some((capability) => capability.name.startsWith('mcp-'))
  ))

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
            Enabling starts declared MCP processes and makes plugin Skills available. Command hooks need digest review and verified OS isolation. Static context hooks only read one approved package file and add it as untrusted session context.
          </DialogDescription>
        </DialogHeader>

        {review && (
          <div className="grid max-h-[60vh] gap-4 overflow-y-auto p-5 sm:grid-cols-2">
            <section className="rounded-lg border border-(--color-border) bg-(--bg-page) p-3">
              <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-(--color-text)">
                <Webhook size={15} /> Agent hooks
              </h3>
              {(review.hooks ?? []).length ? (
                <div className="space-y-3">
                  {(review.hooks ?? []).map((hook) => (
                    <div key={`${hook.hook_id}:${hook.digest ?? 'invalid'}`} className="space-y-1.5">
                      <p className="text-xs font-semibold text-(--color-text)">
                        {readableHookEvent(hook.event)}
                        {!hook.valid && <span className="ml-2 text-(--color-error)">Needs attention</span>}
                      </p>
                      <p className="text-xs text-(--color-text-muted)">
                        {hook.execution_kind === 'static_context'
                          ? 'Adds this plugin’s guidance to the session. It does not run code.'
                          : 'Runs this plugin’s command at this moment.'}
                      </p>
                      <details className="rounded-md border border-(--color-border) px-2.5 py-2 text-[10px]">
                        <summary className="cursor-pointer font-medium text-(--color-text-muted)">Technical details</summary>
                        <div className="mt-2 space-y-1.5">
                          <p><code>{hook.hook_id}</code> · <code>{hook.event}</code></p>
                          <p>Runtime: <code>{hook.runtime}</code> · Declared files: {hook.files.join(', ') || 'entrypoint only'}</p>
                          <code className="block break-all rounded bg-(--bg-key) p-2 text-(--color-text)">
                            {hook.execution_kind === 'static_context'
                              ? `Static context file: ${hook.command_path || 'unresolved'}`
                              : hook.command.map((value) => JSON.stringify(value)).join(' ')}
                          </code>
                          {hook.execution_kind === 'static_context' && hook.context_prefix && <p className="break-all">Context wrapper: {JSON.stringify(hook.context_prefix)}…{JSON.stringify(hook.context_suffix)}</p>}
                          <p className="break-all">Package path: {hook.command_path || 'unresolved'} · Digest: {hook.digest ?? 'unavailable'}</p>
                          <p>Inputs: {hook.input_fields.join(', ') || 'none'} · Outputs: {hook.output_fields.join(', ') || 'none'}</p>
                          <p className="break-all">Matcher: {hook.matcher ? JSON.stringify(hook.matcher) : 'none'} · Timeout: {hook.timeout_seconds} seconds · Failure policy: {hook.failure_policy}</p>
                          <p className="break-all">Environment: {hook.environment_fields.join(', ') || 'none'} · Isolation profile: {hook.isolation_profile}</p>
                        </div>
                      </details>
                    </div>
                  ))}
                </div>
              ) : <EmptyDisclosure />}
              <p className="mt-2 text-[11px] text-(--color-text-subtle)">Enabling the plugin does not approve its hooks. Hook approval is a separate choice in Agent hooks. Commands run only when the host verifies isolation.</p>
            </section>

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
          <Button type="button" disabled={busy} onClick={onConfirm}>
            {hasMcpAccess ? 'Trust MCP access and enable' : 'Enable plugin'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
