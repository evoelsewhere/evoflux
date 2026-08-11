/**
 * useSlashCommandRegistry — the composer's slash-command subsystem for
 * TeamChatView (extracted unchanged).
 *
 * Owns the built-in command list (including durable goal controls), the
 * user-defined commands / snippets / runnable workflows queries and their
 * flattening into ``SlashCommand[]`` / ``SnippetCommand[]``, and every
 * submit-time interceptors: built-ins, ``/goal*``, ``/workflow`` (with the
 * RunInputsDialog request state) and server-side expansion of
 * user-defined commands.
 */
import { useCallback, useMemo, useState, type RefObject } from 'react'
import { renderCommand, renderSnippet, resolveApiUrl, runWorkflow } from '@/api/client'
import { useCommandsQuery } from '@/queries/useCommandsQuery'
import { useSkillFilesQuery } from '@/queries/useSkillFilesQuery'
import { useSnippetsQuery } from '@/queries/useSnippetsQuery'
import { useWorkflowsQuery } from '@/queries/useWorkflowsQuery'
import { useTeamStore } from '@/stores/useTeamStore'
import { useToastStore } from '@/stores/useToastStore'
import { parseGoalCommand } from '@/lib/parseGoalCommand'
import { mapWorkflowArgs, parseWorkflowCommand } from '@/lib/parseWorkflowCommand'
import type { RunInputsRequest } from '../RunInputsDialog'
import type { InputBarHandle, SlashCommand, SnippetCommand } from '../InputBar'
import type { MessageAttachment, SkillMode } from '@/api/types'

async function attachmentToFile(att: MessageAttachment): Promise<File | null> {
  const url = resolveApiUrl(att.url)
  if (!url) return null
  const res = await fetch(url)
  if (!res.ok) return null
  const blob = await res.blob()
  return new File(
    [blob],
    att.original_name ?? att.filename ?? 'attachment',
    { type: att.media_type ?? blob.type },
  )
}

interface UseSlashCommandRegistryArgs {
  mode: 'work' | 'coding' | 'aim'
  workspace: string | null
  agentWorkspace: string | null
  /** Every repository root for a project session; single-repo sessions pass one root. */
  workspaceRoots?: readonly string[]
  /** Route prop — fallback for ``startWorkflowRun`` before the store commits. */
  sessionId: string | undefined
  sessionIdState: string | null
  selectedModel: string
  selectedThinkingLevel: string | null
  inputRef: RefObject<InputBarHandle | null>
  handleNewSession: () => void
}

export function useSlashCommandRegistry({
  mode,
  workspace,
  agentWorkspace,
  workspaceRoots,
  sessionId,
  sessionIdState,
  selectedModel,
  selectedThinkingLevel,
  inputRef,
  handleNewSession,
}: UseSlashCommandRegistryArgs) {
  const pushToast = useToastStore((s) => s.push)
  const [runInputsRequest, setRunInputsRequest] = useState<RunInputsRequest | null>(null)
  const skillMode: SkillMode = mode

  // Shell shortcut: start a message with `!` to run the rest as a shell command.
  // Slash commands for the input bar (type / to trigger).
  // Built-ins execute immediately on pick; user-defined commands are inserted
  // into the textarea (``keepInputOpen``) so the user can append
  // ``$ARGUMENTS`` before submitting.
  const commandsQ = useCommandsQuery(agentWorkspace)
  const skillsQ = useSkillFilesQuery({
    workspaces: workspaceRoots?.length
      ? workspaceRoots
      : agentWorkspace
        ? [agentWorkspace]
        : [],
    mode: skillMode,
  })
  const snippetsQ = useSnippetsQuery(mode === 'coding' ? agentWorkspace : null)
  const userCommandNames = useMemo(
    () => new Set<string>((commandsQ.data?.commands ?? []).map((c) => c.name)),
    [commandsQ.data],
  )
  const workflowsQ = useWorkflowsQuery(
    mode === 'coding' || mode === 'aim' ? workspace : null,
  )
  // Approved + valid definitions matching the session scope (plan §9.1):
  // work sessions list work-scope only; coding/aim sessions additionally
  // list their own scope. Unapproved/invalid → omitted (gating by omission).
  const runnableWorkflows = useMemo(
    () =>
      (workflowsQ.data?.workflows ?? []).filter(
        (wf) =>
          wf.approved &&
          wf.valid &&
          (wf.scope === 'work' || wf.scope === mode),
      ),
    [workflowsQ.data, mode],
  )
  const slashCommands: SlashCommand[] = [
    { id: 'stop', label: 'Stop', description: 'Stop all working agents' },
    { id: 'continue', label: 'Continue', description: 'Continue the last assistant response' },
    { id: 'compact', label: 'Compact', description: 'Summarize and compact this session' },
    { id: 'shell', label: 'Shell', description: 'Run a shell command (prefix your command with !)' },
    { id: 'undo', label: 'Undo', description: 'Undo the previous message' },
    { id: 'redo', label: 'Redo', description: 'Restore all undone messages back to the live tip' },
    { id: 'new', label: 'New Chat', description: 'Start a fresh team conversation' },
    { id: 'init', label: 'Init', description: 'Create or update AGENTS.md for this project' },
    { id: 'btw', label: 'btw', description: 'Open side chat with read-only access to this session' },
    { id: 'goal', label: 'goal <objective>', displayName: 'goal', insertText: 'goal', description: 'Start a durable autonomous goal', keepInputOpen: true },
    { id: 'goal:budget', label: 'goal:budget <tokens>', displayName: 'goal:budget', insertText: 'goal:budget', description: 'Set a token budget, or use none', keepInputOpen: true },
    { id: 'goal:pause', label: 'goal:pause', displayName: 'goal:pause', description: 'Pause the active goal' },
    { id: 'goal:resume', label: 'goal:resume', displayName: 'goal:resume', description: 'Resume the paused goal' },
    { id: 'goal:stop', label: 'goal:stop', displayName: 'goal:stop', description: 'Remove the session goal' },
    {
      id: 'skill',
      label: 'skill:',
      displayName: 'skill:',
      insertText: 'skill:',
      description: 'Choose a skill to use for this message',
      category: 'skill',
      keepInputOpen: true,
      appendSpace: false,
      hideAfterPrefix: 'skill:',
    },
    ...(skillsQ.data?.skills ?? [])
      .filter(
        (skill) =>
          skill.valid &&
          skill.user_invocable !== false &&
          (skill.modes ?? ['work', 'coding', 'aim']).includes(skillMode),
      )
      .map((skill) => {
        const skillName = skill.name.replace('/', ':')
        const directive = `skill:${skillName}`
        const starter = (skill.default_prompt ?? '')
          .replaceAll(`$${skill.name}`, '')
          .trim()
        return {
          id: directive,
          label: skill.display_name || skillName,
          displayName: directive,
          insertText: starter ? `${directive} ${starter}` : directive,
          description:
            skill.short_description || skill.description || `Load the ${skillName} skill`,
          category: 'skill',
          keepInputOpen: true,
          // Keep the root ``/`` menu compact. Skill choices appear only once
          // the user enters the dedicated ``/skill:`` namespace.
          filterPrefix: 'skill:',
        }
      }),
    ...runnableWorkflows.map((wf) => ({
      id: `workflow-${wf.name}`,
      label: `workflow ${wf.name}`,
      displayName: `workflow ${wf.name}`,
      insertText: `workflow ${wf.name}`,
      description: wf.description || `Run the ${wf.name} workflow`,
      category: 'workflow',
      keepInputOpen: true,
    })),
    ...(commandsQ.data?.commands ?? []).map((c) => {
      const displayName = c.name.replace('/', ':')
      return {
        id: c.name,
        label: displayName,
        displayName,
        insertText: displayName,
        description: c.description || `Custom command (${c.source})`,
        category: 'command',
        keepInputOpen: true,
      }
    }),
  ]

  const snippetCommands: SnippetCommand[] = (snippetsQ.data?.snippets ?? []).map((item) => ({
    id: item.name,
    label: item.name.replace('/', ':'),
    description: item.description || `Snippet (${item.source})`,
    category: 'snippet',
  }))

  const handleSnippetCommand = useCallback(async (id: string) => {
    if (!agentWorkspace) return null
    try {
      const res = await renderSnippet(id, agentWorkspace)
      return res.content
    } catch (err) {
      pushToast({
        tone: 'error',
        title: `Failed to render #${id.replace('/', ':')}`,
        description: (err as Error).message,
      })
      return null
    }
  }, [agentWorkspace, pushToast])

  const runGoalCommand = useCallback(async (command: string, objective?: string) => {
    const current = useTeamStore.getState()
    await current.sendGoalCommand(command, objective, {
      mode,
      workspace,
      model: current.sessionId ? selectedModel || null : null,
      thinkingLevel: current.sessionId ? selectedThinkingLevel || null : null,
      fastMode: current.sessionFastMode,
    })
  }, [mode, workspace, selectedModel, selectedThinkingLevel])

  const handleSlashCommand = useCallback((id: string) => {
    switch (id) {
      case 'stop':
        useTeamStore.getState().stopTeam()
        break
      case 'continue':
        useTeamStore.getState().continueTeam()
        break
      case 'compact':
        useTeamStore.getState().compactTeam()
        break
      case 'shell':
        inputRef.current?.setValue('! ')
        inputRef.current?.focus()
        break
      case 'undo':
        void useTeamStore.getState().undoTeam().then(async (response) => {
          const message = response?.message
          if (!message || message.role !== 'user' || message.is_summary) return
          inputRef.current?.setValue(message.content ?? '')
          const attachments = message.attachments ?? []
          const files = (
            await Promise.all(attachments.map((att) => attachmentToFile(att)))
          ).filter((file): file is File => file !== null)
          inputRef.current?.setFiles(files)
          inputRef.current?.focus()
        })
        break
      case 'redo':
        void useTeamStore.getState().redoTeam().then(() => {
          inputRef.current?.setValue('')
          inputRef.current?.setFiles([])
        })
        break
      case 'new':
        handleNewSession()
        break
      case 'goal:pause':
      case 'goal:resume':
      case 'goal:stop':
        void runGoalCommand(`/${id}`)
        break
      case 'init':
        // Prompt body lives on the backend so it can be tweaked without a
        // web rebuild and stays the single source of truth.
        void renderCommand('init', '', agentWorkspace)
          .then((res) =>
            useTeamStore.getState().sendMessage(res.content, undefined, {
              mode,
              workspace: agentWorkspace,
            }),
          )
          .catch((err: Error) =>
            pushToast({
              tone: 'error',
              title: 'Failed to start /init',
              description: err.message,
            }),
          )
        break
      case 'btw':
        // Handled by the parent (TeamChatView) via onSlashCommand callback
        break
    }
  }, [handleNewSession, runGoalCommand, mode, agentWorkspace, pushToast, inputRef])

  const tryHandleBuiltinGoalCommand = useCallback(async (content: string): Promise<boolean> => {
    const parsed = parseGoalCommand(content)
    switch (parsed.kind) {
      case 'none':
        return false
      case 'invalid':
        pushToast({
          tone: 'error',
          title: 'Invalid /goal command',
          description: 'Use /goal <objective>, /goal, /goal:pause, /goal:resume, /goal:budget <tokens|none>, or /goal:stop.',
        })
        return true
      case 'budget_invalid':
        pushToast({
          tone: 'error',
          title: '/goal:budget needs a valid budget',
          description: 'Enter a positive token count, or use none for no limit.',
        })
        return true
      case 'start':
        await runGoalCommand(content, parsed.objective)
        return true
      case 'status':
        await runGoalCommand('/goal')
        return true
      case 'budget':
        await runGoalCommand(content)
        return true
      case 'pause':
      case 'resume':
      case 'stop':
        await runGoalCommand(`/goal:${parsed.kind}`)
        return true
    }
  }, [pushToast, runGoalCommand])

  const startWorkflowRun = useCallback(
    async (name: string, values: Record<string, unknown>) => {
      const sid = sessionIdState ?? sessionId
      if (!sid) throw new Error('No session yet — send a message first.')
      await runWorkflow(name, sid, values, agentWorkspace)
    },
    [sessionIdState, sessionId, agentWorkspace],
  )

  /** FE-intercepted /workflow (plan §9.1, F17): the raw slash text is never
   *  sent as a chat message; positional args map onto declared inputs and
   *  missing required ones open RunInputsDialog. */
  const tryHandleWorkflowCommand = useCallback(
    async (content: string): Promise<boolean> => {
      const parsed = parseWorkflowCommand(content)
      if (parsed.kind === 'none') return false
      if (parsed.kind === 'missing_name') {
        pushToast({
          tone: 'error',
          title: '/workflow needs a name',
          description: 'e.g. "/workflow bug-triage TICKET-1".',
        })
        return true
      }
      const wf = runnableWorkflows.find((w) => w.name === parsed.name)
      if (!wf) {
        pushToast({
          tone: 'error',
          title: `No runnable workflow '${parsed.name}'`,
          description: 'It may be unapproved, invalid, or out of scope here.',
        })
        return true
      }
      const mapped = mapWorkflowArgs(wf.inputs, parsed.args)
      if (mapped.errors.length > 0) {
        pushToast({ tone: 'error', title: 'Bad workflow arguments', description: mapped.errors.join('; ') })
        return true
      }
      if (mapped.missing.length > 0) {
        setRunInputsRequest({ name: wf.name, inputs: wf.inputs, prefilled: mapped.values })
        return true
      }
      try {
        await startWorkflowRun(wf.name, mapped.values)
        pushToast({ tone: 'success', title: `${wf.name} started` })
      } catch (err) {
        pushToast({
          tone: 'error',
          title: `Failed to start ${wf.name}`,
          description: err instanceof Error ? err.message : String(err),
        })
      }
      return true
    },
    [runnableWorkflows, pushToast, startWorkflowRun],
  )

  /** If *content* starts with a known user-defined command, render server-side
   *  and return the expanded body; otherwise return *content* unchanged. */
  const expandUserCommand = useCallback(
    async (content: string): Promise<string> => {
      if (!content.startsWith('/')) return content
      if (content === '/goal' || content.startsWith('/goal:') || content.startsWith('/goal ')) return content
      // The command name may include slashes (nested folders), so we
      // greedily match the longest known prefix instead of splitting on
      // the first space. Tokens are separated by whitespace.
      const rest = content.slice(1)
      // Try progressively shorter prefixes — start with the full first
      // line, peel back to the longest known command name.
      const firstLine = rest.split('\n', 1)[0]
      const tokens = firstLine.split(' ')
      for (let n = tokens.length; n > 0; n--) {
        const candidate = tokens.slice(0, n).join(' ').trim()
        const commandName = candidate.replace(':', '/')
        if (userCommandNames.has(commandName)) {
          const argsHead = tokens.slice(n).join(' ')
          const restOfMessage = rest.slice(firstLine.length)
          const args = (argsHead + restOfMessage).trim()
          try {
            const res = await renderCommand(commandName, args, agentWorkspace)
            return res.content
          } catch (err) {
            pushToast({
              tone: 'error',
              title: `Failed to render /${candidate}`,
              description: (err as Error).message,
            })
            return content
          }
        }
      }
      return content
    },
    [userCommandNames, agentWorkspace, pushToast],
  )

  return {
    slashCommands,
    snippetCommands,
    handleSlashCommand,
    handleSnippetCommand,
    tryHandleBuiltinGoalCommand,
    tryHandleWorkflowCommand,
    expandUserCommand,
    startWorkflowRun,
    runInputsRequest,
    setRunInputsRequest,
    runGoalCommand,
  }
}
