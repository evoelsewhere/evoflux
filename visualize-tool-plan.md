# Implementation Plan: Built-in Visualize Tool

## Overview
Build a native visualize tool for EvoFlux that renders interactive HTML widgets inline in conversations, similar to Claude's `visualize:show_widget` feature. The tool will support progressive streaming rendering with DOM diffing for smooth UX.

## Architecture Decisions

1. **Built-in Tools**: Create `visualize_read_me` and `show_widget` as native Python tools in `app/agent/tools/builtin/`
2. **New SSE Event**: Add `WidgetDeltaEvent` for streaming partial HTML to frontend
3. **Frontend Component**: Create `WidgetRenderer.tsx` with morphdom for DOM diffing
4. **Design Guidelines**: Lazy-load guidelines by module (interactive, chart, mockup, art, diagram)
5. **CSP Security**: Strict Content Security Policy for CDN allowlist

## Task List

### Phase 1: Backend Foundation

#### Task 1: Create Widget Event Schema
**Description:** Add new SSE event types for widget streaming.

**Acceptance criteria:**
- [ ] `WidgetDeltaEvent` added to `app/agent/schemas/events.py`
- [ ] Event includes: agent, tool_call_id, html, metadata
- [ ] Event registered in `AnyStreamEvent` union

**Verification:**
- [ ] Python syntax check passes
- [ ] Import works correctly

**Dependencies:** None

**Files likely touched:**
- `app/agent/schemas/events.py`
- `app/services/stream_envelope.py`

**Estimated scope:** XS

---

#### Task 2: Create Design Guidelines Module
**Description:** Implement lazy-loading design guidelines system.

**Acceptance criteria:**
- [ ] Guidelines organized by module (interactive, chart, mockup, art, diagram)
- [ ] `get_guidelines(modules)` function returns combined guidelines
- [ ] Guidelines follow Claude's design system (CSS variables, dark mode, streaming-first)

**Verification:**
- [ ] Unit test for guidelines loading
- [ ] Guidelines content matches Claude's pattern

**Dependencies:** None

**Files likely touched:**
- `app/agent/tools/builtin/visualize/guidelines.py` (new)

**Estimated scope:** M

---

#### Task 3: Create `visualize_read_me` Tool
**Description:** Tool that returns design guidelines by module.

**Acceptance criteria:**
- [ ] Tool accepts `modules` parameter (list of strings)
- [ ] Returns guidelines text for requested modules
- [ ] Tool registered in builtin tools

**Verification:**
- [ ] Tool can be called via `tool.arun(modules=["interactive"])`
- [ ] Returns valid guidelines text

**Dependencies:** Task 2

**Files likely touched:**
- `app/agent/tools/builtin/visualize/__init__.py` (new)
- `app/agent/tools/builtin/visualize/read_me.py` (new)

**Estimated scope:** S

---

#### Task 4: Create `show_widget` Tool
**Description:** Tool that renders HTML widget with streaming support.

**Acceptance criteria:**
- [ ] Tool accepts: title, loading_messages, widget_code
- [ ] Pushes `WidgetDeltaEvent` for partial HTML during streaming
- [ ] Returns tool result with widget metadata

**Verification:**
- [ ] Tool can be called and emits events
- [ ] Frontend receives streaming updates

**Dependencies:** Task 1, Task 3

**Files likely touched:**
- `app/agent/tools/builtin/visualize/show_widget.py` (new)

**Estimated scope:** M

---

### Checkpoint: Backend Tools
- [ ] Both tools registered and callable
- [ ] Events emit correctly
- [ ] Guidelines load properly

---

### Phase 2: Frontend Integration

#### Task 5: Add Widget Event Handler
**Description:** Handle `widget_delta` events in SSE reducer.

**Acceptance criteria:**
- [ ] `widget_delta` case added to `sse-reducer.ts`
- [ ] Updates widget HTML in state
- [ ] Triggers re-render

**Verification:**
- [ ] Event received and processed
- [ ] State updates correctly

**Dependencies:** Task 1

**Files likely touched:**
- `web/src/stores/useTeamStore/sse-reducer.ts`

**Estimated scope:** S

---

#### Task 6: Create WidgetRenderer Component
**Description:** React component for rendering widgets with morphdom.

**Acceptance criteria:**
- [ ] Renders HTML in sandboxed container
- [ ] Uses morphdom for DOM diffing
- [ ] Supports progressive streaming
- [ ] Handles script execution

**Verification:**
- [ ] Component renders HTML correctly
- [ ] Streaming updates are smooth
- [ ] Scripts execute properly

**Dependencies:** Task 5

**Files likely touched:**
- `web/src/components/WidgetRenderer.tsx` (new)

**Estimated scope:** M

---

#### Task 7: Integrate WidgetRenderer in ToolCall
**Description:** Show widget inline when `show_widget` tool is called.

**Acceptance criteria:**
- [ ] `show_widget` tool call renders WidgetRenderer
- [ ] Widget appears inline in conversation
- [ ] Loading state shows during streaming

**Verification:**
- [ ] Widget renders inline
- [ ] Streaming works end-to-end

**Dependencies:** Task 6

**Files likely touched:**
- `web/src/components/ToolCall/display.tsx`
- `web/src/components/ToolCall/index.tsx`

**Estimated scope:** M

---

### Checkpoint: Frontend Integration
- [ ] Widget renders inline in conversation
- [ ] Streaming updates are smooth
- [ ] Scripts execute properly

---

### Phase 3: Polish & Security

#### Task 8: Add CSP Configuration
**Description:** Configure Content Security Policy for widget rendering.

**Acceptance criteria:**
- [ ] CDN allowlist configured (cdnjs, jsdelivr, unpkg, esm.sh)
- [ ] Scripts only execute from allowed sources
- [ ] No unsafe-eval except for specific cases

**Verification:**
- [ ] CSP headers correct
- [ ] External libraries load correctly

**Dependencies:** Task 6

**Files likely touched:**
- `web/src/components/WidgetRenderer.tsx`

**Estimated scope:** S

---

#### Task 9: Add Dark Mode Support
**Description:** Ensure widgets work in both light and dark modes.

**Acceptance criteria:**
- [ ] CSS variables adapt to theme
- [ ] Widget background transparent
- [ ] Text colors appropriate

**Verification:**
- [ ] Widget looks good in light mode
- [ ] Widget looks good in dark mode

**Dependencies:** Task 6

**Files likely touched:**
- `web/src/components/WidgetRenderer.tsx`
- `app/agent/tools/builtin/visualize/guidelines.py`

**Estimated scope:** S

---

#### Task 10: Add Error Handling
**Description:** Handle widget rendering failures gracefully.

**Acceptance criteria:**
- [ ] Invalid HTML shows error message
- [ ] Script errors caught and displayed
- [ ] Network failures handled

**Verification:**
- [ ] Invalid HTML shows error
- [ ] Script errors displayed

**Dependencies:** Task 6

**Files likely touched:**
- `web/src/components/WidgetRenderer.tsx`

**Estimated scope:** S

---

### Checkpoint: Complete
- [ ] All acceptance criteria met
- [ ] Widget renders correctly
- [ ] Streaming works smoothly
- [ ] Dark mode supported
- [ ] Error handling works

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Streaming performance | Medium | Debounce updates, use morphdom |
| XSS vulnerabilities | High | Strict CSP, sanitize HTML |
| Script execution issues | Medium | Sandbox scripts, catch errors |
| CDN availability | Low | Fallback to static rendering |

## Open Questions
- Should we support `sendPrompt()` function for widget-to-chat communication?
- Should widgets be persistent across turns or ephemeral?
- Should we add a widget gallery for common patterns?

## Timeline
- **Phase 1**: 2-3 days (Backend)
- **Phase 2**: 3-4 days (Frontend)
- **Phase 3**: 2-3 days (Polish)
- **Total**: 1-2 weeks
