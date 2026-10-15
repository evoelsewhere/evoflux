# Rich Intelligent UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an EvoFlux-native, capability-aware rich visual artifact path for useful dashboards, animated explainers, and 3D scenes while preserving native `ui_block` as the simple interaction path.

**Architecture:** A new validated `visual_artifact` tool emits a complete SSE envelope that is persisted and replayed from assistant tool-call arguments, using the existing session/history contract instead of a new artifact control-plane database. A dedicated themed iframe host provides the narrow bridge, motion controls/export, and lazy 3D runtime; `ui_block` remains the default for compact structured UI. Dashboard data comes from tools/files already available to the agent and carries source/freshness metadata.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, existing EvoFlux SSE/tool/skill pipeline, React 19, TypeScript, Vite, existing CSS theme tokens, Web `MessageChannel`, Canvas `captureStream()`/`MediaRecorder`, exact-version-pinned Three.js loaded on demand, pytest, Vitest.

**Spec:** [2026-10-15-rich-intelligent-ui-spec.md](2026-10-15-rich-intelligent-ui-spec.md)

## Global Constraints

- Keep `ui_block` as the default for small declarative interactions; use `visual_artifact` only when custom dashboards, motion, or 3D materially improve the task.
- `source_html` is at most 200,000 UTF-8 bytes; a dashboard has at most 12 source records; title is at most 120 characters; summary is at most 500 characters; motion duration is at most 120,000 ms.
- Rich artifacts persist through normal tool-call history; do not add artifact tables, background workers, scheduled polling, or retired Artifact Fabric control-plane objects.
- The rich artifact iframe must not have `allow-same-origin`; its sandbox bridge is an explicit, schema-validated `MessageChannel`.
- Generated UI uses EvoFlux theme tokens, supports `light`, `dark`, `system`, and reduced motion, and does not fetch arbitrary scripts or data by default.
- Three.js is local, pinned, and loaded only for 3D artifacts; WebGL failure, hidden/offscreen rendering, and reduced motion have tested fallbacks.
- MP4 is offered only when the active browser recorder supports the required codec; otherwise label and export WebM.
- Preserve existing `ui_block`, `show_widget`, and historic transcript rendering behavior; update `CHANGELOG.md` in the same implementation commit.

## Review Focus

- **Missing tool in run-local capability map:** prompt never tells a model to invoke a visual tool absent from that run; pin with tool availability and executor tests in Task 1.
- **Opaque-origin iframe spoofing or oversized bridge messages:** only the owning frame's initialized port and valid bounded messages are accepted; pin in Task 2.
- **Unverified dashboard data presented as live:** label absent/unmatched source calls as illustrative, show verified source calls and only source-provided freshness time, and route refresh to a normal agent message; pin in Task 3.
- **Unsupported MP4/WebGL and reduced-motion environments:** state the available output/fallback and stop expensive rendering; pin in Tasks 4–5.
- **Old history and replaced artifact replay:** rebuild the latest revision once and retain legacy widget behavior; pin in Tasks 1–2.

---

## File map

| Path | Responsibility |
|---|---|
| `app/agent/schemas/events.py` | Validated rich-artifact event and payload models |
| `app/api/routes/team/webbridge.py` | Explicitly allow or reject forwarding the new event in remote session streams |
| `app/agent/tools/builtin/visualize/visual_artifact.py` | Tool contract, limits, session event emission |
| `app/agent/tools/builtin/visualize/__init__.py`, `app/agent/loader.py`, `app/agent/permission.py`, `app/agent/mode/team/tier_policy.py`, `app/services/memory_stream_store.py` | Export/register tool, preserve permission/tier policy, and allow the event through stream storage |
| `app/agent/hooks/skills.py`, `app/agent/hooks/response_style.py`, `app/agent/mode/team/member.py`, `app/agent/builtin_skills/intelligent-ui/SKILL.md` | Always-on concise capability/selection context and expanded conditional Skill guidance |
| `app/agent/agent_loop/tool_executor.py` | Preserve accurate missing-tool failure semantics and prevent confusing recovery behavior |
| `app/agent/schemas/events.py`, `app/services/stream_envelope.py` | SSE event serialization/validation |
| `web/src/api/types.ts`, `web/src/stores/useTeamStore/sse-reducer.ts`, `web/src/utils/messages.ts` | Frontend event/block contract, live reduction and transcript history reconstruction |
| `web/src/components/BlockRenderer.tsx`, `web/src/components/VisualArtifactRenderer.tsx` | Artifact host shell and kind-specific affordances |
| `web/src/components/VisualArtifactFrame.tsx`, `web/src/lib/visual-artifact-bridge.ts` | Isolated iframe, capability bridge, bounded message parsing |
| `web/src/components/WidgetRenderer.tsx` | Keep legacy widget path compatible; no silent sandbox privilege expansion |
| `web/src/lib/theme.ts`, existing theme/reduced-motion stores/hooks | Bridge current user preference to artifact frame |
| `web/src/__tests__/components/VisualArtifactRenderer.test.tsx`, `VisualArtifactFrame.test.tsx`, existing history and `ui_block` tests | Renderer/theme/security/replay regressions |
| `tests/agent/schemas/test_visual_artifact.py`, `tests/agent/tools/builtin/visualize/test_visual_artifact.py`, `tests/agent/skills/test_skills_hook.py`, `tests/agent/test_agent_loop.py` | Validation, capability availability, tool result and failure behavior |
| `documents/features/intelligent-ui.md`, `documents/features/README.md`, `web/src/help/locales/`, `CHANGELOG.md` | Shipped contract, feature index, user Help, release note |

The first implementation decision is **no database migration**. The current transcript already stores assistant tool-call arguments and `ui_block` reconstructs from those arguments. Add the new tool's history projection to the same pipeline and prove it with reload/replay tests before considering any separate storage model.

## Task 1: Define rich artifact contract and make capability context truthful

**Files:**
- Create: `tests/agent/schemas/test_visual_artifact.py`
- Create: `tests/agent/tools/builtin/visualize/test_visual_artifact.py`
- Modify: `app/agent/schemas/events.py`
- Modify: `app/api/routes/team/webbridge.py`
- Modify: `app/services/stream_envelope.py`
- Create: `app/agent/tools/builtin/visualize/visual_artifact.py`
- Modify: `app/agent/tools/builtin/visualize/__init__.py`
- Modify: `app/agent/loader.py`
- Modify: `app/agent/hooks/skills.py`
- Modify: `app/agent/hooks/response_style.py`
- Modify: `app/agent/mode/team/member.py`
- Modify: `app/agent/builtin_skills/intelligent-ui/SKILL.md`
- Create: `tests/agent/hooks/test_response_style.py`
- Test: `tests/agent/test_loader.py`, `tests/agent/skills/test_skills_hook.py`, `tests/agent/test_agent_loop.py`, `tests/api/test_webbridge.py`

**Interfaces:**
- Produces `VisualArtifactEvent(type="visual_artifact", agent: str, tool_call_id: str, artifact_id: str, kind: Literal["dashboard", "motion", "scene3d"], title: str, summary: str, source_html: str | None, scene: Scene3DSpec | None, sources: list[VisualArtifactSourceRef], duration_ms: int | None, is_final: Literal[True])`; a model validator requires HTML for dashboard/motion, `scene` for scene3d, and `duration_ms` for motion.
- Tool input `VisualArtifactSourceRef` is `{tool_call_id: str, query_summary: str}`. The backend requires each ID to refer to a successful tool result in active session history; the frontend resolves each ID to the saved tool name, arguments and result for transcript replay.
- `Scene3DSpec` carries 1–100 nodes; each node has a unique id, one geometry from `box|sphere|cylinder|torus`, position values in `[-100, 100]`, rotation radians in `[-6.2832, 6.2832]`, positive scale values in `[0.01, 100]`, one semantic theme color (`accent|foreground|muted|success|warning|danger|info`), and an optional label of at most 120 characters. The model supplies no URL, shader, or script.
- Tool signature: `async def visual_artifact(artifact_id: str, kind: Literal["dashboard", "motion", "scene3d"], title: str, summary: str, source_html: str | None = None, scene: dict[str, Any] | None = None, sources: list[VisualArtifactSourceRef] | None = None, duration_ms: int | None = None, _injected: dict[str, Any] | None = None) -> dict[str, Any]`.
- Add always-on concise context that says to judge the user's goal and choose prose/native/rich UI by practical utility, while naming only capabilities present in the active run. Skill metadata uses the comma-separated string `runtime-preload-tools: ui_block,visual_artifact` because current frontmatter metadata values must remain strings; preload the detailed catalog if any listed tool is present and otherwise omit instructions to invoke either missing tool.
- Produces `response_style_directive(style: Literal["simple", "visual"], tool_names: set[str]) -> str`; the Visual directive names `ui_block` and/or `visual_artifact` only when each appears in `tool_names`.

- [x] **Step 1: Write schema/tool/capability tests first**

```python
def test_rejects_unknown_kind_wrong_payload_kind_and_source_over_200000_bytes():
    with pytest.raises(ValidationError):
        VisualArtifactEvent.model_validate({**valid_event(), "kind": "video"})
    with pytest.raises(ValidationError, match="source_html"):
        VisualArtifactEvent.model_validate({**valid_event(), "kind": "scene3d", "scene": valid_scene()})
    with pytest.raises(ValidationError, match="duration_ms"):
        VisualArtifactEvent.model_validate({**valid_event(), "kind": "motion", "duration_ms": None})
    with pytest.raises(ValueError, match="200000 UTF-8 bytes"):
        validate_visual_artifact_source("é" * 100_001)

def test_scene_limits_nodes_and_rejects_urls_or_scripts():
    with pytest.raises(ValidationError):
        Scene3DSpec.model_validate({"nodes": [valid_scene_node(i) for i in range(101)]})
    with pytest.raises(ValidationError):
        Scene3DNode.model_validate({**valid_scene_node(1), "geometry": "https://example.test/model.glb"})
    with pytest.raises(ValidationError):
        Scene3DNode.model_validate({**valid_scene_node(1), "script": "fetch('https://example.test')"})
    with pytest.raises(ValidationError):
        Scene3DSpec.model_validate({"nodes": [valid_scene_node(1), valid_scene_node(1)]})

def test_dashboard_source_ref_requires_tool_call_and_query_summary():
    with pytest.raises(ValidationError):
        VisualArtifactSourceRef.model_validate({"tool_call_id": "call-1"})

async def test_dashboard_source_must_match_a_successful_tool_call_in_active_history():
    result = await visual_artifact(
        **valid_dashboard_args(sources=[{"tool_call_id": "missing-call", "query_summary": "pipeline totals"}]),
        _injected=tool_context(messages=[]),
    )
    assert result["success"] is False
    assert "source tool call" in result["error"]

def test_visual_artifact_description_teaches_task_fit_and_payload_contract():
    assert "dashboard" in visual_artifact.description
    assert "motion" in visual_artifact.description
    assert "3D" in visual_artifact.description
    assert "when" in visual_artifact.description.lower()

def test_motion_duration_is_capped_at_120_seconds():
    with pytest.raises(ValidationError):
        VisualArtifactEvent.model_validate({**valid_event(), "duration_ms": 120_001})

def test_skill_preload_mentions_only_tools_available_in_the_active_run():
    assert "visual_artifact" in render_skill_context(tool_names={"visual_artifact"})
    assert "ui_block" in render_skill_context(tool_names={"ui_block"})
    assert "visual_artifact" not in render_skill_context(tool_names=set())

def test_visual_base_context_names_only_tools_present_in_the_run():
    both = response_style_directive("visual", {"ui_block", "visual_artifact"})
    assert "ui_block" in both and "visual_artifact" in both
    without_artifacts = response_style_directive("visual", set())
    assert "visual_artifact" not in without_artifacts and "ui_block" not in without_artifacts

def test_simple_style_does_not_recommend_visual_tools():
    assert "visual_artifact" not in response_style_directive("simple", {"visual_artifact"})

def test_executor_reports_missing_tool_without_fabricating_success():
    with pytest.raises(ToolNotFoundError, match="Tool 'visual_artifact' not found"):
        await execute_tool_call("visual_artifact", {}, run_tools={})
```

- [x] **Step 2: Run focused tests and confirm the new contract fails**

Run: `uv run pytest tests/agent/schemas/test_visual_artifact.py tests/agent/tools/builtin/visualize/test_visual_artifact.py tests/agent/skills/test_skills_hook.py tests/agent/test_loader.py -q`

Expected: FAIL because the event, tool, registration, and capability-specific context do not exist yet.

- [x] **Step 3: Implement bounded Pydantic models, tool, registry, and truthful context**

```python
class VisualArtifactSourceRef(BaseModel):
    tool_call_id: str = Field(min_length=1, max_length=120)
    query_summary: str = Field(min_length=1, max_length=500)

class Scene3DNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    geometry: Literal["box", "sphere", "cylinder", "torus"]
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]
    scale: tuple[float, float, float]
    color: Literal["accent", "foreground", "muted", "success", "warning", "danger", "info"]
    label: str | None = Field(default=None, max_length=120)

class Scene3DSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[Scene3DNode] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_node_ids(self) -> "Scene3DSpec":
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("3D scene node ids must be unique")
        return self

class VisualArtifactEvent(BaseModel):
    type: Literal["visual_artifact"] = "visual_artifact"
    agent: str
    tool_call_id: str
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    kind: Literal["dashboard", "motion", "scene3d"]
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(max_length=500)
    source_html: str | None = Field(default=None, min_length=1)
    scene: Scene3DSpec | None = None
    sources: list[VisualArtifactSourceRef] = Field(default_factory=list, max_length=12)
    duration_ms: int | None = Field(default=None, ge=1, le=120_000)
    is_final: Literal[True] = True

    @model_validator(mode="after")
    def validate_kind_payload(self) -> "VisualArtifactEvent":
        if self.kind in {"dashboard", "motion"} and (self.source_html is None or self.scene is not None):
            raise ValueError("dashboard and motion require source_html only")
        if self.kind == "scene3d" and (self.scene is None or self.source_html is not None):
            raise ValueError("scene3d requires scene only")
        if self.kind == "motion" and self.duration_ms is None:
            raise ValueError("motion requires duration_ms")
        if self.source_html is not None and len(self.source_html.encode("utf-8")) > 200_000:
            raise ValueError("source_html exceeds 200000 UTF-8 bytes")
        return self
```

Validate each scene node's position in `[-100,100]`, rotation in `[-6.2832,6.2832]`, scale in `[0.01,100]`, unique node IDs, and the listed semantic colors. Resolve every source reference against a successful tool call/result in the active session before emitting the event; reject missing/failed IDs. Push one complete event to the current session stream. Register it only in run modes that deliver its renderer. Extend Skill preload metadata with the comma-separated string `runtime-preload-tools: ui_block,visual_artifact` (frontmatter metadata values are strings), retaining current single-tool metadata compatibility. Add a short always-on goal-and-utility rubric to `response_style.py` that names only active tools; preload the detailed Skill when any declared tool is in the run's actual `state.tool_names`. Bump `member.py`'s `response_style_context_version` from `2` to `3` so cached prefixes receive the changed capability contract.

- [x] **Step 4: Run tests and existing visualize regressions**

Run: `uv run pytest tests/agent/schemas/test_visual_artifact.py tests/agent/tools/builtin/visualize/test_visual_artifact.py tests/agent/skills/test_skills_hook.py tests/agent/test_loader.py tests/agent/tools/builtin/visualize/test_tools.py tests/api/test_webbridge.py -q`

Expected: PASS; existing `ui_block` tool and Skill tests remain unchanged and pass.

## Task 2: Stream, reconstruct, and safely render themed artifacts

**Files:**
- Create: `web/src/lib/visual-artifact-bridge.ts`
- Create: `web/src/components/VisualArtifactFrame.tsx`
- Create: `web/src/components/VisualArtifactRenderer.tsx`
- Modify: `web/src/api/types.ts`
- Create: `web/src/__tests__/components/VisualArtifactFrame.test.tsx`
- Create: `web/src/__tests__/components/VisualArtifactRenderer.test.tsx`
- Modify: `web/src/stores/useTeamStore/sse-reducer.ts`
- Modify: `web/src/utils/messages.ts`
- Modify: `web/src/components/BlockRenderer.tsx`
- Modify: `web/src/components/WidgetRenderer.tsx` only if required to preserve old widget behavior without using it for new artifacts
- Test: existing `web/src/__tests__/utils/messages-history-replace.test.ts`, `BlockRendererArtifacts.test.tsx`, `BlockRenderer.ui-block.test.tsx`

**Interfaces:**
- `parseVisualArtifactMessage(raw: unknown): VisualArtifactPayload | null` checks kind, id, UTF-8 payload length, sources and metadata before the reducer stores it.
- `parseVisualArtifactBridgeMessage(raw: unknown): VisualArtifactBridgeMessage | null` accepts only `{type: "resize", height}`, `{type: "send_prompt", prompt}`, `{type: "playback", currentTimeMs, state}`, and bounded `{type: "export_chunk", mimeType, bytes, final}` messages on the initialized `MessagePort`.
- `VisualArtifactRenderer({ artifact, theme, reducedMotion, onSendPrompt }: Props)` owns toolbar/state and delegates source execution to `VisualArtifactFrame`.

- [x] **Step 1: Add failing reducer, history, theme, and isolation tests**

```ts
it('replays one last artifact revision from persisted tool arguments', async () => {
  const blocks = parseTeamBlocks(historyWithArtifactRevisions('budget', 1, 2))
  expect(blocks.filter((block) => block.type === 'visual_artifact')).toHaveLength(1)
  expect(blocks.find((block) => block.type === 'visual_artifact')?.revision).toBe(2)
})

it('keeps the original transcript position when an artifact id is replaced', () => {
  const blocks = reduceArtifactEvents([textBlock('before'), artifact('budget', 1), textBlock('after'), artifact('budget', 2)])
  expect(blocks.map((block) => block.id)).toEqual(['before', 'budget', 'after'])
  expect(blocks[1]).toMatchObject({ artifactId: 'budget', revision: 2 })
})

it('rejects unknown kinds and source payloads above 200000 UTF-8 bytes', () => {
  expect(parseVisualArtifactMessage({ ...validArtifact(), kind: 'video' })).toBeNull()
  expect(parseVisualArtifactMessage({ ...validArtifact(), sourceHtml: 'é'.repeat(100_001) })).toBeNull()
})

it('creates an iframe without same-origin or privileged allow permissions', () => {
  render(<VisualArtifactFrame artifact={validArtifact()} theme={theme} reducedMotion={false} />)
  expect(screen.getByTitle('Budget')).toHaveAttribute('sandbox', 'allow-scripts')
  expect(screen.getByTitle('Budget')).not.toHaveAttribute('allow')
})

it('ignores global window messages and accepts bounded packets on the transferred port', () => {
  const onSendPrompt = vi.fn()
  const { iframe, port } = renderArtifactFrame({ onSendPrompt })
  window.dispatchEvent(new MessageEvent('message', { source: iframe.contentWindow, data: { type: 'send_prompt', prompt: 'spoof' } }))
  expect(onSendPrompt).not.toHaveBeenCalled()
  port.dispatchMessage({ type: 'send_prompt', prompt: 'Refresh with agent' })
  expect(onSendPrompt).toHaveBeenCalledWith('Refresh with agent')
  expect(parseVisualArtifactBridgeMessage({ type: 'send_prompt', prompt: 'x'.repeat(10_001) })).toBeNull()
})

it('updates theme tokens and reduced-motion state after app preferences change', () => {
  const port = renderArtifactWithTheme('dark', true)
  expect(port.sent).toContainEqual(expect.objectContaining({ type: 'theme', mode: 'dark' }))
  expect(port.sent).toContainEqual(expect.objectContaining({ type: 'preferences', reducedMotion: true }))
})
```

- [x] **Step 2: Run focused frontend tests and confirm they fail**

Run: `cd web; bun run test --run src/__tests__/components/VisualArtifactFrame.test.tsx src/__tests__/components/VisualArtifactRenderer.test.tsx src/__tests__/utils/messages-history-replace.test.ts`

Expected: FAIL because no artifact payload parser, reducer case, or renderer exists.

- [x] **Step 3: Implement event/history projection and isolated host renderer**

```ts
export type VisualArtifactKind = 'dashboard' | 'motion' | 'scene3d'

export interface VisualArtifactPayload {
  artifactId: string
  kind: VisualArtifactKind
  title: string
  summary: string
  sourceHtml: string | null
  scene: Scene3DSpec | null
  sources: Array<{ toolCallId: string; querySummary: string }>
  durationMs: number | null
  revision: number
}
```

Reconstruct from persisted `visual_artifact` tool-call arguments using the same history source as `ui_block`; use `artifact_id` as the stable replacement key. Build a transcript-local `tool_call_id → tool name/arguments/result` map and mark only matching successful tool results as verified dashboard sources. Preserve unmatched references as unverified and label that dashboard illustrative. In the host, create a sandboxed iframe with `sandbox="allow-scripts"` and no `allow` capabilities, then transfer a `MessageChannel` port during initialization. Reject all non-schema/oversize packets. Disable default external fetch and remote script execution in the artifact CSP. On bridge initialization, send the current theme tokens/theme mode and reduced-motion flag; resend when either changes. Preserve the existing `WidgetRenderer` contract for old `widget_delta` and custom UI history.

- [x] **Step 4: Run renderer/history and adjacent legacy tests**

Run: `cd web; bun run test --run src/__tests__/components/VisualArtifactFrame.test.tsx src/__tests__/components/VisualArtifactRenderer.test.tsx src/__tests__/utils/messages-history-replace.test.ts src/__tests__/components/BlockRendererArtifacts.test.tsx src/__tests__/components/BlockRenderer.ui-block.test.tsx`

Expected: PASS with no regressions in widget, `ui_block`, or transcript replay.

## Task 3: Build provenance-first dashboards and refresh handoff

**Files:**
- Create: `web/src/components/visual-artifact/DashboardArtifact.tsx`
- Create: `web/src/__tests__/components/DashboardArtifact.test.tsx`
- Modify: `web/src/components/VisualArtifactRenderer.tsx`
- Modify: `app/agent/builtin_skills/intelligent-ui/SKILL.md`
- Modify: `app/agent/builtin_skills/intelligent-ui/reference/worked-examples.md`
- Test: `tests/agent/tools/builtin/visualize/test_visual_artifact.py`

**Interfaces:**
- `DashboardArtifact({ artifact, sourceCalls, onSendPrompt }: Props)` displays each verified tool-call source, the model-provided query summary beside a link to that call, and its actual saved arguments/result; it never marks a dashboard “live” without verified evidence.
- Refresh action sends `Refresh this dashboard using the same available data sources. Re-run the relevant source tools, update every source timestamp, and replace artifact_id "<artifactId>" in place.` through the existing normal-message callback.

- [x] **Step 1: Add failing dashboard evidence/refresh tests**

```tsx
it('shows the verified source tool, query summary, and retrieval time', () => {
  render(<DashboardArtifact artifact={dashboardWithSource('call-sales-1', 'open opportunities')} sourceCalls={new Map([['call-sales-1', successfulToolCall('mcp_salesforce.query')]])} onSendPrompt={vi.fn()} />)
  expect(screen.getByText('mcp_salesforce.query')).toBeVisible()
  expect(screen.getByText('open opportunities')).toBeVisible()
  expect(screen.getByText(/2026-10-15/)).toBeVisible()
})

it('labels data without provenance as illustrative instead of live', () => {
  render(<DashboardArtifact artifact={dashboardWithoutSources()} onSendPrompt={vi.fn()} />)
  expect(screen.getByText(/Illustrative example/i)).toBeVisible()
  expect(screen.queryByText(/Live data/i)).not.toBeInTheDocument()
})

it('sends refresh through chat and retains the artifact id', async () => {
  const onSendPrompt = vi.fn()
  render(<DashboardArtifact artifact={dashboardWithoutSources('weekly-signups')} onSendPrompt={onSendPrompt} />)
  await userEvent.click(screen.getByRole('button', { name: /Refresh with agent/i }))
  expect(onSendPrompt).toHaveBeenCalledWith(expect.stringContaining('weekly-signups'))
})
```

- [x] **Step 2: Run dashboard tests and confirm expected failures**

Run: `cd web; bun run test --run src/__tests__/components/DashboardArtifact.test.tsx`

Expected: FAIL because no dashboard host or refresh action exists.

- [x] **Step 3: Implement dashboard provenance, empty-state, and refresh handoff**

Render verified sources in an accessible expandable provenance panel alongside the generated visualization. Show the actual linked tool name and its saved arguments/result; do not invent a refresh timestamp. If no referenced tool call can be verified, label the data “Illustrative example.” Add the Refresh with agent action and adapt the Skill to require actual tool/file inspection and source call ids before claiming a data-backed dashboard.

- [x] **Step 4: Run dashboard and tool validation tests**

Run: `cd web; bun run test --run src/__tests__/components/DashboardArtifact.test.tsx src/__tests__/components/VisualArtifactRenderer.test.tsx`; then `uv run pytest tests/agent/tools/builtin/visualize/test_visual_artifact.py -q`

Expected: PASS; refreshing sends a chat message and has no hidden background polling.

## Task 4: Add motion timeline, accessible controls, and honest media export

**Files:**
- Create: `web/src/components/visual-artifact/MotionArtifact.tsx`
- Create: `web/src/lib/visual-artifact-export.ts`
- Create: `web/src/__tests__/components/MotionArtifact.test.tsx`
- Create: `web/src/__tests__/lib/visual-artifact-export.test.ts`
- Modify: `web/src/components/VisualArtifactRenderer.tsx`
- Modify: `web/src/lib/visual-artifact-bridge.ts`
- Modify: `app/agent/builtin_skills/intelligent-ui/SKILL.md`
- Modify: `app/agent/builtin_skills/intelligent-ui/reference/worked-examples.md`

**Interfaces:**
- `MotionArtifact({ artifact, port, reducedMotion, onExport }: Props)` presents Play/Pause, Restart, seek slider, elapsed/total time, captions/summary, and an export action.
- `getSupportedExportMimeType(MediaRecorderCtor: typeof MediaRecorder): string | null` selects a actually supported MP4 MIME first, then WebM, or returns `null`.
- `exportCanvas(canvas: HTMLCanvasElement, mimeType: string): Promise<Blob>` captures only after a user action and returns the exact recorder MIME.

- [x] **Step 1: Add failing motion controls and recorder tests**

```ts
it('sends play, pause, restart, and seek commands through the artifact port', async () => {
  const port = createTestPort()
  render(<MotionArtifact artifact={motionArtifact()} port={port} reducedMotion={false} onExport={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: 'Play' }))
  await userEvent.click(screen.getByRole('button', { name: 'Pause' }))
  await userEvent.click(screen.getByRole('button', { name: 'Restart' }))
  await userEvent.click(screen.getByRole('slider', { name: /timeline/i }))
  expect(port.messages.map((message) => message.type)).toEqual(['play', 'pause', 'restart', 'seek'])
})

it('starts paused when reduced motion is enabled', () => {
  render(<MotionArtifact artifact={motionArtifact()} port={createTestPort()} reducedMotion onExport={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Play' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Pause' })).toBeDisabled()
})

it('selects only a recorder format the browser reports as supported', () => {
  const recorder = { isTypeSupported: (mime: string) => mime === 'video/webm;codecs=vp9' } as typeof MediaRecorder
  expect(getSupportedExportMimeType(recorder)).toBe('video/webm;codecs=vp9')
})

it('stops every canvas capture track after export completes', async () => {
  const tracks = [mockTrack(), mockTrack()]
  await exportCanvas(mockCanvasWithTracks(tracks), 'video/webm')
  expect(tracks.every((track) => track.stop.mock.calls.length === 1)).toBe(true)
})
```

- [x] **Step 2: Run motion tests and confirm they fail**

Run: `cd web; bun run test --run src/__tests__/components/MotionArtifact.test.tsx src/__tests__/lib/visual-artifact-export.test.ts`

Expected: FAIL because motion controls and export helpers are not implemented.

- [x] **Step 3: Implement playback host and canvas recording bridge**

Use the frame's transferred port for bounded control messages and recorder chunks; do not pass export data over wildcard `window.postMessage`. Start recording only on the user's export action; call `canvas.captureStream(30)`, finalize a Blob with the recorder's actual MIME; stop all tracks after success, error, timeout, or unmount. Download the resulting file with an extension matching the MIME. When no supported recorder format exists or the marked canvas is absent, disable export with an explanation. Keep agent revisions in place by `artifact_id`, and stop playback before replacing source.

- [x] **Step 4: Run motion, bridge, and production frontend checks**

Run: `cd web; bun run test --run src/__tests__/components/MotionArtifact.test.tsx src/__tests__/lib/visual-artifact-export.test.ts src/__tests__/components/VisualArtifactFrame.test.tsx; bun run typecheck; bun run lint; bun run build`

Expected: PASS; unsupported recorder environments have no mislabeled MP4 download.

## Task 5: Add a lazy, bounded 3D scene runtime and fallback

**Files:**
- Modify: `web/package.json`, `web/bun.lock` (install the selected locally pinned Three.js version only after checking the current version and license)
- Create: `web/src/components/visual-artifact/Scene3DArtifact.tsx`
- Create: `web/src/lib/visual-artifact-three-runtime.ts`
- Create: `web/src/__tests__/components/Scene3DArtifact.test.tsx`
- Create: `web/src/__tests__/lib/visual-artifact-three-runtime.test.ts`
- Modify: `web/src/components/VisualArtifactRenderer.tsx`
- Modify: `app/agent/builtin_skills/intelligent-ui/SKILL.md`

**Interfaces:**
- `Scene3DArtifact({ artifact, reducedMotion, visible }: Props)` renders the validated 1–100-node primitive `Scene3DSpec` in an accessible canvas with labeled camera reset and keyboard/pointer controls.
- `createSceneRuntime(canvas: HTMLCanvasElement, scene: Scene3DSpec, options: { reducedMotion: boolean; maxPixelRatio: number }): SceneRuntime` owns and disposes renderer, scene, camera, animation loop, and GPU resources.
- `SceneRuntime` exposes `setVisible(visible: boolean): void`, `setReducedMotion(enabled: boolean): void`, and `dispose(): void`.

- [x] **Step 1: Add failing lazy-load, fallback, visibility, and disposal tests**

```ts
it('does not import Three.js for non-scene artifacts', async () => {
  render(<VisualArtifactRenderer artifact={dashboardArtifact()} theme={theme} reducedMotion={false} />)
  expect(threeRuntimeImport).not.toHaveBeenCalled()
})

it('shows a labeled 2D fallback when WebGL context creation fails', async () => {
  mockWebGLContext(null)
  render(<Scene3DArtifact artifact={scene3dArtifact()} reducedMotion={false} visible />)
  expect(await screen.findByText(/3D is unavailable/i)).toBeVisible()
  expect(screen.getByRole('img', { name: /static scene/i })).toBeVisible()
})

it('pauses animation while offscreen and when reduced motion is enabled', () => {
  const runtime = createSceneRuntime(testCanvas(), validScene(), { reducedMotion: true, maxPixelRatio: 2 })
  runtime.setVisible(false)
  expect(mockAnimationLoop).toHaveBeenLastCalledWith(null)
})

it('disposes renderer and scene GPU resources when released', () => {
  const runtime = createSceneRuntime(testCanvas(), validScene(), { reducedMotion: false, maxPixelRatio: 2 })
  runtime.dispose()
  expect(mockRenderer.dispose).toHaveBeenCalledOnce()
  expect(mockSceneGeometry.dispose).toHaveBeenCalledOnce()
})
```

- [x] **Step 2: Run 3D tests and confirm they fail**

Run: `cd web; bun run test --run src/__tests__/components/Scene3DArtifact.test.tsx src/__tests__/lib/visual-artifact-three-runtime.test.ts`

Expected: FAIL because no lazy 3D runtime exists.

- [x] **Step 3: Implement lazy local runtime with bounded render settings**

Pin Three.js to an exact version in `web/package.json`, dynamically import it only from the `scene3d` branch, and build the runtime around the validated `Scene3DSpec`; never eval model-supplied code or load model-supplied URLs. Cap device pixel ratio at `2`, size the canvas to at most `1920 × 1080`, render at no more than `30 fps`, stop its animation loop while hidden/offscreen, and avoid autoplay under reduced motion. If canvas/WebGL/context creation is unavailable, render the artifact summary and a static/2D scene fallback. Add accessible reset and keyboard controls. Update Skill guidance to choose 3D only when spatial inspection has practical value.

- [x] **Step 4: Run 3D, motion-canvas, and build checks**

Run: `cd web; bun run test --run src/__tests__/components/Scene3DArtifact.test.tsx src/__tests__/lib/visual-artifact-three-runtime.test.ts src/__tests__/components/MotionArtifact.test.tsx; bun run typecheck; bun run lint; bun run build`

Expected: PASS; 3D dependency remains out of initial route chunks and is disposed after use.

## Task 6: Add model-judgment smoke/evaluation coverage

**Files:**
- Create: `tests/fixtures/intelligent_ui/rich_artifact_cases.json`
- Create: `tests/agent/test_intelligent_ui_eval.py`
- Create: `scripts/smoke_intelligent_ui.py`
- Modify: `app/agent/builtin_skills/intelligent-ui/reference/worked-examples.md`
- Modify: `documents/features/intelligent-ui.md`

**Interfaces:**
- Fixture row shape: `{id: str, prompt: str, expected_choice: Literal["prose", "ui_block", "dashboard", "motion", "scene3d"], required_evidence: list[str], forbidden_choices: list[str]}`.
- Deterministic offline test validates fixture/schema coverage, tool registration and prompt-context conditions. A separate opt-in live smoke invokes MiMo and, when selected, one other configured model; it records selected tool/kind, schema validity, verified source-link presence, and whether the turn completes without tool-not-found; it does not snapshot private reasoning.

- [x] **Step 1: Write fixture validation and capability-regression tests**

```python
def test_visual_eval_cases_cover_prose_native_dashboard_motion_3d_and_missing_tool():
    cases = load_visual_eval_cases()
    assert {case.expected_choice for case in cases} == {"prose", "ui_block", "dashboard", "motion", "scene3d"}
    assert any("visual_artifact" in case.forbidden_choices for case in cases if case.id == "missing_capability")

def test_case_contract_contains_intent_examples_not_runtime_keyword_rules():
    cases = load_visual_eval_cases()
    assert all(case.prompt.strip() for case in cases)
    assert all(case.expected_choice in EXPECTED_CHOICES for case in cases)
    assert "keyword_router" not in read_eval_fixture_text()

def test_live_smoke_is_opt_in_and_records_only_outcomes_and_tool_quality():
    assert live_smoke_requires_explicit_flag()
    assert LIVE_SMOKE_FIELDS == {"case_id", "model_id", "tool", "kind", "payload_bytes", "has_provenance", "status"}
```

- [x] **Step 2: Run the offline evaluation tests and verify fixture gaps fail**

Run: `uv run pytest tests/agent/test_intelligent_ui_eval.py -q`

Expected: FAIL until the cases cover all expected choices and unavailable-tool behavior.

- [x] **Step 3: Add a durable task-intent fixture set and opt-in smoke entry point**

Include the seven prompts from the spec's Evaluation Set. Keep labels as expected outcomes for regression analysis, not runtime routing rules. The live smoke must require explicit local provider configuration and emit only prompt case id, model/provider id, selected tool/kind, validated artifact sizes, whether a source link was verified, and completion/error status; never log raw chain-of-thought or private reasoning fields. Support `--models xiaomi:mimo-v2.6-flash --compare-with-configured` to select one other configured model without exposing provider secrets.

- [x] **Step 4: Run offline eval and, when configured, live model smoke**

Run: `uv run pytest tests/agent/test_intelligent_ui_eval.py tests/agent/skills/test_skills_hook.py tests/agent/tools/builtin/visualize/test_visual_artifact.py -q`

Optional live run: `uv run python scripts/smoke_intelligent_ui.py --models xiaomi:mimo-v2.6-flash --compare-with-configured --cases tests/fixtures/intelligent_ui/rich_artifact_cases.json`

Expected: offline tests PASS. Report live model calls as observational evidence and do not make them a mandatory CI test.

## Task 7: Update product documentation/help and complete verification

**Files:**
- Modify: `documents/features/intelligent-ui.md`
- Modify: `documents/features/README.md`
- Modify: `web/src/help/locales/en.ts`, `web/src/help/locales/vi.ts`, `web/src/help/locales/ja.ts`
- Test: `web/src/__tests__/help/search.test.ts`
- Modify: `CHANGELOG.md`
- Test: `uv run python scripts/validate_skills.py --strict-warnings`, targeted backend/frontend tests listed below

- [x] **Step 1: Add Help-key and feature-doc acceptance checks**

```ts
it('describes dashboard provenance, motion export fallback, 3D and theme matching in Help', () => {
  const article = getHelpArticle('settings-safety', 'en')
  const text = article?.blocks.flatMap((block) => {
    if (block.type === 'p') return [block.text]
    if (block.type === 'tips') return block.items
    if (block.type === 'callout') return [block.title, block.text]
    if (block.type === 'heading') return [block.text]
    if (block.type === 'code') return [block.code]
    if (block.type === 'table') return block.rows.flat()
    return []
  }).join(' ') ?? ''
  expect(text).toMatch(/dashboard/i)
  expect(text).toMatch(/source|provenance/i)
  expect(text).toMatch(/motion|animation/i)
  expect(text).toMatch(/WebM|MP4/i)
  expect(text).toMatch(/3D/i)
  expect(text).toMatch(/dark|theme/i)
})
```

- [x] **Step 2: Run the Help test and Skill validator to confirm documentation is incomplete**

Run: `cd web; bun run test --run src/__tests__/help/search.test.ts`; then `cd ..; uv run python scripts/validate_skills.py --strict-warnings`

Expected: the new Help assertion fails until copy is added; the existing Skill may pass validation before its updated guidance.

- [x] **Step 3: Document shipped boundaries, update the feature index and changelog**

Document which work uses `ui_block` vs `visual_artifact`, how theme/permissions/data provenance/export fallback behave, the no-background-refresh contract, capability availability, and limitations. Update the feature catalogue and in-app Help in all required locales. Add one concise user-facing entry under the existing `CHANGELOG.md` `[Unreleased]` heading.

- [x] **Step 4: Run focused end-to-end verification and inspect the combined diff**

Run:

```powershell
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run ty check app/
uv run pytest tests/agent/schemas/test_visual_artifact.py tests/agent/tools/builtin/visualize/test_visual_artifact.py tests/agent/skills/test_skills_hook.py tests/agent/test_loader.py tests/agent/test_agent_loop.py tests/agent/test_intelligent_ui_eval.py -q
uv run python scripts/validate_skills.py --strict-warnings
Set-Location web
bun run lint
bun run typecheck
bun run test --run src/__tests__/components/VisualArtifactFrame.test.tsx src/__tests__/components/VisualArtifactRenderer.test.tsx src/__tests__/components/DashboardArtifact.test.tsx src/__tests__/components/MotionArtifact.test.tsx src/__tests__/components/Scene3DArtifact.test.tsx src/__tests__/utils/messages-history-replace.test.ts src/__tests__/components/BlockRendererArtifacts.test.tsx src/__tests__/components/BlockRenderer.ui-block.test.tsx
bun run build
```

Expected: all focused checks pass; `git diff --check` is clean; `CHANGELOG.md` describes the user-facing change; existing tool-call history and legacy UI renderers remain covered. Run a live MiMo smoke and visual manual inspection with light, dark, system, reduced motion, unavailable WebGL, and export MIME fallback before calling the release candidate ready.
