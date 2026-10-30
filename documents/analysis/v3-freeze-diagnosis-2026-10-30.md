# v3.1.1 freeze diagnosis - 2026-10-30

## Result

In the final run a health probe exceeded one second during `large_repo_open`:
1,078 ms. At the one-second threshold, `py-spy` captured the main thread active
with the GIL in SQLAlchemy ORM mapper configuration and statement compilation,
ending in `sqlmodel.orm.session.exec`. No application call site was visible
above that frame in the capture.

An earlier successful run against the same v3.1.1 checkout measured a
3,547 ms probe in the same scenario. Its stack showed synchronous Python
import machinery (`importlib` `get_data`) on the main thread, reached from
`app/api/app.py:105` (`mcp_manager.start()`), `app/agent/mcp/lazy.py:22`
(`_resolve`) and `app/agent/mcp/manager.py:39` while importing the MCP SDK.
These samples support the hypothesis that synchronous work can hold up the
event loop. Neither sample proves the entire delay was spent in the captured
frames, nor that it explains the owner's intermittent UI freeze. Reported
maxima may include overhead from attaching `py-spy` after the first second had
already elapsed.

The first workload begins immediately after the backend handshake, while
optional startup services may still be running. These results therefore describe
project-open load combined with cold startup, not a controlled warm-only
reproduction. Other EvoFlux processes and workloads were active on the host.

## Windows measurements

Reference: Windows 11 Home Single Language 10.0.26300, AMD Ryzen 9 5900HS,
23.4 GiB reported RAM, Python 3.12.14, `py-spy` 0.4.2. The backend was v3.1.1
from integration-base release commit `8fd844d5`, with fresh temporary data,
config, state, cache, workspace, wiki and Windows profile directories. A local
mock provider returned deterministic responses; the shell scenario verified a
persisted successful tool result with a duration above ten seconds. Health was
polled approximately every 50 ms; p99 is the nearest-rank value of completed
probes. Four samples in the history scenario are insufficient for a stable
p99 estimate. Windows timer granularity and other host activity also limit
precision.

| Scenario | Samples | Maximum live latency | p99 live latency | Dumps |
| --- | ---: | ---: | ---: | ---: |
| `large_repo_open` | 155 | 1,078 ms | 47 ms | 1 |
| `long_shell_tool` | 227 | 359 ms | 93 ms | 0 |
| `history_reads` | 4 | 15 ms | 15 ms | 0 |
| `mcp_never_answers` | 253 | 32 ms | 16 ms | 0 |
| `large_pdf_intake` | 52 | 31 ms | 31 ms | 0 |

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

The script prints a JSON summary for each scenario and writes `summary.json`
and a `py-spy` stack dump when a probe remains outstanding for more than one
second. Dumps are local diagnostic artifacts and can contain process details;
they are not committed. The backend process tree is terminated on exit.

The first start from the freshly installed v3.1.1 environment exceeded the
runner's 100-second handshake limit during imports and was stopped. The table
is from the subsequent run after that environment's caches had warmed.

The second-OS run remains open. WSL was unavailable on this machine; run the
same script on `ubuntu-latest` or a Linux host with a disposable checkout and
record the resulting measurements and stack captures in a follow-up. A warm
repeat with a populated history and a longer observation period is needed to
assess the owner's intermittent freeze separately from cold-start activity.
