# Tools, Skills, MCP, and plugins

EvoFlux separates executable capabilities from instruction bundles. Tools are
runtime callables; Skills are lazily loaded instructions/resources that teach an
agent how to use available capabilities; MCP and Agent Plugins extend those
surfaces through explicit host-managed boundaries.

## Native tools

The built-in registry covers:

- filesystem read/search/edit/write/patch/remove;
- shell, Python, managed processes and previews;
- web search/fetch, persistent browser and WebBridge;
- LSP, diagnostics, and code-review actions;
- todos, notes, memory, goals, plans, scheduling and user questions;
- worktrees and team delegation/message/handoff/rework/state;
- deferred-tool loading;
- visualization/widget output and multimodal reads.

Each tool declares a JSON-like argument schema and an async handler. Deferred
tools expose only compact catalogue metadata until selected. Tool execution
passes through argument validation, observation policy, permission/sandbox
checks, output bounding and streaming telemetry.

### `ui_block` — native structured UI

`ui_block` renders declarative, shadcn-native UI blocks in the conversation as
one complete `ui_block` SSE event (never delta-streamed). It is the structured
sibling of `show_widget`: **`ui_block` for the catalog; `show_widget` only for
arbitrary HTML** (iframe/CSS escape hatch).

| Block `type` | Renders | Limits (server-validated) |
|---|---|---|
| `stat_cards` | metric cards with delta/hint | 1–6 cards |
| `chart` | chart placeholder/visualization | free-form `spec` object |
| `steps` | step progress with status icons | 1–12 steps, detail ≤400 |
| `table` | column-keyed data table | ≤12 columns, ≤200 rows |
| `key_value` | label/value list | 1–20 pairs |
| `callout` | info/success/warning/error note | body ≤1000 |
| `buttons` | prompt-dispatching button row | 1–5 buttons |
| `form` | fields + submit | 1–8 fields, ≤8 form size |
| `progress` | labeled progress bar | `0 ≤ value`, `max > 0` |
| `flashcards` | tap-to-flip review cards | 1–20 cards, front ≤400 / back ≤800 |
| `checklist` | interactive tick list with progress | 1–40 items, label ≤200 / detail ≤300 |
| `calculator` | live-recompute calculator | 1–12 inputs & outputs, safe arithmetic formulas |

One call carries 1–6 blocks. Unknown `type` values fail validation and the
tool returns `success: false` with `valid_types` instead of emitting a broken
event; the frontend additionally renders a neutral "Unsupported block" card.

**Interactivity round-trip (no new endpoint).** Buttons dispatch their
`prompt` as a normal user message through the store's `sendMessage` action;
form submits compose `${title}` plus one `- label: value` line per filled
field. The agent therefore sees the answers as a normal user message — the
tool itself receives no structured result (accepted trade-off; a future
`ui_interaction` continuation may replace it). Toggles stay client-side.

**Guidance fields (optional, server-capped).** Blocks explain themselves so
the user always knows what the UI does and what happens on submit:

| Block | Field | Cap | Where it renders |
|---|---|---|---|
| `form` | `description` | 240 | muted text directly under the form title — what the form does and what happens on submit |
| `form` field | `helper` | 160 | small muted text under the field label, wired as `aria-describedby` |
| `form` field | required marker | — | free-text fields (`text`/`textarea`) show `*` + `aria-required`; submit stays disabled with an inline "fill in the required (*) fields" hint until they are filled |
| `buttons` | `hint` | 160 | small muted text under the button row |
| `buttons` | accessible name | — | each button is announced as `<label> — sends this message to the agent` |
| `steps` | `description` | 240 | muted text above the list, framing the walkthrough |
| `steps` | status word | — | next to every step: done → **Done**, active → **Now**, pending → **Next**, error → **Blocked**; the active step's title is bold |
| `stat_cards` card | `hint` | 160 | small muted text under the value |
| `flashcards` | `title` | 120 | bold title above the "Card n of m" counter; the card itself flips on tap/click (keyboard: it is a real button) |
| `checklist` | `title` / `description` | 120 / 300 | title above, description under it; a live "N of M done" counter and thin progress bar sit above the items — tick state stays local to the viewer |
| `calculator` | `description` | 300 | muted text under the title; number inputs have − / + steppers and outputs recompute on every keystroke |

**Calculator safety.** Output formulas are validated server-side (Pydantic)
and evaluated client-side by a hand-rolled arithmetic parser — numbers,
input names, and `+ - * / ( )` only. No `eval`/`Function` anywhere; anything
else (function calls, `**`, unknown names, unbalanced parentheses) is
rejected at validation time and surfaces as an inline error if it ever
reaches the renderer.

**Example showcase.** Copy-pasteable `blocks` argument for `ui_block` — a
guided four-step walkthrough: a purpose-framed intake form with helper text,
buttons that say what they do, and stat cards with hints:

```json
{
  "title": "Your first project",
  "blocks": [
    {
      "type": "steps",
      "description": "Follow these four steps to launch your first project — I'll check each one off as you go.",
      "steps": [
        { "title": "Name your project", "status": "done", "detail": "Any name works; you can rename it later." },
        { "title": "Connect a repository", "status": "active", "detail": "Paste a Git URL or let me scaffold one for you." },
        { "title": "Pick the agents you need", "status": "pending", "detail": "A coder plus a reviewer covers most projects." },
        { "title": "Run the first task", "status": "pending", "detail": "I'll open a session and start working." }
      ]
    },
    {
      "type": "form",
      "title": "Project intake",
      "description": "Your answers are sent to the agent as one message — it replies right in this chat.",
      "fields": [
        { "name": "project_name", "label": "Project name", "kind": "text", "placeholder": "invoice-tracker", "helper": "Shown in the sidebar; you can rename it any time." },
        { "name": "goal", "label": "What should the agent build first?", "kind": "textarea", "helper": "One or two sentences — this becomes your first task." },
        { "name": "stack", "label": "Preferred stack", "kind": "select", "options": ["Python + FastAPI", "TypeScript + React"], "helper": "Leave blank and I'll infer it from the repository." }
      ],
      "submit_label": "Send answers"
    },
    {
      "type": "buttons",
      "buttons": [
        { "label": "Use my template", "prompt": "Use my standard project template and show me the summary." },
        { "label": "Start from scratch", "prompt": "Guide me through a blank project setup, one step at a time." }
      ],
      "hint": "Each button sends that message to the agent."
    },
    {
      "type": "stat_cards",
      "cards": [
        { "label": "Projects", "value": 3, "delta": "+1 this week", "delta_tone": "up", "hint": "Across Work and Coding mode" },
        { "label": "Open tasks", "value": 7, "hint": "3 waiting on your review" },
        { "label": "Agents ready", "value": 5, "hint": "Coder, reviewer, researcher and 2 more" }
      ]
    }
  ]
}
```

**Persistence.** The block payload is the tool's own arguments, so history
reload reconstructs it losslessly from the persisted `tool_calls` JSON — no
database migration; the live event is deduplicated by `tool_call_id`.

**Interactive showcase.** One compact call using all three interactive
blocks — flashcards for review, a checklist with progress, and a
calculator whose outputs recompute live as the user types or steppers:

```json
{
  "title": "Sunday roast planner",
  "blocks": [
    {
      "type": "flashcards",
      "title": "Roast basics",
      "cards": [
        { "front": "Why rest the lamb after roasting?", "back": "It lets the juices redistribute — carving too early loses them onto the board." },
        { "front": "Crispiest potatoes, in one sentence?", "back": "Rough up the boiled edges, then roast in hot fat, turning once." }
      ]
    },
    {
      "type": "checklist",
      "title": "Shopping list",
      "description": "For 8 guests — tick items as you shop.",
      "items": [
        { "label": "Lamb shoulder", "detail": "3.6 kg (guests × 0.45 kg)", "checked": true },
        { "label": "Potatoes", "detail": "4 kg (guests × 0.5 kg)" },
        { "label": "Rosemary & garlic", "detail": "2 bulbs, 1 bunch" },
        { "label": "Olive oil, salt, pepper" }
      ]
    },
    {
      "type": "calculator",
      "title": "Adjust the numbers",
      "description": "Change the guest count — shopping amounts update live.",
      "inputs": [
        { "name": "guests", "label": "Guests", "value": 8, "min": 1, "step": 1 }
      ],
      "outputs": [
        { "label": "Lamb", "formula": "guests * 0.45", "unit": "kg", "decimals": 2 },
        { "label": "Potatoes", "formula": "guests * 0.5", "unit": "kg", "decimals": 1 },
        { "label": "Gravy", "formula": "guests / 4", "unit": "L", "decimals": 2 }
      ]
    }
  ]
}
```

A bill-split calculator is the same shape: inputs `total` and `people`,
one output with formula `total / people`.

## Agent Skills

EvoFlux follows Anthropic's Agent Skills architecture; the full contract is
[Agent Skills](../architecture/agent-skills.md).

- A Skill is a directory with `SKILL.md` (YAML `name` + `description`
  frontmatter and Markdown instructions) plus optional reference files,
  `scripts/` and `assets/`.
- Discovery covers project (`.evoflux/skills`, `.agents/skills`,
  `.claude/skills` up to the Git root), user (`{CONFIG_DIR}/skills`,
  `~/.agents/skills`, `~/.claude/skills`), enabled plugin and built-in roots,
  in that precedence order.
- Only each Skill's name, description and `SKILL.md` location are in the
  system prompt. The model reads `SKILL.md` with the `read` tool when a task
  matches, reads referenced files on demand, and runs bundled scripts with
  `shell`. There is no dedicated Skill tool and no router model call.
- Users type `$skill-name` to activate a Skill explicitly; an agent's
  `skills:` field preloads Skills into that agent's system prompt.
- Skills are available in Work and Coding mode alike. Settings lists every
  discovered Skill with its diagnostics, creates and edits user Skills, and
  turns any Skill on or off (`skill-settings.json`).

EvoFlux does not impose an aggregate byte ceiling on Skill bundle resources.
Managed create/update and validation still enforce the per-resource size and
entry-count budgets, reject symlinks and unsafe paths, require regular files,
and keep Settings previews bounded. This relaxation applies only to Skill
bundles; chat attachment and upload limits remain separate and unchanged.

## Global MCP client

Global servers are configured in `{CONFIG_DIR}/mcp.json`. EvoFlux supports
stdio and HTTP transports in the current Settings/API schema and retains
compatibility with supported MCP client transports in the runtime. Environment
references expand from the process or config `.env`; secret values are not
materialized into API responses.

`MCPRuntime` watches configuration, reconciles enabled servers, exposes status
and maps tools into the agent registry. MCP tools use the same permission
system as native tools. OAuth responses are stored in the cache root and are
scoped by server.

The Python runtime currently locks the MCP SDK to `2.2.0` and uses its native
`stdio_client` and `streamable_http_client` transports. Streamable HTTP headers
and OAuth are supplied through the SDK's native `httpx2` client; protocol
handshake versions remain negotiated per server by `ClientSession`.

The runtime is split into explicit boundaries:

```text
MCPRuntime
├── config watcher/reconciler + public registry
├── MCPServerRunner per server
│   └── ClientSession lifecycle and tool projection
└── MCPTransportFactory
    ├── stdio
    └── Streamable HTTP + httpx2 + OAuth
```

Global and plugin MCP runtimes share these components but use separate runtime
instances and configuration scopes. `MCPManager` remains as a compatibility
facade for existing integrations.

## Agent Plugins

Portable Agent Plugins use a root `plugin.json`, immediate-child `skills/` and
optional `mcp.json`. Plugin Center and CLI support inspect, scaffold, import,
install, development-link, update, pack, enable/disable and uninstall.

Plugin Center's Create flow defaults a blank starter Skill name to the plugin
name, so a new scaffold contributes a discoverable workflow instead of only a
manifest. EvoFlux does not generate an MCP server: `mcp.json` is added only by
an author who supplies a portable executable or remote endpoint. Static
validation does not install dependencies or prove process readiness. A remote
server awaiting authorization remains visible as **Authentication required**;
enabling does not grant access or make its tools available.

New installations are disabled until the user reviews executable commands,
remote hosts, environment-field names and declared capabilities. Plugin
credentials and data live outside the package and survive in-place updates.
Plugin MCP servers run in an installation-scoped manager and are never copied
into global `mcp.json`.

Plugin packages cannot inject frontend code or bypass permissions. Portable
stdio and Streamable HTTP servers execute; legacy SSE declarations are
validated/reported but not started by the plugin runtime.

See [Agent Plugin architecture](../architecture/agent-plugins.md) and the
[operator guide](../guides/agent-plugins.md).

### Marketplaces

The **Marketplace** tab in Plugin Center can add and sync Agent Plugins 1.0.0
and Claude Code marketplace sources, then search their cached catalogs. Source
setup and saved-source cards stack in narrow Plugin Center drawers and share a row
when the panel has enough width. Results use compact selectable rows with local
monograms, compatibility, and source cues; results stay full-width until a plugin
is selected. On wide panels, selected details stay in a sticky side panel whose
review/install action remains in view; narrow panels retain the details drawer.
Search and source filters remain above the results, alongside category, component
and compatibility filters. Categories/keywords come from catalog declarations;
missing metadata is shown as uncategorized or not declared, never guessed from
names. Preparing an individual package identifies its supported/unsupported
components without fetching every catalog entry.

Plugin Center starts with compact neutral rows and a short overview instead of
full configuration and repeated health summaries. **Components**, **Package
files**, and **Technical details** expose the deeper data on demand; paths,
fingerprints, runtime IDs and nonblocking warnings are not shown by default.
Blocking errors and required authorization stay visible. Search remains visible,
while **Filters** reports active selections and **Manage marketplaces** holds
source setup/sync controls (open initially when no source exists).

**Inspect package** prepares a selected package for read-only review, not
installation. Review displays each Skill and its description/path/validation,
each MCP transport and command/arguments or remote URL, environment/header field
names, capabilities, diagnostics, README, and a bounded file list/text viewer.
Files are displayed as inert text: HTML, scripts and remote images are not
executed or rendered. Sensitive files are excluded and credentials are masked.
Validation errors or an unavailable file listing block the installation action;
late inspection results cannot replace another selected package.

Installed rows show a short durable-origin label: marketplace, imported archive,
imported directory, development link, built-in, or unknown. Expanded details keep
the full marketplace/source identity. Origin/component
filters are separate from Marketplace filters. Local package drafts are labelled
as development packages, not installations. Old installations without provenance
remain unknown instead of being retroactively attributed to a marketplace.

Marketplace sources/catalogs
remain separate from installed-plugin records. Artifact packages are checked
against their declared size and SHA-256 before inspection. Unsupported entries
show why EvoFlux cannot install them. `unverified` is a trust warning, not an
installability check; compatible unverified entries can still be reviewed.

Claude Code marketplace entries can be installed only from supported relative,
URL, GitHub, or Git subdirectory sources; npm and command sources are not
installed or executed. Claude Code content is normalized only into compatible
Skills and MCP configuration. Commands, agents, hooks, and other unsupported
components are not imported or executed. Agent Plugins entries must declare
`portable: true`, provide at least one supported Skills or MCP component, and
not exclude `evoflux` in `compatibleClients`. When a package is only partly
compatible, Plugin Center requires confirmation to install supported components
only; the CLI requires `--allow-partial`. Installed marketplace plugins remain
disabled until the user explicitly enables them.

## Legacy Python hooks

Trusted local Python hook plugins under the configured plugin directories are a
separate, host-code extension mechanism. They are not portable Agent Plugins
and have a stronger trust requirement because they execute in the application
process.

## Source and tests

Primary code: `app/agent/tools/`, `app/agent/skills/`, `app/agent/mcp/`,
`app/plugin_platform/`, Skill/MCP/Plugin API routes, Settings editors and Plugin
Center.

Focused coverage exists under `tests/agent/tools`, `tests/agent/skills`,
`tests/agent/mcp`, `tests/plugin_platform`, API route tests and frontend Skill,
MCP and Plugin Center tests.
