# Target base checklist — .NET 8

For the solution architect scaffolding the target repo before an AIM project starts. Not a template to auto-generate from — a checklist to review a hand-built base against.

- [ ] Solution layout decided (e.g. layered: Domain / Application / Infrastructure / Web or similar) and documented in `target-conventions.md`.
- [ ] Data access approach chosen (Entity Framework Core vs. Dapper vs. other) and a skeleton example wired up end to end.
- [ ] Test project in place (xUnit or equivalent) with a working `dotnet test` from a clean checkout.
- [ ] CI pipeline that builds, tests, and reports on a sample/skeleton unit.
- [ ] **UI kit decided before any screen work starts** (§3.13A R1): target UI framework (Blazor, MVC + Razor, MAUI, or other), component library, and layout templates for each pattern in `ui-patterns/vb6-to-dotnet-ui-patterns.md`.
- [ ] Error-handling and global-state conventions decided project-wide (see `vb6-dotnet-idioms` skill) — not left for each converted unit to improvise.
- [ ] Skeleton example of the target's configuration-loading and logging conventions.
- [ ] `target-conventions.md` and `ui-conventions.md` in the KB actually reflect the real scaffold above, not a generic description.
