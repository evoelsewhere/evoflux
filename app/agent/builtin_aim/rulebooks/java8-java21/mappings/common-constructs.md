# Common construct mapping — Java 8 → Java 21

Reference table for `aim-target-architect` when writing a unit's `mapping/<unit>.md`. See the `java-modernization-idioms` skill for the semantic traps behind each row.

| Legacy (Java 8) construct | Target (Java 21) construct | Equivalence note |
|---|---|---|
| Anonymous inner class implementing a functional interface | Lambda expression | Safe if stateless; check captured-state semantics otherwise |
| `java.util.Date` / `Calendar` | `java.time.Instant` / `LocalDateTime` / `ZonedDateTime` | Make time zone explicit — don't rely on JVM default |
| `Collections.unmodifiableList(list)` | `List.of(...)` / `List.copyOf(list)` | Not equivalent if the source list may contain nulls |
| `switch` statement (String/int) | `switch` expression | Only if no intentional fall-through is relied upon |
| `if (x instanceof Foo) { Foo f = (Foo) x; ... }` | `if (x instanceof Foo f) { ... }` | Purely syntactic — always safe |
| Plain class as an immutable data carrier | `record` | Only if genuinely immutable and never subclassed |
| `StringBuffer` | `StringBuilder` | Only if usage is genuinely single-threaded |
| `finalize()` override | try-with-resources / explicit `close()` / `java.lang.ref.Cleaner` | Requires a real design change, not a rename |
| `SecurityManager` usage | (removed in later JDKs — needs an alternative access-control design) | Requires an ADR, not a mechanical mapping |
| Blocking I/O in a thread-per-request service | Virtual threads (`Thread.ofVirtual()`) | Opportunity, not obligation — only if the target base already adopts this pattern |

Add rows here as the project encounters constructs not yet covered.
