# Evoflux

AI Automation Workflow for SDLC

Evoflux is a visual workflow automation platform powered by AI, designed to streamline the Software Development Life Cycle. Build, run, and manage complex AI-driven workflows with a drag-and-drop canvas.

## Features

- Visual workflow canvas with drag-and-drop node editing
- Multi-provider AI support (OpenAI, Anthropic, Ollama, OpenAI-Compatible)
- ReAct Agent with tool execution (code, shell, file, HTTP)
- Condition branching, loops, iteration, variable management
- Real-time run monitoring with node-level progress tracking
- Input variables for interactive workflow execution
- Auto-save with persistent storage
- Customizable appearance (themes, accent colors, fonts)
- Workflow import/export as JSON
- SQLite database for run history and memory

## Tech Stack

- Electron + React + TypeScript
- Vite (electron-vite)
- ReactFlow for canvas
- Ant Design for UI components
- Zustand for state management
- better-sqlite3 for persistence

## Getting Started

```bash
npm install
npm run dev
```

## Build

```bash
npm run build
```

## License

MIT
