# Side Chat Feature Specification

## Overview

Side Chat enables users to ask questions in a side panel that has read-only access to the main session's context, without polluting the main conversation thread. Inspired by Claude Code Desktop's `/btw` feature.

## Architecture Decisions

### Decision 1: Separate Session vs. Extended Context

**Option A: Separate Session (Chosen)**
- Create independent side chat sessions with `source_session_id` reference
- Pros: Clean isolation, independent history, no main session pollution
- Cons: More complex data model, requires context injection

**Option B: Extended Context**
- Add side chat messages to the main session with a flag
- Pros: Simpler data model, unified history
- Cons: Pollutes main session, complex filtering, harder to manage

**Decision:** Option A - Separate sessions provide better isolation and cleaner architecture.

### Decision 2: Tool Filtering Strategy

**Option A: Hard Exclusion (Chosen)**
- Completely remove write/mutating tools from side chat
- Pros: Clear security boundary, impossible to accidentally modify state
- Cons: Less flexible, cannot upgrade tools later

**Option B: Soft Restriction**
- Keep all tools but add warnings/prompts for destructive actions
- Pros: More flexible, can upgrade tools later
- Cons: Complex implementation, potential security risks

**Decision:** Option A - Hard exclusion provides clearer security boundaries for read-only mode.

### Decision 3: Context Injection Approach

**Option A: Prepend to Message List (Chosen)**
- Add source session messages at the beginning of the message list
- Pros: Simple implementation, clear context boundary
- Cons: May exceed context window limits

**Option B: System Prompt Injection**
- Add context summary to the system prompt
- Pros: More control over context presentation
- Cons: Less natural conversation flow, harder to implement

**Decision:** Option A - Prepending to message list is simpler and more natural.

### Decision 4: SSE Streaming Strategy

**Option A: Independent Streams (Chosen)**
- Separate SSE stream for each side chat session
- Pros: Clean isolation, no cross-session interference
- Cons: More connections, higher resource usage

**Option B: Multiplexed Stream**
- Single SSE stream with session ID multiplexing
- Pros: Fewer connections, lower resource usage
- Cons: More complex implementation, potential interference

**Decision:** Option A - Independent streams provide cleaner isolation.

## 1. Data Model Changes

### 1.1 ChatSession Model Extensions

**File:** `app/models/chat.py` (lines 78-167)

Add new fields to `ChatSession`:

```python
class ChatSession(SQLModel, table=True):
    # ... existing fields ...
    
    # New fields for side chat
    session_type: str = Field(
        default="main",
        max_length=20,
        sa_column=Column(sa.String(20), nullable=False, server_default="main"),
    )
    # For side chats: reference to the main session they read from
    source_session_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
```

**Migration:** New migration file to add `session_type` and `source_session_id` columns.

### 1.2 Session Types

- `main`: Regular chat session (default)
- `team_member`: Team member session (existing `parent_session_id` usage)
- `side_chat`: Side chat session with read-only access to `source_session_id`

### 1.3 Conflict Resolution

**Current Usage:** `parent_session_id` links team member sessions to their lead session.

**Side Chat Usage:** `source_session_id` links side chat to the main session it reads from.

**Key Distinction:** Side chat sessions are NOT children of the main session - they are independent sessions with read-only access to the main session's context.

## 2. API Endpoints

### 2.1 Create Side Chat Session

**File:** `app/api/routes/team/chat.py`

```python
@router.post("/team/{session_id}/side-chat", response_model=SessionResponse)
async def create_side_chat(
    session_id: UUID,
    db: DbSession,
) -> SessionResponse:
    """Create a side chat session with read-only access to the main session."""
    # Validate main session exists
    main_session = await db.get(ChatSession, session_id)
    if not main_session:
        raise HTTPException(status_code=404, detail="Main session not found")
    
    # Create side chat session
    side_chat = ChatSession(
        title=f"Side Chat: {main_session.title or 'Untitled'}",
        session_type="side_chat",
        source_session_id=session_id,
        agent_name=main_session.agent_name,
        mode=main_session.mode,
        workspace=main_session.workspace,
        project_id=main_session.project_id,
    )
    db.add(side_chat)
    await db.flush()
    await db.refresh(side_chat)
    
    return SessionResponse.model_validate(side_chat)
```

### 2.2 Get Side Chat Context

**File:** `app/services/chat_service.py`

```python
async def get_side_chat_context(
    db: AsyncSession,
    source_session_id: UUID,
    max_messages: int = 50,
) -> list[ChatMessage]:
    """Get read-only context from the source session for side chat."""
    # Get the latest messages from the source session
    stmt = (
        select(SessionMessage)
        .where(col(SessionMessage.session_id) == source_session_id)
        .where(~col(SessionMessage.exclude_from_context))
        .order_by(col(SessionMessage.created_at).desc())
        .limit(max_messages)
    )
    db_messages = list((await db.exec(stmt)).all())
    db_messages.reverse()  # Chronological order
    
    # Deserialize and return
    return await asyncio.to_thread(
        _deserialize_messages, db_messages, sanitize_tool_pairs=True
    )
```

### 2.3 Side Chat Message Submission

**File:** `app/api/routes/team/chat.py`

```python
@router.post("/team/{session_id}/side-chat/{side_chat_id}/message")
async def send_side_chat_message(
    session_id: UUID,
    side_chat_id: UUID,
    body: SendMessageRequest,
    db: DbSession,
    form: ChatFormDep,
) -> dict:
    """Send a message to a side chat session."""
    # Validate side chat belongs to the main session
    side_chat = await db.get(ChatSession, side_chat_id)
    if (
        not side_chat
        or side_chat.session_type != "side_chat"
        or side_chat.source_session_id != session_id
    ):
        raise HTTPException(status_code=404, detail="Side chat not found")
    
    # Save user message
    await save_message(db, side_chat_id, "user", body.content)
    
    # Get side chat context (read-only from main session)
    context = await get_side_chat_context(db, session_id)
    
    # Get side chat's own messages
    side_chat_messages = await get_messages_for_llm(db, side_chat_id)
    
    # Combine: context + side chat messages
    all_messages = context + side_chat_messages
    
    # Run agent with restricted tools
    # ... (see Agent Loop section)
```

### 2.4 Side Chat SSE Stream

**File:** `app/api/routes/team/chat.py`

```python
@router.get("/{session_id}/side-chat/{side_chat_id}/stream")
async def side_chat_stream(
    session_id: UUID,
    side_chat_id: UUID,
    request: Request,
):
    """SSE stream for side chat agent events."""
    # Validate side chat belongs to the main session
    side_chat = await db.get(ChatSession, side_chat_id)
    if (
        not side_chat
        or side_chat.session_type != "side_chat"
        or side_chat.source_session_id != session_id
    ):
        raise HTTPException(status_code=404, detail="Side chat not found")
    
    async def _gen() -> AsyncGenerator[dict, None]:
        try:
            async for event in stream_store.attach(str(side_chat_id)):
                if await request.is_disconnected():
                    break
                yield {
                    "event": event.get("event", "message"),
                    "data": event.get("data", "{}"),
                }
        except Exception as exc:
            logger.exception("side_chat_stream_error type={}", type(exc).__name__)
            yield {
                "event": "error",
                "data": f'{{"type":"error","message":"stream_error:{type(exc).__name__}"}}',
            }
    
    return EventSourceResponse(_gen())
```

## 3. Agent Loop Changes

### 3.1 Tool Filtering for Side Chat

**File:** `app/agent/agent_loop/core.py` (lines 189-190, 247-254)

The agent loop already supports `excluded_tools` parameter. For side chat, we exclude all write/mutating tools:

```python
# In side chat agent run
SIDE_CHAT_EXCLUDED_TOOLS: frozenset[str] = frozenset({
    "write",
    "edit",
    "patch",
    "rm",
    "shell",
    "bg",
    "python",
    "browser_use",
    "webbridge",
    "schedule_task",
    "skill",  # Skills may have side effects
    "todo_manage",  # May modify todo state
    "team_message",  # May send messages to team
    "team_handoff",  # May send handoffs
    "team_state",  # May modify shared state
    "create_pull_request",  # May create PRs
    "show_widget",  # May render widgets
    "visualize_read_me",  # May render visualizations
})

# Run agent with restricted tools
result = await agent.run(
    messages=all_messages,
    excluded_tools=SIDE_CHAT_EXCLUDED_TOOLS,
    # ... other params
)
```

### 3.2 Context Injection

**File:** `app/services/chat_service.py` (lines 391-462)

Modify `get_messages_for_llm()` to support side chat context injection:

```python
async def get_messages_for_llm(
    db: AsyncSession,
    session_id: UUID,
    *,
    include_source_context: bool = False,
) -> list[ChatMessage]:
    """Return the message window that should be sent to the LLM.
    
    When include_source_context=True (for side chats), prepend read-only
    context from the source session.
    """
    # ... existing logic ...
    
    if include_source_context:
        session = await db.get(ChatSession, session_id)
        if session and session.session_type == "side_chat" and session.source_session_id:
            # Get source session context
            source_context = await get_side_chat_context(
                db, session.source_session_id, max_messages=50
            )
            # Prepend as read-only context
            messages = source_context + messages
    
    return messages
```

### 3.3 System Prompt Extension

**File:** `app/agent/agent_loop/core.py`

Add side chat context to system prompt:

```python
SIDE_CHAT_SYSTEM_PROMPT_ADDENDUM = """
## Side Chat Mode

You are in a side chat session with read-only access to the main conversation.
- You can read the main session's context for reference
- You CANNOT modify files, execute commands, or make changes
- You CANNOT send messages to team members or modify shared state
- Your responses should focus on answering questions and providing information
- If the user asks you to perform actions, explain that you're in read-only mode
"""
```

## 4. Frontend Component Hierarchy

### 4.1 SideChatPanel Component

**File:** `web/src/components/SideChatPanel/index.tsx`

```tsx
import { SidePanel } from '@/components/shell/SidePanel'
import { InputBar } from '@/components/InputBar'
import { useSideChat } from './useSideChat'

interface SideChatPanelProps {
  mainSessionId: string
  isOpen: boolean
  onClose: () => void
}

export function SideChatPanel({ mainSessionId, isOpen, onClose }: SideChatPanelProps) {
  const {
    messages,
    isWorking,
    sendMessage,
    stopGeneration,
  } = useSideChat(mainSessionId)
  
  return (
    <SidePanel
      storageKey="side-chat-panel"
      defaultWidth={400}
      minWidth={320}
      maxWidth={600}
      title="Side Chat"
      onClose={onClose}
      closeLabel="Close side chat"
      resizeLabel="Resize side chat panel"
      mobileOverlay
    >
      <div className="flex flex-col h-full">
        {/* Message list */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
        </div>
        
        {/* Input bar */}
        <div className="border-t p-4">
          <InputBar
            onSubmit={sendMessage}
            onStop={stopGeneration}
            isStreaming={isWorking}
            placeholder="Ask a question about the main session..."
            // Restricted slash commands for side chat
            slashCommands={SIDE_CHAT_SLASH_COMMANDS}
          />
        </div>
      </div>
    </SidePanel>
  )
}
```

### 4.2 useSideChat Hook

**File:** `web/src/components/SideChatPanel/useSideChat.ts`

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef } from 'react'
import { apiClient } from '@/api/client'
import { useTeamStore } from '@/stores/useTeamStore'

export function useSideChat(mainSessionId: string) {
  const queryClient = useQueryClient()
  const abortControllerRef = useRef<AbortController | null>(null)
  
  // Create/get side chat session
  const { data: sideChatSession } = useQuery({
    queryKey: ['sideChat', mainSessionId],
    queryFn: () => apiClient.createSideChat(mainSessionId),
    enabled: !!mainSessionId,
  })
  
  // Send message mutation
  const sendMessage = useMutation({
    mutationFn: async (content: string) => {
      if (!sideChatSession) throw new Error('No side chat session')
      
      // Abort any previous streaming request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
      abortControllerRef.current = new AbortController()
      
      return apiClient.sendSideChatMessage(
        mainSessionId, 
        sideChatSession.id, 
        content,
        abortControllerRef.current.signal
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sideChatMessages', sideChatSession?.id] })
    },
  })
  
  // Get messages
  const { data: messages = [] } = useQuery({
    queryKey: ['sideChatMessages', sideChatSession?.id],
    queryFn: () => apiClient.getSideChatMessages(sideChatSession?.id),
    enabled: !!sideChatSession?.id,
  })
  
  // SSE connection for streaming
  useEffect(() => {
    if (!sideChatSession?.id) return
    
    const eventSource = new EventSource(
      `${apiBaseUrl()}/team/${mainSessionId}/side-chat/${sideChatSession.id}/stream`
    )
    
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data)
      // Handle streaming updates
      useTeamStore.getState()._handleSSEEvent(data.type, data)
    }
    
    eventSource.onerror = () => {
      // Reconnect logic
      eventSource.close()
    }
    
    return () => {
      eventSource.close()
    }
  }, [sideChatSession?.id, mainSessionId])
  
  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
  }, [])
  
  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [])
  
  return {
    messages,
    isWorking: sendMessage.isPending,
    sendMessage: sendMessage.mutate,
    stopGeneration,
  }
}
```

### 4.3 Integration with TeamChatView

**File:** `web/src/components/TeamChatView/index.tsx`

```tsx
import { SideChatPanel } from '../SideChatPanel'

export function TeamChatView({ sessionId, mode, workspace, codingSessionLoading }: TeamChatViewProps) {
  const [sideChatOpen, setSideChatOpen] = useState(false)
  
  // ... existing code ...
  
  return (
    <AppShell>
      {/* ... existing layout ... */}
      
      {/* Side Chat Panel */}
      {sideChatOpen && sessionId && (
        <SideChatPanel
          mainSessionId={sessionId}
          isOpen={sideChatOpen}
          onClose={() => setSideChatOpen(false)}
        />
      )}
      
      {/* FloatingInputBar with /btw command */}
      <FloatingInputBar
        // ... existing props ...
        onSlashCommand={(id) => {
          if (id === 'btw') {
            setSideChatOpen(true)
          } else {
            // ... existing slash command handling ...
          }
        }}
      />
    </AppShell>
  )
}
```

### 4.4 API Client Functions

**File:** `web/src/api/client/team.ts`

```typescript
// Add these functions to the existing team.ts file

export async function createSideChat(
  mainSessionId: string,
): Promise<SessionResponse> {
  const res = await fetch(`${apiBaseUrl()}/team/${mainSessionId}/side-chat`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) {
    await parseDetailOrThrow(res, 'Create side chat')
  }
  return res.json()
}

export async function sendSideChatMessage(
  mainSessionId: string,
  sideChatId: string,
  content: string,
  signal?: AbortSignal,
): Promise<{ status: string; session_id: string }> {
  const res = await fetch(
    `${apiBaseUrl()}/team/${mainSessionId}/side-chat/${sideChatId}/message`,
    {
      method: 'POST',
      headers: { 
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ content }),
      signal,
    }
  )
  if (!res.ok) {
    await parseDetailOrThrow(res, 'Send side chat message')
  }
  return res.json()
}

export async function getSideChatMessages(
  sideChatId: string,
): Promise<ChatMessage[]> {
  const res = await fetch(`${apiBaseUrl()}/team/side-chat/${sideChatId}/messages`, {
    method: 'GET',
    headers: { Accept: 'application/json' },
  })
  if (!res.ok) {
    await parseDetailOrThrow(res, 'Get side chat messages')
  }
  return res.json()
}
```

### 4.4 /btw Slash Command

**File:** `web/src/components/TeamChatView/useSlashCommandRegistry.ts`

```tsx
const slashCommands: SlashCommand[] = [
  // ... existing commands ...
  { 
    id: 'btw', 
    label: 'Side Chat', 
    description: 'Open a side chat with read-only access to this session',
    keepInputOpen: false, // Opens the panel, doesn't insert text
  },
]
```

## 5. Permission Model

### 5.1 Tool Restrictions

**Read-Only Tools Allowed:**
- `read` - Read files
- `grep` - Search file contents
- `glob` - Find files by pattern
- `code_search` - Search code symbols
- `code_graph` - Explore symbol relationships
- `code_path` - Trace dependency paths
- `ls` - List directory contents
- `memory_search` - Search memory
- `web_search` - Search the web
- `web_fetch` - Fetch URLs
- `image_search` - Search for images

**Write/Mutating Tools Excluded:**
- `write` - Write files
- `edit` - Edit files
- `patch` - Apply patches
- `rm` - Delete files
- `shell` - Execute shell commands
- `bg` - Background processes
- `python` - Execute Python code
- `browser_use` - Browser automation
- `webbridge` - Web bridge control
- `schedule_task` - Schedule tasks
- `skill` - Load skills (may have side effects)
- `todo_manage` - Manage todos
- `team_message` - Send team messages
- `team_handoff` - Send handoffs
- `team_state` - Modify shared state
- `create_pull_request` - Create PRs
- `show_widget` - Render widgets
- `visualize_read_me` - Render visualizations

### 5.2 Session Isolation

Side chat sessions are isolated from the main session:
- No shared mutable state
- Independent message history
- Separate SSE streaming
- Independent agent loop execution

### 5.3 Access Control

- Users can only create side chats for sessions they have access to
- Side chat sessions inherit workspace/project permissions from the main session
- Side chat sessions cannot be accessed by other team members (private to creator)

## 6. Edge Cases and Race Conditions

### 6.1 Main Session Updates

**Problem:** Main session receives new messages while side chat is open.

**Solution:** 
- Side chat context is fetched at message submission time
- No real-time sync with main session
- User can manually refresh context by sending a new message

### 6.2 Concurrent Side Chats

**Problem:** Multiple side chats for the same main session.

**Solution:**
- Allow multiple side chats per main session
- Each side chat has independent context snapshot
- No conflict between side chats

### 6.3 Main Session Deletion

**Problem:** Main session is deleted while side chat is open.

**Solution:**
- `source_session_id` has `ON DELETE SET NULL`
- Side chat continues to work but loses source context
- UI shows warning that source session was deleted

### 6.4 Agent Loop Interruption

**Problem:** Side chat agent is interrupted mid-response.

**Solution:**
- Use existing `interrupt_event` mechanism
- Side chat has independent interrupt state
- No impact on main session agent

### 6.5 SSE Streaming Isolation

**Problem:** Side chat streaming should not interfere with main session streaming.

**Solution:**
- Side chat uses separate session ID for SSE
- Independent `memory_stream_store` entries
- No cross-session event leakage

### 6.6 Context Freshness

**Problem:** Side chat context becomes stale as main session progresses.

**Solution:**
- Side chat shows timestamp of when context was last fetched
- User can manually refresh by sending a new message
- Optional: Auto-refresh notification when main session receives new messages

### 6.7 Tool Execution in Side Chat

**Problem:** Side chat agent tries to use restricted tools.

**Solution:**
- Agent loop filters tools at startup using `excluded_tools`
- System prompt explicitly states read-only restrictions
- If agent attempts restricted tool, it receives error message explaining limitation

## 7. Migration Strategy

### 7.1 Backward Compatibility

- `session_type` defaults to "main" - existing sessions unchanged
- `source_session_id` is nullable - no migration needed for existing data
- `parent_session_id` usage unchanged - team member sessions unaffected

### 7.2 Database Migration

```sql
-- Add new columns
ALTER TABLE chat_sessions ADD COLUMN session_type VARCHAR(20) NOT NULL DEFAULT 'main';
ALTER TABLE chat_sessions ADD COLUMN source_session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL;

-- Add index for source_session_id
CREATE INDEX ix_chat_sessions_source_session ON chat_sessions(source_session_id);

-- Update existing team member sessions (optional, for clarity)
UPDATE chat_sessions SET session_type = 'team_member' WHERE parent_session_id IS NOT NULL;
```

### 7.3 Rollback Plan

- Remove new columns if feature is rolled back
- No data loss - existing sessions unaffected
- Frontend gracefully handles missing `session_type` field

## 8. Testing Strategy

### 8.1 Unit Tests

**Backend:**
- `test_create_side_chat_session` - API endpoint creates side chat correctly
- `test_get_side_chat_context` - Context retrieval with message limits
- `test_side_chat_tool_filtering` - Tool exclusion works correctly
- `test_side_chat_session_isolation` - Sessions are independent
- `test_side_chat_source_session_validation` - Invalid source session handling
- `test_side_chat_message_persistence` - Messages are saved correctly

**Frontend:**
- `test_side_chat_panel_rendering` - Component renders correctly
- `test_side_chat_slash_command` - /btw command opens panel
- `test_side_chat_message_submission` - User can send messages
- `test_side_chat_streaming` - SSE events are processed correctly
- `test_side_chat_error_handling` - Error states are displayed

### 8.2 Integration Tests

- `test_side_chat_end_to_end` - Full flow from creation to response
- `test_side_chat_with_main_session_updates` - Context freshness
- `test_side_chat_concurrent_access` - Multiple side chats
- `test_side_chat_agent_execution` - Agent runs with restricted tools
- `test_side_chat_sse_streaming` - Real-time updates work correctly

### 8.3 E2E Tests

- `test_side_chat_user_flow` - Complete user journey
- `test_side_chat_persistence` - Side chat survives page reload
- `test_side_chat_mobile_responsive` - Works on mobile devices

### 8.4 Test Data Setup

```python
# pytest fixtures for side chat tests
@pytest.fixture
async def main_session(db: AsyncSession):
    """Create a main session with some messages."""
    session = ChatSession(title="Test Main Session")
    db.add(session)
    await db.flush()
    
    # Add some messages
    await save_message(db, session.id, "user", "Hello, world!")
    await save_message(db, session.id, "assistant", "Hi there!")
    
    return session

@pytest.fixture
async def side_chat_session(db: AsyncSession, main_session: ChatSession):
    """Create a side chat session linked to the main session."""
    session = ChatSession(
        title="Test Side Chat",
        session_type="side_chat",
        source_session_id=main_session.id,
    )
    db.add(session)
    await db.flush()
    return session
```

## 9. Implementation Order

### Phase 1: Backend Foundation
1. **Database migration** for new columns (`session_type`, `source_session_id`)
2. **`ChatSession` model updates** - Add new fields to the model
3. **`create_side_chat` API endpoint** - Create side chat sessions
4. **`get_side_chat_context` service function** - Retrieve read-only context
5. **`send_side_chat_message` API endpoint** - Handle message submission
6. **`get_side_chat_messages` API endpoint** - Retrieve side chat messages

**Dependencies:** None (foundation work)
**Estimated Time:** 2-3 days

### Phase 2: Agent Integration
7. **Tool filtering for side chat** - Define `SIDE_CHAT_EXCLUDED_TOOLS`
8. **System prompt extension** - Add side chat context to system prompt
9. **Context injection in `get_messages_for_llm`** - Prepend source session context
10. **Side chat agent execution** - Run agent with restricted tools
11. **SSE streaming for side chat** - Implement streaming endpoint

**Dependencies:** Phase 1 complete
**Estimated Time:** 3-4 days

### Phase 3: Frontend UI
12. **`SideChatPanel` component** - Main UI component
13. **`useSideChat` hook** - State management and API integration
14. **API client functions** - Add to `web/src/api/client/team.ts`
15. **Integration with `TeamChatView`** - Mount panel in main layout
16. **`/btw` slash command** - Add to slash command registry

**Dependencies:** Phase 2 complete (API endpoints)
**Estimated Time:** 3-4 days

### Phase 4: Testing & Polish
17. **Unit tests** - Backend and frontend
18. **Integration tests** - End-to-end flows
19. **E2E tests** - User journeys
20. **Documentation** - API docs, user guide
21. **Performance testing** - Ensure no regression

**Dependencies:** Phases 1-3 complete
**Estimated Time:** 2-3 days

### Total Estimated Time: 10-14 days

### Critical Path
1. Database migration → Model updates → API endpoints → Agent integration
2. API endpoints → Frontend integration → Testing

### Parallel Work Opportunities
- **Frontend UI** can start after API endpoints are defined (mock data)
- **Testing** can start as soon as components are complete
- **Documentation** can be written in parallel with implementation

## 10. Open Questions

1. **Context Window Size:** How many messages from the main session should be included in side chat context? (Proposed: 50 messages)
   - **Trade-off:** More context = better understanding but higher token cost
   - **Recommendation:** Start with 50, make configurable via API parameter

2. **Real-time Sync:** Should side chat automatically refresh when main session receives new messages? (Proposed: No, manual refresh only)
   - **Trade-off:** Real-time sync = better UX but more complex implementation
   - **Recommendation:** Manual refresh for v1, consider real-time sync for v2

3. **Side Chat Persistence:** Should side chat sessions persist across page reloads? (Proposed: Yes, but can be manually deleted)
   - **Trade-off:** Persistence = better UX but more storage
   - **Recommendation:** Persist with TTL (e.g., 7 days) for automatic cleanup

4. **Team Access:** Should team members be able to see side chats created by others? (Proposed: No, private to creator)
   - **Trade-off:** Privacy vs. collaboration
   - **Recommendation:** Private for v1, add sharing option later

5. **Model Selection:** Should side chat use the same model as the main session? (Proposed: Yes, but could be configurable)
   - **Trade-off:** Consistency vs. flexibility
   - **Recommendation:** Start with same model, add selection later

6. **Side Chat Title:** How should side chat titles be generated? (Proposed: Auto-generate from first message or "Side Chat: [Main Session Title]")
   - **Trade-off:** Automation vs. user control
   - **Recommendation:** Auto-generate with edit capability

7. **Side Chat Limits:** Should there be a limit on concurrent side chats per main session? (Proposed: No limit)
   - **Trade-off:** Resource usage vs. flexibility
   - **Recommendation:** No hard limit, but warn at 10+ side chats

8. **Error Handling:** How should side chat handle main session deletion or access revocation? (Proposed: Show warning, continue with stale context)
   - **Trade-off:** Graceful degradation vs. hard failure
   - **Recommendation:** Graceful degradation with clear messaging

---

**Document Version:** 1.0
**Last Updated:** 2025-08-25
**Author:** architect#1
**Status:** Draft - Pending Review