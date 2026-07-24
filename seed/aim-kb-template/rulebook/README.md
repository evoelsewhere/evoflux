# Project-owned AIM rulebook

This directory is the only rulebook for this migration engagement. Start with
[`GUIDELINES.md`](GUIDELINES.md) and keep `rulebook.yaml` aligned with the files
you activate.

| Path | Purpose | Activation |
|---|---|---|
| `rulebook.yaml` | Stack metadata, parser strategy, lifecycle maturity, active paths | Always active |
| `canonicalizers/default.yaml` | Deterministic compare normalization | Active as the default profile |
| `mappings/` | Source construct to target pattern guidance | Read directly by architecture/conversion work |
| `extractors/` | Structural parser definitions | Rename an example and declare it in `extractors` |
| `runners/` | Legacy/target execution adapters | Rename examples and declare them in `runners` |
| `agents/` | Project-specific agent guidance examples | Documentation only; no automatic global merge |
| `skills/` | Project-specific knowledge examples | `.example.md` files are not auto-discovered |
| `workflows/` | Optional project workflow examples | `.example.yaml` files are not auto-discovered |
| `target-base/` | Preconditions for the target repository | Review before conversion |
| `ui-patterns/` | Legacy-screen to target-template mappings | Adapt for UI-heavy migrations |
| `commands/` | Operator command documentation | Documentation only |

All lifecycle capabilities begin as `template`. Promote one to `ready` only
after its declared files, deterministic commands, fixtures, and review gates are
actually usable in this project.