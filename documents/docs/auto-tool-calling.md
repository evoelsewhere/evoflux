---
title: Auto Tool Calling — User-Defined Tools
description: Plan for letting users create, test, and deploy custom shell/Python tools that become first-class agent tool-calls.
status: draft
updated: 2026-06-23
---

# Auto Tool Calling — User-Defined Tools

Users define tools by writing a shell command or Python script. They set named
variables (like secrets or config values) that get injected at runtime. Once a
tool passes the built-in test runner it is saved and automatically available to
any agent as a tool-call — indistinguishable from built-in tools (`shell`,
`python`, `web_fetch`, etc.).

A dedicated **`tool-builder` skill** lets the agent itself create tools on
behalf of the user through natural conversation — no UI required.

---

## Table of Contents

1. [User journey](#1-user-journey)
2. [Data model](#2-data-model)
3. [Backend — API & services](#3-backend--api--services)
4. [Tool runtime — how custom tools run](#4-tool-runtime--how-custom-tools-run)
5. [Agent integration](#5-agent-integration)
6. [The `tool-builder` skill](#6-the-tool-builder-skill)
7. [Frontend — UI](#7-frontend--ui)
8. [Migration](#8-migration)
9. [File layout](#9-file-layout)
10. [Implementation order](#10-implementation-order)

---

## 1. User journey

There are two entry points. Both produce identical DB records.

### A. Conversational (primary) — `/create-tool-calling` slash command

```
Phase 1 — Design (agent, no secrets asked)
──────────────────────────────────────────
User:  /create-tool-calling
       "Tạo tool gọi GitHub REST API để tạo Pull Request"

Agent (loads tool-builder skill):
  1. Confirms intent, infers name → "github_create_pr"
  2. Drafts parameters: title (string), branch (string), base (string, default "main")
  3. Writes Python template using {{GITHUB_TOKEN}}, {{GITHUB_REPO}}, {{title}}, {{branch}}, {{base}}
  4. POST /api/custom-tools → tool saved (enabled=false until tested)
  5. POST /api/custom-tools/variables for each {{VARIABLE}} with value="" (empty placeholder)
  6. Replies:
       ✅ Tool "github_create_pr" created.
       ⚠️  Set these variables in Settings → Custom Tools → Variables:
           • GITHUB_TOKEN  — your Personal Access Token
           • GITHUB_REPO   — e.g. "owner/repo"
       Then run /test-tool github_create_pr to verify.

Phase 2 — Configure & test (user, in Settings)
───────────────────────────────────────────────
User opens Settings → Custom Tools → Variables
  → fills GITHUB_TOKEN = "ghp_..."
  → fills GITHUB_REPO  = "khuonghung/evoflux"

User opens the tool → clicks "Run Test" (or types /test-tool github_create_pr)
  → test runner calls POST /api/custom-tools/{id}/test
  → shows exit code + output
  → on success: tool auto-enables → live in all agents
```

**Why agent never asks for secret values in chat:**
- Secrets typed in chat pass through LLM context and appear in session logs.
- Agent only *identifies* what variables are needed (name + description).
- User sets actual values in Settings (plain input with masking) — never through the model.

### B. Settings UI (manual)

```
Settings → Custom Tools
  ├── Variables tab   ← define GITHUB_TOKEN, BASE_URL, ... (fill values here)
  └── Tools tab
        ├── New Tool button
        │     ├── Name + description (shown to LLM)
        │     ├── Type: Shell | Python
        │     ├── Parameters (what the LLM fills in)
        │     ├── Template editor ({{VARIABLE}} + {{param}})
        │     └── Save → jumps to test runner
        ├── Test runner  ← fill params → Run → see output → enable
        └── Tool list (toggle enabled, edit, delete)
```

---

## 2. Data model

### 2.1 DB tables (SQLModel / SQLite WAL)

#### `custom_tool_variables` — global + per-tool variables

```python
class CustomToolVariable(SQLModel, table=True):
    __tablename__ = "custom_tool_variables"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    # NULL  → global variable (shared across all tools)
    # set   → per-tool override
    tool_id: UUID | None = Field(default=None, foreign_key="custom_tools.id",
                                  sa_column=Column(sa.Uuid(), ForeignKey(
                                      "custom_tools.id", ondelete="CASCADE"),
                                      nullable=True, index=True))
    name: str = Field(max_length=64)    # e.g.  GITHUB_TOKEN
    value: str = Field(default="")      # empty = "needs to be set by user"
    description: str = Field(default="", max_length=256)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
```

A variable with `value=""` means the user has not set it yet. The test runner
checks for empty values and returns a clear error: `"Variable GITHUB_TOKEN is
not set — go to Settings → Custom Tools → Variables to set it."`

#### `custom_tools` — tool definitions

```python
class CustomTool(SQLModel, table=True):
    __tablename__ = "custom_tools"

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    name: str = Field(max_length=64, unique=True)    # tool-call name for LLM
    description: str = Field(max_length=1024)         # what the LLM sees
    tool_type: str = Field(max_length=16)             # "shell" | "python"
    template: str                                      # command/script body
    # JSON list of ParameterDef objects
    parameters: list[dict] = Field(default_factory=list,
                                   sa_column=Column(JSON))
    # False when created via /create-tool-calling; becomes True only after
    # a successful test run. Prevents untested tools from being called.
    enabled: bool = Field(default=False)
    # Last test run result — drives the Settings UI badge
    last_test_exit: int | None = Field(default=None)
    last_test_output: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
```

#### `ParameterDef` schema (stored in `parameters` JSON column)

```python
class ParameterDef(BaseModel):
    name: str                      # param name in template  {{name}}
    description: str               # shown to LLM
    type: Literal["string", "integer", "boolean", "number"] = "string"
    required: bool = True
    default: str | int | bool | float | None = None
    enum: list[str] | None = None  # restrict to choices
```

### 2.2 Variable resolution order

At runtime, variables are resolved in this priority (highest first):

```
1. Per-tool variables  (tool_id = <this tool's id>)
2. Global variables    (tool_id = NULL)
3. Process environment (os.environ)
```

Template placeholders: `{{VARIABLE_NAME}}` and `{{param_name}}`.

---

## 3. Backend — API & services

### 3.1 New API routes  `app/api/routes/custom_tools.py`

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/custom-tools` | List all tools |
| `POST` | `/api/custom-tools` | Create tool |
| `GET` | `/api/custom-tools/{id}` | Get tool |
| `PUT` | `/api/custom-tools/{id}` | Update tool |
| `DELETE` | `/api/custom-tools/{id}` | Delete tool |
| `POST` | `/api/custom-tools/{id}/test` | Test run (returns output) |
| `GET` | `/api/custom-tools/variables` | List global variables |
| `POST` | `/api/custom-tools/variables` | Create global variable |
| `PUT` | `/api/custom-tools/variables/{id}` | Update global variable |
| `DELETE` | `/api/custom-tools/variables/{id}` | Delete global variable |

### 3.2 Request / response schemas  `app/api/schemas/custom_tools.py`

```python
class ParameterDefBody(BaseModel):
    name: str
    description: str
    type: Literal["string", "integer", "boolean", "number"] = "string"
    required: bool = True
    default: str | int | bool | float | None = None
    enum: list[str] | None = None

class CustomToolBody(BaseModel):
    name: str
    description: str
    tool_type: Literal["shell", "python"]
    template: str
    parameters: list[ParameterDefBody] = []
    enabled: bool = True

class CustomToolTestBody(BaseModel):
    # param values to fill in for the test run
    param_values: dict[str, str | int | bool | float] = {}
    timeout_seconds: int = 30

class VariableBody(BaseModel):
    name: str                       # e.g. "OPENAI_KEY"
    value: str
    description: str = ""
    tool_id: UUID | None = None     # None → global
```

### 3.3 Service layer  `app/services/custom_tool_service.py`

```python
async def list_tools(db: AsyncSession) -> list[CustomTool]: ...
async def create_tool(db, body: CustomToolBody) -> CustomTool: ...
async def update_tool(db, tool_id: UUID, body: CustomToolBody) -> CustomTool: ...
async def delete_tool(db, tool_id: UUID) -> None: ...

async def test_tool(
    db: AsyncSession,
    tool_id: UUID,
    param_values: dict,
    timeout: int,
) -> tuple[int, str]:
    """Render template, run it, return (exit_code, output).

    Pre-flight: reject if any variable has value="" (not yet set by user).
    On success (exit_code == 0): set tool.enabled = True automatically.
    """
    tool = await _get_tool(db, tool_id)
    variables = await _resolve_variables(db, tool_id)

    # Check for unset variables before running
    unset = [k for k, v in variables.items() if v == ""]
    if unset:
        names = ", ".join(unset)
        return 1, (
            f"[Not ready] Variable(s) not set: {names}\n"
            f"Go to Settings → Custom Tools → Variables to set them."
        )

    rendered = _render_template(tool.template, variables, param_values)
    if tool.tool_type == "shell":
        exit_code, output = await _run_shell(rendered, timeout)
    else:
        exit_code, output = await _run_python(rendered, timeout)

    # Auto-enable on first successful test
    if exit_code == 0 and not tool.enabled:
        tool.enabled = True
    tool.last_test_exit = exit_code
    tool.last_test_output = output[:4096]
    await db.commit()

    return exit_code, output

def _render_template(template: str, variables: dict, params: dict) -> str:
    """Replace {{NAME}} with resolved values; raise on missing placeholders."""
    context = {**variables, **params}
    missing = set(re.findall(r"\{\{(\w+)\}\}", template)) - context.keys()
    if missing:
        raise ValueError(f"Unresolved placeholders: {missing}")
    for key, val in context.items():
        template = template.replace(f"{{{{{key}}}}}", str(val))
    return template
```

`_run_shell` / `_run_python` reuse the same subprocess pattern as
`app/agent/tools/builtin/shell.py` and `python.py` (including the
`NotImplementedError` → `asyncio.to_thread` fallback added in the Windows fix).

---

## 4. Tool runtime — how custom tools run

### 4.1 Dynamic `Tool` construction  `app/agent/tools/custom_loader.py`

At agent startup, `load_custom_tools(db)` queries enabled `CustomTool` rows
and wraps each one in a standard `Tool` object from `app/agent/tools/registry`.

```python
from app.agent.tools.registry import Tool

async def load_custom_tools(db: AsyncSession) -> list[Tool]:
    tools = await list_enabled_tools(db)
    return [_make_tool(t, db) for t in tools]

def _make_tool(ct: CustomTool, db: AsyncSession) -> Tool:
    """Build a runtime Tool from a CustomTool row."""

    # Build a Pydantic model for the tool's parameters so the registry
    # can generate the correct OpenAI function schema.
    fields = {
        p["name"]: (
            _py_type(p["type"]),
            Field(description=p["description"],
                  default=p.get("default", ...),
            ),
        )
        for p in ct.parameters
    }
    ParamModel = create_model(f"_{ct.name}_params", **fields)

    async def _run(**kwargs: Any) -> str:
        variables = await _resolve_variables(db, ct.id)
        rendered = _render_template(ct.template, variables, kwargs)
        if ct.tool_type == "shell":
            exit_code, output = await _run_shell(rendered, timeout=60)
        else:
            exit_code, output = await _run_python(rendered, timeout=120)
        status = "[Succeeded]" if exit_code == 0 else f"[Failed — exit code {exit_code}]"
        return f"{status}\n\n{output}"

    return Tool(_run, name=ct.name, description=ct.description)
```

### 4.2 Security / sandbox

- Custom shell tools run through the same `SandboxConfig` / `check_command`
  path as built-in shell tool.
- Python tools run via `sys.executable` (same interpreter), sandboxed by OS
  user permissions.
- Variable values are **never** logged; `_render_template` is called only at
  runtime, not stored as rendered text.
- In v1, variable values are stored in plaintext SQLite. A follow-up
  can encrypt with OS keychain (`keyring` package).

---

## 5. Agent integration

### 5.1 Loading custom tools into the agent

In `app/services/chat_service.py` (or wherever `build_tools` is called for a
session), append the result of `load_custom_tools(db)`:

```python
all_tools = builtin_tools + await load_custom_tools(db)
```

Custom tools must not shadow built-in names — the service raises
`ValueError` at load time if there is a name collision.

### 5.2 Agent tool list (`builtin_prompts.py`)

Custom tools are **not** hardcoded in `NORMAL_EVOFLUX_TOOLS`. Instead they
are dynamically appended at session initialisation so the LLM system prompt
gets an up-to-date list.

### 5.3 Auto-discovery

No agent config change is needed. When `enabled = True` every new custom tool
is immediately callable in every chat session. Toggle `enabled = False` to
hide a tool without deleting it.

---

## 6. The `tool-builder` skill

### 6.1 Purpose

The skill is a bundled SKILL.md installed by `EvoFlux init` (via
`seed/skills/tool-builder/SKILL.md`). When the user asks the agent to create,
edit, or test a custom tool through conversation, the agent loads this skill
and follows its step-by-step protocol.

This is the conversational alternative to the Settings UI — both paths write
to the same DB tables and produce identical results.

### 6.2 Skill file layout

```
seed/skills/
  tool-builder/
    SKILL.md          ← loaded by the agent (frontmatter + instructions)
    api-reference.md  ← full endpoint + schema reference (agent reads via read tool)
    examples.md       ← example tools: GitHub PR, send Slack, run backup, ...
```

### 6.3 `SKILL.md` content design

```markdown
---
name: tool-builder
description: Create, test, and manage custom agent tools via conversation.
  Teach the agent the tool API and template syntax so it can build shell/Python
  tools on behalf of the user and register them as first-class tool-calls.
---

# Tool Builder

You can create persistent custom tools that agents call like built-in tools.
Tools are shell commands or Python scripts with named parameters and
{{VARIABLE}} placeholders for secrets/config.

## When to load this skill

Load when the user says things like:
- "tạo tool …", "create a tool …", "add a tool that …"
- "edit / update / delete my tool …"
- "test tool …", "what tools do I have?"

## Workflow: create a new tool

1. **Understand intent** — ask the user:
   - What should the tool do? (one sentence)
   - What will the LLM pass as arguments? (names, types, descriptions)
   - Are there secrets or config values (API keys, URLs) to inject?

2. **Check existing variables** — GET /api/custom-tools/variables
   Match needed secrets to existing global variables.
   If missing, tell the user: "I need to store {{GITHUB_TOKEN}} — what's the value?"
   Then POST /api/custom-tools/variables to create it.

3. **Draft the template** — write shell or Python that:
   - Uses {{VARIABLE_NAME}} for variables resolved from settings
   - Uses {{param_name}} for LLM-supplied parameters
   - Is non-interactive (no stdin prompts)
   - Returns meaningful stdout on success

4. **Create the tool** — POST /api/custom-tools with:
   ```json
   {
     "name": "snake_case_name",
     "description": "One sentence the LLM reads when deciding whether to call this tool.",
     "tool_type": "shell" | "python",
     "template": "...",
     "parameters": [
       {"name": "title", "description": "PR title", "type": "string", "required": true}
     ]
   }
   ```

5. **Test** — POST /api/custom-tools/{id}/test with sample param values.
   Inspect exit_code and output.
   If exit_code ≠ 0: iterate on the template (PUT /api/custom-tools/{id}).
   Repeat until [Succeeded].

6. **Confirm** — tell the user the tool name, description, and that it is live.
   Example: "Tool `github_create_pr` is ready. Agents can call it now."

## Template syntax rules

| Placeholder | Resolved from | Example |
|-------------|---------------|---------|
| `{{VARIABLE_NAME}}` | Variables settings (global or per-tool) | `{{GITHUB_TOKEN}}` |
| `{{param_name}}` | LLM-supplied argument at call time | `{{branch}}` |

- Placeholders are case-sensitive.
- All placeholders must resolve before the tool runs — the runtime raises
  an error listing any unresolved ones.
- Never hard-code secrets in the template body.

## API quick-reference

Read `api-reference.md` (same directory) for full schemas.
Read `examples.md` for ready-made templates to adapt.

## Edit / delete / list

- List tools: GET /api/custom-tools
- Get one:   GET /api/custom-tools/{id}
- Update:    PUT /api/custom-tools/{id}  (same body as POST)
- Delete:    DELETE /api/custom-tools/{id}
- Toggle:    PUT /api/custom-tools/{id}  with {"enabled": false}
```

### 6.4 `api-reference.md` — full schema for the agent

Contains the complete OpenAPI-style description of every endpoint, request
body field, and response field so the agent never has to guess. Updated
whenever the API changes.

### 6.5 `examples.md` — ready-made templates

Bundled examples the agent can adapt:

| Tool | Type | Description |
|------|------|-------------|
| `github_create_pr` | Python | POST to GitHub REST API, returns PR URL |
| `slack_notify` | Python | POST to Slack incoming webhook |
| `run_backup` | Shell | `rsync` workspace to a target path |
| `http_get` | Python | Generic `httpx.get` with `{{URL}}` + `{{HEADERS}}` |
| `docker_run` | Shell | `docker run --rm {{IMAGE}} {{COMMAND}}` |
| `send_email` | Python | `smtplib` with `{{SMTP_HOST}}`, `{{SMTP_USER}}`, `{{SMTP_PASS}}` |

### 6.6 Agent HTTP access to the custom tool API

The agent uses the `shell` tool (or the `python` tool with `httpx`) to call
`http://localhost:{port}/api/custom-tools/...` — the same port the EvoFlux
server is running on. The skill instructs the agent to discover the port
from `EVOFLUX_API_PORT` env var or default to `8000`.

Alternatively, expose the endpoints as a dedicated **MCP resource** so the
agent can call them without shell/python — a follow-up improvement.

---

## 7. Frontend — UI

### 7.1 Placement

Custom Tools lives inside the existing **Settings** panel (Settings sidebar →
new **Tools** section), below Agents and Skills.

```
Settings sidebar
  ├── Agents
  ├── Skills
  ├── MCP Servers
  └── Custom Tools   ← NEW
        ├── Variables
        └── Tools
```

### 7.2 Variables tab  `web/src/components/settings/CustomToolVariables.tsx`

A simple CRUD table:

| Column | Description |
|--------|-------------|
| Name | `SCREAMING_SNAKE_CASE` identifier |
| Value | Text input (masked if name contains `KEY`, `SECRET`, `TOKEN`, `PASSWORD`) |
| Description | Short label for context |
| Scope | Global / per-tool |
| Actions | Edit · Delete |

- **Add Variable** button → inline row or modal
- Values masked in UI by default (show/hide toggle per row)

### 7.3 Tools tab  `web/src/components/settings/CustomToolsList.tsx`

List view same style as Agents list:

- Each row: tool name · type badge (Shell / Python) · description excerpt ·
  enabled toggle · Edit · Delete
- **New Tool** button → detail / create panel

### 7.4 Tool editor  `web/src/components/settings/CustomToolEditor.tsx`

Two-pane layout (responsive: stacked on mobile, side-by-side ≥ md):

**Left pane — definition**

```
Name           [text input]  — e.g.  github_create_pr
Description    [textarea]    — shown to LLM
Type           [Shell | Python toggle]
Parameters     — dynamic list
  + Add parameter
    Name · Type · Description · Required · Default

Template       [Monaco / CodeMirror editor]
  Shell:  multi-line command, supports &&, pipes, {{VAR}}, {{param}}
  Python: full script, same placeholders
```

**Right pane — test runner**

```
Variables in use   — resolved preview (masked for secrets)
Parameters
  [for each param: label + input]
[Run Test]  ←  calls POST /api/custom-tools/{id}/test
─────────────────────
Output:
  ┌─────────────────────────────┐
  │ [Succeeded]                 │
  │                             │
  │ <stdout / stderr>           │
  └─────────────────────────────┘
  Exit code: 0  · Runtime: 1.2 s
```

- **Run Test** is only available after the tool is saved (has an id).
- On success the editor shows a green badge; on failure it shows exit code +
  output so the user can iterate.

### 7.5 Template editor hints

- Syntax highlighting: `bash` (shell) or `python` (Monaco language mode).
- Hover on `{{NAME}}` shows the resolved value preview (masked for secrets).
- Unresolved placeholders highlighted in red.

### 7.6 Frontend data hooks  `web/src/hooks/useCustomTools.ts`

```typescript
// TanStack Query hooks
useCustomTools()           // GET /api/custom-tools
useCustomTool(id)          // GET /api/custom-tools/:id
useCreateCustomTool()      // POST
useUpdateCustomTool()      // PUT
useDeleteCustomTool()      // DELETE
useTestCustomTool()        // POST /api/custom-tools/:id/test
useCustomToolVariables()   // GET /api/custom-tools/variables
```

---

## 8. Migration

New migration `app/migrations/versions/00000011_create_custom_tools.py`:

```
CREATE TABLE custom_tool_variables (
    id UUID PK,
    tool_id UUID FK→custom_tools(id) ON DELETE CASCADE NULLABLE,
    name VARCHAR(64) NOT NULL,
    value TEXT NOT NULL,
    description VARCHAR(256),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(tool_id, name)
);

CREATE TABLE custom_tools (
    id UUID PK,
    name VARCHAR(64) NOT NULL UNIQUE,
    description VARCHAR(1024) NOT NULL,
    tool_type VARCHAR(16) NOT NULL,
    template TEXT NOT NULL,
    parameters JSON DEFAULT '[]',
    enabled BOOLEAN DEFAULT TRUE,
    last_test_exit INTEGER,
    last_test_output TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

---

## 9. File layout

```
app/
  models/
    custom_tool.py            ← CustomTool + CustomToolVariable SQLModel
  migrations/versions/
    00000011_create_custom_tools.py
  services/
    custom_tool_service.py    ← CRUD + test runner + variable resolution
  agent/tools/
    custom_loader.py          ← load_custom_tools(db) → list[Tool]
  api/routes/
    custom_tools.py           ← FastAPI router
  api/schemas/
    custom_tools.py           ← Pydantic request/response schemas

seed/
  skills/
    tool-builder/
      SKILL.md                ← agent instructions for tool creation
      api-reference.md        ← full endpoint + schema reference
      examples.md             ← ready-made templates to adapt
  commands/
    create-tool-calling.md    ← /create-tool-calling slash command
    test-tool.md              ← /test-tool [name] slash command

web/src/
  hooks/
    useCustomTools.ts         ← TanStack Query hooks
  components/settings/
    CustomToolVariables.tsx   ← Variables CRUD table
    CustomToolsList.tsx       ← Tools list view
    CustomToolEditor.tsx      ← Tool create / edit + test runner
```

---

## 10. Implementation order

Work in strict dependency order so each step is independently testable:

| Step | What | Files touched |
|------|------|---------------|
| 1 | DB migration — create both tables | `models/custom_tool.py`, migration |
| 2 | Service layer CRUD + `_render_template` + test runner (auto-enable on success, empty-var guard) | `services/custom_tool_service.py` |
| 3 | API routes + schemas, register in `api/app.py` | `api/routes/custom_tools.py`, `api/schemas/custom_tools.py` |
| 4 | `custom_loader.py` — build `Tool` objects from enabled rows | `agent/tools/custom_loader.py` |
| 5 | Wire into chat session tool loading | `services/chat_service.py` |
| 6 | Backend tests | `tests/services/test_custom_tool_service.py`, `tests/api/test_custom_tools.py` |
| 7 | **`tool-builder` skill** — SKILL.md + api-reference.md + examples.md | `seed/skills/tool-builder/` |
| 8 | **`/create-tool-calling` slash command** — prompt template that tells the agent to load tool-builder skill | `seed/commands/create-tool-calling.md` |
| 9 | **`/test-tool` slash command** — `[name]` argument → agent calls test API, reports result | `seed/commands/test-tool.md` |
| 10 | Wire skill + commands into `EvoFlux init` seed install | `app/cli/seed.py` |
| 11 | Frontend hooks `useCustomTools.ts` | `web/src/hooks/` |
| 12 | Variables UI `CustomToolVariables.tsx` — empty-value warning badge | `web/src/components/settings/` |
| 13 | Tools list `CustomToolsList.tsx` — status badge: Draft / Ready | same |
| 14 | Tool editor + test runner `CustomToolEditor.tsx` | same |
| 15 | Wire Settings sidebar to show Custom Tools section | `web/src/components/settings/SettingsSidebar.tsx` |

Steps 1–10 (backend + skill + commands) are fully usable through conversation
before the UI (steps 11–15) is built.
Each step can be PR'd independently.

---

## Open questions / follow-ups

- **Secret storage**: v1 uses plaintext SQLite. v2 should encrypt variable
  values at rest using the OS keychain (`keyring`) or a
  `cryptography`-derived AES key stored in the config dir.
- **Import / export**: zip-based export of a custom tool (definition +
  non-secret variables) so users can share them.
- **Tool marketplace**: community-contributed tool templates hosted in the
  EvoFlux repo (like seed agents).
- **Streaming output** in test runner: use SSE `/api/custom-tools/{id}/test/stream`
  so large outputs appear progressively instead of waiting for the full run.
- **Per-agent opt-out**: a way to exclude specific custom tools from a
  particular agent config (e.g. `exclude_tools: [my_tool]` in frontmatter).
