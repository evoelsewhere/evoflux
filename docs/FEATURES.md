# Evoflux — Feature List

> Đồng bộ với ARCHITECTURE.md. Mỗi feature có ID, mô tả, priority, effort, dependencies.

---

## F1. Workflow Engine Core

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F1.1 | Variable Pool | Segment-based shared data store. Nodes đọc/ghi qua selector `[nodeId, key]`. Types: string, number, boolean, object, array, file. | P0 | 3d | — |
| F1.2 | Graph Parser | Parse DSL JSON → Graph adjacency list. Cycle detection. | P0 | 2d | — |
| F1.3 | Topological Sort | Sắp xếp nodes theo dependency order. Phát hiện cycle. | P0 | 1d | F1.2 |
| F1.4 | Node Factory + Registry | Self-registering node classes. Decorator-based registration. Version-based resolution. | P0 | 2d | — |
| F1.5 | BaseNode Abstract Class | Interface chung cho tất cả nodes: `run(inputs, variablePool) → outputs`. Port definitions. | P0 | 2d | F1.1, F1.4 |
| F1.6 | GraphEngine — Sequential | DAG executor. Topological traversal. Event emitter (`node:start`, `node:complete`, `node:error`, `graph:complete`). | P0 | 4d | F1.1, F1.2, F1.3, F1.5 |
| F1.7 | GraphEngine — Parallel | Parallel branch execution. Configurable worker pool. | P0 | 2d | F1.6 |
| F1.8 | Layer System | Interceptor pattern cho cross-cutting concerns. Built-in: UILayer, PersistenceLayer, ExecutionLimitsLayer. | P1 | 3d | F1.6 |
| F1.9 | Template Resolver | Resolve `{{#nodeId.key#}}` syntax trong prompts, templates, expressions. | P0 | 2d | F1.1 |
| F1.10 | DSL Serializer | Graph → JSON DSL. | P1 | 1d | F1.2, F1.5 |
| F1.11 | DSL Deserializer | JSON DSL → Graph. | P1 | 1d | F1.2, F1.5 |
| F1.12 | Execution Limits | Max steps, max execution time, max parallel nodes. Configurable per workflow. | P1 | 1d | F1.6, F1.8 |
| F1.13 | Custom Error Classes | WorkflowError, NodeExecutionError, SandboxError, MemoryError, AgentError. | P0 | 1d | — |

---

## F2. Core Nodes

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F2.1 | Start Node | Entry point. Defines workflow input variables (name, type, required, default). | P0 | 1d | F1.5 |
| F2.2 | End Node | Terminal node. Defines workflow outputs. | P0 | 1d | F1.5 |
| F2.3 | LLM Node | AI model invocation. Prompt template. Model selection. Temperature/max_tokens. Streaming. Memory toggle. | P0 | 5d | F1.5, F1.1, F1.9 |
| F2.4 | Code Node | Python/JS sandbox execution. Input variables injection. Output capture. Error handling. | P0 | 4d | F1.5, F8.1 |
| F2.5 | Condition Node | IF/ELSE branching. Boolean expression evaluation. True/false output handles. | P0 | 2d | F1.5, F1.1 |
| F2.6 | HTTP Request Node | External API calls. Method, URL, headers, body config. Response parsing. SSRF protection. | P0 | 3d | F1.5 |
| F2.7 | Template Node | Jinja2/ES6 template rendering. Variable injection from pool. | P1 | 2d | F1.5, F1.1 |
| F2.8 | Iteration Node | For-each loop over arrays. Spawns child GraphEngine per item. Index variable. | P1 | 4d | F1.6 |
| F2.9 | Loop Node | While loop with condition. Max iterations safety. Break/continue support. | P1 | 4d | F1.6 |
| F2.10 | Variable Aggregator Node | Merge variables from parallel branches into single output. | P1 | 2d | F1.5, F1.1 |
| F2.11 | Variable Assigner Node | Set/overwrite variable value at runtime. | P1 | 1d | F1.5, F1.1 |
| F2.12 | Knowledge Retrieval Node | Query workflow memory graph (FluxMem). Semantic/episodic/procedural search. | P1 | 3d | F1.5, F6.1 |
| F2.13 | Parameter Extractor Node | LLM-powered structured parameter extraction from text. | P2 | 3d | F2.3 |
| F2.14 | Question Classifier Node | LLM-powered N-way classification. Multiple output handles. | P2 | 3d | F2.3 |

---

## F3. File Explorer & Context Loading

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F3.1 | File Explorer Node | Native Electron dialog to browse & select local files/folders. Filter by extension. Exclude patterns (node_modules, .git). Max depth/limit. | P0 | 3d | — |
| F3.2 | File Reader Node | Read file content. Auto-detect format. Modes: `auto`, `markdown`, `plain`, `structured`. | P0 | 3d | F3.6 |
| F3.3 | Context Loader Node | Load directory tree as structured context for LLM. Tree visualization + file content. Configurable max files/chars. Output formatted for prompt injection. | P0 | 4d | F3.1, F3.2 |
| F3.4 | File Type Detection | Auto-detect file type by extension + content. Map to language for syntax highlighting. Binary detection. | P1 | 2d | — |
| F3.5 | Directory Tree Generator | Generate visual tree structure from directory path. Respect exclude patterns. | P0 | 1d | F3.1 |
| F3.6 | markitdown Integration | `markitdown` (Microsoft, 146k stars) convert file → markdown. CLI + Python API. Support: PDF, DOCX, PPTX, XLSX, images, audio, HTML, CSV, JSON, XML, ZIP, YouTube, EPUB. | P0 | 3d | — |
| F3.7 | markitdown Python Setup | Install `markitdown[all]` in sandbox Python env. | P0 | 1d | F3.6 |
| F3.8 | Markdown Parser (structured) | `marked` (GFM-compatible) for structured access mode. Extract headings, code blocks, links, tables, frontmatter. | P0 | 2d | — |
| F3.9 | PDF Text Extraction | Via markitdown. Supports scanned PDFs with OCR (optional LLM). | P1 | 1d | F3.6 |
| F3.10 | Office Document Conversion | markitdown: DOCX → MD, PPTX → MD, XLSX → MD. Preserve tables, headings, lists. | P1 | 1d | F3.6 |
| F3.11 | Image OCR | markitdown: EXIF metadata + optional LLM-based OCR for text in images. | P2 | 2d | F3.6 |

---

## F4. ReAct Agent

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F4.1 | ReAct Agent Node | Thought → Action → Observation loop. Configurable max iterations (default 25). Max time (default 300s). Early stop condition. | P0 | 5d | F2.3, F8.1 |
| F4.2 | Agent Tool Interface | Tool definition: name, description, parameters (JSON Schema), handler type. | P0 | 2d | — |
| F4.3 | Built-in Tools | `run_code`, `run_command`, `read_file`, `write_file`, `search_memory`, `http_request`. | P0 | 4d | F4.2, F8.1, F6.1 |
| F4.4 | Thought/Action Parser | Parse LLM output để extract action type + parameters. Handle malformed output. | P1 | 3d | F4.1 |
| F4.5 | Custom Tool Definition | Users define custom tools via JSON Schema. Register in workflow config. | P1 | 2d | F4.2 |
| F4.6 | Tool Permission System | Per-tool permissions. Whitelist/blacklist commands for shell. File path restrictions. | P2 | 2d | F4.2 |

---

## F5. Agent Orchestrator

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F5.1 | Agent Orchestrator Node | Manage team of sub-agents. Supervisor pattern. Configurable process type. | P0 | 5d | F4.1, F4.2 |
| F5.2 | Agent Definition | Role/Goal/Backstory per agent. Per-agent model selection. Per-agent tool assignment. `allow_delegation` flag. | P0 | 3d | — |
| F5.3 | Sequential Process | Tasks execute one by one. Each agent receives previous agent's output as context. | P0 | 3d | F5.1, F5.2 |
| F5.4 | Hierarchical Process | Supervisor decomposes task, delegates to workers, validates results. LLM-driven speaker selection. | P0 | 5d | F5.1, F5.2 |
| F5.5 | Hybrid Process | Mix sequential + hierarchical. Stage-based: some stages sequential, some hierarchical. | P1 | 4d | F5.3, F5.4 |
| F5.6 | Progress Ledger | Structured JSON evaluation per round: `is_request_satisfied`, `is_progress_being_made`, `is_in_loop`, `next_speaker`. (AutoGen pattern) | P0 | 4d | F5.1 |
| F5.7 | Stall Detection | Detect when agents stuck (no progress or in loop). Increment stall counter. | P0 | 2d | F5.6 |
| F5.8 | Auto Re-planning | When stalls exceed threshold → re-analyze state, update facts/plan, reset agents. | P1 | 4d | F5.7 |
| F5.9 | Agent Communication Protocol | Message types: task, result, question, delegation, feedback. Supervisor↔Worker, Worker→Worker (delegation). | P1 | 3d | F5.1 |
| F5.10 | Shared Team State | Typed dict shared across agents. Agent outputs, task results, messages, progress. Reducer functions for aggregation. | P1 | 3d | F5.1 |
| F5.11 | Planning Phase | Optional pre-execution planning. Task decomposition. Agent assignment. | P1 | 3d | F5.1, F5.2 |
| F5.12 | Sub-Workflow Node | Embed another workflow as a node. Pass inputs, get outputs. | P2 | 4d | F1.6 |

---

## F6. FluxMem Memory System

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F6.1 | Memory Graph Core | Heterogeneous graph structure. Nodes (semantic/episodic/procedural) + edges (ground/distill/refine). SQLite-backed. | P0 | 5d | F7.1 |
| F6.2 | Semantic Layer | Store facts, documents, code snippets, API docs, error patterns. Embedding-based similarity search. | P1 | 4d | F6.1 |
| F6.3 | Episodic Layer | Store past execution trajectories. Step-by-step records. Outcome + feedback. | P1 | 3d | F6.1 |
| F6.4 | Procedural Layer | Reusable skills/patterns distilled from successful episodes. Usage count, success rate, PEMS score. | P1 | 4d | F6.3 |
| F6.5 | Stage I: Initial Connection | Per-step online: semantic retrieval, episodic retrieval, procedural inheritance. Context assembly. | P1 | 4d | F6.2, F6.3, F6.4 |
| F6.6 | Stage II: Feedback Refinement | Per-step online: link expansion (under-connection), link pruning (over-connection), content reshaping (granularity). | P2 | 5d | F6.5 |
| F6.7 | Stage III: Long-term Consolidation | Offline periodic: trajectory clustering, skill distillation, PEMS calculation, convergence check. | P2 | 5d | F6.4 |
| F6.8 | Memory API for Nodes | `semantic_search()`, `episodic_search()`, `procedural_search()`, `get_context()`, `add_semantic()`, `record_step()`, `record_outcome()`. | P0 | 3d | F6.1 |
| F6.9 | Memory Persistence (SQLite) | Save/load memory graph to SQLite. Per-workflow `.db` file. | P0 | 3d | F6.1, F7.1 |
| F6.10 | Embedding Service (Local) | `multilingual-e5-small` via `@xenova/transformers`. 384-dim, 94 languages, ~118MB. `query:`/`passage:` prefix convention. | P0 | 2d | — |

---

## F7. Database & Storage

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F7.1 | SQLite Setup | `better-sqlite3`. Schema migration. WAL mode. Per-workflow `.db` file. | P0 | 2d | — |
| F7.2 | Workflow Repository | CRUD operations for workflow DSL via SQLite. | P0 | 2d | F7.1 |
| F7.3 | Run Repository | Store/query execution history, node run records. | P0 | 2d | F7.1 |
| F7.4 | Memory Tables | Semantic/episodic/procedural tables with BLOB embeddings. | P0 | 2d | F7.1 |
| F7.5 | Vector Search | Brute-force cosine similarity on 384-dim embeddings. | P0 | 2d | F7.4, F6.10 |
| F7.6 | Env Variables Table | Encrypted storage for secrets/API keys. | P1 | 1d | F7.1 |

---

## F8. Sandbox System

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F8.1 | Sandbox Core | Per-workflow isolated environment. Create/destroy lifecycle. File system + process execution. | P0 | 5d | — |
| F8.2 | Sandbox Filesystem | Tempdir-based. Read/write/list files. Path isolation. | P0 | 3d | F8.1 |
| F8.3 | Process Execution | `exec(command)` and `execCode(language, code)`. stdout/stderr capture. Timeout. | P0 | 4d | F8.1 |
| F8.4 | Python Runtime | Execute Python code in sandbox. pip install support. | P0 | 3d | F8.3 |
| F8.5 | JavaScript Runtime | Execute JS/TS code in sandbox. npm support. | P1 | 3d | F8.3 |
| F8.6 | Shell Command Node | Execute arbitrary shell commands in sandbox. Whitelist option. | P0 | 2d | F8.3 |
| F8.7 | File Write Node | Write content to file in sandbox. | P0 | 1d | F8.2 |
| F8.8 | Environment Variables | Inject env vars into sandbox. Mask secrets. | P1 | 1d | F8.1 |
| F8.9 | Sandbox Snapshot | Save/restore sandbox state. For debugging and re-run. | P2 | 3d | F8.1 |

---

## F9. Triggers

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F9.1 | Manual Trigger | User-initiated workflow execution. Input form for variables. | P0 | 1d | — |
| F9.2 | Webhook Trigger | HTTP webhook endpoint. POST body as input. | P2 | 3d | F1.6 |
| F9.3 | Schedule Trigger | Cron-based scheduling. | P2 | 3d | F1.6 |

---

## F10. Frontend — Workflow Canvas

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F10.1 | Workflow Editor | React Flow main canvas. Drag-drop. Pan/zoom. Minimap. Background grid. | P0 | 5d | — |
| F10.2 | BaseNode Component | Shared node wrapper. Header (icon + title + status). Input/output handles. Selection ring. | P0 | 3d | — |
| F10.3 | Node Type Registry | `NodeComponentMap` + `PanelComponentMap`. Dynamic registration. | P0 | 2d | F10.2 |
| F10.4 | Block Selector (Node Picker) | Categorized, searchable menu. Drag to add. Categories: AI, Logic, Tools, Agent, Trigger. | P0 | 4d | F10.3 |
| F10.5 | Toolbar | Run, Stop, Save, Export, Undo, Redo, Auto-layout, Zoom controls. | P0 | 3d | — |
| F10.6 | Node Config Panel | Right sidebar. Dynamic panel based on selected node type. | P0 | 4d | F10.3 |
| F10.7 | Edge Connections | Custom edge type. Animated when running. Label support. Source/target handle validation. | P0 | 2d | — |
| F10.8 | Run Monitor | Bottom panel. Real-time execution log. Per-node status (waiting/running/complete/error). | P1 | 4d | F10.1 |
| F10.9 | Undo/Redo | Zustand temporal. State history. Keyboard shortcuts (Ctrl+Z/Y). | P1 | 3d | — |
| F10.10 | Auto-Layout | Dagre-based automatic node positioning. | P2 | 3d | — |
| F10.11 | Keyboard Shortcuts | Delete node, copy/paste, select all, run, save. | P2 | 2d | — |
| F10.12 | Canvas Comments | Sticky notes on canvas. For documentation. | P2 | 2d | — |

---

## F11. Frontend — Node-Specific Panels

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F11.1 | LLM Panel | Model selector. Prompt editor (multiline). System prompt. Temperature/max_tokens sliders. Memory toggle. | P0 | 4d | F10.6 |
| F11.2 | Code Panel | Language selector (Python/JS). Code editor (Monaco). Input variables mapping. | P0 | 4d | F10.6 |
| F11.3 | Condition Panel | Expression editor. True/false branch labels. Variable picker integration. | P0 | 2d | F10.6 |
| F11.4 | HTTP Panel | Method selector. URL input. Headers editor (key-value). Body editor (JSON). | P1 | 3d | F10.6 |
| F11.5 | Template Panel | Template editor with syntax highlighting. Variable insertion helper. | P1 | 2d | F10.6 |
| F11.6 | Iteration/Loop Panel | Array selector (iteration). Condition editor (loop). Max iterations. | P1 | 2d | F10.6 |
| F11.7 | ReAct Agent Panel | Model selector. System prompt. Tool checklist. Max iterations slider. Memory toggle. | P0 | 4d | F10.6 |
| F11.8 | Orchestrator Panel | Task description. Expected output. Process type selector. Agent list with add/remove/edit. | P0 | 5d | F10.6 |
| F11.9 | Agent Definition Editor | Name, role, goal, backstory fields. Model selector per agent. Tool checklist per agent. | P0 | 4d | F11.8 |
| F11.10 | Progress Ledger Viewer | Real-time JSON display of ledger state. Stall counter. Round counter. | P1 | 3d | F11.8 |
| F11.11 | File Explorer Panel | Browse button (native dialog). Selected path display. File count. Filter config. | P0 | 3d | F10.6 |
| F11.12 | Context Loader Panel | Root path. File type filter. Exclude patterns. Max files/chars. Tree preview. | P0 | 3d | F10.6 |
| F11.13 | Knowledge Retrieval Panel | Query input. Layer selector (semantic/episodic/procedural). Top-k. | P1 | 2d | F10.6 |
| F11.14 | Variable Selector Component | Tree view: nodeId → keys. Search. Used by all panels. | P0 | 3d | — |
| F11.15 | Memory Inspector Panel | Graph view. Search. Stats. | P2 | 4d | — |

---

## F12. IPC & Integration

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F12.1 | Workflow Run IPC | Execute workflow from renderer → main process. Return stream of events. | P0 | 4d | F1.6 |
| F12.2 | Sandbox Management IPC | Create/destroy sandbox. Execute code/commands. File operations. | P0 | 3d | F8.1 |
| F12.3 | Memory IPC | Search memory. Record outcomes. Save/load memory graph. | P1 | 3d | F6.1 |
| F12.4 | Real-time Event Streaming | Stream engine events to UI via IPC. Node status updates. Progress. | P1 | 3d | F12.1 |
| F12.5 | AI Provider IPC | Chat, stream chat, list models, test connection. OpenAI + Ollama. | P0 | 2d | — |
| F12.6 | Workflow CRUD IPC | Save, load, list, delete workflows. DSL persistence via SQLite. | P0 | 2d | F1.8, F7.2 |
| F12.7 | DSL Import/Export IPC | Export workflow as JSON file. Import from file. | P2 | 2d | F1.10, F1.11 |
| F12.8 | Error Handling + Retry | Wrap IPC errors. Retry logic for transient failures. | P1 | 2d | — |

---

## F13. Dashboard & Navigation

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F13.1 | Dashboard — Workflow List | Card grid. Name, description, last modified, status. Search/filter. | P0 | 3d | F12.6 |
| F13.2 | Create Workflow | New workflow button. Name input. Template selection (blank or pre-built). | P0 | 2d | F12.6 |
| F13.3 | Template Gallery | Pre-built workflow templates: Code Review, Coding Agent, Full SDLC, Sprint Automation. | P1 | 3d | F1.8 |
| F13.4 | Workflow Import/Export UI | Export button. Import from file. | P2 | 2d | F12.7 |
| F13.5 | Breadcrumb Navigation | Dashboard → Workflows → Workflow Name. Clickable segments. Back button. | P0 | 1d | — |
| F13.6 | Settings Page | API keys (OpenAI, Ollama). Model selection. Theme toggle. Sandbox config. markitdown status. | P0 | 2d | — |

---

## F14. Theme & UI Polish

| ID | Feature | Mô tả | Priority | Effort | Depends On |
|---|---|---|---|---|---|
| F14.1 | Dark/Light Theme | CSS variables. Toggle in sidebar. Persist preference. | P0 | 2d | — |
| F14.2 | SVG Icons | Custom SVG icon components for all node types and UI elements. No emojis. | P0 | 3d | — |
| F14.3 | Responsive Layout | Sidebar collapse. Panel resize. Canvas fills available space. | P1 | 2d | — |
| F14.4 | Monaco Editor Integration | Code editor for Code nodes, Template nodes, expression editors. Theme-aware. | P1 | 2d | — |
| F14.5 | Loading States | Skeleton loaders. Spinner for node execution. Progress bars. | P2 | 2d | — |
| F14.6 | Error Handling UI | Error toast. Per-node error display. Error details panel. ErrorBoundary. | P1 | 2d | — |
| F14.7 | Error Boundary | React ErrorBoundary. Catch render errors. Fallback UI. | P1 | 1d | — |

---

## Feature Summary

| Priority | Count | Total Effort |
|---|---|---|
| **P0** (Must-have) | 55 | ~140 days |
| **P1** (Should-have) | 32 | ~80 days |
| **P2** (Nice-to-have) | 15 | ~45 days |
| **Total** | **102 features** | **~265 days** |

---

## Milestone Roadmap

| Milestone | Features | Target |
|---|---|---|
| **M1: Engine + Core Nodes** | F1.*, F2.1-F2.6, F1.9 | Week 3 |
| **M2: Database + Sandbox + File System** | F7.*, F8.*, F3.1-F3.3, F3.5-F3.8 | Week 5 |
| **M3: Memory + Embedding** | F6.*, F7.5 | Week 7 |
| **M4: Agents + Orchestrator** | F4.*, F5.*, F9.1 | Week 9 |
| **M5: Frontend Canvas + Panels** | F10.*, F11.*, F13.*, F14.* | Week 11 |
| **M6: IPC + Integration + Polish** | F12.*, F3.9-F3.11, F13.3, F14.* | Week 12 |
