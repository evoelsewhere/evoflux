# v3.1.1 freeze diagnosis - 2026-10-30

## Result

A cold-start repeat reproduced a 1,407 ms `live` probe before optional services
were ready. The one-second `py-spy` capture showed the main thread in the MCP
SDK import, reached from `app/api/app.py:105` (`_start_optional_services`),
`app/agent/mcp/lazy.py:22` (`_resolve`) and `app/agent/mcp/manager.py:39`.
The reviewer's independent run observed the same 1,407 ms delay and call sites;
an earlier run observed 3,547 ms during the same import. These observations
support synchronous startup work blocking the event loop for roughly 1?3.5 s,
but they do not establish that every start stalls for that long: the full
rerun's cold-start maximum was 640 ms. Attaching `py-spy` after one second
may add overhead, and a stack is a point sample rather than a breakdown of
the whole delay.

No steady-state workload exceeded one second in the rerun after optional
services were ready. The earlier 1,078 ms project-open result overlapped cold
startup and cannot be attributed to repository activity. This experiment does
not establish whether any workload causes the owner's intermittent UI freeze;
other EvoFlux processes and workloads were active on the host.

## Windows measurements

Reference: Windows 11 Home Single Language 10.0.26300, AMD Ryzen 9 5900HS,
23.4 GiB reported RAM, Python 3.12.14, `py-spy` 0.4.2. The backend was v3.1.1
from integration-base release commit `8fd844d5`, with fresh temporary data,
config, state, cache, workspace, wiki and Windows profile directories. A local
mock provider returned deterministic responses; the shell scenario verified a
persisted successful tool result with a duration above ten seconds. Health was
polled approximately every 50 ms; p99 is the nearest-rank value of completed
probes. The short cold-start and history scenarios are insufficient for stable
p99 estimates. Windows timer granularity and other host activity also limit
precision.

| Scenario | Samples | Maximum live latency | p99 live latency | Dumps |
| --- | ---: | ---: | ---: | ---: |
| `cold_start` | 3 | 640 ms | 640 ms | 0 |
| `large_repo_open` | 182 | 62 ms | 32 ms | 0 |
| `long_shell_tool` | 225 | 516 ms | 110 ms | 0 |
| `history_reads` | 6 | 31 ms | 31 ms | 0 |
| `mcp_never_answers` | 252 | 31 ms | 16 ms | 0 |
| `large_pdf_intake` | 50 | 16 ms | 16 ms | 0 |

A separate run selecting only `history_reads` measured cold-start max/p99
1,407/1,407 ms (4 samples, one MCP-import stack dump), followed by history
max/p99 47/47 ms (5 samples, no dump). The cold-start and history samples are
too few for a stable p99. The cold-start window runs from the handshake until
the `optional_services_ready` log line, not from process creation; the probe
already in flight when readiness is logged is allowed to finish.

All five workload checks completed without a reported error. The shell command
used the isolated session's bypass permission mode solely to run a controlled
12-second local wait. History made 20 concurrent reads of a fresh session; it
was not a large populated history. The MCP test verified that a local stdio
process started but did not answer initialization. The PDF had 400 pages,
3,600,928 bytes and an extractable text layer on its first and last pages.

The owner replaced the obsolete repository-index rebuild scenario with
`large_repo_open`. It created a Coding project on a shallow checkout of
`https://github.com/microsoft/vscode.git` at
`cd2259bdf72ec7421e70ae80999ceb46f8bd86fe`, then concurrently requested file
listing, Git status and diff, and search-everywhere while the workspace watcher
observed a burst of 2,000 writes. The disposable checkout was clean afterwards.
The original clone completed checkout but exited nonzero on its LFS
post-checkout hook; this run used the checked-out tree, not LFS file contents.

## Reproduction and open work

Install `py-spy`, obtain a disposable large checkout and a clean checkout of
v3.1.1 (`8fd844d5`), run `uv sync --frozen` in the v3 checkout, then from the
migration repository root run:

```text
uv run python scripts/migration/diagnose_freeze.py --v3-source <v3.1.1-checkout> --repo <disposable-repo> --output <output-dir> --py-spy <py-spy-executable>
```

The script always measures `cold_start` first, waits for `optional_services_ready`,
and then runs the selected workload(s). It prints a JSON summary for each
scenario and writes `summary.json`
and a `py-spy` stack dump when a probe remains outstanding for more than one
second. Dumps are local diagnostic artifacts and can contain process details;
they are not committed. The backend process tree is terminated on exit.

The first start from the freshly installed v3.1.1 environment exceeded the
runner's 100-second handshake limit during imports and was stopped. A forced
handshake-timeout check confirmed the runner terminates its backend parent and
child before the temporary directory is removed. An older leftover temporary
directory could not be removed by the current account and remains open cleanup.

The second-OS run remains open. WSL was unavailable on this machine; run the
same script on `ubuntu-latest` or a Linux host with a disposable checkout and
record the resulting measurements and stack captures in a follow-up. A warm
repeat with a populated history and a longer observation period is needed to
assess the owner's intermittent freeze separately from cold-start activity.
