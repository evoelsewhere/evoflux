# Code graph coverage and trust model

Code graph `Ready` means every repository has a committed index. It is **not**
a parser-coverage percentage. EvoFlux reports structural coverage separately
from search-only coverage so a searchable Markdown/JSON/SQL file is never
misrepresented as a parsed symbol graph.

## Reproducible audit

Run the same gitignore-aware source discovery and parser registry used by the
indexer:

```bash
uv run python scripts/audit_code_graph_coverage.py /path/to/repository
```

The report includes:

- indexable, structural, and search-only files;
- structural parse failures and success percentage;
- symbols, relations, and symbols per KLOC;
- symbol/relation distribution by kind;
- signature and docstring completeness;
- a bounded list of parser failures.

On 2026-08-23, after the TS/TSX/Rust leaf-symbol coverage update:

| Repository | Structural files | Search-only | Parse failures | Symbols excluding file nodes | Relations | Symbols/KLOC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `evoflux` | 1,443 | 257 | 0 | 24,677 | 335,608 | 57.76 |
| `evo-conductor` | 201 | 20 | 0 | 5,218 | 46,121 | 111.50 |

Index/UI totals also include one file node per indexable file. The corresponding
committed totals are 26,377 and 5,439 symbols respectively.

## What improved

The parser now emits named API-surface leaves that were previously absent:

- TypeScript interface/object properties and method signatures;
- TypeScript class fields and enum members;
- Rust struct/variant fields, enum variants, associated types, and macros;
- type-reference relations for the added TS and Rust declaration shapes;
- collision-safe stable local IDs for same-line union members and overload-like
  declarations.

This raises the two-repository project from roughly 23.4K existing indexed
symbols to an expected 31.8K after reindex (about +35.9%), without counting
anonymous syntax nodes or inflating the graph with duplicate relations.

## Explorer sampling

The interactive constellation is intentionally bounded for canvas performance.
It now displays `visible/total` symbols and relations plus a `sampled` marker.
The overview totals and audit report are authoritative; the number of dots in
the explorer is not the stored graph size.

## Mutation gate

The optimized leaf extractor is mutation-tested with Mutmut:

```bash
uv run mutmut run
uv run mutmut results
```

The configured scope is `parsers/symbol_leaves.py`, with TS/TSX/Rust coverage
fixtures as the oracle. The current campaign kills 42/42 covered mutants with
no survivors or uncovered mutants. A wider audit of the legacy TS/Rust parser
files produced 599 killed, 816 survivors, and 285 uncovered mutants; that result
is retained as explicit test-debt evidence rather than being hidden inside the
focused score.

## Current limits

- Search-only formats contribute chunks and file nodes, not structural symbols.
- Static name resolution cannot prove every dynamic callback, reflection, macro
  expansion, or runtime dispatch edge.
- Docstring completeness reflects documentation present in source; it is not a
  parse-success metric.
- Cross-repository resolution is conservative when multiple symbols share the
  same unqualified name.

These limits should be shown and measured, not converted into a misleading
single “coverage” percentage.
