import { useState } from 'react'
import { Sparkles } from 'lucide-react'

import { useCreateSkillMutation } from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import { SettingsGroup, SettingsPage } from '@/components/settings/SettingsLayout'
import { SkillBundleEditor } from '@/components/settings/SkillBundleEditor'
import {
  getSkillBundleChanges,
  type SkillBundleDraftFile,
} from '@/components/settings/skillBundle'
import { skillDraftName, validateSkillDraft } from '@/components/settings/schema'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'

/**
 * Starter ``SKILL.md``. Only ``name`` and ``description`` are required; the
 * description is written in the third person and says both what the Skill
 * does and when to use it, because that is all the agent sees before it
 * decides to read the file. See ``documents/architecture/agent-skills.md``.
 */
export const NEW_SKILL_TEMPLATE = `---
name: new-skill
description: Describes what this skill does and when to use it. Replace this with a third-person summary such as "Reviews pull requests for security issues. Use when the user asks for a code review or mentions vulnerabilities."
---

# New skill

## Instructions

1. State the first concrete step.
2. Continue with the smallest reliable workflow for this task.
3. Explain how to check the result before finishing.

## Additional resources

Put long reference material in separate files next to SKILL.md and link them
here, for example [reference.md](reference.md), so they are read only when
needed.
`

export function NewSkillPage() {
  const [content, setContent] = useState(NEW_SKILL_TEMPLATE)
  const [files, setFiles] = useState<SkillBundleDraftFile[]>([])
  const createMut = useCreateSkillMutation()
  const push = useToastStore((s) => s.push)
  const navigate = useSettingsNavigate()
  const [saveError, setSaveError] = useState<string | null>(null)

  // The folder name is the frontmatter name.
  const name = skillDraftName(content) ?? ''
  const draftErrors = validateSkillDraft(content)
  const invalid = draftErrors !== null
  const firstDraftError = draftErrors ? Object.values(draftErrors)[0] : null
  const dirty = content !== NEW_SKILL_TEMPLATE || files.length > 0
  const saving = createMut.isPending
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
        description: 'Available on the next turn.',
      })
      navigate('/settings/skills/$name', { params: { name }, force: true })
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
      lede="Creates a skill folder in your user skills directory."
      actions={
        <EditorHeaderActions
          dirty={dirty}
          invalid={invalid}
          saving={saving}
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
            <span className="font-mono">name</span> becomes the folder name: lowercase letters,
            digits and single hyphens, up to 64 characters. The agent sees only the name and{' '}
            <span className="font-mono">description</span> until it decides to read{' '}
            <span className="font-mono">SKILL.md</span>. Add reference files, scripts, and assets
            beside it.
          </>
        }
      >
        <SkillBundleEditor
          skillContent={content}
          onSkillContentChange={setContent}
          files={files}
          onFilesChange={setFiles}
          disabled={saving}
          invalid={invalid}
        />
      </SettingsGroup>
    </SettingsPage>
  )
}
