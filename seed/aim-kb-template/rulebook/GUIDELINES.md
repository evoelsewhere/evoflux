# Project rulebook guidelines

This directory is the engagement's only AIM rulebook. EvoFlux does not ship or
fall back to stack-specific rulebooks. `rulebook.yaml` is active from project
creation and is pinned by the root `aim.yaml`.

## Customize here when

- the estate uses project-specific source extensions or extractor patterns;
- target conventions require different construct mappings;
- runners need customer environment commands;
- canonicalization must handle a documented harmless difference;
- a stack-specific agent overlay or skill has project-only knowledge;
- target-base or UI-pattern requirements need project-specific guidance.

## Do not

- copy generic AIM workflow state logic into this folder;
- mark a lifecycle capability `ready` while adapters are templates;
- weaken a canonicalizer only to make a failing comparison pass;
- edit source-system behavior without a rule or ADR;
- delete provenance or sign-off from golden metadata.

The template is intentionally non-operational: every lifecycle capability starts
as `template`, parser strategy is `none`, and example files are not referenced by
the manifest. Adapt one surface at a time, validate it, then declare it in
`rulebook.yaml` and promote only that capability to `ready`.

## Activation order

1. Describe the real source and target stacks and file extensions.
2. Choose `tree_sitter`, `structural`, or `none` for parsing.
3. Copy and rename only the example files the engagement needs.
4. Declare renamed paths in `rulebook.yaml`.
5. Add representative fixtures and run the corresponding validation.
6. Change a capability from `template` to `ready` only when its deterministic
   prerequisites are executable and reviewed.

See each subdirectory README/example and the repository-level `GUIDELINES.md`.