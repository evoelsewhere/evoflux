# Skill harness standards audit — 2026-08-06

## Decision

EvoFlux now treats Agent Skills as progressively disclosed runtime packages,
not prompt fragments and not a request-search subsystem. A portable skill may
legally contain only `SKILL.md`, but an EvoFlux-distributed production skill is
expected to add client metadata, activation evals, and only the references,
scripts, assets, or examples that its workflow actually needs.

The runtime contract is:

1. Discover and validate metadata without reading instruction bodies into the
   model context.
2. Render a mode- and policy-filtered catalog containing only name,
   description, and locator. Budget it to 2% of the model context window, with
   an 8,000-byte fallback.
3. Let the model select by semantic fit, or let the user select explicitly.
   Never turn normal request prose into a server-side skill search query.
4. Load one exact `SKILL.md` body after selection.
5. List bundle resources at activation and read an individual text resource
   only when the loaded workflow needs it.

## Sources reviewed

The audit used official documentation and pinned repository snapshots rather
than third-party summaries:

- [Agent Skills specification](https://agentskills.io/specification) and
  [client implementation guide](https://agentskills.io/client-implementation/adding-skills-support),
  repository snapshot `agentskills/agentskills@217be548739f21d6008915c29aefe320ea1a90af`.
- [Codex skills documentation](https://developers.openai.com/codex/skills) and
  `openai/codex@57f42a81131ccf5933e7ec5dc659c381eeb5d72b`, especially
  [`catalog_prompt.rs`](https://github.com/openai/codex/blob/57f42a81131ccf5933e7ec5dc659c381eeb5d72b/codex-rs/ext/skills/src/catalog_prompt.rs),
  [`render.rs`](https://github.com/openai/codex/blob/57f42a81131ccf5933e7ec5dc659c381eeb5d72b/codex-rs/ext/skills/src/render.rs),
  and the bounded discovery loader.
- [`openai/plugins@11c74d6ba24d3a6d48f54a194cd00ef3beea18f9`](https://github.com/openai/plugins),
  which supersedes the deprecated `openai/skills` examples. The data
  visualization router/specialist and Notion research packages were the most
  relevant reference designs.
- [Claude Code skills documentation](https://code.claude.com/docs/en/skills),
  [`anthropics/skills@b29e7cf65e5cb78a5ac33d582270551bc74a14eb`](https://github.com/anthropics/skills), and
  [`anthropics/claude-code@5cf69b18c86d0224dc53815332bbd85574b97097`](https://github.com/anthropics/claude-code).
  The review covered model/user invocation policy, compaction behavior, and
  command/agent separation in addition to package layout.

## What the standards actually require

`SKILL.md` is the only mandatory file in the portable Agent Skills format. Its
frontmatter requires a directory-matching, lowercase-hyphenated `name` of at
most 64 characters and a concrete `description` of at most 1,024 characters.
The description must explain both capability and activation boundary because
it is routing metadata.

Optional package content has distinct ownership:

| Path | Purpose | Loading rule |
|---|---|---|
| `agents/openai.yaml` | Display metadata, default prompt, invocation policy, tool dependencies | Parse during discovery; do not inject as instructions |
| `references/` | Conditional domain rules, checklists, formats | Read only from a step that needs the reference |
| `scripts/` | Deterministic, repeatable operations | Execute or inspect only when the workflow calls for it |
| `assets/` | Templates and source material used in outputs | Copy or transform; do not inject wholesale |
| `evals/` or `evaluations/` | Positive, near-miss, negative, and scenario fixtures | Use in validation/benchmarking, never for runtime keyword routing |

Adding empty folders or generic prose is not conformance. This is why the old
quality fixer, which padded skills to arbitrary length and heading targets,
was removed. The replacement validator checks the portable contract, OpenAI
metadata, safe relative links, symlinks, resource limits, and balanced trigger
fixtures without judging quality by word count.

## Findings before refactor

The former EvoFlux harness diverged from both Codex and Claude in several
material ways:

- Normal model context did not contain a usable metadata catalog, so implicit
  selection could not reliably work.
- Agent-assigned skill bodies and generic built-ins were preloaded without a
  clear user-owned contract, creating instruction competition.
- Discovery omitted portable `.agents/skills`, Claude-compatible roots,
  ancestor scopes, and additional authorized repositories.
- Duplicate identities silently used first-wins behavior; malformed YAML could
  disturb unrelated skills.
- `Agent.skills` was effectively dead configuration while UI implied it had
  runtime meaning.
- Activation returned unstructured prose, resources had no canonical reader,
  and compaction could remove the workflow while retaining a stale loaded flag.
- Settings CRUD could follow a discovered symlink outside the intended skill
  root.
- The package-quality script rewarded filler instead of precise workflows.
- Broad Work/Coding skills all competed for activation instead of using a
  small implicit router with explicit-only specialists.

## Implemented architecture

### Discovery and identity

Every sandbox-authorized workspace participates in cross-repository discovery.
For each workspace, EvoFlux scans the ancestor chain to its nearest Git root
for `.evoflux/skills`, `.agents/skills`, `.claude/skills`, and
`.opencode/skills`, then user, administrator, and bundled roots. Scans are
bounded to depth 6, 2,000 directories, and 20,000 entries.

Discovery produces typed records and diagnostics. Malformed bundles are
isolated; collisions retain lower-precedence candidates and surface their
paths. Mode projection chooses the highest-precedence valid candidate that is
actually available in the current mode, so an out-of-mode project skill cannot
hide a usable lower-precedence bundle.

Symlinked packages may be discovered and activated read-only. Settings cannot
edit or delete them, and the resource reader rejects symlink traversal.

### Catalog and activation

The catalog renderer mirrors Codex's progressive disclosure and budget model.
It filters invalid, out-of-mode, and explicit-only entries, shortens
descriptions fairly before omitting identities, and records omission
diagnostics. There is no lexical classifier, request-to-query conversion, or
hard-coded natural-language routing table.

Activation returns a structured `<skill_content>` block containing canonical
identity, a content revision, exact instructions, canonical directory, and a
bounded resource manifest. `read_resource` requires an already loaded skill,
accepts only contained POSIX paths, rejects `SKILL.md`, hidden EvoFlux scope
metadata, symlinks, binary files, and resources above 256 KiB.

Both discovery and activation use bounded reads, so replacing a validated file
with an oversized one between those phases cannot bypass the limit. The OpenAI
sidecar is capped at 256 KiB and its tool dependency records are typed,
length-limited, and exposed as harness metadata rather than injected as skill
instructions. EvoFlux reports these declarations but does not silently install
or authorize a missing external tool.

Untrusted YAML/JSON nesting errors are isolated as bundle diagnostics rather
than escaping discovery. `.evoflux.json` is capped at 16 KiB and any malformed
or partly invalid mode list fails open to both modes. Directory traversal
consumes bounded `scandir` iterators before sorting, so a single very wide
repository directory cannot defeat an after-the-fact entry cap.

The full-body activation paths are intentionally limited to:

- exact model selection from the catalog or an already loaded router;
- explicit Codex-style `$name` user selection (with legacy
  `/skill:<name>` compatibility);
- an explicit skill assignment in an agent configuration.

`Agent.skills` therefore means user-owned preload, not hidden recommendation.
Successful activation assistant/tool pairs are preserved exactly through
compaction within a separate UTF-8 byte budget. The budget charges the complete
atomic assistant/tool-call group, including non-skill outputs in a mixed batch,
so provider pairing rules cannot be used to retain unbounded unrelated output.
One activation is also capped at 95,000 model-visible bytes. If an old
activation is no longer retained, the ephemeral loaded cache is reconciled so
the bundle can be loaded again.

### Package strategy

Work and Coding each expose one implicit router. Their 13 broad specialists
are explicit-only and are named from the loaded router, reducing catalog
competition while preserving precise workflows. One narrow native-tool
workflow, `code-graph-navigation`, remains independently discoverable in Coding
mode because its exact-symbol trigger is precise:

- `work-router` routes research, data analysis, writing, planning, and
  decisions.
- `coding-router` routes graph navigation, investigation, debugging,
  implementation, testing, review, performance, security, and migration.

Code graph uses a deliberate two-layer contract. The optional
`code-graph-navigation` skill teaches selection, evidence, ambiguity, and
fallback workflow through progressive disclosure. The native `code_graph` tool
still owns exact-symbol validation and structural execution independently. It
is never a natural-language search layer, mode-level prompt injection, or
server-side request router.

### Management UI

Settings lists the canonical display name, source, diagnostics, invocation
policy, resource count, symlink/read-only state, and Work/Coding/Both scope.
Create scaffolds a complete starting package with `SKILL.md`,
`agents/openai.yaml`, and positive/near-miss trigger cases. The editor manages
a bounded bundle preview and sends only changed resources, so unseen resources
remain untouched and executable script modes are preserved. EvoFlux's
product-specific mode stays in a hidden `.evoflux.json` sidecar so portable
frontmatter remains standard.

The HTTP catalog, detail view, registry, update, and delete operations all use
the same ordered workspace list and optional mode projection as the runtime.
This prevents a Coding-only collision from hiding a valid Work variant and
keeps every repository in an active cross-repository project visible to the
slash menu and Settings. New package names use the portable Agent Skills
grammar; previously imported legacy nested names remain editable.

Bundle mutation is transactional: EvoFlux validates and stages `SKILL.md`,
the sidecar, deletions, and resource writes before one directory swap. Failed
base64, invalid frontmatter, over-budget files, root or descendant symlinks,
and nested-bundle traversal therefore leave the original package unchanged.
The 20 MiB resource budget and 2,000-entry limit are checked against the final
staged directory, not merely the current request, so repeated updates cannot
grow a package past its contract.
List/detail responses are capped by file count, walked entries, per-file bytes,
and aggregate inline bytes instead of materializing an unbounded repository.

## Verification contract

Regression tests cover metadata-only catalog rendering, budget truncation and
omission, policy/mode filtering, malformed sibling isolation, collisions,
cross-repository roots, exact activation, router-to-specialist handoff,
resource traversal, explicit selection, configured preload, compaction, API
projection, mode-specific collision projection, strict package validation,
transaction rollback, bounded bundle previews, dependency projection,
post-discovery file growth, executable-mode preservation, and symlink CRUD
denial. Additional adversarial cases cover recursive YAML/JSON, wide
directories, mixed-call durable-budget bypass, cumulative bundle growth,
noncanonical activation wrappers, empty instruction bodies, and bounded OpenAI
interface fields.

Static trigger fixtures validate package boundaries but are not a lexical
runtime selector. A true activation-quality benchmark must launch fresh model
sessions repeatedly, record which skills the model actually loads, and measure
precision before recall. Until such a model benchmark is wired into CI,
trigger fixtures are contract data and manual/offline evaluation input rather
than proof of model-level activation accuracy.

Latest verification on 2026-08-07 completed with no failures: the validator accepted
all 29 bundled packages and all six trigger cases per package; the full
`tests/agent` suite exited successfully; the focused
skill, hook, API, filesystem, and validator suites passed; Ruff passed; and the
frontend passed typecheck, lint, and all 161 unit tests across 47 files. A
localhost Settings smoke test now shows all 29 skills: 18 in Work, 16 in
Coding, and five in Both. `code-graph-navigation` appears once in Coding and
zero times in Work. API and validator regressions require the same mode
projection, complete runtime metadata, bounded resources, and the three-mode
creation control without browser console errors.

## Trust boundary and remaining limitation

Built-in, administrator, and user skills are application/user configuration.
Project skills are loaded only from repositories already present in the
session's sandbox-authorized workspace roots; those roots are EvoFlux's current
trust boundary and tool permissions still apply after activation.

EvoFlux does not yet expose a second, persistent "trust this repository's
instructions" toggle independent of workspace authorization. The Agent Skills
client guide recommends considering such a gate for freshly cloned repositories.
Adding it would be defense in depth, but it must be a real product trust state,
not a hidden keyword or path heuristic.

Codex can also resolve some declared MCP dependencies through its plugin/MCP
installation flow. EvoFlux intentionally stops at validation and visibility
today because installing or granting an external capability requires a separate
user-authorized lifecycle. That lifecycle and a repeatable live-model activation
benchmark are the two remaining parity items; neither should be simulated with
prompt injection or lexical request routing.
