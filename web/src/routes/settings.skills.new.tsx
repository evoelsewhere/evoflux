import { useState } from 'react'
import { Sparkles } from 'lucide-react'

import { useCreateSkillMutation } from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import {
  SettingsGroup,
  SettingsPage,
  SettingsRow,
} from '@/components/settings/SettingsLayout'
import { validateSkillDraft } from '@/components/settings/schema'
import { Textarea } from '@/components/ui/textarea'
import { useSettingsNavigate } from '@/contexts/SettingsContext'

const TEMPLATE = `---
name: new-skill
description: One-line description shown to agents when they see the skill list.
---

# New skill

Replace this with the instructions an agent should follow when applying
this skill. Keep it focused on a single concern.
`

export function NewSkillPage() {
  const [content, setContent] = useState(TEMPLATE)
  const [name, setName] = useState('new-skill')
  const createMut = useCreateSkillMutation()
  const push = useToastStore((s) => s.push)
  const navigate = useSettingsNavigate()
  const [saveError, setSaveError] = useState<string | null>(null)

  const handleContentChange = (raw: string) => {
    setContent(raw)
    const match = /^\s*---[\s\S]*?name:\s*([A-Za-z0-9._/-]+)/m.exec(raw)
    if (match) setName(match[1])
  }

  const draftErrors = validateSkillDraft(content)
  const invalid = draftErrors !== null
  const firstDraftError = draftErrors ? Object.values(draftErrors)[0] : null

  const handleCreate = async () => {
    setSaveError(null)
    if (invalid) {
      setSaveError(firstDraftError ?? 'Form has validation errors.')
      return
    }
    try {
      await createMut.mutateAsync({ name, content })
      push({
        tone: 'success',
        title: `Created skill "${name}"`,
        description: 'Active on next turn.',
      })
      navigate('/settings/skills/$name', { params: { name } })
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      setSaveError(msg)
      push({ tone: 'error', title: 'Create failed', description: msg })
    }
  }

  return (
    <SettingsPage
      icon={Sparkles}
      title="New skill"
      actions={
        <EditorHeaderActions
          dirty={content !== TEMPLATE}
          invalid={invalid}
          saving={createMut.isPending}
          error={saveError}
          validationHint={firstDraftError}
          onSave={handleCreate}
        />
      }
    >
      <SettingsGroup
        title="Skill source"
        description={
          <>
            Frontmatter (<span className="font-mono">name</span>,{' '}
            <span className="font-mono">description</span>) is required; use{' '}
            <span className="font-mono">parent/sub</span> for a one-level sub-skill. The body is the
            instruction the agent loads on demand.
          </>
        }
      >
        <SettingsRow
          stacked
          control={
            <Textarea
              aria-label="Skill source"
              value={content}
              onChange={(e) => handleContentChange(e.target.value)}
              disabled={createMut.isPending}
              rows={28}
              spellCheck={false}
              aria-invalid={invalid || undefined}
              className="min-h-96 font-mono text-[13px] leading-relaxed"
            />
          }
        />
      </SettingsGroup>
    </SettingsPage>
  )
}
