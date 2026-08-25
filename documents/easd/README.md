# Evo Agent Specs repository store

This directory is the version-controlled source of truth for EASD runs owned by
this repository. Commit Intent, immutable Spec/Plan revisions, lifecycle events,
mission snapshots, review/verification evidence, deviations, and convergence.

Standard document shapes live under `templates/`. Active run data is created
under `runs/<slug>--<uuid>/`. Machine-local locks and session bindings never
belong here.
