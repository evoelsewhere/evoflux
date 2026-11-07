# evo-tools

[![crates.io](https://img.shields.io/crates/v/evo-tools.svg)](https://crates.io/crates/evo-tools)
[![docs.rs](https://docs.rs/evo-tools/badge.svg)](https://docs.rs/evo-tools)

The built-in agent tools and the execution environment they run against:
`read`, `write`, `edit`, `bash`, plus `grep`, `find`, `ls` and `powershell`,
implemented as `AgentTool`s that any agent built on
[`evo-agent`](https://crates.io/crates/evo-agent) can use.

The point of the crate is the split between *what a tool does* and *where it
runs*. Tools are written against `ExecutionEnv`, so the same `read` tool works
against the real filesystem, an in-memory fake, or a remote backend — and the
test suite never touches your disk.

## Install

```toml
[dependencies]
evo-tools = "0.3"
evo-agent = "0.3"
```

## Execution environments

| Backend | Purpose |
| ------- | ------- |
| `OsExecutionEnv` | The real filesystem and real shell processes; resolves relative paths against a configurable cwd |
| `InMemoryExecutionEnv` | A fake filesystem plus scripted shell responses, for deterministic tests |

Both implement `ExecutionEnv`; mutating backends additionally implement
`MutatingEnv`. Tools are constructed from an `ExecutionToolContext` that carries
the environment:

```rust
use std::sync::Arc;

use evo_tools::{create_bash_tool, create_write_tool, ExecutionToolContext, OsExecutionEnv};

let env = Arc::new(OsExecutionEnv::with_cwd("/tmp/workspace".into()));
let ctx = ExecutionToolContext::new(
    env.clone() as Arc<dyn evo_tools::ExecutionEnv>,
    Some(env as Arc<dyn evo_tools::MutatingEnv>),
);

let write_tool = create_write_tool(&ctx);
let bash_tool = create_bash_tool(&ctx, None);

let agent = evo_agent::AgentBuilder::new()
    .model(model)
    .stream_fn(stream_fn)
    .tools(vec![write_tool, bash_tool])
    .build()?;
```

A complete, runnable version — a faux provider that writes a file through the
real OS backend and reads it back — is in
[`examples/tools`](https://github.com/evoelsewhere/evo-harness/tree/main/examples/tools)
(`cargo run -p tools`).

## Testing against the in-memory backend

```rust
use std::sync::Arc;
use evo_tools::{ExecutionToolContext, InMemoryExecutionEnv, MutationQueueRegistry};

let env = Arc::new(InMemoryExecutionEnv::new());
let ctx = ExecutionToolContext::new(
    env.clone() as Arc<dyn evo_tools::ExecutionEnv>,
    Some(env as Arc<dyn evo_tools::MutatingEnv>),
);
let read = evo_tools::create_read_tool(&ctx, None);
```

Because the backend is in memory, a test asserts on tool *behaviour* rather than
on whatever happens to be in the working directory, and it runs in parallel with
every other test.

## Safety properties this crate is responsible for

- **Path containment.** Resolving a tool argument into a path is centralized in
  `path_utils`, so a tool cannot silently escape the environment root.
- **Mutation ordering.** `file_mutation_queue` serializes writes to the same
  path, so two concurrent `edit` calls cannot interleave into a corrupted file.
- **Bounded output.** Shell and file output are truncated through `truncate` +
  `shell_output` before reaching the model, so one `cat` of a huge log cannot
  blow up the context window.
- **Cancellation.** A blocking shell command is tied to the run's cancellation
  token, including process-tree termination on Windows.

## Tools available

`read`, `write`, `edit`, `bash`, `grep`, `find`, `ls`, `powershell`.
`create_*_tool` constructors all take the shared `ExecutionToolContext`;
`create_read_tool` and `create_bash_tool` additionally take an options argument
(`None` for the defaults).

The `evo` CLI loads `read`, `write`, `edit` and `bash` by default — the
Evo-compatible set — and exposes the rest through the `default_tools` setting.

## Related crates

| Crate | Role |
| ----- | ---- |
| [`evo-agent`](https://crates.io/crates/evo-agent) | The `AgentTool` trait these tools implement |
| [`evo-ai`](https://crates.io/crates/evo-ai) | Message and tool-schema types |
| [`evo-harness`](https://crates.io/crates/evo-harness) | Sessions and the run loop that drives them |
| [`evo-cli`](https://crates.io/crates/evo-cli) | The terminal agent |

## Documentation

- Crate docs: <https://docs.rs/evo-tools>
- Architecture: [docs/architecture/overview.md](https://github.com/evoelsewhere/evo-harness/blob/main/docs/architecture/overview.md)

## License

Apache-2.0. See [LICENSE](https://github.com/evoelsewhere/evo-harness/blob/main/LICENSE)
and [NOTICE](https://github.com/evoelsewhere/evo-harness/blob/main/NOTICE).
