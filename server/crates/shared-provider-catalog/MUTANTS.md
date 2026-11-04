# P-004 mutation results

All 240 generated candidates are resolved: 217 caught, 23 unviable, zero missed,
zero equivalents and zero platform exclusions. No timeout was needed.
The unviable logs contain compiler type errors (`E0277` / `E0283`), with no
disk-space, linker or permission failures.

Scope: the whole `evoflux-shared-provider-catalog` crate, including generated
override constants. Every run used `--in-place --timeout 30 --test-tool nextest`
inside `server/`, under a separate foreground `timeout 580` command.

The first two runs used shards `0/8` and `1/8`. The remaining candidates were
enumerated and covered by file/function scopes: catalog merge/lookup helpers,
`configured.rs` (two shards), `data.rs`, and `registry.rs` (two shards). A
`provider_label` retest also selected the 48 override-table constants. The final
audit compared candidate names against every outcome, deduplicating repeated
runs; none were omitted. Raw reports and the audit are in the migration bridge:
`cx-catalog-{m0,m1,label-retest,remaining-catalog,configured0,configured1,data,
data-retest,registry0,registry1,alias-retest}` and
`cx-catalog-{all-mutants,mutation-summary}.json`, `cx-catalog-audit.py`.

Three initial misses were genuine fixture gaps, closed with JSON generated from
the actual Python helpers:

- An empty config label must fall back to the catalog name, then the provider id.
- A fetched envelope's explicit id must win over a different map key.
- An explicitly empty `models_dev_id` must fall back to the config's own id.

The relevant label, data, and alias mutations were rerun and caught after adding
those cases. Production code did not change during these retests. The original
start also had a real parity defect for numeric/bool fetched ids; the additional
Python fixture first failed against Rust, then passed after matching Python's
scalar conversion and falsy-id fallback.
