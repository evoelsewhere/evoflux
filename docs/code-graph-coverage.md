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

On 2026-08-23, after the leaf-symbol and shared-traversal hardening updates:

| Repository | Structural files | Search-only | Parse failures | Symbols excluding file nodes | Relations | Symbols/KLOC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `evoflux` | 1,447 | 257 | 0 | 29,972 | 345,757 | 69.84 |
| `evo-conductor` | 201 | 20 | 0 | 5,309 | 44,799 | 113.44 |

Index/UI totals also include one file node per indexable file. The corresponding
committed totals are 31,676 and 5,530 symbols respectively. The combined
project totals are 37,206 symbols and 390,556 relations.

## What improved

The parser now emits named API-surface leaves that were previously absent:

- TypeScript interface/object properties and method signatures;
- TypeScript class fields and enum members;
- Rust struct/variant fields, enum variants, associated types, and macros;
- type-reference relations for the added TS and Rust declaration shapes;
- collision-safe stable local IDs for same-line union members and overload-like
  declarations;
- exact graph contracts for node metadata, ownership, imports, calls, type/value
  references, decorators, inheritance, synthetic symbols, and source lines;
- reference filtering across the complete syntax ancestry instead of fixed
  four/five-level windows, removing false runtime references from deeply nested
  type and import syntax;
- a strict per-file node cap and bounded collision search, so pathological input
  cannot exceed the advertised limit or hang an indexing job;
- JavaScript inheritance across its distinct tree-sitter heritage shape;
- qualified JS/TS callback, member-call, prototype, and `this` ownership paths;
- nested/generic TS heritage, type-alias and annotated-variable references;
- JSDoc plus Rust line/block documentation attached across decorators/attributes;
- qualified Rust scoped/field calls, generic/scoped trait implementations, and
  type references for aliases, constants, statics, and associated bounds;
- Python class/dataclass-style fields, annotated module/field references,
  qualified nested calls, generic inheritance, and runtime default-parameter
  references;
- semantic Python docstring evaluation/indent normalization that rejects bytes,
  f-strings, and malformed literals rather than reporting them as docs;
- Go grouped type/var/const declarations, struct fields, interface methods,
  qualified selector calls, typed specs, and blank/dot/raw imports;
- Java fields, record components, enum constants, annotation members, recursive
  generic type refs, qualified calls, inheritance/interfaces, imports, Javadoc,
  and DI collaborator edges.
- C# fields, record parameters, enum members, properties, qualified/generic
  type refs, nested member calls, imports, XML docs, attributes, heritage, and
  DI collaborator edges.
- C/C++ struct and union fields, enum members, globals, prototypes,
  function-pointer/aggregate typedefs, scoped method definitions, template and
  aggregate type refs, qualified/member/constructor calls, attributes, and
  compact or multiline documentation.
- PHP properties, promoted constructor properties, class/enum/global constants,
  enum cases and interfaces, trait-use references, DNF/union/intersection and
  qualified types, recursive attributes, scoped/chained calls, and exact
  bracketed or file-scoped namespace ownership.
- Kotlin primary/data-class fields, class and top-level properties, enums and
  entries, type aliases, object singletons, generic/qualified/nullable/function
  types, syntax-based superclass/interface edges, qualified calls, annotations,
  and KDoc/block documentation.
- Swift stored/protocol properties, top-level variables, protocol requirements,
  enum cases, type aliases, generic/qualified/composite types, class versus
  struct/actor conformance semantics, qualified calls, attributes, and line or
  block documentation.
- Dart fields and globals, enum values, mixins/extensions, type aliases,
  generic/qualified types, superclass/mixin/interface edges, stacked
  annotations, qualified calls, documentation comments, and method-body edge
  ownership repaired across the grammar's signature/body sibling split.
- Ruby class/module constants, scoped constant ownership, include/extend/prepend
  references, attribute macros, qualified receiver calls, modifier adjacency,
  Sorbet signature types, static/dynamic require separation, and ordered
  documentation comments.
- Scala case-class parameters, class/top-level vals and vars, trait requirements,
  Scala 3 enums/cases, type aliases, object conformance, generic/qualified types,
  superclass-versus-mixin edges, qualified calls, annotations, packages,
  Scaladoc, and exact import selectors/aliases.
- Objective-C implementation methods and multi-part selectors, property nodes
  plus implicit/custom accessors, protocol/class/category ownership,
  interface/implementation coalescing, precise method/property/function types,
  message/C calls, Clang/GNU attributes, documentation, and framework/local/module
  imports without generic selector/property identifier noise.
- Lua/Luau module variables, function-valued assignments, deep module ownership,
  qualified dot/colon calls, path-aware `require` imports without duplicate call
  edges, LuaLS documentation, and Luau generic/function/variable type references
  without selector or generic-parameter noise.
- R globals and nested functions, R6/S4/reference classes, class fields and
  methods, R6/S4 inheritance, Roxygen documentation, qualified namespace/member
  calls, loader/source imports, and DSL ownership without generic identifier
  fragments or structural constructor-call noise.
- Pascal/Delphi program/library/unit ownership, globals/constants, enum members,
  record/class fields, interfaces, generic and qualified types, multi-parent
  heritage, qualified calls, explicit unit paths, documentation comments, and
  signature-aware declaration/implementation coalescing that preserves
  overloads.

This raises the two-repository project from roughly 23.4K previously indexed
symbols to 37.2K after a full reindex (about +59%), without counting anonymous
syntax nodes or inflating the graph with duplicate relations.

Documentation detail is also measurable: EvoFlux has 4,813 documented symbols
and Evo Conductor has 163. EvoFlux's percentage is 16.06% after adding 4.6K
mostly-undocumented class fields, so the report includes both absolute and
percentage values. Signature completeness remains 100% and structural parse
failures remain zero.

## Explorer sampling

The interactive constellation is intentionally bounded for canvas performance.
It now displays `visible/total` symbols and relations plus a `sampled` marker.
The overview totals and audit report are authoritative; the number of dots in
the explorer is not the stored graph size.

## Mutation gate

The shared tree-sitter traversal, Python parser, JavaScript/TypeScript/TSX
parser, C/C++ parser, C# parser, Dart parser, Go parser, Java parser, Kotlin
parser, Lua/Luau parser, Objective-C parser, Pascal parser, PHP parser, R parser,
Ruby parser, Rust parser, Scala parser, Swift parser, and optimized leaf extractor are
mutation-tested with Mutmut:

```bash
uv run mutmut run
uv run mutmut results
```

The configured scope is `parsers/base.py`, `parsers/python.py`,
`parsers/ecmascript.py`, `parsers/c_family.py`, `parsers/csharp.py`,
`parsers/dart.py`,
`parsers/go.py`, `parsers/java.py`, `parsers/kotlin.py`, `parsers/lua.py`,
`parsers/objc.py`, `parsers/pascal.py`, `parsers/php.py`, `parsers/r_lang.py`,
`parsers/ruby.py`, `parsers/rust.py`, `parsers/scala.py`, `parsers/swift.py`, and
`parsers/symbol_leaves.py`. Exact
shared-walker and per-language contracts are the primary oracle. A cache-clean
campaign for the
shared/Python/ECMAScript/Rust tier kills 2,699/2,699 generated mutants with no
survivors, timeouts, or uncovered mutants. Two
behaviorally equivalent line mutations are excluded explicitly in source:
extending an already proven-free collision candidate range, and replacing a
capped synthetic-loop `break` with `return` when every child is blocked by the
same cap.

Go, Java, C#, C/C++, PHP, Kotlin, Swift, Dart, Ruby, Scala, Objective-C,
Lua/Luau, R, and Pascal were hardened afterward with isolated cache-clean 524/524, 533/533,
620/620, 885/885, 719/719, 543/543, 547/547, 690/690, 501/501, 586/586,
533/533, 536/536, 695/695, and 606/606 campaigns. A combined all-configured-parser campaign
remains required after the remaining language tier is complete.

The pre-hardening broad baseline produced 599 killed, 816 survivors, and 285
uncovered mutants. The primary repository stack has now moved into the clean
gate above; lower-volume language modules remain explicit follow-up scope and
must not be represented as mutation-hardened yet.

## Current limits

- Search-only formats contribute chunks and file nodes, not structural symbols.
- Static name resolution cannot prove every dynamic callback, reflection, macro
  expansion, or runtime dispatch edge.
- Docstring completeness reflects documentation present in source; it is not a
  parse-success metric.
- Cross-repository resolution is conservative when multiple symbols share the
  same unqualified name.
- Language modules outside the
  shared/Python/ECMAScript/C/C++/C#/Dart/Go/Java/Kotlin/Lua/Luau/Objective-C/Pascal/PHP/R/Ruby/Rust/Scala/Swift
  gate still rely on parser regression suites rather than a zero-survivor
  mutation contract.

These limits should be shown and measured, not converted into a misleading
single “coverage” percentage.
