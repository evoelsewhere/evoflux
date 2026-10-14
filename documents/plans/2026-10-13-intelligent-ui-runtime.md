# Runtime Intelligence (Tier 2+3) — Build-Ready Spec

**Date:** 2026-10-13
**Task ID:** 06ace3ab-301a-7a6a-8000-327f93d34431
**Status:** Build-ready, approved scope
**Predecessor spec:** [`documents/plans/2026-10-13-intelligent-ui.md`](2026-10-13-intelligent-ui.md) (features A+B+C+D — implemented, branch tip `e17b89e0`)
**Target of this spec:** Tier-2+3 unified runtime-intelligence package: (a) block identity + `replace_id` protocol, (b) `layout` block type, (c) `custom` block type, (d) markdown-table → interactive upgrade contract, (e) 2-stream ownership map, (f) focused test plan.

---

## 0. Context and ground rules

Features A–D from the predecessor spec are implemented and merged on `EvoFlux/integration/06acd916-2b5` (tip `e17b89e0`). **Nothing from that work is removed or reworked** — this package builds on it; prior commits remain necessary foundation (the lead's plan update confirms no prior commits were dropped). This spec reads against these implemented surfaces:

| Surface | File (verified) | Key anchors |
|---|---|---|
| `ui_block` tool | `app/agent/tools/builtin/visualize/ui_block.py` | `_VALID_TYPES` :25, `description` :44-55, `blocks` arg :61-77, `title` arg :81-91, `UiBlockEvent.model_validate` :126, single `push_event` :140-148 |
| Event models | `app/agent/schemas/events.py` | `_formula_identifiers` :560, `UiCalculatorBlock` model_validator :651 (the server-validation pattern), discriminated `UiBlockNode` union :666-683, `UiBlockEvent` :685-698 |
| Replay journal | `app/services/memory_stream_store.py` | `ui_block` already in `_AGENT_CONTENT_EVENT_TYPES` :63-80 → replayed in producer order on reconnect |
| Browser bridge projection | `app/api/routes/team/webbridge.py` | `ui_block` in forward list :1934, projection branch :2077-2090 |
| Live SSE reducer | `web/src/stores/useTeamStore/sse-reducer.ts` | `case 'ui_block'` :301-330 (dedupe by `toolCallId`, `currentBlocks` only), `tool_end` fallback :400-434, stream flush :805-820 |
| History reconstruction | `web/src/utils/messages.ts` | `assistantBlocks` :150, ui_block branch :241-259, `pendingToolBlocks` :301/:339/:352, `parseApiMessages` :299, `parseTeamBlocks` :454/:507 |
| Block wire type | `web/src/api/types.ts` | `uiBlocks` on `ChatBlock` :862 |
| Catalog + dispatch | `web/src/components/ui/ui-block-types.ts` (union :150-162), `web/src/components/ui/UiBlockRenderer.tsx` (dispatch switch) |
| Widget pipeline | `app/agent/tools/builtin/visualize/show_widget.py` (delta loop :120-143), `web/src/components/WidgetRenderer.tsx` (`wrapHtml` CSP/storage/prompt/resize bridges, iframe `sandbox`/`srcdoc` :266-281) |
| Widget token guidance | `app/agent/tools/builtin/visualize/guidelines.py` :49-75 (`:root` / `.dark` widget token vocabulary) |
| Markdown pipeline | `web/src/utils/markdown.tsx` — `remark-gfm` in `package.json`, single `ReactMarkdown` call site :572-578, `MarkdownBlock` components map :649-735 (`isStreaming` already in memo deps :734), streaming caret targets direct-child `table` in `web/src/index.css` :2928-2946 |
| Theme mechanism | `web/src/lib/theme.ts` (`:root.light`/`:root.dark` via `html.classList`), observer pattern in `web/src/components/markdown/ChartBlock.tsx` :76 |

**Hard constraints (from delegation):** provider-neutral schemas; tool-agnostic prompt bodies — **zero agent-prompt/seed edits** (no Tier-1 prompt/propensity/response-style changes); **no DB/Alembic ever** (persistence stays via tool-args reconstruction); no scheduler changes; thin routes; single complete `ui_block` SSE event per tool call (no delta streaming for `ui_block`).

**Non-goals:** no new SSE event types; no `show_widget`/`widget_delta` behavior change; no changes to `app/agent/permission.py`, `app/agent/mode/team/tier_policy.py`, `app/agent/loader.py`, or `_AGENT_CONTENT_EVENT_TYPES` (all are tool-level or already correct — block types are internal to the tool/event/renderer); no Help/docs/CHANGELOG edits in the coder streams — those are merge-task obligations (see §6.4).

---

## 1. Block identity + `replace_id` protocol (a)

### 1.1 Tool arguments (source contract)

Two new optional args on `ui_block` alongside `title` (`ui_block.py:61-100`):

```jsonc
// First call — name the block group so it can be updated later
{
  "title": "deploy_status",
  "block_id": "deploy_status",
  "blocks": [ { "type": "steps", "items": [/* … */] } ]
}

// Later call — replace the earlier group in place (same message/session)
{
  "replace_id": "deploy_status",
  "blocks": [ { "type": "steps", "items": [/* … */] } ]
}
```

- `block_id: str = ""` — optional stable name for **this** group. Agents should always set it on blocks they intend to update (provider tool-call id formats are not guaranteed identical across providers; `block_id` is the supported path).
- `replace_id: str = ""` — optional identity of an earlier group to replace in place.
- Both are declared as `Annotated[..., Field(description=...)]` next to `title`, documented in the tool `description` (:44-55) and in the `blocks` arg Field description (:64-77). Empty string is normalized to `None` before `model_validate` (agents habitually pass `""`).
- `title`/`blocks` semantics unchanged. Tool result dict unchanged (still no block echo).

### 1.2 Server-side validation (format)

On `UiBlockEvent` (`events.py:685-698`) — the same model the tool already `model_validate`s (:126), so validation lands on the hot path with the calculator-pattern behavior (raise → friendly tool error, no SSE push):

```python
_BLOCK_ID_RE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"   # max 128 chars

class UiBlockEvent(BaseModel):
    ...
    block_id:   str | None = Field(default=None, pattern=_BLOCK_ID_RE)
    replace_id: str | None = Field(default=None, pattern=_BLOCK_ID_RE)
```

- `pattern` applies only to non-`None`; `None` (absent or `""`-normalized) always passes → **old persisted tool args and old events remain valid; no migration, no Alembic**.
- Format tolerates typical provider tool-call ids (`call_…`, `toolu_…`) *and* snake/kebab ids, but the tool description steers agents to `block_id` for replaceable groups.

### 1.3 SSE event shape (single complete event)

One complete `ui_block` event per call, unchanged envelope plus two optional fields:

```jsonc
{
  "type": "ui_block",
  "agent": "main",
  "tool_call_id": "call_abc123",     // identity when block_id absent
  "block_id": "deploy_status",       // NEW, optional
  "replace_id": null,                // NEW, optional
  "blocks": [ /* 1..6 validated nodes, now incl. layout/custom */ ],
  "is_final": true,
  "metadata": { "title": "deploy_status" }   // present only when title given
}
```

- `block_id`/`replace_id` are **typed top-level fields** (not `metadata`) so validation and the TS mirror stay explicit.
- `app/api/routes/team/webbridge.py:2077-2090` projection gains `copy_strings("block_id", "replace_id")` so browser-bridge consumers see the same contract (`blocks` already passes through wholesale, so new block types ride along with no bridge change).
- `app/services/stream_envelope.py` `AnyStreamEvent` already includes `UiBlockEvent` — no change.

### 1.4 Identity rules (normative — both client paths MUST implement exactly this)

Let **scope** be the ordered list of the agent's `ui_block` groups (defined per path in §1.5). For each incoming call/event, in order:

1. `target = scope.find(identity == replace_id)` if `replace_id` present.
2. Else `target = scope.find(identity == block_id ?? tool_call_id)` (same-name upsert / same-call dedupe).
3. If `target` found → **update `target` in place** (same array index, same `block.id`, same stored identity). Payload = the later call's complete state: `uiBlocks` replaced wholesale; **title updated only when the later call supplies one** (event `metadata.title`/`d.title` absent ⇒ keep existing title — mirrors today's `if (title) existing.title = title` reducer behavior at `sse-reducer.ts:318-320`); `toolCallId` refreshed to the latest call.
4. If not found → **append a new group**; its `identity = block_id ?? replace_id ?? tool_call_id` (precedence order). An unmatched `replace_id` therefore becomes the new group's identity, so a subsequent call can still chain it (covers partial-replay and cross-scope cases deterministically).

**Ordering semantics:** *a later call with `replace_id` replaces the earlier block in-place — the group keeps the position of its first appearance in the conversation; all rendered content comes from the latest write in arrival order (last writer wins).* Events are applied strictly in journal/history order.

**Identity is immutable once created** (rule 3 never renames). This is what makes replay idempotent: a replayed `replace_id` call re-finds the same group; a replayed creation call re-finds by `block_id ?? tool_call_id`; nothing ever forks into a duplicate.

Storage: `ChatBlock` (ui_block variant) gains `uiBlockIdentity?: string` (`web/src/api/types.ts:858-862` region — named with the existing `uiBlocks` prefix convention). The SSE event does not carry a computed identity; the client derives it per rule 4/§1.4 from `block_id ?? tool_call_id`.

### 1.5 Scope definition per path

- **Live (reducer):** the agent's own stream — search `stream.blocks` **then** `stream.currentBlocks` (`sse-reducer.ts:301-330`). Searching `stream.blocks` too is a deliberate extension of today's `currentBlocks`-only dedupe: it makes replace work across message-finalization boundaries and makes reconnect replay of an already-flushed event idempotent (today a replayed event after flush would append a duplicate).
- **History (messages.ts):** the session's messages in order — a shared `uiBlockGroups: Map<string, ContentBlock>` threaded through `assistantBlocks` exactly like `pendingToolBlocks` (`messages.ts:301/:352`, `:454/:507`). Scope equals "this agent's session conversation" (team messages are per-agent sessions; `parseTeamBlocks` builds one flat list per fetched session set). Both paths therefore agree: **scope = one agent's ordered conversation.**
- Cross-agent / cross-session `replace_id` ⇒ not found ⇒ rule 4 (append with `identity = replace_id`). Explicitly unsupported: agent B replacing agent A's block.

### 1.6 Reference algorithm (shared by reducer and history)

```text
applyUiBlock(scope, {tool_call_id, block_id, replace_id, blocks, title}):
  identity   = block_id ?? tool_call_id
  target     = replace_id ? find(scope, replace_id) : find(scope, identity)
  if target:
      target.uiBlocks = blocks
      if title is present: target.title = title
      target.toolCallId = tool_call_id        # latest writer
      # target.uiBlockIdentity UNCHANGED, target.id UNCHANGED, position UNCHANGED
      return target                            # no append
  group = new ui_block block:
      id              = (history: `${msg.id}:ui_block:${identity}`)   # first creator's msg
      uiBlockIdentity = replace_id ?? block_id ?? tool_call_id        # rule 4
      uiBlocks        = blocks
      toolCallId      = tool_call_id
      title           = title ?? ('UI Block')                        # existing fallback
  scope.append(group); register group for tool_call_id (history: pendingToolBlocks)
  return group
```

**Integrations:**

- `sse-reducer.ts` `case 'ui_block'` (:301-330): replace the `toolCallId`-only dedupe with `applyUiBlock` over `[...stream.blocks, ...stream.currentBlocks]`.
- `sse-reducer.ts` `tool_end` fallback (:400-434): reconstructs from tool args when the SSE event never arrived — it must read `block_id`/`replace_id` from `parsedArgs` and call the **same** `applyUiBlock` helper (extract one in-module helper function; no new files).
- `messages.ts` ui_block branch (:241-259): replace "always push a new block" with `applyUiBlock`; when a call updates an existing group, still register `pendingToolBlocks.set(tool.id, group)` so the later call's tool-result message attaches to the merged group (today only the creating call registers — `:257`).

### 1.7 Idempotent replay — why it holds

- **Reload:** history reconstruction is a pure function of the ordered `tool_calls` JSON. Applying §1.4 in message order yields one group per identity, first-appearance position, latest-writer content. Re-running the parse produces byte-identical blocks (group ids derive from `identity`, not loop index — note the current `${tool.id || toolIndex}` at `messages.ts:247` changes to identity-based).
- **Reconnect (live):** `ui_block` is journaled and replayed in producer order (`memory_stream_store.py:63-80`). Every operation in §1.4 is *find-by-identity-or-append with immutable identity*; replaying the same ordered sequence over a state that already contains it converges to the same state (updates overwrite with identical payload; no op ever duplicates a group). A replayed creation event whose group already flushed into `stream.blocks` is found there (§1.5).
- **Partial replay** (only a replace arrives, creation lost): rule 4 appends with `identity = replace_id`; if the creation event then arrives, its `identity = block_id ?? tool_call_id` equals that value and converges to the same group.

### 1.8 Backward compatibility

- Old persisted tool args (no `block_id`/`replace_id`) ⇒ `identity = tool_call_id` ⇒ identical rendering to today.
- Old SSE events ⇒ fields `undefined` ⇒ current dedupe behavior.
- Old clients seeing new events ⇒ ignore unknown fields.
- `is_final`, event ordering, single-event-per-call, and the no-block-echo tool result are unchanged.

---

## 2. `layout` block type (b)

### 2.1 Composition schema (Pydantic, `events.py` — placed before the `UiBlockNode` alias, forward refs resolved after)

```python
MAX_UI_BLOCK_DEPTH  = 3    # layout nesting levels (root layout = 1)
MAX_UI_BLOCK_NODES  = 50   # total nodes per ui_block event

class UiLayoutSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str | None = Field(default=None, max_length=80)
    children: list["UiBlockNode"] = Field(min_length=1, max_length=8)

class UiLayoutBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["layout"] = "layout"
    orientation: Literal["columns", "stack"] = "columns"
    sections: list[UiLayoutSection] = Field(min_length=1, max_length=4)
```

- Recursive forward refs: define both classes **above** `UiBlockNode = Annotated[Union[…], Field(discriminator="type")]` (`events.py:666`), append `UiLayoutBlock` to the union list, then call `UiLayoutSection.model_rebuild()` and `UiLayoutBlock.model_rebuild()` immediately after the alias (same module tail, before `UiBlockEvent`).
- **Depth + node-cap validation (server):** a `@model_validator(mode="after")` on `UiBlockEvent` (same decorator style as `UiCalculatorBlock:651`) walks all nodes: counts total nodes, tracks layout nesting depth (depth increments only through `UiLayoutSection.children`), raises `ValueError` past `MAX_UI_BLOCK_DEPTH`/`MAX_UI_BLOCK_NODES`. Friendly tool error, no event pushed. Existing `blocks` cap of 1..6 stays (`events.py:696`).
- Non-layout blocks cannot nest — only `layout` contributes depth.

### 2.2 Client mirror + catalog

- `web/src/components/ui/ui-block-types.ts`: `UiLayoutSection`/`UiLayoutBlock` interfaces (style of existing interfaces :95-145), add `UiLayoutBlock` to the `UiBlockNode` union (:150-162), export `UI_BLOCK_MAX_DEPTH = 3` mirror constant.
- `web/src/components/ui/UiLayout.tsx` (**NEW**): renders sections — `orientation: "columns"` ⇒ CSS grid `grid-template-columns: repeat(auto-fit, minmax(240px, 1fr))` via inline style (no dynamic Tailwind classes — Tailwind cannot purge-safe generate per-count utilities); `stack` ⇒ vertical flex with gap. Section titles render as quiet headings using existing text tokens (`--color-text-muted` pattern as in `UiBlockRenderer.tsx:96`).
- **Cycle-free recursion:** `UiLayout` does **not** import `UiBlockRenderer`. `UiBlockRenderer` passes a render-prop: `renderChild={(child, depth) => <UiBlockRenderer node={child} depth={depth} />}`. `UiLayout` imports only types. No ESM import cycle.
- `web/src/components/ui/UiBlockRenderer.tsx`: add `case 'layout'`, and an optional `depth = 0` prop threaded into `renderChild`.

### 2.3 Depth cap + recursion protection (both layers)

- **Server:** §2.1 validator (authoritative — invalid payloads never reach SSE).
- **Client:** `UiBlockRenderer` renders `layout` nodes only while `depth < UI_BLOCK_MAX_DEPTH`; deeper children render an `UiCallout` fallback ("Layout nested too deep"). This guards hand-edited/legacy tool args that bypassed server validation (history args are validated at creation time, not on read) and guarantees termination even on malformed data.

### 2.4 Tool registration

`app/agent/tools/builtin/visualize/ui_block.py`: add `layout` (and `custom`, §3) to `_VALID_TYPES` (:25-38) and to both human/agent-facing type enumerations (`description` :46-49, `blocks` arg Field description :64-77), with one-line shape guidance ("layout: {orientation?: 'columns'|'stack', sections: [{title?, children: [...]}], nesting ≤ 3"). This is tool-contract text, **not** an agent prompt file — prompt/seed files remain untouched per constraints.

---

## 3. `custom` block type (c)

### 3.1 Schema

```python
class UiCustomBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["custom"] = "custom"
    html: str = Field(min_length=1, max_length=100_000)
    height: int | None = Field(default=None, ge=64, le=2000)   # initial frame height
```

Added to the `UiBlockNode` union and TS mirror (§2.2 files) with `UiCustomBlock` interface + union member.

### 3.2 Rendering decision — reuse the show_widget iframe sandbox, single frame

- `web/src/components/ui/UiCustom.tsx` (**NEW**) renders `<WidgetRenderer html={...} />` (existing named export, `web/src/components/WidgetRenderer.tsx`) inside a container seeded with `height ?? 320` px. It inherits **everything** already built by the `show_widget` pipeline: `wrapHtml` CSP (`default-src 'none'`, allowlisted script CDNs, `connect-src 'self'`), storage shim, `window.evoflux.widget.sendPrompt` → conversation bridge, and the postMessage auto-resize bridge. `WidgetRenderer.tsx` itself is **not modified**.
- **Single-frame semantics:** the `custom` HTML arrives complete inside the one `ui_block` SSE event — no `widget_delta`, no streaming/morphdom growth loop; the frame mounts once (`isStreaming` false path of WidgetRenderer). Multiple `custom` nodes in one call ⇒ one independent iframe each. Post-mount changes happen only if the `html` prop changes (used by the theme bridge below).
- **Sanitization decision:** server-side = size cap only (`max_length=100_000`) plus `model_validate` typing; **no HTML rewriting/stripping** — the agent's HTML is the deliverable and `show_widget` likewise enforces no sanitization beyond structure (its "no doctype" rule is docstring guidance). Containment is the sandbox: React assigns `srcdoc` as an iframe property, so the HTML is never parsed into the host DOM; scripts inside run under the injected CSP. This is parity with the existing widget posture (see risk R2 for the inherited `allow-scripts allow-same-origin` caveat — deliberately unchanged this round).
- `BlockRenderer.tsx` needs no change (`case 'ui_block'` :465 already delegates to `UiBlockRenderer`; `case 'widget'` :450 untouched).

### 3.3 Design-token / theme inheritance

Widgets today self-declare tokens and follow OS `prefers-color-scheme`, desyncing from the app theme (`html.dark`, `web/src/lib/theme.ts:61`). For `custom`, bridge the app theme explicitly, entirely inside `UiCustom.tsx`:

1. **At render:** `collectWidgetTokens()` reads resolved values from `getComputedStyle(document.documentElement)` and prepends `<style id="evoflux-widget-tokens">:root{ …; color-scheme: light|dark; }</style>` to the html handed to `WidgetRenderer`.
2. **Frozen mapping** (widget vocabulary per `guidelines.py:49-75` ← app token ← literal fallback copied from `guidelines.py`):

   | widget var | app source (`web/src/index.css`) | fallback |
   |---|---|---|
   | `--color-text-primary` | `--color-text` (:190) | guideline light/dark literal |
   | `--color-text-secondary` | `--color-text-2` (:191) | guideline literal |
   | `--color-background` | `--bg-card` (:171) | guideline literal |
   | `--color-background-secondary` | `--bg-page` (:169) | guideline literal |
   | `--color-border` | `--color-border` (:186/:197 area) | guideline literal |
   | `--color-accent` | `--color-accent` (= `--accent`, :114) | guideline literal |
   | `--color-success` / `--color-warning` / `--color-error` | app semantic vars if present | `guidelines.py:60-62/:70-74` literals |

   App-only tokens (`--color-text-muted`, `--color-text-subtle`, `--bg-*`) are injected verbatim as a second group so agent HTML may also use the app vocabulary directly.
3. **On theme change:** a `MutationObserver` on `documentElement`'s `class` attribute (the `ChartBlock.tsx:76` pattern) recomputes tokens and re-renders with the new `html` prop → morphdom applies the updated `<style>` in place. No `WidgetRenderer` or theme-store changes.

---

## 4. Markdown-table → interactive upgrade (d) — CLIENT-ONLY contract, FIXED rules

**The following rules are fixed by the lead — documented verbatim, not to be redesigned:**

> activate only when the message is not streaming; threshold >= 6 body rows AND >= 3 columns; features = column sort (aria-sort, numeric-aware) + quick filter input when >= 10 body rows + contained horizontal scroll; reuse existing table styling tokens; streaming or small tables stay plain; no regression of existing markdown tests

**Interpretation boundaries (contract, not redesign):**

- **Client-only:** no backend, SSE, schema, or persistence changes of any kind. Pure `web/` change.
- **Gating:** interactive behavior activates only when `isStreaming` is false for the message *and* the parsed table has **≥ 6 body rows and ≥ 3 columns**. Streaming tables and smaller tables render exactly as they render today (plain element, no wrapper).
- **Features when active:** (1) column sort — clickable header cells, `aria-sort` reflecting current direction, numeric-aware comparison (numeric values compare numerically, strings case-insensitively); (2) quick-filter input when **≥ 10 body rows** — case-insensitive substring match across cells with an explicit empty-result row; (3) contained horizontal scroll on narrow viewports (`overflow-x: auto` on the wrapper only — never page-level).
- **Styling:** reuse existing table styling tokens — the interactive wrapper must be visually indistinguishable from today's `.oa-prose table` output.
- **Streaming caret safety:** `web/src/index.css:2928-2946` styles `.oa-streaming-prose > table:last-child …` as a **direct child** selector; because interactive mode never engages while streaming, the plain table stays a direct child during streaming and the caret rules are unaffected. No wrapper may be inserted while `isStreaming`.
- **Single pipeline:** one `ReactMarkdown` call site (`web/src/utils/markdown.tsx:572-578`) fed by the `MarkdownBlock` components map (:649-735, `isStreaming` already in its memo deps :734) — the `table` entry belongs in that map; verify no second user-facing prose renderer passes a different map.
- **Ownership:** this slice is **Stream 3** — pre-dispatched as task `task_19` to `coder#5`, scope `web/src/components/markdown/**` + its focused tests (per coder#5's brief: "(1) Render a markdown table as interactive only when the message is NOT streaming AND the table has >= 6 body rows AND >= 3 columns; smaller tables or tables still streaming render exactly as plain today. (2) Interactive features: click a column header to sort (toggle asc/desc, numeric-aware comparison so \"10\" > \"9\" numerically, string columns compare case-insensitively); a quick-filter input when the table has >= 10 body rows (case-insensitive substring match across all cells, live filtering, an explicit \"no matches\" row); contained horizontal scroll on narrow screens." — that brief remains stream-3's source of truth for expansion). Stream 3 has **zero file overlap** with Streams 1–2 (§5).

---

## 5. Ownership map (e) — exactly 2 coder streams for this package (+ pre-dispatched Stream 3)

### 5.1 Stream 1 — replace/update protocol (task `task_17`)

| File | Change |
|---|---|
| `app/agent/schemas/events.py` | `UiBlockEvent`: +`block_id`, +`replace_id` fields with `_BLOCK_ID_RE` pattern (:685-698 region) |
| `app/agent/tools/builtin/visualize/ui_block.py` | +`block_id`/`replace_id` args (:61-100), `""→None` normalization, event dict fields (:126-135), tool `description` guidance (:44-55) |
| `app/api/routes/team/webbridge.py` | projection `copy_strings("block_id", "replace_id")` (:2077-2090 branch) |
| `web/src/api/types.ts` | `uiBlockIdentity?: string` on ui_block `ChatBlock` (:858-862 region) |
| `web/src/stores/useTeamStore/sse-reducer.ts` | in-module `applyUiBlock` helper; `case 'ui_block'` (:301-330) and `tool_end` fallback (:400-434) become identity-aware over `[stream.blocks, stream.currentBlocks]` |
| `web/src/utils/messages.ts` | identity-keyed reconstruction (:241-259), `uiBlockGroups` map threaded via `parseApiMessages`/`parseTeamBlocks` call sites (:352/:507), `pendingToolBlocks` registration for replaced calls |
| `web/src/__tests__/stores/useTeamStore.uiBlock.test.ts` | extend (§6.1) |
| `web/src/__tests__/utils/messages.test.ts` | extend (§6.1) |
| `tests/agent/schemas/test_ui_block_identity.py` | **NEW** (§6.1) |
| `tests/agent/tools/builtin/visualize/test_tools.py` | extend — `TestUiBlock` class only (§6.1) |
| `tests/api/test_webbridge.py` | extend — projection fields |
| `tests/services/test_memory_stream_store.py` | extend — journal round-trip retains new fields |

### 5.2 Stream 2 — `layout` + `custom` block types (task `task_18`)

| File | Change |
|---|---|
| `app/agent/schemas/events.py` | `UiLayoutSection`/`UiLayoutBlock`/`UiCustomBlock`, union additions + `model_rebuild`, depth/node-cap validator on `UiBlockEvent`, constants |
| `app/agent/tools/builtin/visualize/ui_block.py` | `_VALID_TYPES` (:25-38) + both type enumerations (:46-49, :64-77) += `layout`, `custom` |
| `web/src/components/ui/ui-block-types.ts` | `UiLayoutBlock`/`UiCustomBlock` interfaces, union members (:150-162), `UI_BLOCK_MAX_DEPTH` |
| `web/src/components/ui/UiBlockRenderer.tsx` | `layout`/`custom` dispatch cases, `depth` prop, depth-cap fallback |
| `web/src/components/ui/UiLayout.tsx` | **NEW** — sections/columns renderer with `renderChild` render-prop (no back-import) |
| `web/src/components/ui/UiCustom.tsx` | **NEW** — `WidgetRenderer` reuse, token collector + map + `MutationObserver` |
| `web/src/__tests__/components/UiBlockRenderer.test.tsx` | extend (§6.2) |
| `web/src/__tests__/components/UiLayout.test.tsx` | **NEW** (§6.2) |
| `web/src/__tests__/components/UiCustom.test.tsx` | **NEW** (§6.2) |
| `tests/agent/schemas/test_ui_block_composition.py` | **NEW** (§6.2) |
| `tests/agent/tools/builtin/visualize/test_ui_block_composition.py` | **NEW** (§6.2) |

### 5.3 Shared files — explicit sequential order

Exactly two files are touched by both streams: **`app/agent/schemas/events.py`** and **`app/agent/tools/builtin/visualize/ui_block.py`** (disjoint regions: Stream 1 = `UiBlockEvent` field tail + tool arg signature; Stream 2 = node models + union + `_VALID_TYPES`/type lists). Mandatory sequence:

1. **Stream 1 lands its edits to those two files first.**
2. **Stream 2 starts immediately on its exclusive files** (components, TS types, tests) and applies its edits to the two shared files **only after Stream 1's version is pulled**.
3. Stream 1's other files (`sse-reducer.ts`, `messages.ts`, `api/types.ts`, backend projection/tests) and Stream 2's files never intersect Stream 3 — **zero file overlap across the three scopes**.

If the lead chooses full parallelism instead, the two shared files must be edited in their stated disjoint regions and merged by the integrator (`task_20`) — the sequential order above is the default because it makes that merge mechanical.

### 5.4 Merge-task obligations (not in either stream)

`task_20` (merge): focused gates + browser verification; `CHANGELOG.md` `[Unreleased]` entries; docs — `documents/features/intelligent-ui.md` (+ its catalogue/reference entries per the repository documentation contract) and in-app Help under `web/src/help/locales/` if user-visible help applies. No prompt/seed file edits anywhere in this package.

---

## 6. Focused test plan (f) — exact paths

### 6.1 Stream 1 — pytest (backend)

- `tests/agent/schemas/test_ui_block_identity.py` **(NEW)**
  - `block_id`/`replace_id` accept snake/kebab/provider-style ids; reject 129 chars, leading punctuation, illegal chars (`$`, spaces, `/`).
  - `None`/absent pass; event round-trips both fields; old-shaped payload (fields absent) still validates.
- `tests/agent/tools/builtin/visualize/test_tools.py` **(extend — `class TestUiBlock` only)**
  - tool passes `block_id`/`replace_id` into the pushed envelope; `""` normalized to absent; invalid `replace_id` ⇒ error result, **no** `ui_block` event pushed; single event per call unchanged.
- `tests/api/test_webbridge.py` **(extend)** — projected `ui_block` JSON carries `block_id`/`replace_id`; absent fields stay absent.
- `tests/services/test_memory_stream_store.py` **(extend)** — journal replay round-trips an envelope containing both fields (existing `UiBlockEvent` usage :1428).

### 6.2 Stream 2 — pytest (backend)

- `tests/agent/schemas/test_ui_block_composition.py` **(NEW)**
  - discriminated union parses `layout`/`custom`; section/children limits; depth-4 layout rejected with `ValueError`; >50-node payload rejected; depth-3 accepted; `custom` html min/max/height bounds.
- `tests/agent/tools/builtin/visualize/test_ui_block_composition.py` **(NEW)**
  - tool round-trips a `layout` envelope and a `custom` envelope (single event each); `_VALID_TYPES`/description registration; deep-nesting payload ⇒ friendly error, no push.

### 6.3 Vitest (web) — Stream 1

- `web/src/__tests__/stores/useTeamStore.uiBlock.test.ts` **(extend)**
  - replace hits `stream.currentBlocks` in place (index/`id` preserved, content/title updated only when title present); replace hits a group already flushed into `stream.blocks` (cross-message); same-`block_id` upsert; unmatched `replace_id` appends with `identity = replace_id`; replay of a full sequence twice ⇒ identical state (single group, final content); `tool_end` fallback honors `replace_id`/`block_id`; identity in another agent's stream is NOT matched.
- `web/src/__tests__/utils/messages.test.ts` **(extend)**
  - cross-message replace chain rebuilds one group at the **first** call's position with the last call's content; identity-based group ids (stable across rebuild runs); `pendingToolBlocks` maps the later call's tool id to the merged group so its tool-result attaches; unmatched `replace_id` appends; no-`block_id` legacy calls behave exactly as today (regression fixtures).

### 6.4 Vitest (web) — Stream 2

- `web/src/__tests__/components/UiBlockRenderer.test.tsx` **(extend)** — dispatches `layout`/`custom`; renders depth-cap fallback beyond `UI_BLOCK_MAX_DEPTH`.
- `web/src/__tests__/components/UiLayout.test.tsx` **(NEW)** — columns/stack rendering, section titles, `renderChild` recursion to depth 3, guard at 4, no import cycle (renders nested fixture).
- `web/src/__tests__/components/UiCustom.test.tsx` **(NEW)** — mounts `WidgetRenderer` with single complete html (no delta), token `<style>` prepended with mapped vars, `MutationObserver` re-render on `html` class flip, prompt bridge reachable inside the frame (mock `postMessage`).
- Existing regression suites must stay green: `web/src/__tests__/components/BlockRenderer.ui-block.test.tsx`, `UiInteractiveBlocks.test.tsx`.

### 6.5 Stream 3 (task `task_19`, coder#5 — listed for completeness)

- `web/src/__tests__/utils/markdown.test.tsx` **(extend)** — every fixed rule in §4 (6×3 threshold, streaming-plain, ≥10-row filter, numeric sort, `aria-sort`, contained scroll) + existing markdown tests unchanged.

### 6.6 Commands

```bash
# backend (per stream, then full at merge)
uv run ruff check app/ tests/ && uv run ruff format --check app/ tests/ \
  && uv run ty check app/ \
  && uv run pytest --no-cov -q tests/agent/schemas/test_ui_block_identity.py \
       tests/agent/schemas/test_ui_block_composition.py \
       tests/agent/tools/builtin/visualize/ tests/api/test_webbridge.py \
       tests/services/test_memory_stream_store.py

# web
cd web && bun run lint && bun run typecheck \
  && bun run test:unit -- src/__tests__/stores/useTeamStore.uiBlock.test.ts \
       src/__tests__/utils/messages.test.ts src/__tests__/components/UiBlockRenderer.test.tsx \
       src/__tests__/components/UiLayout.test.tsx src/__tests__/components/UiCustom.test.tsx

# merge task additionally runs the full suites + `git diff --check` + CHANGELOG/docs audit
```

---

## 7. Risks and open questions

| # | Risk / question | Mitigation / decision |
|---|---|---|
| R1 | **Shared files** (`events.py`, `ui_block.py`) edited by both streams | Mandatory sequential order §5.3; disjoint regions named; integrator merges |
| R2 | **Sandbox posture:** `WidgetRenderer` uses `sandbox="allow-scripts allow-same-origin"` with `srcdoc`, so frame scripts share the host origin — inherited from `show_widget`, deliberately reused for `custom` | Explicit non-goal this round; do not "quietly harden" (dropping `allow-same-origin` breaks `connect-src 'self'` and the storage shim). Track as a follow-up security item with its own test pass |
| R3 | Replace scope: per-message vs session-wide — per-message would break the core mid-turn update flow (turns span multiple assistant messages, see `messages.ts:276` comment) | Decided: **session-wide per agent** (§1.5); both paths share `applyUiBlock`; cross-agent replace explicitly unsupported |
| R4 | Tool `description` edits are model-facing text while the constraint says "zero prompt edits" | Treated as **tool contract** (args documentation), not prompt/propensity change — the delegation itself mandates `replace_id` as a tool arg. Lead to confirm if a stricter reading was intended |
| R5 | Provider tool-call id formats vary (case/length) — targeting them via `replace_id` can fail the pattern | `block_id` is the supported, documented path; regex broad (`A-Za-z0-9_.-`, ≤128); tool description says "set `block_id` on blocks you intend to update" |
| R6 | Stream-3 brief expansion of rule (3) (visual tokens) was only partially recovered into this spec | Stream 3 is pre-dispatched; coder#5's brief (task `task_19`) is its source of truth — §4's lead-fixed sentence above is the complete verbatim mandate this spec must carry |
| R7 | Layout column classes must not be dynamically generated (Tailwind purge) | Fixed `auto-fit minmax(240px, 1fr)` inline grid + stack variant (§2.2) |
| R8 | Replay journal is in-memory (dead sessions rely on history only) | Both paths implemented and tested independently (§1.7, §6.3) |
| R9 | `custom` html cap 100 000 chars vs unbounded `show_widget` | Deliberate: `ui_block` events are one-shot envelopes (≤6 nodes); raise only if real agents hit the cap |
| R10 | `identity` naming on the shared flat `ChatBlock` interface | Prefixed `uiBlockIdentity` to match `uiBlocks` convention and avoid collisions |

**Open question for the lead (non-blocking):** none — R4 is flagged for confirmation but the spec defaults to in-scope.
