import { useState } from 'react'
import { Check, Users } from 'lucide-react'

import { useCreateAgentMutation } from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { AgentForm } from '@/components/settings/AgentForm'
import {
  AgentGlyph,
} from '@/components/settings/AgentVisuals'
import {
  AGENT_TEAM_VISUALS,
  type AgentTeam,
} from '@/lib/agent-visuals'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import { SettingsPage } from '@/components/settings/SettingsLayout'
import { cn } from '@/lib/utils'
import { validateAgentDraft } from '@/components/settings/schema'
import { useSettingsSearch, useSettingsNavigate } from '@/contexts/SettingsContext'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'

type AgentMode = AgentTeam

const TEMPLATE = `---
name: new_agent
role: member
description: A helpful team member.
model: googlegenai:gemini-3.1-flash-lite-preview
---

You are "new_agent" — a helpful team member.

## Style
- Be concise.
- Ask clarifying questions when requirements are ambiguous.
`

export function NewAgentPage() {
  const search = useSettingsSearch()
  const initialMode: AgentMode =
    search.mode === 'coding' ? 'coding' : search.mode === 'aim' ? 'aim' : 'work'
  const [draft, setDraft] = useState(TEMPLATE)
  const [name, setName] = useState('new_agent')
  const [agentMode, setAgentMode] = useState<AgentMode>(initialMode)
  const createMut = useCreateAgentMutation()
  const push = useToastStore((s) => s.push)
  const navigate = useSettingsNavigate()
  const [saveError, setSaveError] = useState<string | null>(null)
  const [mode, setMode] = useState<'form' | 'raw'>('form')

  // Keep the name in sync with whatever the user typed into the form.
  // AgentForm is the canonical source of raw content; we sniff the name
  // from its frontmatter on each change.
  const handleDraftChange = (raw: string) => {
    setDraft(raw)
    const match = /^\s*---[\s\S]*?name:\s*([A-Za-z0-9._-]+)/m.exec(raw)
    if (match) setName(match[1])
  }

  const draftErrors = validateAgentDraft(draft)
  const invalid = draftErrors !== null
  const firstDraftError = draftErrors ? Object.values(draftErrors)[0] : null
  const dirty = draft !== TEMPLATE || agentMode !== initialMode
  useRegisterSettingsDirty(dirty)

  const handleCreate = async () => {
    setSaveError(null)
    if (invalid) {
      setSaveError(firstDraftError ?? 'Form has validation errors.')
      return
    }
    try {
      const agentName =
        agentMode === 'coding' ? `coding/${name}` : agentMode === 'aim' ? `aim/${name}` : name
      await createMut.mutateAsync({ name: agentName, content: draft })
      push({
        tone: 'success',
        title: `Created "${agentName}"`,
        description: 'Active on next turn.',
      })
      // The draft is persisted, so it must not trigger the discard confirm.
      navigate('/settings/agents/$name', { params: { name: agentName }, force: true })
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      setSaveError(msg)
      push({ tone: 'error', title: 'Create failed', description: msg })
    }
  }

  return (
    <SettingsPage
      icon={Users}
      title="Create an agent"
      lede="Start with a focused role. You can refine its model, access, and instructions before creating the file."
      size="wide"
      actions={
        <EditorHeaderActions
          dirty={dirty}
          invalid={invalid}
          saving={createMut.isPending}
          error={saveError}
          validationHint={firstDraftError}
          mode={mode}
          onModeChange={setMode}
          saveLabel="Create agent"
          onSave={handleCreate}
        />
      }
    >
      <section className="overflow-hidden rounded-2xl border border-(--color-border) bg-(--bg-card)">
        <header className="border-b border-(--color-border-subtle) bg-(--bg-key)/25 px-4 py-3.5 sm:px-5">
          <h2 className="font-heading text-sm font-semibold text-(--color-text)">Choose a team</h2>
          <p className="mt-0.5 text-xs text-(--color-text-muted)">
            The team controls the file location and inherited capability tier.
          </p>
        </header>
        <div className="grid gap-2 p-3 sm:grid-cols-3 sm:p-4">
          {(['work', 'coding', 'aim'] as const).map((team) => {
            const visual = AGENT_TEAM_VISUALS[team]
            const active = team === agentMode
            return (
              <button
                key={team}
                type="button"
                aria-pressed={active}
                onClick={() => setAgentMode(team)}
                className={cn(
                  'relative flex min-w-0 items-center gap-3 rounded-xl border p-3 text-left outline-none transition-[border-color,background-color,transform] active:scale-[0.99] focus-visible:ring-3 focus-visible:ring-(--focus-ring)/35 sm:flex-col sm:items-start',
                  active
                    ? 'border-(--color-accent)/45 bg-(--color-accent-soft)'
                    : 'border-(--color-border) bg-(--bg-input) hover:border-(--color-border-strong) hover:bg-(--bg-key)/35',
                )}
              >
                <AgentGlyph name={team === 'work' ? name : `${team}/${name}`} role="member" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-(--color-text)">{visual.label}</p>
                  <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-(--color-text-muted)">{visual.description}</p>
                </div>
                {active && (
                  <span className="absolute right-2.5 top-2.5 flex size-5 items-center justify-center rounded-full bg-(--color-accent) text-(--color-text-on-accent)">
                    <Check size={11} strokeWidth={3} aria-hidden="true" />
                  </span>
                )}
              </button>
            )
          })}
        </div>
        <div className="border-t border-(--color-border-subtle) px-4 py-2.5 text-[11px] text-(--color-text-muted) sm:px-5">
          File: <span className="font-mono text-(--color-text-2)">
            {agentMode === 'work' ? `${name}.md` : `${agentMode}/${name}.md`}
          </span>
        </div>
      </section>

      <AgentForm
        initial={TEMPLATE}
        onChange={handleDraftChange}
        disabled={createMut.isPending}
        isNew
        mode={mode}
        onModeChange={setMode}
      />
    </SettingsPage>
  )
}
