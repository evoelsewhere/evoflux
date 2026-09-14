<div align="center">
  <img src="web/public/brand-assets/evoflux-app-icon.png" width="72" height="72" alt="EvoFlux logo" />

  # EvoFlux

  **A local-first desktop workspace for AI agent teams.**

  EvoFlux brings agent conversations, files, terminal, browser, git, and
  verification into one workspace. Use Work for general tasks and Coding for
  repository-aware development.

  [![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-2563EB.svg)](LICENSE)
  [![Desktop app](https://img.shields.io/badge/Product-Desktop-1764FF)](desktop/)
  [![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](pyproject.toml)
  [![Tauri v2](https://img.shields.io/badge/Tauri-v2-FFC131?logo=tauri&logoColor=white)](desktop/)

  **[Download](#download)** · **[Run from source](#run-from-source)** ·
  **[Documentation](#documentation)**
</div>

## Highlights

- **Work and Coding modes** for cowork tasks and persistent repositories.
- **Lead-and-specialist teams** with per-agent models, skills, tools, and
  permissions.
- **Bring your own model** through hosted, cloud, routed, or local providers.
- **Repository-aware Coding** with code search, symbol relationships, LSP
  feedback, git workflows, and reviewable diffs.
- **Spec-first delivery** through Evo Agent Specs (EASD), with user-approved
  specifications, verification, and evidence-based convergence.
- **Local control** with inspectable history, permissions, sandboxing, and
  outbound data protection.
- **Memory, plugins, MCP, scheduling, and browser tooling** are available as
  integrated workspace capabilities.

## Download

Download the latest desktop release from
[GitHub Releases](https://github.com/evoelsewhere/evoflux/releases). Packages
are available for macOS, Windows, and Linux. The desktop packages include the
native Python sidecar.

Linux packages should be installed through the system package manager, for
example:

```sh
sudo apt install ./EvoFlux_*_amd64.deb
```

WebBridge is an optional browser companion distributed separately in the
[evo-webbridge repository](https://github.com/evoelsewhere/evo-webbridge).

## Run from source

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [Bun](https://bun.sh/)
- Rust and the [Tauri CLI](https://v2.tauri.app/start/prerequisites/)
- Tauri prerequisites for your operating system

### Setup

```sh
git clone https://github.com/evoelsewhere/evoflux.git
cd evoflux

uv sync
cd web && bun install && cd ..
```

Start the development app with:

```sh
# React UI + local API
make dev-web

# React UI + local API + Tauri desktop shell
make dev-desktop
```

`make dev` is an alias for `make dev-web`. EvoFlux is developed and shipped as
a desktop product; the web development server is an internal development
surface.

On first launch, connect a model provider, then start a Work session or open a
repository in Coding mode.

## Documentation

The README stays intentionally high-level. Detailed contracts and guides live
under [`documents/`](documents/):

- [Documentation index](documents/README.md)
- [EASD methodology](documents/reference/easd-methodology.md)
- [Evo Agent Specs guide](documents/guides/agent-specification-driven-development.md)
- [Agent Plugins guide](documents/guides/agent-plugins.md)
- [Coding architecture](documents/architecture/)
- [Development guide](documents/development/README.md)

## Architecture at a glance

```text
Tauri desktop shell
        ↓
React UI  ↔  local FastAPI sidecar
        ↓
local state, agent runtime, repositories, and model providers
```

The app keeps the main runtime and project state on the user's machine. Model
providers are replaceable, while the harness handles context, tools,
permissions, memory, and verification.

## Project layout

```text
app/        FastAPI sidecar, agents, code context, memory, scheduler, MCP
web/        React interface
desktop/    Tauri shell and Python sidecar packaging
seed/       Work and Coding blueprints, skills, and config
tests/      Backend and frontend tests
documents/  Architecture, feature contracts, guides, and records
```

## Contributing

Issues and pull requests are welcome. Keep changes focused and include the
smallest relevant test run. Report vulnerabilities privately through GitHub
Security Advisories.

## License

EvoFlux is released under the [Apache License 2.0](LICENSE).
