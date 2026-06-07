<p align="center">
  <img src="build/icon.png" width="128" height="128" alt="Evoflux Logo">
</p>

<h1 align="center">Evoflux</h1>

<p align="center">
  <strong>AI-Powered Workflow Automation for Software Development</strong>
</p>

<p align="center">
  Visual workflow builder with multi-provider AI integration, ReAct agents, and real-time execution monitoring.
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#node-types">Node Types</a> •
  <a href="#ai-providers">AI Providers</a> •
  <a href="#build">Build</a> •
  <a href="#architecture">Architecture</a>
</p>

---

## Features

### Workflow Editor
- **Visual Canvas** — Drag-and-drop workflow builder powered by ReactFlow
- **21 Node Types** — Triggers, AI, Logic, Tools, Agents, and more
- **Condition Branching** — True/False paths with visual labels
- **Loops & Iteration** — While loops and for-each iteration over arrays
- **Variable System** — Variable aggregator, assigner, and template nodes
- **Auto Layout** — Dagre-based layout in vertical (TB) or horizontal (LR) direction
- **Import/Export** — Save and load workflows as JSON files

### AI Integration
- **Multi-Provider Support** — OpenAI, Anthropic, Ollama, OpenAI-Compatible, Claude CLI, GitHub Copilot CLI
- **Multiple Provider Instances** — Add as many providers as you need, each with its own API key and model
- **Per-Node Provider Selection** — Each LLM/Agent node can use a different provider
- **Custom Endpoints** — Azure OpenAI, Groq, Together, or any OpenAI-compatible API

### AI Assistant
- **Workflow Assistant** — Chat-based AI that creates and modifies workflows using tools
- **ReAct Agent Pattern** — Multi-step reasoning: Thought → Action → Observation loop
- **10 Workflow Tools** — get_workflow, create_node, connect_nodes, update_node, delete_node, and more
- **Real-Time Canvas Updates** — See nodes appear on canvas as the assistant creates them

### Agent System
- **ReAct Agent Node** — Thought → Action → Observation loop with tool execution
- **Agent Orchestrator** — Multi-agent teams with sequential or hierarchical process
- **6 Built-In Tools** — run_code, run_command, read_file, write_file, search_memory, http_request
- **Sandboxed Execution** — Code runs in isolated sandbox with configurable permissions

### Execution Engine
- **Graph Engine** — Topological sort with parallel execution support
- **Real-Time Monitoring** — Node-level progress tracking with status indicators
- **Run History** — All runs persisted to SQLite with per-node execution traces
- **Input Variables** — Define variables in Start node, fill values before running

### Memory System
- **3-Tier Memory** — Semantic, Episodic, and Procedural memory layers
- **Knowledge Graph** — Memory edges for relationship tracking
- **Cross-Run Learning** — Patterns extracted from past executions
- **Memory Consolidation** — Episodic → Procedural memory promotion

### Data Persistence
- **SQLite Database** — All data stored in `~/.evoflux/evoflux.db`
- **Auto-Save** — 500ms debounced save on every change
- **Sync Save on Close** — Synchronous save via `beforeunload` ensures no data loss
- **Single Source of Truth** — No localStorage, no electron-store, only SQLite

### Appearance
- **Dark/Light Theme** — System-aware theme switching
- **10 Accent Colors** — Blue, Violet, Rose, Orange, Amber, Emerald, Teal, Cyan, Pink, Indigo
- **Font Customization** — Size (Small/Medium/Large) and Family (Inter/System/Mono)
- **Canvas Styling** — Dot size, dot color, node border radius
- **Compact Mode** — Reduced padding for denser UI
- **macOS-Style Dock** — Floating pill dock at bottom with hover labels

---

## Quick Start

### Prerequisites
- Node.js 18+ 
- npm 9+

### Install & Run

```bash
# Clone the repository
git clone https://github.com/khuonghung/evoflux.git
cd evoflux

# Install dependencies
npm install

# Rebuild native modules for Electron
npx electron-rebuild -f -w better-sqlite3

# Start development
npm run dev
```

### First Workflow

1. Click **+** in the dock to add nodes
2. Add a **Manual Trigger** node
3. Add an **LLM** node and configure your provider
4. Connect them by dragging from output handle to input handle
5. Click **Run** in the dock to execute

---

## Node Types

### Triggers
| Node | Description |
|------|-------------|
| Manual Trigger | User-initiated execution with input variables |
| Webhook | HTTP webhook endpoint |
| Schedule | Cron-based scheduling |

### AI & LLM
| Node | Description |
|------|-------------|
| LLM | Large Language Model call with configurable provider/model |
| Parameter Extractor | Extract structured data from text using AI |
| Question Classifier | Classify questions into categories |
| Knowledge Retrieval | Search semantic/episodic/procedural memory |

### Logic
| Node | Description |
|------|-------------|
| Condition | Branch workflow based on expression (true/false) |
| Iteration | For-each loop over array items |
| Loop | While loop with condition |
| Variable Aggregator | Merge variables from multiple branches |
| Variable Assigner | Set variable values |
| Template | String template with variable interpolation |

### Tools
| Node | Description |
|------|-------------|
| Code | Execute Python/JavaScript/TypeScript/Shell code |
| Shell | Run shell commands |
| HTTP Request | Make HTTP calls (GET/POST/PUT/DELETE) |
| File Explorer | Browse and filter files in a directory |
| File Reader | Read file contents (text, markdown, PDF) |
| File Write | Write content to files |
| Context Loader | Load project context for AI analysis |

### Agents
| Node | Description |
|------|-------------|
| ReAct Agent | Thought → Action → Observation loop with tools |
| Agent Orchestrator | Multi-agent team with sequential/hierarchical process |
| Sub-Workflow | Execute another workflow as a sub-process |

### Other
| Node | Description |
|------|-------------|
| Comment | Add notes and documentation to canvas |

---

## AI Providers

### Supported Providers

| Provider | Type | Authentication |
|----------|------|----------------|
| OpenAI | `openai` | API Key |
| Anthropic | `anthropic` | API Key |
| Ollama | `ollama` | Local (no key) |
| OpenAI-Compatible | `openai-compatible` | API Key + Custom URL |
| Claude CLI | `claude-cli` | CLI auth |
| GitHub Copilot CLI | `copilot-cli` | GitHub auth |

### Adding a Provider

1. Go to **Settings** → **AI Providers**
2. Select provider type from dropdown
3. Click **Add Provider**
4. Enter API Key, Base URL, and Default Model
5. Click **Test Connection** to verify
6. Set as **Default** if needed

### Custom Endpoints

For Azure OpenAI, Groq, Together, or other compatible APIs:

1. Add an **OpenAI-Compatible** provider
2. Set **Base URL** to your endpoint (e.g., `https://your-resource.openai.azure.com/openai/deployments/gpt-4o/`)
3. Set **API Key** to your key
4. Add model names to **Models** field

---

## Build

### Development
```bash
npm run dev          # Start Electron dev server
npm run build        # Build for production
npm run typecheck    # Run TypeScript checks
npm run lint         # Run ESLint
```

### Production Installers
```bash
npm run build:mac    # macOS DMG + ZIP (x64 + arm64)
npm run build:win    # Windows NSIS installer (x64)
npm run build:all    # Both platforms
```

### Output
```
dist/
├── Evoflux-1.0.0.dmg              # macOS Intel
├── Evoflux-1.0.0-arm64.dmg        # macOS Apple Silicon
├── Evoflux-1.0.0-mac.zip          # macOS Intel (zip)
├── Evoflux-1.0.0-arm64-mac.zip    # macOS Apple Silicon (zip)
└── Evoflux Setup 1.0.0.exe        # Windows x64
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Electron Main Process                                       │
│  ├── IPC Handlers (workflow, ai, sandbox, memory, dsl)       │
│  ├── SQLite Database (~/.evoflux/evoflux.db)                 │
│  └── Graph Engine (topological sort, parallel execution)     │
├─────────────────────────────────────────────────────────────┤
│  Preload (contextBridge)                                     │
│  └── window.api = { workflow, ai, sandbox, memory, settings }│
├─────────────────────────────────────────────────────────────┤
│  Renderer (React + Vite)                                     │
│  ├── ReactFlow Canvas (nodes, edges, drag-and-drop)          │
│  ├── Zustand Stores (workflow, provider, settings, assistant)│
│  ├── AI Assistant (ReAct engine + 10 workflow tools)          │
│  ├── Node Popup (per-node settings editor)                   │
│  ├── Run Panel (real-time execution monitor)                 │
│  └── Floating Dock (macOS-style navigation)                  │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow
```
Renderer State (zustand)
    │
    ├── onChange → window.api.workflow.save() → SQLite
    ├── onChange → window.api.settings.save() → SQLite
    │
    └── startup → window.api.workflow.load() → SQLite → zustand
```

### Project Structure
```
evoflux/
├── electron/                 # Main process
│   ├── main.ts              # App entry point
│   ├── preload.ts           # Context bridge
│   └── ipc/                 # IPC handlers
│       ├── ai.ts            # AI provider integration
│       ├── workflow.ts      # Workflow CRUD
│       ├── workflow-runner.ts # Execution engine
│       ├── sandbox.ts       # Code sandbox
│       ├── memory.ts        # Memory system
│       └── dsl.ts           # Import/export
├── src/                     # Renderer process
│   ├── assistant/           # AI Assistant
│   │   ├── engine.ts        # ReAct loop
│   │   ├── tools.ts         # 10 workflow tools
│   │   └── prompt.ts        # System prompt
│   ├── components/
│   │   ├── workflow/        # Canvas components
│   │   │   ├── WorkflowEditor.tsx
│   │   │   ├── NodePopup.tsx
│   │   │   ├── RunPanel.tsx
│   │   │   ├── AssistantPanel.tsx
│   │   │   ├── BlockSelector.tsx
│   │   │   └── nodes/       # Node components
│   │   ├── layout/
│   │   │   └── Sidebar.tsx  # Floating dock
│   │   ├── dashboard/
│   │   │   └── Dashboard.tsx
│   │   └── settings/
│   │       └── SettingsPage.tsx
│   ├── engine/              # Execution engine
│   │   ├── graph-engine.ts  # Graph execution
│   │   ├── node-factory.ts  # Node base class
│   │   ├── nodes/           # Node implementations
│   │   ├── agent/           # ReAct agent system
│   │   └── db/              # Database layer
│   │       ├── database.ts  # SQLite adapter
│   │       ├── schema.ts    # Schema + migrations
│   │       └── repos.ts     # CRUD functions
│   ├── stores/              # State management
│   │   ├── workflowStore.ts
│   │   ├── providerStore.ts
│   │   ├── settingsStore.ts
│   │   └── assistantStore.ts
│   └── utils/
│       └── layout.ts        # Dagre auto-layout
├── build/                   # App icons
│   ├── icon.icns            # macOS
│   ├── icon.ico             # Windows
│   └── icon.png             # Generic
└── package.json
```

---

## Database Schema

All data persists to SQLite at `~/.evoflux/evoflux.db`:

| Table | Purpose |
|-------|---------|
| `settings` | Key-value settings (providers, appearance, etc.) |
| `providers` | AI provider instances with API keys |
| `workflows` | Workflow definitions (nodes + edges JSON) |
| `runs` | Workflow execution history |
| `node_runs` | Per-node execution traces |
| `memory_semantic` | Semantic memory entries |
| `memory_episodic` | Episodic memory (past executions) |
| `memory_procedural` | Extracted patterns and procedures |
| `memory_edges` | Knowledge graph relationships |
| `env_variables` | Per-workflow environment variables |
| `schema_version` | Migration tracking |

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+S` / `Cmd+S` | Save workflow |
| `Ctrl+Z` / `Cmd+Z` | Undo |
| `Ctrl+Y` / `Cmd+Shift+Z` | Redo |
| `Delete` | Delete selected node |
| `Shift+Click` | Multi-select nodes |
| `Scroll` | Pan canvas |
| `Pinch` | Zoom canvas |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Desktop | Electron 33 |
| Frontend | React 18 + TypeScript |
| Build | Vite (electron-vite) |
| Canvas | ReactFlow 11 |
| UI Library | Ant Design 5 |
| State | Zustand 5 |
| Database | better-sqlite3 |
| Layout | Dagre |
| Code Editor | Monaco Editor |
| AI Client | OpenAI SDK |

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Commit Convention

```
feat:     New feature
fix:      Bug fix
docs:     Documentation
style:    Formatting
refactor: Code restructuring
test:     Tests
chore:    Build/tooling
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

<p align="center">
  Built with Electron + React + TypeScript
</p>
