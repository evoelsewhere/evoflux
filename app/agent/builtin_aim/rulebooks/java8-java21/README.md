# Rulebook: java8-java21 (draft)

The simplest AIM pilot pair — same language, no structural parser needed, `parser_strategy: tree_sitter` reuses the existing Java grammar in `app/services/code_graph/parsers/` untouched. Intended as the first end-to-end validation of the AIM pipeline once AIM-1/AIM-2 land, per `documents/research/aim-framework.md` §4.1.

**Status: content-only (AIM-0).** Not yet installed anywhere — the AIM-1 `aim_rulebook_service` is what will eventually copy `agents/`, `skills/`, and (later) `workflows/` into a project's config and KB.
