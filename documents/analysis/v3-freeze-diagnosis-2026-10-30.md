# v3.1.1 freeze diagnosis — 2026-10-30

Status: incomplete. No load scenario has been measured, so no stall has been reproduced or ruled out and the event-loop hypothesis remains untested.

## Approved workload change

The owner replaced the obsolete repository-index rebuild scenario with `large_repo_open`: create a Coding project and concurrently exercise the file tree, Git status/diff, search everywhere, and the workspace watcher while writing 2,000 files. The other four planned scenarios remain required.

A shallow clone of `https://github.com/microsoft/vscode.git` at `cd2259bdf72ec7421e70ae80999ceb46f8bd86fe` checked out 20,718 files, but Git reported failure at the LFS post-checkout hook under clone protection. This checkout has not been validated as a usable workload fixture.

## Windows setup observations

`uv sync --frozen` installed the project dependencies. A startup smoke test using temporary EvoFlux directories initially failed because the settings loader tried to inspect the real user's `.config/evoflux/.env`, which the sandbox denied. Setting the child process's `USERPROFILE` to the temporary profile allowed the v3.1.1 backend to start and emit its handshake. This was only a startup test; no health latency was measured. The smoke test's wrapper terminated `uv` rather than the Python child, leaving its database open; the identified child was subsequently stopped. Any diagnostic runner must clean up the actual server process and its descendants before deleting temporary files.

A standalone `py-spy dump --pid <child>` probe against a test Python child exited 1 with `Failed to find python version from target process`. It has not been established whether a dump of the EvoFlux process would work. The second OS requirement is also unverified: `wsl -d Ubuntu -- uname -a` failed with `Wsl/Service/E_ACCESSDENIED`. No workload runner or results are included yet.

## Follow-up: real backend stack capture

A subsequent unsandboxed Windows startup used isolated EvoFlux directories and
`USERPROFILE`, and tracked the PID printed by the backend handshake. Both
`py-spy dump --pid <handshake-pid>` and the `--nonblocking` variant succeeded
against that real backend; the earlier test-child error does not establish a
blocker. The process tree was stopped after the probe. No stack dump was
associated with a health stall, and the five workload scenarios remain unrun.

The Linux run remains an open follow-up: the same script must later be run on
`ubuntu-latest` or another Linux host.
