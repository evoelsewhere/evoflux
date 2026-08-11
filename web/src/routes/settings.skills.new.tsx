import { useState } from 'react'
import { Sparkles } from 'lucide-react'

import { useCreateSkillMutation, useUpdateSkillSettingsMutation } from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import { SettingsGroup, SettingsPage } from '@/components/settings/SettingsLayout'
import { SkillBundleEditor } from '@/components/settings/SkillBundleEditor'
import { SkillModeSelector } from '@/components/settings/SkillModeSelector'
import { SkillRuntimeControls } from '@/components/settings/SkillRuntimeControls'
import {
  getSkillBundleChanges,
  type SkillBundleDraftFile,
} from '@/components/settings/skillBundle'
import { validateNewSkillDraft } from '@/components/settings/schema'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'
import { ALL_SKILL_MODES, skillModesEqual } from '@/lib/skill-modes'
import type { SkillMode } from '@/api/types'

const TEMPLATE = `---
name: new-skill
description: Describe what this skill does and the concrete situations where it should activate. Include boundaries that distinguish it from nearby skills.
---

# New skill

## Use this skill when

- State the positive activation conditions.
- State important near-misses that should not activate it.

## Workflow

1. Define required inputs and the intended output.
2. Perform the smallest reliable workflow for this specialty.
3. Read a bundled reference only at the step that needs it.
4. Verify the result with observable checks before handing it off.

## Output contract

- Specify the artifact, answer, or code change the skill must produce.
- Report evidence, uncertainty, and remaining risks.
`

const EVOFLUX_METADATA = `interface:
  display_name: New skill
  short_description: A focused reusable workflow for EvoFlux
  default_prompt: Use $new-skill for this task.
policy:
  allow_implicit_invocation: true
`

const TRIGGER_EVALS = `{
  "skill": "new-skill",
  "cases": [
    {
      "prompt": "A realistic request that should activate this workflow.",
      "should_trigger": true,
      "reason": "Replace with the distinguishing activation signal."
    },
    {
      "prompt": "A nearby request that the base agent can handle without this workflow.",
      "should_trigger": false,
      "reason": "Replace with the boundary that prevents over-triggering."
    }
  ]
}
`

function scaffoldFiles(): SkillBundleDraftFile[] {
  return [
    {
      path: 'agents/evoflux.yaml',
      content: EVOFLUX_METADATA,
      encoding: 'utf-8',
      size: 0,
      mediaType: 'application/yaml',
      editable: true,
    },
    {
      path: 'evals/trigger-cases.json',
      content: TRIGGER_EVALS,
      encoding: 'utf-8',
      size: 0,
      mediaType: 'application/json',
      editable: true,
    },
  ]
}

function scaffoldDisplayName(name: string): string {
  if (name === 'new-skill') return 'New skill'
  return name
    .split('-')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function NewSkillPage() {
  const [content, setContent] = useState(TEMPLATE)
  const [files, setFiles] = useState<SkillBundleDraftFile[]>(scaffoldFiles)
  const [name, setName] = useState('new-skill')
  const [skillModes, setSkillModes] = useState<SkillMode[]>(() => [...ALL_SKILL_MODES])
  const [allowImplicitInvocation, setAllowImplicitInvocation] = useState(true)
  const [userInvocable, setUserInvocable] = useState(true)
  const createMut = useCreateSkillMutation()
  const updateSettingsMut = useUpdateSkillSettingsMutation()
  const push = useToastStore((s) => s.push)
  const navigate = useSettingsNavigate()
  const [saveError, setSaveError] = useState<string | null>(null)

  const handleContentChange = (raw: string) => {
    setContent(raw)
    const match = /^\s*---[\s\S]*?name:\s*([A-Za-z0-9._/-]+)/m.exec(raw)
    if (match && match[1] !== name) {
      const nextName = match[1]
      setFiles((current) =>
        current.map((file) =>
          file.originalPath || file.content === null
            ? file
            : {
                ...file,
                content: file.content
                  .replaceAll(name, nextName)
                  .replace(
                    `display_name: ${scaffoldDisplayName(name)}`,
                    `display_name: ${scaffoldDisplayName(nextName)}`,
                  ),
              },
        ),
      )
      setName(nextName)
    }
  }

  const draftErrors = validateNewSkillDraft(content)
  const invalid = draftErrors !== null
  const firstDraftError = draftErrors ? Object.values(draftErrors)[0] : null
  const dirty =
    content !== TEMPLATE ||
    files.length > 0 ||
    !skillModesEqual(skillModes, ALL_SKILL_MODES) ||
    !allowImplicitInvocation ||
    !userInvocable
  const saving = createMut.isPending || updateSettingsMut.isPending
  useRegisterSettingsDirty(dirty)

  const handleCreate = async () => {
    setSaveError(null)
    if (invalid) {
      setSaveError(firstDraftError ?? 'Form has validation errors.')
      return
    }
    let created = false
    try {
      const bundle = getSkillBundleChanges(files, [])
      const result = await createMut.mutateAsync({
        name,
        content,
        files: bundle.files,
        modes: skillModes,
      })
      created = true
      if (
        result.allow_implicit_invocation !== allowImplicitInvocation ||
        result.user_invocable !== userInvocable
      ) {
        await updateSettingsMut.mutateAsync({
          name,
          settings: {
            settings_id: result.settings_id,
            modes: skillModes,
            allow_implicit_invocation: allowImplicitInvocation,
            user_invocable: userInvocable,
          },
        })
      }
      push({
        tone: 'success',
        title: `Created skill "${name}"`,
        description: 'Active on next turn.',
      })
      navigate('/settings/skills/$name', { params: { name }, force: true })
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      if (created) {
        const partial = `The skill bundle was created, but its runtime settings were not saved: ${msg}`
        push({
          tone: 'info',
          title: 'Skill created; settings failed',
          description: partial,
        })
        navigate('/settings/skills/$name', { params: { name }, force: true })
      } else {
        setSaveError(msg)
        push({ tone: 'error', title: 'Create failed', description: msg })
      }
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
          saving={saving}
          error={saveError}
          validationHint={firstDraftError}
          onSave={handleCreate}
        />
      }
    >
      <SettingsGroup
        title="Availability"
        description="Choose every application mode where this workflow is relevant."
      >
        <SkillModeSelector
          value={skillModes}
          onChange={setSkillModes}
          disabled={saving}
        />
      </SettingsGroup>

      <SettingsGroup
        title="Discovery"
        description="Choose how agents and users can find and activate this skill after creation. These controls are independent."
      >
        <SkillRuntimeControls
          allowImplicitInvocation={allowImplicitInvocation}
          userInvocable={userInvocable}
          onAllowImplicitInvocationChange={setAllowImplicitInvocation}
          onUserInvocableChange={setUserInvocable}
          disabled={saving}
        />
      </SettingsGroup>

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
          disabled={saving}
          invalid={invalid}
        />
      </SettingsGroup>
    </SettingsPage>
  )
}
