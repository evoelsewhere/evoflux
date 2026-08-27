import type { HelpArticle, HelpCategory } from '../types'

export const HELP_CATEGORIES_EN: HelpCategory[] = [
  {
    id: 'getting-started',
    label: 'Getting started',
    description: 'Install, connect a model, and run your first session',
  },
  {
    id: 'modes',
    label: 'Modes',
    description: 'Work and Coding',
  },
  {
    id: 'chat',
    label: 'Chat & team',
    description: 'Lead, specialists, views, and permissions',
  },
  {
    id: 'composer',
    label: 'Composer',
    description: 'Mentions, attachments, skills, and workflows',
  },
  {
    id: 'slash',
    label: 'Slash & goals',
    description: 'Built-in slash commands and durable goals',
  },
  {
    id: 'sessions',
    label: 'Sessions & folders',
    description: 'Pins, folders, and shared context',
  },
  {
    id: 'workbench',
    label: 'Workbench',
    description: 'Panels beside chat',
  },
  {
    id: 'coding',
    label: 'Coding',
    description: 'Repos, projects, git, graph, and PRs',
  },
  {
    id: 'memory',
    label: 'Memory & Dream',
    description: 'Wiki knowledge and synthesis',
  },
  {
    id: 'scheduler',
    label: 'Scheduler',
    description: 'Cron and one-shot agent tasks',
  },
  {
    id: 'browser',
    label: 'Browser & WebBridge',
    description: 'Built-in browser and real Chrome/Edge',
  },
  {
    id: 'plugins',
    label: 'Plugins',
    description: 'Portable Agent Skills and MCP packages',
  },
  {
    id: 'settings',
    label: 'Settings & safety',
    description: 'Providers, agents, MCP, sandbox',
  },
  {
    id: 'shortcuts',
    label: 'Keyboard shortcuts',
    description: 'Command on macOS, Ctrl on Windows/Linux',
  },
  {
    id: 'troubleshooting',
    label: 'Troubleshooting',
    description: 'Connection, health, and diagnostics',
  }
]

export const HELP_ARTICLES_EN: HelpArticle[] = [
  {
    id: 'getting-started',
    category: 'getting-started',
    title: 'Getting started with EvoFlux',
    summary:
      'Install the desktop app or run from source, connect a bring-your-own model provider, confirm the sidecar is healthy, then run a first Work chat or open a Coding repo. This guide is the onboarding path from cold launch to a verified streaming session.',
    keywords: [
      'start',
      'install',
      'setup',
      'provider',
      'first',
      'onboarding',
      'desktop',
      'make dev',
      'sidecar',
      'HealthDot',
      'BYOM',
      'Welcome',
      'bun install',
      'bắt đầu',
      'cài đặt',
      'kết nối',
      'nhà cung cấp',
      'はじめ',
      'セットアップ',
      'インストール',
      'プロバイダ'
],
    setup:
      'Packaged desktop app launches the FastAPI sidecar automatically. From source: Terminal 1 `make dev` (API + Vite), Terminal 2 `make -C desktop dev` (Tauri shell). Frontend deps: `cd web && bun install`. Have at least one provider credential or local daemon (Ollama, etc.) ready before the first chat.',
    tricks: [
      'Click the HealthDot in the sidebar footer to jump straight to Connection settings when the backend looks unhealthy.',
      'Settings → Providers is the first stop — API key, OAuth, or a local daemon (Ollama, etc.). Without a configured provider, the composer has nothing to stream.',
      'Appearance → Display language supports English, Vietnamese, and Japanese for UI chrome; chat content stays in whatever language you write.',
      'Cold start shows Welcome until the sidecar and team registry are ready — wait before retrying chat or hunting “empty team” bugs.',
      'After a provider is connected, send a short Work message (“ping — reply with ok”) to verify streaming end-to-end before opening a large repo.',
      'In Coding, clicking a repo focuses the workspace; use + / New chat to create a session. Focus alone never starts a transcript.',
      'Open Guidelines anytime from the sidebar Help button (this modal); the command palette stays on Ctrl+P and is for actions, not docs.',
      'If HealthDot is green but chat fails, open Settings → Diagnostics before reinstalling — subsystem checks often beat a full wipe.',
      'Keep BYOM credentials out of chat transcripts; configure them only under Settings → Providers.'
],
    blocks: [
      {
        type: 'p',
        text: 'EvoFlux is a local-first desktop harness: Tauri shell → React UI → FastAPI sidecar on your machine. Models are bring-your-own (BYOM). Nothing in the core loop requires a vendor cloud account beyond the model provider you choose. Transcripts, wiki memory, sandbox policy, and git work stay on your disk.',
      },
      {
        type: 'p',
        text: 'Local ownership is the product bet. The two modes (Work and Coding) share one team harness — Lead/specialists, composer, permissions, and workbench — so you learn the chrome once and switch surfaces for the job. Use Work for research and throwaway folders; use Coding for persistent repos.',
      },
      {
        type: 'p',
        text: 'Packaged install: download the desktop build for your OS and launch it. The shell starts a bundled sidecar on an ephemeral port with a token handshake — you normally never type a backend URL. From source: install web deps (`cd web && bun install`), run `make dev` for API + Vite, then `make -C desktop dev` for the Tauri window pointed at the Vite URL.',
      },
      {
        type: 'tips',
        items: [
          '1) Confirm HealthDot is green (or open Connection if not) and wait until Welcome clears.',
          '2) Settings → Providers → connect at least one model; confirm it appears as configured.',
          '3) Stay in Work and send a short first chat, or switch to Coding and open a git repository.',
          '4) Optional: switch to Coding → open a repo or project and start a session.',
          '5) Explore workbench tools (Terminal, Files, Memory, Browser) once a session exists.',
          '6) Optional hardening: review Settings → Sandbox deny globs before enabling auto or bypass.'
],
      },
      {
        type: 'p',
        text: 'HealthDot lives in the sidebar footer next to the theme toggle. Red or amber means the UI cannot reach a healthy backend — fix Connection before chasing chat or tool errors. Settings → Diagnostics runs live subsystem checks when you need more than a binary health signal.',
      },
      {
        type: 'p',
        text: 'Common first-day mistakes: sending chat while Welcome is still up; debugging “no models” as a connection failure instead of opening Providers; assuming a Coding repo click creates a chat; bookmarking `/scheduler` (it redirects home — use Ctrl+S); treating Guidelines and the Ctrl+P palette as the same surface.',
      },
      {
        type: 'p',
        text: 'When to stay in Work vs jump modes: use Work for browser tasks, docs, and folder-organized research with no git lifecycle. Switch to Coding as soon as you need Changes, Graph, Review, worktrees, or AGENTS.md.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: after first chat works, open Memory (Ctrl+M) so you know where durable notes will land.',
          'Cross-feature: skim permission shield modes (keys 1–5) before letting agents edit a real repo.',
          'Cross-feature: Ctrl+P → Search “Diagnostics” if health is green but a tool panel stays empty.',
          'From source only: never start the Tauri shell without `make dev` already serving the API.'
],
      },
      {
        type: 'p',
        text: 'Next reads: modes overview for when to use Work / Coding; Providers for BYOM setup; Connection if HealthDot stays red; Troubleshooting for the ordered fix checklist.',
      }
],
    related: [
      'modes-overview',
      'providers-settings',
      'connection-settings',
      'troubleshooting-connection',
      'keyboard-shortcuts'
],
    openAction: { type: 'settings', path: 'providers' },
  },
  {
    id: 'modes-overview',
    category: 'modes',
    title: 'Work and Coding modes',
    summary:
      'Two product modes share one harness but different workspaces, specialists, and default tools. The mode switcher remembers the last route per mode so returning to Coding lands where you left off.',
    keywords: [
      'mode',
      'work',
      'coding',
      'switch',
      'cowork',
      'route',
      'mode switcher',
      'chế độ',
      'làm việc',
      'mã hóa',
      'モード',
      'ワーク',
      'コーディング'
],
    tricks: [
      'The mode switcher remembers the last route per mode — return to Coding and you land on the same workspace path you left.',
      'Collapsed sidebar disappears completely; use Ctrl+B or the floating sidebar button to restore it.',
      'Settings hides the mode switcher while you configure the app; leave Settings to switch modes again.',
      'Work is best for research, docs, browser tasks, and throwaway scripts; Coding for persistent repos.',
      'Permission modes, slash commands, and most workbench tools work across modes; Overview / Graph / Changes / Review are Coding-scoped.',
      'Do not open a git monorepo in Work expecting Changes/Review — switch to Coding so source-control tools attach.',
      'Use Work folders + share_context for parallel research threads; use Coding projects when repos must stay linked.',
      'Mode memory is per mode, not per window — if you expected a blank Coding home, check whether an old workspace route was restored.'
],
    blocks: [
      {
        type: 'p',
        text: 'EvoFlux exposes two top-level modes in the sidebar: Work (cowork sandbox) and Coding (repositories and projects). Each mode has its own sidebar tree and session list, but the Lead/specialist team, composer, and permissions model stay familiar so shortcuts and Guidelines apply everywhere.',
      },
      {
        type: 'p',
        text: 'Separating modes keeps general cowork from polluting git workspaces. Shared chrome means you are not relearning permissions, slash, or workbench when you switch.',
      },
      {
        type: 'p',
        text: 'Work sessions use a private session folder or another local folder you select; no persistent multi-repo project is required. Coding opens a git repo or multi-repo project; agents edit real trees with graph, git, worktrees, and PR review.',
      },
      {
        type: 'tips',
        items: [
          'Work — research, documents, browser tasks, quick scripts, folder-organized chats.',
          'Coding — single repos, multi-repo projects, worktrees, graph, Changes, Review.',
          'Mode memory — last route per mode is restored when you switch back.',
          'Settings — mode switcher hidden until you leave the settings routes.'
],
      },
      {
        type: 'p',
        text: 'When to use vs not: prefer Work when the output is notes, browser evidence, or a disposable folder. Prefer Coding when you need commits, PRs, worktrees, or AGENTS.md.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: Ctrl+B toggles the mode sidebar the same way in every mode.',
          'Cross-feature: Scheduler tasks target work or coding mode explicitly — set the right mode on the task.',
          'Cross-feature: Skills and workflows can be scoped per mode in Settings; a Coding-only workflow stays hidden in Work.'
],
      },
      {
        type: 'p',
        text: 'Step-by-step mode switch: (1) expand the sidebar if needed, (2) click Work or Coding in the mode switcher, (3) pick or create a session, (4) confirm the workbench tools you need are available for that mode before prompting the agent.',
      }
],
    related: [
      'coding-workspaces',
      'getting-started',
      'sessions-folders',
      'workbench-tools'
],
  },
  {
    id: 'chat-team',
    category: 'chat',
    title: 'Lead and specialists',
    summary:
      'The Lead owns the user-facing transcript; specialists activate on demand and work in parallel through a shared mailbox. Switch Agent, Split, and Monitor views while watching the context budget bar so long runs stay recoverable.',
    keywords: [
      'lead',
      'specialist',
      'team',
      'agent',
      'split',
      'monitor',
      'mailbox',
      'Ctrl+V',
      'context budget',
      'auto-split',
      'đội',
      'trưởng nhóm',
      'chuyên gia',
      'エージェント',
      'リード',
      'スプリット'
],
    setup:
      'Open any session. Configure team membership, models, and tools under Settings → Agents (scoped to work / coding). Session pills on the composer override model, thinking level, and fast mode for the current chat only.',
    tricks: [
      'Ctrl+V cycles Agent ↔ Split on desktop (disabled while the focused field uses paste).',
      'Command palette has Next / Previous Agent when workers are active — faster than hunting the identity dropdown.',
      'Auto-split can open when specialists activate so you can watch them work without hunting the view menu.',
      'Monitor view gives an overview of activity across the team when many workers are live.',
      'The context budget bar on the workbench uses the model’s context_length and summary_trigger_tokens — compact early if it climbs.',
      'Configure models, skills, tools, and permissions per agent in Settings → Agents.',
      'Use the topbar Lead selector to choose a Work or Coding lead for the current idle session. Each option lists only that lead’s owned members; switching is disabled during active work.',
      'Settings → Agents groups members under collapsible lead teams. Delegation cards read “lead delegated → member#N”; the lead still owns coordination and final synthesis.',
      'Session pills on the composer set model, thinking level, and fast mode for the current chat only.',
      'Keep simple tasks on the Lead; fan-out only when parallelism clearly shortens wall time.',
      'Lead-only tools (ask_user, plan mode helpers, some worktree helpers) are never granted to specialists — do not expect workers to approve plans.'
],
    blocks: [
      {
        type: 'p',
        text: 'Every session persists one selected Lead agent that owns the user-facing transcript. Each mode can define multiple leads, and each member belongs to exactly one lead through Settings → Agents. Complex work is broken into subtasks with goals and constraints; only the selected lead’s specialists activate on demand, exchange results through a shared mailbox, and return evidence before the Lead answers you.',
      },
      {
        type: 'p',
        text: 'Keeping simple tasks on the Lead avoids unnecessary fan-out and token burn. Parallel specialists shorten wall time for research, coding, migration, and review while the mailbox keeps coordination structured instead of dumping every worker’s dump into one chat.',
      },
      {
        type: 'p',
        text: 'View modes: Agent (single focus on one agent), Split (Lead + workers side by side), Monitor (activity overview). Use the workbench identity dropdown to jump between agents, or palette Next/Previous Agent. Ctrl+V toggles Agent ↔ Split on desktop. When auto-split is enabled, activating specialists may open Split automatically.',
      },
      {
        type: 'p',
        text: 'Context budget — the bar near the workbench header reflects token usage against the active model’s context window. When usage approaches the summary trigger, run /compact or start a fresh chat rather than waiting for a hard failure. Budget pressure often looks like “the agent forgot earlier files” before it looks like an error.',
      },
      {
        type: 'tips',
        items: [
          'Agent — deep focus on one transcript (Lead or a selected specialist).',
          'Split — watch Lead and workers in parallel panes.',
          'Monitor — overview when many agents are active.',
          'Teams are scoped to work / coding in Settings → Agents.',
          'Mailbox — structured specialist results; Lead synthesizes for you.'
],
      },
      {
        type: 'p',
        text: 'Step-by-step for a multi-agent task: (1) state the outcome and constraints to the Lead, (2) let specialists activate (or ask for parallel research/coding), (3) switch to Split or Monitor to watch progress, (4) answer ask-user prompts promptly, (5) when the context bar climbs, /compact or /new before the next large attachment dump.',
      },
      {
        type: 'p',
        text: 'Common mistakes: pasting huge logs into the Lead while specialists are already summarizing the same files; fighting Ctrl+V while the composer is focused (paste wins); expecting Monitor to show Coding Review PRs (that is a different workbench tool); leaving a specialist selected in Agent view and wondering why your messages feel ignored — switch back to the Lead.',
      },
      {
        type: 'tips',
        items: [
          'When to fan out — multi-file investigation, parallel test/fix, specialist lanes.',
          'When to stay Lead-only — short Q&A, single-file edits, permission-sensitive first passes.',
          'Cross-feature: pair Split with Plan review so you can read the plan while workers idle.',
          'Cross-feature: /btw side chat for meta questions without stopping the team run.'
],
      }
],
    related: [
      'permissions-modes',
      'composer-power',
      'agents-settings',
      'keyboard-shortcuts',
      'side-chat'
],
  },
  {
    id: 'permissions-modes',
    category: 'chat',
    title: 'Permission modes and plan review',
    summary:
      'Control how freely tools run with ask, accept-edits, plan, auto, or bypass — then approve tools Once/Always/Reject and review plans with Accept/Revise/Reject. Filesystem-tool deny globs apply underneath every mode.',
    keywords: [
      'permission',
      'ask',
      'accept-edits',
      'plan',
      'auto',
      'bypass',
      'approve',
      'shield',
      'Once',
      'Always',
      'Reject',
      'ask-user',
      'plan review',
      'quyền',
      'chế độ quyền',
      'phê duyệt',
      '権限',
      'プラン',
      '承認'
],
    setup:
      'Open the shield / permission control on the composer. Keys 1–5 work while that menu is open. Review Settings → Sandbox before enabling auto or bypass on a machine with broad filesystem access.',
    tricks: [
      'With the permission menu open, keys 1–5 jump to ask → accept-edits → plan → auto → bypass.',
      'Ask pauses before every tool call; accept-edits auto-accepts file edits but still asks for shell and destructive ops.',
      'Plan mode records proposed edits/shell until you Accept in the Plan review panel — or Revise / Reject.',
      'Select plan text in the review panel to quote it into a revise message in the composer.',
      'When a tool needs approval, choose Once, Always, or Reject on the permission bar.',
      'Ask-user question modals appear when the agent needs structured answers before continuing — answer to unblock the run.',
      'Goal mode never expands the session’s permissions or sandbox scope — set the shield deliberately before `/goal`.',
      'Bypass skips all permission checks — fastest, but use only in a disposable environment or a host you fully trust.',
      'Always is sticky for matching rules — Prefer Once when you are still learning what the agent wants to run.'
],
    blocks: [
      {
        type: 'p',
        text: 'Each session has a PermissionMode: ask, accept-edits, plan, auto, or bypass. Separately, individual tool calls may still surface Once / Always / Reject, and plan mode surfaces a dedicated Plan review panel with Accept / Revise / Reject. Think of the shield as the session default and the permission bar as per-call overrides.',
      },
      {
        type: 'p',
        text: 'Fine-grained control lets you stay hands-on for risky work (ask), move faster on edits (accept-edits), force an explicit plan gate (plan), run unattended in a trusted tree (auto), or skip prompts entirely (bypass). Permissions decide when to ask; filesystem tools still apply workspace and deny-glob checks. Shell commands run directly on the host after a best-effort denied-path scan.',
      },
      {
        type: 'p',
        text: 'Open the shield control on the composer, pick a mode (or press 1–5). In plan mode, wait for the Plan review panel: Accept executes, Revise focuses the composer (optionally with a quoted selection), Reject stops the plan. Tool prompts offer Once (this call), Always (remember for matching rules), or Reject. Ask-user modals collect structured answers mid-run.',
      },
      {
        type: 'tips',
        items: [
          '1 Ask — pause before every tool call.',
          '2 Accept edits — auto file edits; ask for shell / destructive.',
          '3 Plan — plan then approve before execution.',
          '4 Auto — automatically approve operations.',
          '5 Bypass — skip permission checks entirely.',
          'Filesystem tools — still apply deny globs even under bypass.'
],
      },
      {
        type: 'p',
        text: 'When to use which mode: ask for unfamiliar repos and production-adjacent trees; accept-edits for day-to-day Coding once you trust the tree; plan for multi-step refactors and large changes you want to read first; auto for trusted hosts and scheduled maintenance; bypass only for short, deliberate bursts in disposable environments.',
      },
      {
        type: 'p',
        text: 'Common mistakes: leaving bypass on overnight; confusing Always with “trust this agent forever” (it is rule-matched); switching out of plan mode mid-flight and assuming the pending plan was accepted; ignoring ask-user modals and thinking the team hung; expecting Goal to loosen permissions for unattended work.',
      },
      {
        type: 'tips',
        items: [
          'Step — shield → Plan (3) → send task → Plan review → Accept / Revise / Reject.',
          'Step — on a tool prompt, prefer Once until the pattern is clearly safe.',
          'Cross-feature: pair plan with quote-into-composer for surgical revises.',
          'Cross-feature: tighten Sandbox before auto on multi-repo projects.'
],
      },
      {
        type: 'p',
        text: 'MCP tools inherit the same permission rules as native tools. Approving an MCP call Once/Always follows the same bar; sandbox and outbound policy still apply. If tools are “denied unexpectedly,” check the shield and Settings → Sandbox before reconfiguring MCP.',
      }
],
    related: ['slash-goal', 'sandbox-settings', 'plan-review', 'chat-team', 'agents-settings'],
  },
  {
    id: 'plan-review',
    category: 'chat',
    title: 'Plan review panel',
    summary:
      'In plan permission mode, review the agent’s markdown plan before any recorded edits or shell run. Accept executes, Revise steers with an optional quote, and Reject aborts the planned path so you stay in control of multi-step work.',
    keywords: [
      'plan review',
      'Accept',
      'Revise',
      'Reject',
      'quote',
      'plan mode',
      'markdown plan',
      'Accept & execute',
      'xem kế hoạch',
      'chấp nhận',
      'プランレビュー'
],
    setup:
      'Set permission mode to Plan (key 3 in the shield menu), then send a task that needs multi-step work. Keep the Plan review panel visible — do not switch permission mode until you Accept, Revise, or Reject a pending plan.',
    tricks: [
      'Select text in the plan document to quote it into a revise message — the fastest way to say “change only this section.”',
      'Revise returns focus to the composer so you can steer without rejecting the whole plan.',
      'Reject stops the planned execution path; you can send a new instruction afterward without leftover half-applied steps from that plan turn.',
      'Leaving plan mode mid-flight does not auto-accept a pending plan — resolve Accept / Revise / Reject first when prompted.',
      'After Accept, consider dropping to accept-edits or ask if you want tighter tool prompts during execution.',
      'Use plan mode before Goal for large objectives so the first autonomous stretch starts from an approved outline.',
      'If the plan is vague, Revise with a concrete Definition of Done rather than Accepting and hoping.',
      'Split view helps: keep Plan review open while you glance at specialist status.',
      'Quoted revise chips clear before send if you change your mind — same quote pipeline as transcript selections.'
],
    blocks: [
      {
        type: 'p',
        text: 'Plan review is the gated UI for plan permission mode. The agent drafts a markdown plan; edits and shell stay recorded until you Accept & execute, ask to Revise, or Reject. Nothing in that planned batch should run until Accept — that is the point of the gate.',
      },
      {
        type: 'p',
        text: 'Use plan review when the cost of a wrong direction is high: multi-file refactors, migrations touching shared modules, destructive shell, or any task where you want a readable outline before tools fire. Skip it for one-line fixes and trivial Q&A where ask or accept-edits is enough.',
      },
      {
        type: 'p',
        text: 'Read the plan in the review panel top to bottom: goal, steps, files, risks, and verification. Highlight any section and use quote-into-composer when revising. Accept continues with the approved plan; Reject aborts that plan turn. Pair with ask or accept-edits after acceptance if you want tighter tool prompts during execution.',
      },
      {
        type: 'tips',
        items: [
          'Accept — execute the approved plan path.',
          'Revise — focus composer; optional quoted selection.',
          'Reject — abort this plan turn; send a new instruction.',
          'Quote — select plan text → revise chip above draft.',
          'Shield 3 — enter plan mode before the task, not after tools started.'
],
      },
      {
        type: 'p',
        text: 'Step-by-step: (1) open shield → Plan, (2) describe the outcome and constraints, (3) wait for the Plan review panel, (4) skim risks and file list, (5) Accept, or select a weak section → quote → Revise with corrections, or Reject and rewrite the ask, (6) optionally tighten permission mode for the execution phase.',
      },
      {
        type: 'p',
        text: 'Common mistakes: Accepting unread plans because they “look long enough”; Rejecting when you meant Revise (you lose the useful structure); switching to bypass to “just run it” and losing the audit trail you wanted; assuming Reject deletes prior successful tool calls from earlier turns — it only stops that planned execution path.',
      },
      {
        type: 'tips',
        items: [
          'Good revise prompts name files, tests, and out-of-scope items explicitly.',
          'Bad revise prompts are vague (“make it better”) — quote the weak bullet first.',
          'Cross-feature: Send unrelated meta questions to side chat so the plan thread stays clean.',
          'Cross-feature: after Accept on Coding work, open Changes (Ctrl+G) to verify the diff matches the plan.'
],
      },
      {
        type: 'p',
        text: 'Do not use plan review as a substitute for sandbox policy. A beautiful plan can still propose paths you never want touched — keep deny globs in Settings → Sandbox, and Reject plans that expand scope into secrets, vendor dirs, or unrelated repos.',
      }
],
    related: ['permissions-modes', 'composer-power', 'attachments', 'slash-goal', 'coding-git'],
  },
  {
    id: 'composer-power',
    category: 'composer',
    title: 'Composer power features',
    summary:
      'Use /, !, @, # snippets, attachments, quote selection, Work folder targeting, nested skills, and workflows with RunInputsDialog. Undo restores attachments too, so drafts stay recoverable after a bad send.',
    keywords: [
      'composer',
      'mention',
      '@',
      '#',
      'snippet',
      'attach',
      'drag',
      'paste',
      'skill',
      'workflow',
      'RunInputsDialog',
      'WorkFolderSelector',
      'quote',
      '!',
      'shell',
      'soạn thảo',
      'đính kèm',
      'đề cập',
      '入力',
      '添付',
      'スニペット'
],
    setup:
      'Focus the composer (Ctrl+I). Attachments must be enabled for the session. In Work, WorkFolderSelector sits near the composer to retarget the session folder. In Coding, # snippets require workspace or global snippet definitions.',
    tricks: [
      'Start a message with ! to run a shell command (or pick /shell to prefill bang mode).',
      'Type @ to insert ranked file/folder path references from the active workspace.',
      'In Coding, type # to expand workspace or global snippets into the composer.',
      'Nested skills use /skill:parent:child (colon and slash are interchangeable for nested names).',
      'Workflows open RunInputsDialog when required and never send the raw slash text as chat.',
      'Undo restores the previous user message and its attachments into the composer.',
      'Paste images/files or drag-drop onto the composer when attachments are enabled.',
      'Select transcript text for Add to chat, more details, or Send to side chat.',
      'Prefer @ mentions over pasting whole files — ranked paths keep context precise and cheaper.',
      'Custom commands under .evoflux/commands/ usually insert into the textarea so you can append $ARGUMENTS.'
],
    blocks: [
      {
        type: 'p',
        text: 'The composer is more than a text box: slash menu (/), shell bang (!), path mentions (@), Coding snippets (#), file attachments, quote context chips, WorkFolderSelector for Work sessions, skill directives, and approved workflows. Mastering these affordances is the difference between dumping trees into the prompt and steering with precision.',
      },
      {
        type: 'p',
        text: 'These controls keep context precise without flooding the model. Skills and workflows package repeatable procedures; attachments and quotes pin evidence; WorkFolderSelector retargets the session folder without opening the Files tool. Shell bang is for deliberate commands, not a substitute for Terminal when you need a long interactive session.',
      },
      {
        type: 'p',
        text: 'Type / to open the command menu (built-ins, skills under /skill:, workflows, custom .evoflux/commands/). Prefix with ! for shell. Use @ to pick paths. In Coding, # expands snippets. Drag-drop or paste files onto the bar. On Work sessions, use WorkFolderSelector near the composer to point at a private session folder or another local directory. After /undo, both text and attachments return to the draft.',
      },
      {
        type: 'tips',
        items: [
          '/ — slash commands, skills, workflows, custom commands',
          '! — shell mode for the rest of the line',
          '@ — file/folder mentions',
          '# — snippets (Coding workspaces)',
          'DnD / paste — attachments when enabled',
          'Quote selection — Add to chat or Send to side chat',
          'WorkFolderSelector — retarget Work session folder',
          'RunInputsDialog — workflow parameters before launch'
],
      },
      {
        type: 'p',
        text: 'Step-by-step for a precise Coding ask: (1) @ the files that matter, (2) attach a screenshot or log only if needed, (3) state the outcome and tests, (4) optionally /skill:… for a known procedure, (5) set permission mode, (6) send. For Work research: set WorkFolderSelector, attach sources, quote prior answers, then ask.',
      },
      {
        type: 'p',
        text: 'Common mistakes: sending raw `/workflow name` text hoping it runs (workflows launch through the menu/dialog); nesting skills with spaces instead of `:` / `/`; using # in Work expecting Coding snippets; pasting secrets into the composer instead of configuring Providers; forgetting that /undo restores attachments — re-send carefully if the files were sensitive.',
      },
      {
        type: 'tips',
        items: [
          'When to use ! — short one-liners tied to the chat turn.',
          'When to use Terminal (Ctrl+`) — interactive or long-running processes.',
          'When to use @ — known paths; use Files tool browse when you are still exploring.',
          'Cross-feature: quote → Send to side chat for /btw without stopping Goal.'
],
      },
      {
        type: 'p',
        text: 'Workflows must be approved and valid for the session scope (work / coding) or they stay hidden. Skills appear under /skill: only after they validate in Settings → Skills. If a command is missing, check scope and validation before assuming a slash bug.',
      }
],
    related: [
      'slash-commands',
      'attachments',
      'side-chat',
      'coding-workspaces',
      'agents-settings'
],
  },
  {
    id: 'attachments',
    category: 'composer',
    title: 'Attachments, paste, and quotes',
    summary:
      'Attach files by drag-and-drop or paste, quote transcript or plan selections into the next message, and rely on /undo to restore attachments with the draft. Quotes and files are how you pin evidence without rewriting context by hand.',
    keywords: [
      'attachment',
      'drag and drop',
      'paste',
      'quote',
      'Add to chat',
      'image',
      'file',
      'chip',
      'clipboard',
      'đính kèm',
      'dán',
      'trích dẫn',
      '添付',
      'ペースト',
      '引用'
],
    setup:
      'Attachments must be enabled for the session/composer; some environments disable uploads for policy reasons. Confirm the composer drop target highlights before relying on drag-and-drop. Quotes work from transcript selections, Plan review, and Send to side chat.',
    tricks: [
      'Paste from the clipboard (images/files) or drag onto the composer drop target — both bind to the next user message.',
      'Quoted context appears as a chip above the draft — clear it if you change your mind before send.',
      'Plan review quote → composer is the same quote pipeline used for transcript selections.',
      '/undo restores attachments that were part of the undone user message — text and files come back together.',
      'Send to side chat carries a quote into /btw without interrupting the main run.',
      'Prefer a tight quote plus a short ask over re-pasting an entire prior assistant essay.',
      'Images help UI and error-dialog bugs; for stack traces, paste text or attach a .log so the model can copy tokens exactly.',
      'Clear stale quote chips before switching topics — leftover quotes silently bias the next turn.',
      'If paste seems to “do nothing,” check focus is on the composer and attachments are enabled for the session.'
],
    blocks: [
      {
        type: 'p',
        text: 'Attachments are files (and often images) bound to a user message. Quotes are selected text from the transcript, plan panel, or side-chat targeting that become context for the next send. Together they pin evidence so you are not re-describing a UI state or an error block every turn.',
      },
      {
        type: 'p',
        text: 'Use attachments when the bytes matter: screenshots, PDFs, CSVs, small logs, design exports. Use quotes when the text already lives in the transcript or plan and you want surgical follow-up. Avoid attaching entire repositories — use @ mentions, Files, or Coding graph tools instead.',
      },
      {
        type: 'p',
        text: 'Drop or paste files onto the composer. Select text in the transcript for Add to chat / more details / Send to side chat. In Plan review, select plan text to quote into a revise message. After undo, re-send or edit the restored draft including files. Watch for the quote chip above the draft before you hit send.',
      },
      {
        type: 'tips',
        items: [
          'Drag-drop — files onto the composer drop target',
          'Paste — clipboard images/files into a focused composer',
          'Add to chat — quote transcript into the main draft',
          'Send to side chat — quote into /btw parallel ask',
          'Plan quote — select plan markdown → revise chip',
          '/undo — restore previous user text + attachments',
          'Clear chip — remove quote before send if topic changed'
],
      },
      {
        type: 'p',
        text: 'Step-by-step for a bug report: (1) reproduce and capture a screenshot, (2) paste or drop it on the composer, (3) quote the failing assistant step or error line if present, (4) state expected vs actual, (5) send under ask or plan if fixes will touch many files.',
      },
      {
        type: 'p',
        text: 'Common mistakes: attaching secrets (.env, key files) “just for context”; stacking five large binaries until the context budget spikes; quoting an outdated plan section after the agent already revised; assuming side-chat quotes merge back into the parent history (they do not).',
      },
      {
        type: 'tips',
        items: [
          'When not to attach — huge build artifacts, node_modules zips, full database dumps.',
          'When to quote — disagreeing with one paragraph, revising one plan bullet, asking “explain this”.',
          'Cross-feature: after /undo, review restored attachments before re-send.',
          'Cross-feature: WorkFolderSelector does not attach a folder; it retargets the session root.'
],
      },
      {
        type: 'p',
        text: 'Policy note: if your org disables uploads, you will still have quotes and @ mentions. Prefer those paths over fighting the attachment gate. Outbound PII redaction in Settings → Sandbox can still apply when content leaves toward a provider.',
      }
],
    related: [
      'composer-power',
      'plan-review',
      'side-chat',
      'slash-commands',
      'sandbox-settings'
],
  },
  {
    id: 'slash-commands',
    category: 'slash',
    title: 'Built-in slash commands',
    summary:
      'Type / in the composer for stop, compact, undo, init, btw, goal, skills, workflows, and custom commands from .evoflux/commands/. Built-ins run immediately; custom entries usually insert so you can finish arguments.',
    setup:
      'Focus the composer and type /. Place project or global custom commands under `.evoflux/commands/` (compatible OpenCode paths also work).',
    keywords: [
      'slash',
      '/stop',
      '/compact',
      '/undo',
      '/init',
      '/btw',
      '/goal',
      '/workflow',
      '/skill',
      'command',
      '.evoflux/commands',
      'lệnh',
      'lệnh tùy chỉnh',
      'スラッシュ',
      'コマンド'
],
    tricks: [
      'Built-ins execute immediately on pick; custom commands usually insert into the textarea so you can append $ARGUMENTS.',
      'Longest-prefix match; : and / are interchangeable for nested command and skill names.',
      'Custom commands live under project or global .evoflux/commands/ (and compatible OpenCode paths).',
      'Skills appear under /skill: only after they validate in Settings → Skills.',
      'Workflows must be approved and valid for the session scope (work / coding) or they stay hidden.',
      '/compact early when the context budget bar climbs — waiting for failure wastes a turn.',
      '/init is Coding-oriented for AGENTS.md scaffolding.',
      '/stop is the panic button for runaway specialist fan-out; pair with a clearer next instruction.',
      'Prefer /btw over polluting the main transcript with meta questions during a long run.'
],
    blocks: [
      {
        type: 'p',
        text: 'Slash commands are first-class composer actions. Built-ins control the team run; goal subcommands manage durable objectives; skills and workflows attach structured behavior; user-defined Markdown/YAML commands expand server-side. The menu is searchable — type a few letters to filter.',
      },
      {
        type: 'p',
        text: 'Slash keeps high-frequency actions discoverable without hunting menus, and lets repos ship team conventions via .evoflux/commands/ that travel with the project. Treat custom commands as shared runbooks, not as a place to hide secrets.',
      },
      {
        type: 'slash',
        commands: [
          { cmd: '/stop', desc: 'Stop all working agents immediately' },
          { cmd: '/continue', desc: 'Continue the last assistant response' },
          { cmd: '/compact', desc: 'Summarize and compact this session’s context' },
          { cmd: '/shell', desc: 'Prefill shell mode (! command)' },
          { cmd: '/undo', desc: 'Undo the previous user message (restores text + attachments)' },
          { cmd: '/redo', desc: 'Restore undone messages back to the live tip' },
          { cmd: '/new', desc: 'Start a fresh team conversation' },
          { cmd: '/init', desc: 'Create or update AGENTS.md (Coding workspaces)' },
          { cmd: '/btw', desc: 'Open side chat with read-only access to this session' },
          { cmd: '/goal <objective>', desc: 'Start a durable autonomous goal' },
          { cmd: '/goal', desc: 'Inspect active goal status' },
          { cmd: '/goal:budget <tokens|none>', desc: 'Set or clear the goal token budget' },
          { cmd: '/goal:pause', desc: 'Pause the active goal' },
          { cmd: '/goal:resume', desc: 'Resume a paused goal' },
          { cmd: '/goal:stop', desc: 'Remove the session goal' },
          { cmd: '/skill:…', desc: 'Attach a skill for the next message (nested: /skill:parent:child)' },
          { cmd: '/workflow <name>', desc: 'Run an approved workflow (may open RunInputsDialog)' }
],
      },
      {
        type: 'p',
        text: 'Type / to filter commands. Pick a built-in to run it, or a custom/skill/workflow entry to insert or launch. Place custom files under `.evoflux/commands/` in the project or your global EvoFlux config. Nested names prefer longest prefix; use either `:` or `/` as separators. Workflows may open RunInputsDialog and never send the raw slash line as ordinary chat.',
      },
      {
        type: 'tips',
        items: [
          'Built-in — executes on pick',
          'Custom — usually inserts; append $ARGUMENTS',
          'Skill — /skill: after Settings → Skills validation',
          'Workflow — scope + approval required or hidden',
          'Longest prefix — parent:child nesting with : or /'
],
      },
      {
        type: 'p',
        text: 'Step-by-step custom command: (1) add a Markdown/YAML command under `.evoflux/commands/`, (2) reload or reopen the slash menu, (3) pick the command so it inserts, (4) fill arguments, (5) send. Add only the custom commands you need — unused prompts stay out of the menu on purpose.',
      },
      {
        type: 'p',
        text: 'Common mistakes: expecting `/scheduler` to open a page (use Ctrl+S — the route redirects home); treating missing workflows as a composer bug when scope/approval is wrong; running /compact so late that the summary drops the constraint you still needed; using /undo thinking it reverts git commits — it only restores the prior user message draft.',
      },
      {
        type: 'tips',
        items: [
          'When to /new — topic change with a polluted context bar.',
          'When to /compact — same topic, rising budget, keep continuity.',
          'When to /stop — runaway tools or wrong fan-out; then restate the ask.',
          'Cross-feature: /init + Coding Overview after opening a new repo.'
],
      }
],
    related: [
      'slash-goal',
      'side-chat',
      'composer-power',
      'coding-workspaces'
],
  },
  {
    id: 'slash-goal',
    category: 'slash',
    title: 'Durable Goal mode',
    summary:
      'Run an autonomous objective that survives reconnects with optional token budget, pause/resume/stop, and a blocker streak — without expanding permissions or sandbox scope. Goals are for work that should continue after you close the window.',
    keywords: [
      'goal',
      '/goal',
      'budget',
      'autonomous',
      'pause',
      'resume',
      'blocker',
      'blocker streak',
      '/goal:pause',
      '/goal:resume',
      '/goal:stop',
      '/goal:budget',
      'mục tiêu',
      'ngân sách',
      'tạm dừng',
      'ゴール',
      '予算',
      '一時停止'
],
    setup:
      'Start with `/goal <objective>` in any mode. Optional: `/goal:budget <tokens>` before or during the run. Set permission mode and Settings → Sandbox deliberately first — Goal never widens them.',
    tricks: [
      'Use /goal alone to inspect status; /goal:budget <tokens|none> to change or clear the budget.',
      'Pause / resume / stop with /goal:pause, /goal:resume, /goal:stop.',
      'The same concrete blocker reported three turns in a row stops progress; the UI shows the blocker streak.',
      'Goal state, elapsed time, and token usage survive app restarts and reconnects.',
      'Hidden internal turns continue until completion, budget pause, user pause/stop, or blocker streak.',
      'Goal never expands permission mode or sandbox scope — set those deliberately before starting.',
      'Prefer a clear objective and a token budget for unattended overnight runs.',
      'Draft with plan mode first on large goals, Accept, then `/goal` so autonomy starts from an approved outline.',
      'Use /btw for meta questions while a goal runs so you do not derail the objective transcript.'
],
    blocks: [
      {
        type: 'p',
        text: 'Goal mode attaches a durable autonomous objective to the session. The Lead keeps working through internal turns until the objective is recorded complete, the budget pauses execution, you pause/stop, or the blocker streak trips. Closing the window should not forget the objective.',
      },
      {
        type: 'p',
        text: 'Ordinary chats stop when you close the window or the turn ends. Goals are for longer objectives (“migrate module X”, “finish the refactor checklist”) that should resume after reconnect without you re-prompting every step. They are not a license to bypass safety.',
      },
      {
        type: 'p',
        text: 'Run `/goal ship the login refactor with tests` to start. `/goal` shows status. `/goal:budget 200000` sets a token ceiling; `/goal:budget none` clears it. `/goal:pause` / `/goal:resume` / `/goal:stop` control lifecycle. Watch the goal UI for elapsed time, tokens, and blocker streak. Permissions and sandbox stay exactly as configured for the session.',
      },
      {
        type: 'slash',
        commands: [
          { cmd: '/goal <objective>', desc: 'Start durable autonomous work' },
          { cmd: '/goal', desc: 'Show goal status' },
          { cmd: '/goal:budget <tokens|none>', desc: 'Set or clear token budget' },
          { cmd: '/goal:pause', desc: 'Pause execution' },
          { cmd: '/goal:resume', desc: 'Resume after pause or budget hold' },
          { cmd: '/goal:stop', desc: 'Clear the session goal' }
],
      },
      {
        type: 'tips',
        items: [
          'Write objectives with a Definition of Done and out-of-scope list.',
          'Set a token budget before overnight runs.',
          'Watch blocker streak — same blocker ×3 stops progress.',
          'Do not expect Goal to flip ask → bypass for you.',
          'Use /goal:pause before large manual edits in the same tree.'
],
      },
      {
        type: 'p',
        text: 'When to use: multi-hour Coding refactors, checklist-driven chores, research that should continue after sleep. When not to use: interactive design debates, one-shot Q&A, or anything that needs frequent human taste every minute — stay in normal chat or plan review.',
      },
      {
        type: 'p',
        text: 'Common mistakes: starting Goal under bypass on a broad home directory; omitting a budget and waking up to a huge bill; ignoring blocker streak and re-prompting the same stuck step; using /stop instead of /goal:stop (they address different layers); packing multiple unrelated objectives into one `/goal` line.',
      },
      {
        type: 'tips',
        items: [
          'Step — shield + sandbox → optional plan Accept → /goal:budget → /goal <objective>.',
          'Step — stuck → read blocker → /goal:pause → fix environment → /goal:resume.',
          'Cross-feature: Scheduler is for cron prompts; Goal is in-session autonomy.',
          'Cross-feature: Dream cron is separate under Settings → Memory.'
],
      }
],
    related: [
      'permissions-modes',
      'slash-commands',
      'chat-team',
      'plan-review',
      'scheduler-tasks'
],
  },
  {
    id: 'sessions-folders',
    category: 'sessions',
    title: 'Sessions, pins, and Work folders',
    summary:
      'Pin important chats, organize Work sessions into folders with drag-and-drop, toggle share_context for sibling digests, and delete folders without deleting conversations. Filing is organization — it does not rewrite history or model settings.',
    keywords: [
      'folder',
      'pin',
      'session',
      'drag',
      'share context',
      'share_context',
      'Move to folder',
      'unfile',
      'Ctrl+R',
      'Today',
      'Pinned',
      'thư mục',
      'ghim',
      'phiên',
      'chia sẻ ngữ cảnh',
      'フォルダ',
      'ピン',
      'セッション'
],
    setup:
      'Work mode sidebar → Folders section. Coding use their own session trees; folder filing is a Work organization feature. Use Ctrl+R to refresh the Work session list after external changes.',
    tricks: [
      'Drag a session row onto a folder header (desktop), or use Move to folder… on touch.',
      'The link icon on a folder toggles share_context — siblings receive a bounded digest of each other.',
      'Folder + creates a new chat already filed in that folder.',
      'Deleting a folder un-files sessions; conversations are never deleted with the folder.',
      'Ctrl+R refreshes the Work sidebar session list.',
      'Pin sessions to keep them on top above Today / Yesterday / Older.',
      'Filing only sets folder_id — history, model, and workspace settings stay with the session.',
      'Long transcripts preload earlier history several screens before the top; fast upward scrolling should keep the current text anchored while older turns appear.',
      'Turn share_context off for sensitive client folders that must not digest into siblings.',
      'Name folders by outcome (“RFP research”, “incident 4821”), not by date — dates already group unfiled chats.',
      'Unfile via Move to folder… → none when a thread no longer belongs with its siblings.'
],
    blocks: [
      {
        type: 'p',
        text: 'Work sessions can be pinned and filed into named folders. Folders optionally enable share_context so sibling chats exchange a bounded digest. Unfiled sessions still group by Pinned / Today / Yesterday / Older. and Coding keep their own trees — do not look for Work folders there.',
      },
      {
        type: 'p',
        text: 'Long-running cowork accumulates many chats. Folders keep research threads, client work, or experiments separated without fragmenting each session’s own history and model settings. Pins keep the few chats you reopen daily from sinking under Today.',
      },
      {
        type: 'p',
        text: 'Create a folder in the Work sidebar. Drag sessions onto the folder header, or open the session menu → Move to folder…. Click the link icon to toggle share_context. Use + on a folder to start a new chat already filed there. Delete a folder to unfile its sessions; use the session delete action only when you intend to remove the conversation itself.',
      },
      {
        type: 'tips',
        items: [
          'Pin — keep critical sessions at the top.',
          'share_context — bounded sibling digests (link icon).',
          'Folder + — new chat pre-filed.',
          'Delete folder — unfiles only; chats remain.',
          'Ctrl+R — refresh Work session list.',
          'Move to folder… — touch-friendly filing / unfiling.',
          'Today / Yesterday / Older — automatic groups for unfiled chats.'
],
      },
      {
        type: 'p',
        text: 'Step-by-step project setup in Work: (1) create a folder named for the engagement, (2) enable share_context only if sibling digests help, (3) Folder + for the main thread, (4) spawn sibling chats for parallel research, (5) pin the decision log chat, (6) delete the folder later to unfile without losing history.',
      },
      {
        type: 'p',
        text: 'When to use share_context: parallel angles on the same research question where a digest prevents duplicate work. When not to: regulated client data, HR topics, or anything that must not leak summaries into neighboring chats — leave the link icon off.',
      },
      {
        type: 'p',
        text: 'Common mistakes: deleting a folder expecting chats to vanish; assuming filing copies the filesystem WorkFolderSelector path; dragging on mobile without using Move to folder…; expecting Coding sessions to appear under Work folders; leaving share_context on after a folder’s purpose changes to sensitive work.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: WorkFolderSelector sets the on-disk folder for tools; sidebar folders organize chats.',
          'Cross-feature: pin + Goal on the decision chat for long engagements.',
          'Cross-feature: /new inside a folder keeps filing if you started from Folder +.',
          'Refresh with Ctrl+R if a moved session does not appear where you expect.'
],
      }
],
    related: [
      'composer-power',
      'modes-overview',
      'getting-started',
      'slash-goal',
      'side-chat'
],
  },
  {
    id: 'workbench-tools',
    category: 'workbench',
    title: 'Workbench tools',
    summary:
      'Open Terminal, Browser, Files, Graph, Side chat, Memory, Scheduler, Changes, and Review beside chat — with platform-native shortcuts: Command on macOS, Ctrl on Windows/Linux.',
    keywords: [
      'workbench',
      'panel',
      'terminal',
      'files',
      'dock',
      'overview',
      'graph',
      'Changes',
      'Review',
      'Ctrl+F',
      'Ctrl+;',
      '⌘P',
      '⌥⌘S',
      'bảng',
      'bảng công cụ',
      'ワークベンチ',
      'パネル'
],
    setup:
      'Open a session first. Coding Overview, Graph, Changes, and Review need a Coding workspace. Built-in Browser must be enabled under Settings → Browser before Ctrl+T is useful.',
    tricks: [
      'Open tools from the workbench bar, dock, or keyboard shortcuts listed below.',
      'Coding Overview appears only when a workspace is selected.',
      'Runtime shortcuts and labels adapt to the OS: Command on macOS, Ctrl on Windows/Linux.',
      'Live mappings: Files = Ctrl+F (label may show ⌘P); Side chat = Ctrl+; (label may show ⌥⌘S).',
      'Graph and Review have no dedicated global shortcuts — use the workbench bar or command palette.',
      'Terminal and Browser support multiple tab instances; other tools are single-instance toggles.',
      'Changes (Ctrl+G) and Review are Coding-only; Graph needs a Coding workspace.',
      'Toggle the same tool again to close it — the workbench is not a pile of permanent cards.',
      'When opening the workbench with a Coding workspace and no tool selected, Overview opens by default.'
],
    blocks: [
      {
        type: 'p',
        text: 'The workbench is the right-hand (or docked) tool surface beside chat. Tools: Overview, Terminal, Browser, Files, Graph, Side chat, Memory (wiki), Scheduler, Changes (source control), and Review (pull/merge requests). Chat stays primary; tools are inspection and action surfaces one shortcut away.',
      },
      {
        type: 'p',
        text: 'Agents produce files, diffs, browser steps, and schedules that need inspection without leaving the session. The workbench keeps those surfaces close so you are not alt-tabbing into five other apps for every verification step.',
      },
      {
        type: 'shortcuts',
        rows: [
          { keys: 'Ctrl+`', action: 'Terminal' },
          { keys: 'Ctrl+T', action: 'Built-in browser' },
          { keys: 'Ctrl+F', action: 'Files / Changed & Files (label may show ⌘P)' },
          { keys: 'Ctrl+;', action: 'Side chat (label may show ⌥⌘S)' },
          { keys: 'Ctrl+M', action: 'Memory (wiki)' },
          { keys: 'Ctrl+S', action: 'Scheduler' },
          { keys: 'Ctrl+K', action: 'Plugins' },
          { keys: 'Ctrl+G', action: 'Git Changes (Coding)' }
],
      },
      {
        type: 'tips',
        items: [
          'Overview — Coding workspace / git / session / tool status at a glance.',
          'Terminal — run commands in the active workspace.',
          'Browser — in-app browser (enable in Settings → Browser).',
          'Files — workspace files and generated artifacts.',
          'Graph — structural code graph (Coding).',
          'Side chat — /btw parallel questions.',
          'Memory — wiki + pending notes.',
          'Scheduler — cron / one-shot tasks (panel only; /scheduler redirects home).',
          'Changes — stage, commit, branch operations (Coding).',
          'Review — PR/MR list for connected hosts (Coding).'
],
      },
      {
        type: 'p',
        text: 'Click a tool in the workbench bar or press its shortcut. Toggle the same tool again to close it. Prefer the command palette (Ctrl+P) when you forget which tool owns an action. Do not confuse built-in Browser (Ctrl+T) with WebBridge pairing for real Chrome/Edge.',
      },
      {
        type: 'p',
        text: 'Common mistakes: hunting Review in Work mode; expecting Graph without a focused Coding workspace; bookmarking `/scheduler`; trusting a ⌘P label for Files; opening ten Terminal tabs for one-liners better sent with ! in the composer.',
      },
      {
        type: 'tips',
        items: [
          'When to use Terminal vs ! — interactive/long vs short chat-tied commands.',
          'When to use Files vs @ — browse/explore vs pin a known path into the ask.',
          'Cross-feature: Changes after Accept in plan mode to verify diffs.',
          'Cross-feature: Memory after research sessions so Dream has material.'
],
      }
],
    related: [
      'side-chat',
      'memory-dream',
      'scheduler-tasks',
      'coding-git',
      'keyboard-shortcuts',
      'browser-webbridge'
],
  },
  {
    id: 'side-chat',
    category: 'workbench',
    title: 'Side chat (/btw)',
    summary:
      'Ask a focused question with read-only access to the main session without interrupting the active run or merging histories back. Side chat is the “btw” lane for clarifications, constraint checks, and side explorations.',
    keywords: [
      'side chat',
      'btw',
      '/btw',
      'parallel',
      'Ctrl+;',
      'Send to side chat',
      'read-only',
      'chat phụ',
      'hỏi thêm',
      'サイドチャット',
      'ちなみに'
],
    setup:
      'Open with /btw, the platform shortcut (Command+; on macOS, Ctrl+; on Windows/Linux), the workbench Side chat tool, or the session-row icon. Optionally select transcript text → Send to side chat to carry a quote.',
    tricks: [
      'Open with /btw, Ctrl+;, the workbench Side chat tool, or the session-row icon.',
      'Quote selection → Send to side chat for a tight follow-up without retyping the passage.',
      'Side chat does not merge its history back into the parent session — paste conclusions manually if the Lead must see them.',
      'Use side chat to clarify while Goal or a long specialist run continues on the main transcript.',
      'Side chat uses Command+; on macOS and Ctrl+; on Windows/Linux.',
      'Keep side chat short and factual; dump long implementation work back on the Lead thread.',
      'Close the panel when done so you do not accidentally type the next main instruction into /btw.',
      'Side chat sees parent context read-only — it should not be your primary editor for repo-wide refactors.',
      'If you need a durable parallel thread with its own tools, prefer a sibling Work session (optionally share_context) instead of overloading /btw.'
],
    blocks: [
      {
        type: 'p',
        text: 'Side chat is a parallel composer with read-only access to the parent session context. It is ideal for “btw” questions, clarifying constraints, or exploring an idea without polluting the main transcript. Histories stay separate on purpose.',
      },
      {
        type: 'p',
        text: 'Interrupting a long Lead/specialist run to ask a meta-question forces awkward stop/continue cycles. Side chat keeps the main thread clean while you still benefit from session awareness. Goal mode especially benefits — autonomy continues while you sanity-check a detail.',
      },
      {
        type: 'p',
        text: 'Run /btw, press Ctrl+;, open Side chat from the workbench, or use the session-row icon. Optionally quote transcript text via Send to side chat. Ask your question; close the panel when done. If the answer must steer the main run, summarize it back into the Lead composer (or Revise a plan) yourself.',
      },
      {
        type: 'tips',
        items: [
          '/btw — open from composer slash menu',
          'Ctrl+; — toggle Side chat workbench tool',
          'Send to side chat — quote selection into /btw',
          'Read-only parent context — no history merge back',
          'Session-row icon — open without the slash menu',
          '⌥⌘S label — ignore; live binding is Ctrl+;'
],
      },
      {
        type: 'p',
        text: 'Step-by-step during a long Coding run: (1) select the confusing assistant paragraph, (2) Send to side chat, (3) ask “is this claiming X or Y?”, (4) if Y was wrong, return to the main composer with a corrective instruction or plan revise, (5) close Side chat.',
      },
      {
        type: 'p',
        text: 'When to use: clarifying terms, checking a constraint, asking for a quick explanation of a tool result, brainstorming alternatives you might discard. When not to use: primary implementation work, attaching the only copy of a critical file, or anything that must be auditable inside the main session history.',
      },
      {
        type: 'p',
        text: 'Common mistakes: typing the next “please implement…” into side chat and wondering why the Lead did not act; expecting side chat to approve plans or answer ask-user modals for the parent; leaving Ctrl+; open and losing track of which composer is focused; assuming quotes auto-sync both ways.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: pair with Plan review quotes for “explain this bullet” without Rejecting.',
          'Cross-feature: Work sibling chats + share_context for heavier parallel research.',
          'Cross-feature: /stop still targets the main team — side chat is not a second Lead.',
          'If side chat lacks a tool you need, you are probably past the /btw use case.'
],
      }
],
    related: [
      'composer-power',
      'workbench-tools',
      'slash-commands',
      'slash-goal',
      'plan-review'
],
    openAction: { type: 'workbench', tool: 'side-chat' },
  },
  {
    id: 'coding-workspaces',
    category: 'coding',
    title: 'Coding workspaces, projects, and worktrees',
    summary:
      'Open repos, group them into multi-repo projects, create managed worktrees, and use /init for AGENTS.md. Clicking a repo focuses it; it does not start a chat — use + / New chat when you want a transcript.',
    keywords: [
      'workspace',
      'project',
      'worktree',
      'repo',
      'multi-repo',
      'AGENTS.md',
      '/init',
      'sandbox',
      'user_data',
      'dự án',
      'kho mã',
      'cây làm việc',
      'ワークスペース',
      'プロジェクト',
      'ワークツリー'
],
    setup:
      'Switch to Coding (`/coding`) and add a repository or create a project. Configure worktree location under Settings → Sandbox (repository vs user_data). Run /init in a session once conventions should live in AGENTS.md.',
    tricks: [
      'Clicking a repo focuses it — it does not start a chat. Use + on Repos (or New chat) to create a session.',
      'Projects span multiple repositories under one project_id; graph tools resolve cross-repo links automatically.',
      'Worktree location is controlled in Settings → Sandbox (repository vs user_data).',
      'Uncommitted source changes are not copied into new worktrees.',
      'Managed worktrees nest under the source repo in the sidebar tree.',
      'Standalone repos remain valid single-workspace sessions without a project.',
      'Run /init in a Coding session to create or update AGENTS.md for agent conventions.',
      'Open Coding Overview from the workbench when a workspace is selected for status at a glance.',
      'Commit or stash before spawning a worktree if you need those dirty changes elsewhere — they will not appear in the new tree.',
      'Prefer a project when services share APIs across repos; prefer a single repo when the change set is local.'
],
    blocks: [
      {
        type: 'p',
        text: 'Coding mode manages git repositories, optional multi-repo projects, and managed worktrees. Agents edit real trees with Files, Graph, Terminal, Changes, and Review tools available beside chat. This is the mode for persistent engineering work.',
      },
      {
        type: 'p',
        text: 'Persistent repos need different UX than Work’s ephemeral folders: focus vs new chat, project grouping, sandbox worktree placement, and AGENTS.md conventions for the team. Treating Coding like Work is the most common onboarding confusion.',
      },
      {
        type: 'p',
        text: 'Add a repo from the Coding sidebar. Click to focus; press + / New chat for a session. Create a Project to bind multiple repos. Spawn a worktree from the repo menu; choose repository-local vs user_data location in Settings → Sandbox. Use /init to scaffold or refresh AGENTS.md. Graph and Overview enable once a workspace is active.',
      },
      {
        type: 'tips',
        items: [
          'Focus ≠ chat — click selects; + creates.',
          'Projects — multi-repo under one project_id.',
          'Worktrees — clean trees; uncommitted source not copied.',
          '/init — AGENTS.md for Coding conventions.',
          'Sandbox — worktree location policy.',
          'Overview — status once a workspace is focused.'
],
      },
      {
        type: 'p',
        text: 'Step-by-step first Coding session: (1) switch to Coding, (2) add the git repo, (3) click to focus, (4) + / New chat, (5) /init if AGENTS.md is missing, (6) set permission mode, (7) @ key files and describe the change, (8) open Overview to confirm workspace health.',
      },
      {
        type: 'p',
        text: 'Worktrees: use them for parallel branches/agents without dirtying your primary checkout. Remember new worktrees start clean relative to the source commit state — uncommitted edits stay behind. Nesting under the source repo in the sidebar helps you see the family relationship.',
      },
      {
        type: 'p',
        text: 'Common mistakes: clicking a repo and waiting for a chat that never starts; putting uncommitted work only in the source tree then opening a worktree that lacks it; skipping /init then wondering why agents ignore repo conventions; creating a multi-repo project when a single submodule path would do; leaving worktree location on a slow network drive via user_data without intending to.',
      },
      {
        type: 'tips',
        items: [
          'When to project — cross-repo types, shared contracts, multi-service changes.',
          'When not to project — one app repo with vendored code you rarely touch.',
          'Cross-feature: graph cross-repo resolution needs a project_id.',
          'Cross-feature: Review/Changes attach to the focused workspace.'
],
      }
],
    related: [
      'coding-git',
      'coding-graph',
      'slash-commands',
      'sandbox-settings',
      'modes-overview'
],
    openAction: { type: 'route', to: '/coding' },
  },
  {
    id: 'coding-git',
    category: 'coding',
    title: 'Git, changes, and pull requests',
    summary:
      'Stage, commit, branch, merge, rebase, stash, and review PRs/MRs from Coding via Changes (Ctrl+G), the Review panel, and Settings → Git & reviews. Keep safety toggles intentional before force-with-lease or huge diffs.',
    keywords: [
      'git',
      'commit',
      'branch',
      'pr',
      'mr',
      'merge',
      'rebase',
      'stash',
      'review',
      'Ctrl+G',
      'source control',
      'force-with-lease',
      'GitHub',
      'GitLab',
      'Bitbucket',
      'Gitea',
      'Azure DevOps',
      'kéo yêu cầu',
      'cam kết',
      'ギット',
      'プルリクエスト',
      'コミット'
],
    setup:
      'Coding mode with a git workspace. Connect hosts under Settings → Git & reviews for remote PR/MR actions. Review timeouts, max diff size, and force-with-lease before aggressive operations.',
    tricks: [
      'Ctrl+G opens Changes (source control).',
      'Diff review panels can prompt the agent to Create PRs.',
      'Force-with-lease and max diff size are gated in version-control settings.',
      'Review workbench lists PRs/MRs for GitHub, GitLab, Bitbucket, Gitea, and Azure DevOps when connected.',
      'Agents can also run git operations through tools subject to permission mode and sandbox.',
      'Use stash / branch / rebase from Changes or agent tools depending on comfort level.',
      'Prefer small commits with clear messages — agents write better follow-ups against clean history.',
      'Connect the host before asking for Create PR; otherwise local commits succeed and remote steps fail late.',
      'If a diff is huge, raise max diff size only temporarily — oversized reviews hide risk.'
],
    blocks: [
      {
        type: 'p',
        text: 'Coding exposes local source control (Changes) and remote review (Review). Supported local operations include stage, commit, branch, merge, rebase, cherry-pick, stash, and worktree-aware flows. Remote hosts power PR/MR listing and review actions when Settings → Git & reviews is configured.',
      },
      {
        type: 'p',
        text: 'Keeping git next to the agent transcript shortens the edit → review → commit → PR loop without switching to an external IDE for every step. Safety policy (timeouts, max diff size, force-with-lease) lives in Settings so aggressive git ops stay intentional.',
      },
      {
        type: 'p',
        text: 'Press Ctrl+G or open Changes from the workbench. Review diffs, stage, and commit. Open Review for connected PR/MRs. Configure hosts, timeouts, and safety toggles under Settings → Git & reviews. Ask the agent to create PRs from diff review when the host connection is ready.',
      },
      {
        type: 'tips',
        items: [
          'Ctrl+G — Changes / source control',
          'Review — PR/MR list for connected hosts',
          'GitHub / GitLab / Bitbucket / Gitea / Azure DevOps — host integrations',
          'force-with-lease — gated; not a casual default',
          'max diff size — raise only when you must',
          'stash / branch / rebase — UI or agent tools'
],
      },
      {
        type: 'p',
        text: 'Step-by-step PR loop: (1) agent edits under accept-edits or plan, (2) Ctrl+G to inspect the diff, (3) stage related hunks, (4) commit with a why-focused message, (5) push via agent or your usual remote flow, (6) open Review / Create PR on the connected host, (7) address review comments in a follow-up chat.',
      },
      {
        type: 'p',
        text: 'When to let the agent run git vs do it yourself: let the agent stage/commit when the diff matches the plan and permission mode is appropriate; do merges/rebases yourself on protected branches if your team requires human ceremony. Never enable force-with-lease casually on shared branches.',
      },
      {
        type: 'p',
        text: 'Common mistakes: committing secrets that sandbox did not catch because they were new files outside deny globs; asking for a PR before host auth; mixing unrelated files in one agent-driven commit; assuming Review works in Work mode; treating force-with-lease like plain `--force`.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: Plan Accept → Changes to verify the plan became the diff you expected.',
          'Cross-feature: worktrees keep experimental commits off your main checkout.',
          'Cross-feature: permission ask mode before first push on a production remote.'
],
      }
],
    related: [
      'coding-workspaces',
      'workbench-tools',
      'settings-safety',
      'permissions-modes',
      'plan-review'
],
    openAction: { type: 'workbench', tool: 'source-control' },
  },
  {
    id: 'coding-graph',
    category: 'coding',
    title: 'Repository code context',
    summary:
      'Repository-local indexes combine source search, structural patterns, and exact symbol navigation. Use one code_context tool across every authorized repository.',
    keywords: [
      'code graph',
      'symbols',
      'cross-repo',
      'index',
      'code_context',
      'tree-sitter',
      'đồ thị mã',
      'biểu tượng',
      'コードグラフ',
      'シンボル'
],
    setup:
      'Coding workspace or project — the first query refreshes changed source components. Open Graph to inspect the current dynamic repository snapshot.',
    tricks: [
      'Coding skills progressively disclose one code_context workflow.',
      'Use code_context search for discovery, grep for code shapes, and graph actions for one known exact symbol.',
      'Open the Graph workbench tool to explore visually and reindex when needed.',
      'Cross-repo relationships resolve dynamically from imports, module paths, and unique definitions; no resolver job or persisted guessed edge exists.',
      'code_context graph actions cover definition, callers, callees, references, impact, and neighborhood.',
      'Use refresh=true after edits and refresh=false only for immediate same-version follow-ups.',
      'Ask structural questions (“who calls X?”) instead of “read the whole package.”',
      'Multi-repo projects get cross-repo edges; standalone repos still benefit inside one tree.',
      'The skill body is never injected by Coding mode, and raw request prose is never keyword-routed into a graph query.'
],
    blocks: [
      {
        type: 'p',
        text: 'Each repository owns a local managed index of AST-aware chunks, symbols, relations, and FTS source. The native code_context tool queries those targets, and Graph renders a dynamic snapshot.',
      },
      {
        type: 'p',
        text: 'Whole-file dumps burn context. Graph-first navigation is token-efficient for “who calls X?” and cross-repo questions inside a project, while still allowing grep/LSP/tests when static resolution is insufficient. Treat the graph as a map, not as ground truth that replaces reading hot paths.',
      },
      {
        type: 'tips',
        items: [
          'code_context search — identifiers, literals, comments, and concepts',
          'code_context grep — by-example structural matching',
          'code_context definition/callers/callees — exact symbol navigation',
          'code_context references/impact/neighborhood — bounded relationship traversal'
],
      },
      {
        type: 'p',
        text: 'Open a Coding workspace and query code_context. The first query reconciles additions, updates, and deletions into repository-local targets. Multi-repo edges resolve over the current authorized target set when queried or visualized.',
      },
      {
        type: 'p',
        text: 'Step-by-step investigation: (1) discover an identifier with search or a code shape with grep, (2) call an exact-symbol action, (3) disambiguate duplicates by path or repository, (4) inspect limitations, and (5) verify dynamic behavior with tests, logs, or runtime evidence.',
      },
      {
        type: 'p',
        text: 'When to use graph vs grep: graph for typed symbols, call edges, and cross-file architecture; grep for error strings, comments, feature flags, YAML keys, and generated code the parser may skip. When not to trust graph alone: macros, heavy reflection, and templates that erase symbols at compile time.',
      },
      {
        type: 'p',
        text: 'Common mistakes: passing prose to an exact-symbol action, dumping directories into chat, querying unauthorized siblings, skipping refresh after external edits, or treating suggestions as resolved roots.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: pair graph hits with Changes to see if your edit set matches the call neighborhood.',
          'Cross-feature: AGENTS.md can tell agents to prefer graph-first navigation.',
          'Cross-feature: specialists inherit tools per Settings → Agents — ensure workers can search code.'
],
      }
],
    related: ['coding-workspaces', 'agents-settings', 'composer-power', 'coding-git'],
    openAction: { type: 'workbench', tool: 'graph' },
  },
  {
    id: 'evo-agent-specs',
    category: 'coding',
    title: 'Agent Specification-Driven Development (EASD)',
    summary:
      'Use Evo Agent Specs to accept a versioned specification, bind agent missions to acceptance criteria, collect snapshot-bound evidence, record deviations, and converge only when every required gate passes.',
    keywords: [
      'EASD',
      'Evo Agent Specs',
      'specification',
      'SDD',
      'ADD',
      'acceptance criteria',
      'mission',
      'evidence',
      'deviation',
      'convergence',
    ],
    setup:
      'Open a Coding workspace and initialize every repository with a tracked EASD knowledge base plus ignored local Run storage. Existing project docs stay where they are. Create Intent, review the agent-suggested direct/planned flow, and Approve specification. Direct continues to Implement; planned adds Run/Approve plan. Both finish Review → Verify → Converge.',
    tricks: [
      'Initialize once per repository; project runs stay locked until every live project repository is ready.',
      'Operational Runs, missions, evidence, events, Recovery, and Realtime state stay under ignored `.evoflux/easd/.local/`; linked Git worktrees share the source repository runtime. Accepted Specs and explicitly adopted docs remain trackable. Setup previews exact legacy paths, revalidates generated defaults, and rolls back a failed move.',
      'A converged Run can manually publish one compact Git-visible audit record. EvoFlux excludes prompts, raw evidence, transcripts, and local paths, and never commits or deletes the local Recovery ledger automatically.',
      'Initialization installs five Coding-only project skills: easd-specify, easd-plan, easd-implement, easd-review, and easd-verify. They are discovered only from repositories in the active Coding scope.',
      'EASD chat handoffs select only the current phase Skill: Specify for drafting, Plan only for accepted planned flow, Implement for direct or approved-plan execution, Review for mandatory challenge, and Verify for the final gate.',
      'Every EASD Skill re-reads persisted phase and hash state. A stale plan, mission, review snapshot, or verification result stops instead of continuing from chat memory.',
      'Core rule “Fix the Spec, Not the Code—before approval”: resolve ambiguity in the draft before coding; after approval, fix violating code or create a new user-approved Spec revision instead of weakening the contract.',
      'Creating a run persists Intent only; there is no specification revision and implementation is blocked.',
      'Draft specification in chat binds an idle authorized Coding session. The lead reads project instructions, docs, source/configuration and tests, asks clarifying questions, and submits the complete draft through a typed lead-only tool.',
      'After successful Spec or Plan submission, the chat tool result shows Review specification or Review plan and opens the exact Run in the EASD workbench. Retry drafting/planning repeats an interrupted attempt; Redraft/Replan preserves the prior draft until a replacement is persisted.',
      'Proof commands are one non-shell argv-style command per line. Use canonical commands such as `python -m pytest tests/test_simple.py`; shell chains, redirection, pipelines, and `python -c` snippets are rejected.',
      'The panel changes phase only after a durable repository write. Agent prose cannot unlock specification approval, required plan approval, implementation, Review, Verify, or Converge.',
      'The Run header action rail shows Intent → Spec → Plan → Implement → Review → Verify → Done. It marks direct Plan as skipped, names the next action, and explains server-derived blockers before you click; Spec approval, Plan approval, and Converge require confirmation.',
      'Open Trace to follow repository events and relationships from Spec/Plan through AC ownership, mission attempts, evidence, deviations, and convergence. Filter by AC and select an entity to inspect its persisted identity; Trace never changes Run state.',
      'Open Recovery to preview a safe retry. It shows the phase transition, reused Spec/Plan/session identities, and preserved history before confirmation. A stale repository generation stops the retry; converged Runs remain immutable.',
      'An open Run streams repository events in real time. The header shows connection/viewer state; reconnect resumes after the last event sequence, while stale mutations still fail instead of overwriting collaborator work.',
      'Review outcome, Scope, risk, AC evidence policy and commands; edit by saving a newer draft revision, then explicitly Approve specification. The agent cannot approve it.',
      'The Spec recommends direct or planned flow. Direct skips Plan only for low-risk single-boundary work; planned persists a typed mission graph and only user Approve plan unlocks implementation.',
      'Plan summaries highlight backtick-delimited symbols and paths. Verification command blocks distinguish executables, flags, and path arguments while keeping the original command selectable. EASD chat messages use phase labels and hide full contract hashes/Run IDs from presentation while preserving the exact copied/runtime prompt; built-in, Skill, Workflow, and custom slash commands share one syntax highlighter.',
      'Use Board for workflow state, Table for comparison, or List for compact navigation. Search spans title, status, risk, and repository.',
      'Accept freezes the normalized Spec revision/hash and publishes a hash-identical immutable copy into the common specs catalogue; later changes create another revision.',
      'Run review is separate and read-only. Delegated evidence must match the approved review mission and uses runtime reviewer identity; Run verify remains a separate user action.',
      'EASD team_delegate always includes run ID, exact Spec hash, AC ownership, and accepted Scope. Planned flow also requires exact Plan hash/mission ID; direct flow must omit them.',
      'Machine evidence comes only from CompletionContracts. Every accepted Proof command has a verification mission; Verify can create a fresh revision-bound contract without editing files. Runtime executes commands without a shell, blocks changed paths outside Scope, and worktree missions wait for an accepted merge.',
      'Record scope drift as a deviation instead of silently widening the specification.',
      'Converge accepts only Verify-phase runs and is a server gate, not an agent confidence claim.',
    ],
    blocks: [
      {
        type: 'p',
        text: 'EASD means Evo Agent Specification-Driven Development. It is EvoFlux’s spec-governed Agent-Driven Development protocol: SDD defines the normative contract, and ADD executes it through bounded agent missions.',
      },
      {
        type: 'p',
        text: 'Initialization adds `.evoflux/easd/config.json`, `RULES.md`, five Coding-only Skills, and an EASD knowledge skeleton under the repository data folder (default `documents/easd`): specs, features, architecture, reference, guides, development, records, images, templates, and runs. Existing project documentation is not moved or copied. `.local/` contains only ignored rebuildable locks/session bindings.',
      },
      {
        type: 'p',
        text: 'Project Skills guide Specify, optional Plan, Implement, Review, and Verify. They do not grant lifecycle authority: the user approves the Spec, approves Plan when planned, starts later phases, and invokes Converge.',
      },
      {
        type: 'p',
        text: 'Create Intent, let the lead draft the specification and flow recommendation, then Approve specification. Direct goes to implementation without a Plan artifact; planned persists and separately approves an acyclic mission graph. Both keep explicit Review and Verify phases.',
      },
      {
        type: 'tips',
        items: [
          'Draft — editable specification.',
          'Accepted revision — immutable payload and SHA-256 hash.',
          'Accepted plan — optional immutable spec-bound mission graph for planned flow.',
          'Mission — durable DelegationTask bound to ACs.',
          'Evidence — machine, review, manual, or waiver provenance.',
          'Deviation — visible contract/scope drift.',
          'Convergence — all required AC and mission gates satisfied.',
        ],
      },
      {
        type: 'p',
        text: 'For cross-layer and critical runs, convergence also requires independent review evidence. A missing planned verification command, blocking open/approved deviation, uncovered AC, failed evidence, or non-terminal mission returns structured reasons instead of a false Done state.',
      },
      {
        type: 'p',
        text: 'The panel and public API can add manual, review, or waiver evidence, but cannot manufacture machine evidence or runtime reviewer independence; trusted runtime tools own those levels.',
      },
      {
        type: 'p',
        text: 'Common mistakes: skipping a required Plan, inventing Plan identity for direct flow, delegating without Spec/AC/scope identity, treating review as convergence, or hiding scope expansion.',
      },
    ],
    related: ['coding-workspaces', 'permissions-modes', 'plan-review', 'coding-git', 'coding-graph'],
    openAction: { type: 'workbench', tool: 'easd' },
  },
  {
    id: 'memory-dream',
    category: 'memory',
    title: 'Memory wiki and Dream',
    summary:
      'Inspect a Markdown wiki (topics, entities, notes, imports) and run Dream synthesis on a cron (default 0 2 * * *) or manually via Run Dream. Memory turns chat into durable, citable pages instead of opaque model weights.',
    keywords: [
      'memory',
      'wiki',
      'dream',
      'notes',
      'INDEX',
      'LOG.md',
      'topics',
      'entities',
      'imports',
      'Ctrl+M',
      '0 2 * * *',
      'Run Dream',
      'trí nhớ',
      'wiki',
      'ghi chú',
      'メモリ',
      'ドリーム',
      'ノート'
],
    setup:
      'Open Memory with Ctrl+M or the workbench tool. Configure Dream under Settings → Memory (cron and related options). Default Dream cron is `0 2 * * *` if you leave the schedule untouched.',
    tricks: [
      'Pending notes/ stay read-only until Dream synthesizes them into curated wiki pages.',
      'Default Dream cron is 0 2 * * *; Run Dream now from settings or the command palette.',
      'Wiki sections include topics, entities, notes, imports, INDEX.md, and append-only LOG.md.',
      'Dream pages carry citations, confidence, and related-page metadata — inspect before trusting blindly.',
      'Memory is a workbench panel, not a separate product mode.',
      'Pair Dream with Scheduler only when you need arbitrary agent prompts; Dream has its own schedule.',
      'Skim LOG.md after overnight Dream runs to see what changed before you cite a page in chat.',
      'Prefer writing short pending notes during the day over hoping the model will remember next week.',
      'If Dream confidence is low, treat the page as a draft hypothesis and verify in source systems.'
],
    blocks: [
      {
        type: 'p',
        text: 'Memory is an inspectable Markdown wiki on disk. Dream is the scheduled (or manually triggered) synthesis agent that consolidates unprocessed sessions and notes into curated pages with citations and confidence metadata. You can open, diff, and correct the files like any other docs.',
      },
      {
        type: 'p',
        text: 'Chat history alone is a poor long-term knowledge base. A wiki you can open, diff, and cite keeps durable facts out of opaque model weights while still allowing automated consolidation overnight. Memory is for durable knowledge; the transcript is for the active conversation.',
      },
      {
        type: 'p',
        text: 'Press Ctrl+M or open Memory in the workbench. Browse topics/, entities/, notes/, imports/, INDEX.md, and LOG.md. Notes under notes/ are read-only pending synthesis. Configure the Dream cron in Settings → Memory (default `0 2 * * *`) or trigger Run Dream now. After Dream runs, review new/updated pages and LOG.md entries.',
      },
      {
        type: 'tips',
        items: [
          'topics/ — curated subject pages',
          'entities/ — people, systems, components',
          'notes/ — pending, read-only until Dream',
          'imports/ — ingested external material',
          'INDEX.md — entry map',
          'LOG.md — append-only synthesis log',
          'Ctrl+M — open Memory workbench',
          'Run Dream — manual synthesis trigger'
],
      },
      {
        type: 'p',
        text: 'Step-by-step daily habit: (1) during work, capture short notes into Memory, (2) leave notes/ pending, (3) let Dream run on cron or Run Dream at end of day, (4) read LOG.md, (5) fix any wrong citations on the wiki page itself, (6) mention corrected pages in later chats when relevant.',
      },
      {
        type: 'p',
        text: 'When to use Memory vs a Work folder of chats: use Memory for facts that should outlive a single engagement; use folders for active parallel threads. When not to rely on Dream alone: regulated decisions that need a human-authored source of truth — write the page yourself and treat Dream as assistive.',
      },
      {
        type: 'p',
        text: 'Common mistakes: editing notes/ expecting them to stay authoritative (they are pending); confusing Scheduler cron tasks with Dream’s Settings → Memory cron; never opening INDEX.md then claiming “Memory is empty”; citing high-confidence pages without checking the linked evidence after a messy week of chats.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: Scheduler for arbitrary prompts; Dream for wiki synthesis only.',
          'Cross-feature: after a large research or coding push, Run Dream so new facts land in wiki form.',
          'Cross-feature: sandbox/outbound policy still matters when Dream content later flows to providers via chat.'
],
      }
],
    related: [
      'scheduler-tasks',
      'workbench-tools',
      'settings-safety',
      'sessions-folders'
],
    openAction: { type: 'workbench', tool: 'wiki' },
  },
  {
    id: 'scheduler-tasks',
    category: 'scheduler',
    title: 'Scheduled tasks',
    summary:
      'Create cron or one-shot agent prompts from the Scheduler workbench panel — the /scheduler route redirects home; use Ctrl+S. Tasks deliver prompts to the team Lead of the matching mode without keeping a chat window focused.',
    keywords: [
      'scheduler',
      'cron',
      'schedule',
      'reminder',
      'one-shot',
      'Ctrl+S',
      '/scheduler',
      'pause',
      'resume',
      'trigger',
      'lịch',
      'đặt lịch',
      'nhắc nhở',
      'スケジュール',
      'クロン'
],
    setup:
      'Open Scheduler with Ctrl+S (workbench tool). The `/scheduler` route redirects home — always use the panel. Pick work or coding mode on the task so the prompt lands on the right Lead.',
    tricks: [
      'Pause, resume, or trigger tasks from the panel without waiting for the next cron tick.',
      'Coding context can prefill workspace/mode for new tasks.',
      'Tasks deliver prompts to the team Lead of the matching mode (work or coding).',
      'Use one-shot for reminders; use cron for recurring maintenance or Dream-adjacent routines you own.',
      'Do not confuse Scheduler with Dream’s own cron under Settings → Memory.',
      'Trigger manually after editing a prompt to verify it before trusting overnight cron.',
      'Keep scheduled prompts idempotent — reruns should not create duplicate messy side effects.',
      'Pause tasks before long laptop sleeps if your backend is local-only and will miss the window anyway.',
      'Name tasks by outcome (“weekday repo chore”) so the panel stays scannable.'
],
    blocks: [
      {
        type: 'p',
        text: 'Scheduled tasks send prompts to the agent team on a cron expression or as a one-shot run, without keeping a chat window open. Management UI lives only in the Scheduler workbench tool — there is no lasting `/scheduler` page.',
      },
      {
        type: 'p',
        text: 'Recurring ops (status digests, repo chores, reminders) should not depend on you being in the transcript. Scheduler decouples “when” from “which chat is focused,” so maintenance can happen while you are elsewhere.',
      },
      {
        type: 'p',
        text: 'Press Ctrl+S or open Scheduler from the workbench. Create a task with mode (work/coding), schedule, and prompt. Pause/resume/trigger from the same panel. Ignore bookmarking `/scheduler` — it redirects home by design so you are not stuck on an empty route.',
      },
      {
        type: 'tips',
        items: [
          'Ctrl+S — open Scheduler panel',
          'Cron — recurring agent prompts',
          'One-shot — single future run / reminder',
          'Pause / resume / trigger — lifecycle controls in-panel',
          'Mode — work or coding Lead target',
          '/scheduler — redirects home; do not bookmark',
          'Dream cron — separate under Settings → Memory'
],
      },
      {
        type: 'p',
        text: 'Step-by-step first cron task: (1) Ctrl+S, (2) create task, (3) choose coding or work, (4) set cron expression, (5) write a prompt with explicit Definition of Done, (6) Trigger once to validate, (7) leave enabled only after a good dry run, (8) Pause when the chore is obsolete instead of deleting immediately if you may reuse it.',
      },
      {
        type: 'p',
        text: 'When to use Scheduler vs Goal vs Dream: Scheduler fires discrete prompts on a clock; Goal continues an in-session autonomous objective; Dream synthesizes the Memory wiki on its own cron. Pick one mechanism per job — stacking all three on the same chore usually creates duplicate work.',
      },
      {
        type: 'p',
        text: 'Common mistakes: bookmarking `/scheduler` and thinking Scheduler is broken; pointing a Coding chore at work mode; writing prompts that assume UI focus or an open Terminal tab; confusing a missed local-sidecar window with a cron parser bug; using Scheduler to “run Dream” instead of Settings → Memory.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: set permission mode carefully on sessions that scheduled prompts will hit.',
          'Cross-feature: HealthDot must be green when the cron fires on a local sidecar.',
          'Cross-feature: for wiki consolidation use Dream; for “ask the Lead every Monday” use Scheduler.',
          'Idempotent prompts — safe if a trigger runs twice.'
],
      }
],
    related: [
      'memory-dream',
      'workbench-tools',
      'slash-goal',
      'troubleshooting-connection'
],
    openAction: { type: 'workbench', tool: 'scheduler' },
  },
  {
    id: 'browser-webbridge',
    category: 'browser',
    title: 'Built-in browser and WebBridge',
    summary:
      'Use the in-app browser (Ctrl+T), or pair a real Chrome/Edge session via the WebBridge extension with teach mode and per-chat enable. WebBridge is a CDP companion to the desktop app — not a web version of EvoFlux.',
    keywords: [
      'browser',
      'webbridge',
      'extension',
      'chrome',
      'edge',
      'cdp',
      'Ctrl+T',
      'teach',
      'pairing',
      'per-chat',
      'trình duyệt',
      'tiện ích',
      'dạy',
      'ブラウザ',
      '拡張機能',
      'ティーチ'
],
    setup:
      'Built-in: enable under Settings → Browser, then Ctrl+T. WebBridge: install the Chrome/Edge extension, enable master policy in Settings → Browser, pair from the desktop status control, then enable WebBridge per chat that should use it.',
    tricks: [
      'Ctrl+T toggles the built-in browser workbench — this is not WebBridge pairing.',
      'WebBridge can be enabled per chat; master policy lives in Settings → Browser.',
      'Teach mode records meaningful browser actions (not raw keystrokes) for reviewable replay with confirmation.',
      'Pairing uses scoped credentials and one-time session tickets; revoking a pairing closes the live relay.',
      'Selections and page context from the real browser are treated as untrusted input.',
      'WebBridge is not a web version of EvoFlux — it is a CDP companion to the desktop app.',
      'Use built-in Browser for sandboxed agent browsing; use WebBridge when you need real SSO cookies or corporate extensions.',
      'Revoke pairing when lending a machine or rotating access — outstanding tickets die with the revoke.',
      'Confirm teach replays before sharing monitored results into the agent loop.'
],
    blocks: [
      {
        type: 'p',
        text: 'Two browser paths exist: (1) the built-in in-app browser workbench for agent-driven pages inside EvoFlux, and (2) WebBridge, an extension that relays CDP control to your real Chrome or Edge profile with domain policy and audit trails. Pick the path that matches the login and trust model of the task.',
      },
      {
        type: 'p',
        text: 'Some tasks need a sandboxed in-app view; others need your real logged-in browser (SSO, corporate cookies, extensions). WebBridge bridges that gap without turning EvoFlux into a cloud web IDE. Treat page content as untrusted either way.',
      },
      {
        type: 'p',
        text: 'Built-in: Settings → Browser → enable, then Ctrl+T or the Browser tool. WebBridge: install the extension, enable policy in Settings → Browser, open the desktop WebBridge status control to pair, then enable WebBridge for the chats that should use it. Use Teach to record reviewable action sequences; confirm before monitored results are shared.',
      },
      {
        type: 'tips',
        items: [
          'Ctrl+T — built-in browser only',
          'Status control — pair / unpair WebBridge',
          'Per-chat toggle — allow the real browser for this session',
          'Teach — meaningful actions, no raw keystrokes',
          'Revoke pairing — kills relay + outstanding tickets',
          'Settings → Browser — master policy for both paths',
          'Untrusted input — selections/page context from the real browser'
],
      },
      {
        type: 'p',
        text: 'Step-by-step WebBridge: (1) install the Chrome/Edge extension, (2) enable master policy in Settings → Browser, (3) pair from the desktop status control, (4) open the target chat, (5) enable WebBridge for that chat, (6) optionally Teach a flow and confirm replay, (7) revoke pairing when finished with the machine or engagement.',
      },
      {
        type: 'p',
        text: 'When to use built-in vs WebBridge: built-in for disposable browsing and demos inside the harness; WebBridge for authenticated enterprise apps you already use in Chrome/Edge. When not to use WebBridge: public untrusted sites where a real profile’s cookies should never be exposed to agent control.',
      },
      {
        type: 'p',
        text: 'Common mistakes: pressing Ctrl+T expecting the extension to pair; enabling master policy but forgetting the per-chat toggle; treating teach recordings as raw keylogger scripts; leaving an old pairing alive on a shared laptop; pasting WebBridge page text into prompts without skepticism.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: sandbox/outbound policy still applies to what leaves toward providers.',
          'Cross-feature: if WebBridge is offline, check Troubleshooting before reinstalling the app.',
          'Cross-feature: side chat can clarify a page quote without stopping a main browser run.'
],
      }
],
    related: [
      'workbench-tools',
      'settings-safety',
      'troubleshooting-connection',
      'sandbox-settings'
],
    openAction: { type: 'settings', path: 'browser' },
  },
  {
    id: 'providers-settings',
    category: 'settings',
    title: 'Providers and models (BYOM)',
    summary:
      'Connect Anthropic, OpenAI, QwenCloud, Gemini, Bedrock, Ollama, and more — twenty built-in integrations behind one streaming abstraction — then pick models per agent or per session. EvoFlux does not lock you to a single vendor model.',
    keywords: [
      'provider',
      'model',
      'api key',
      'oauth',
      'ollama',
      'byom',
      'Anthropic',
      'OpenAI',
      'QwenCloud',
      'Gemini',
      'Bedrock',
      'DeepSeek',
      'xAI',
      'Vertex',
      'Copilot',
      'nhà cung cấp',
      'mô hình',
      'khóa api',
      'プロバイダ',
      'モデル',
      'APIキー'
],
    openAction: { type: 'settings', path: 'providers' },
    setup:
      'Settings → Providers. Have an API key, OAuth access, or a running local daemon URL ready. Confirm HealthDot is green before debugging empty model lists as a network outage.',
    tricks: [
      'Pick models independently per agent in Settings → Agents.',
      'Session pills on the composer set model, thinking level, and fast mode for the current chat.',
      'Provider list supports fuzzy model search.',
      'Local daemons (Ollama, etc.) use base URL overrides when needed.',
      'No models listed usually means zero configured providers — fix Providers before debugging chat.',
      'Context budget bar uses the selected model’s context_length from the registry.',
      'Use a fast model for Lead triage and a stronger model for Coding specialists when cost matters.',
      'After rotating keys, re-test with a tiny Work ping before starting Goal.',
      'OAuth providers still need a successful connect state — a half-finished OAuth leaves you model-less.',
      'QwenCloud subscription keys must use the matching Token Plan or Coding Plan Base URL shown by QwenCloud.'
],
    blocks: [
      {
        type: 'p',
        text: 'Providers are BYOM integrations (API key, OAuth, or local daemon) that expose models through one streaming layer. Supported families include Anthropic, OpenAI, QwenCloud, Google Gemini, AWS Bedrock, Ollama, DeepSeek, xAI, Vertex AI, GitHub Copilot, and more. Credentials live in Settings, not in chat.',
      },
      {
        type: 'p',
        text: 'EvoFlux does not lock you to a single vendor model. Different agents can use different models (fast Lead triage vs deep specialist coding) without changing the UI harness. Session pills let you override for one chat without editing agent defaults.',
      },
      {
        type: 'p',
        text: 'Open Settings → Providers, add credentials or a base URL, confirm the provider shows as configured, then assign defaults under Agents or override per session via composer pills. Use Diagnostics if streams fail after keys look correct. Fuzzy search helps when a provider exposes a long model list.',
      },
      {
        type: 'p',
        text: 'QwenCloud uses DASHSCOPE_API_KEY and defaults to the international pay-as-you-go OpenAI-compatible endpoint. Token Plan and Coding Plan keys (sk-sp-…) are not interchangeable with pay-as-you-go keys: copy the complete matching Base URL into Settings. Token Plan Individual terms may restrict schedules and other unattended automation, so verify your plan before using it for those runs.',
      },
      {
        type: 'tips',
        items: [
          'API key / OAuth / local daemon — three connect styles',
          'Settings → Agents — per-agent default models',
          'Composer pills — per-session model / thinking / fast mode',
          'context_length — drives the context budget bar',
          'Ollama — set base URL when not on the default port',
          'Empty model list — configure Providers first'
],
      },
      {
        type: 'p',
        text: 'Step-by-step first provider: (1) HealthDot green, (2) Settings → Providers, (3) add key or OAuth or daemon URL, (4) confirm configured state, (5) pick a default on the Lead under Agents, (6) send a short Work ping, (7) only then open large Coding tasks or Goal.',
      },
      {
        type: 'p',
        text: 'Common mistakes: pasting API keys into the transcript; debugging “no models” as a sidecar crash; assuming session pills changed agent defaults permanently; pointing Ollama at the wrong host from inside the desktop sandbox; ignoring rate-limit errors when HealthDot is still green.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: Diagnostics after credentials look right but streams fail.',
          'Cross-feature: stronger models raise context_length — watch /compact habits.',
          'Cross-feature: MCP and tools still need permission mode even with a perfect model.'
],
      }
],
    related: [
      'agents-settings',
      'getting-started',
      'connection-settings',
      'troubleshooting-connection'
],
  },
  {
    id: 'agent-plugins',
    category: 'plugins',
    title: 'Agent Plugins: install, trust, configure, and develop',
    summary:
      'Use Plugin Center to validate, import, inspect, configure, enable, edit, pack, update, and remove portable Agent Plugins. Understand the package boundary, trust review, credentials, Skill discovery, MCP runtime, and the checks to run when a plugin is not ready.',
    keywords: [
      'plugin',
      'plugins',
      'agent plugins',
      'plugin center',
      'evoplugin',
      'plugin.json',
      'mcp.json',
      'skill.md',
      'portable skills',
      'stdio',
      'streamable http',
      'credentials',
      'trust review',
      'enable',
      'link folder',
      'pack archive',
      'org.evoelsewhere.evoflux',
      'extension namespace'
],
    setup:
      'Open Plugins from either the Work or Coding sidebar. Use Add plugin → Import package for `.evoplugin`/ZIP, Link development folder for an unpacked directory, Validate folder for a read-only check, or Create plugin for a scaffold plus built-in editor.',
    tricks: [
      'A portable plugin contributes data and code through `plugin.json`, immediate-child `skills/*/SKILL.md`, and optional root `mcp.json`; it cannot inject custom EvoFlux UI.',
      'Import and Link install disabled by default. Read the trust review before selecting Trust and enable.',
      'Trust review lists executable commands and arguments, remote hosts, environment field names, and capabilities — never secret values.',
      'Choose Keep disabled when anything is unexpected; you can still edit files and configure credentials.',
      'Credentials are installation-scoped, stored outside the package, and injected only into that plugin’s stdio MCP processes.',
      'Use the canonical namespaces `org.evoelsewhere.evoflux.credentials` and `org.evoelsewhere.evoflux.mcp` for new packages.',
      'The legacy aliases `evoflux.credentials` and `evoflux.mcp` remain readable; canonical declarations win when both exist.',
      'Plugin MCP servers appear in Settings → MCP servers with a plugin badge; they are not copied into global MCP configuration.',
      'Plugin Skills become discoverable only while the installation is enabled and the Skill validates.',
      'Link is for live local development; Import copies a managed package. Pack produces a deterministic `.evoplugin` ZIP wrapper.',
      'Disabling stops/reconciles MCP runners and removes contributed Skills without deleting installation data.',
      'Uninstall preserves plugin data by default; remove data only when you intentionally want credentials and mutable state gone.'
],
    blocks: [
      {
        type: 'p',
        text: 'Agent Plugins 1.0 is the portable package contract. EvoFlux supports Agent Skills plus MCP stdio and Streamable HTTP. A plugin is an unpacked directory with a root `plugin.json`; `.evoplugin` is only a deterministic ZIP distribution wrapper. Legacy SSE entries are diagnosed but not started. Managed Agent Plugins are separate from trusted in-process legacy Python hooks.',
      },
      {
        type: 'tips',
        items: [
          'Required — `plugin.json` with the Agent Plugins 1.0 `$schema`, lowercase portable name, and optional version/description.',
          'Skills — direct children only: `skills/<skill-name>/SKILL.md`; nested Skill folders are resources, not extra discoverable Skills.',
          'MCP — optional root `mcp.json`; each server fails independently so one bad entry does not hide healthy siblings.',
          'Mutable data — use `${PLUGIN_DATA}`; bundled read-only files resolve from `${PLUGIN_ROOT}`.',
          'Host extensions — place EvoFlux-only declarations under the canonical reverse-domain namespaces in `plugin.json`.'
],
      },
      {
        type: 'p',
        text: 'Safe install sequence: (1) Add plugin, (2) import an archive or link a directory, (3) read package/component diagnostics, (4) inspect the enable trust review, (5) keep disabled if command, host, environment field, or capability is unfamiliar, (6) configure Credentials if declared, (7) toggle on and confirm Trust and enable, (8) verify Skills and MCP status, (9) run a harmless first tool under ask permission mode.',
      },
      {
        type: 'p',
        text: 'Trust review is static: EvoFlux reads declarations without starting plugin code. Executable disclosure includes the exact program and argument array for stdio servers. Remote disclosure includes host, URL, and transport. Environment disclosure contains names only from `mcp.json` and the credential schema. Capabilities include contributed Agent Skills, MCP transports, and declared EvoFlux server capabilities. Installation is not a global grant; normal permission and sandbox checks still apply to every tool call.',
      },
      {
        type: 'p',
        text: 'Credentials: open a plugin card → Actions → Credentials. Supported fields are text, secret, URL, and boolean. Required fields must be configured before the form is complete. Secrets are masked on read and stored outside the package with restrictive file permissions. They overlay declared stdio environment entries, after which EvoFlux forces trusted `PLUGIN_ROOT` and `PLUGIN_DATA`. Streamable HTTP does not receive these saved values; never place live secrets in portable headers.',
      },
      {
        type: 'p',
        text: 'Runtime behavior: an enabled valid Skill joins the normal metadata catalog and loads only when activated. Loading a plugin Skill makes ready MCP tools from the same installation available for that run, subject to permission rules. Settings → Skills shows discovery/validation; Settings → MCP servers shows plugin-badged runtime state and tool names. Runtime names contain installation hashes, so author instructions should refer to stable server/tool suffixes rather than copying a generated prefix.',
      },
      {
        type: 'p',
        text: 'Development: Add plugin → Create plugin accepts manifest metadata and a starter Skill, then opens the built-in editor. A blank Skill name defaults to the plugin name. EvoFlux does not generate MCP code, expose a host-interpreter alias, or install dependencies; add `mcp.json` only with a bundled/verified executable or supported remote endpoint. Use the file tree to edit and Validate before Pack. Link the directory for live development. A package cannot ship a custom settings page or arbitrary frontend; Plugin Center owns lifecycle, credentials, diagnostics, and runtime UI.',
      },
      {
        type: 'tips',
        items: [
          'Plugin does not install — open inspection diagnostics; fix fatal `plugin.json`, unsafe path, archive collision, symlink, size, or digest errors.',
          'Skill is missing — enable the installation; confirm `skills/<name>/SKILL.md` is one level below `skills/`, has valid frontmatter, and is not shadowed by a higher-precedence project/user Skill.',
          'MCP is missing from Settings — confirm the plugin is enabled, `mcp.json` validates, and the transport is stdio or Streamable HTTP rather than SSE.',
          'MCP is error — expand the runtime row; check executable path, arguments, working directory, startup logs, required credentials, and whether stdout is reserved for stdio protocol messages.',
          'Credentials page says unsupported — add `org.evoelsewhere.evoflux.credentials.fields` to `plugin.json`, then validate and return.',
          'Remote server is not ready — verify URL/host reachability and literal headers; stored plugin credentials are intentionally not injected into Streamable HTTP.',
          'Tools are not selected in chat — activate the matching plugin Skill or explicitly select the plugin MCP server for the agent; installation alone does not grant all tools.',
          'Changes look stale — Validate or save again, refresh Plugin Center, then disable/enable to reconcile the runtime.'
],
      },
      {
        type: 'p',
        text: 'CLI equivalent: `evoflux plugin inspect`, `create`, `link`, `install`, `show`, `enable`, `disable`, `pack`, `update`, and `uninstall`. CLI install/link also default to disabled. Run `show <installation-id>` and inspect `inspection.trust` before `enable`; use `--enabled` only when non-interactive automation has an independent trust gate.',
      }
],
    related: [
      'agents-settings',
      'permissions-modes',
      'workbench-tools',
      'troubleshooting-connection'
    ],
    openAction: { type: 'workbench', tool: 'plugins' },
  },
  {
    id: 'agent-plugins-authoring',
    category: 'plugins',
    title: 'Authoring reference: manifests, Skills, MCP, and extensions',
    summary:
      'Build a standards-compatible plugin directory with concrete file layouts and JSON examples. Learn which declarations are portable, which belong to EvoFlux extensions, and how to validate and package the result.',
    keywords: ['plugin authoring', 'manifest', 'plugin.json example', 'mcp.json example', 'skill frontmatter', 'credentials schema', 'capabilities', 'package layout'],
    setup: 'Start with Add plugin → Create plugin, or make the directory yourself and run `evoflux plugin inspect ./my-plugin` before linking or packing it.',
    blocks: [
      { type: 'heading', text: 'Package layout and ownership' },
      {
        type: 'code',
        language: 'text',
        caption: 'Portable directory',
        code: 'my-plugin/\n├── plugin.json\n├── skills/\n│   └── release-audit/\n│       ├── SKILL.md\n│       ├── references/\n│       └── scripts/\n├── mcp.json\n├── server.py\n├── README.md\n└── LICENSE',
      },
      {
        type: 'table',
        columns: ['Path', 'Required', 'Meaning'],
        rows: [
          ['plugin.json', 'Yes', 'Portable package identity and host extensions.'],
          ['skills/<name>/SKILL.md', 'No', 'Immediate-child Agent Skill; references/scripts stay inside its directory.'],
          ['mcp.json', 'No', 'Portable stdio, Streamable HTTP, or legacy SSE declarations.'],
          ['Implementation files', 'As needed', 'Bundled server code invoked by an MCP declaration.'],
          ['README / LICENSE', 'Recommended', 'Human setup, provenance, constraints, and licensing.'],
        ],
      },
      { type: 'heading', text: 'Minimal plugin.json' },
      {
        type: 'code',
        language: 'json',
        caption: 'Portable manifest',
        code: '{\n  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",\n  "name": "release-audit",\n  "version": "0.1.0",\n  "description": "Audit a release with guided instructions and read-only tools.",\n  "author": { "name": "Example Team" },\n  "repository": "https://example.com/plugins/release-audit",\n  "license": "MIT",\n  "keywords": ["release", "audit"],\n  "extensions": {}\n}',
      },
      {
        type: 'callout',
        title: 'Manifest rules',
        text: 'Names are 1–64 lowercase ASCII letters, digits, dots, or hyphens; they start/end alphanumeric and contain neither double hyphens nor consecutive dots. Unknown root fields warn and are ignored. Put client-specific data under extensions.',
      },
      { type: 'heading', text: 'Agent Skill contract' },
      {
        type: 'code',
        language: 'markdown',
        caption: 'skills/release-audit/SKILL.md',
        code: '---\nname: release-audit\ndescription: Inspect release evidence, checks, and risk before publishing.\n---\n\n# Release audit\n\n1. Gather bounded evidence.\n2. Use the plugin MCP tools only when live data is required.\n3. Separate facts, inference, and missing evidence.\n4. Never publish or mutate a release without explicit authorization.',
      },
      {
        type: 'p',
        text: 'Skill name must match the portable Agent Skills naming contract. Write a precise description because it drives discovery. Keep the core workflow in SKILL.md and load large references only when needed. Refer to MCP tools by stable suffix because EvoFlux prefixes runtime names per installation.',
      },
      {
        type: 'p',
        text: 'EvoFlux places no aggregate byte limit on Skill bundle resources. Per-file and entry-count limits, path containment, regular-file and symlink checks, and bounded Settings previews still apply. Chat attachment and upload limits are separate and unchanged.',
      },
      { type: 'heading', text: 'MCP stdio and Streamable HTTP' },
      {
        type: 'code',
        language: 'json',
        caption: 'mcp.json',
        code: '{\n  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",\n  "mcpServers": {\n    "local": {\n      "type": "stdio",\n      "command": "./bin/local-server",\n      "args": ["--cache", "${PLUGIN_DATA}/cache"],\n      "cwd": "${PLUGIN_ROOT}"\n    },\n    "remote": {\n      "type": "streamable-http",\n      "url": "https://api.example.com/mcp",\n      "headers": { "X-Client": "evoflux-plugin" }\n    }\n  }\n}',
      },
      {
        type: 'table',
        columns: ['Transport', 'Use when', 'Important constraints'],
        rows: [
          ['stdio', 'Server code ships with the plugin.', 'No shell command string; keep protocol stdout clean; credentials may be injected.'],
          ['streamable-http', 'A maintained remote endpoint provides MCP.', 'Redirects are disabled; package headers are literal; stored credentials are not injected.'],
          ['sse', 'Legacy declaration compatibility only.', 'Validated and diagnosed, but EvoFlux does not start it.'],
        ],
      },
      { type: 'heading', text: 'Credentials and capability extensions' },
      {
        type: 'code',
        language: 'json',
        caption: 'plugin.json extensions excerpt',
        code: '{\n  "extensions": {\n    "org.evoelsewhere.evoflux.credentials": {\n      "fields": [\n        {\n          "key": "endpoint",\n          "label": "Service URL",\n          "type": "url",\n          "env": "SERVICE_URL",\n          "required": true\n        },\n        {\n          "key": "token",\n          "label": "API token",\n          "type": "secret",\n          "env": "SERVICE_TOKEN",\n          "required": true\n        }\n      ]\n    },\n    "org.evoelsewhere.evoflux.mcp": {\n      "servers": {\n        "local": { "capabilities": ["webbridge-safe"] }\n      }\n    }\n  }\n}',
      },
      {
        type: 'callout',
        tone: 'warning',
        title: 'Do not package live secrets',
        text: 'Credential declarations contain field metadata, never values. Do not commit tokens, insert them into Streamable HTTP headers, print them to logs/stdout, or ask users to paste them into chat.',
      },
      { type: 'heading', text: 'Validate, link, pack, and update' },
      {
        type: 'code',
        language: 'shell',
        caption: 'Authoring loop',
        code: 'evoflux plugin inspect ./my-plugin\nevoflux plugin link ./my-plugin\nevoflux plugin show <installation-id>\nevoflux plugin enable <installation-id>\nevoflux plugin pack ./my-plugin\nevoflux plugin update <installation-id> ./my-plugin.evoplugin',
      },
      {
        type: 'p',
        text: 'Inspect after every contract change. Test component validation, startup, a harmless tool call, failure isolation, secret masking, result bounds, and disable/enable reconciliation. Pack only a valid directory; the archive remains a distribution format, not a new plugin contract.',
      },
    ],
    related: ['agent-plugins', 'agent-plugins-runtime-security', 'agent-plugins-troubleshooting'],
    openAction: { type: 'workbench', tool: 'plugins' },
  },
  {
    id: 'agent-plugins-runtime-security',
    category: 'plugins',
    title: 'Runtime and security: trust, credentials, permissions, and data',
    summary:
      'Understand exactly what happens from static inspection to enablement, how data and credentials cross the runtime boundary, and which protections still apply after a plugin is trusted.',
    keywords: ['plugin security', 'trust model', 'environment', 'plugin data', 'permission', 'sandbox', 'runtime manager', 'precedence', 'secret masking'],
    setup: 'Import or link the package, keep it disabled, and compare its trust review with the source files before enabling it.',
    blocks: [
      { type: 'heading', text: 'Lifecycle state machine' },
      {
        type: 'table',
        columns: ['Stage', 'Code runs?', 'What EvoFlux does'],
        rows: [
          ['Validate', 'No', 'Parse schemas, paths, URLs, components, extensions, and package digest.'],
          ['Install / Link', 'No by default', 'Register a disabled managed copy or developer directory.'],
          ['Trust review', 'No', 'Disclose commands, remote hosts, environment names, Skills/transports, and capabilities.'],
          ['Enable', 'Yes', 'Publish valid Skills and reconcile valid MCP runners.'],
          ['Disable', 'Stops code', 'Remove contributed Skills and stop/reconcile MCP runners; preserve data.'],
          ['Uninstall', 'No', 'Remove registration/package; preserve data unless explicitly deleted.'],
        ],
      },
      { type: 'heading', text: 'What trust review means' },
      {
        type: 'table',
        columns: ['Disclosure', 'Source', 'Question to ask'],
        rows: [
          ['Executable + args', 'stdio entries in mcp.json', 'Is this the expected interpreter/binary and bundled entrypoint?'],
          ['Remote host + URL', 'Streamable HTTP/SSE entries', 'Do I trust this operator, destination, port, and path?'],
          ['Environment names', 'stdio env plus credential schema', 'Why does the process need each variable?'],
          ['Capabilities', 'Skills, MCP transports, EvoFlux extension', 'Does the declared scope match the plugin purpose?'],
        ],
      },
      {
        type: 'callout',
        tone: 'warning',
        title: 'Trust is not permission bypass',
        text: 'Trust allows declared plugin components to participate in the runtime. Individual MCP tool calls still pass through agent selection, permission mode, and sandbox policy. A Skill activation is not authorization for destructive work.',
      },
      { type: 'heading', text: 'Process and data boundaries' },
      {
        type: 'code',
        language: 'text',
        caption: 'Host-mediated flow',
        code: 'plugin package (read-only files)\n        │ validate + trust review\n        ▼\ninstallation registry ── enabled? ──► Skill catalog\n        │                              MCP manager\n        └── private data/<id>/ ──────► PLUGIN_DATA + credentials env',
      },
      {
        type: 'p',
        text: 'Each installation has a stable private data directory outside the package. Updates preserve installation ID and PLUGIN_DATA. Credentials are stored there with restrictive permissions and injected only through declared environment names into stdio. Reserved PLUGIN_ROOT and PLUGIN_DATA are forced by the host after overrides. Package paths, symlinks, archive entries, URLs, headers, cwd, and placeholder expansion are validated before runtime adaptation.',
      },
      { type: 'heading', text: 'Skill and tool visibility' },
      {
        type: 'table',
        columns: ['Concern', 'Rule'],
        rows: [
          ['Skill precedence', 'Project/user/admin roots override enabled plugins; enabled plugins override EvoFlux built-ins.'],
          ['MCP configuration', 'Plugin declarations stay in a separate in-memory manager and never modify global mcp.json.'],
          ['Agent availability', 'Explicit MCP selection or activation of a same-installation Skill makes ready tools available for that run.'],
          ['WebBridge', 'Only explicitly declared safe capabilities may keep a non-browser plugin server visible in a WebBridge run.'],
          ['Failure isolation', 'Bad Skill/server entries are isolated; fatal manifest/package errors reject the package.'],
        ],
      },
      { type: 'heading', text: 'Review checklist before enable' },
      {
        type: 'tips',
        items: [
          'Verify publisher/source, package digest, license, and expected version.',
          'Read SKILL.md for hidden mutation instructions, secret requests, or overly broad claims.',
          'Inspect executable, arguments, bundled scripts, dependencies, cwd, and write destinations.',
          'Verify remote ownership and that headers contain no live credential.',
          'Confirm every environment field and capability is necessary.',
          'Configure least-privilege service credentials and test with a harmless read-only call.',
          'Keep permission mode on ask until behavior and result bounds are understood.',
        ],
      },
    ],
    related: ['agent-plugins', 'agent-plugins-authoring', 'permissions-modes', 'sandbox-settings'],
    openAction: { type: 'workbench', tool: 'plugins' },
  },
  {
    id: 'agent-plugins-troubleshooting',
    category: 'plugins',
    title: 'Agent Plugins troubleshooting and diagnostics',
    summary:
      'Diagnose installation, Skill discovery, credential setup, MCP startup, missing tools, stale development links, and packaging failures in a deterministic order.',
    keywords: ['plugin error', 'mcp not ready', 'skill missing', 'credentials unsupported', 'plugin logs', 'validation diagnostic', 'stale plugin', 'archive error'],
    setup: 'Keep the plugin disabled while inspecting package errors. Use Plugin Center diagnostics and `evoflux plugin inspect/show` before changing global MCP or reinstalling EvoFlux.',
    blocks: [
      { type: 'heading', text: 'Symptom → likely cause → next check' },
      {
        type: 'table',
        columns: ['Symptom', 'Likely cause', 'Next check'],
        rows: [
          ['Import rejected', 'Fatal manifest, unsafe archive/path, symlink, duplicate name, size/ratio limit', 'Read package diagnostics; inspect unpacked directory.'],
          ['Plugin valid but Skill absent', 'Disabled install, invalid/deep Skill, name collision', 'Enable; verify immediate-child SKILL.md and precedence.'],
          ['MCP absent from Settings', 'Disabled install, invalid mcp.json, only SSE entries', 'Inspect server diagnostics and supported transport.'],
          ['MCP starting forever', 'Process does not initialize or corrupts stdout', 'Run entrypoint manually; move logs to stderr; verify dependencies.'],
          ['MCP error', 'Bad command/args/cwd, missing credential, network/TLS failure', 'Expand runtime error and compare trust/config.'],
          ['Credentials unsupported', 'No canonical/legacy credential extension', 'Add fields extension, save, validate, refresh.'],
          ['Credentials incomplete', 'Required field missing or invalid URL/type', 'Fill required fields; leave configured secret blank only to preserve it.'],
          ['Tools not offered to agent', 'Server not ready or not selected/activated', 'Select MCP for agent or activate same-plugin Skill.'],
          ['Linked code looks stale', 'Unsaved file or runtime not reconciled', 'Save, Validate, refresh, disable/enable.'],
          ['Update fails', 'Invalid replacement or identity/package safety failure', 'Inspect new directory/archive before update; keep old installation.'],
        ],
      },
      { type: 'heading', text: 'Ordered diagnostic loop' },
      {
        type: 'code',
        language: 'shell',
        caption: 'CLI evidence',
        code: 'evoflux plugin inspect ./plugin-dir\nevoflux plugin list\nevoflux plugin show <installation-id>\nevoflux plugin disable <installation-id>\n# fix files or credentials, then:\nevoflux plugin enable <installation-id>',
      },
      {
        type: 'tips',
        items: [
          '1) Fix package-level errors first; component debugging is unreliable when plugin.json is invalid.',
          '2) Confirm the installation is the expected source_type, root, version, digest, and enabled state.',
          '3) Check Skill and MCP component diagnostics independently.',
          '4) Compare trust review with actual files and intended dependencies.',
          '5) Configure required credentials without exposing values in chat/logs.',
          '6) Inspect Settings → MCP servers runtime error and registered tool names.',
          '7) Test the server entrypoint with the same cwd and non-secret placeholder values.',
          '8) Re-enable, then make one bounded read-only tool call under ask mode.',
        ],
      },
      { type: 'heading', text: 'Common stdio protocol mistakes' },
      {
        type: 'table',
        columns: ['Mistake', 'Effect', 'Fix'],
        rows: [
          ['Logs printed to stdout', 'JSON-RPC stream is corrupted', 'Send operational logs to stderr.'],
          ['Shell expression used as command', 'No shell expansion; executable not found', 'Use command plus separate args array.'],
          ['Relative file assumes caller cwd', 'Works manually, fails in host', 'Use PLUGIN_ROOT or declare contained cwd.'],
          ['Writes into managed package', 'Update loses state or permission fails', 'Write mutable state under PLUGIN_DATA.'],
          ['Unbounded results/startup', 'Slow or oversized tool responses', 'Add timeouts, pagination, limits, and sanitized errors.'],
        ],
      },
      {
        type: 'callout',
        title: 'Do not “fix” plugin MCP in global Settings',
        text: 'Plugin-owned MCP is intentionally managed separately. Edit the plugin mcp.json or credentials, then validate/reconcile it. Adding a duplicate global server creates a second identity and hides the real package problem.',
      },
      { type: 'heading', text: 'Evidence to include in a bug report' },
      {
        type: 'tips',
        items: [
          'EvoFlux version/OS and whether the app is packaged or dev.',
          'Plugin name/version/source type and content digest — never credential values.',
          'Package, Skill, and MCP diagnostic codes/messages.',
          'Runtime server state, sanitized error, transport, and stable tool suffixes.',
          'Minimal plugin tree plus redacted plugin.json/mcp.json.',
          'Exact operation: import/link/update/enable and whether disable/enable changes it.',
        ],
      },
    ],
    related: ['agent-plugins', 'agent-plugins-authoring', 'agent-plugins-runtime-security', 'troubleshooting-connection'],
    openAction: { type: 'workbench', tool: 'plugins' },
  },
  {
    id: 'agents-settings',
    category: 'settings',
    title: 'Agents, skills, and MCP',
    summary:
      'Configure Markdown agents, skill packs, and MCP servers under Settings — tools inherit the same permission rules as native tools. Teams stay scoped to work / coding so the right specialists appear in each mode.',
    keywords: [
      'agents',
      'skills',
      'mcp',
      'stdio',
      'http',
      'sse',
      'tools',
      'frontmatter',
      'kỹ năng',
      'tác nhân',
      'máy chủ mcp',
      'スキル',
      'エージェント',
      'MCP'
],
    setup:
      'Settings → Agents for team members; Settings → Skills to validate packs; Settings → MCP to add servers. From chat, use /skill: or the command palette for New Agent / New Skill shortcuts.',
    tricks: [
      'Agents are .md files with YAML frontmatter — diffable and versionable.',
      'Settings → Skills creates, edits, displays, and filters skills by Work, Coding, or Both; valid skills appear under /skill: only in matching sessions.',
      'MCP status dots: ready / starting / auth / error / stopped.',
      'MCP tools inherit the same permission rules as native tools.',
      'Teams are scoped to work / coding.',
      'Command palette jumps to Edit <agent>… or create new agents and skills.',
      'Use tools_opt_out to disable code-owned tool defaults for one agent; remove an assigned skill directly from its skills list.',
      'Lead-only tools (ask_user, plan mode helpers, some worktree helpers) are never granted to specialists.',
      'If an MCP server sits on auth, finish the auth flow before blaming the composer slash menu.'
],
    blocks: [
      {
        type: 'p',
        text: 'Agents define role, model, tools, and system prompt. Skills are instruction packs loaded on demand via /skill:. MCP servers expose external tools over stdio, HTTP, or SSE. Together they are how you shape team behavior without forking the product.',
      },
      {
        type: 'p',
        text: 'Markdown agents and skills stay reviewable in git. MCP extends the tool surface without forking the core product, while permissions/sandbox still gate execution. Treat MCP like any other tool provider — least privilege, then widen.',
      },
      {
        type: 'p',
        text: 'Settings → Agents to edit team members; Settings → Skills to validate packs; Settings → MCP to add servers and watch status dots. From chat, type /skill: or open the palette for New Agent / New Skill. Lead-only tools (ask_user, plan mode, worktree helpers) are never granted to specialists.',
      },
      {
        type: 'tips',
        items: [
          'Agents — .md + YAML frontmatter',
          'Skills — /skill: after validation',
          'MCP — stdio / HTTP / SSE',
          'Status dots — ready / starting / auth / error / stopped',
          'tools_opt_out — disable code-owned tool defaults',
          'Mode scope — work / coding teams',
          'Lead-only tools — never on specialists'
],
      },
      {
        type: 'p',
        text: 'Step-by-step add an MCP server: (1) Settings → MCP, (2) choose transport, (3) configure command or URL, (4) wait for ready (finish auth if needed), (5) confirm tools appear, (6) run a harmless tool under ask mode, (7) only then loosen permissions.',
      },
      {
        type: 'p',
        text: 'Common mistakes: expecting invalid skills in the slash menu; granting specialists Lead-only tools in your head; leaving MCP on error and retrying chat; putting secrets in agent markdown committed to a public repo; forgetting mode scope so a Coding specialist never appears in Work.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: activated Coding skills teach the workflow; native code_context validates and executes every retrieval action.',
          'Cross-feature: workflows and skills both need scope validity to show in /.',
          'Cross-feature: permission Always rules apply to MCP tools too — prefer Once first.'
],
      }
],
    related: [
      'composer-power',
      'permissions-modes',
      'coding-graph',
      'slash-commands'
],
    openAction: { type: 'settings', path: 'agents' },
  },
  {
    id: 'sandbox-settings',
    category: 'settings',
    title: 'Sandbox and outbound protection',
    summary:
      'Configure filesystem-tool deny globs, worktree location, process limits, environment exposure, and outbound PII redaction.',
    keywords: [
      'sandbox',
      'deny',
      'isolation',
      'pii',
      'outbound',
      'worktree',
      'user_data',
      'glob',
      'hộp cát',
      'chặn',
      'bảo vệ',
      'サンドボックス',
      '拒否',
      '隔離'
],
    openAction: { type: 'settings', path: 'sandbox' },
    setup:
      'Settings → Sandbox. Review deny patterns before enabling aggressive auto/bypass permission modes. Help popovers on the page explain ** and * glob syntax.',
    tricks: [
      'Deny patterns use ** and * globs; help popovers in Settings explain syntax.',
      'Worktree location (repository vs user_data) lives on the Sandbox page.',
      'Outbound redact/block runs before content reaches the provider when enabled.',
      'Goal mode keeps the same workspace and deny-pattern policy.',
      'Symlinks into blocked roots are rejected; shell commands are tokenized for denied-path checks.',
      'Combine accept-edits or auto with a tight denylist for day-to-day coding speed.',
      'Deny credential caches and unrelated disks even if you trust the model.',
      'Re-test a sample tool call after editing globs — silent mis-globs feel like “tools are broken.”',
      'Pair filesystem denylist with Settings → Browser domain policy for WebBridge.'
],
    blocks: [
      {
        type: 'p',
        text: 'Built-in filesystem tools enforce workspace roots, read-only roots, and deny patterns under every permission mode. Shell commands are scanned for obvious denied paths, but run directly on the host without OS-level containment.',
      },
      {
        type: 'p',
        text: 'Permission modes decide when to ask. Application-level path checks remain active for built-in tools, while shell-command scanning is a guardrail rather than a security boundary. Goal mode keeps the same policy.',
      },
      {
        type: 'p',
        text: 'Open Settings → Sandbox. Add deny globs, set the Coding worktree location, configure process limits and environment exposure, and enable outbound PII redact/block as needed. Re-test a sample tool call after changes. Pair with Settings → Browser domain policy for WebBridge.',
      },
      {
        type: 'tips',
        items: [
          'Deny globs — ** and * patterns',
          'Worktree location — repository vs user_data',
          'Outbound PII — redact/block before provider',
          'Symlinks — rejected into blocked roots',
          'Shell tokenization — denied-path checks on commands',
          'Goal — never widens sandbox scope'
],
      },
      {
        type: 'p',
        text: 'Step-by-step harden a Coding laptop: (1) list sensitive roots (keys, cloud sync, other clients), (2) add deny globs, (3) set worktree location intentionally, (4) enable outbound redact if policy requires, (5) run a probe tool under ask, (6) only then consider accept-edits or auto for speed.',
      },
      {
        type: 'p',
        text: 'Common mistakes: enabling bypass with an empty denylist on a home directory workspace; forgetting symlinks; assuming outbound redact replaces not pasting secrets; putting worktrees on user_data then wondering why disk usage moved; confusing a deny hit with an MCP auth failure.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: plan Reject when a plan targets denied paths instead of fighting the sandbox.',
          'Cross-feature: Troubleshooting “tools denied” checklist includes shield + denylist.',
          'Cross-feature: Coding worktrees follow the Sandbox location policy.'
],
      }
],
    related: [
      'permissions-modes',
      'settings-safety',
      'coding-workspaces',
      'slash-goal'
],
  },
  {
    id: 'connection-settings',
    category: 'settings',
    title: 'Connection settings',
    summary:
      'Point the UI at the bundled local sidecar or an external EvoFlux server URL with access key — first stop when HealthDot goes red. Packaged apps default to the bundled sidecar with an ephemeral port and token handshake.',
    keywords: [
      'connection',
      'sidecar',
      'external',
      'access key',
      'HealthDot',
      'backend',
      'URL',
      'token handshake',
      'ephemeral port',
      'kết nối',
      'máy chủ',
      '接続',
      'サイドカー'
],
    openAction: { type: 'settings', path: 'connection' },
    setup:
      'Settings → Connection (or click HealthDot). Packaged apps default to the bundled sidecar. From source, ensure `make dev` is up before `make -C desktop dev`.',
    tricks: [
      'Bundled sidecar uses an ephemeral port and token handshake — you usually do not set a URL.',
      'External mode needs a reachable server URL and access key.',
      'From source, ensure `make dev` is up before `make -C desktop dev`.',
      'After switching connection mode, wait for Welcome/team ready before sending chat.',
      'Diagnostics complements Connection when the URL is fine but a subsystem is down.',
      'Click HealthDot anytime for a shortcut into Connection.',
      'Relaunch the packaged app to restart a wedged bundled sidecar before editing unrelated settings.',
      'Do not paste access keys into chat transcripts when configuring external mode.',
      'If you toggle external → bundled, confirm HealthDot returns green before assuming Providers broke.'
],
    blocks: [
      {
        type: 'p',
        text: 'Connection settings choose between the bundled local FastAPI sidecar and an external EvoFlux backend. HealthDot reflects whether the UI can reach a healthy server. Most desktop users never leave bundled mode.',
      },
      {
        type: 'p',
        text: 'Wrong connection mode looks like “chat is dead” even when Providers are perfect. Separating Connection from Providers and Diagnostics saves time: first reach a healthy backend, then check credentials and subsystems.',
      },
      {
        type: 'p',
        text: 'Open Settings → Connection. Keep bundled for normal desktop use. Switch to external only when you intentionally run a remote or separately launched API. Click HealthDot anytime for a shortcut here. After changes, wait for Welcome/team ready before sending chat.',
      },
      {
        type: 'tips',
        items: [
          'Bundled — ephemeral port + token handshake',
          'External — server URL + access key',
          'HealthDot — shortcut into Connection',
          'Welcome — wait for sidecar/team ready',
          'From source — `make dev` then `make -C desktop dev`',
          'Diagnostics — when URL is fine but a subsystem fails'
],
      },
      {
        type: 'p',
        text: 'Step-by-step recover a red HealthDot (packaged): (1) click HealthDot, (2) confirm bundled mode, (3) relaunch the app to restart the sidecar, (4) wait for Welcome to clear, (5) open Diagnostics if still unhealthy, (6) only then touch Providers.',
      },
      {
        type: 'p',
        text: 'Step-by-step external mode: (1) start or locate the remote/local API, (2) copy base URL and access key, (3) Settings → Connection → external, (4) save, (5) wait for health, (6) verify a tiny chat. Revert to bundled if you are back on a normal single-machine desktop workflow.',
      },
      {
        type: 'p',
        text: 'Common mistakes: typing a Vite URL as the API URL; starting the Tauri shell before `make dev`; switching to external for “debugging” and forgetting; sending chat during Welcome; treating a green HealthDot as proof that every subsystem (MCP, git host, WebBridge) is fine — use Diagnostics for that.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: Getting started cold-start order matches Connection recovery.',
          'Cross-feature: Scheduler cron on a local sidecar still needs the machine awake and healthy.',
          'Cross-feature: Troubleshooting checklist starts at HealthDot → Connection.'
],
      }
],
    related: [
      'troubleshooting-connection',
      'getting-started',
      'settings-safety',
      'providers-settings'
],
  },
  {
    id: 'settings-safety',
    category: 'settings',
    title: 'Settings map',
    summary:
      'A map of every settings page: providers, agents, skills, MCP, memory, connection, git, sandbox, browser, notifications, appearance, telemetry, and diagnostics. Knowing which page owns which concern avoids hunting.',
    keywords: [
      'settings',
      'connection',
      'appearance',
      'notifications',
      'telemetry',
      'diagnostics',
      'git',
      'version-control',
      'memory',
      'mcp',
      'cài đặt',
      'bản đồ',
      '設定',
      'マップ'
],
    openAction: { type: 'settings', path: '' },
    tricks: [
      'Desktop shows settings categories in the sidebar rail; mobile uses the About hub as a nav list.',
      'Guidelines (this help) is also linked from Settings → About.',
      'Telemetry has a full page at /telemetry as well as Settings → Telemetry.',
      'Git & reviews hosts PR connections and safety policy (timeouts, max diff, force-with-lease).',
      'Appearance includes theme, accent, fonts, motion, and locale (en / vi / ja).',
      'Diagnostics is for live subsystem checks — complementary to HealthDot’s binary signal.',
      'Intelligence vs System vs Application groupings keep risky toggles from mixing with theme picks.',
      'Notifications include a test ping — use it before trusting unfocused alerts.',
      'Open the command palette if you forget which settings page owns a toggle.'
],
    blocks: [
      {
        type: 'p',
        text: 'Settings is grouped into Intelligence (Providers, Agents, Skills, MCP), Knowledge (Memory / Dream), System (Connection, Git & reviews, Sandbox, Browser, Notifications), and Application (Appearance, Telemetry, Diagnostics), plus About. Use this map when you know the concern but not the page name.',
      },
      {
        type: 'p',
        text: 'Knowing which page owns which concern avoids hunting: models vs agents vs sandbox vs browser policy are intentionally separate so risky toggles stay deliberate. Theme changes should never sit next to force-with-lease in your mental model.',
      },
      {
        type: 'tips',
        items: [
          'Providers — API keys, OAuth, local daemons, model registry',
          'Agents — model, tools, system prompt per team member',
          'Skills — instruction packs for /skill:',
          'MCP servers — stdio / HTTP / SSE external tools',
          'Memory — long-term wiki + Dream schedule',
          'Connection — bundled sidecar vs external URL / access key',
          'Git & reviews — host connections, timeouts, diff size, force-with-lease',
          'Sandbox — deny globs, process limits, worktree location, outbound PII',
          'Browser — built-in WebView + WebBridge master policy',
          'Notifications — desktop/mobile alerts when unfocused; test ping',
          'Appearance — theme, accent, fonts, motion, locale (en / vi / ja)',
          'Telemetry — traces and summary (also /telemetry)',
          'Diagnostics — live subsystem health checks',
          'About — app info + Guidelines link'
],
      },
      {
        type: 'p',
        text: 'Step-by-step new machine checklist: (1) Connection healthy, (2) Providers connected, (3) Agents models assigned, (4) Sandbox denylist reviewed, (5) Git & reviews hosts if you need PRs, (6) Browser/WebBridge policy if needed, (7) Appearance locale, (8) Notifications test ping, (9) open Guidelines from About once to confirm help works.',
      },
      {
        type: 'p',
        text: 'Common mistakes: changing Appearance when chat fails; looking for Dream cron under Scheduler; looking for PR host tokens under Providers; expecting mobile settings chrome to match desktop rail layout; ignoring Diagnostics because HealthDot is green.',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: each major Guidelines article deep-links via openAction to the right page when available.',
          'Cross-feature: locale changes UI chrome only — chat content stays as written.',
          'Cross-feature: empty telemetry often means extras disabled, not a chat outage.'
],
      }
],
    related: [
      'providers-settings',
      'agents-settings',
      'sandbox-settings',
      'connection-settings',
      'troubleshooting-connection'
],
  },
  {
    id: 'keyboard-shortcuts',
    category: 'shortcuts',
    title: 'Keyboard shortcuts',
    summary:
      'EvoFlux uses the native primary modifier — Command on macOS, Ctrl on Windows/Linux. Guidelines (Help) remains separate from the command palette.',
    keywords: [
      'shortcut',
      'keyboard',
      'ctrl',
      'hotkey',
      'palette',
      'Ctrl+P',
      'Ctrl+N',
      'Ctrl+B',
      'Ctrl+V',
      'macOS',
      'phím tắt',
      'bàn phím',
      'ショートカット',
      'キーボード'
],
    tricks: [
      'The primary modifier + P opens the command palette (Search in the sidebar). Help opens this Guidelines modal — not the palette.',
      'Shortcut badges update automatically: ⌘ on macOS, Ctrl on Windows/Linux.',
      'While typing in an input, copy/paste/select/undo keys keep their native edit behavior; the view-cycle shortcut is suppressed during paste.',
      'Ctrl+B is owned once by AppShell for all mode sidebars.',
      'Ctrl+R refreshes Work sessions only (not a full app reload).',
      'Prefer Ctrl+P search by action name when you forget a binding.',
      'Keys 1–5 only switch permission modes while the shield menu is open.',
      'Ctrl+I focuses chat input — useful after clicking through workbench panels.'
],
    blocks: [
      {
        type: 'p',
        text: 'Global navigation and workbench shortcuts use Command on macOS and Ctrl on Windows/Linux. The badges and the live bindings resolve from the same platform rule.',
      },
      {
        type: 'p',
        text: 'Native edit shortcuts keep priority while focus is inside an input. Outside editable controls, the table below uses the platform primary modifier.',
      },
      {
        type: 'shortcuts',
        rows: [
          { keys: 'Ctrl+P', action: 'Command palette' },
          { keys: 'Ctrl+N', action: 'New team chat' },
          { keys: 'Ctrl+B', action: 'Toggle sidebar' },
          { keys: 'Ctrl+V', action: 'Cycle Agent ↔ Split (desktop; not while pasting)' },
          { keys: 'Ctrl+F', action: 'Files / Changed & Files (label may show ⌘P)' },
          { keys: 'Ctrl+M', action: 'Memory wiki' },
          { keys: 'Ctrl+S', action: 'Scheduler' },
          { keys: 'Ctrl+K', action: 'Plugins' },
          { keys: 'Ctrl+T', action: 'Built-in browser' },
          { keys: 'Ctrl+G', action: 'Git Changes (Coding)' },
          { keys: 'Ctrl+`', action: 'Terminal' },
          { keys: 'Ctrl+I', action: 'Focus chat input' },
          { keys: 'Ctrl+;', action: 'Side chat (label may show ⌥⌘S)' },
          { keys: 'Ctrl+R', action: 'Refresh Work sessions' },
          { keys: '1–5', action: 'Permission modes when shield menu is open' }
],
      },
      {
        type: 'p',
        text: 'Prefer the command palette (Ctrl+P) when you forget a binding — most actions are searchable by name. Guidelines (Help) stays separate so palette search remains command-focused. Graph and Review rely on the workbench bar or palette because they have no dedicated global shortcut.',
      },
      {
        type: 'tips',
        items: [
          'Help button — Guidelines modal (docs)',
          'Ctrl+P — command palette (actions)',
          '⌘P / ⌥⌘S labels — stale; use Ctrl+F / Ctrl+;',
          'Ctrl+V — view cycle suppressed while pasting',
          'Ctrl+R — Work sessions refresh only',
          '1–5 — only with shield menu open'
],
      },
      {
        type: 'p',
        text: 'Common mistakes: pressing Cmd+P on macOS expecting the palette; using Ctrl+R thinking it reloads the whole app; fighting Ctrl+V in the composer during paste; assuming Graph has a hidden hotkey; opening Help when you meant the palette (or vice versa).',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: permission shield + 1–5 is faster than clicking modes.',
          'Cross-feature: Ctrl+; side chat during Goal without /stop.',
          'Cross-feature: Ctrl+G after plan Accept to verify diffs.'
],
      }
],
    related: [
      'workbench-tools',
      'getting-started',
      'permissions-modes',
      'side-chat'
],
    openAction: { type: 'palette' },
  },
  {
    id: 'troubleshooting-connection',
    category: 'troubleshooting',
    title: 'Connection and diagnostics',
    summary:
      'When the backend is down, sessions fail, or health checks go red — use HealthDot, Connection, Diagnostics, and the common fix checklist. Separate connection, provider, permission, and WebBridge failures before reinstalling.',
    keywords: [
      'troubleshoot',
      'connection',
      'health',
      'diagnostics',
      'sidecar',
      'HealthDot',
      'make dev',
      'error',
      'lỗi',
      'sự cố',
      'chẩn đoán',
      '接続',
      '診断',
      'トラブル'
],
    setup:
      'Start at HealthDot in the sidebar footer. Keep Settings → Connection and Settings → Diagnostics nearby. From source, have two terminals ready: `make dev` and `make -C desktop dev`.',
    tricks: [
      'Click HealthDot → Connection to verify bundled vs external backend.',
      'Settings → Diagnostics runs live checks across subsystems.',
      'Cold start shows Welcome until the sidecar and team are ready — wait before retrying chat.',
      'From source: Terminal 1 `make dev`, Terminal 2 `make -C desktop dev`.',
      'No models listed → Settings → Providers before anything else.',
      'Tools denied unexpectedly → permission mode + Sandbox deny globs.',
      'WebBridge offline → extension installed, pairing valid, Browser settings enabled, per-chat toggle on.',
      'Empty telemetry → observability/DuckDB extras may be disabled — not necessarily a chat outage.',
      'Goal stuck → inspect blocker streak, budget pause, or /goal:stop.',
      '/scheduler 404-feeling → use Ctrl+S panel; route redirects home.'
],
    blocks: [
      {
        type: 'p',
        text: 'Most “EvoFlux is broken” reports are connection, provider, permission, or WebBridge pairing issues. HealthDot is the binary signal; Diagnostics is the detailed panel; Connection chooses which backend the UI talks to. Fix in that order before reinstalling.',
      },
      {
        type: 'p',
        text: 'The UI can be up while the sidecar is still booting, pointed at the wrong URL, or missing provider credentials. Separating those failure modes saves time and avoids destructive “reset everything” reflexes that hide the real cause.',
      },
      {
        type: 'p',
        text: 'Check HealthDot. If unhealthy, open Connection and confirm bundled sidecar vs external URL/key. From source, ensure both `make dev` and `make -C desktop dev` are running. Packaged apps should relaunch to restart the sidecar. Then open Diagnostics for subsystem checks. Only after health is green, verify Providers, permission mode, Sandbox, and Browser/WebBridge.',
      },
      {
        type: 'tips',
        items: [
          'HealthDot red/amber → Connection + wait for Welcome/team ready',
          'Source runs → `make dev` then `make -C desktop dev`',
          'No models → Settings → Providers',
          'Stream errors with green health → model/provider credentials or rate limits',
          'Tools denied → permission mode (ask/plan) + Sandbox deny globs',
          'WebBridge offline → extension, pairing, Browser policy, per-chat enable',
          'Empty telemetry → observability extras disabled (often non-blocking)',
          'Goal stuck → inspect blocker streak, budget pause, or /goal:stop',
          '/scheduler 404-feeling → use Ctrl+S panel; route redirects home',
          'Stale graph → reindex from Graph tool after huge external edits'
],
      },
      {
        type: 'p',
        text: 'Ordered checklist: (1) HealthDot, (2) Connection mode, (3) Welcome/team ready, (4) Diagnostics, (5) Providers, (6) permission shield, (7) Sandbox denylist, (8) Browser/WebBridge, (9) mode-specific tools (Changes/Graph/Review only in Coding). Stop at the first failing layer.',
      },
      {
        type: 'p',
        text: 'Common mistakes: reinstalling for a missing provider key; debugging MCP while HealthDot is red; assuming green health means Ollama is up; force-refreshing with Ctrl+R expecting a full reload (it refreshes Work sessions only).',
      },
      {
        type: 'tips',
        items: [
          'Cross-feature: Getting started cold-start order matches this checklist.',
          'Cross-feature: plan review pending Accept is not a hang — resolve the panel.',
          'Cross-feature: side chat focus mistakes look like “Lead ignored me.”',
          'When in doubt — Diagnostics + a tiny Work ping beat speculative resets.'
],
      }
],
    related: [
      'getting-started',
      'connection-settings',
      'settings-safety',
      'providers-settings',
      'browser-webbridge'
],
    openAction: { type: 'settings', path: 'diagnostics' },
  }
]
