//! Mirrors `packages/agent/test/harness/tools.test.ts` "coalesces updates and
//! persists truncated full output" — the bash tool must emit at most one
//! `on_update` per ~100ms throttle window when the command streams many chunks.
//!
//! We drive a custom env whose `exec` fires `on_stdout` many times in rapid
//! succession (one `on_update` would be expected per chunk without throttling).
//! With throttling, the count stays bounded well below the chunk count. The
//! InMemory env emits a single chunk per script, so we use a delegating wrapper
//! that replays N chunks — same pattern as `abort_bracketing.rs`.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use async_trait::async_trait;
use evo_tools::{
    ExecutionEnv, ExecutionToolContext, FileContent, FileError, FileInfo, FileSystem,
    InMemoryExecutionEnv, MutatingEnv, MutationQueueRegistry, Shell, ShellExecOptions, ShellOutput,
};
use tokio_util::sync::CancellationToken;

/// A delegating env that, for the command "stream", fires `on_stdout` 500 times
/// (one line each) so the throttle has something to coalesce.
struct StreamingEnv {
    inner: Arc<InMemoryExecutionEnv>,
    registry: Arc<MutationQueueRegistry>,
}

impl StreamingEnv {
    fn new(inner: Arc<InMemoryExecutionEnv>) -> Self {
        Self {
            inner,
            registry: Arc::new(MutationQueueRegistry::new()),
        }
    }
}

impl MutatingEnv for StreamingEnv {
    fn as_env(&self) -> &dyn ExecutionEnv {
        self
    }
    fn mutation_registry(&self) -> &MutationQueueRegistry {
        &self.registry
    }
}

#[async_trait]
impl FileSystem for StreamingEnv {
    fn cwd(&self) -> &Path {
        self.inner.cwd()
    }
    async fn absolute_path(
        &self,
        p: &str,
        c: Option<&CancellationToken>,
    ) -> Result<PathBuf, FileError> {
        self.inner.absolute_path(p, c).await
    }
    async fn join_path(
        &self,
        p: &[&str],
        c: Option<&CancellationToken>,
    ) -> Result<PathBuf, FileError> {
        self.inner.join_path(p, c).await
    }
    async fn read_text_file(
        &self,
        p: &str,
        c: Option<&CancellationToken>,
    ) -> Result<String, FileError> {
        self.inner.read_text_file(p, c).await
    }
    async fn read_text_lines(
        &self,
        p: &str,
        m: Option<usize>,
        c: Option<&CancellationToken>,
    ) -> Result<Vec<String>, FileError> {
        self.inner.read_text_lines(p, m, c).await
    }
    async fn read_binary_file(
        &self,
        p: &str,
        c: Option<&CancellationToken>,
    ) -> Result<Vec<u8>, FileError> {
        self.inner.read_binary_file(p, c).await
    }
    async fn write_file(
        &self,
        p: &str,
        c: FileContent,
        c2: Option<&CancellationToken>,
    ) -> Result<(), FileError> {
        self.inner.write_file(p, c, c2).await
    }
    async fn append_file(
        &self,
        p: &str,
        c: FileContent,
        c2: Option<&CancellationToken>,
    ) -> Result<(), FileError> {
        self.inner.append_file(p, c, c2).await
    }
    async fn rename_file(
        &self,
        s: &str,
        d: &str,
        c: Option<&CancellationToken>,
    ) -> Result<(), FileError> {
        self.inner.rename_file(s, d, c).await
    }
    async fn file_info(
        &self,
        p: &str,
        c: Option<&CancellationToken>,
    ) -> Result<FileInfo, FileError> {
        self.inner.file_info(p, c).await
    }
    async fn list_dir(
        &self,
        p: &str,
        c: Option<&CancellationToken>,
    ) -> Result<Vec<FileInfo>, FileError> {
        self.inner.list_dir(p, c).await
    }
    async fn canonical_path(
        &self,
        p: &str,
        c: Option<&CancellationToken>,
    ) -> Result<PathBuf, FileError> {
        self.inner.canonical_path(p, c).await
    }
    async fn exists(&self, p: &str, c: Option<&CancellationToken>) -> Result<bool, FileError> {
        self.inner.exists(p, c).await
    }
    async fn create_dir(
        &self,
        p: &str,
        r: bool,
        c: Option<&CancellationToken>,
    ) -> Result<(), FileError> {
        self.inner.create_dir(p, r, c).await
    }
    async fn remove(
        &self,
        p: &str,
        r: bool,
        f: bool,
        c: Option<&CancellationToken>,
    ) -> Result<(), FileError> {
        self.inner.remove(p, r, f, c).await
    }
    async fn create_temp_dir(
        &self,
        p: Option<&str>,
        c: Option<&CancellationToken>,
    ) -> Result<PathBuf, FileError> {
        self.inner.create_temp_dir(p, c).await
    }
    async fn create_temp_file(
        &self,
        p: &str,
        s: &str,
        c: Option<&CancellationToken>,
    ) -> Result<PathBuf, FileError> {
        self.inner.create_temp_file(p, s, c).await
    }
    async fn cleanup(&self) {
        let inner: &dyn FileSystem = &*self.inner;
        inner.cleanup().await;
    }
}

#[async_trait]
impl Shell for StreamingEnv {
    async fn exec<'a>(
        &'a self,
        command: &str,
        mut options: ShellExecOptions<'a>,
    ) -> Result<ShellOutput, evo_tools::ExecutionError> {
        if command.starts_with("stream") {
            // Fire 500 chunks as fast as possible — without throttling this
            // would produce ~500 on_update calls.
            if let Some(cb) = options.on_stdout.as_mut() {
                for i in 0..500u32 {
                    cb(&format!("line-{i}\n"));
                }
            }
            return Ok(ShellOutput {
                stdout: String::new(),
                stderr: String::new(),
                exit_code: 0,
            });
        }
        self.inner.exec(command, options).await
    }
    async fn cleanup(&self) {
        let inner: &dyn Shell = &*self.inner;
        inner.cleanup().await;
    }
}

impl ExecutionEnv for StreamingEnv {}

#[tokio::test]
async fn coalesces_updates_within_throttle_window() {
    let inner = Arc::new(InMemoryExecutionEnv::with_cwd("/tmp/work".into()));
    let wrapper = Arc::new(StreamingEnv::new(inner));
    let env_dyn: Arc<dyn ExecutionEnv> = wrapper.clone() as Arc<dyn ExecutionEnv>;
    let mut_env: Arc<dyn MutatingEnv> = wrapper.clone() as Arc<dyn MutatingEnv>;
    let ctx = ExecutionToolContext::new(env_dyn, Some(mut_env));

    let tool = evo_tools::create_bash_tool(&ctx, None);

    // Count on_update invocations. The Arc<AtomicUsize> survives the closure.
    let count = Arc::new(AtomicUsize::new(0));
    let count_for_cb = count.clone();
    let on_update: Arc<dyn Fn(evo_agent::types::ToolResultPartial) + Send + Sync> =
        Arc::new(move |_p| {
            count_for_cb.fetch_add(1, Ordering::SeqCst);
        });

    let signal = CancellationToken::new();
    let _r = tool
        .execute(
            "bash-throttle",
            serde_json::json!({ "command": "stream" }),
            signal,
            on_update,
        )
        .await
        .expect("ok");

    let n = count.load(Ordering::SeqCst);
    // 500 raw chunks + 1 initial empty + 1 final flush. With a 100ms throttle
    // the whole stream (synchronous, sub-ms) collapses to very few flushes.
    // The TS test asserts updates.length < 25; we match that bound.
    assert!(n < 25, "throttle should coalesce, got {n} updates");
    assert!(n >= 1, "at least the initial empty update should fire");
}
