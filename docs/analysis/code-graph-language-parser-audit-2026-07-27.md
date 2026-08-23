# Code Graph Language Parser Audit

| | |
|---|---|
| Date | 2026-07-27 |
| Scope | 25 built-in parser registrations, shared tree-sitter walker, module/FQN ownership, calls, imports, type relations, embedded scripts, and cross-repository inputs |
| Runtime | Python 3.12+, tree-sitter 0.25+, tree-sitter-language-pack 0.10+ |
| Verdict | Broad production-useful static coverage, with explicit dynamic-language and receiver-inference limits; support must be measured by semantic contracts, not file-extension count |

## 1. Executive conclusion

The code graph parser layer is now structurally sound for its intended role: produce a conservative static graph from source text, then let the indexer resolve local, imported, ambiguous, and cross-repository relationships. The audit found that many grammars were registered but several common constructs did not reach that graph correctly. The highest-impact failures were qualified ownership, import aliases, embedded script coordinates, generated members, literal module dependencies, and language-specific definition forms.

Those failures were corrected with AST-backed regressions. The shared walker now also supports synthetic leaf definitions, which is required when one syntax node creates several symbols, such as Ruby accessors, Objective-C property accessors, and Liquid variables.

At the time of this audit, an earlier code-graph skill had been retired because it duplicated the native tool contract and polluted the catalog. That catalog decision was superseded on 2026-08-07: `code-graph-navigation` returned as progressively disclosed Coding-only workflow guidance, while the native `code_graph` tool still owns execution. Parser correctness now lives in [the parser service](../../app/services/code_index/parsers), and every language claim below is tied to executable syntax evidence.

## 2. Audit method

The audit used five evidence classes:

1. Official language references for declaration, module, call, import, and type semantics.
2. The installed tree-sitter grammars, inspected through real AST node types and field names.
3. Direct `ParseResult` corpora comparing expected nodes/edges with parser output.
4. Focused regressions added before each parser change.
5. Full parser, import, type-reference, and decorator suites after the changes.

A language is not considered covered merely because its extension maps to a grammar. A useful support claim requires evidence for the applicable axes:

- definitions and lexical/module ownership;
- calls and constructor/member-call normalization;
- imports or equivalent static dependencies, including aliases;
- inheritance, implementation, mixin, or type references where the language defines them;
- source coordinates and containment;
- explicit behavior for dynamic constructs that cannot be resolved safely.

## 3. Shared parser contract

The common walker in [base.py](../../app/services/code_index/parsers/base.py) owns traversal, safety limits, qualified names, containment, calls, imports, supertypes, decorators, type references, and documentation edges.

The current invariants are:

- `ExtractedNode.name` is the local leaf name; `qualified_name` carries package, namespace, module, class, receiver, or lexical ownership.
- `ImportRef.name` identifies the target symbol, `local_name` identifies the source binding, and `module_path` preserves the raw dependency specifier.
- Literal/static dependencies are emitted. Computed dependency paths are ignored rather than guessed.
- Synthetic definitions are leaf siblings. They do not steal ownership of the syntax node's children.
- Synthetic local IDs have stable suffixes, preventing collisions when an implicit method and a property share a source line and qualified name.
- Dynamic languages do not receive invented static classes or types. Only syntax or well-defined static macros are modeled.
- Embedded-language parsers preserve host-file line numbers and report the host language while delegating semantic extraction.

These values feed [the source-to-index pipeline](../../app/services/code_index/pipeline.py) and the [module-path/cross-repository resolver](../../app/services/code_index/query.py).

## 4. Built-in language matrix

Status meanings:

- **Deep**: definitions/FQNs, calls, dependencies, and applicable type relations have direct regression coverage.
- **Core**: common static forms are covered; a documented language-specific precision gap remains.
- **Dynamic-core**: statically named forms are covered and runtime metaprogramming is intentionally excluded.
- **Delegated**: host format delegates embedded script semantics to the ECMAScript parsers.

| Parser | Extensions | Verified semantic surface | Status | Principal residual limit |
|---|---|---|---|---|
| Python | `.py`, `.pyi` | nested/class/function/variable definitions, calls, imports and aliases, inheritance, decorators, annotations, docstrings | Deep | runtime monkey-patching and computed imports |
| TypeScript | `.ts`, `.mts`, `.cts` | classes/interfaces/functions/methods/variables, namespaces, calls, all common module dependency forms, decorators, nested type refs | Deep | non-literal `import()` |
| TSX | `.tsx` | TypeScript graph plus JSX-hosted source | Deep | JSX template relationships are not component edges |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | definitions, calls, static imports, side-effect imports, re-exports, literal dynamic imports | Deep | prototype mutation and computed imports |
| Go | `.go` | package FQNs, types/interfaces/functions/methods/vars, receiver ownership, calls, imports, embedding, type refs, docs | Deep | build-tag evaluation and receiver type inference across calls |
| Rust | `.rs` | module tree, structs/enums/traits/functions/impl methods, calls/macros, `use`, trait relations, type refs, docs | Core | `impl Type` can still produce a duplicate type container |
| Java | `.java` | package FQNs, classes/interfaces/enums/methods, calls, imports, extends/implements, annotations, types, docs, common DI fields | Deep | anonymous-class ownership and framework-specific reflection |
| C# | `.cs` | namespace FQNs, classes/interfaces/structs/enums/methods/properties, calls, `using`, inheritance, attributes, recursive types, DI fields | Deep | source generators and runtime reflection |
| C | `.c`, `.h` | functions, structs/enums, calls, includes, attributes, type refs, comments | Core | preprocessor condition evaluation and macro-generated declarations |
| C++ | `.cpp`, `.hpp`, `.cc`, `.cxx`, `.hxx`, `.hh` | namespace ownership, classes/structs/enums/functions/methods, calls/new, includes, inheritance, attributes, types, docs | Deep | template-dependent lookup and macro expansion |
| Swift | `.swift` | nominal types/protocols/extensions/functions/methods, calls, imports, conformance, attributes, types, docs | Deep | generated declarations and advanced operator dispatch |
| Kotlin | `.kt`, `.kts` | package FQNs, classes/interfaces/objects/functions/methods, calls, imports/aliases, supertypes, annotations, types, docs | Deep | compiler plugins and delegated runtime members |
| PHP | `.php` | namespace FQNs, classes/interfaces/traits/functions/methods, calls/new, `use` aliases, inheritance, attributes, types, docs | Deep | dynamic includes and magic methods |
| Ruby | `.rb` | nested and compact namespaces, classes/modules/methods, singleton methods, calls, require paths, inheritance, Sorbet refs, docs, `attr_*` methods | Dynamic-core | `define_method`, mixin relations, and general metaprogramming |
| Scala | `.scala`, `.sc` | package FQNs, traits/classes/objects/functions/methods, calls, imports, inheritance, annotations, types, docs | Deep | macro/inline-generated declarations and extension collision for `.sc` overrides |
| Dart | `.dart` | classes/mixins/extensions/functions/methods, constructors and selector chains, imports, inheritance, metadata, types, docs | Deep | generated code and runtime mirrors |
| Objective-C | `.m`, `.mm` | classes/protocols/categories/functions/methods/properties, message/C calls, imports/modules, inheritance/adoption, attributes, recursive types | Core | selector normalization removes colons; method declarations and implementations remain distinct |
| Lua | `.lua` | named functions, function-value assignments, deep table-owned methods, calls, `require`, docs | Dynamic-core | table-as-class conventions and multi-target function assignments |
| Luau | `.luau` | Lua surface plus exported/generic type aliases, typed functions/function values, unions/optionals/object types | Core | runtime Roblox instance paths are retained but not type-inferred |
| R | `.r`, `.R` | assigned functions including S3 dotted names and right assignment, calls including `$`, package/namespace dependencies, literal `source`, Roxygen docs | Dynamic-core | S4/R6 runtime class construction and non-standard evaluation |
| Pascal | `.pas`, `.pp`, `.dpr`, `.lpr` | unit ownership, enum/record/class/property/procedure kinds, nested procedures, calls, `uses`, parents/interfaces, recursive signature refs, docs | Core | a lone first parent cannot always be distinguished as class versus interface without symbol resolution |
| Svelte | `.svelte` | all script/module-script blocks delegated to JS/TS with absolute host lines | Delegated | template directives and component props are not first-class graph nodes |
| Vue | `.vue` | normal and setup scripts delegated to JS/TS with absolute host lines | Delegated | Options API/template semantics are not statically expanded |
| Astro | `.astro` | frontmatter delegated to TypeScript with absolute host lines | Delegated | template component usage is not a call graph |
| Liquid | `.liquid` | assign/capture/increment/decrement and loop variables, static include/render calls and dependencies | Core | variable reads, filters, and dynamic template names are intentionally not resolved |

## 5. Remediation ledger

| Confirmed issue | Resolution |
|---|---|
| Agent tool dropped stored relationships | Render every edge kind with correct direction and ambiguity candidates |
| Cross-repository traversal ignored direction or stale source links | Direction-aware rendering and changed-target reattachment |
| Import aliases disconnected calls and collided in caches | Explicit target name, local binding, and collision-safe module-resolution keys |
| Incremental UUID targets lost file/scope metadata | Preserve file and qualified ownership through incremental resolution |
| C# extraction was shallow | Namespace ownership, annotations, DI fields, and recursive type references |
| Svelte/Vue/Astro parsed one script with wrong coordinates/language | Merge every script block and translate all nodes/edges to absolute host lines |
| Dart emitted no calls | Parse functions, constructors, named constructors, selectors, generics, and `await` chains |
| Static-language package/module ownership was missing | Add package, namespace, module, and receiver FQNs across Go, Kotlin, PHP, C++, Rust, Scala, and TypeScript namespaces |
| ECMAScript missed side-effect imports, re-exports, and dynamic imports | Emit module dependencies for side-effect, barrel, and literal `import()` forms |
| Ruby `attr_*` created no graph methods | Emit implicit readers and writers from static symbol/string arguments |
| Ruby compact `A::B` definitions disappeared | Normalize constant paths into leaf names plus dot-qualified graph ownership |
| Lua/Luau function values disappeared | Treat single-target function assignment as the owning definition |
| Luau parser used obsolete AST node names | Align with `type_definition` and current annotation layout; filter generic parameters from refs |
| R missed `$` calls and namespace/file loaders | Extract literal member calls, namespace loaders, and literal `source()` dependencies |
| Pascal nested procedures and unit scope were lost | Make `defProc` and `unit` real containers; classify enum/record/property and signature refs correctly |
| Objective-C properties/categories/protocol inheritance were incomplete | Add property/accessor symbols, category identity, inherited protocols, selector correction, and class-container coalescing |
| Liquid assignments and loop bindings were absent | Emit static variables plus include/render call and import edges |

## 6. Cross-repository behavior

Cross-repository resolution is intentionally based on stable static evidence:

- package, namespace, unit, and module prefixes reduce global name collisions;
- imported target names remain separate from source aliases;
- literal module paths survive parsing for workspace and repository lookup;
- unresolved but precise inheritance, implementation, and DI edges can become cross-repository candidates;
- ambiguity is preserved and shown to agents rather than resolved arbitrarily;
- changed target repositories can reattach links from unchanged source repositories.

The parser does not infer a receiver's runtime type. A call such as `service.run()` usually emits the leaf selector `run`; import bindings, containment, nearby types, and ambiguity handling then constrain resolution. Receiver-type inference is a separate analysis layer and should not be approximated inside language hooks.

## 7. Accepted limits and remaining backlog

### P1 - Structural precision

1. Coalesce Rust `impl Type` containers without merging legitimate overloads or separate nominal definitions.
2. Introduce declaration/definition identity where C++, Pascal, and Objective-C intentionally expose both source locations.
3. Add receiver/type-aware call resolution as a separate, evidence-carrying pass.
4. Model Ruby `include`, `prepend`, and `extend` with a dedicated mixin relation rather than overloading inheritance.

### P2 - Language-specific depth

1. Support Lua/Luau multiple assignment when each function body can be paired safely with one target.
2. Distinguish Pascal's first interface-only parent using the indexed target kind, not name heuristics.
3. Preserve full Objective-C selectors, including colon positions, while maintaining compatibility with existing call resolution.
4. Add template target nodes or path-aware virtual symbols so Liquid include/render edges can resolve directly to `.liquid` files.
5. Expand Svelte/Vue/Astro template-level relationships only behind framework-specific contracts; do not treat markup as JavaScript calls.

### Intentionally excluded

- computed import/require/source/template names;
- Ruby `method_missing`, arbitrary `define_method`, and eval-created code;
- Lua table/metatable class inference;
- R S4/R6 objects and non-standard evaluation inference;
- source-generator, compiler-plugin, macro-expansion, and reflection outputs;
- preprocessor branch evaluation.

These exclusions should remain visible in user-facing capability reporting. Silent guessed edges would reduce graph trust more than missing dynamic edges.

## 8. Official source index

The implementation was checked against these primary or canonical references, then against the installed grammar AST rather than assuming the documentation maps one-to-one to node names.

| Family | References used |
|---|---|
| Parser runtime | [Tree-sitter parser API](https://tree-sitter.github.io/tree-sitter/using-parsers/), [tree-sitter-language-pack](https://github.com/Goldziher/tree-sitter-language-pack) |
| Python | [Compound statements](https://docs.python.org/3/reference/compound_stmts.html), [Simple statements](https://docs.python.org/3/reference/simple_stmts.html) |
| JavaScript/TypeScript | [MDN modules](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules), [MDN import](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/import), [MDN export](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/export), [TypeScript classes](https://www.typescriptlang.org/docs/handbook/2/classes.html), [TypeScript namespaces](https://www.typescriptlang.org/docs/handbook/namespaces.html) |
| Go | [The Go Programming Language Specification](https://go.dev/ref/spec) |
| Rust | [Rust items](https://doc.rust-lang.org/reference/items.html), [Rust modules](https://doc.rust-lang.org/reference/items/modules.html) |
| Java | [Java Language Specification](https://docs.oracle.com/javase/specs/jls/se24/html/) |
| C# | [C# language specification](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/language-specification/) |
| C/C++ | [WG14 documents](https://www.open-std.org/jtc1/sc22/wg14/www/docs/), [C++ working draft](https://eel.is/c++draft/) |
| Swift | [Swift declarations](https://docs.swift.org/swift-book/documentation/the-swift-programming-language/declarations/) |
| Kotlin | [Kotlin language documentation](https://kotlinlang.org/docs/home.html) |
| PHP | [PHP language reference](https://www.php.net/manual/en/langref.php) |
| Ruby | [Modules and classes](https://docs.ruby-lang.org/en/master/syntax/modules_and_classes_rdoc.html), [Module accessors](https://docs.ruby-lang.org/en/master/Module.html#method-i-attr_accessor) |
| Scala | [Packages and imports](https://docs.scala-lang.org/tour/packages-and-imports.html), [Package prefixes](https://docs.scala-lang.org/scala3/reference/changed-features/package-prefixes.html) |
| Dart | [Dart language](https://dart.dev/language) |
| Objective-C | [Defining classes](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/DefiningClasses/DefiningClasses.html), [Customizing classes](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/CustomizingExistingClasses/CustomizingExistingClasses.html), [Protocols](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/ProgrammingWithObjectiveC/WorkingwithProtocols/WorkingwithProtocols.html) |
| Lua/Luau | [Lua 5.4 Reference Manual](https://www.lua.org/manual/5.4/manual.html), [Luau type system](https://luau.org/types) |
| R | [R Language Definition](https://cran.r-project.org/doc/manuals/r-release/R-lang.html), [Namespace loading](https://stat.ethz.ch/R-manual/R-devel/library/base/html/ns-load.html), [`source`](https://stat.ethz.ch/R-manual/R-devel/library/base/html/source.html) |
| Pascal | [Free Pascal Reference Guide](https://www.freepascal.org/docs-html/ref/ref.html) |
| Web components | [Svelte files](https://svelte.dev/docs/svelte/svelte-files), [Vue SFC specification](https://vuejs.org/api/sfc-spec.html), [Astro components](https://docs.astro.build/en/basics/astro-components/) |
| Liquid | [Variable tags](https://shopify.github.io/liquid/tags/variable/), [Iteration tags](https://shopify.github.io/liquid/tags/iteration/), [Shopify render](https://shopify.dev/docs/api/liquid/tags/render) |

## 9. Validation

The final parser validation covered core parser semantics, tiered language corpora, language-specific import suites, type references, and decorators:

```text
uv run pytest --no-cov -q tests/services/test_code_graph_*.py

Result: PASS
```

Changed parser and regression files also pass Ruff and VS Code diagnostics.

## 10. Ongoing quality gate

For every new grammar or newly claimed construct:

1. Cite the language's official semantics.
2. Inspect the installed grammar's real AST.
3. Add a failing `ParseResult` regression.
4. Make the smallest parser or shared-walker change.
5. Run the focused test immediately.
6. Run the full parser corpus.
7. Record dynamic exclusions and cross-repository implications.

This gate prevents the project from returning to extension-count coverage, where a parser is registered but common code does not produce a navigable graph.
