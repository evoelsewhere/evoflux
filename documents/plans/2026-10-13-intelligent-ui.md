# Intelligent UI (A/B/C/D) — Build-Ready Plan

**Date:** 2026-10-13
**Task ID:** 06acdaff-4c5c-7085-8000-86d2886f470c
**Status:** Approved scope, contracts frozen for implementation
**Audience:** A coder with zero prior context implementing either stream.

Every `file:line` anchor below was re-verified directly in the repository on
2026-10-13 (verification log in §13). Repository-relative links; paths are
repo-root-relative for `D:\evoelsewhere\evoflux`.

---

## 1. Scope and stream split

The user approved four features (research summary: ChatGPT-style "intelligent
UI" — structured, interactive responses instead of raw prose):

| ID | Feature | Stream |
|---|---|---|
| **A** | **Response-style setting** ("Simple" / "Visual"): a settings card cloned from the existing follow-up settings slice, plus a `@dynamic_prompt` hook that injects the chosen style into the agent's system prompt. | 1 |
| **D** | **```` ```chart ```` / ```` ```mermaid ```` fenced blocks** in the shared markdown pipeline, rendered with Recharts v3 + Mermaid v11, both lazy-loaded. | 1 |
| **B** | **Native `ui_block` tool**: a first-party tool emitting a new `ui_block` SSE event, rendered by a shadcn-native component catalog; arbitrary HTML keeps using the existing `show_widget` iframe escape hatch. | 2 |
| **C** | **Persistence of `ui_block` via tool-args reconstruction** — no Alembic, no schema change; blocks rebuild from stored tool-call arguments (the exact mechanism `show_widget` already uses). | 2 |

Streams can be built in parallel worktrees. The shared-file ownership map in
§8 is binding: neither stream may edit a file owned by the other; report to
the lead instead. Merge happens in task `task_8`.

**Why two streams split this way:** A and D are prompt + rendering-layer
changes with zero overlap in the SSE/tool stack; B and C form one vertical
slice (tool → event → render → persist/replay) that shares many files.

---

## 2. Verified anchor index (ground truth)

### 2.1 Backend — settings/prompt (feature A)

| Anchor | What it is |
|---|---|
| `app/core/runtime_settings.py:61` | `class FollowUpSettings(BaseModel)` — the slice to clone |
| `app/core/runtime_settings.py:75-77` | `model_config = ConfigDict(extra="ignore")`; `delivery: Literal["steer","queue"] = "queue"` |
| `app/core/runtime_settings.py:316` | `class RuntimeSettings(BaseModel)`; `model_config = ConfigDict(extra="ignore")` at :317 |
| `app/core/runtime_settings.py:340` | `follow_up: FollowUpSettings = Field(default_factory=FollowUpSettings)` — field to clone |
| `app/core/runtime_settings.py:343` | `follow_up_delivery_default()` — accessor precedent |
| `app/api/schemas/settings.py:19-24` | `class FollowUpSettingsBody(BaseModel)`; `extra="forbid"` at :22; `delivery: Literal[...] = "queue"` at :24 |
| `app/api/routes/settings.py:709-723` | `GET/PUT /settings/follow-up` handlers (422 on `ValueError`, `load_runtime_settings`/`save_runtime_settings`) |
| `app/agent/hooks/dynamic_prompt.py:92-95` | `PromptRequest` fields: `base_prompt: str`, `state: AgentState`, `ctx: RunContext` |
| `app/agent/hooks/dynamic_prompt.py:129-150` | `def dynamic_prompt(...)` decorator; returns `_DynamicPromptHook(fn)` at :150 |
| `app/agent/hooks/dynamic_prompt.py:158-179` | `@dynamic_prompt def inject_current_date` — the pattern to clone; body returns `f"{request.base_prompt}\n\nCurrent date (UTC): ..."` at :179 |
| `app/agent/hooks/__init__.py:2,32` | exports of `dynamic_prompt`, `inject_current_date` — add the new hook here |
| `app/agent/mode/team/member.py:1395-1400` | `HookPipeline()`; `pipeline.add(HookStage.BASE_CONTEXT, "clock", inject_current_date)` at :1396 — registration precedent |

### 2.2 Backend — tool/SSE stack (features B+C)

| Anchor | What it is |
|---|---|
| `app/agent/tools/registry.py:479-516` | `@tool` decorator (overloads + `def tool(...)`; params include `name`, `description`, `concurrency_safe`, `tiers`) |
| `app/agent/tools/builtin/visualize/show_widget.py:15-19` | `@tool(name="show_widget", tiers=("work",), description=..., concurrency_safe=False)` |
| `app/agent/tools/builtin/visualize/show_widget.py:55-71` | typed params with `Annotated[..., Field(description=...)]`; `_injected: dict[str, Any] \| None = None` at :71 |
| `app/agent/tools/builtin/visualize/show_widget.py:94-108` | read-me precondition (:94-98); `_injected` extraction of `agent`/`tool_call_id`/`session_id` (:102-108) |
| `app/agent/tools/builtin/visualize/show_widget.py:111-137` | emission block: imports (:111-114), `WidgetDeltaEvent(...)` (:126-132), `await stream_store.push_event(session_id, StreamEnvelope.from_event(event))` (:133), throttle `asyncio.sleep(0.05)` (:137) |
| `app/agent/tools/builtin/visualize/show_widget.py:146-154` | success return dict shape |
| `app/agent/tools/builtin/visualize/__init__.py:11-14` | tool package exports (`visualize_read_me`, `show_widget`) |
| `app/agent/loader.py:373` | `from app.agent.tools.builtin.visualize import visualize_read_me, show_widget` |
| `app/agent/loader.py:429-430` | registry dict entries `"visualize_read_me": ..., "show_widget": ...` |
| `app/agent/schemas/events.py:363-376` | `class WidgetDeltaEvent(BaseModel)` — model to clone (`type: Literal["widget_delta"]` at :371) |
| `app/services/stream_envelope.py:51` | `WidgetDeltaEvent` import from `app.agent.schemas.events` |
| `app/services/stream_envelope.py:58-86` | `AnyStreamEvent = Union[...]` (member `WidgetDeltaEvent` at :85) |
| `app/services/stream_envelope.py:104` | `StreamEnvelope.from_event(cls, evt: AnyStreamEvent)` |
| `app/services/memory_stream_store.py:41-53` | `_NON_REPLAYABLE_EVENT_TYPES` — do **not** add `ui_block` here |
| `app/services/memory_stream_store.py:59-70` | `_AGENT_CONTENT_EVENT_TYPES` frozenset; `"widget_delta"` at :67 — add `"ui_block"` here |
| `app/services/memory_stream_store.py:577` | usage: `entry.event in _AGENT_CONTENT_EVENT_TYPES` (per-agent content classification/pruning) |
| `app/api/routes/team/webbridge.py:1924-1958` | `_BROWSER_PANEL_STREAM_EVENT_TYPES = frozenset({...})`; `"widget_delta"` at :1933 |
| `app/api/routes/team/webbridge.py:2065-2071` | projection branch `elif event_type == "widget_delta":` (copies `id`, `agent`, `html`, `title`, `is_final`, metadata) — clone for `ui_block` |
| `app/api/routes/team/chat.py:746` | follow-up default consumed at send time (precedent for settings → runtime behavior) |

### 2.3 Frontend

| Anchor | What it is |
|---|---|
| `web/src/api/client/settings.ts:214-217` | `export type FollowUpSettings = {...}` |
| `web/src/api/client/settings.ts:218-232` | `getFollowUpSettings()` / `updateFollowUpSettings()` fetch calls to `/settings/follow-up` |
| `web/src/queries/keys.ts:177` | `followUp: () => ['settings', 'follow-up'] as const` |
| `web/src/queries/useFollowUpSettingsQuery.ts:10-26` | query hook (:10-16) + mutation with `setQueryData` (:18-26) |
| `web/src/queries/index.ts:144-147` | re-export block for the follow-up hooks |
| `web/src/routes/settings.agents.tsx:217` | `<FollowUpBehaviorCard />` mount point in the page |
| `web/src/routes/settings.agents.tsx:379-409` | `FollowUpBehaviorCard` implementation (query :380, mutation :381, default :382, radio group :384-402, helper copy :404-409) |
| `web/src/utils/markdown.tsx:640-654` | `const components = useMemo(...)`; `pre:` renderer :642; language parsed from `language-*` class :648; `<CodeBlock language={language} rawText={codeText}>` :650 |
| `web/src/utils/markdown.tsx:456-465` | streaming splitter docs — "Fenced code/math … stay together"; `splitStreamingMarkdown` :465 |
| `web/src/utils/markdown.tsx:721-728` | `<MarkdownSegment ... components={components} ... streamingTail={...}/>` |
| `web/src/api/types.ts:838-868` | `interface ContentBlock`; union `type` :840 (`... | 'widget'`); `extra?: Record<string, unknown> \| null` :863 |
| `web/src/stores/useTeamStore/sse-reducer.ts:266-324` | `case 'widget_delta':` — agent/toolCallId/html/isFinal parse :267-270, upsert logic below |
| `web/src/stores/useTeamStore/sse-reducer.ts:326-360` | tool_end fallback: "construct the widget block from the tool-call arguments" comment :329-331; `if (toolName === 'show_widget' && toolCallId)` :332; `hasWidget` dedupe :334-336 |
| `web/src/utils/messages.ts:222-238` | history reconstruction: comment :222; `if (name === 'show_widget' && typeof parsedArgs?.widget_code === 'string')` :225; block built with `type: 'widget'` :228, `widgetHtml: parsedArgs.widget_code` :231, pushed :236, `continue` :238 |
| `web/src/components/BlockRenderer.tsx:449-461` | `case 'widget': {` :449; `<WidgetRenderer html=... />` :455-460 |
| `web/src/components/WidgetRenderer.tsx:49-61` | iframe CSP builder (escape-hatch reference) |
| `web/src/components/WidgetRenderer.tsx:197-218` | interactivity round-trip precedent: `useTeamStore((s) => s.sendMessage)` :197, prompt dispatch :202-213, deps `[onSendPrompt, sessionId, sendMessage]` :218 |
| `web/src/api/stream-scheduler.ts:8-16` | `VISUAL_DELTA_EVENTS` list (coalesced stream types; `widget_delta` html merge branch :38-47) |
| `web/src/api/sse.ts:78` | `dispatchEvent()` in the SSE reader — events fan out to the reducer by `type` string (no frontend allowlist) |
| `web/package.json:14-16` | `"test": "bun run test:unit"`, `"test:unit": "vitest run"` |
| `web/package.json:62,98` | `react-markdown`, `vitest` deps; **no** `recharts`/`mermaid` present (verified by grep of `web/package.json` + `web/src`) |
| `web/src/help/locales/en.ts:65` | `id: 'settings'` help category; `:2229` `openAction: { type: 'settings', path: 'agents' }`; `ja.ts`/`vi.ts` exist as sibling locales |

### 2.4 Tests, docs

| Anchor | What it is |
|---|---|
| `tests/api/test_settings_routes.py` | settings-route tests; `isolated_runtime_settings` fixture used e.g. at :1617, :2253, :2269 (round-trip + "unrelated section survives" patterns) |
| `tests/agent/tools/builtin/visualize/test_tools.py` | `TestShowWidget` class (:85+); `test_html_content_preserved` :98 |
| `tests/agent/hooks/test_dynamic_prompt_hook.py` | dynamic-prompt hook tests |
| `tests/services/test_memory_stream_store.py` | stream-store tests |
| `tests/api/test_webbridge.py` | webbridge projection tests |
| `tests/agent/test_loader.py` | tool registry tests |
| `tests/api/routes/test_team.py:520` | `monkeypatch.setattr(chat_routes, "follow_up_delivery_default", ...)` — settings-in-runtime test precedent |
| `web/src/__tests__/utils/markdown.test.tsx` | markdown renderer tests |
| `web/src/__tests__/stores/useTeamStore.followUp.test.ts` | store test style to clone |
| `web/src/__tests__/api/stream-scheduler.test.ts` | api-layer test style |
| `web/src/__tests__/components/ToolCallGroup.test.tsx` (colocated sibling: `web/src/components/ToolCallGroup.test.ts`) | component test styles |
| `documents/features/README.md:7-9` | feature catalogue table (`| Feature | Page |`) |
| `documents/features/tools-skills-mcp-and-plugins.md` | tool feature page (S2) |
| `CHANGELOG.md` | root changelog; `[Unreleased]` groups per root `AGENTS.md` |
| `documents/reference/http-api.md`, `documents/reference/configuration.md` | verified **not** to list `/settings/follow-up` or `follow_up` — precedent: settings endpoints/keys are not documented there, so no obligation for `response-style` either |

---

## 3. Feature A — Response style (Stream 1, `task_6`)

### 3.1 Contract

**Backend model** — new class in `app/core/runtime_settings.py` directly after
`FollowUpSettings` (:77):

```python
class ResponseStyleSettings(BaseModel):
    """Default presentation style for agent answers."""
    model_config = ConfigDict(extra="ignore")
    style: Literal["simple", "visual"] = "visual"
```

Field on `RuntimeSettings` directly after :340:

```python
response_style: ResponseStyleSettings = Field(default_factory=ResponseStyleSettings)
```

Accessor after `follow_up_delivery_default()` (:343), same shape:

```python
def response_style_default() -> str:
    """Configured response style (``simple`` | ``visual``)."""
```

`extra="ignore"` on `RuntimeSettings` (:317) means old `settings.yaml` files
without the key load fine, and files written by a newer build load in an
older one — **no migration, no Alembic** (requirement C-style persistence).

**Decision — default `visual`:** new features should be discoverable;
`simple` is the opt-out that reproduces today's plain behavior. (Trade-off
accepted: prompt output changes for users who never open Settings.)

**API schema** — new model in `app/api/schemas/settings.py` after :24:

```python
class ResponseStyleSettingsBody(BaseModel):
    """Default answer presentation style (Settings -> Agents)."""
    model_config = ConfigDict(extra="forbid")
    style: Literal["simple", "visual"] = "visual"
```

**Endpoints** — new handlers in `app/api/routes/settings.py` directly after
:723, cloning the follow-up pair line-for-line:

```python
@router.get("/response-style")
async def get_response_style_settings() -> ResponseStyleSettingsBody: ...

@router.put("/response-style")
async def save_response_style_settings(body: ResponseStyleSettingsBody) -> ResponseStyleSettingsBody: ...
```

GET returns `ResponseStyleSettingsBody(style=cfg.response_style.style)`; PUT
loads with `ValueError → HTTPException(422)`, assigns, `save_runtime_settings`,
echoes back (same as `settings.py:717-723`).

**Prompt hook** — new module `app/agent/hooks/response_style.py`:

```python
from __future__ import annotations

from app.agent.hooks.dynamic_prompt import PromptRequest, dynamic_prompt
from app.core.runtime_settings import load_runtime_settings


@dynamic_prompt
def inject_response_style(request: PromptRequest) -> str:
    """Append the configured response style to the system prompt."""
    try:
        style = load_runtime_settings().response_style.style
    except ValueError:
        style = "visual"
    if style == "simple":
        line = (
            "Response style: simple — answer in plain prose with minimal "
            "structure. Do not emit ```chart or ```mermaid fences and avoid "
            "the ui_block tool; plain text and lists are preferred."
        )
    else:
        line = (
            "Response style: visual — prefer scannable, structured answers: "
            "use tables, ```chart (JSON spec) and ```mermaid fences, and the "
            "ui_block tool when the ui_block tool is available in your tool "
            "registry."
        )
    return f"{request.base_prompt}\n\n{line}"
```

Exact wording is copy-tunable; the **contract** is: reads
`response_style.style`, returns the full new `base_prompt`, degrades to
`visual` on corrupt settings. Shape matches `inject_current_date`
(`dynamic_prompt.py:158-179`).

- Export it from `app/agent/hooks/__init__.py` (add to the import at :2 and
  `__all__` near :32).
- Register in `app/agent/mode/team/member.py` immediately after :1396:
  `pipeline.add(HookStage.BASE_CONTEXT, "response-style", inject_response_style)`
  (next to `"clock"`). Base context runs before wiki/team context, so later
  hooks compose on top unchanged.

**Frontend contract** (clone follow-up slice):

```ts
// web/src/api/client/settings.ts — after :232
export type ResponseStyleSettings = { style: 'simple' | 'visual' }
export async function getResponseStyleSettings(): Promise<ResponseStyleSettings>
export async function updateResponseStyleSettings(body: ResponseStyleSettings): Promise<ResponseStyleSettings>
//   GET/PUT `${apiBaseUrl()}/settings/response-style`
```

- `web/src/queries/keys.ts` after :177: `responseStyle: () => ['settings', 'response-style'] as const`.
- New `web/src/queries/useResponseStyleSettingsQuery.ts` cloning
  `useFollowUpSettingsQuery.ts:10-26` (staleTime 30_000, `setQueryData` on success).
- Re-export from `web/src/queries/index.ts` after :147.
- New `ResponseStyleCard` in `web/src/routes/settings.agents.tsx`, cloning
  `FollowUpBehaviorCard` (:379-409), mounted after :217. Copy: title
  **Response style**, two-option segmented radio **Simple** / **Visual**
  (same radio-group markup as :384-402), helper text explaining that Visual
  enables charts, diagrams, and structured UI blocks.

### 3.2 Step order (A)

1. `app/core/runtime_settings.py` — model + field + accessor.
2. `app/api/schemas/settings.py` — body model.
3. `app/api/routes/settings.py` — GET/PUT.
4. `tests/api/test_settings_routes.py` — tests (§9.1).
5. `app/agent/hooks/response_style.py` + `__init__.py` export + `member.py:1396` registration.
6. `tests/agent/hooks/test_dynamic_prompt_hook.py` additions.
7. Frontend client/query/keys/exports.
8. `ResponseStyleCard` + mount.
9. Frontend tests, help entries (§10), CHANGELOG bullet.

Steps 1–6 are backend-only and shippable before 7–9.

---

## 4. Feature D — ```` ```chart ```` / ```` ```mermaid ```` fences (Stream 1)

### 4.1 Contract

**Dependencies** — in `web/`: `bun add recharts@^3 mermaid@^11`
(Recharts v3, Mermaid v11 per approved scope; neither exists in
`web/package.json` today — verified).

**ChartSpec** — new `web/src/components/markdown/chart-spec.ts`:

```ts
export type ChartSpec = {
  type: 'line' | 'bar' | 'area' | 'pie'
  title?: string
  xKey: string
  series: Array<{ key: string; label?: string; color?: string }>
  data: Array<Record<string, string | number>>
  yLabel?: string
  stacked?: boolean            // bar only
  unit?: string
}
export function parseChartSpec(text: string): ChartSpec | null   // JSON.parse + structural validation
```

Example fence (documented in the feature page + help):

````markdown
```chart
{
  "type": "line",
  "xKey": "month",
  "series": [{ "key": "revenue", "label": "Revenue" }],
  "data": [{ "month": "Jan", "revenue": 120 }, { "month": "Feb", "revenue": 180 }]
}
```
````

**Fence dispatch** — modify only the `pre` renderer inside
`web/src/utils/markdown.tsx:642-654`:

```tsx
pre: (props) => {
  const codeEl = ...
  const codeText = extractText(codeEl?.props?.children)
  const language = codeEl?.props?.className?.match(/(?:^|\s)language-([^\s]+)/)?.[1]  // :648 unchanged
  const fallback = <CodeBlock language={language} rawText={codeText}>{...}</CodeBlock>
  if (language === 'chart')  return <ChartFence rawText={codeText} streaming={streaming} fallback={fallback} />
  if (language === 'mermaid') return <MermaidFence rawText={codeText} streaming={streaming} fallback={fallback} />
  return fallback
}
```

`streaming` comes from the component that owns the `useMemo` at :640 (add it
to the `useMemo` deps array). This is safe because
`splitStreamingMarkdown` (:465, docs :456-462) keeps fences together in the
live tail.

**New files (all under Stream 1):**

| File | Responsibility |
|---|---|
| `web/src/components/markdown/chart-spec.ts` | `ChartSpec` + `parseChartSpec` (above) |
| `web/src/components/markdown/ChartFence.tsx` | `React.lazy` wrapper: `parseChartSpec` → invalid & `streaming` ⇒ skeleton placeholder; invalid & complete ⇒ `fallback` + one-line muted "Invalid chart spec"; valid ⇒ lazy `ChartBlock` |
| `web/src/components/markdown/ChartBlock.tsx` | the Recharts renderer (`import { ResponsiveContainer, LineChart, ... } from 'recharts'` lives only inside this module, so it becomes one lazy chunk) |
| `web/src/components/markdown/MermaidFence.tsx` | `React.lazy` wrapper: `const mermaid = (await import('mermaid')).default`; `mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme })` once; `await mermaid.render(id, code)` → SVG injected into a `div`; error ⇒ `fallback` + muted error line |

Both wrappers are consumed with `React.lazy(() => import(...))` +
`<Suspense fallback={skeleton}>` from `markdown.tsx` — Recharts and Mermaid
bundle size lands in separate chunks, never in the initial bundle.

**Rules:**
- Never throw out of a fence renderer — a broken spec must degrade to today's
  `CodeBlock` behavior (identical to unknown languages).
- `securityLevel: 'strict'` is mandatory for Mermaid (no raw HTML/scripts in
  diagrams).
- Dark mode: use the app's existing theme tokens for chart colors; Mermaid
  theme picked from `prefers-color-scheme` / app theme at initialize time.

### 4.2 Step order (D)

1. Add deps (`web/package.json` + lockfile).
2. `chart-spec.ts` + unit tests.
3. `ChartBlock.tsx`, `ChartFence.tsx`, `MermaidFence.tsx`.
4. Wire `pre` dispatcher in `markdown.tsx` (only change to an existing file).
5. Extend `web/src/__tests__/utils/markdown.test.tsx`.
6. Help + feature doc + CHANGELOG (§10).

---

## 5. Feature B — native `ui_block` tool (Stream 2, `task_7`)

### 5.1 Pydantic event models — `app/agent/schemas/events.py`

Append after `WidgetDeltaEvent` (:376). Node models use Pydantic with
`extra="ignore"` (external payload rule from `app/AGENTS.md`); all limits are
enforced server-side so one SSE frame stays small.

```python
class UiStatCard(BaseModel):
    label: str = Field(max_length=80)
    value: str | int | float
    delta: str | None = Field(default=None, max_length=40)
    delta_tone: Literal["up", "down", "neutral"] = "neutral"
    hint: str | None = Field(default=None, max_length=160)

class UiStatCardsBlock(BaseModel):
    type: Literal["stat_cards"] = "stat_cards"
    cards: list[UiStatCard] = Field(min_length=1, max_length=6)

class UiChartBlock(BaseModel):
    type: Literal["chart"] = "chart"
    spec: dict[str, Any]          # ChartSpec (§4.1); frontend validates — see §8.3 stub rule

class UiStep(BaseModel):
    title: str = Field(max_length=160)
    status: Literal["done", "active", "pending", "error"] = "pending"
    detail: str | None = Field(default=None, max_length=400)

class UiStepsBlock(BaseModel):
    type: Literal["steps"] = "steps"
    steps: list[UiStep] = Field(min_length=1, max_length=12)

class UiTableBlock(BaseModel):
    type: Literal["table"] = "table"
    columns: list[dict[str, str]] = Field(min_length=1, max_length=12)   # {"key","label","align?"}
    rows: list[dict[str, Any]] = Field(max_length=200)

class UiKeyValueBlock(BaseModel):
    type: Literal["key_value"] = "key_value"
    pairs: list[dict[str, str]] = Field(min_length=1, max_length=20)     # {"label","value"}

class UiCalloutBlock(BaseModel):
    type: Literal["callout"] = "callout"
    tone: Literal["info", "success", "warning", "error"] = "info"
    title: str | None = Field(default=None, max_length=120)
    body: str = Field(max_length=2000)

class UiButton(BaseModel):
    label: str = Field(max_length=80)
    prompt: str = Field(max_length=500)        # sent as a chat message when clicked
    style: Literal["primary", "secondary"] = "secondary"

class UiButtonsBlock(BaseModel):
    type: Literal["buttons"] = "buttons"
    buttons: list[UiButton] = Field(min_length=1, max_length=5)

class UiFormField(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    label: str = Field(max_length=80)
    kind: Literal["text", "textarea", "select", "checkbox"] = "text"
    options: list[str] = Field(default_factory=list, max_length=30)
    placeholder: str | None = Field(default=None, max_length=120)
    default: str | None = None

class UiFormBlock(BaseModel):
    type: Literal["form"] = "form"
    title: str | None = Field(default=None, max_length=120)
    fields: list[UiFormField] = Field(min_length=1, max_length=8)
    submit_label: str = Field(default="Send", max_length=40)

class UiProgressBlock(BaseModel):
    type: Literal["progress"] = "progress"
    label: str = Field(max_length=120)
    value: int = Field(ge=0)
    max: int = Field(gt=0)
    unit: str | None = Field(default=None, max_length=20)

UiBlockNode = Annotated[
    Union[
        UiStatCardsBlock, UiChartBlock, UiStepsBlock, UiTableBlock,
        UiKeyValueBlock, UiCalloutBlock, UiButtonsBlock, UiFormBlock,
        UiProgressBlock,
    ],
    Field(discriminator="type"),
]

class UiBlockEvent(BaseModel):
    """Native structured UI blocks emitted by the ``ui_block`` tool."""
    type: Literal["ui_block"] = "ui_block"
    agent: str
    tool_call_id: str
    blocks: list[UiBlockNode] = Field(min_length=1, max_length=6)
    is_final: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)   # {"title": ...}
```

Unknown `type` values fail Pydantic validation → the tool returns a friendly
error (§5.2) instead of emitting a broken event. The frontend additionally
renders an "unsupported block" card for forward-compat (§5.5).

### 5.2 Tool signature and behavior — `app/agent/tools/builtin/visualize/ui_block.py` (new)

```python
@tool(
    name="ui_block",
    tiers=("work", "coding"),          # both modes; see preview.py:1084 for the multi-tier form
    description=(
        "Render native structured UI (charts, stat cards, steps, tables, "
        "callouts, buttons, forms, progress) inline in the conversation. "
        "Prefer this over raw prose for structured data. For arbitrary "
        "interactive HTML, use show_widget instead."
    ),
    concurrency_safe=False,            # emits stream events — same as show_widget
)
async def ui_block(
    blocks: Annotated[
        list[dict[str, Any]] | str,
        Field(description="1-6 UI block objects, or a JSON-encoded string of that array. "
                          "Each object needs a 'type' (stat_cards, chart, steps, table, "
                          "key_value, callout, buttons, form, progress)."),
    ],
    title: Annotated[str, Field(description="Short snake_case title for the block group", max_length=80)] = "",
    _injected: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

Behavior (clone `show_widget.py:94-154`):

1. **Read-me gate:** `ui_block` has no companion read-me tool; instead the
   description carries the usage rule. (Do not gate on `visualize_read_me` —
   it documents HTML widgets, not this catalog.)
2. **Normalize:** if `blocks` is a `str`, `json.loads` it; on failure or
   non-list result return
   `{"success": False, "error": "blocks must be a JSON array of objects"}`.
   Do not raise — tool failures are results, not exceptions.
3. **Validate:** `UiBlockEvent`-style validation of each node (or construct
   the event directly). On validation error return
   `{"success": False, "error": str(exc), "valid_types": [...]}`.
4. **Inject identity** from `_injected` exactly like `show_widget.py:102-108`
   (`agent`, `tool_call_id`, `session_id`).
5. **Emit ONE event** (no chunk loop, no sleep):

   ```python
   from app.services import memory_stream_store as stream_store
   from app.services.stream_envelope import StreamEnvelope
   from app.agent.schemas.events import UiBlockEvent

   event = UiBlockEvent(
       agent=agent, tool_call_id=tool_call_id, blocks=validated,
       is_final=True, metadata={"title": title} if title else {},
   )
   await stream_store.push_event(session_id, StreamEnvelope.from_event(event))
   ```

   (same call shape as `show_widget.py:133`); wrap in `try/except` with a
   loguru warning like `show_widget.py:139-144` so a push failure never
   fails the turn — the tool_end reconstruction path (§6) is the fallback.
6. **Return** `{"success": True, "block_count": n, "types": [...], "message": "..."}`.
   Do **not** echo `blocks` in the result — history persistence uses the
   tool **arguments** (§6), and echoing doubles the payload.

**Registration** (both required or the tool is invisible):

- `app/agent/tools/builtin/visualize/__init__.py:11-14` — import + `__all__`.
- `app/agent/loader.py:373` — extend the visualize import.
- `app/agent/loader.py:429-430` — `"ui_block": ui_block,` registry entry.

**JSON schema** exposed to the model is derived by the `@tool` decorator from
the `Annotated[..., Field(...)]` metadata (same mechanism as
`show_widget.py:55-71`); no hand-written schema file exists or should be
added.

### 5.3 SSE registration checklist — four backend lists (+ projection)

`ui_block` must be registered in **all four** of these, or it silently
disappears on replay/refresh/browser-panel. Widget parity is the test: every
place `"widget_delta"` appears, decide `ui_block` explicitly.

- [ ] **List 1 — event model**: add the §5.1 models to
      `app/agent/schemas/events.py` after :376.
- [ ] **List 2 — envelope union**: import `UiBlockEvent` alongside
      `WidgetDeltaEvent` (`app/services/stream_envelope.py:51`) and add it to
      `AnyStreamEvent = Union[...]` (:58-86).
- [ ] **List 3 — stream-store classification**: add `"ui_block"` to
      `_AGENT_CONTENT_EVENT_TYPES` (`app/services/memory_stream_store.py:59-70`).
      Do **not** add it to `_NON_REPLAYABLE_EVENT_TYPES` (:41-53) — it must
      replay on reconnect like `widget_delta`.
- [ ] **List 4 — browser-panel allowlist**: add `"ui_block"` to
      `_BROWSER_PANEL_STREAM_EVENT_TYPES` (`app/api/routes/team/webbridge.py:1924-1958`)
      **and** a projection branch after :2071:
      `elif event_type == "ui_block":` copying `agent`, `tool_call_id`/`id`,
      `is_final`, and `blocks` (bounds-checked like the widget branch).
      If the projection branch is skipped, the allowlist entry alone keeps
      the panel from dropping the event, but the projected payload will be
      minimal — copy the fields.

Frontend registration (not one of the four backend lists, but required):

- [ ] `web/src/stores/useTeamStore/sse-reducer.ts` — new `case 'ui_block':`
      after the `widget_delta` case (:266-324): parse `agent`,
      `tool_call_id`, `blocks`; upsert a `type: 'ui_block'` block on the
      message (dedupe by `toolCallId`, mirroring :334-336).
- [ ] `web/src/api/types.ts:840` — add `'ui_block'` to the `type` union; add
      `uiBlocks?: UiBlockNode[]` to `ContentBlock` (alongside the widget
      fields :854-857).
- [ ] `web/src/api/stream-scheduler.ts:8-16` — **no change**: `ui_block` is a
      single complete frame, not a token delta; `VISUAL_DELTA_EVENTS`
      coalescing does not apply. (Record this as a deliberate skip in review.)
- [ ] `web/src/api/sse.ts` — no change (no allowlist; dispatches by `type`).

### 5.4 Interactivity round-trip payload

Reuse the widget precedent — no new endpoint in v1. Define in
`web/src/components/ui/ui-block-types.ts`:

```ts
export type UiInteraction =
  | { kind: 'send_prompt'; prompt: string }                  // buttons, form submit
  | { kind: 'toggle'; id: string }                           // local expand/collapse only
```

- Every interactive node accepts `onInteract?: (i: UiInteraction) => void`.
- `UiBlockRenderer` wires `send_prompt` to
  `useTeamStore.getState().sendMessage(prompt)` — the exact mechanism
  `WidgetRenderer.tsx:197-218` uses (`sendMessage` from the team store).
- **Buttons:** click → `send_prompt` with `button.prompt` verbatim.
- **Forms:** submit → compose
  `${title ?? 'Form response'}:\n- ${label}: ${value}` for each filled field
  → one `send_prompt`. Agent therefore sees the answers as a normal user
  message.
- `toggle` never leaves the client.

**Trade-off (accepted):** the agent does not receive a structured tool
result; a future `ui_interaction` continuation can replace this without
touching storage. Document as follow-up in the feature page.

### 5.5 Frontend component catalog (Stream 2 files)

All new, all under `web/src/components/ui/`:

| File | Node type(s) |
|---|---|
| `ui-block-types.ts` | TS mirror of §5.1 (`UiBlockNode` discriminated union) + `UiInteraction` |
| `UiBlockRenderer.tsx` | switch over `type`; unknown type ⇒ neutral "Unsupported block" card (never throw) |
| `UiStatCards.tsx` | `stat_cards` — responsive grid of shadcn `Card`s, delta colored via existing tone tokens |
| `UiChart.tsx` | `chart` — **stub rule: no recharts import** (see §8.3) |
| `UiSteps.tsx` | `steps` — vertical stepper (existing icons) |
| `UiTable.tsx` | `table` — shadcn-style table, `maxRows` slice |
| `UiKeyValue.tsx` | `key_value` — definition-list rows |
| `UiCallout.tsx` | `callout` — tone-mapped callout (info/success/warning/error) |
| `UiButtons.tsx` | `buttons` — button row → `onInteract` |
| `UiForm.tsx` | `form` — fields + submit → composed `send_prompt` |
| `UiProgress.tsx` | `progress` — progress bar with label/value |

Styling: use the repo's existing shadcn/Tailwind v4 primitives and `--z-*` /
`--color-*` tokens; no new CSS files, no raw z-index numbers (per
`web/src/AGENTS.md`).

**Wiring into the message flow:**

1. `web/src/components/BlockRenderer.tsx` — new `case 'ui_block': {` after
   :449's widget case, rendering `<UiBlockRenderer blocks={block.uiBlocks ?? []} ... />`
   (widget case shows the exact prop-passing pattern :455-460).
2. `web/src/stores/useTeamStore/sse-reducer.ts` — live event case (§5.3).
3. Tool-call card: `ui_block` appears in `ToolCallGroup` automatically as a
   normal tool call; no change expected there (verify — `ToolCallGroup.tsx`
   renders by `toolName` generically).

---

## 6. Feature C — persistence via tool-args reconstruction (Stream 2)

**No Alembic, no SQLModel change, no new API.** The server already persists
`tool_call` arguments in message history; the client already reconstructs
widget blocks from those arguments. `ui_block` copies both paths:

1. **History load** — `web/src/utils/messages.ts`: after the widget branch
   (:225-238), add:

   ```ts
   if (name === 'ui_block' && Array.isArray(parsedArgs?.blocks)) {
     // build a type: 'ui_block' block: id, uiBlocks: parsedArgs.blocks,
     // title: parsedArgs.title, toolCallId: tool.id, isStreaming: false
     // push + pendingToolBlocks.set(tool.id, block) + continue  (mirror :236-238)
   }
   ```

2. **Live-session safety net** — `web/src/stores/useTeamStore/sse-reducer.ts`
   at `tool_end` (:326-360 pattern): if `toolName === 'ui_block'` and no
   block with that `toolCallId` exists (the `hasWidget`-style dedupe at
   :334-336), construct it from the tool-call arguments. This covers a lost
   `ui_block` SSE event (backend push failure — `show_widget.py:139-144`
   logs exactly this class of failure).

3. **Replay/reconnect** — automatic once List 3 (§5.3) is registered:
   `ui_block` is journaled (not in `_NON_REPLAYABLE_EVENT_TYPES`) and
   re-delivered to resubscribed clients, same as `widget_delta`.

Dedupe invariant: a block is keyed by `toolCallId`; whichever of (event,
tool_end, history) arrives first wins, later ones no-op.

---

## 7. Ordering, dependencies

| Step | Stream | Depends on | Verifiable at |
|---|---|---|---|
| A1 settings model+endpoints | 1 | — | pytest settings round-trip |
| A2 prompt hook + registration | 1 | A1 | pytest hook unit tests |
| A3 frontend slice | 1 | A1 | vitest + manual Settings page |
| D1 deps + chart-spec | 1 | — | vitest parse tests |
| D2 fences + markdown wiring | 1 | D1 | vitest markdown tests |
| B1 event models + 4 lists | 2 | — | pytest store/envelope/webbridge |
| B2 tool + registration | 2 | B1 | pytest tool tests |
| B3 reducer + types + renderer | 2 | B1 | vitest component/reducer tests |
| B4 BlockRenderer wiring | 2 | B3 | vitest + manual chat |
| C1 history + tool_end recon. | 2 | B3 | vitest messages/store tests |
| Merge | task_8 | task_6 + task_7 | full gates (§11) |

A and D within Stream 1 are independent (A1-A3 can proceed while D1-D2 runs).

---

## 8. Shared-file ownership map + parallel-start protocol

### 8.1 Ownership (binding)

| File / dir | Owner |
|---|---|
| `app/core/runtime_settings.py` | S1 |
| `app/api/schemas/settings.py` | S1 |
| `app/api/routes/settings.py` | S1 |
| `app/agent/hooks/response_style.py` (new) | S1 |
| `app/agent/hooks/__init__.py` | S1 |
| `app/agent/mode/team/member.py` | S1 |
| `web/src/api/client/settings.ts` | S1 |
| `web/src/queries/**` (keys, index, new hook file) | S1 |
| `web/src/routes/settings.agents.tsx` | S1 |
| `web/src/utils/markdown.tsx` | S1 |
| `web/src/components/markdown/**` (new) | S1 |
| `web/package.json` + lockfile | S1 |
| `web/src/help/locales/{en,ja,vi}.ts` | S1 (S2 does not touch help — see §10) |
| `documents/features/intelligent-ui.md` (new) | S1 creates, owns structure; S2's B/C section text is delivered in its handoff and inserted **only** at merge (`task_8`) |
| `documents/features/README.md` | S1 (adds the catalogue row) |
| `documents/features/tools-skills-mcp-and-plugins.md` | S2 |
| `app/agent/schemas/events.py` | S2 |
| `app/services/stream_envelope.py` | S2 |
| `app/services/memory_stream_store.py` | S2 |
| `app/api/routes/team/webbridge.py` | S2 |
| `app/agent/tools/builtin/visualize/**` (`ui_block.py`, `__init__.py`) | S2 |
| `app/agent/loader.py` | S2 |
| `web/src/api/types.ts` | S2 |
| `web/src/components/ui/**` (new) | S2 |
| `web/src/components/BlockRenderer.tsx` | S2 |
| `web/src/stores/useTeamStore/sse-reducer.ts` | S2 |
| `web/src/utils/messages.ts` | S2 |
| `web/src/__tests__/**` | each stream only for its own test files |
| `tests/api/test_settings_routes.py`, `tests/agent/hooks/**` | S1 |
| `tests/agent/tools/builtin/visualize/**`, `tests/services/test_memory_stream_store.py`, `tests/api/test_webbridge.py`, `tests/agent/test_loader.py` | S2 |
| **`CHANGELOG.md`** | **both** — the only shared-edit file; see 8.2 |

If a change seems to need a file you don't own: stop and report to the lead
rather than editing across the line.

### 8.2 Parallel-start protocol

1. Both streams start immediately on separate worktrees; no waiting.
2. Each stream adds its own bullet(s) under `## [Unreleased]` → `Added` in
   `CHANGELOG.md` as its very last step. A textual conflict at merge is
   expected; `task_8` resolves it by **keeping both** bullets (they describe
   different features). Do not reword the other stream's bullet.
3. Each stream runs only its own checks (§11); it must not "fix" failures
   caused by the other stream's absent files.
4. Neither stream creates, edits, or imports from files owned by the other
   (§8.1). No cherry-picking between worktrees.

### 8.3 Chart-block stub rule (critical)

Stream 2's `chart` node kind must **not** hard-depend on Stream 1's
`ChartBlock`:

- `web/src/components/ui/UiChart.tsx` (S2) takes `{ spec: unknown }`, casts
  structurally to its own local `UiChartSpec` type declared inside
  `ui-block-types.ts`, and renders a **dependency-free** visualization (a
  small inline SVG bar/line built from `spec.data`, or a neutral
  "chart preview" card). It must not import `recharts`, must not import
  `@/components/markdown/*`, and must not reference `ChartSpec` from S1.
- Stream 1's `chart-spec.ts` `parseChartSpec` remains the canonical validator
  for fences.
- **At merge (`task_8`):** re-point `UiChart.tsx`'s body to the shared
  renderer — `parseChartSpec` from `@/components/markdown/chart-spec` and the
  Recharts `ChartBlock` — keeping the `UiChartProps` interface unchanged, so
  the swap is a one-file edit. Until merge, both streams build, test, and
  demo independently.

---

## 9. Test plan

### 9.1 Stream 1 (A + D) — backend

`tests/api/test_settings_routes.py` (clone the `isolated_runtime_settings`
patterns at :1617 and :2269):

- `test_response_style_defaults_to_visual` — GET returns `{style: "visual"}` on a fresh settings file.
- `test_response_style_round_trip` — PUT `{"style":"simple"}` → 200, GET returns `simple`, persisted after reload.
- `test_response_style_rejects_invalid_value` — PUT `{"style":"detailed"}` → 422 (`extra="forbid"` / Literal).
- `test_unrelated_section_survives_response_style_put` — clone :2269.

`tests/agent/hooks/test_dynamic_prompt_hook.py`:

- `test_inject_response_style_simple_appends_line` / `_visual_appends_line` — monkeypatch settings (load from an isolated file, the `test_team.py:520` monkeypatch style is acceptable) and assert `request.base_prompt` prefix is preserved and the correct line is appended.
- `test_inject_response_style_corrupt_settings_falls_back_to_visual`.

`tests/agent/mode/team/` or hooks pipeline test: one assertion that the team
member pipeline registers a `BASE_CONTEXT` stage named `"response-style"` —
if building the full pipeline in-test is impractical, a focused grep-able
registration test (import `member`, inspect the pipeline construction helper)
is acceptable; do not skip registration verification entirely.

### 9.2 Stream 1 (D) — frontend (vitest: `bun run test:unit`)

Extend `web/src/__tests__/utils/markdown.test.tsx`:

- ```` ```chart ```` with valid spec → chart component rendered (assert test-id), not `CodeBlock`.
- invalid JSON → falls back to `CodeBlock` + no crash.
- ```` ```chart ```` while streaming with partial JSON → skeleton, no error UI.
- ```` ```mermaid ```` → lazy component mounts (mock `import('mermaid')` with a fake `render`), and on reject → `CodeBlock` fallback.
- unknown language fences → behavior unchanged (regression guard).

New `web/src/__tests__/api/settings-response-style.test.ts` — mocked
`fetch`, mirrors the client-test style of
`web/src/__tests__/api/stream-scheduler.test.ts`: GET/PUT paths, method,
payload mapping.

New `web/src/__tests__/components/ResponseStyleCard.test.tsx` — renders both
options, mutation fired with the chosen style (mock the query module, same
approach as existing component tests).

### 9.3 Stream 2 (B + C) — backend

`tests/agent/tools/builtin/visualize/test_tools.py` — new `TestUiBlock`:

- valid `blocks` list → `success True`, `block_count`; `memory_stream_store.push_event` awaited with an envelope whose `event == "ui_block"` (monkeypatch `push_event`, the `show_widget` tests show the pattern).
- `blocks` as JSON string → same.
- malformed JSON string → `success False`, error mentions JSON array; no exception.
- unknown `type` node → `success False` with `valid_types` listing the catalog.
- `> 6` blocks / over-limit row count → `success False`.
- push failure (monkeypatch `push_event` to raise) → tool still returns `success True` or logged-failure per §5.2 step 5 (assert turn does not raise).

`tests/services/test_memory_stream_store.py`:

- `"ui_block" in _AGENT_CONTENT_EVENT_TYPES` and `"ui_block" not in _NON_REPLAYABLE_EVENT_TYPES` (cheap membership guards for Lists 3 and the negative rule).
- replay test: push a `UiBlockEvent`, subscribe a late client, assert it is delivered (clone the existing `widget_delta` replay test if present).

`tests/api/test_webbridge.py`:

- `ui_block` is in the browser-panel allowlist and its projection copies `blocks`/`tool_call_id`/`is_final` (clone the widget projection test).

`tests/agent/test_loader.py`:

- registry contains `ui_block` (there should be an existing "all builtin tools registered" style assertion — extend it).

### 9.4 Stream 2 — frontend (vitest)

- New `web/src/__tests__/components/UiBlockRenderer.test.tsx` — one render
  assertion per node type; unknown type → unsupported card; buttons emit
  `send_prompt` (mock store `sendMessage`); form submit composes the
  expected message.
- New `web/src/__tests__/utils/messages-ui-block.test.ts` — history
  reconstruction: a message whose tool call is `ui_block` with
  `arguments.blocks` produces exactly one `type: 'ui_block'` block with
  `uiBlocks` populated, `toolCallId` set, and no duplicate on second pass.
- New `web/src/__tests__/stores/useTeamStore.sse-ui-block.test.ts` (clone
  `useTeamStore.followUp.test.ts` style) — `ui_block` SSE event upserts a
  block; duplicate event no-ops; `tool_end` fallback constructs the block
  when the event was missed (the §6.2 path).

---

## 10. Docs / CHANGELOG / in-app help obligations (per AGENTS.md)

**Both streams — `CHANGELOG.md`:** one bullet each under
`## [Unreleased]` → `Added`, written for the user, UI names in bold
(**Settings → Agents**), commands/paths/API names in backticks, no commit
hashes. Examples:

- S1: "- **Settings → Agents** adds a **Response style** choice … - Chat messages now render ```` ```chart ```` and ```` ```mermaid ```` fences as live charts and diagrams."
- S2: "- Agents can now render native structured UI — charts, stat cards, steps, tables, forms — via the `ui_block` tool, which survives reloads and reconnects."

**Stream 1:**

- New `documents/features/intelligent-ui.md` — S1 creates it with the
  A/B/C/D scope headings; fill A and D fully (behavior, settings path,
  fence syntax + spec example, contracts summary); leave B and C sections
  as explicit `<!-- Stream 2 content inserted at merge -->` markers (S1
  owns the file until merge; §8.1).
- `documents/features/README.md:7-9` — add catalogue row: `| Intelligent chat UI (response style, charts, native blocks) | [Intelligent UI](intelligent-ui.md) |`.
- In-app help, `web/src/help/locales/en.ts` (and mirror `ja.ts`/`vi.ts`
  entries per existing practice — run `bun run i18n:extract` /
  `bun run i18n:audit:vi`): a Settings article for **Response style**
  (the settings category is at `en.ts:65`, the Agents settings openAction
  at `:2229`) and a short chat article covering ```chart/```mermaid
  fences.

**Stream 2:**

- `documents/features/tools-skills-mcp-and-plugins.md` — new `ui_block`
  section: catalog table, limits, interaction round-trip, and the
  `show_widget` escape hatch (iframe/CSP) rule: *"ui_block for the catalog;
  show_widget only for arbitrary HTML."*
- In-app help: **not applicable** — no new user-facing settings or chrome;
  state this explicitly in the handoff (AGENTS says "when applicable").
- `documents/reference/http-api.md` / `configuration.md`: **no change** —
  verified that existing settings endpoints (`/settings/follow-up`) and
  runtime-settings keys are not documented there; matching precedent.

---

## 11. Verification commands

**Stream 1:**

```bash
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run ty check app/
uv run pytest --no-cov -q tests/api/test_settings_routes.py tests/agent/hooks
uv run pytest --no-cov -q            # full, before handoff
cd web
bun run lint
bun run typecheck
bun run test:unit -- src/__tests__/utils/markdown.test.tsx   # plus new test files
bun run build                         # proves recharts/mermaid code-splitting
```

**Stream 2:**

```bash
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run ty check app/
uv run pytest --no-cov -q tests/agent/tools/builtin/visualize tests/services/test_memory_stream_store.py tests/api/test_webbridge.py tests/agent/test_loader.py
uv run pytest --no-cov -q            # full, before handoff
cd web
bun run lint
bun run typecheck
bun run test:unit                     # new UiBlock/messages/store tests included
```

Both: `git diff --check`, confirm own `CHANGELOG.md` bullet exists, and
report exactly which checks ran (root AGENTS.md handoff rules).

---

## 12. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | One of the four backend lists in §5.3 is missed | Event silently dropped on refresh/reconnect/browser panel — hard-to-debug "it disappears" bug | §5.3 checklist is all-or-nothing; membership tests in §9.3; parity rule: grep `"widget_delta"` and account for every hit |
| 2 | Parallel edits collide in `CHANGELOG.md` (only shared file) | Merge conflict | §8.2 protocol: separate bullets, merge keeps both |
| 3 | Stream 2 hard-depends on Stream 1's ChartBlock/recharts | Streams can't start in parallel; merge blocked | §8.3 stub rule: dependency-free `UiChart.tsx`, one-file re-point at merge |
| 4 | LLM emits malformed JSON for `blocks` (string escaping) | Tool errors, agent retries, wasted turns | Accept list-or-string, validate with discriminated union, return structured `success False` result with `valid_types`, never raise |
| 5 | Recharts/Mermaid bloat the initial bundle | Slower app start; packaging regression | Both behind `React.lazy`/dynamic import; `bun run build` in S1 verification, inspect chunk split |
| 6 | Streaming partial fence → parse errors/flicker | Visual glitches during generation | `splitStreamingMarkdown` keeps fences intact (:465); invalid+streaming ⇒ skeleton, invalid+complete ⇒ CodeBlock fallback; never throw |
| 7 | XSS via Mermaid SVG / chart HTML | Security | `securityLevel: 'strict'`; chart spec is data-only (no HTML fields); no `dangerouslySetInnerHTML` except Mermaid's sanitized SVG output |
| 8 | Prompt hook reads settings on every model call | I/O per call / stale cache | Same pattern as existing hooks; `load_runtime_settings` is a small file read — if profiling shows cost, cache with mtime check (follow-up decision, not blocking) |
| 9 | `ui_block` event and tool_end reconstruction both create a block | Duplicate blocks in chat | Key by `toolCallId` + existence check (precedent `sse-reducer.ts:334-336`) |
| 10 | Prompt references `ui_block` before Stream 2 merges (A's visual line) | None in practice | Line says "when the ui_block tool is available in your tool registry" (§3.1) |
| 11 | Behavior default flip (`visual`) surprises existing users | Prompt output changes on upgrade | Call out in CHANGELOG as user-visible; `simple` is one click away; `extra="ignore"` keeps old/new settings files interoperable |
| 12 | Webbridge projection branch omitted | Browser panel shows raw/minimal event | List 4 sub-item in §5.3 includes the projection branch; covered by `tests/api/test_webbridge.py` |

**Decisions already taken (no further input needed):**
default `visual`; no new interactivity endpoint in v1 (messages-as-answers);
`http-api.md`/`configuration.md` untouched per precedent; S2 skips in-app
help; chart spec validated on the frontend for `ui_block` nodes until merge.

---

## 13. Anchor verification log

All anchors in §2 were re-read/grepped in-repo on 2026-10-13. Corrections
made against earlier assumptions while verifying:

1. **`FollowUpBehaviorCard` location** — it lives inline in
   `web/src/routes/settings.agents.tsx:379-409` (mounted at :217), not in a
   separate component file.
2. **Tool rendering component** — only `web/src/components/ToolCallGroup.tsx`
   (+ its colocated test) exists; there is no `ToolCall*` component family.
3. **Frontend test script** — `web/package.json:14-16` confirms
   `bun run test:unit` (`vitest run`); there is no plain `bun test`.
4. **No existing backend test hits `/settings/follow-up`** — response-style
   route tests must be written fresh in `tests/api/test_settings_routes.py`
   (the closest templates are the computer-app round-trip test at :1617 and
   the unrelated-section test at :2269).
5. **`recharts`/`mermaid` confirmed absent** from both `web/package.json`
   dependencies and all of `web/src` — D must add them.
6. **`http-api.md` / `configuration.md` confirmed not to document settings
   endpoints or runtime-settings keys** — no doc obligation for the new
   endpoint/key.
7. **`_NON_REPLAYABLE_EVENT_TYPES` exists separately** from
   `_AGENT_CONTENT_EVENT_TYPES` (`memory_stream_store.py:41` vs :59) — the
   checklist explicitly records the negative rule (never add `ui_block` to
   the former).
8. **`messages.ts` widget branch** starts at :225 (condition) with the
   comment at :222; `BlockRenderer` widget case at :449; client follow-up
   type at `settings.ts:214` — earlier looser ranges tightened to these
   exact lines.
