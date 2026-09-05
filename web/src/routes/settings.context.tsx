import { AlertTriangle, Info, Layers } from 'lucide-react'

import type { ContextOverrides, ContextSettings } from '@/api/types'
import {
  SettingsCallout,
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { SettingsAsyncBoundary } from '@/components/settings/SettingsLoading'
import { SelectControl } from '@/components/ui/select'
import {
  useContextSettingsQuery,
  useUpdateContextSettingsMutation,
} from '@/queries'
import { useToastStore } from '@/stores/useToastStore'

type Field = keyof ContextOverrides

/** How each field is offered and described. Choices bracket the default. */
const FIELDS: {
  field: Field
  label: string
  description: string
  choices: number[]
  format: (value: number) => string
}[] = [
  {
    field: 'summary_trigger_tokens',
    label: 'Compact at',
    description:
      'Prompt size that triggers a compaction. The default balances what one compaction costs against carrying context on every later turn.',
    choices: [60_000, 100_000, 150_000, 250_000, 350_000, 500_000, 750_000],
    format: formatTokens,
  },
  {
    field: 'summary_max_tokens',
    label: 'Summary length',
    description:
      'Ceiling on the summary that replaces the compacted turns. Shorter frees more context but keeps less of what happened.',
    choices: [8_000, 15_000, 30_000, 50_000, 80_000],
    format: formatTokens,
  },
  {
    field: 'keep_recent_turns',
    label: 'Keep recent turns verbatim',
    description:
      'Assistant turns left uncompacted. A summary cannot reproduce a diff, a stack trace, or exact line numbers byte-for-byte — these can.',
    choices: [0, 1, 2, 3, 5, 8],
    format: (value) =>
      value === 0
        ? 'None — summarise everything'
        : `${value} ${value === 1 ? 'turn' : 'turns'}`,
  },
  {
    field: 'tool_result_offload_chars',
    label: 'Offload tool results over',
    description:
      'Longer results are written to a session artifact and replaced by a short receipt the agent can re-read on demand.',
    choices: [5_000, 10_000, 20_000, 40_000, 80_000, 200_000],
    format: (value) => `${Math.round(value / 1000)}K chars`,
  },
  {
    field: 'keep_recent_tool_batches',
    label: 'Keep recent tool batches verbatim',
    description:
      'Older tool results are replaced by receipts at the provider boundary. A wider window replays more exact output on every turn.',
    choices: [1, 2, 3, 4, 6, 8],
    format: (value) => `${value} ${value === 1 ? 'batch' : 'batches'}`,
  },
]

function formatTokens(value: number): string {
  return value >= 1_000_000
    ? `${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
    : `${Math.round(value / 1000)}K`
}

export function ContextSettingsPage() {
  const query = useContextSettingsQuery()
  const update = useUpdateContextSettingsMutation()
  const push = useToastStore((state) => state.push)
  const settings = query.data ?? null

  const change = (field: Field, label: string, format: (v: number) => string) =>
    (raw: string) => {
      const next = raw === 'default' ? null : Number(raw)
      update.mutate({ [field]: next } as Partial<ContextOverrides>, {
        onSuccess: () =>
          push({
            tone: 'success',
            title: `${label} updated`,
            description:
              next === null
                ? 'Back to the built-in default.'
                : `Now ${format(next)}, for every session.`,
          }),
        onError: (error) =>
          push({
            tone: 'error',
            title: 'Save failed',
            description: error instanceof Error ? error.message : String(error),
          }),
      })
    }

  return (
    <SettingsPage
      icon={Layers}
      title="Context"
      lede="What a session keeps in its prompt, what it throws away, and when."
    >
      <SettingsAsyncBoundary
        loading={query.isLoading}
        hasData={settings !== null}
        error={query.error}
        variant="detail"
        loadingLabel="Loading context settings"
        errorTitle="Could not load context settings"
        onRetry={() => void query.refetch()}
      >
        {settings && (
          // SettingsAsyncBoundary renders its children through a
          // `display: contents` wrapper, so SettingsPage's own `space-y` never
          // reaches the groups inside it. Every settings page with more than
          // one group carries its own spacer for that reason.
          <div className="space-y-10">
            {settings.ignored.length > 0 && (
              <SettingsCallout tone="warning" icon={AlertTriangle}>
                <p>
                  settings.yaml sets {settings.ignored.length === 1 ? 'a value' : 'values'} here
                  that {settings.ignored.length === 1 ? 'is' : 'are'} being ignored, so the file
                  and your sessions disagree. Saving anything on this page rewrites the file
                  without {settings.ignored.length === 1 ? 'it' : 'them'}.
                </p>
                <ul className="mt-1.5 space-y-0.5">
                  {settings.ignored.map((item) => (
                    <li key={item.field}>
                      <code>{item.field}</code> — {item.message}
                    </li>
                  ))}
                </ul>
              </SettingsCallout>
            )}
            <SettingsGroup
              title="Compaction"
              description="When a session summarises its earlier turns, and how much survives."
            >
              {FIELDS.slice(0, 3).map((spec) => (
                <ThresholdRow
                  key={spec.field}
                  spec={spec}
                  settings={settings}
                  disabled={update.isPending}
                  onChange={change(spec.field, spec.label, spec.format)}
                />
              ))}
              <SettingsCallout tone="info" icon={Info}>
                Every model is capped at 75% of its own context window, so a
                threshold above that is clamped rather than ignored — a 32K model
                compacts at 24K whatever is chosen here. Compacting sooner spends
                fewer tokens replaying history, but each compaction replaces exact
                text with a summary and resets the prompt cache.
              </SettingsCallout>
            </SettingsGroup>

            <SettingsGroup
              title="Tool output"
              description="Tool results are the bulk of a coding session's context. These decide how much of it is replayed."
            >
              {FIELDS.slice(3).map((spec) => (
                <ThresholdRow
                  key={spec.field}
                  spec={spec}
                  settings={settings}
                  disabled={update.isPending}
                  onChange={change(spec.field, spec.label, spec.format)}
                />
              ))}
            </SettingsGroup>
          </div>
        )}
      </SettingsAsyncBoundary>
    </SettingsPage>
  )
}

function ThresholdRow({
  spec,
  settings,
  disabled,
  onChange,
}: {
  spec: (typeof FIELDS)[number]
  settings: ContextSettings
  disabled: boolean
  onChange: (raw: string) => void
}) {
  const current = settings[spec.field]
  const fallback = settings.defaults[spec.field]
  // Two of the built-ins are smaller in Coding. Saying only the Work number
  // would misreport what a Coding session actually does, so name both.
  const codingFallback = settings.coding_defaults[spec.field]
  const defaultLabel = codingFallback !== undefined && codingFallback !== fallback
    ? `Default — ${spec.format(fallback)}, ${codingFallback} in Coding`
    : `Default — ${spec.format(fallback)}`
  return (
    <SettingsRow
      label={spec.label}
      description={spec.description}
      control={
        <SelectControl
          size="sm"
          // Wide enough for the longest default label, which names both
          // modes: "Default — 4 batches, 3 in Coding".
          className="w-64"
          ariaLabel={spec.label}
          disabled={disabled}
          value={String(current ?? 'default')}
          onValueChange={onChange}
          options={[
            { value: 'default', label: defaultLabel },
            ...spec.choices
              .filter((value) => value <= settings.max_tokens)
              .map((value) => ({ value: String(value), label: spec.format(value) })),
          ]}
        />
      }
    />
  )
}
