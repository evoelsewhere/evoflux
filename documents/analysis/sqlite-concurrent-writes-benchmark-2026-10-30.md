# SQLite concurrent-write benchmark - 2026-10-30

Windows 11 Home 10.0.26300, AMD Ryzen 9 5900HS (16 logical processors),
23.4 GiB RAM, Rust 1.98.0, release build, pinned `begin-concurrent` base
3.51.3. Python 3.12.14 links stock SQLite 3.53.1. The latest official stock
[SQLite download](https://www.sqlite.org/download.html) was 3.54.1; its
Windows CLI was downloaded with its published SHA3-256 verified and used for
the compatibility gate via `EVOFLUX_SQLITE_CLI`. CI downloads and verifies
the latest official CLI on each supported platform; a local run without that
variable checks Python SQLite only. The pinned base is behind that release
and needs a security-fix review; the monthly release check will open an issue when enabled. GitHub scheduled
workflows run from the default branch (`main`), so the schedule does not run
until this workflow is also present there. Other host activity was not
controlled.

Each row is one five-second run on a fresh copy of the v3.0.0 fixture. FIFO
uses the exclusive lane; concurrent uses `BEGIN CONCURRENT`. The same-table
case inserts into `chat_sessions`; cross-table distributes work over
`chat_sessions`, `session_folders`, and `memory_facts` (one writer uses one
table, two use two, and four or eight use all three). These are real schema
rowid tables and use the production random-rowid insert helper. Throughput is
acknowledged inserts divided by measured elapsed time; p99 includes retries
and admission. The retry metric counts internal transaction retries, and the
busy column counts outer retries after the DB API exhausted its retry budget.

| Lane | Workload | Writers | Writes/s | p99 ms | Transaction retries | Busy retries |
|---|---|---:|---:|---:|---:|---:|
| fifo | same-table | 1 | 2588 | 2.47 | 0 | 0 |
| fifo | same-table | 2 | 2509 | 21.44 | 0 | 0 |
| fifo | same-table | 4 | 2526 | 29.02 | 0 | 0 |
| fifo | same-table | 8 | 2391 | 34.80 | 0 | 0 |
| fifo | cross-table | 1 | 2428 | 3.27 | 0 | 0 |
| fifo | cross-table | 2 | 3009 | 19.12 | 0 | 0 |
| fifo | cross-table | 4 | 3004 | 25.48 | 0 | 0 |
| fifo | cross-table | 8 | 3239 | 29.67 | 0 | 0 |
| concurrent | same-table | 1 | 2669 | 2.44 | 0 | 0 |
| concurrent | same-table | 2 | 445 | 9.48 | 633 | 0 |
| concurrent | same-table | 4 | 398 | 134.93 | 1145 | 14 |
| concurrent | same-table | 8 | 475 | 269.09 | 1912 | 27 |
| concurrent | cross-table | 1 | 2659 | 2.45 | 0 | 0 |
| concurrent | cross-table | 2 | 442 | 8.28 | 0 | 0 |
| concurrent | cross-table | 4 | 470 | 33.13 | 167 | 8 |
| concurrent | cross-table | 8 | 543 | 267.21 | 919 | 23 |

On this run one concurrent writer had the highest throughput in both patterns
and the lowest concurrent p99; `DbOptions.concurrent_writers` is therefore 1.
Concurrent writes default to off while Python writes because the mixed-writer
compatibility test failed on the fresh database; set
`EVOFLUX_DB_CONCURRENT_WRITES=on` only for explicit testing until that failure
is resolved.
Four-writer tests explicitly request four connections so that conflict and
retry coverage is preserved. The cross-table results with more writers did
not show the expected benefit, even when two writers reported no conflicts;
this measurement does not establish why. A single short trial, different table
mixes, shared host activity, and one operating system are insufficient for a
general performance conclusion. Repeat on representative workloads and all
platforms before changing the pool again (and repeat in Phase 4).

Run with `cargo build -p evoflux-core --release --example db_stress` and then
`cargo bench -p evoflux-core write_lanes` from `server/`.

The initial 60-second standalone writer and 120-second Python-plus-Rust run
passed on both fixtures. On a repeat, the v3.0.0 mixed-writer case passed with
51,017 Rust writes, 280 Python sessions and 560 Python messages matching row
counts. The fresh mixed-writer case failed after the processes stopped: stock
Python SQLite raised `sqlite3.OperationalError: disk I/O error` while counting
rows. The fresh failure repeated after adding the startup readiness wait and WAL
checkpoint; a 120-second fresh FIFO fallback run also failed with the same
post-shutdown `disk I/O error`. After adding the real backend PID wait, a
fresh FIFO repeat passed with 148,430 Rust writes, 256 Python sessions and
512 Python messages matching row counts and both stock SQLite checks passing.
A subsequent fresh concurrent repeat also passed, with 50,131 Rust writes,
239 Python sessions and 478 Python messages matching row counts. These
repeats suggest a shutdown timing issue, but do not prove its cause; the
conservative default remains off. Later checks of the affected files using
both stock Python SQLite and the SQLite 3.54.1 CLI returned `ok` with no
foreign-key errors, but this does not establish the cause or make the failed
check safe to ignore. The default is off under the design's Phase 1-3
fallback; the four-writer concurrent test remains an unweakened gate. The
harness now waits for Python startup readiness and the real backend PID to
exit, and checkpoints WAL before copying; it retains the post-shutdown
integrity and row-count checks. Only Windows and the v3.0.0 plus fresh
fixtures were available; other platforms and fixture versions remain open.
