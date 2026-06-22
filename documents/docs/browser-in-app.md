# Browser-in-App — Native Live Browser Viewer

> **Status:** Implemented (M1–M6 complete)  
> **Target:** v1.60.0  
> **Owner:** TBD  
> **Depends on:** `browser-use` (already in `pyproject.toml`), `browser_use` built-in tool

## Problem

When the agent calls `browser_use`, the user only sees text results in the chat.
There is no way to watch the browser navigate, click, or fill forms in real time.
For complex multi-step web tasks (research, form filling, scraping), the user
cannot verify what the agent is doing until the final text result appears.

## Goal

Embed a **live browser viewport** inside the EvoFlux app. When `browser_use` is
active, a "See Browser" button appears in the chat tool result. Clicking it opens
a side panel with a real-time view of the Chromium browser the agent is
controlling — pages load, clicks happen, forms fill, all visible live.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Tauri Shell (desktop/src-tauri)                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  React Frontend (web/src)                             │  │
│  │  ┌──────────────┐  ┌──────────────────────────────┐   │  │
│  │  │  Chat View    │  │  BrowserViewer Panel         │   │  │
│  │  │  (AgentView)  │  │  ┌────────────────────────┐  │   │  │
│  │  │              │  │  │ <webview> or <iframe>   │  │   │  │
│  │  │  [See Browser]│──│  │ pointing at CDP URL    │  │   │  │
│  │  │   button     │  │  │ http://127.0.0.1:PORT  │  │   │  │
│  │  └──────────────┘  │  └────────────────────────┘  │   │  │
│  │                     └──────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────────┘  │
│                           │ SSE: browser_session event      │
│                           ▼                                 │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  FastAPI Backend (app/)                               │  │
│  │  ┌─────────────────┐  ┌────────────────────────────┐  │  │
│  │  │ browser_use_tool │  │ /api/team/{sid}/browser    │  │  │
│  │  │                 │  │ (CDP URL + status endpoint) │  │  │
│  │  │ BrowserSession  │──│                             │  │  │
│  │  │ (headless=False)│  └────────────────────────────┘  │  │
│  │  └─────────────────┘                                   │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Key Insight: CDP Forwarding

`browser-use`'s `BrowserSession` wraps Playwright which launches Chromium with
a CDP WebSocket endpoint. By launching with `--remote-debugging-port=PORT`
(or extracting the CDP URL from the session), we can expose it to the frontend.

The frontend renders the live browser via one of:
1. **Tauri `<webview>`** — native webview pointing at the CDP URL (best perf)
2. **`<iframe>` with Playwright's browser UI** — simpler, works in dev mode
3. **CDP screencast via WebSocket** — frame-by-frame screenshots streamed to a
   `<canvas>` (most portable, works everywhere)

**Recommended: Option 3 (CDP screencast)** — works in both Tauri and web,
no CORS issues, no need to expose Chromium's debugging port to the network.

---

## Implementation Plan

### Phase 1: Backend — CDP URL + Screencast API

#### 1.1 Expose CDP endpoint from BrowserSession

**File:** `app/agent/tools/builtin/browser_use_tool.py`

- When creating `BrowserSession`, configure a fixed CDP port
  (e.g., `--remote-debugging-port=9222` via `args` in `BrowserProfile`)
- Store the CDP WebSocket URL in `_sessions` alongside the session
- Add `_get_cdp_url(state)` helper

```python
# In _get_session():
from browser_use import BrowserProfile
profile = BrowserProfile(
    headless=False,  # visible for debugging; headless for production
    args=[f"--remote-debugging-port={cdp_port}"],
)
session = BrowserSession(browser_profile=profile)
```

#### 1.2 New API endpoint: browser session info

**File:** `app/api/routes/team/browser.py` (new)

```
GET /api/team/{session_id}/browser
```

Response:
```json
{
  "active": true,
  "cdp_url": "ws://127.0.0.1:9222/devtools/browser/...",
  "cdp_http": "http://127.0.0.1:9222",
  "current_url": "https://example.com",
  "current_title": "Example Domain",
  "tabs": [
    {"index": 0, "url": "https://example.com", "title": "Example Domain"}
  ]
}
```

#### 1.3 New SSE event: `browser_session`

**File:** `app/agent/schemas/events.py` (add event type)

```python
class BrowserSessionEvent(BaseModel):
    type: Literal["browser_session"] = "browser_session"
    agent: str
    active: bool
    cdp_url: str | None = None
    current_url: str | None = None
    current_title: str | None = None
    action: str | None = None  # "started", "navigated", "stopped", etc.
```

Emitted by `browser_use_tool.py` after every action that changes browser state.

#### 1.4 CDP Screencast proxy endpoint

**File:** `app/api/routes/team/browser.py`

```
GET /api/team/{session_id}/browser/screencast
```

Proxies the CDP screencast WebSocket to the frontend. The backend connects to
Chromium's CDP WebSocket and forwards `Page.screencastFrame` events as binary
frames (JPEG/PNG) over a WebSocket to the frontend.

Alternative: Use Playwright's built-in screenshot streaming via a dedicated
WebSocket endpoint that polls `page.screenshot()` at ~5fps.

---

### Phase 2: Frontend — BrowserViewer Component

#### 2.1 BrowserViewer panel component

**File:** `web/src/components/BrowserViewer/index.tsx` (new)

```
┌─────────────────────────────────────────┐
│ Browser                    [↗ Popout] [X]│
├─────────────────────────────────────────┤
│ ┌─────────────────────────────────────┐ │
│ │                                     │ │
│ │   Live browser viewport             │ │
│ │   (WebSocket screencast canvas)     │ │
│ │                                     │ │
│ │                                     │ │
│ └─────────────────────────────────────┘ │
│ ┌─────────────────────────────────────┐ │
│ │ ← → ⟳  https://example.com         │ │
│ └─────────────────────────────────────┘ │
│ Tabs: [0: Example Domain] [1: Google]   │
└─────────────────────────────────────────┘
```

- Opens as a **Sheet** (slide-in from right) or replaces the right side panel
- Connects to `/api/team/{sessionId}/browser/screencast` WebSocket
- Renders frames on a `<canvas>` element at native refresh rate
- URL bar shows current page URL (read-only, for display)
- Tab list shows all open tabs with click-to-switch
- Back/forward/refresh buttons (send actions via `browser_use` tool)
- "Popout" button opens in a new Tauri window (optional Phase 3)

#### 2.2 "See Browser" button in ToolCall component

**File:** `web/src/components/ToolCall/index.tsx`

When `toolName === "browser_use"` and the tool is running or just completed:
- Show a floating "See Browser" button (eye icon) on the tool call row
- Clicking it opens the BrowserViewer panel
- Button pulses/animates while browser is actively navigating

**File:** `web/src/components/ToolCall/display.tsx`

Add `browser_use` to `getToolDisplay()`:
- Header: Show action summary (e.g., "Navigating to example.com", "Clicking login button")
- Args: Show simplified action list (not raw JSON)

#### 2.3 BrowserViewer state management

**File:** `web/src/stores/useBrowserStore.ts` (new, or extend `useUIStore`)

```typescript
interface BrowserState {
  active: boolean
  cdpUrl: string | null
  currentUrl: string | null
  currentTitle: string | null
  tabs: Array<{ index: number; url: string; title: string }>
  panelOpen: boolean
}

// Actions
openPanel: () => void
closePanel: () => void
updateFromSSE: (data: BrowserSessionEvent) => void
```

#### 2.4 SSE integration

**File:** `web/src/stores/useTeamStore/sse-reducer.ts`

Add handler for `browser_session` event type:
```typescript
case 'browser_session':
  useBrowserStore.getState().updateFromSSE(data)
  break
```

---

### Phase 3: Tauri Native Integration (Optional Enhancement)

#### 3.1 Native webview via Tauri

Instead of CDP screencast, use Tauri's `<webview>` API to embed a native
Chromium view pointing at the CDP URL. This gives:
- Native performance (no JPEG compression)
- Real mouse/keyboard interaction (user can take over)
- DevTools access

**File:** `desktop/src-tauri/src/main.rs`

Add Tauri command:
```rust
#[tauri::command]
async fn open_browser_view(url: String, label: String) -> Result<(), String> {
    // Create a new webview pointing at the CDP URL
}
```

#### 3.2 Split-view layout

Add a new view mode `'browser'` to the existing `VIEW_MODES` system in
`TeamChatView`. The layout becomes:

```
┌──────────────────┬──────────────────┐
│  Chat (left)     │  Browser (right) │
│  50% width       │  50% width       │
│                  │                  │
│  AgentView       │  BrowserViewer   │
│                  │  (native webview)│
└──────────────────┴──────────────────┘
```

---

## Data Flow

```
1. Agent calls browser_use tool
   └→ browser_use_tool.py starts BrowserSession
   └→ Emits SSE: browser_session { active: true, action: "started" }
   └→ Frontend: "See Browser" button appears on tool call

2. User clicks "See Browser"
   └→ useBrowserStore.openPanel()
   └→ BrowserViewer mounts, connects WebSocket to /browser/screencast
   └→ Canvas renders live frames

3. Agent navigates/clicks/extracts
   └→ browser_use_tool.py executes action
   └→ Emits SSE: browser_session { action: "navigated", current_url: "..." }
   └→ Frontend: URL bar updates, canvas continues streaming

4. Agent finishes / calls stop
   └→ browser_use_tool.py closes session
   └→ Emits SSE: browser_session { active: false, action: "stopped" }
   └→ Frontend: "See Browser" button fades, panel shows "Browser closed"
```

---

## Files to Create/Modify

### New files
| File | Purpose |
|------|---------|
| `app/api/routes/team/browser.py` | Browser status REST + screencast WebSocket endpoint |
| `web/src/components/BrowserViewer/index.tsx` | BrowserViewer panel (URL bar, nav, tabs, overlays) |
| `web/src/components/BrowserViewer/ScreencastCanvas.tsx` | WebSocket canvas renderer with `send()` ref |

### Modified files
| File | Change |
|------|--------|
| `app/agent/tools/builtin/browser_use_tool.py` | CDP URL extraction, SSE emission, `get_browser_page/session` accessors |
| `app/agent/schemas/events.py` | Added `BrowserSessionEvent` |
| `app/services/stream_envelope.py` | Added `BrowserSessionEvent` to `AnyStreamEvent` |
| `app/services/memory_stream_store.py` | `browser_session` state tracking + reconnect replay |
| `app/api/routes/team/__init__.py` | Registered `browser.router` |
| `web/src/api/types.ts` | Added `'browser_session'` to `SSEEventType` |
| `web/src/api/client/team.ts` | Added `getBrowserSession()` API client |
| `web/src/stores/useTeamStore/types.ts` | Added `BrowserSessionInfo`, `BrowserTabInfo` |
| `web/src/stores/useTeamStore/sse-reducer.ts` | Handle `browser_session` SSE event |
| `web/src/stores/useTeamStore/index.ts` | Initialize `browserSession: null` |
| `web/src/stores/useUIStore.ts` | Added `browserOpen`, `toggleBrowser`, `closeBrowser` |
| `web/src/components/ToolCall/index.tsx` | "See Browser" button on `browser_use` calls |
| `web/src/components/ToolCall/display.tsx` | Custom display for `browser_use` actions |
| `web/src/components/ToolResult.tsx` | `BrowserUseResult` renderer |
| `web/src/components/TeamChatView/index.tsx` | BrowserViewer panel integration |
| `desktop/src-tauri/src/main.rs` | `app_open_browser_devtools` Tauri command |
| `desktop/src-tauri/capabilities/default.json` | Added `allow-app-open-browser-devtools` |

---

## Screencast Implementation Detail

The recommended approach is a **backend-mediated CDP screencast**:

```
Browser (Chromium)
  │ CDP WebSocket (internal, localhost:9222)
  │ Page.startScreencast({ format: 'jpeg', quality: 60, maxWidth: 1280 })
  │ Page.screencastFrame events
  ▼
Backend (FastAPI)
  │ /api/team/{sid}/browser/screencast (WebSocket)
  │ Connects to CDP, forwards frames as binary messages
  │ Also sends JSON control messages: { "url": "...", "tabs": [...] }
  ▼
Frontend (React)
  │ WebSocket client → Canvas 2D context
  │ drawImage(blob) at requestAnimationFrame rate
```

**Why not direct CDP from frontend?**
- Chromium's CDP WebSocket is on localhost only, not accessible from a web page
- CORS/origin restrictions prevent direct WebSocket from frontend
- Backend proxy gives us control over frame rate, compression, and access control

**Frame rate:** Target 5fps for screencast (sufficient for watching navigation).
The agent's actions are not video — they're discrete page changes. 5fps keeps
bandwidth reasonable (~500KB/s at 1280x720 JPEG quality 60).

---

## Security Considerations

1. **CDP port binding:** Bind to `127.0.0.1` only (never `0.0.0.0`)
2. **Session isolation:** CDP URL is per-session, not global
3. **Screencast WebSocket:** Authenticated via the same session token used for
   the SSE stream
4. **No user input forwarding in Phase 1:** The viewport is view-only. User
   interaction (clicking in the browser) is Phase 3.
5. **Cleanup:** CDP port released when browser session stops

---

## Testing Plan

1. **Unit tests:**
   - `browser_use_tool.py` emits correct SSE events
   - `/api/team/{sid}/browser` returns correct state
   - CDP port allocation doesn't conflict

2. **Integration tests:**
   - Start browser → SSE event → frontend state update
   - Navigate → screencast frame received → canvas updated
   - Stop browser → panel shows "closed" state

3. **Manual testing:**
   - Agent navigates to a website → user sees it live
   - Agent fills a form → user sees fields being filled
   - Multiple tabs → tab switching works
   - Browser crashes → graceful error in panel

---

## Milestones

| Milestone | Scope | Status |
|-----------|-------|--------|
| **M1: CDP exposure** | Backend exposes CDP URL, `/browser` API endpoint | ✅ Done |
| **M2: SSE events** | `browser_session` event emitted on all actions, reconnect replay | ✅ Done |
| **M3: Screencast proxy** | WebSocket endpoint streams JPEG frames at 5fps | ✅ Done |
| **M4: BrowserViewer panel** | Canvas-based live view with interactive URL bar + tabs | ✅ Done |
| **M5: Chat integration** | "See Browser" button on `browser_use` tool calls + custom display | ✅ Done |
| **M6: Polish** | Loading states, Escape-to-close, BrowserUseResult renderer, error handling | ✅ Done |
| **M7 (optional): Native webview** | Tauri `app_open_browser_devtools` — opens Chromium DevTools in native window | ✅ Done |
| **M8 (optional): User interaction** | Click/type/scroll forwarding via canvas → WebSocket → Playwright | ✅ Done |
