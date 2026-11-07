//! The sandbox policy (Settings → Sandbox) shapes real shell commands and file
//! tools. One test in its own binary: the policy is process-wide, so the steps
//! run in order rather than racing other tests.

use std::sync::Arc;

use evo_tools::sandbox::{configure, SandboxConfig};
use evo_tools::shell_output::{execute_shell_with_capture, ShellCaptureOptions};
use evo_tools::{OsExecutionEnv, Shell, ShellExecOptions};

#[tokio::test]
async fn sandbox_policy_shapes_shell_and_file_access() {
    let dir = tempfile::tempdir().expect("tempdir");
    let env = Arc::new(OsExecutionEnv::with_cwd(dir.path().to_path_buf()));
    if let Err(error) = env.exec("true", ShellExecOptions::default()).await {
        eprintln!("skipping: no usable shell ({error})");
        return;
    }
    std::env::set_var("EVO_SANDBOX_PROBE_TOKEN", "s3cret");
    let probe = r#"printf 'token=[%s] path=%s\n' "$EVO_SANDBOX_PROBE_TOKEN" "$(command -v ls >/dev/null && echo ok)""#;

    // Default: the host environment is inherited, as before.
    let out = env
        .exec(probe, ShellExecOptions::default())
        .await
        .expect("exec");
    assert_eq!(out.stdout.trim(), "token=[s3cret] path=ok");

    // Inherit off: secrets stay out, PATH still works.
    configure(SandboxConfig {
        inherit_env: false,
        ..Default::default()
    })
    .unwrap();
    let out = env
        .exec(probe, ShellExecOptions::default())
        .await
        .expect("exec");
    assert_eq!(out.stdout.trim(), "token=[] path=ok");

    // Load profile: a login shell, still in the workspace folder.
    let login = r#"shopt -q login_shell && echo login || echo plain; basename "$PWD""#;
    let folder = dir
        .path()
        .file_name()
        .unwrap()
        .to_string_lossy()
        .to_string();
    configure(SandboxConfig::default()).unwrap();
    let out = env
        .exec(login, ShellExecOptions::default())
        .await
        .expect("exec");
    assert_eq!(
        out.stdout.split_whitespace().collect::<Vec<_>>(),
        ["plain", folder.as_str()]
    );
    configure(SandboxConfig {
        load_profile: true,
        ..Default::default()
    })
    .unwrap();
    let out = env
        .exec(login, ShellExecOptions::default())
        .await
        .expect("exec");
    assert_eq!(
        out.stdout.split_whitespace().last(),
        Some(folder.as_str()),
        "stays in the workspace: {}",
        out.stdout
    );
    assert!(
        out.stdout.contains("login"),
        "runs as a login shell: {}",
        out.stdout
    );

    // A cap beats a longer timeout the model asked for.
    configure(SandboxConfig {
        max_timeout_secs: Some(1.0),
        ..Default::default()
    })
    .unwrap();
    let started = std::time::Instant::now();
    let result = env
        .exec(
            "sleep 20",
            ShellExecOptions {
                timeout: Some(60.0),
                ..Default::default()
            },
        )
        .await;
    assert!(result.is_err(), "the capped command should time out");
    assert!(
        started.elapsed().as_secs() < 10,
        "killed at the cap, not the requested 60s"
    );

    // Inline output follows the limit; the rest is in a file.
    configure(SandboxConfig {
        max_output_kib: Some(1),
        ..Default::default()
    })
    .unwrap();
    let shared: Arc<dyn evo_tools::ExecutionEnv> = env.clone();
    let capture = execute_shell_with_capture(
        &shared,
        "for i in $(seq 1 200); do echo line-$i-xxxxxxxxxxxxxxxxxxxx; done",
        ShellCaptureOptions::default(),
    )
    .await
    .expect("capture");
    assert!(capture.truncation.truncated);
    assert!(
        capture.output.len() <= 1024,
        "inline output is {} bytes",
        capture.output.len()
    );
    assert!(capture.output.contains("line-200-"), "the tail is kept");
    assert!(capture.full_output_path.is_some());

    // Denied patterns stop the file tools.
    configure(SandboxConfig {
        denied_patterns: vec!["**/.env".into()],
        ..Default::default()
    })
    .unwrap();
    let policy = evo_tools::sandbox::policy();
    let secret = dir.path().join(".env");
    assert!(policy
        .check_path(&secret.to_string_lossy(), Some(dir.path()))
        .is_err());
    assert!(policy
        .check_path(
            &dir.path().join("main.rs").to_string_lossy(),
            Some(dir.path())
        )
        .is_ok());

    configure(SandboxConfig::default()).unwrap();
}
