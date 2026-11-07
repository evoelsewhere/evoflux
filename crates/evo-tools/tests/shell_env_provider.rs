//! `OsExecutionEnv::with_shell_env_provider`: extra variables and PATH folders
//! are read each time a command starts, so something installed while a chat is
//! open is visible to its next command. Needs a real shell; skipped without one.

use std::sync::{Arc, Mutex};

use evo_tools::{OsExecutionEnv, Shell, ShellEnv, ShellExecOptions};

#[tokio::test]
async fn the_provider_is_asked_for_every_command() {
    let value = Arc::new(Mutex::new(String::new()));
    let seen = value.clone();
    let tmp = std::env::temp_dir();
    let env = OsExecutionEnv::with_cwd(tmp).with_shell_env_provider(Arc::new(move || ShellEnv {
        vars: vec![("EVO_TEST_PROVIDED".into(), seen.lock().unwrap().clone())],
        path_append: vec![],
    }));
    let mut outputs = Vec::new();
    for text in ["first", "second"] {
        *value.lock().unwrap() = text.to_string();
        match env
            .exec("echo \"[$EVO_TEST_PROVIDED]\"", ShellExecOptions::default())
            .await
        {
            Ok(out) => outputs.push(out.stdout),
            Err(_) => return, // no bash here
        }
    }
    assert!(outputs[0].contains("[first]"), "{outputs:?}");
    assert!(outputs[1].contains("[second]"), "{outputs:?}");
}

#[tokio::test]
async fn path_folders_are_appended_after_the_inherited_ones() {
    let dir = std::env::temp_dir().join("evo-provided-bin");
    let appended = dir.clone();
    let env = OsExecutionEnv::with_cwd(std::env::temp_dir()).with_shell_env_provider(Arc::new(
        move || ShellEnv {
            vars: vec![],
            path_append: vec![appended.clone()],
        },
    ));
    let Ok(out) = env
        .exec("echo \"$PATH\"", ShellExecOptions::default())
        .await
    else {
        return;
    };
    let leaf = dir.file_name().unwrap().to_string_lossy().to_string();
    let path = out.stdout;
    let at = path.find(&leaf).expect("the folder is on PATH");
    assert!(
        at > path.len() / 3,
        "appended near the end, not first: {path}"
    );
}
