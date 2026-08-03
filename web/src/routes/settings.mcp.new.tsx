import { useState } from 'react'
import { Plug } from 'lucide-react'

import { useCreateMcpServerMutation } from '@/queries'
import { useToastStore } from '@/stores/useToastStore'
import { ApiValidationError } from '@/api/client'
import { EditorHeaderActions } from '@/components/settings/EditorHeaderActions'
import { McpServerForm } from '@/components/settings/McpServerForm'
import { SettingsGroup, SettingsPage } from '@/components/settings/SettingsLayout'
import {
  draftToServerBody,
  emptyDraft,
  validateDraft,
  type McpServerDraft,
} from '@/components/settings/McpServerDraft'
import { useSettingsNavigate } from '@/contexts/SettingsContext'
import { useRegisterSettingsDirty } from '@/lib/settings-dirty'

const TEMPLATE: McpServerDraft = {
  ...emptyDraft(),
  name: 'new-server',
  command: 'npx',
  argsText: '-y\n@modelcontextprotocol/server-filesystem\n/tmp',
}

function isPristine(draft: McpServerDraft): boolean {
  return (
    draft.name === TEMPLATE.name &&
    draft.transport === TEMPLATE.transport &&
    draft.enabled === TEMPLATE.enabled &&
    draft.capabilities.length === 0 &&
    draft.command === TEMPLATE.command &&
    draft.argsText === TEMPLATE.argsText &&
    draft.envPairs.length === 0 &&
    draft.url === '' &&
    draft.headerPairs.length === 0 &&
    draft.oauthEnabled === TEMPLATE.oauthEnabled &&
    draft.oauthClientIdEnv === TEMPLATE.oauthClientIdEnv &&
    draft.oauthClientSecretEnv === TEMPLATE.oauthClientSecretEnv
  )
}

export function NewMcpServerPage() {
  const [draft, setDraft] = useState<McpServerDraft>(TEMPLATE)
  const [saveError, setSaveError] = useState<string | null>(null)
  const createMut = useCreateMcpServerMutation()
  const push = useToastStore((s) => s.push)
  const navigate = useSettingsNavigate()

  const fieldErrors = validateDraft(draft, { isNew: true })
  const invalid = fieldErrors !== null
  const firstError = fieldErrors ? Object.values(fieldErrors)[0] : null
  const dirty = !isPristine(draft)
  useRegisterSettingsDirty(dirty)

  const handleCreate = async () => {
    setSaveError(null)
    if (invalid) {
      setSaveError(firstError ?? 'Form has validation errors.')
      return
    }
    const result = draftToServerBody(draft)
    if (!result.ok) {
      setSaveError(result.error)
      return
    }
    try {
      await createMut.mutateAsync({ name: draft.name, server: result.body })
      push({
        tone: 'success',
        title: `Created MCP server "${draft.name}"`,
        description: 'Available on next turn.',
      })
      // The draft is persisted, so it must not trigger the discard confirm.
      navigate('/settings/mcp/$name', { params: { name: draft.name }, force: true })
    } catch (err) {
      const msg = err instanceof ApiValidationError ? err.message : String(err)
      setSaveError(msg)
      push({ tone: 'error', title: 'Create failed', description: msg })
    }
  }

  return (
    <SettingsPage
      icon={Plug}
      title="New MCP server"
      actions={
        <EditorHeaderActions
          dirty={dirty}
          invalid={invalid}
          saving={createMut.isPending}
          error={saveError}
          validationHint={firstError}
          onSave={handleCreate}
        />
      }
    >
      <SettingsGroup bare>
        <McpServerForm
          value={draft}
          onChange={setDraft}
          isNew
          disabled={createMut.isPending}
          errors={fieldErrors}
        />
      </SettingsGroup>
    </SettingsPage>
  )
}
