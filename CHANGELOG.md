# Changelog

All notable changes to EvoFlux are documented in this file.

## [1.0.0] - 2026-08-27

EvoFlux 1.0.0 is the first stable release.

### Highlights

- Introduced Evo Agent Specs (EASD), a repository-backed specification-driven
  workflow with guided actions, phase retry, review handoff, real-time events,
  traceability, recovery, and local runtime data.
- Expanded agent-team workflows with explicit mode-lead team selection and
  safer delegation and handoff behavior.
- Added QwenCloud support and optimized prompt-cache request shaping across
  supported Anthropic, Bedrock, Codex, DeepSeek, Gemini, OpenAI-compatible,
  OpenRouter, and xAI provider paths.
- Expanded code-graph coverage and hardened language parsing across the primary
  and extended parser set, while isolating and caching index builds.
- Improved Coding workspace navigation, multi-repository chat setup, transcript
  preload/rendering, and request-ingress feedback.

### Added

- Repository knowledge-base initialization, portable EASD project contracts,
  durable trace records, and scoped memory.
- Shared browser-tool result plumbing and richer workbench integration.
- Separate context and turn usage totals for clearer token accounting.

### Changed

- Standardized web selection controls and improved command-message
  presentation.
- Removed the aggregate skill-bundle size limit and reduced built-in skill
  catalog overhead.
- Retired the non-executable terminal agent tool in favor of executable process
  and approved tool paths.
- Reorganized contributor and product documentation under `documents/`.

### Fixed

- Hardened SQLite concurrency, foreign-key repair, migration reconciliation,
  runtime teardown, and cleanup behavior.
- Repaired graph API schemas and numerous code-graph parser edge cases.
- Fixed coding repository visibility, chat working state, plugin scaffolding,
  and overlapping lead selectors.
- Improved outbound redaction and prompt finalization before summarization.

For the curated release overview, see
[`documents/releases/v1.0.0.md`](documents/releases/v1.0.0.md).

[1.0.0]: https://github.com/evoelsewhere/evoflux/compare/v0.0.8...v1.0.0
