# Common construct mapping — VB6 → .NET

Reference table for `aim-target-architect`. See the `vb6-dotnet-idioms` skill for why most of these are redesign decisions, not mechanical substitutions.

| Legacy (VB6) construct | Target (.NET) construct | Equivalence note |
|---|---|---|
| `Sub` / `Function` | Method | Check `ByRef` parameters — .NET defaults to by-value; explicit `ref`/`out` needed where VB6 relied on `ByRef` |
| `Variant` | Narrowest concrete type the usage requires | Check null/empty/coercion behavior on real data before picking a type |
| `On Error GoTo` / `Resume` / `Resume Next` | `try`/`catch` + an explicit resume strategy | Needs a project-level ADR — no direct equivalent |
| Standard module (`.bas`) global variable | DI-scoped or singleton service field | Decide the target state-management convention once, project-wide |
| `Currency` | `decimal` | Verify rounding behavior matches, don't assume |
| VB6 date serial | `DateOnly` / `DateTime` | Check date-arithmetic edge cases explicitly |
| Fixed-length string (`String * n`) | `string` + explicit padding logic | Only if legacy behavior/format depends on the padding |
| `Collection` | `List<T>` or `Dictionary<TKey,TValue>` | Depends on whether legacy code uses indexed or keyed access |
| ADO/DAO `Recordset` | Entity Framework Core query / `DbSet<T>` | Check for reliance on cursor position, `MoveNext`/`MovePrevious` semantics |
| COM/ActiveX control (OCX) | (no default — needs a target UI decision) | Flag for `aim-target-architect`, don't guess a replacement |
| `DoEvents` / modal message loop | `async`/`await` or background work, per project convention | Concurrency-model decision, not a line mapping |
| VB6 Form (see `ui-patterns/`) | Target UI template per pattern | Never map ad hoc — use the approved pattern |

Add rows here as the project encounters constructs not yet covered.
