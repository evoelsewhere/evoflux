# Evoflux Architecture v2 — Workflow-First, FluxMem Memory, ReAct Agent

## Core Design Principles

1. **Workflow-Only UI** — No separate pages for KB, Agent, Tools. Everything is a node in the workflow canvas.
2. **Flexible Node System** — Core node types are generic (LLM, Code, HTTP, Condition, etc.). SDLC-specific behaviors emerge from how users compose them, not from hardcoded node types.
3. **FluxMem Memory** — Each workflow gets a heterogeneous graph memory (semantic, episodic, procedural) that evolves through 3 stages: initial connection, feedback-driven refinement, long-term consolidation.
4. **ReAct Agent Loop** — Any node or subgraph can run as a ReAct agent (Thought → Action → Observation loop) for heavy, multi-step tasks.
5. **Sandbox Per Workflow** — Each workflow execution gets an isolated sandbox (file system, process, memory).

---

## 1. UI Architecture — Workflow-Centric

### 1.1 Routes

```
/                           → Dashboard (workflow list)
/workflows/:id              → Workflow Editor (the ONLY main view)
/settings                   → Settings (API keys, preferences)
```

No `/knowledge`, `/tools`, `/agent` routes. Those concepts are nodes.

### 1.2 Dashboard (Home)

Simple workflow list with:
- Workflow cards (name, description, last modified, status)
- Create new workflow button
- Search/filter
- Template gallery

### 1.3 Workflow Editor Layout

```
┌─────────────────────────────────────────────────────────┐
│ Toolbar: [Back] [Name] | [Run] [Stop] [Save] [Export]   │
├──────┬──────────────────────────────────────┬───────────┤
│      │                                      │           │
│ Node │         React Flow Canvas            │  Node     │
│ Picker│                                     │  Panel    │
│      │    (visual DAG editor)               │  (config) │
│      │                                      │           │
│      ├──────────────────────────────────────┤           │
│      │  Run Monitor (execution log, status) │           │
├──────┴──────────────────────────────────────┴───────────┤
│ Sandbox Terminal / Memory Inspector                      │
└─────────────────────────────────────────────────────────┘
```

### 1.4 Node Picker (Block Selector)

Categorized, searchable. Users drag nodes onto canvas:

```
🧠 AI & LLM
  ├── LLM                    — Model call with prompt template
  ├── Knowledge Retrieval     — RAG from workflow memory or external docs
  ├── Parameter Extractor     — LLM-powered structured extraction
  └── Question Classifier     — LLM-powered N-way classification

⚡ Logic & Flow
  ├── Condition (IF/ELSE)    — Boolean branching
  ├── Iteration              — For-each loop
  ├── Loop                   — While loop with condition
  ├── Variable Aggregator    — Merge parallel branch outputs
  ├── Variable Assigner      — Set/overwrite variable
  └── Template Transform     — Jinja2/ES6 template rendering

🛠 Tools & Code
  ├── Code (Sandbox)         — Python/JS execution in sandbox
  ├── HTTP Request           — External API calls
  ├── File Explorer          — Browse & select local files/folders (native dialog)
  ├── File Reader            — Read file content (code, markdown, txt, json, csv, pdf, etc.)
  ├── File Write             — Write content to sandbox file
  ├── Context Loader         — Load directory tree as structured context for LLM
  └── Shell Command          — Run commands in sandbox

🤖 Agent
  ├── ReAct Agent            — Thought→Action→Observation loop
  ├── Agent Orchestrator     — Manage a team of sub-agents (supervisor pattern)
  └── Sub-Workflow           — Embed another workflow as a node

🔗 Triggers
  ├── Manual Trigger         — User-initiated
  ├── Webhook Trigger        — HTTP webhook
  └── Schedule Trigger       — Cron-based
```

Key: No hardcoded "Code Reviewer" or "Test Generator" nodes. Users compose those behaviors by chaining LLM + Code + Condition nodes with custom prompts.

---

## 2. Node System — Flexible, Not Hardcoded

### 2.1 Node Type Hierarchy

```
BaseNode (abstract)
  ├── LLMNode                 — AI model invocation
  ├── CodeNode                — Sandbox code execution
  ├── ConditionNode           — IF/ELSE branching
  ├── HTTPNode                — External HTTP calls
  ├── TemplateNode            — String template rendering
  ├── IterationNode           — For-each loop (spawns child engine)
  ├── LoopNode                — While loop (spawns child engine)
  ├── VariableAggregatorNode  — Merge variables
  ├── VariableAssignerNode    — Set variable
  ├── KnowledgeRetrievalNode  — Query workflow memory graph
  ├── ParameterExtractorNode  — LLM-based structured extraction
  ├── QuestionClassifierNode  — LLM-based classification
  ├── FileExplorerNode        — Browse & select local files/folders (native dialog)
  ├── FileReaderNode          — Read file content (multi-format parser)
  ├── FileNode                — Write to sandbox file
  ├── ContextLoaderNode       — Load directory tree as structured context
  ├── ShellNode               — Execute command in sandbox
  ├── ReActAgentNode          — ReAct loop (orchestrates LLM + Tools)
  ├── AgentOrchestratorNode   — Team-based multi-agent supervisor
  ├── SubWorkflowNode         — Embed another workflow
  ├── StartNode               — Entry point
  └── EndNode                 — Exit point
```

### 2.2 Node Interface

```typescript
interface NodeDefinition {
  type: string
  label: string
  icon: string                // SVG icon component
  category: 'ai' | 'logic' | 'tools' | 'agent' | 'trigger'
  description: string
  inputs: PortDefinition[]    // Input ports with types
  outputs: PortDefinition[]   // Output ports with types
  configSchema: JSONSchema    // JSON Schema for config validation
  defaultConfig: unknown
}

interface PortDefinition {
  name: string
  label: string
  type: 'string' | 'number' | 'boolean' | 'object' | 'array' | 'file'
  required: boolean
}
```

### 2.3 How Users Build SDLC Workflows

Instead of hardcoded "Code Reviewer" node, users compose:

```
[Start: source_code]
  → [LLM: "Analyze this code for issues: {{source_code}}"]
  → [Code: run static analysis tool]
  → [LLM: "Based on analysis, generate review with severity ratings"]
  → [Condition: has_critical_issues?]
      ├─ Yes → [LLM: "Generate fix suggestions"] → [End]
      └─ No → [End: "Code approved"]
```

This is MORE flexible than hardcoded nodes because users can:
- Change the analysis methodology
- Add custom steps
- Use different models for different steps
- Chain with other workflows

---

## 3. FluxMem-Inspired Memory System

### 3.0 Storage & Embedding Stack

| Component | Technology | Lý do |
|---|---|---|
| **Database** | SQLite (via `better-sqlite3`) | Zero-config, embedded, file-based, single-file backup |
| **Embedding Model** | `intfloat/multilingual-e5-small` (local, 384-dim, 94 languages) | Free, no API key, fast (CPU), multilingual (vi/en/zh/ja/ko/...) |
| **Embedding Runtime** | `@xenova/transformers` (ONNX, quantized int8 ~118MB) | No Python dependency, runs in Electron main process |
| **Vector Search** | SQLite + `vecss` extension OR brute-force cosine | Simple, no external service |

**Key decision**: All persistence in SQLite. No JSON files. No external vector DB. Single `.db` file per workflow.

### 3.1 Overview

Each workflow gets a **Memory Graph** — a heterogeneous graph with 3 layers, inspired by FluxMem (Zhejiang University + Alibaba, 2026).

```
┌─────────────────────────────────────────────┐
│  Workflow Memory Graph                       │
│                                              │
│  ┌─────────────────────────────────────┐    │
│  │ Procedural Layer (Vproc)            │    │
│  │  - Reusable skills/patterns         │    │
│  │  - Distilled from successful runs   │    │
│  └──────────────┬──────────────────────┘    │
│                 │ distill edges              │
│  ┌──────────────┴──────────────────────┐    │
│  │ Episodic Layer (Vepi)               │    │
│  │  - Past execution trajectories      │    │
│  │  - Task-specific observations       │    │
│  └──────────────┬──────────────────────┘    │
│                 │ ground edges              │
│  ┌──────────────┴──────────────────────┐    │
│  │ Semantic Layer (Vsem)               │    │
│  │  - Facts, documents, code snippets  │    │
│  │  - API docs, error patterns         │    │
│  │  - User-provided context            │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

### 3.2 Memory Node Types (Graph Vertices)

```typescript
// Semantic memory units
interface SemanticUnit {
  id: string
  type: 'fact' | 'document' | 'code_snippet' | 'api_doc' | 'error_pattern'
  content: string
  embedding: number[]         // For similarity search
  metadata: Record<string, unknown>
  created_at: number
  access_count: number
}

// Episodic memory units
interface EpisodeUnit {
  id: string
  task_id: string             // Which workflow run
  trajectory: StepRecord[]    // Full step-by-step trajectory
  outcome: 'success' | 'failure'
  feedback: string            // Environmental or self-verification feedback
  embedding: number[]
  created_at: number
}

// Procedural memory units (distilled from episodes)
interface ProcedureUnit {
  id: string
  name: string
  description: string
  pattern: string             // Reusable template/strategy
  source_episodes: string[]   // Which episodes this was distilled from
  usage_count: number
  success_rate: number
  maturity_score: number      // PEMS (Procedure Evolution Maturity Score)
  embedding: number[]
  created_at: number
  last_used: number
}

// Edges
interface MemoryEdge {
  source_id: string
  target_id: string
  type: 'ground' | 'distill' | 'refine' | 'inherit'
  weight: number
  created_at: number
}
```

### 3.3 Three-Stage Evolution Pipeline

#### Stage I: Initial Connection Formation (per step, online)

When a node executes at step `t`:

1. **Semantic Retrieval** — Query `Vsem` for relevant facts using embedding similarity
   ```
   Vsem_t = TopK(Vsem, cos(similarity, observation_t), k=10)
   ```

2. **Episodic Retrieval** — Query `Vepi` for similar past tasks
   ```
   Vepi_t = TopK(Vepi, cos(similarity, current_task), k=5)
   ```

3. **Procedural Inheritance** — Traverse distillation edges from retrieved episodes
   ```
   Vproc_t = {vproc | (vepi, vproc) ∈ Edistill, vepi ∈ Vepi_t}
   ```

4. **Context Assembly** — Concatenate activated nodes into context
   ```
   Context_t = Concat(query, observation_t, Vsem_t, Vepi_t, Vproc_t)
   ```

#### Stage II: Feedback-Driven Refinement (per step, online)

After each step execution, analyze feedback `f_t`:

1. **Under-Connection Fix** — If feedback indicates missing context:
   - Search for unactivated but semantically proximate nodes
   - Add new edges: `Et ← Et ∪ {(vt, vnew)}`

2. **Over-Connection Fix** — If feedback indicates noise/hallucination:
   - Identify distractor edges `Enoise ⊂ Et`
   - Prune: `Et ← Et \ Enoise`

3. **Content Reshaping** — If abstraction granularity mismatches:
   - Too coarse → Expand with finer-grained details
   - Too fine → Compress with higher-level summary

4. **Bypass Decision** — If memory is harmful, temporarily bypass:
   - Skip memory injection for this step

#### Stage III: Long-Term Consolidation (offline, periodic)

After workflow run completes:

1. **Trajectory Clustering** — Group similar successful episodes
2. **Skill Distillation** — Extract common patterns into procedural nodes
   ```
   vproc = LLM("Extract reusable pattern from these successful runs: ...")
   ```
3. **PEMS Calculation** — Procedure Evolution Maturity Score
   ```
   PEMS = f(usage_count, success_rate, stability_over_time)
   ```
4. **Convergence Check** — If PEMS > threshold, skill is stable and reusable

### 3.4 SQLite Database Schema

All data persisted trong **1 file SQLite** per workflow: `workflows/{id}/memory.db`

```sql
-- Workflow metadata
CREATE TABLE workflow (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  dsl_json TEXT NOT NULL,           -- Full DSL JSON
  config_json TEXT,                 -- Workflow config
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

-- Execution history
CREATE TABLE runs (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  status TEXT NOT NULL,             -- 'running' | 'completed' | 'failed'
  input_json TEXT,
  output_json TEXT,
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  FOREIGN KEY (workflow_id) REFERENCES workflow(id)
);

-- Per-node execution records
CREATE TABLE node_runs (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  node_id TEXT NOT NULL,
  status TEXT NOT NULL,             -- 'running' | 'completed' | 'error'
  input_json TEXT,
  output_json TEXT,
  error TEXT,
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  FOREIGN KEY (run_id) REFERENCES runs(id)
);

-- FluxMem: Semantic layer
CREATE TABLE memory_semantic (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  type TEXT NOT NULL,               -- 'fact' | 'document' | 'code_snippet' | 'api_doc' | 'error_pattern'
  content TEXT NOT NULL,
  embedding BLOB,                   -- 384-dim float32 vector (all-MiniLM-L6-v2)
  metadata_json TEXT,
  created_at INTEGER NOT NULL,
  access_count INTEGER DEFAULT 0,
  FOREIGN KEY (workflow_id) REFERENCES workflow(id)
);

-- FluxMem: Episodic layer
CREATE TABLE memory_episodic (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  task_description TEXT,
  trajectory_json TEXT NOT NULL,    -- Full step-by-step records
  outcome TEXT NOT NULL,            -- 'success' | 'failure'
  feedback TEXT,
  embedding BLOB,                   -- 384-dim float32 vector
  created_at INTEGER NOT NULL,
  FOREIGN KEY (workflow_id) REFERENCES workflow(id)
);

-- FluxMem: Procedural layer
CREATE TABLE memory_procedural (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  pattern TEXT NOT NULL,            -- Reusable template/strategy
  source_episodes_json TEXT,        -- Array of episode IDs
  usage_count INTEGER DEFAULT 0,
  success_rate REAL DEFAULT 0,
  maturity_score REAL DEFAULT 0,    -- PEMS
  embedding BLOB,                   -- 384-dim float32 vector
  created_at INTEGER NOT NULL,
  last_used_at INTEGER,
  FOREIGN KEY (workflow_id) REFERENCES workflow(id)
);

-- FluxMem: Memory edges
CREATE TABLE memory_edges (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  type TEXT NOT NULL,               -- 'ground' | 'distill' | 'refine' | 'inherit'
  weight REAL DEFAULT 1.0,
  created_at INTEGER NOT NULL,
  FOREIGN KEY (workflow_id) REFERENCES workflow(id)
);

-- Environment variables (secrets)
CREATE TABLE env_variables (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  is_secret INTEGER DEFAULT 0,
  FOREIGN KEY (workflow_id) REFERENCES workflow(id),
  UNIQUE(workflow_id, key)
);

-- Indexes
CREATE INDEX idx_semantic_workflow ON memory_semantic(workflow_id);
CREATE INDEX idx_episodic_workflow ON memory_episodic(workflow_id);
CREATE INDEX idx_procedural_workflow ON memory_procedural(workflow_id);
CREATE INDEX idx_edges_source ON memory_edges(source_id);
CREATE INDEX idx_edges_target ON memory_edges(target_id);
CREATE INDEX idx_runs_workflow ON runs(workflow_id);
CREATE INDEX idx_node_runs_run ON node_runs(run_id);
```

### 3.5 Embedding Service

```typescript
// src/engine/memory/embedding.ts

import { pipeline } from '@xenova/transformers'

// Multilingual embedding model — 94 languages, 384 dims, ~118MB quantized
const MODEL = 'Xenova/multilingual-e5-small'
const DIMENSION = 384

let embedder: any = null

async function getEmbedder() {
  if (!embedder) {
    embedder = await pipeline('feature-extraction', MODEL)
  }
  return embedder
}

// multilingual-e5 requires "query:" prefix for search, "passage:" for indexing
export async function embed(text: string, mode: 'query' | 'passage' = 'passage'): Promise<Float32Array> {
  const pipe = await getEmbedder()
  const input = mode === 'query' ? `query: ${text}` : `passage: ${text}`
  const output = await pipe(input, { pooling: 'mean', normalize: true })
  return Float32Array.from(output.data)
}

export async function embedBatch(texts: string[], mode: 'query' | 'passage' = 'passage'): Promise<Float32Array[]> {
  const pipe = await getEmbedder()
  const results: Float32Array[] = []
  for (const text of texts) {
    const input = mode === 'query' ? `query: ${text}` : `passage: ${text}`
    const output = await pipe(input, { pooling: 'mean', normalize: true })
    results.push(Float32Array.from(output.data))
  }
  return results
}

export function cosineSimilarity(a: Float32Array, b: Float32Array): number {
  let dot = 0, normA = 0, normB = 0
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i]
    normA += a[i] * a[i]
    normB += b[i] * b[i]
  }
  return dot / (Math.sqrt(normA) * Math.sqrt(normB))
}
```

**Why multilingual-e5-small**:
- **94 languages** — Vietnamese, English, Chinese, Japanese, Korean, and more
- 384 dimensions — small enough for SQLite BLOB
- ~118MB quantized (int8) — reasonable for desktop app
- Runs on CPU — no GPU required
- Good quality: Mr. TyDi avg 64.4 (multilingual retrieval benchmark)
- `query:` / `passage:` prefix convention for better retrieval quality
- First run downloads model, cached locally after that

**Vector search strategy**: Brute-force cosine similarity for v1 (< 10k vectors is fast enough). Upgrade to SQLite `vecss` extension or HNSW index for v2 if needed.

### 3.6 Memory API for Nodes

```typescript
interface WorkflowMemory {
  // Read
  semantic_search(query: string, k: number): Promise<SemanticUnit[]>
  episodic_search(query: string, k: number): Promise<EpisodeUnit[]>
  procedural_search(query: string, k: number): Promise<ProcedureUnit[]>
  get_context(observation: string): Promise<MemoryContext>  // Full Stage I

  // Write
  add_semantic(unit: Omit<SemanticUnit, 'id'>): Promise<string>
  record_step(step: StepRecord): void
  record_outcome(outcome: 'success' | 'failure', feedback: string): void

  // Evolution (called automatically)
  refine(f_t: string): Promise<RefinementResult>  // Stage II
  consolidate(): Promise<ConsolidationResult>     // Stage III

  // Inspection
  get_graph(): MemoryGraph
  get_stats(): MemoryStats
}
```

---

## 4. ReAct Agent Loop

### 4.1 ReAct Pattern

The ReAct Agent node implements the Thought → Action → Observation loop:

```
┌──────────────────────────────────────────┐
│  ReAct Agent Node                         │
│                                           │
│  Loop until done:                         │
│    1. THOUGHT: LLM reasons about next     │
│       step given context + memory          │
│    2. ACTION: LLM chooses an action       │
│       (use tool, write code, read file,   │
│       call API, query memory, FINISH)     │
│    3. OBSERVATION: Execute action,         │
│       get result                          │
│    4. FEEDBACK: Evaluate if on track      │
│       → Update memory (Stage II)          │
│                                           │
│  Max iterations: configurable (default 25)│
│  Timeout: configurable (default 300s)     │
└──────────────────────────────────────────┘
```

### 4.2 ReAct Agent Config

```typescript
interface ReActAgentConfig {
  // Model
  model: ModelConfig
  system_prompt: string

  // Tools available to the agent
  tools: AgentTool[]

  // Loop control
  max_iterations: number      // Default: 25
  max_time_seconds: number    // Default: 300
  early_stop_condition?: string  // Custom stop condition

  // Memory integration
  use_memory: boolean         // Default: true
  memory_retrieval_k: number  // Default: 5
  auto_refine: boolean        // Stage II refinement after each step
  auto_consolidate: boolean   // Stage III after run completes

  // Sandbox
  sandbox_enabled: boolean    // Default: true
  allowed_commands?: string[]  // Whitelist for shell commands
}

interface AgentTool {
  name: string
  description: string
  parameters: JSONSchema
  handler: 'sandbox_code' | 'sandbox_shell' | 'http' | 'memory_search' | 'file_read' | 'file_write'
}
```

### 4.3 Built-in Agent Tools

```typescript
const builtinTools: AgentTool[] = [
  {
    name: 'run_code',
    description: 'Execute Python or JavaScript code in the sandbox',
    parameters: { language: 'string', code: 'string' },
    handler: 'sandbox_code'
  },
  {
    name: 'run_command',
    description: 'Execute a shell command in the sandbox',
    parameters: { command: 'string' },
    handler: 'sandbox_shell'
  },
  {
    name: 'read_file',
    description: 'Read a file from the sandbox filesystem',
    parameters: { path: 'string' },
    handler: 'file_read'
  },
  {
    name: 'write_file',
    description: 'Write content to a file in the sandbox',
    parameters: { path: 'string', content: 'string' },
    handler: 'file_write'
  },
  {
    name: 'search_memory',
    description: 'Search workflow memory for relevant context',
    parameters: { query: 'string', type: 'semantic' | 'episodic' | 'procedural' },
    handler: 'memory_search'
  },
  {
    name: 'http_request',
    description: 'Make an HTTP request to an external API',
    parameters: { url: 'string', method: 'string', body: 'object' },
    handler: 'http'
  }
]
```

### 4.4 ReAct Execution Flow

```typescript
async function* runReActAgent(
  config: ReActAgentConfig,
  input: string,
  memory: WorkflowMemory,
  sandbox: Sandbox
): AsyncGenerator<ReActEvent> {
  // Get memory context (Stage I)
  const memoryContext = config.use_memory
    ? await memory.get_context(input)
    : null

  const messages: Message[] = [
    { role: 'system', content: config.system_prompt },
    ...(memoryContext ? [{ role: 'system', content: `Relevant context:\n${memoryContext}` }] : []),
    { role: 'user', content: input }
  ]

  for (let i = 0; i < config.max_iterations; i++) {
    // THOUGHT
    yield { type: 'thought:start', iteration: i }
    const thought = await llm.chat(messages, { model: config.model })
    yield { type: 'thought:end', iteration: i, content: thought }

    // Parse action from thought
    const action = parseAction(thought)
    if (action.type === 'FINISH') {
      yield { type: 'complete', result: action.output }
      return
    }

    // ACTION + OBSERVATION
    yield { type: 'action:start', iteration: i, action }
    const observation = await executeAction(action, sandbox, memory)
    yield { type: 'observation', iteration: i, content: observation }

    // Update messages
    messages.push({ role: 'assistant', content: thought })
    messages.push({ role: 'user', content: `Observation: ${observation}` })

    // FEEDBACK + MEMORY REFINEMENT (Stage II)
    if (config.use_memory && config.auto_refine) {
      await memory.refine(`Step ${i}: ${thought} → ${observation}`)
    }
  }

  yield { type: 'max_iterations_reached' }
}
```

---

## 5. Agent Orchestrator — Team-Based Multi-Agent Management

### 5.1 Concept

The Agent Orchestrator node manages a **team of sub-agents**, each with a defined role, goal, and toolset. A supervisor agent coordinates task decomposition, delegation, progress tracking, and stall recovery.

Inspired by:
- **CrewAI** — Role/Goal/Backstory agent identity, sequential/hierarchical process
- **AutoGen MagenticOne** — Ledger-based progress tracking, stall detection + re-planning
- **LangGraph** — Typed shared state, conditional routing
- **OpenAI Swarm** — Lightweight handoff-as-return

### 5.2 Visual on Canvas

```
┌─────────────────────────────────────────────┐
│ 🤖 Agent Orchestrator                       │
│ "Build e-commerce API"                      │
│                                             │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐      │
│  │Architect│ │Backend  │ │Tester   │      │
│  │  Agent  │→│  Agent  │→│  Agent  │      │
│  └─────────┘ └─────────┘ └─────────┘      │
│                                             │
│  Process: hierarchical │ Max rounds: 10     │
│  Status: running │ Round: 3/10             │
│  Progress: ████████░░ 80%                  │
└─────────────────────────────────────────────┘
```

### 5.3 Configuration Schema

```typescript
interface AgentOrchestratorConfig {
  // Task
  task: string                           // Natural language task description
  expected_output: string                // What success looks like

  // Team
  agents: AgentDefinition[]

  // Process
  process: 'sequential' | 'hierarchical' | 'hybrid'

  // Manager (for hierarchical process)
  manager?: {
    model: ModelConfig
    instructions: string
  }

  // Planning
  planning: boolean                      // Pre-plan before execution
  planning_model?: ModelConfig

  // Execution limits
  max_rounds: number                     // Default: 15
  max_stalls: number                     // Max rounds without progress before re-plan (default: 3)
  max_time_seconds: number               // Default: 600

  // Memory
  use_memory: boolean
  auto_refine: boolean
  auto_consolidate: boolean

  // Output
  output_format?: 'text' | 'json' | 'structured'
  output_schema?: JSONSchema
}

interface AgentDefinition {
  id: string
  name: string
  role: string                           // e.g. "Senior Backend Engineer"
  goal: string                           // e.g. "Build robust, scalable APIs"
  backstory: string                      // e.g. "10 years experience in Node.js..."
  model: ModelConfig                     // Can be different per agent
  tools: AgentTool[]                     // Tools available to this agent
  allow_delegation: boolean              // Can delegate to peer agents
  max_iterations: number                 // Per-task iteration limit (default: 10)
  system_prompt?: string                 // Additional system prompt
}
```

### 5.4 Process Types

#### Sequential Process

Tasks execute one after another. Each agent receives the output of the previous agent as context.

```
Agent A (task_1) → output_1 → Agent B (task_2, context: output_1) → output_2 → Agent C (task_3, context: output_2) → final
```

Use when: Linear pipeline where each step depends on the previous.

#### Hierarchical Process

A supervisor/manager agent decomposes the task, delegates to specialized workers, validates results, and handles re-planning.

```
                    ┌─────────────┐
                    │  Supervisor  │
                    │  (Manager)   │
                    └──────┬──────┘
                           │ decompose + delegate
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌─────────┐ ┌─────────┐ ┌─────────┐
         │ Worker A │ │ Worker B │ │ Worker C │
         └────┬────┘ └────┬────┘ └────┬────┘
              │            │            │
              └────────────┼────────────┘
                           ▼
                    ┌─────────────┐
                    │  Supervisor  │ ← validate + re-plan if needed
                    │  (review)    │
                    └─────────────┘
```

Use when: Complex tasks requiring decomposition, parallel work, and quality control.

#### Hybrid Process

Mix of sequential and hierarchical. Some agents run sequentially (pipeline), others are managed by a supervisor within a stage.

```
[Sequential Stage 1: Requirements]
  Agent A (Analyst) → Agent B (Reviewer)
      │
      ▼
[Hierarchical Stage 2: Implementation]
  Supervisor manages: Backend Dev + Frontend Dev + DB Engineer (parallel)
      │
      ▼
[Sequential Stage 3: Validation]
  Agent C (Tester) → Agent D (Doc Writer)
```

### 5.5 Ledger-Based Progress Tracking (from AutoGen)

The supervisor maintains a **Progress Ledger** — a structured JSON evaluated at each round:

```typescript
interface ProgressLedger {
  is_request_satisfied: {
    answer: boolean
    reason: string
  }
  is_progress_being_made: {
    answer: boolean
    reason: string
  }
  is_in_loop: {
    answer: boolean
    reason: string
  }
  next_speaker: {
    answer: string        // Agent ID
    reason: string
  }
  instruction_or_question: {
    answer: string        // What to tell the next agent
  }
}
```

**Stall Detection**: If `is_progress_being_made === false` or `is_in_loop === true` for `max_stalls` consecutive rounds, the supervisor triggers re-planning:
1. Re-analyze current state
2. Update facts and plan
3. Reset agents (clear their context)
4. Resume with new plan

### 5.6 Communication Between Agents

```typescript
interface AgentMessage {
  from: string              // Agent ID
  to: string                // Agent ID or 'all' (broadcast)
  type: 'task' | 'result' | 'question' | 'delegation' | 'feedback'
  content: string
  metadata?: Record<string, unknown>
}
```

**Communication patterns**:
1. **Supervisor → Worker**: Task assignment with context
2. **Worker → Supervisor**: Task result or question
3. **Worker → Worker** (via delegation): When `allow_delegation=true`, agent can call `delegate_work(target_agent, subtask)` or `ask_question(target_agent, question)`
4. **Broadcast**: Supervisor sends updated plan/facts to all agents

### 5.7 Shared State (from LangGraph)

All agents share a typed state dictionary:

```typescript
interface TeamSharedState {
  // Task
  task: string
  plan: string
  facts: string[]

  // Results
  agent_outputs: Record<string, string>   // agent_id → latest output
  task_results: TaskResult[]               // Completed task results

  // Messages
  messages: AgentMessage[]                 // Full conversation log

  // Progress
  current_round: number
  stall_count: number
  status: 'planning' | 'executing' | 'reviewing' | 'completed' | 'failed'
}
```

### 5.8 Orchestrator Execution Flow

```typescript
async function* runOrchestrator(
  config: AgentOrchestratorConfig,
  input: string,
  memory: WorkflowMemory,
  sandbox: Sandbox
): AsyncGenerator<OrchestratorEvent> {
  const state: TeamSharedState = { task: input, ... }

  // === OUTER LOOP: Planning ===
  yield { type: 'planning:start' }

  if (config.planning) {
    state.facts = await gatherFacts(config.task, config.planning_model)
    state.plan = await createPlan(config.task, state.facts, config.agents, config.planning_model)
  }

  yield { type: 'planning:complete', plan: state.plan }

  // === INNER LOOP: Execution ===
  for (let round = 0; round < config.max_rounds; round++) {
    state.current_round = round
    yield { type: 'round:start', round }

    if (config.process === 'sequential') {
      // Sequential: run agents one by one
      for (const agent of config.agents) {
        yield { type: 'agent:start', agentId: agent.id }
        const context = buildSequentialContext(state, agent)
        const output = await runAgent(agent, context, sandbox, memory)
        state.agent_outputs[agent.id] = output
        state.task_results.push({ agentId: agent.id, output })
        yield { type: 'agent:complete', agentId: agent.id, output }
      }
    }

    if (config.process === 'hierarchical') {
      // Evaluate progress ledger
      const ledger = await evaluateProgress(state, config.manager)

      yield { type: 'ledger:evaluated', ledger }

      if (ledger.is_request_satisfied.answer) {
        yield { type: 'complete', result: compileResult(state) }
        return
      }

      // Stall detection
      if (!ledger.is_progress_being_made.answer || ledger.is_in_loop.answer) {
        state.stall_count++
        if (state.stall_count >= config.max_stalls) {
          yield { type: 'replanning:start' }
          state.facts = await updateFacts(state)
          state.plan = await createPlan(state.task, state.facts, config.agents, config.manager)
          state.stall_count = 0
          // Reset agents
          yield { type: 'replanning:complete', newPlan: state.plan }
          continue
        }
      } else {
        state.stall_count = 0
      }

      // Delegate to next speaker
      const nextAgent = config.agents.find(a => a.id === ledger.next_speaker.answer)
      if (nextAgent) {
        yield { type: 'agent:start', agentId: nextAgent.id }
        const instruction = ledger.instruction_or_question.answer
        const output = await runAgent(nextAgent, instruction, sandbox, memory)
        state.agent_outputs[nextAgent.id] = output
        state.messages.push({ from: 'supervisor', to: nextAgent.id, type: 'task', content: instruction })
        state.messages.push({ from: nextAgent.id, to: 'supervisor', type: 'result', content: output })
        yield { type: 'agent:complete', agentId: nextAgent.id, output }
      }
    }
  }

  yield { type: 'max_rounds_reached', result: compileResult(state) }
}
```

### 5.9 Example: SDLC Team Workflow

```json
{
  "type": "agent-orchestrator",
  "data": {
    "task": "Build a REST API for user management with authentication",
    "expected_output": "Working API with tests, documentation, and deployment config",
    "process": "hierarchical",
    "planning": true,
    "max_rounds": 20,
    "agents": [
      {
        "id": "architect",
        "name": "System Architect",
        "role": "Senior System Architect",
        "goal": "Design scalable, maintainable system architecture",
        "backstory": "15 years experience designing distributed systems",
        "model": { "provider": "openai", "name": "gpt-4o" },
        "tools": ["run_code", "write_file"],
        "allow_delegation": true
      },
      {
        "id": "backend-dev",
        "name": "Backend Developer",
        "role": "Senior Backend Engineer",
        "goal": "Implement robust, well-tested API endpoints",
        "backstory": "Expert in Node.js, TypeScript, PostgreSQL",
        "model": { "provider": "openai", "name": "gpt-4o" },
        "tools": ["run_code", "run_command", "read_file", "write_file"],
        "allow_delegation": false
      },
      {
        "id": "tester",
        "name": "QA Engineer",
        "role": "Senior QA Engineer",
        "goal": "Ensure comprehensive test coverage and catch bugs",
        "backstory": "Expert in unit, integration, and e2e testing",
        "model": { "provider": "openai", "name": "gpt-4o" },
        "tools": ["run_code", "run_command", "read_file"],
        "allow_delegation": false
      },
      {
        "id": "doc-writer",
        "name": "Technical Writer",
        "role": "Senior Technical Writer",
        "goal": "Create clear, comprehensive documentation",
        "backstory": "Expert in API documentation and developer experience",
        "model": { "provider": "openai", "name": "gpt-4o-mini" },
        "tools": ["read_file", "write_file"],
        "allow_delegation": false
      }
    ]
  }
}
```

**Execution flow**:
1. Supervisor decomposes: "Design architecture → Implement API → Write tests → Generate docs"
2. Architect designs system → outputs architecture doc
3. Backend Dev implements based on architecture → outputs code
4. Tester writes and runs tests → outputs test results
5. If tests fail → supervisor re-delegates to Backend Dev with feedback
6. Doc Writer generates API docs from code
7. Supervisor validates final output

---

## 6. Sandbox System

### 5.1 Per-Workflow Sandbox

Each workflow execution gets an isolated sandbox:

```typescript
interface Sandbox {
  id: string
  workflow_id: string
  run_id: string

  // File system (virtual or container-based)
  filesystem: SandboxFS

  // Process execution
  exec(command: string, options?: ExecOptions): Promise<ExecResult>
  execCode(language: 'python' | 'javascript', code: string): Promise<ExecResult>

  // Environment
  env: Record<string, string>
  cwd: string

  // Lifecycle
  create(): Promise<void>
  destroy(): Promise<void>
  snapshot(): Promise<SandboxSnapshot>
  restore(snapshot: SandboxSnapshot): Promise<void>
}
```

### 5.2 Sandbox Implementation Options

| Approach | Pros | Cons |
|---|---|---|
| **Docker container** | Full isolation, any language | Heavy, requires Docker |
| **VM2/Isolated-VM** | Lightweight, Node.js native | JS only, limited |
| **Temp directory + child_process** | Simple, any language | Weak isolation |
| **WebContainer (StackBlitz)** | Browser-based, no install | JS/TS only |

**Recommended**: Temp directory + child_process for v1 (simplest), Docker for v2 (production).

### 5.3 Sandbox File System

```
/workflow-sandboxes/{workflow_id}/{run_id}/
  ├── src/                    # Source files
  ├── output/                 # Generated outputs
  ├── temp/                   # Temporary files
  ├── memory/                 # Memory snapshots
  │   ├── semantic.json
  │   ├── episodic.json
  │   └── procedural.json
  └── .env                    # Environment variables
```

---

## 6.5 File Explorer & Context Loading Nodes

### File Explorer Node

Native file/folder picker. User chọn folder chứa source code → node output là path list.

```typescript
interface FileExplorerConfig {
  mode: 'file' | 'folder' | 'both'
  file_types?: string[]           // ['.ts', '.tsx', '.js', '.py', '.md', '.json']
  exclude_patterns?: string[]     // ['node_modules', '.git', 'dist', '__pycache__']
  max_depth?: number              // Max directory depth (default: 10)
  max_files?: number              // Max files to list (default: 1000)
  include_hidden?: boolean        // Include .hidden files (default: false)
}

interface FileExplorerOutput {
  root_path: string               // Selected root folder
  files: FileInfo[]               // List of files found
  total_size: number              // Total size in bytes
  file_count: number
  directory_count: number
}

interface FileInfo {
  path: string                    // Full path
  relative_path: string           // Relative to root
  name: string
  extension: string
  size: number
  modified_at: number
  is_binary: boolean              // Detected binary file
}
```

**UI**: Button "Browse" → native Electron dialog. Display selected folder path + file count.

### File Reader Node

Read file content với multi-format support. Outputs structured content.

```typescript
interface FileReaderConfig {
  path: string                    // File path (from FileExplorer or manual input)
  encoding?: string               // 'utf-8' (default), 'ascii', 'base64'
  max_size_mb?: number            // Max file size (default: 10MB)
}

interface FileReaderOutput {
  content: string                 // File content as text
  metadata: {
    path: string
    name: string
    extension: string
    size: number
    language: string              // Detected: typescript, python, markdown, etc.
    line_count: number
    char_count: number
  }
}
```

**Supported formats** — powered by **[markitdown](https://github.com/microsoft/markitdown)** (Microsoft, 146k stars):

markitdown là Python tool convert mọi file format sang Markdown. Evoflux gọi `markitdown` CLI hoặc Python API từ sandbox để đọc file.

| Category | Extensions | How |
|---|---|---|
| **Code** | `.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.java`, `.go`, `.rs`, `.c`, `.cpp`, `.h`, `.cs`, `.rb`, `.php`, `.swift`, `.kt`, `.lua`, `.sh`, `.bat`, `.ps1`, `.sql`, `.r`, `.scala`, `.dart`, `.zig`, `.nim` | Plain text (read directly) |
| **Web** | `.html`, `.css`, `.scss`, `.less`, `.sass`, `.vue`, `.svelte`, `.astro` | markitdown convert |
| **Config** | `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.env`, `.xml`, `.properties`, `.conf` | Plain text |
| **Markdown** | `.md`, `.mdx` | markitdown convert |
| **Office** | `.docx`, `.pptx`, `.xlsx`, `.xls` | markitdown convert |
| **PDF** | `.pdf` | markitdown convert |
| **Images** | `.jpg`, `.png`, `.gif`, `.bmp`, `.tiff` | markitdown (EXIF + OCR via LLM) |
| **Audio** | `.mp3`, `.wav` | markitdown (EXIF + transcription) |
| **Data** | `.csv`, `.tsv`, `.json`, `.xml` | markitdown convert |
| **Archive** | `.zip` | markitdown (iterate contents) |
| **Web** | YouTube URLs | markitdown (transcript extraction) |
| **eBook** | `.epub` | markitdown convert |
| **Email** | `.eml`, `.msg` | markitdown convert |
| **Docs** | `.txt`, `.log`, `.diff`, `.patch` | Plain text |
| **Skip** | `.exe`, `.dll`, `.so`, `.dylib`, `.wasm`, `.woff`, `.ttf`, `.mp4`, `.avi` | Mark as binary |

### markitdown Integration

```typescript
// src/engine/file-reader/markitdown.ts

import { execFile } from 'child_process'
import { promisify } from 'util'

const execFileAsync = promisify(execFile)

interface MarkitdownResult {
  content: string           // Markdown output
  title?: string            // Extracted title
  metadata?: Record<string, unknown>
}

// Option 1: CLI (markitdown must be installed in Python env)
export async function convertToMarkdown(filePath: string): Promise<MarkitdownResult> {
  const { stdout } = await execFileAsync('markitdown', [filePath], {
    timeout: 30000,
    maxBuffer: 50 * 1024 * 1024  // 50MB max
  })
  return { content: stdout }
}

// Option 2: Python subprocess (more control)
export async function convertToMarkdownViaPython(filePath: string): Promise<MarkitdownResult> {
  const script = `
import sys
from markitdown import MarkItDown
md = MarkItDown()
result = md.convert(sys.argv[1])
print(result.text_content)
`
  const { stdout } = await execFileAsync('python', ['-c', script, filePath], {
    timeout: 30000,
    maxBuffer: 50 * 1024 * 1024
  })
  return { content: stdout }
}

// Option 3: HTTP API (if running markitdown as microservice)
export async function convertToMarkdownViaAPI(filePath: string): Promise<MarkitdownResult> {
  const response = await fetch('http://localhost:8000/convert', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_path: filePath })
  })
  return response.json()
}
```

**Installation** (in sandbox Python env):
```bash
pip install 'markitdown[all]'
```

**Fallback strategy**: If markitdown not installed or fails, fall back to plain text read for code files.

### FileReader Node (updated)

```typescript
interface FileReaderConfig {
  path: string                    // File path (from FileExplorer or manual)
  mode: 'auto' | 'markdown' | 'plain' | 'structured'
  // 'auto' → use markitdown for office/pdf/images, plain text for code
  // 'markdown' → force markitdown conversion
  // 'plain' → force plain text read
  // 'structured' → parse markdown AST (headings, code blocks, links)
  max_size_mb?: number            // 10MB default
  llm_client?: boolean            // Use LLM for image OCR (markitdown feature)
}

interface FileReaderOutput {
  content: string                 // File content (markdown or plain text)
  metadata: {
    path: string
    name: string
    extension: string
    size: number
    format: string                // Detected format: code, markdown, office, pdf, image, etc.
    language?: string             // For code files: typescript, python, etc.
    line_count?: number
    converted_by: 'markitdown' | 'plain_text' | 'binary_skip'
  }
}
```

### Context Loader Node (updated)

Uses markitdown under the hood for non-code files:

```typescript
interface ContextLoaderConfig {
  root_path: string
  file_types?: string[]
  exclude_patterns?: string[]
  max_files?: number              // Default: 50
  max_total_chars?: number        // Default: 100000
  include_tree?: boolean          // Default: true
  include_file_content?: boolean  // Default: true
  convert_office_docs?: boolean   // Use markitdown for .docx/.pptx/.xlsx (default: false)
  convert_pdfs?: boolean          // Use markitdown for .pdf (default: false)
}
```

**Default behavior**: Context Loader reads code + config + markdown files as plain text. Office/PDF disabled by default (slower). User can enable via config.

### Markdown Parser Detail

For `.md` files, markitdown handles parsing. Additionally, for structured access:

**Parser**: `marked` (npm package, fast, GFM-compatible) — used when `mode: 'structured'`

```typescript
import { marked } from 'marked'
import { gfmHeadingId } from 'marked-gfm-heading-id'

// Support GitHub Flavored Markdown
marked.use(gfmHeadingId())

function parseMarkdownToText(md: string): string {
  // Option 1: Strip all formatting → plain text
  const tokens = marked.lexer(md)
  return tokens.map(token => {
    switch (token.type) {
      case 'heading':
        return `${'#'.repeat(token.depth)} ${token.text}\n`
      case 'paragraph':
        return `${token.text}\n`
      case 'code':
        return `\`\`\`${token.lang || ''}\n${token.text}\n\`\`\`\n`
      case 'list':
        return token.items.map((item, i) =>
          `${token.ordered ? `${i + 1}.` : '-'} ${item.text}`
        ).join('\n') + '\n'
      case 'table':
        // Convert table to readable format
        return formatTable(token)
      case 'blockquote':
        return token.text.split('\n').map(l => `> ${l}`).join('\n') + '\n'
      case 'hr':
        return '---\n'
      default:
        return token.raw || ''
    }
  }).join('\n')
}

function parseMarkdownToStructured(md: string): MarkdownAST {
  // Option 2: Structured output for LLM context
  const tokens = marked.lexer(md)
  return {
    headings: extractHeadings(tokens),      // Table of contents
    codeBlocks: extractCodeBlocks(tokens),   // All code blocks
    links: extractLinks(tokens),             // All links
    images: extractImages(tokens),           // All images
    tables: extractTables(tokens),           // All tables
    plainText: parseMarkdownToText(md),      // Full text
    frontmatter: extractFrontmatter(md)      // YAML frontmatter if present
  }
}

interface MarkdownAST {
  headings: { level: number; text: string; id: string }[]
  codeBlocks: { lang: string; code: string }[]
  links: { text: string; url: string }[]
  images: { alt: string; src: string }[]
  tables: { headers: string[]; rows: string[][] }[]
  plainText: string
  frontmatter: Record<string, unknown> | null
}
```

**FileReader output modes**:

```typescript
interface FileReaderConfig {
  path: string
  encoding?: string               // 'utf-8' (default)
  max_size_mb?: number            // 10MB default
  markdown_mode?: 'plain' | 'structured' | 'raw'  // For .md files
  // 'plain' → stripped text (default, best for LLM context)
  // 'structured' → headings, code blocks, links extracted separately
  // 'raw' → original markdown as-is
}
```

**Context Loader uses `markdown_mode: 'plain'` by default** — gives LLM clean readable text without markdown syntax noise.

### Context Loader Node

Load toàn bộ directory tree làm structured context cho LLM. Tự động read files, format thành context string.

```typescript
interface ContextLoaderConfig {
  root_path: string               // Directory path
  file_types?: string[]           // Filter by extension
  exclude_patterns?: string[]     // Exclude patterns
  max_files?: number              // Max files (default: 50)
  max_total_chars?: number        // Max total characters (default: 100000)
  include_tree?: boolean          // Include directory tree structure (default: true)
  include_file_content?: boolean  // Include file content (default: true)
  tree_only?: boolean             // Only output tree structure, no content
}

interface ContextLoaderOutput {
  tree: string                    // Directory tree visualization
  files: FileContent[]            // File contents
  total_chars: number
  files_loaded: number
  files_skipped: number           // Due to size/binary/excluded
  context: string                 // Combined context string for LLM
}
```

**Output format** (ready to inject into LLM prompt):

```
## Project Structure
```
src/
├── components/
│   ├── App.tsx
│   └── Header.tsx
├── utils/
│   └── helpers.ts
└── index.ts
```

## File: src/components/App.tsx
```tsx
import React from 'react'
export default function App() {
  return <div>Hello</div>
}
```

## File: src/utils/helpers.ts
```ts
export function add(a: number, b: number) {
  return a + b
}
```
```

**Use cases**:
- **Code Review**: File Explorer → Context Loader → LLM ("Review this codebase")
- **Architecture Analysis**: File Explorer → Context Loader → LLM ("Analyze architecture")
- **Documentation**: File Explorer → Context Loader → LLM ("Generate docs for this project")
- **Refactoring**: File Explorer → Context Loader → LLM ("Suggest refactoring")
- **Bug Finding**: File Explorer → Context Loader → LLM ("Find potential bugs")

### Example Workflow: Code Review

```
[Start]
  → [File Explorer: select project folder, filter: .ts,.tsx,.js]
  → [Context Loader: load top 50 files, include tree]
  → [LLM: "You are a senior code reviewer. Review this codebase:\n{{context_loader.context}}\n\nList issues with severity and suggestions."]
  → [Condition: has_critical_issues?]
      ├─ Yes → [LLM: "Generate fix for critical issues:\n{{llm.output}}"]
      └─ No → [End: "Code approved"]
  → [End]
```

---

**Persistence**: All data stored in SQLite (`better-sqlite3`). One `.db` file per workflow at `workflows/{id}/data.db`. Contains workflow DSL, runs, node executions, memory graph, env variables.

**DSL Format**: JSON serialization of the workflow graph. Stored in `workflow.dsl_json` column. Used for import/export.

```typescript
interface WorkflowDSL {
  version: '2.0'
  name: string
  description: string

  // Graph
  graph: {
    nodes: NodeDSL[]
    edges: EdgeDSL[]
  }

  // Workflow-level config
  config: {
    // Model defaults
    default_model: ModelConfig

    // Sandbox
    sandbox: {
      enabled: boolean
      type: 'tempdir' | 'docker'
      allowed_commands?: string[]
    }

    // Memory
    memory: {
      enabled: boolean
      auto_refine: boolean
      auto_consolidate: boolean
      semantic_sources?: string[]  // Files/URLs to index
    }

    // Execution limits
    max_steps: number
    max_time_seconds: number
    max_parallel_nodes: number
  }

  // Environment variables
  environment_variables: VariableDef[]

  // Metadata
  metadata: {
    created_at: string
    updated_at: string
    tags: string[]
    template?: string
  }
}
```

---

## 8. Implementation Plan — Phased Roadmap

### Overview

```
Week  1   2   3   4   5   6   7   8   9   10  11  12
      ├───┤
      P1: Engine Core
          ├───┤
          P2: Core Nodes
              ├───┤
              P3: Sandbox + Memory
                  ├───┤
                  P4: ReAct + Orchestrator
                      ├───┤
                      P5: Frontend Canvas
                          ├───┤
                          P6: Node Panels
                              ├───┤
                              P7: IPC + Integration
                                  ├───┤
                                  P8: Polish + Templates
                                      ├───────────┤
                                      M5: Release v1.0
```

---

### Phase 1: Engine Core (Week 1-2)

**Goal**: DAG execution engine hoạt động. Parse DSL → execute nodes theo topo order → emit events.

**Deliverables**:
- VariablePool đọc/ghi variables qua selector
- Graph parse JSON DSL, detect cycle
- GraphEngine chạy nodes tuần tự, emit events
- NodeFactory register + instantiate nodes

| # | Task | Files | Priority | Effort |
|---|---|---|---|---|
| 1.1 | VariablePool with segments | `src/engine/variable-pool.ts` | P0 | 3d |
| 1.2 | Graph parser + adjacency list | `src/engine/graph.ts` | P0 | 2d |
| 1.3 | Topological sort + cycle detection | `src/engine/graph.ts` | P0 | 1d |
| 1.4 | NodeFactory + self-registering registry | `src/engine/node-factory.ts` | P0 | 2d |
| 1.5 | BaseNode abstract class | `src/engine/nodes/base.ts` | P0 | 2d |
| 1.6 | GraphEngine — sequential execution + events | `src/engine/graph-engine.ts` | P0 | 4d |
| 1.7 | GraphEngine — parallel branch execution | `src/engine/graph-engine.ts` | P0 | 2d |
| 1.8 | Layer system (UILayer, PersistenceLayer, LimitsLayer) | `src/engine/layers.ts` | P1 | 3d |
| 1.9 | DSL serializer (graph → JSON) | `src/engine/dsl.ts` | P1 | 1d |
| 1.10 | DSL deserializer (JSON → graph) | `src/engine/dsl.ts` | P1 | 1d |

**Acceptance Criteria**:
- [ ] Parse `{ nodes: [...], edges: [...] }` into Graph object
- [ ] Execute 5-node sequential workflow, each node reads/writes VariablePool
- [ ] Execute 3-node parallel branches correctly
- [ ] Cycle detection throws error
- [ ] Events emitted: `node:start`, `node:complete`, `node:error`, `graph:complete`
- [ ] DSL roundtrip: serialize → deserialize → same graph

**Dependencies**: None (starting point)

---

### Phase 2: Core Nodes (Week 2-3)

**Goal**: 6 node types cơ bản hoạt động. Users có thể build workflow đơn giản.

**Deliverables**:
- Start, End, LLM, Code, Condition, HTTP nodes
- Variable reference resolution `{{#nodeId.key#}}`
- Basic prompt template system

| # | Task | Files | Priority | Effort |
|---|---|---|---|---|
| 2.1 | Start node (input variables) | `src/engine/nodes/start.ts` | P0 | 1d |
| 2.2 | End node (output definition) | `src/engine/nodes/end.ts` | P0 | 1d |
| 2.3 | LLM node (prompt template, model config, streaming) | `src/engine/nodes/llm.ts` | P0 | 4d |
| 2.4 | Code node (sandbox exec, I/O) | `src/engine/nodes/code.ts` | P0 | 3d |
| 2.5 | Condition node (expression eval, true/false branches) | `src/engine/nodes/condition.ts` | P0 | 2d |
| 2.6 | HTTP Request node (method, URL, headers, body, response) | `src/engine/nodes/http-request.ts` | P0 | 3d |
| 2.7 | Variable reference resolution `{{#nodeId.key#}}` | `src/engine/template-resolver.ts` | P0 | 2d |
| 2.8 | Template node (Jinja2/ES6 rendering) | `src/engine/nodes/template.ts` | P1 | 2d |
| 2.9 | Iteration node (for-each, child engine) | `src/engine/nodes/iteration.ts` | P1 | 4d |
| 2.10 | Loop node (while condition, child engine) | `src/engine/nodes/loop.ts` | P1 | 4d |
| 2.11 | Variable Aggregator node | `src/engine/nodes/variable-aggregator.ts` | P1 | 2d |
| 2.12 | Variable Assigner node | `src/engine/nodes/variable-assigner.ts` | P1 | 1d |
| 2.13 | Knowledge Retrieval node | `src/engine/nodes/knowledge-retrieval.ts` | P1 | 3d |
| 2.14 | Parameter Extractor node | `src/engine/nodes/parameter-extractor.ts` | P2 | 3d |
| 2.15 | Question Classifier node | `src/engine/nodes/question-classifier.ts` | P2 | 3d |

**Acceptance Criteria**:
- [ ] LLM node gọi OpenAI/Ollama, inject prompt từ VariablePool
- [ ] Code node chạy Python/JS trong sandbox, capture stdout/stderr
- [ ] Condition node eval expression, rẽ nhánh đúng
- [ ] HTTP node gọi external API, parse response
- [ ] `{{#start.query#}}` resolve thành actual value
- [ ] Iteration node chạy child engine cho mỗi array item
- [ ] Build được workflow: Start → LLM → Condition → End

**Dependencies**: Phase 1

---

### Phase 3: Sandbox + Memory (Week 3-5)

**Goal**: Mỗi workflow có isolated sandbox + FluxMem memory graph. All data in SQLite.

**Deliverables**:
- SQLite database setup + schema
- Sandbox (tempdir + child_process)
- File/Shell nodes
- FluxMem Memory Graph (3 layers) backed by SQLite
- Local embedding service (all-MiniLM-L6-v2)
- Memory API cho nodes
- 3-stage evolution pipeline

| # | Task | Files | Priority | Effort |
|---|---|---|---|---|
| 3.1 | SQLite setup (better-sqlite3, schema migration) | `src/engine/db/database.ts` | P0 | 2d |
| 3.2 | Workflow repository (CRUD via SQLite) | `src/engine/db/workflow-repo.ts` | P0 | 2d |
| 3.3 | Run repository (execution history) | `src/engine/db/run-repo.ts` | P0 | 2d |
| 3.4 | Embedding service (multilingual-e5-small via @xenova/transformers) | `src/engine/memory/embedding.ts` | P0 | 2d |
| 3.5 | Sandbox core (create/destroy lifecycle) | `src/engine/sandbox.ts` | P0 | 3d |
| 3.6 | Sandbox filesystem (read/write/list) | `src/engine/sandbox-fs.ts` | P0 | 2d |
| 3.7 | Sandbox process execution (exec, execCode) | `src/engine/sandbox-exec.ts` | P0 | 3d |
| 3.8 | Python runtime | `src/engine/runtimes/python.ts` | P0 | 2d |
| 3.9 | JavaScript runtime | `src/engine/runtimes/javascript.ts` | P1 | 2d |
| 3.10 | File Read node | `src/engine/nodes/file-read.ts` | P0 | 1d |
| 3.11 | File Write node | `src/engine/nodes/file-write.ts` | P0 | 1d |
| 3.12 | Shell Command node | `src/engine/nodes/shell.ts` | P0 | 2d |
| 3.13 | Memory Graph core (SQLite-backed heterogeneous graph) | `src/engine/memory/memory-graph.ts` | P0 | 4d |
| 3.14 | Semantic layer (SQLite + embedding search) | `src/engine/memory/semantic.ts` | P1 | 3d |
| 3.15 | Episodic layer (trajectory recording to SQLite) | `src/engine/memory/episodic.ts` | P1 | 2d |
| 3.16 | Procedural layer (skill distillation + PEMS) | `src/engine/memory/procedural.ts` | P1 | 3d |
| 3.17 | Stage I: Initial Connection Formation | `src/engine/memory/stage1.ts` | P1 | 3d |
| 3.18 | Stage II: Feedback-Driven Refinement | `src/engine/memory/stage2.ts` | P2 | 4d |
| 3.19 | Stage III: Long-Term Consolidation | `src/engine/memory/stage3.ts` | P2 | 4d |
| 3.20 | Memory API (search, record, refine, consolidate) | `src/engine/memory/api.ts` | P0 | 2d |

**Acceptance Criteria**:
- [ ] SQLite schema tạo đúng, workflow CRUD hoạt động
- [ ] Embedding service tạo 384-dim vector từ text (all-MiniLM-L6-v2)
- [ ] Cosine similarity search hoạt động trên semantic memory
- [ ] Sandbox tạo tempdir, chạy Python code, capture output
- [ ] Sandbox tạo tempdir, chạy JS code, capture output
- [ ] File nodes đọc/ghi file trong sandbox
- [ ] Shell node chạy command, return stdout/stderr
- [ ] Memory graph lưu semantic units vào SQLite, search by embedding
- [ ] Memory graph record episode trajectory vào SQLite
- [ ] Stage I: retrieve relevant semantic + episodic + procedural context
- [ ] Memory persist qua SQLite, reload on workflow restart
- [ ] Sandbox isolated giữa các workflow runs

**Dependencies**: Phase 1, Phase 2 (Code node)

---

### Phase 4: ReAct Agent + Orchestrator (Week 5-7)

**Goal**: Agent chạy multi-step tasks. Orchestrator quản lý team agents.

**Deliverables**:
- ReAct Agent node (Thought→Action→Observation loop)
- Agent tool system + built-in tools
- Agent Orchestrator (sequential, hierarchical, hybrid)
- Progress Ledger + stall detection + re-planning
- Agent communication protocol

| # | Task | Files | Priority | Effort |
|---|---|---|---|---|
| 4.1 | Agent tool interface + registry | `src/engine/agent/tools.ts` | P0 | 2d |
| 4.2 | Built-in tools (run_code, shell, read_file, write_file, search_memory, http) | `src/engine/agent/builtin-tools.ts` | P0 | 4d |
| 4.3 | ReAct Agent node (loop, max iterations, timeout) | `src/engine/nodes/react-agent.ts` | P0 | 5d |
| 4.4 | Thought/Action/Observation parser | `src/engine/agent/parser.ts` | P1 | 3d |
| 4.5 | Custom tool definition (user-defined JSON Schema) | `src/engine/agent/custom-tools.ts` | P1 | 2d |
| 4.6 | Tool permission system (whitelist/blacklist) | `src/engine/agent/permissions.ts` | P2 | 2d |
| 4.7 | Agent definition (role/goal/backstory/model/tools) | `src/engine/agent/agent-definition.ts` | P0 | 2d |
| 4.8 | Agent Orchestrator node | `src/engine/nodes/agent-orchestrator.ts` | P0 | 4d |
| 4.9 | Sequential process runner | `src/engine/agent/process-sequential.ts` | P0 | 3d |
| 4.10 | Hierarchical process runner (supervisor pattern) | `src/engine/agent/process-hierarchical.ts` | P0 | 5d |
| 4.11 | Progress Ledger (structured JSON evaluation) | `src/engine/agent/progress-ledger.ts` | P0 | 3d |
| 4.12 | Stall detection + auto re-planning | `src/engine/agent/stall-recovery.ts` | P1 | 3d |
| 4.13 | Agent communication protocol (task/result/question/delegation) | `src/engine/agent/communication.ts` | P1 | 3d |
| 4.14 | Shared team state (typed dict, reducers) | `src/engine/agent/team-state.ts` | P1 | 2d |
| 4.15 | Planning phase (task decomposition) | `src/engine/agent/planning.ts` | P1 | 3d |
| 4.16 | Hybrid process runner (stage-based mix) | `src/engine/agent/process-hybrid.ts` | P2 | 4d |
| 4.17 | Sub-Workflow node | `src/engine/nodes/sub-workflow.ts` | P2 | 4d |

**Acceptance Criteria**:
- [ ] ReAct Agent chạy loop: Thought → Action → Observation → repeat
- [ ] Agent gọi tool (run_code), nhận kết quả, tiếp tục reasoning
- [ ] Agent dừng khi LLM output FINISH hoặc đạt max iterations
- [ ] Orchestrator sequential: Agent A → B → C, mỗi agent nhận output trước
- [ ] Orchestrator hierarchical: supervisor decompose task, delegate, validate
- [ ] Progress Ledger evaluate mỗi round, select next speaker
- [ ] Stall detection: 3 rounds no progress → re-plan
- [ ] Agent delegation: Agent A gọi delegate_work → Agent B nhận subtask
- [ ] Build workflow: Start → Orchestrator(4 agents) → End

**Dependencies**: Phase 1, Phase 2, Phase 3

---

### Phase 5: Frontend — Canvas + Dashboard (Week 7-9)

**Goal**: UI hoàn chỉnh. Users tạo workflow bằng visual editor, chạy và monitor.

**Deliverables**:
- Workflow Editor (React Flow canvas)
- Node Picker (block selector)
- Dashboard (workflow list)
- Toolbar, Breadcrumb, Settings
- Dark/Light theme

| # | Task | Files | Priority | Effort |
|---|---|---|---|---|
| 5.1 | Workflow Editor (React Flow canvas, pan/zoom/minimap) | `src/components/workflow/WorkflowEditor.tsx` | P0 | 5d |
| 5.2 | BaseNode component (header, handles, status indicator) | `src/components/workflow/nodes/_base/BaseNode.tsx` | P0 | 3d |
| 5.3 | Node type registry (NodeComponentMap, PanelComponentMap) | `src/components/workflow/nodes/registry.ts` | P0 | 2d |
| 5.4 | Block Selector (categorized, searchable, drag-to-add) | `src/components/workflow/BlockSelector.tsx` | P0 | 4d |
| 5.5 | Toolbar (Run, Stop, Save, Export, Undo, Redo) | `src/components/workflow/Toolbar.tsx` | P0 | 3d |
| 5.6 | Edge connections (custom edge, animated, label) | `src/components/workflow/edges/CustomEdge.tsx` | P0 | 2d |
| 5.7 | Dashboard — workflow list (cards, search, create) | `src/components/dashboard/Dashboard.tsx` | P0 | 3d |
| 5.8 | Template gallery (pre-built workflows) | `src/components/dashboard/TemplateGallery.tsx` | P1 | 3d |
| 5.9 | NodePanel — dynamic config sidebar | `src/components/workflow/NodePanel.tsx` | P0 | 4d |
| 5.10 | Run Monitor (execution log, per-node status) | `src/components/workflow/RunMonitor.tsx` | P1 | 4d |
| 5.11 | Breadcrumb navigation | `src/components/common/Breadcrumb.tsx` | P0 | 1d |
| 5.12 | Settings page (API keys, model, theme) | `src/components/settings/SettingsPage.tsx` | P0 | 2d |
| 5.13 | Dark/Light theme (CSS variables, toggle) | `src/components/common/ThemeProvider.tsx` | P0 | 2d |
| 5.14 | SVG icons for all node types | `src/components/common/Icons.tsx` | P0 | 3d |
| 5.15 | Variable Selector component (tree view, search) | `src/components/workflow/common/VariableSelector.tsx` | P1 | 3d |
| 5.16 | Undo/Redo (zustand temporal) | `src/stores/workflowStore.ts` | P1 | 3d |
| 5.17 | Auto-layout (dagre) | `src/components/workflow/utils/layout.ts` | P2 | 3d |
| 5.18 | Keyboard shortcuts | `src/components/workflow/shortcuts.ts` | P2 | 2d |

**Acceptance Criteria**:
- [ ] Canvas: drag-drop nodes, connect edges, pan/zoom/minimap
- [ ] Block Selector: search, categories (AI, Logic, Tools, Agent, Trigger)
- [ ] Dashboard: list workflows, create new, search, click to open
- [ ] NodePanel: dynamic panel per node type, edit config, save
- [ ] Run Monitor: real-time log, node status colors (waiting/running/done/error)
- [ ] Toolbar: run workflow, stop, save, export JSON
- [ ] Theme: dark/light toggle, persist preference
- [ ] Variable Selector: pick variable from pool tree
- [ ] Undo/Redo: Ctrl+Z / Ctrl+Y

**Dependencies**: Phase 1 (for engine integration), Phase 2 (for node types)

---

### Phase 6: Frontend — Node-Specific Panels (Week 9-10)

**Goal**: Mỗi node type có panel config riêng. Agent Orchestrator có team editor.

**Deliverables**:
- LLM, Code, Condition, HTTP panels
- ReAct Agent panel
- Agent Orchestrator panel + Agent editor + Ledger viewer
- Monaco editor integration

| # | Task | Files | Priority | Effort |
|---|---|---|---|---|
| 6.1 | LLM Panel (model, prompt, system prompt, temperature, memory) | `src/components/workflow/nodes/llm/LLMPanel.tsx` | P0 | 4d |
| 6.2 | Code Panel (language selector, Monaco editor, I/O mapping) | `src/components/workflow/nodes/code/CodePanel.tsx` | P0 | 4d |
| 6.3 | Condition Panel (expression editor, branch labels) | `src/components/workflow/nodes/condition/ConditionPanel.tsx` | P0 | 2d |
| 6.4 | HTTP Panel (method, URL, headers KV, body JSON) | `src/components/workflow/nodes/http/HTTPPanel.tsx` | P1 | 3d |
| 6.5 | Template Panel (template editor, variable insertion) | `src/components/workflow/nodes/template/TemplatePanel.tsx` | P1 | 2d |
| 6.6 | Iteration/Loop Panel (array/condition selector, max iter) | `src/components/workflow/nodes/loop/LoopPanel.tsx` | P1 | 2d |
| 6.7 | ReAct Agent Panel (model, prompt, tool checklist, max iter, memory) | `src/components/workflow/nodes/react-agent/AgentPanel.tsx` | P0 | 4d |
| 6.8 | Orchestrator Panel (task, expected output, process type, agent list) | `src/components/workflow/nodes/orchestrator/OrchestratorPanel.tsx` | P0 | 5d |
| 6.9 | Agent Definition Editor (name, role, goal, backstory, model, tools) | `src/components/workflow/nodes/orchestrator/AgentEditor.tsx` | P0 | 4d |
| 6.10 | Progress Ledger Viewer (real-time JSON, stall counter) | `src/components/workflow/nodes/orchestrator/LedgerViewer.tsx` | P1 | 3d |
| 6.11 | Monaco editor integration (theme-aware, syntax highlight) | `src/components/common/MonacoEditor.tsx` | P1 | 2d |
| 6.12 | Memory Inspector Panel (graph view, search, stats) | `src/components/workflow/MemoryInspector.tsx` | P2 | 4d |

**Acceptance Criteria**:
- [ ] LLM Panel: select model, edit prompt, toggle memory, adjust temperature
- [ ] Code Panel: select language, edit code in Monaco, map inputs/outputs
- [ ] Condition Panel: edit expression, set branch labels
- [ ] ReAct Agent Panel: select model, edit system prompt, check tools, set max iter
- [ ] Orchestrator Panel: add/remove/edit agents, select process type
- [ ] Agent Editor: edit role/goal/backstory per agent, assign tools
- [ ] Ledger Viewer: show real-time JSON state during execution

**Dependencies**: Phase 5

---

### Phase 7: IPC + Integration (Week 10-11)

**Goal**: Frontend ↔ Engine full integration. Real-time execution streaming.

**Deliverables**:
- Workflow run IPC (renderer → main → engine)
- Sandbox IPC
- Memory IPC
- Real-time event streaming

| # | Task | Files | Priority | Effort |
|---|---|---|---|---|
| 7.1 | Workflow run IPC (start, stop, status) | `electron/ipc/workflow-runner.ts` | P0 | 4d |
| 7.2 | Sandbox IPC (create, exec, read/write file, destroy) | `electron/ipc/sandbox.ts` | P0 | 3d |
| 7.3 | Memory IPC (search, record, save/load) | `electron/ipc/memory.ts` | P1 | 3d |
| 7.4 | Real-time event streaming (node status, progress, logs) | `electron/ipc/events.ts` | P0 | 3d |
| 7.5 | AI provider IPC (chat, stream, list models, test) | `electron/ipc/ai.ts` | P0 | 2d |
| 7.6 | Workflow CRUD IPC (save, load, list, delete) | `electron/ipc/workflow.ts` | P0 | 2d |
| 7.7 | DSL import/export IPC | `electron/ipc/dsl.ts` | P2 | 2d |
| 7.8 | Error handling + retry logic | `src/engine/error-handler.ts` | P1 | 2d |

**Acceptance Criteria**:
- [ ] Click Run → engine executes → UI shows real-time node status
- [ ] Sandbox create → run code → read output → destroy
- [ ] Memory search returns relevant context from SQLite
- [ ] AI provider: OpenAI + Ollama both work
- [ ] Workflow save/load persists correctly via SQLite
- [ ] Execution history queryable from SQLite
- [ ] Error on node → UI shows error state + message

**Dependencies**: Phase 4, Phase 5, Phase 6

---

### Phase 8: Polish + Templates (Week 11-12)

**Goal**: Production-ready. Template workflows. Edge cases handled.

**Deliverables**:
- Template workflows (Code Review, Coding Agent, Full SDLC)
- Error handling polish
- Performance optimization
- Documentation

| # | Task | Files | Priority | Effort |
|---|---|---|---|---|
| 8.1 | Template: Code Review Pipeline | `src/templates/code-review.json` | P1 | 1d |
| 8.2 | Template: ReAct Coding Agent | `src/templates/coding-agent.json` | P1 | 1d |
| 8.3 | Template: Full SDLC Pipeline | `src/templates/full-sdlc.json` | P1 | 1d |
| 8.4 | Template: Agent Orchestrator Team | `src/templates/team-orchestrator.json` | P1 | 1d |
| 8.5 | Template: Sprint Automation | `src/templates/sprint-automation.json` | P2 | 1d |
| 8.6 | Error handling UI (toast, per-node error, details panel) | `src/components/common/ErrorBoundary.tsx` | P1 | 2d |
| 8.7 | Loading states (skeleton, spinner, progress bar) | `src/components/common/LoadingStates.tsx` | P2 | 2d |
| 8.8 | Canvas comments (sticky notes) | `src/components/workflow/CommentNode.tsx` | P2 | 2d |
| 8.9 | Performance optimization (large graph, memoization) | — | P2 | 3d |
| 8.10 | Memory visualization (graph view) | `src/components/workflow/MemoryGraph.tsx` | P2 | 4d |
| 8.11 | README + user documentation | `docs/USER_GUIDE.md` | P2 | 3d |

**Acceptance Criteria**:
- [ ] 4 template workflows loadable from gallery
- [ ] Each template runs end-to-end successfully
- [ ] Error states handled gracefully (no crash)
- [ ] Large workflow (50+ nodes) renders without lag
- [ ] Memory graph visualizable

**Dependencies**: All previous phases

---

### Milestone Summary

| Milestone | Phase | Target | Key Deliverable |
|---|---|---|---|
| **M1: Engine Works** | P1 + P2 | Week 3 | DAG engine + 6 core nodes + basic workflow runs |
| **M2: Sandbox + Memory** | P3 | Week 5 | Isolated sandbox + FluxMem memory graph |
| **M3: Agents** | P4 | Week 7 | ReAct agent + Orchestrator with team management |
| **M4: UI Complete** | P5 + P6 | Week 10 | Visual editor + all node panels + dashboard |
| **M5: Integrated** | P7 + P8 | Week 12 | Full integration + templates + polish → v1.0 |

---

### Risk Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| GraphEngine parallel execution complexity | High | Start sequential, add parallel in Phase 1.7 |
| FluxMem memory too complex for v1 | Medium | Ship with Stage I only, add Stage II/III post-v1 |
| Orchestrator stall detection tuning | Medium | Make thresholds configurable, default conservative |
| Sandbox security (code execution) | High | Start with tempdir (weak isolation), Docker post-v1 |
| Large workflow performance | Medium | Memoization + virtualized canvas + lazy node loading |

---

## 9. Template Workflows

### 8.1 Code Review Pipeline

```json
{
  "name": "Code Review Pipeline",
  "graph": {
    "nodes": [
      { "type": "start", "data": { "variables": [{ "name": "source_code", "type": "string" }] } },
      { "type": "llm", "data": { "prompt": "Analyze this code:\n{{start.source_code}}\n\nList issues with severity (critical/major/minor)." } },
      { "type": "condition", "data": { "expression": "{{llm_1.output}}.includes('critical')" } },
      { "type": "llm", "data": { "prompt": "Generate fix suggestions for critical issues:\n{{llm_1.output}}" } },
      { "type": "end", "data": { "output": "{{condition_1.trueBranch ? llm_2.output : 'No critical issues found'}}" } }
    ]
  }
}
```

### 8.2 ReAct Coding Agent

```json
{
  "name": "Coding Agent",
  "graph": {
    "nodes": [
      { "type": "start", "data": { "variables": [{ "name": "task", "type": "string" }] } },
      { "type": "react-agent", "data": {
        "model": "gpt-4o",
        "system_prompt": "You are a senior software engineer. Complete the task step by step.",
        "tools": ["run_code", "run_command", "read_file", "write_file", "search_memory"],
        "max_iterations": 25,
        "use_memory": true,
        "auto_refine": true
      }},
      { "type": "end", "data": { "output": "{{react_agent_1.output}}" } }
    ]
  }
}
```

### 8.3 Full SDLC Pipeline

```json
{
  "name": "Full SDLC Pipeline",
  "graph": {
    "nodes": [
      { "type": "start", "data": { "variables": [{ "name": "prd", "type": "string" }] } },
      { "type": "llm", "data": { "prompt": "Extract structured requirements from:\n{{start.prd}}" } },
      { "type": "llm", "data": { "prompt": "Design system architecture for:\n{{llm_1.output}}" } },
      { "type": "react-agent", "data": { "prompt": "Implement the system:\n{{llm_2.output}}", "max_iterations": 30 } },
      { "type": "react-agent", "data": { "prompt": "Write comprehensive tests for:\n{{react_agent_1.output}}", "max_iterations": 15 } },
      { "type": "react-agent", "data": { "prompt": "Run tests and fix failures:\n{{react_agent_2.output}}", "max_iterations": 10 } },
      { "type": "llm", "data": { "prompt": "Generate documentation for:\n{{react_agent_1.output}}" } },
      { "type": "end", "data": { "output": "Implementation + Tests + Docs" } }
    ]
  }
}
```

---

## 10. Key Differences from Dify

| Aspect | Dify | Evoflux |
|---|---|---|
| **Scope** | General LLM app platform | SDLC-focused workflow automation |
| **UI** | Multiple sections (workflow, dataset, tools, etc.) | Workflow-only canvas |
| **Node types** | Many hardcoded specialized nodes | Few generic + composable nodes |
| **Memory** | Simple RAG retrieval | FluxMem 3-layer evolving graph |
| **Agent** | Basic tool-calling agent | Full ReAct loop with memory integration |
| **Sandbox** | None (code node runs in-process) | Per-workflow isolated sandbox |
| **Backend** | Python Flask + Celery | Electron main process + Node.js |
| **Frontend** | Next.js | React + Electron |
