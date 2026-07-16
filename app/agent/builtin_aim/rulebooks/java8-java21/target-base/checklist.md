# Target base checklist — Java 21

For the solution architect scaffolding the target repo before an AIM project starts (§1.3 of the design doc: "AIM converts units into a base that's already dressed"). Not a template to auto-generate from — a checklist to review a hand-built base against.

- [ ] Build tool chosen and configured for a JDK 21 toolchain (Gradle toolchains or Maven `maven.compiler.release=21`).
- [ ] Package layout and module boundaries decided and documented in `target-conventions.md`.
- [ ] Test framework in place (JUnit 5) with a working `./gradlew test` / `mvn test` from a clean checkout.
- [ ] CI pipeline that builds, tests, and reports on a sample/skeleton unit.
- [ ] Static analysis / lint configured (so `aim-converter`'s output is checked against the same bar as everything else in the repo).
- [ ] A skeleton example of the target's error-handling, configuration-loading, and logging conventions — the things `aim-converter` should follow rather than invent per unit.
- [ ] Decision recorded (even if "no" for now) on adopting Java 21 features project-wide: records, sealed classes, virtual threads, pattern-matching switch — so `aim-target-architect` isn't guessing per unit.
- [ ] `target-conventions.md` in the KB actually reflects the base above, not a generic description — `aim-archaeologist`/`aim-target-architect` should update it from the real scaffold, not from this checklist.
