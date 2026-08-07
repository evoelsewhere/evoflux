# Coding routing matrix

Use the evidence state and requested deliverable to resolve adjacent cases.

| Situation | Primary specialist | Add or switch when |
| --- | --- | --- |
| Exact identifier is known; ask for definition, callers, callees, references, impact, or neighborhood | `code-graph-navigation` | Switch to investigation when the root must first be discovered or dynamic wiring matters. |
| "How does this work?", "what enables this?", or caller question without an exact root | `coding-investigation` | Load graph navigation after investigation exposes an exact identifier; switch to implementation only after the user asks for a change. |
| Test/build/runtime symptom, cause unknown | `coding-debugging` | Continue into implementation when a fix is explicitly requested or inherent in the task. |
| Desired behavior and acceptance criteria are known | `coding-implementation` | Use migration instead when compatibility must span releases or consumers. |
| Old and new contracts coexist | `coding-migration` | Add testing for a cross-version verification strategy. |
| System is slow or expensive | `coding-performance` | Start with debugging only if the reported metric is actually a correctness anomaly. |
| Existing diff needs assessment | `coding-review` | Add security only when a real trust boundary is in scope. |
| Auth, tenant isolation, untrusted input, secrets | `coding-security` | Add implementation only when remediation is requested. |
| Coverage, flakes, test architecture, proof | `coding-testing` | Use debugging when a failing product behavior—not the test strategy—is the central unknown. |

## Multi-specialist sequences

- Unknown cause then fix: debugging owns the evidence loop; implementation owns
  the final contract change only if the implementation work is substantial.
- Unknown root then structural traversal: investigation discovers and
  disambiguates the identifier; graph navigation owns only the exact static
  relationship query.
- Migration with verification: migration owns ordering and rollback; testing
  owns the compatibility matrix.
- Security finding with remediation: security defines the invariant and abuse
  case; implementation applies the narrow fix.
- Performance change: performance owns baseline and comparison; implementation
  is unnecessary unless the code change becomes a separate deliverable.

Never infer permission to mutate code from an explanatory, audit, or review
request.
