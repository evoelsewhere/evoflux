# AIM knowledge-base template

This is the scaffold used by `AimSetupWizard` for a new migration project.
The KB is the project's Git-tracked system of record for unit state, business
rules, target mappings, evidence, approvals, and decisions.

Start with [GUIDELINES.md](GUIDELINES.md), then use [INDEX.md](INDEX.md) as the
content map. `aim.yaml` declares project identity and pins the rulebook stored
in this repository.

The `rulebook/` directory is active and project-owned from creation. EvoFlux
ships no stack-specific rulebook and performs no catalog fallback. Its sample
manifest and subitems are deliberately marked `template`; adapt and activate
them according to [rulebook/GUIDELINES.md](rulebook/GUIDELINES.md).
