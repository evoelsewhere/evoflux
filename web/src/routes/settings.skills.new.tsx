import { useState } from 'react'
import { Sparkles } from 'lucide-react'

import { useCreateSkillMutation } from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import {
  SettingsGroup,
  SettingsPage,
} from '@/components/settings/SettingsLayout'
import {
  SkillBundleEditor,
} from '@/components/settings/SkillBundleEditor'
import {
  getSkillBundleChanges,
  type SkillBundleDraftFile,
} from '@/components/settings/skillBundle'
import { validateSkillDraft } from '@/components/settings/schema'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'

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
  const [files, setFiles] = useState<SkillBundleDraftFile[]>([])
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
  const dirty = content !== TEMPLATE || files.length > 0
  useRegisterSettingsDirty(dirty)

  const handleCreate = async () => {
    setSaveError(null)
    if (invalid) {
      setSaveError(firstDraftError ?? 'Form has validation errors.')
      return
    }
    try {
      const bundle = getSkillBundleChanges(files, [])
      await createMut.mutateAsync({ name, content, files: bundle.files })
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
          dirty={dirty}
          invalid={invalid}
          saving={createMut.isPending}
          error={saveError}
          validationHint={firstDraftError}
          onSave={handleCreate}
        />
      }
    >
      <SettingsGroup
        title="Skill bundle"
        description={
          <>
            Keep the core workflow in <span className="font-mono">SKILL.md</span>. Add supporting
            docs, scripts, and assets as bundle files so agents can load only what they need.
          </>
        }
      >
        <SkillBundleEditor
          skillContent={content}
          onSkillContentChange={handleContentChange}
          files={files}
          onFilesChange={setFiles}
          disabled={createMut.isPending}
          invalid={invalid}
        />
      </SettingsGroup>
    </SettingsPage>
  )
}
