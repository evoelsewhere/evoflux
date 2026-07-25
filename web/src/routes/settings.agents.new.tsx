import { useState } from 'react'
import { Wrench } from 'lucide-react'

import { useCreateAgentMutation } from '@/queries'
import { Button } from '@/components/ui/button'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { AgentForm } from '@/components/settings/AgentForm'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import {
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { validateAgentDraft } from '@/components/settings/schema'
import { useSettingsSearch, useSettingsNavigate } from '@/contexts/SettingsContext'

type AgentMode = 'forge' | 'coding' | 'aim'

const TEMPLATE = `---
name: new_agent
role: member
description: A helpful team member.
model: googlegenai:gemini-3.1-flash-lite-preview
temperature: 0.2
---

You are "new_agent" — a helpful team member.

## Style
- Be concise.
- Ask clarifying questions when requirements are ambiguous.
`

export function NewAgentPage() {
  const search = useSettingsSearch()
  const initialMode: AgentMode =
    search.mode === 'coding' ? 'coding' : search.mode === 'aim' ? 'aim' : 'forge'
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
      navigate('/settings/agents/$name', { params: { name: agentName } })
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      setSaveError(msg)
      push({ tone: 'error', title: 'Create failed', description: msg })
    }
  }

  return (
    <SettingsPage
      icon={Wrench}
      title="New agent"
      actions={
        <EditorHeaderActions
          dirty={draft !== TEMPLATE}
          invalid={invalid}
          saving={createMut.isPending}
          error={saveError}
          validationHint={firstDraftError}
          mode={mode}
          onModeChange={setMode}
          onSave={handleCreate}
        />
      }
    >
      <SettingsGroup title="Create in">
        <SettingsRow
          stacked
          description={
            agentMode === 'coding'
              ? `Will create coding/${name}.md for coding sessions.`
              : agentMode === 'aim'
                ? `Will create aim/${name}.md for AIM sessions.`
                : `Will create ${name}.md for forge sessions.`
          }
          control={
            <div className="flex gap-2">
              <Button
                type="button"
                size="xs"
                className="min-h-11 md:min-h-0"
                variant={agentMode === 'forge' ? 'default' : 'outline'}
                onClick={() => setAgentMode('forge')}
              >
                Forge
              </Button>
              <Button
                type="button"
                size="xs"
                className="min-h-11 md:min-h-0"
                variant={agentMode === 'coding' ? 'default' : 'outline'}
                onClick={() => setAgentMode('coding')}
              >
                Coding
              </Button>
              <Button
                type="button"
                size="xs"
                className="min-h-11 md:min-h-0"
                variant={agentMode === 'aim' ? 'default' : 'outline'}
                onClick={() => setAgentMode('aim')}
              >
                AIM
              </Button>
            </div>
          }
        />
      </SettingsGroup>

      <SettingsGroup bare>
        <AgentForm
          initial={TEMPLATE}
          onChange={handleDraftChange}
          disabled={createMut.isPending}
          isNew
          mode={mode}
          onModeChange={setMode}
        />
      </SettingsGroup>
    </SettingsPage>
  )
}
