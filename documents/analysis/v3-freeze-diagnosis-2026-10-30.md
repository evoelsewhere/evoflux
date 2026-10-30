# v3.1.1 freeze diagnosis — 2026-10-30

Status: blocked before measurement. No stall has been reproduced or ruled out.

The Phase 0 plan asks for a repository index rebuild on a large repository.
At the v3.1.1 release commit `8fd844d5`, searches of the Python application
for a code-index or repository-index rebuild entry point found no implementation.
Migration `app/migrations/versions/00000046_drop_application_code_graph.py`
records removal of the application-database code graph and says a regeneratable
per-repository SQLite target replaced it; the searches did not identify how to
invoke that replacement in the v3.1.1 backend. This does not establish that no
index exists elsewhere in the product.

Owner clarification is required on the intended entry point or replacement
workload before the prescribed scenarios can be implemented. No health latency
measurements or stack captures have been taken. The event-loop blocking
hypothesis therefore remains untested.
