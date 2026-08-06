# Built-in skill context audit — 2026-08-06

## Finding

EvoFlux bundled 45 skills. First-party member profiles assigned two to five
generic methodology skills each, and `SkillPreloadHook` inserted every assigned
body into first-turn message history as synthetic tool results. The `skill`
tool also repeated the complete name catalog in its always-visible schema.

This made instructions compete with code-owned role prompts and native tool
schemas. Moving the bodies out of the system prompt did not make the injection
context-neutral; the same text still entered the model history before it chose
a workflow.

## Retention rule

A bundled skill remains only when it owns a specialized artifact or EvoFlux
operational workflow that cannot be communicated adequately by a native tool
schema and role prompt. Generic engineering behavior belongs in the role
contract; native capability usage belongs in the tool schema.

## Retained catalog (13)

- Artifact/design: `algorithmic-art`, `canvas-design`, `docx`,
  `frontend-design`, `pdf`, `pptx`, `theme-factory`, `xlsx`.
- EvoFlux operations: `mcp-installer`, `plugin-installer`, `skill-installer`,
  `self-healing`.
- Provider lifecycle: `review-pull-requests`.

These skills are progressively disclosed. Their names and bodies are not
present in normal context. The model must deliberately list/load one, or the
user must explicitly select it with `/skill:<name>`.

## Removed catalog (32)

The removed bundles were generic methodology, duplicated native tool
contracts, depended on obsolete capabilities, or duplicated another retained
workflow:

`api-and-interface-design`, `brand-guidelines`,
`browser-testing-with-devtools`, `ci-cd-and-automation`,
`code-graph-navigation`, `code-review-and-quality`, `code-simplification`,
`context-engineering`, `debugging-and-error-recovery`, `decision-analysis`,
`deep-research`, `deprecation-and-migration`, `doc-coauthoring`,
`documentation-and-adrs`, `doubt-driven-development`,
`frontend-ui-engineering`, `git-workflow-and-versioning`, `idea-refine`,
`incremental-implementation`, `interview-me`,
`observability-and-instrumentation`, `performance-optimization`,
`planning-and-task-breakdown`, `red-team-and-critique`,
`research-and-fact-checking`, `security-and-hardening`,
`shipping-and-launch`, `source-driven-development`,
`spec-driven-development`, `test-driven-development`, `using-agent-skills`,
and `writing-and-deliverables`.

## Runtime invariants

- Built-in agent profiles assign no skills.
- Agent `skills:` metadata never preloads a body.
- Normal request prose never selects a skill.
- The always-visible `skill` schema never enumerates the catalog.
- `skill(action="list")` is the only catalog expansion path.
- `skill(action="load", skill_name=...)` and explicit `/skill:<name>` are the
  only body expansion paths.
- `code_graph` owns symbol navigation entirely; no graph skill mirrors it.
