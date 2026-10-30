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

Each cell is the median of three five-second runs (2026-10-31), each on a
fresh copy of the v3.0.0 fixture; raw runs are kept outside the repository.
FIFO uses the exclusive lane; concurrent uses `BEGIN CONCURRENT`. The
same-table case inserts into `chat_sessions`; cross-table distributes work over
`chat_sessions`, `session_folders`, and `memory_facts` (one writer uses one
table, two use two, and four or eight use all three). The message case is a
multi-statement chat turn per transaction: a user message, an assistant
message carrying usage JSON, and an `UPDATE` of the session's `updated_at`,
with one session per writer. Inserts use the production random-rowid helper.
Throughput is acknowledged transactions divided by measured elapsed time; p99
includes retries and admission. Transaction retries are internal retries after
a lost commit; busy retries are outer retries after the DB API exhausted its
retry budget (a `database_busy` response in production). WAL max is the
largest `-wal` file seen during any of the three runs.

| Lane | Workload | Writers | Writes/s | p99 ms | Transaction retries | Busy retries | WAL max MiB |
|---|---|---:|---:|---:|---:|---:|---:|
| fifo | same-table | 1 | 1793 | 2.45 | 0 | 0 | 7.9 |
| fifo | same-table | 2 | 2441 | 19.54 | 0 | 0 | 7.9 |
| fifo | same-table | 4 | 2334 | 34.37 | 0 | 0 | 7.9 |
| fifo | same-table | 8 | 2702 | 30.03 | 0 | 0 | 7.9 |
| fifo | cross-table | 1 | 2209 | 0.97 | 0 | 0 | 7.9 |
| fifo | cross-table | 2 | 3354 | 3.01 | 0 | 0 | 7.9 |
| fifo | cross-table | 4 | 3071 | 23.16 | 0 | 0 | 7.9 |
| fifo | cross-table | 8 | 3259 | 33.10 | 0 | 0 | 7.9 |
| fifo | message | 1 | 1753 | 0.96 | 0 | 0 | 7.9 |
| fifo | message | 2 | 2087 | 16.37 | 0 | 0 | 7.9 |
| fifo | message | 4 | 2065 | 36.89 | 0 | 0 | 7.9 |
| fifo | message | 8 | 1944 | 54.02 | 0 | 0 | 7.9 |
| concurrent | same-table | 1 | 2357 | 0.82 | 0 | 0 | 7.9 |
| concurrent | same-table | 2 | 1619 | 17.25 | 482 | 1 | 15.8 |
| concurrent | same-table | 4 | 1947 | 32.77 | 1276 | 4 | 15.8 |
| concurrent | same-table | 8 | 1928 | 99.33 | 2356 | 25 | 15.8 |
| concurrent | cross-table | 1 | 2079 | 0.97 | 0 | 0 | 7.9 |
| concurrent | cross-table | 2 | 2940 | 6.28 | 0 | 0 | 15.8 |
| concurrent | cross-table | 4 | 3010 | 18.01 | 421 | 1 | 15.8 |
| concurrent | cross-table | 8 | 3065 | 38.07 | 1770 | 12 | 15.9 |
| concurrent | message | 1 | 1609 | 2.28 | 0 | 0 | 7.9 |
| concurrent | message | 2 | 1472 | 27.94 | 450 | 0 | 15.8 |
| concurrent | message | 4 | 1444 | 50.17 | 1049 | 7 | 15.8 |
| concurrent | message | 8 | 1601 | 120.29 | 2154 | 32 | 15.9 |

**WAL growth (fixed).** The 2026-10-30 run measured concurrent cross-table at
442 writes/s with two writers and no conflicts. The cause was the WAL: with two
or more `BEGIN CONCURRENT` connections one transaction is nearly always open,
so SQLite's autocheckpoint can never reset the WAL. It grew without bound
(29 → 109 MB in 4 s at two writers) and every commit paid for another
checkpoint attempt. The write lanes now set `wal_autocheckpoint=0` and
checkpoint themselves: `PASSIVE` every 1000 new frames under the commit mutex,
and at 4000 frames new write transactions wait until open ones finish while a
`TRUNCATE` checkpoint resets the WAL. The WAL now stays under 16 MiB in every
cell; `db_stress` fails a run whose WAL exceeds 2 × 4000 frames, and the core
test `concurrent_writes_keep_wal_bounded` asserts the bound.

**Pool size.** With the WAL bounded, two concurrent writers lead cross-table
work (2940 vs 2079 writes/s for one) without exhausting the retry budget in any
workload, while four and eight writers add `database_busy` outcomes and p99
without more throughput. `DbOptions.concurrent_writers` is therefore 2. The
message workload conflicts on every multi-writer size because all sessions'
`UPDATE`s land on the same `chat_sessions` leaf page; FIFO is faster there,
and FIFO with two or more callers matches or beats the concurrent lane in every
workload on this host. **Default (owner decision, design §3.3).** FIFO is the default for every
write path, not only while Python writes. The concurrent lane is built, and
`EVOFLUX_DB_CONCURRENT_WRITES=on` enables it; any other value, or no value,
keeps FIFO. The table above does not justify turning it on by default. It
stays off until it is re-benchmarked in Phase 4 and v4.1.
Repeat on representative workloads and all platforms before changing the pool
again (and repeat in Phase 4).

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
