# Coding skill consolidation — 2026-09-15

Supersedes the coding-workflow section of
[`builtin-skill-context-audit-2026-08-06.md`](builtin-skill-context-audit-2026-08-06.md).
The retention rule in that audit still holds; only the packaging changed.

## Finding

The curated catalog of eight coding workflows had grown back to thirteen
(`coding-api-design`, `coding-browser-verify`, `coding-debugging`,
`coding-git-workflow`, `coding-implementation`, `coding-investigation`,
`coding-migration`, `coding-observability`, `coding-performance`,
`coding-review`, `coding-security`, `coding-simplification`,
`coding-testing`).

Every one of them was implicitly invocable, so all thirteen descriptions were
rendered into the always-visible catalog on every turn:

| | Bytes |
| --- | --- |
| Rendered coding-mode catalog | 12,093 |
| The thirteen `coding-*` entries within it | 5,358 |
| Budget at a 128k context window | 10,240 |

The catalog was over budget. `render_skill_catalog` resolves an overflow by
truncating descriptions — and the part it truncates is the tail, which is
exactly where each skill states what it is *not* for. The distinctions that
separated `coding-debugging` from `coding-investigation` from
`coding-implementation` were the first bytes discarded. Fragmentation was
degrading the routing it existed to sharpen.

Twelve copies of `references/code-context-contract.md` were also maintained by
hand. They were identical in content; only working-tree line endings differed,
and `.gitattributes` normalizes those on commit.

## Change

Thirteen skills became four hubs, grouped by the *posture* of the work rather
than by topic — posture is what the model must discriminate at catalog time,
and topic is what a hub can route on once loaded.

| Hub | Workflows under `references/workflows/` |
| --- | --- |
| `coding-investigate` | `investigate`, `debug`, `browser-verify` |
| `coding-change` | `implement`, `simplify`, `migrate`, `api-design` |
| `coding-verify` | `review`, `security`, `test` |
| `coding-operate` | `performance`, `observability`, `git-workflow` |

This reuses the hub pattern already carried by `data-analytics`,
`product-design`, and `sales`. `_RESOURCE_DIR_NAMES` excludes `references/`
from discovery traversal, so a workflow body under it is never a catalog entry
and is reached only through `skill(action="read_resource")`.

Workflow bodies moved verbatim. Their relative links still resolve because
resource paths are relative to the *skill root*, which is now the hub, and the
shared references sit at that root.

### Result

| | Before | After |
| --- | --- | --- |
| Coding catalog entries | 25 | 16 |
| `coding-*` description bytes | 5,358 | 2,325 |
| Rendered coding catalog | 12,093 | 9,060 |
| Truncated at 128k | yes | no |

The cost is one routing hop per task: load the hub, read one workflow. For
`coding-change` that hop is effectively unconditional.

## Invariants this change depends on

- **A hub declares only the dependencies every workflow it owns needs.**
  Built-in dependencies are a hard activation gate
  (`_resolve_builtin_dependencies` raises `SkillDependencyError` on any missing
  tool), so declaring `browser_use` on `coding-investigate` would have made
  investigation and debugging unloadable wherever no browser tool is granted.
  Tools that only one workflow needs are named in the hub body as a routing
  precondition instead. `browser-verify` and `git-workflow` are the two cases.
- **Relative links inside a workflow body resolve against the hub root**, not
  against the file. `scripts/validate_skills.py` rejects `..` in a link, so a
  shared reference must live at the hub root rather than beside the workflow.
- **Every eval case carries `expected_workflow`.** Near-miss negatives that
  used to distinguish two sibling skills are now positive intra-hub routing
  cases; only cases that leave the hub stay negative.
  `test_coding_hubs_route_to_every_workflow_they_own` asserts the eval routing
  set matches the shipped workflow set.

## Second pass — hoisting the repeated prose

The first pass moved workflow bodies unchanged, so each one still restated the
observation limits. Those were hoisted into the hubs afterwards. Three blocks
were genuinely duplicated:

| Block | Copies before | After |
| --- | --- | --- |
| `refresh=true` / `refresh=false` index semantics (byte-identical) | 11 | 4 hubs |
| Source-discovery tooling and the shell-reread prohibition | 10 | 4 hubs |
| `process(action="wait", wait_seconds=60)` polling rule | 7 | 4 hubs |

What stayed in each workflow is what actually varies: **what it reserves shell
for** (reproduction vs benchmarks vs migration vs bounded negative tests vs
git), its **stop gate**, and its **deliverable**. Those read as boilerplate but
are not.

### The prediction above was wrong

This section originally predicted the hoist "would shrink activation bytes as
this change shrank catalog bytes." Measured, it does not. An activation loads
one hub plus one workflow, so moving text from thirteen workflows into one hub
does not remove it from any single activation — it only stops paying for the
text thirteen times on disk.

| | Before hoist | After hoist |
| --- | --- | --- |
| Mean activation (hub + one workflow) | 8,571 B | 8,674 B |
| Total bytes across 4 hubs + 13 workflows | 77,591 B | 74,186 B |

Mean activation rose by 103 bytes (+1.2%). Four of the thirteen activations got
cheaper; `coding-operate/git-workflow` got 660 bytes more expensive, because
that workflow never carried the hoisted rules and now pays for hub bullets
about source discovery it does not use.

The change is still worth keeping, but for the maintenance reason rather than
the context reason: eleven hand-synchronised copies of the index-refresh
paragraph became four, and `test_native_code_context_contract_is_stated_once_per_coding_hub`
now asserts that no workflow restates a hoisted rule, so they cannot drift
apart again.

## Not done

The remaining 9,060-byte catalog is still over budget at a 128k context window
once user and project skills are added. The residual is driven by the twenty
`ALL_SKILL_MODES` bundles, not by coding workflows.
