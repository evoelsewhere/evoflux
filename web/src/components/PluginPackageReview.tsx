import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  getPluginPackageFile,
  getPluginPackageReview,
  revokePluginHookTrust,
  trustPluginHook,
} from '@/api/client'
import type { PluginInspection } from '@/api/types'
import { queryKeys } from '@/queries/keys'

const codeClass = 'max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-(--color-border) bg-(--bg-surface) p-3 font-mono text-xs text-(--color-text)'

function names(value: unknown): string {
  return value && typeof value === 'object' && !Array.isArray(value) ? Object.keys(value).join(', ') : ''
}

function safeUrl(value: unknown): string {
  if (typeof value !== 'string') return ''
  try {
    const url = new URL(value)
    url.username = ''
    url.password = ''
    // Query values and fragments can contain credentials. Hosts/paths suffice for review.
    for (const key of [...url.searchParams.keys()]) url.searchParams.set(key, '[redacted]')
    url.hash = ''
    return url.toString()
  } catch { return 'Invalid URL (see diagnostics)' }
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
  return labels[event] ?? event
}

function readableHookStatus(status: string | undefined, valid: boolean): string {
  if (!valid) return 'Invalid'
  switch (status) {
    case 'active': return 'On'
    case 'disabled': return 'Plugin is off'
    case 'disabled_by_settings': return 'Paused'
    case 'replaced_by_settings': return 'Replaced by your workflow'
    case 'awaiting_trust': return 'Needs review'
    case 'blocked_isolation_unavailable': return 'Blocked on this device'
    case 'shadowed_by_settings': return 'Covered by your workflow'
    default: return 'Unavailable'
  }
}

export function PluginInspectionDetails({
  inspection,
  installationId,
  onHookTrustChanged,
}: {
  inspection: PluginInspection
  installationId?: string
  onHookTrustChanged?: () => void | Promise<void>
}) {
  const [reviewingHook, setReviewingHook] = useState<string | null>(null)
  const [hookAction, setHookAction] = useState<string | null>(null)
  const [hookActionError, setHookActionError] = useState<string | null>(null)
  const diagnostics = [
    ...(inspection.diagnostics ?? []),
    ...(inspection.skills ?? []).flatMap((item) => item.diagnostics),
    ...(inspection.mcp_servers ?? []).flatMap((item) => item.diagnostics),
  ]
  const errors = diagnostics.filter((item) => item.severity === 'error')
  const warnings = diagnostics.filter((item) => item.severity !== 'error')
  const skills = inspection.skills ?? []
  const servers = inspection.mcp_servers ?? []
  const hooks = inspection.hooks ?? []
  const hookStatuses = inspection.hook_statuses ?? []
  const capabilities = inspection.trust?.capabilities ?? []
  const hasComponents = Boolean(skills.length || servers.length || hooks.length)
  const hasTechnicalDetails = Boolean(warnings.length || capabilities.length || servers.length || hookStatuses.length)
  return <div className="space-y-3 text-xs">
    {errors.map((item, index) => <p key={`${item.code}:${index}`} role="alert" className="rounded-md border border-(--color-error) px-3 py-2 text-destructive">{item.message}</p>)}
    {hasComponents && <details className="rounded-md border border-(--color-border) px-3 py-2">
      <summary className="cursor-pointer font-medium text-(--color-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">Components</summary>
      <div className="mt-3 space-y-4">
        {skills.length > 0 && <section aria-label="Package Skills" className="space-y-2">
          <h4 className="font-semibold text-(--color-text)">Skills</h4>
          {skills.map((skill) => <div key={skill.path} className="space-y-1 rounded-md border border-(--color-border) p-3">
            <div className="flex flex-wrap items-center justify-between gap-2"><strong>{skill.name}</strong><span className={skill.valid ? 'text-(--color-text-muted)' : 'text-destructive'}>{skill.valid ? 'Valid' : 'Invalid — not available'}</span></div>
            {skill.description && <p className="text-(--color-text-muted)">{skill.description}</p>}
            <p className="break-all font-mono text-(--color-text-subtle)">{skill.path}</p>
          </div>)}
        </section>}
        {servers.length > 0 && <section aria-label="Package MCP servers" className="space-y-2">
          <h4 className="font-semibold text-(--color-text)">MCP servers</h4>
          {servers.map((server) => <p key={server.name} className="text-(--color-text-muted)">{server.name} · {server.transport} · {server.valid ? 'Valid' : 'Invalid'}</p>)}
        </section>}
        {hooks.length > 0 && <section aria-label="Package lifecycle hooks" className="space-y-2">
          <h4 className="font-semibold text-(--color-text)">Lifecycle hooks</h4>
          {hookActionError && <p role="alert" className="text-destructive">{hookActionError}</p>}
          {hooks.map((hook) => {
            const runtime = hookStatuses.find((status) => status.hook_id === hook.definition.hook_id)
            const trustDisclosure = inspection.trust.hooks?.find((item) => item.hook_id === hook.definition.hook_id)
            const isReviewing = reviewingHook === hook.definition.hook_id
            const canReview = Boolean(installationId && runtime && hook.valid && hook.digest)
            const isStaticContext = hook.definition.execution_kind === 'static_context'
            const readableStatus = readableHookStatus(runtime?.status, hook.valid)
            const reviewAction = async (trust: boolean) => {
              if (!installationId || !hook.digest) return
              setHookAction(hook.definition.hook_id)
              setHookActionError(null)
              try {
                if (trust) {
                  await trustPluginHook(installationId, hook.definition.hook_id, hook.digest)
                } else {
                  await revokePluginHookTrust(installationId, hook.definition.hook_id)
                }
                setReviewingHook(null)
                await onHookTrustChanged?.()
              } catch (error) {
                setHookActionError(error instanceof Error ? error.message : 'Could not update hook trust.')
              } finally {
                setHookAction(null)
              }
            }
            return <div key={hook.definition.hook_id} className="space-y-2 rounded-md border border-(--color-border) p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <strong>{readableHookEvent(hook.definition.event)}</strong>
                <span className={runtime?.status === 'blocked_isolation_unavailable' ? 'text-(--color-warning)' : 'text-(--color-text-muted)'}>
                  {readableStatus}
                </span>
              </div>
              <p className="text-(--color-text-muted)">{isStaticContext
                ? 'Adds this plugin’s guidance to a new session.'
                : 'Runs this plugin’s command at this moment.'}</p>
              <p className="text-(--color-text-muted)">{isStaticContext
                ? 'This reads a Markdown guide and does not run code.'
                : 'This runs executable code. It needs verified isolation on this device.'}</p>
              <p className="text-(--color-text-muted)">{isStaticContext
                ? 'No session data is provided. The guide is treated as untrusted content.'
                : `Can read: ${hook.definition.input_fields.join(', ') || 'no session data declared'} · Can change: ${hook.definition.output_fields.join(', ') || 'nothing declared'}`}</p>
              {runtime?.status === 'blocked_isolation_unavailable' && <p className="text-(--color-warning)">This device cannot enforce the required isolation, so this workflow stays off here.</p>}
              {!hook.valid && hook.diagnostics.map((item, index) => <p key={`${item.code}:${index}`} className="text-destructive">{item.message}</p>)}
              {runtime && <p className="text-(--color-text-muted)">Workflow approval: {runtime.trusted ? 'approved for this content' : 'review required'} · Plugin: {runtime.enabled ? 'enabled' : 'off'}</p>}
              {canReview && <div className="flex flex-wrap gap-2 pt-1">
                {!runtime?.trusted && !isReviewing && <button type="button" className="rounded-md border border-(--color-border) px-2.5 py-1.5 font-medium hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)" onClick={() => setReviewingHook(hook.definition.hook_id)}>Review workflow</button>}
                {runtime?.trusted && <button type="button" className="rounded-md border border-(--color-border) px-2.5 py-1.5 font-medium hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)" disabled={hookAction !== null} onClick={() => void reviewAction(false)}>{hookAction === hook.definition.hook_id ? 'Revoking…' : 'Revoke workflow approval'}</button>}
                {isReviewing && <div className="w-full space-y-2 rounded-md bg-(--bg-page) p-3">
                  <p>{isStaticContext
                    ? 'Allowing approves this exact guide and adds it as untrusted session context. It does not enable the plugin.'
                    : 'Allowing approves this exact command and declared data access. It does not enable the plugin; execution still requires verified isolation.'}</p>
                  <details className="rounded border border-(--color-border) px-2.5 py-2">
                    <summary className="cursor-pointer font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">Technical details</summary>
                    <div className="mt-2 space-y-1 break-all text-(--color-text-muted)">
                      <p><code>{hook.definition.hook_id}</code> · event <code>{hook.definition.event}</code></p>
                      <p>{isStaticContext ? `Static context file: ${hook.command_path}` : `Command: ${hook.definition.command.map((part) => JSON.stringify(part)).join(' ')}`}</p>
                      {isStaticContext && hook.definition.context_prefix && <p>Context wrapper: <code>{JSON.stringify(hook.definition.context_prefix)}…{JSON.stringify(hook.definition.context_suffix)}</code></p>}
                      <p>Runtime: <code>{hook.definition.runtime ?? 'native'}</code> · Declared files: {hook.definition.files?.join(', ') || 'entrypoint only'}</p>
                      <p>Inputs: {hook.definition.input_fields.join(', ') || 'none'} · Outputs: {hook.definition.output_fields.join(', ') || 'none'}</p>
                      <p>Matcher: <code>{hook.definition.matcher ? JSON.stringify(hook.definition.matcher) : 'none'}</code> · Timeout: {hook.definition.timeout_seconds} seconds · Failure policy: <code>{hook.definition.failure_policy}</code></p>
                      <p>Environment: {trustDisclosure?.environment_fields.join(', ') || 'none'} · Isolation profile: <code>{trustDisclosure?.isolation_profile ?? 'unavailable'}</code></p>
                      <p className="font-mono">SHA-256: {hook.digest}</p>
                    </div>
                  </details>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className="rounded-md bg-(--color-accent) px-2.5 py-1.5 font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)" disabled={hookAction !== null} onClick={() => void reviewAction(true)}>{hookAction === hook.definition.hook_id ? 'Saving…' : 'Allow this workflow'}</button>
                    <button type="button" className="rounded-md border border-(--color-border) px-2.5 py-1.5 font-medium hover:bg-(--bg-key) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)" onClick={() => setReviewingHook(null)}>Cancel</button>
                  </div>
                </div>}
              </div>}
            </div>
          })}
          <p className="text-(--color-text-subtle)">Command workflows are executable code and run only on hosts with verified OS isolation and digest-bound approval. Static workflows only read an approved package file; all injected contents are treated as untrusted data.</p>
        </section>}
      </div>
    </details>}
    {hasTechnicalDetails && <details className="rounded-md border border-(--color-border) px-3 py-2">
      <summary className="cursor-pointer font-medium text-(--color-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">Technical details</summary>
      <div className="mt-3 space-y-3">
        {capabilities.length > 0 && <section className="space-y-1"><h4 className="font-semibold">Capabilities</h4>{capabilities.map((capability) => <p key={`${capability.name}:${capability.source}`} className="text-(--color-text-muted)">{capability.name} · {capability.source}</p>)}</section>}
        {warnings.length > 0 && <section aria-label="Validation diagnostics" className="space-y-1"><h4 className="font-semibold">Validation diagnostics</h4>{warnings.map((item, index) => <p key={`${item.code}:${index}`} className="text-(--color-text-muted)">{item.severity}: {item.message}</p>)}</section>}
        {servers.length > 0 && <section aria-label="MCP server configuration" className="space-y-2">
          <h4 className="font-semibold">MCP server configuration</h4>
          {servers.map((server) => {
            const config = server.config ?? {}
            const args = Array.isArray(config.args) ? config.args.filter((arg): arg is string => typeof arg === 'string') : []
            const envNames = names(config.env)
            const headerNames = names(config.headers)
            return <div key={server.name} className="space-y-1 rounded-md border border-(--color-border) p-3">
              <strong>{server.name}</strong>
              {typeof config.command === 'string' && <pre className={codeClass}>{[config.command, ...args].join(' ')}</pre>}
              {typeof config.url === 'string' && <p className="break-all font-mono">{safeUrl(config.url)}</p>}
              {typeof config.cwd === 'string' && <p className="break-all">Working directory: <code>{config.cwd}</code></p>}
              {envNames && <p className="break-all text-(--color-text-muted)">Environment fields: {envNames}</p>}
              {headerNames && <p className="break-all text-(--color-text-muted)">Header fields: {headerNames}</p>}
            </div>
          })}
          <p className="text-(--color-text-subtle)">Preview does not start servers. Field names are shown, never credential values. Enabling may start the declared processes or remote connections.</p>
        </section>}
      </div>
    </details>}
  </div>
}

export function PluginPackageFiles({ target, id, onReviewReady }: { target: 'preview' | 'installation'; id: string; onReviewReady?: (ready: boolean) => void }) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const listing = useQuery({ queryKey: queryKeys.plugins.packageReview(target, id), queryFn: () => getPluginPackageReview(target, id), retry: false })
  const file = useQuery({ queryKey: queryKeys.plugins.packageFile(target, id, selectedPath ?? ''), queryFn: () => getPluginPackageFile(target, id, selectedPath!), enabled: selectedPath !== null, retry: false })
  useEffect(() => { onReviewReady?.(listing.isSuccess && !listing.error) }, [onReviewReady, listing.isSuccess, listing.error])
  const fileError = selectedPath ? file.error : null
  const content = selectedPath ? file.data?.content : listing.data?.readme?.content
  return <div className="space-y-2 text-xs">
    {listing.error && <p role="alert" className="text-destructive">{listing.error instanceof Error ? listing.error.message : 'Unable to read package file listing.'}</p>}
    <details className="rounded-md border border-(--color-border) px-3 py-2 text-xs">
    <summary className="cursor-pointer font-medium text-(--color-text) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--color-accent)">Package files</summary>
    <section aria-label="Read-only package files" className="mt-3 space-y-2">
    <p className="text-(--color-text-muted)">Read-only text preview. HTML and scripts are not rendered or executed. Sensitive files are excluded and credential values are masked.</p>
    {listing.isPending && <p>Loading package files…</p>}
    {listing.data && <>
      <div className="max-h-40 overflow-auto rounded-md border border-(--color-border)" aria-label="Package file list">
        {listing.data.files.map((entry) => <button key={entry.path} type="button" disabled={entry.kind !== 'text'} aria-pressed={selectedPath === entry.path} className="flex w-full items-start justify-between gap-3 px-3 py-2 text-left hover:bg-(--bg-hover) disabled:opacity-50" onClick={() => setSelectedPath(entry.path)}>
          <span className="min-w-0 break-all font-mono">{entry.path}</span><span className="shrink-0 text-(--color-text-muted)">{entry.size.toLocaleString()} B{entry.kind !== 'text' ? ` · ${entry.kind}` : ''}</span>
        </button>)}

      </div>
      {listing.data.truncated && <p className="text-(--color-text-muted)">File listing was limited for safety; this is not the complete package.</p>}
    </>}
    {(selectedPath || listing.data?.readme) && <p className="break-all font-mono">{selectedPath ?? listing.data?.readme?.path}</p>}
    {selectedPath && file.isPending && <p>Loading file…</p>}
    {fileError && <p role="alert" className="text-destructive">{fileError instanceof Error ? fileError.message : 'Unable to read package file.'}</p>}
    {content != null && !fileError && <pre className={codeClass}>{content}</pre>}
    {selectedPath && file.data?.truncated && <p className="text-(--color-text-muted)">File text was truncated for safety.</p>}
    </section>
    </details>
  </div>
}
