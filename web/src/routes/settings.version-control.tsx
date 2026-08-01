import { useState } from 'react'
import { AlertTriangle, GitBranch, Save, ShieldCheck } from 'lucide-react'

import type { VersionControlSettings } from '@/api/client'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { Switch } from '@/components/ui/switch'
import {
  useUpdateVersionControlSettingsMutation,
  useVersionControlSettingsQuery,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'

function NumericControl({
  id,
  value,
  min,
  max,
  step = 1,
  unit,
  onChange,
}: {
  id: string
  value: number
  min: number
  max: number
  step?: number
  unit: string
  onChange: (value: number) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <Input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-8 w-24 text-right font-mono"
      />
      <span className="w-14 text-xs text-(--color-text-muted)">{unit}</span>
    </div>
  )
}

export function VersionControlSettingsPage() {
  const query = useVersionControlSettingsQuery()
  const update = useUpdateVersionControlSettingsMutation()
  const push = useToastStore((state) => state.push)
  const [editedDraft, setEditedDraft] = useState<VersionControlSettings | null>(null)
  const draft = editedDraft ?? query.data ?? null
  const dirty = Boolean(
    editedDraft
    && query.data
    && JSON.stringify(editedDraft) !== JSON.stringify(query.data),
  )
  useRegisterSettingsDirty(dirty)

  const patch = <K extends keyof VersionControlSettings>(
    key: K,
    value: VersionControlSettings[K],
  ) => setEditedDraft((current) => {
    const source = current ?? query.data
    return source ? { ...source, [key]: value } : current
  })

  const save = async () => {
    if (!draft) return
    const normalized: VersionControlSettings = {
      ...draft,
      network_timeout_seconds: Math.min(1800, Math.max(10, draft.network_timeout_seconds)),
      max_diff_bytes: Math.min(50_000_000, Math.max(64_000, draft.max_diff_bytes)),
      review_request_timeout_seconds: Math.min(300, Math.max(2, draft.review_request_timeout_seconds)),
      review_retry_attempts: Math.min(5, Math.max(0, Math.round(draft.review_retry_attempts))),
      review_retry_backoff_seconds: Math.min(10, Math.max(0, draft.review_retry_backoff_seconds)),
      review_max_concurrent_repositories: Math.min(32, Math.max(1, Math.round(draft.review_max_concurrent_repositories))),
      review_max_pages_per_repository: Math.min(20, Math.max(1, Math.round(draft.review_max_pages_per_repository))),
    }
    try {
      await update.mutateAsync(normalized)
      setEditedDraft(null)
      push({
        tone: 'success',
        title: 'Git settings saved',
        description: 'New Git and review operations use these guardrails immediately.',
      })
    } catch (error) {
      push({
        tone: 'error',
        title: 'Save failed',
        description: error instanceof Error ? error.message : String(error),
      })
    }
  }

  return (
    <SettingsPage
      icon={GitBranch}
      title="Git & reviews"
      lede="Reliability limits and safety policy for local Git, remote synchronization, and pull or merge request APIs."
      actions={
        <div className="flex items-center gap-2">
          {dirty && <span className="text-xs text-(--color-text-muted)">Unsaved</span>}
          <Button size="sm" onClick={() => void save()} disabled={!dirty || update.isPending}>
            <Save size={12} aria-hidden="true" />
            {update.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      }
    >
      <SettingsAsyncBoundary
        loading={query.isLoading}
        hasData={Boolean(query.data)}
        error={query.error}
        variant="detail"
        loadingLabel="Loading Git settings"
        errorTitle="Failed to load Git settings"
        onRetry={() => void query.refetch()}
      >
        {draft && (
          <div className="space-y-7">
            <SettingsGroup
              title="Remote Git"
              description="Defaults used by fetch, pull, push, tag push, and the create-pull-request agent tool."
            >
              <SettingsRow
                label="Pull strategy"
                description="Fast-forward only is the safest production default because it never creates an implicit merge commit or rewrites local commits."
                control={
                  <SegmentedControl
                    options={[
                      { value: 'ff_only', label: 'FF only' },
                      { value: 'merge', label: 'Merge' },
                      { value: 'rebase', label: 'Rebase' },
                    ]}
                    value={draft.default_pull_strategy}
                    onChange={(value) => patch('default_pull_strategy', value)}
                    layoutId="git-pull-strategy"
                    ariaLabel="Default Git pull strategy"
                  />
                }
              />
              <SettingsRow
                label="Network timeout"
                description="Hard deadline for each remote Git process. Timed-out process groups are terminated."
                htmlFor="git-network-timeout"
                control={
                  <NumericControl
                    id="git-network-timeout"
                    value={draft.network_timeout_seconds}
                    min={10}
                    max={1800}
                    unit="seconds"
                    onChange={(value) => patch('network_timeout_seconds', value)}
                  />
                }
              />
              <SettingsRow
                label="Maximum diff"
                description="Prevents the source-control viewer from loading an unexpectedly large file or patch into memory and the UI."
                htmlFor="git-max-diff"
                control={
                  <NumericControl
                    id="git-max-diff"
                    value={Number((draft.max_diff_bytes / 1_000_000).toFixed(2))}
                    min={0.064}
                    max={50}
                    step={0.25}
                    unit="MB"
                    onChange={(value) => patch('max_diff_bytes', Math.round(value * 1_000_000))}
                  />
                }
              />
              <SettingsRow
                label="Prune on fetch"
                description="Remove remote-tracking refs that no longer exist on the selected server. Individual API calls can override this default."
                control={
                  <Switch
                    checked={draft.prune_on_fetch}
                    onCheckedChange={(value) => patch('prune_on_fetch', value)}
                    aria-label="Prune deleted remote branches on fetch"
                  />
                }
              />
              <SettingsRow
                label="Allow force-with-lease push"
                description="Enables the guarded force-push option. Regular pushes remain available when this is off."
                control={
                  <Switch
                    checked={draft.allow_force_push}
                    onCheckedChange={(value) => patch('allow_force_push', value)}
                    aria-label="Allow force with lease pushes"
                  />
                }
              />
              {draft.allow_force_push && (
                <div className="px-4 py-4 sm:px-5">
                  <SettingsCallout tone="warning" icon={AlertTriangle}>
                    Force-with-lease can rewrite a shared branch. EvoFlux still requires the caller to request it explicitly.
                  </SettingsCallout>
                </div>
              )}
            </SettingsGroup>

            <SettingsGroup
              title="Pull and merge requests"
              description="Provider-neutral limits shared by GitHub, GitLab, Bitbucket, Gitea/Forgejo, and Azure DevOps adapters."
            >
              <SettingsRow
                label="Review mutations"
                description="Master kill switch for comments, approvals, metadata updates, state changes, review creation, and merge. Read-only review remains available."
                control={
                  <Switch
                    checked={draft.allow_review_mutations}
                    onCheckedChange={(value) => patch('allow_review_mutations', value)}
                    aria-label="Allow pull request mutations"
                  />
                }
              />
              <SettingsRow
                label="Require successful checks before merge"
                description="Blocks provider merge calls unless normalized CI status is successful. Providers without checks support cannot merge while enabled."
                control={
                  <Switch
                    checked={draft.require_successful_checks_before_merge}
                    onCheckedChange={(value) => patch('require_successful_checks_before_merge', value)}
                    aria-label="Require successful checks before merge"
                  />
                }
              />
              <SettingsRow
                label="Allow insecure servers"
                description="Permit plain HTTP or disabled TLS verification for self-hosted Git servers. Keep off in production."
                control={
                  <Switch
                    checked={draft.allow_insecure_connections}
                    onCheckedChange={(value) => patch('allow_insecure_connections', value)}
                    aria-label="Allow insecure Git server connections"
                  />
                }
              />
              <SettingsRow
                label="API timeout"
                description="Deadline for one Git server REST request."
                htmlFor="review-api-timeout"
                control={
                  <NumericControl
                    id="review-api-timeout"
                    value={draft.review_request_timeout_seconds}
                    min={2}
                    max={300}
                    unit="seconds"
                    onChange={(value) => patch('review_request_timeout_seconds', value)}
                  />
                }
              />
              <SettingsRow
                label="Transient retries"
                description="Retries read requests after rate limits and transient 5xx failures with exponential backoff. Mutations are never retried automatically."
                htmlFor="review-retries"
                control={
                  <NumericControl
                    id="review-retries"
                    value={draft.review_retry_attempts}
                    min={0}
                    max={5}
                    unit="retries"
                    onChange={(value) => patch('review_retry_attempts', value)}
                  />
                }
              />
              <SettingsRow
                label="Retry backoff"
                description="Initial delay; each subsequent retry doubles it, capped internally at 30 seconds."
                htmlFor="review-backoff"
                control={
                  <NumericControl
                    id="review-backoff"
                    value={draft.review_retry_backoff_seconds}
                    min={0}
                    max={10}
                    step={0.25}
                    unit="seconds"
                    onChange={(value) => patch('review_retry_backoff_seconds', value)}
                  />
                }
              />
              <SettingsRow
                label="Repository concurrency"
                description="Maximum repositories queried at once when a project or all-repositories review scope is open."
                htmlFor="review-concurrency"
                control={
                  <NumericControl
                    id="review-concurrency"
                    value={draft.review_max_concurrent_repositories}
                    min={1}
                    max={32}
                    unit="repos"
                    onChange={(value) => patch('review_max_concurrent_repositories', value)}
                  />
                }
              />
              <SettingsRow
                label="Pagination cap"
                description="Maximum list pages fetched per repository, limiting rate usage on very large installations."
                htmlFor="review-pages"
                control={
                  <NumericControl
                    id="review-pages"
                    value={draft.review_max_pages_per_repository}
                    min={1}
                    max={20}
                    unit="pages"
                    onChange={(value) => patch('review_max_pages_per_repository', value)}
                  />
                }
              />
              {!draft.allow_insecure_connections && !draft.allow_force_push && (
                <div className="px-4 py-4 sm:px-5">
                  <SettingsCallout tone="success" icon={ShieldCheck}>
                    Secure transport and force-push protection are enabled.
                  </SettingsCallout>
                </div>
              )}
            </SettingsGroup>
          </div>
        )}
      </SettingsAsyncBoundary>
    </SettingsPage>
  )
}
