# Test-level selection

Choose the lowest level that still crosses every boundary needed to observe the
failure.

| Level | Use when | Avoid when |
| --- | --- | --- |
| Unit | Pure policy, transformation, state machine, or error mapping | Framework wiring or real serialization is the risk |
| Component | One module with framework lifecycle or rendering matters | Network/process contract is central |
| Contract | Independently deployed producer/consumer must agree | Both sides always deploy atomically |
| Integration | Database, queue, filesystem, protocol, or dependency behavior matters | A stable fake proves the same owned contract |
| End-to-end | Only the full user path proves routing, identity, or assembly | A lower level pinpoints and proves the invariant |
| Property | Large input/state space has stable invariants | Failures cannot be minimized or reproduced |
| Load | Concurrency, saturation, tail latency, or resource bounds are requirements | Functional behavior alone is under test |

## Test-double boundary

Fake what the system does not own; keep real the behavior whose contract is
under test. Assert requests at owned interfaces rather than the internals of a
third-party client. Contract-test shared schemas separately when producer and
consumer release independently.

## Flake replacement

Before deleting a flaky high-level test, identify its unique proof obligation.
Move deterministic obligations down, retain only the assembly assertion at the
higher level, and verify the replacement fails when the original regression is
reintroduced.
