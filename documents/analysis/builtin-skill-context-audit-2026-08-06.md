# Built-in skill context audit — 2026-08-06

## Original finding

EvoFlux bundled 45 skills. First-party member profiles assigned two to five
generic methodology skills each, and `SkillPreloadHook` inserted every assigned
body into first-turn message history as synthetic tool results. The `skill`
tool also repeated the complete name catalog in its always-visible schema.

This made instructions compete with code-owned role prompts and native tool
schemas. Moving the bodies out of the system prompt did not make the injection
context-neutral; the same text still entered the model history before it chose
a workflow.

## Retention rule

A bundled skill remains only when it owns an optional, problem-specific
workflow with a clear trigger: a Work/Coding method, specialized artifact,
EvoFlux operation, or progressively disclosed workflow for a native tool whose
correct use requires more guidance than its execution schema. Always-applicable
behavior belongs in the role contract; hard execution constraints remain in
the native tool schema and service boundary.

## Curated catalog (25)

- Work workflows: `work-data-analysis`, `work-decision`, `work-planning`,
  `work-research`, and `work-writing`, behind the implicit `work-router`.
- Coding workflows: `coding-debugging`, `coding-implementation`,
  `coding-investigation`, `coding-migration`, `coding-performance`,
  `coding-review`, `coding-security`, and `coding-testing`, behind the implicit
  `coding-router`.
- Coding tool workflow: `code-graph-navigation` is independently discoverable
  for exact-symbol structural navigation while execution remains owned by the
  native `code_graph` tool.
- Work artifacts/design: `algorithmic-art`, `canvas-design`, and
  `theme-factory`.
- Coding provider lifecycle: `review-pull-requests`.
- Shared operational workflows: `frontend-design`, `mcp-installer`,
  `plugin-installer`, `skill-installer`, and `self-healing`.

The mode projection is deliberate: Work sees 14 relevant entries and Coding
sees 16; only the five operational workflows are shared. User and project
skills default to both modes and can be scoped to Work, Coding, or Both in
Settings. EvoFlux persists that choice in a hidden `.evoflux.json` sidecar so
portable `SKILL.md` frontmatter remains limited to `name` and `description`.

These skills are progressively disclosed. A bounded routing catalog contains
only implicit skill names, descriptions, and locators; bodies are absent until
activation. Broad Work/Coding specialists are explicit-only and named by their
mode router. The narrow `code-graph-navigation` integration remains implicit so
an exact-symbol request can select it without preloading its body.

## Removed catalog (31)

The removed bundles were generic methodology, duplicated native tool
contracts, depended on obsolete capabilities, or duplicated another retained
workflow:

`api-and-interface-design`, `brand-guidelines`,
`browser-testing-with-devtools`, `ci-cd-and-automation`,
`code-review-and-quality`, `code-simplification`,
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

## Runtime invariants after the harness refactor

- Built-in agent profiles assign no skills.
- Agent `skills:` is an explicit user-owned preload contract; absent assignment
  does not load a body.
- Normal request prose is never converted to a query or hard-selected by the
  server. The model chooses from Tier-1 descriptions.
- The always-visible catalog is mode/policy filtered and budgeted to 2%/8K
  UTF-8 bytes.
- `skill(action="load", skill_name=...)`, explicit `$name` or
  `/skill:<name>`, and an agent assignment are the only body expansion paths;
  all reject out-of-mode or invalid bundles.
- Activation returns a revisioned body, canonical directory, and bounded
  resource manifest; `read_resource` enforces relative-path containment and a
  size limit.
- Exact activations survive compaction; stale ephemeral loaded markers do not.
- Project/user collisions and malformed metadata produce diagnostics instead
  of silently breaking or hiding the whole catalog.
- `code-graph-navigation` owns optional workflow guidance; `code_graph` owns
  execution, exact-symbol validation, traversal, and safety independently. The
  skill is progressively loaded and never injected at mode level.
