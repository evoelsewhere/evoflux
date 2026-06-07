# Evoflux — Technical Architecture & Coding Standards

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ELECTRON APP                                 │
│                                                                     │
│  ┌─────────────────────────────┐  ┌──────────────────────────────┐ │
│  │      RENDERER PROCESS       │  │       MAIN PROCESS           │ │
│  │      (React + TypeScript)   │  │    (Node.js + TypeScript)    │ │
│  │                             │  │                              │ │
│  │  ┌───────────────────────┐  │  │  ┌────────────────────────┐  │ │
│  │  │    React Components   │  │  │  │    Workflow Engine     │  │ │
│  │  │  ┌─────────────────┐  │  │  │  │  ┌──────────────────┐ │  │ │
│  │  │  │ WorkflowEditor  │  │  │  │  │  │   GraphEngine    │ │  │ │
│  │  │  │ (React Flow)    │  │  │  │  │  │   (DAG executor) │ │  │ │
│  │  │  └─────────────────┘  │  │  │  │  └──────────────────┘ │  │ │
│  │  │  ┌─────────────────┐  │  │  │  │  ┌──────────────────┐ │  │ │
│  │  │  │   NodePanel     │  │  │  │  │  │   NodeFactory    │ │  │ │
│  │  │  │   BlockSelector │  │  │  │  │  │   (Registry)     │ │  │ │
│  │  │  │   RunMonitor    │  │  │  │  │  └──────────────────┘ │  │ │
│  │  │  └─────────────────┘  │  │  │  │  ┌──────────────────┐ │  │ │
│  │  └───────────────────────┘  │  │  │  │  VariablePool     │ │  │ │
│  │                             │  │  │  └──────────────────┘ │  │ │
│  │  ┌───────────────────────┐  │  │  └────────────────────────┘  │ │
│  │  │    State Management   │  │  │                              │ │
│  │  │  ┌─────────────────┐  │  │  │  ┌────────────────────────┐  │ │
│  │  │  │ Zustand Stores  │  │  │  │  │    Agent System        │  │ │
│  │  │  │ (workflow,      │  │  │  │  │  ┌──────────────────┐  │  │ │
│  │  │  │  settings,      │  │  │  │  │  │  ReAct Agent     │  │  │ │
│  │  │  │  theme)         │  │  │  │  │  │  Orchestrator    │  │  │ │
│  │  │  └─────────────────┘  │  │  │  │  │  Tools           │  │  │ │
│  │  └───────────────────────┘  │  │  │  └──────────────────┘  │  │ │
│  │                             │  │  └────────────────────────┘  │ │
│  │  ┌───────────────────────┐  │  │                              │ │
│  │  │    TanStack Query     │  │  │  ┌────────────────────────┐  │ │
│  │  │  (server state +      │  │  │  │    Sandbox System      │  │ │
│  │  │   IPC mutations)      │──│──│  │  ┌──────────────────┐  │  │ │
│  │  └───────────────────────┘  │  │  │  │  SandboxFS       │  │  │ │
│  │                             │  │  │  │  ProcessExec     │  │  │ │
│  └─────────────────────────────┘  │  │  │  Python/JS RT    │  │  │ │
│                                   │  │  └──────────────────┘  │  │ │
│           IPC (contextBridge)     │  └────────────────────────┘  │ │
│  ─────────────────────────────────│──────────────────────────────│ │
│                                   │  ┌────────────────────────┐  │ │
│                                   │  │    Memory System       │  │ │
│                                   │  │  ┌──────────────────┐  │  │ │
│                                   │  │  │  SQLite (better- │  │  │ │
│                                   │  │  │  sqlite3)        │  │  │ │
│                                   │  │  └──────────────────┘  │  │ │
│                                   │  │  ┌──────────────────┐  │  │ │
│                                   │  │  │  Embedding       │  │  │ │
│                                   │  │  │  (multilingual-  │  │  │ │
│                                   │  │  │  e5-small)       │  │  │ │
│                                   │  │  └──────────────────┘  │  │ │
│                                   │  │  ┌──────────────────┐  │  │ │
│                                   │  │  │  FluxMem Graph   │  │  │ │
│                                   │  │  │  (semantic/epi/  │  │  │ │
│                                   │  │  │   procedural)    │  │  │ │
│                                   │  │  └──────────────────┘  │  │ │
│                                   │  └────────────────────────┘  │ │
│                                   │                              │ │
│                                   │  ┌────────────────────────┐  │ │
│                                   │  │    markitdown          │  │ │
│                                   │  │  (file → markdown)     │  │ │
│                                   │  └────────────────────────┘  │ │
│                                   └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Layer Architecture

```
┌─────────────────────────────────────────────┐
│  Presentation Layer (Renderer)              │
│  React components, Zustand stores, hooks    │
│  NO business logic, NO direct file I/O      │
├─────────────────────────────────────────────┤
│  IPC Layer (Bridge)                         │
│  contextBridge, typed IPC channels          │
│  Serialize/deserialize, error wrapping      │
├─────────────────────────────────────────────┤
│  Application Layer (Main Process)           │
│  WorkflowEngine, AgentOrchestrator          │
│  Use cases, orchestration                   │
├─────────────────────────────────────────────┤
│  Domain Layer (Engine Core)                 │
│  GraphEngine, VariablePool, NodeFactory     │
│  Pure business logic, no external deps      │
├─────────────────────────────────────────────┤
│  Infrastructure Layer                       │
│  SQLite, markitdown, AI providers, sandbox  │
│  External services, file system, network    │
└─────────────────────────────────────────────┘
```

**Dependency rule**: Dependencies point inward only.
- Presentation → IPC → Application → Domain
- Domain has ZERO dependencies on Infrastructure
- Infrastructure implements Domain interfaces

---

## 3. Project Structure

```
evoflux/
├── electron/                          # Main Process
│   ├── main.ts                        # Entry point
│   ├── preload.ts                     # contextBridge
│   └── ipc/                           # IPC handlers
│       ├── ai.ts
│       ├── workflow.ts
│       ├── sandbox.ts
│       ├── memory.ts
│       └── events.ts
│
├── src/                               # Renderer Process
│   ├── main.tsx                       # React entry
│   ├── App.tsx                        # Router
│   │
│   ├── engine/                        # Domain Layer (shared, isomorphic)
│   │   ├── graph.ts                   # Graph structure
│   │   ├── graph-engine.ts            # DAG executor
│   │   ├── variable-pool.ts           # Variable store
│   │   ├── node-factory.ts            # Node registry
│   │   ├── template-resolver.ts       # {{#ref#}} resolution
│   │   ├── dsl.ts                     # DSL serialize/deserialize
│   │   │
│   │   ├── nodes/                     # Node implementations
│   │   │   ├── base.ts                # BaseNode abstract
│   │   │   ├── start.ts
│   │   │   ├── end.ts
│   │   │   ├── llm.ts
│   │   │   ├── code.ts
│   │   │   ├── condition.ts
│   │   │   ├── http-request.ts
│   │   │   ├── template.ts
│   │   │   ├── iteration.ts
│   │   │   ├── loop.ts
│   │   │   ├── variable-aggregator.ts
│   │   │   ├── variable-assigner.ts
│   │   │   ├── knowledge-retrieval.ts
│   │   │   ├── file-explorer.ts
│   │   │   ├── file-reader.ts
│   │   │   ├── file-write.ts
│   │   │   ├── context-loader.ts
│   │   │   ├── shell.ts
│   │   │   ├── react-agent.ts
│   │   │   └── agent-orchestrator.ts
│   │   │
│   │   ├── agent/                     # Agent system
│   │   │   ├── tools.ts
│   │   │   ├── builtin-tools.ts
│   │   │   ├── parser.ts
│   │   │   ├── agent-definition.ts
│   │   │   ├── progress-ledger.ts
│   │   │   ├── stall-recovery.ts
│   │   │   ├── communication.ts
│   │   │   ├── team-state.ts
│   │   │   ├── planning.ts
│   │   │   ├── process-sequential.ts
│   │   │   ├── process-hierarchical.ts
│   │   │   └── process-hybrid.ts
│   │   │
│   │   ├── memory/                    # FluxMem memory
│   │   │   ├── memory-graph.ts
│   │   │   ├── semantic.ts
│   │   │   ├── episodic.ts
│   │   │   ├── procedural.ts
│   │   │   ├── embedding.ts
│   │   │   ├── stage1.ts
│   │   │   ├── stage2.ts
│   │   │   ├── stage3.ts
│   │   │   └── api.ts
│   │   │
│   │   ├── sandbox/                   # Sandbox system
│   │   │   ├── sandbox.ts
│   │   │   ├── sandbox-fs.ts
│   │   │   ├── sandbox-exec.ts
│   │   │   └── runtimes/
│   │   │       ├── python.ts
│   │   │       └── javascript.ts
│   │   │
│   │   ├── db/                        # Database layer
│   │   │   ├── database.ts
│   │   │   ├── schema.ts
│   │   │   ├── workflow-repo.ts
│   │   │   └── run-repo.ts
│   │   │
│   │   ├── file-reader/               # File reading
│   │   │   ├── markitdown.ts
│   │   │   ├── markdown-parser.ts
│   │   │   └── file-detector.ts
│   │   │
│   │   └── layers/                    # Engine layers
│   │       ├── ui-layer.ts
│   │       ├── persistence-layer.ts
│   │       └── limits-layer.ts
│   │
│   ├── components/                    # Presentation Layer
│   │   ├── layout/
│   │   │   ├── AppLayout.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   └── Header.tsx
│   │   │
│   │   ├── dashboard/
│   │   │   ├── Dashboard.tsx
│   │   │   └── TemplateGallery.tsx
│   │   │
│   │   ├── workflow/
│   │   │   ├── WorkflowEditor.tsx     # Main canvas
│   │   │   ├── Toolbar.tsx
│   │   │   ├── BlockSelector.tsx      # Node picker
│   │   │   ├── NodePanel.tsx          # Config sidebar
│   │   │   ├── RunMonitor.tsx
│   │   │   ├── MemoryInspector.tsx
│   │   │   │
│   │   │   ├── nodes/                 # Per-node-type components
│   │   │   │   ├── _base/
│   │   │   │   │   ├── BaseNode.tsx
│   │   │   │   │   └── BasePanel.tsx
│   │   │   │   ├── start/
│   │   │   │   │   ├── StartNode.tsx
│   │   │   │   │   └── StartPanel.tsx
│   │   │   │   ├── llm/
│   │   │   │   │   ├── LLMNode.tsx
│   │   │   │   │   └── LLMPanel.tsx
│   │   │   │   ├── code/
│   │   │   │   │   ├── CodeNode.tsx
│   │   │   │   │   └── CodePanel.tsx
│   │   │   │   ├── react-agent/
│   │   │   │   │   ├── AgentNode.tsx
│   │   │   │   │   └── AgentPanel.tsx
│   │   │   │   ├── orchestrator/
│   │   │   │   │   ├── OrchestratorNode.tsx
│   │   │   │   │   ├── OrchestratorPanel.tsx
│   │   │   │   │   ├── AgentEditor.tsx
│   │   │   │   │   └── LedgerViewer.tsx
│   │   │   │   └── registry.ts        # NodeComponentMap
│   │   │   │
│   │   │   ├── edges/
│   │   │   │   └── CustomEdge.tsx
│   │   │   │
│   │   │   └── common/
│   │   │       └── VariableSelector.tsx
│   │   │
│   │   └── common/
│   │       ├── Breadcrumb.tsx
│   │       ├── CodeEditor.tsx
│   │       ├── Icons.tsx
│   │       ├── ThemeProvider.tsx
│   │       ├── SettingsModal.tsx
│   │       └── ErrorBoundary.tsx
│   │
│   ├── stores/                        # Zustand stores
│   │   ├── workflowStore.ts
│   │   ├── settingsStore.ts
│   │   └── themeStore.ts
│   │
│   ├── hooks/                         # React hooks
│   │   ├── useWorkflow.ts
│   │   ├── useAI.ts
│   │   ├── useRunWorkflow.ts
│   │   └── useDraftSync.ts
│   │
│   ├── types/                         # TypeScript types
│   │   ├── workflow.ts
│   │   ├── ai.ts
│   │   ├── node.ts
│   │   ├── agent.ts
│   │   └── electron.d.ts
│   │
│   ├── utils/                         # Utilities
│   │   ├── graph.ts
│   │   ├── variables.ts
│   │   └── layout.ts
│   │
│   ├── styles/
│   │   └── global.css
│   │
│   └── templates/                     # Pre-built workflows
│       ├── code-review.json
│       ├── coding-agent.json
│       └── full-sdlc.json
│
├── tests/                             # Test files
│   ├── engine/
│   │   ├── graph-engine.test.ts
│   │   ├── variable-pool.test.ts
│   │   └── nodes/
│   │       ├── llm.test.ts
│   │       └── condition.test.ts
│   ├── agent/
│   │   └── react-agent.test.ts
│   └── memory/
│       └── memory-graph.test.ts
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── FEATURES.md
│   └── CODING_STANDARDS.md
│
├── electron.vite.config.ts
├── tsconfig.json
├── package.json
└── .eslintrc.cjs
```

---

## 4. Coding Rules

### 4.1 TypeScript Rules

```typescript
// RULE 1: Strict mode always
// tsconfig.json: "strict": true

// RULE 2: No `any` — use `unknown` and narrow
// ❌ BAD
function process(data: any) { ... }
// ✅ GOOD
function process(data: unknown) {
  if (typeof data === 'string') { ... }
}

// RULE 3: Explicit return types on public functions
// ❌ BAD
export function getNode(id) { ... }
// ✅ GOOD
export function getNode(id: string): Node<NodeData> | undefined { ... }

// RULE 4: Use interfaces for object shapes, types for unions/intersections
interface WorkflowConfig {
  name: string
  maxSteps: number
}
type NodeType = 'llm' | 'code' | 'condition' | 'start' | 'end'

// RULE 5: Prefer readonly for immutable data
interface NodeDefinition {
  readonly type: string
  readonly label: string
  readonly inputs: readonly PortDefinition[]
}

// RULE 6: Use discriminated unions for state
type NodeStatus =
  | { status: 'idle' }
  | { status: 'running'; startedAt: number }
  | { status: 'completed'; output: string; finishedAt: number }
  | { status: 'error'; error: string; finishedAt: number }
```

### 4.2 Naming Conventions

```
Files:
  - Components:    PascalCase.tsx     (WorkflowEditor.tsx)
  - Hooks:         camelCase.ts       (useWorkflow.ts)
  - Stores:        camelCase.ts       (workflowStore.ts)
  - Types:         camelCase.ts       (workflow.ts)
  - Utils:         camelCase.ts       (graph.ts)
  - Engine:        camelCase.ts       (graph-engine.ts)
  - Tests:         camelCase.test.ts  (graph-engine.test.ts)

Variables & Functions:
  - camelCase      (nodeId, getNode, runWorkflow)
  - Boolean:       is/has/can/should (isRunning, hasError, canExecute)

Classes & Interfaces:
  - PascalCase     (GraphEngine, BaseNode, WorkflowConfig)

Constants:
  - UPPER_SNAKE    (MAX_ITERATIONS, DEFAULT_MODEL)

Enum members:
  - PascalCase     (NodeType.Start, ProcessType.Hierarchical)

Generic type params:
  - T, U, V or descriptive: TNode, TConfig
```

### 4.3 File Size Rules

```
- Max 300 lines per file (soft limit)
- Max 500 lines per file (hard limit — must split)
- Max 50 lines per function (soft limit)
- Max 100 lines per function (hard limit — must extract)
- Max 5 levels of nesting (hard limit)
- Max 5 exports per file (soft limit)
```

### 4.4 Import Rules

```typescript
// 1. External libs first
import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Input } from 'antd'

// 2. Engine/domain imports
import { GraphEngine } from '@/engine/graph-engine'
import { VariablePool } from '@/engine/variable-pool'

// 3. Component imports
import { BaseNode } from './nodes/_base/BaseNode'

// 4. Type imports (use `import type`)
import type { NodeData, WorkflowConfig } from '@/types/workflow'

// 5. No relative imports beyond 2 levels
// ❌ BAD:  import { foo } from '../../../engine/graph'
// ✅ GOOD: import { foo } from '@/engine/graph'
```

### 4.5 Error Handling Rules

```typescript
// RULE 1: Never swallow errors
// ❌ BAD
try { await doSomething() } catch (e) { }

// ❌ BAD
try { await doSomething() } catch (e) { console.log(e) }

// ✅ GOOD
try {
  await doSomething()
} catch (error) {
  const message = error instanceof Error ? error.message : 'Unknown error'
  throw new WorkflowError(`Failed to do something: ${message}`, { cause: error })
}

// RULE 2: Use custom error classes
class WorkflowError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options)
    this.name = 'WorkflowError'
  }
}

class NodeExecutionError extends WorkflowError {
  constructor(
    public nodeId: string,
    public nodeType: string,
    message: string,
    options?: ErrorOptions
  ) {
    super(message, options)
    this.name = 'NodeExecutionError'
  }
}

class SandboxError extends WorkflowError { ... }
class MemoryError extends WorkflowError { ... }
class AgentError extends WorkflowError { ... }

// RULE 3: Result pattern for expected failures
type Result<T, E = Error> =
  | { ok: true; value: T }
  | { ok: false; error: E }

function parseExpression(expr: string): Result<number, string> {
  try {
    return { ok: true, value: eval(expr) }
  } catch {
    return { ok: false, error: `Invalid expression: ${expr}` }
  }
}

// RULE 4: Error boundaries in React
<ErrorBoundary fallback={<ErrorFallback />}>
  <WorkflowEditor />
</ErrorBoundary>
```

### 4.6 Async Rules

```typescript
// RULE 1: Always handle promise rejections
// ❌ BAD
doSomething()  // floating promise

// ✅ GOOD
await doSomething()
// or
doSomething().catch(handleError)

// RULE 2: Use AbortController for cancellable operations
const controller = new AbortController()
const timeout = setTimeout(() => controller.abort(), 30000)

try {
  const result = await llm.chat(messages, { signal: controller.signal })
} finally {
  clearTimeout(timeout)
}

// RULE 3: Async generators for streaming
async function* runWorkflow(
  graph: Graph,
  pool: VariablePool
): AsyncGenerator<EngineEvent> {
  for (const nodeId of graph.topologicalSort()) {
    yield { type: 'node:start', nodeId }
    try {
      const output = await executeNode(nodeId, pool)
      yield { type: 'node:complete', nodeId, output }
    } catch (error) {
      yield { type: 'node:error', nodeId, error }
      throw error
    }
  }
}

// RULE 4: No top-level await in modules
// Use async function instead
async function main() {
  const engine = new GraphEngine(config)
  await engine.run()
}
main().catch(console.error)
```

### 4.7 IPC Rules

```typescript
// RULE 1: Typed IPC channels
// electron/preload.ts
const api = {
  workflow: {
    run: (dsl: WorkflowDSL, options?: RunOptions): Promise<RunResult> =>
      ipcRenderer.invoke('workflow:run', dsl, options),
    stop: (runId: string): Promise<void> =>
      ipcRenderer.invoke('workflow:stop', runId),
  },
  ai: {
    chat: (messages: Message[], options?: ChatOptions): Promise<string> =>
      ipcRenderer.invoke('ai:chat', messages, options),
  }
}

// RULE 2: Error wrapping in IPC handlers
ipcMain.handle('workflow:run', async (_event, dsl, options) => {
  try {
    return await workflowRunner.run(dsl, options)
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    throw new Error(`Workflow run failed: ${message}`)
  }
})

// RULE 3: Event streaming via IPC
// Main process sends events
mainWindow.webContents.send('workflow:event', event)

// Renderer listens
ipcRenderer.on('workflow:event', (_event, data) => {
  store.getState().handleEvent(data)
})

// RULE 4: Never pass functions or class instances over IPC
// ❌ BAD:  ipcRenderer.invoke('run', engine)  // engine has methods
// ✅ GOOD: ipcRenderer.invoke('run', dsl)     // plain data only
```

### 4.8 React Rules

```typescript
// RULE 1: Components < 200 lines
// Extract sub-components if longer

// RULE 2: Hooks at top of component
function WorkflowEditor() {
  const { nodes, edges } = useWorkflowStore()
  const navigate = useNavigate()
  const [showCode, setShowCode] = useState(false)

  // ✅ All hooks at top, before any logic
  const handleSave = useCallback(() => { ... }, [nodes, edges])
  const handleRun = useCallback(() => { ... }, [nodes])

  // Then render
  return (...)
}

// RULE 3: Memoize expensive computations
const nodeTypes = useMemo<NodeTypes>(() => ({
  start: StartNode,
  end: EndNode,
  llm: LLMNode,
  code: CodeNode,
}), [])

// RULE 4: Callback refs for event handlers
const onNodeClick = useCallback((_: React.MouseEvent, node: { id: string }) => {
  setSelectedNodeId(node.id)
}, [setSelectedNodeId])

// RULE 5: No inline styles > 3 properties — extract to const
// ❌ BAD
<div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 16, background: '#111', border: '1px solid #222', borderRadius: 8 }}>

// ✅ GOOD
const containerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: 16,
  background: 'var(--bg-elevated)',
  border: '1px solid var(--border-primary)',
  borderRadius: 8
}
<div style={containerStyle}>

// RULE 6: Use CSS variables, not hardcoded colors
// ❌ BAD:  color: '#ededed'
// ✅ GOOD: color: 'var(--text-primary)'

// RULE 7: Use Ant Design components, not raw HTML
// ❌ BAD:  <button onClick={handler}>Click</button>
// ✅ GOOD: <Button onClick={handler}>Click</Button>
```

### 4.9 Zustand Store Rules

```typescript
// RULE 1: One store per domain
const useWorkflowStore = create<WorkflowState>((set, get) => ({ ... }))
const useSettingsStore = create<SettingsState>()(persist((set) => ({ ... }), { name: 'settings' }))

// RULE 2: Actions inside store, not in components
// ❌ BAD
const { nodes, setNodes } = useWorkflowStore()
const addNode = (node) => setNodes([...nodes, node])  // Logic in component

// ✅ GOOD
const { addNode } = useWorkflowStore()
addNode(node)  // Logic in store

// RULE 3: Selectors for performance
// ❌ BAD:  const store = useWorkflowStore()  // Re-renders on any change
// ✅ GOOD: const nodes = useWorkflowStore((s) => s.nodes)  // Only re-renders when nodes change

// RULE 4: Persist only what's needed
const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({ ... }),
    {
      name: 'evoflux-settings',
      partialize: (state) => ({
        aiProvider: state.aiProvider,
        selectedModel: state.selectedModel,
        theme: state.theme,
        // Don't persist: openaiApiKey (use electron-store for secrets)
      })
    }
  )
)
```

### 4.10 Node Implementation Rules

```typescript
// RULE 1: Every node extends BaseNode
@RegisterNode(NodeType.LLM)
export class LLMNode extends BaseNode {
  readonly type = NodeType.LLM

  static getMetadata(): NodeMetadata {
    return {
      type: NodeType.LLM,
      label: 'LLM',
      icon: 'robot',
      category: 'ai',
      inputs: [
        { name: 'prompt', label: 'Prompt', type: 'string', required: true },
        { name: 'system_prompt', label: 'System Prompt', type: 'string', required: false },
      ],
      outputs: [
        { name: 'output', label: 'Output', type: 'string' },
        { name: 'usage', label: 'Token Usage', type: 'object' },
      ],
      defaultConfig: {
        model: 'gpt-4o-mini',
        temperature: 0.7,
        maxTokens: 2048,
      }
    }
  }

  async run(
    inputs: Record<string, unknown>,
    pool: VariablePool
  ): Promise<NodeOutput> {
    // 1. Validate inputs
    // 2. Resolve variable references
    // 3. Execute logic
    // 4. Return outputs
    return { output: result, usage: tokenUsage }
  }
}

// RULE 2: Nodes are stateless — all state in VariablePool
// ❌ BAD:  this.lastOutput = result
// ✅ GOOD: return { output: result }

// RULE 3: Nodes must be serializable
// No circular references, no functions in config

// RULE 4: Validate inputs at start of run()
// Throw NodeExecutionError with clear message
```

---

## 5. Testing Rules

### 5.1 Unit Tests

```typescript
// File: tests/engine/variable-pool.test.ts
import { describe, it, expect } from 'vitest'
import { VariablePool } from '@/engine/variable-pool'

describe('VariablePool', () => {
  it('should set and get variable by selector', () => {
    const pool = new VariablePool()
    pool.set(['node1', 'output'], 'hello')
    expect(pool.get(['node1', 'output'])).toBe('hello')
  })

  it('should resolve template references', () => {
    const pool = new VariablePool()
    pool.set(['start', 'query'], 'test query')
    const result = pool.resolve('Process: {{#start.query#}}')
    expect(result).toBe('Process: test query')
  })

  it('should return undefined for missing variables', () => {
    const pool = new VariablePool()
    expect(pool.get(['nonexistent', 'key'])).toBeUndefined()
  })
})
```

### 5.2 Integration Tests

```typescript
// File: tests/engine/graph-engine.test.ts
describe('GraphEngine', () => {
  it('should execute sequential nodes', async () => {
    const graph = new Graph()
    graph.addNode({ id: 'start', type: 'start', data: { label: 'Start' } })
    graph.addNode({ id: 'end', type: 'end', data: { label: 'End' } })
    graph.addEdge({ source: 'start', target: 'end' })

    const engine = new GraphEngine({ graph, nodeFactory })
    const events: EngineEvent[] = []

    for await (const event of engine.run()) {
      events.push(event)
    }

    expect(events).toContainEqual(expect.objectContaining({ type: 'node:complete', nodeId: 'start' }))
    expect(events).toContainEqual(expect.objectContaining({ type: 'node:complete', nodeId: 'end' }))
    expect(events).toContainEqual(expect.objectContaining({ type: 'graph:complete' }))
  })
})
```

### 5.3 Test File Location

```
src/engine/graph.ts          → tests/engine/graph.test.ts
src/engine/nodes/llm.ts      → tests/engine/nodes/llm.test.ts
src/stores/workflowStore.ts  → tests/stores/workflowStore.test.ts
```

### 5.4 Test Coverage Targets

| Layer | Target | Priority |
|---|---|---|
| Engine Core (graph, pool, factory) | 90%+ | P0 |
| Node implementations | 80%+ | P0 |
| Agent system | 70%+ | P1 |
| Memory system | 70%+ | P1 |
| React components | 50%+ | P2 |

---

## 6. Performance Rules

```
1. React components: memo() for node components, useMemo for expensive computations
2. Zustand: use selectors, avoid subscribing to entire store
3. React Flow: nodeTypes/edgeTypes defined outside component or useMemo
4. SQLite: use WAL mode, batch inserts, prepared statements
5. Embedding: batch requests, cache results
6. Large graphs: virtualize node rendering, lazy load panels
7. IPC: batch small messages, use transferable objects for large data
```

---

## 7. Security Rules

```
1. NEVER log API keys or secrets
2. Use contextBridge for IPC (no nodeIntegration)
3. Validate all IPC inputs (don't trust renderer)
4. Sandbox code execution (no fs/network access by default)
5. Markitdown: sanitize file paths, restrict to allowed directories
6. SQL: use parameterized queries (better-sqlite3 does this)
7. CSP: restrict script sources in production
```

---

## 8. Git Rules

```
Branch naming:
  feature/FXXX-description    (e.g., feature/F1.1-variable-pool)
  fix/FXXX-description        (e.g., fix/F2.3-condition-node)
  refactor/description        (e.g., refactor/graph-engine)

Commit messages:
  feat(engine): add VariablePool with segment-based storage
  fix(node): condition node not evaluating expressions correctly
  refactor(agent): extract ReAct loop into separate class
  docs(arch): add FluxMem memory system specification
  test(engine): add GraphEngine integration tests
  chore(deps): update react-flow to v12

PR rules:
  - Max 400 lines changed per PR (soft limit)
  - Must pass TypeScript check (tsc --noEmit)
  - Must pass ESLint
  - Must have tests for new features
  - Self-review before requesting review
```
