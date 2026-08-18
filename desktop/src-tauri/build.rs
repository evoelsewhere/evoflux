fn main() {
    // The updater verification key is compiled into release binaries. Make
    // Cargo invalidate cached builds when CI provisions or rotates the key.
    println!("cargo:rerun-if-env-changed=EVOFLUX_UPDATER_PUBLIC_KEY");
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "request_voice_permissions",
            "save_workspace_file",
            "backend_health",
            "backend_logs_path",
            "app_backend_status",
            "app_retry_backend",
            "app_reveal_backend_log",
            "app_check_for_updates",
            "app_remove_backend_server",
            "app_save_backend_server",
            "app_use_external_backend",
            "app_use_bundled_backend",
            "app_new_window",
            "app_browser_webview_navigate",
            "app_browser_webview_command",
            "app_browser_webview_url",
            "app_browser_webview_agent_action",
            "set_tray_session",
            "list_workspace_files",
            "read_workspace_file",
            "open_workspace_file_with_handle",
            "open_workspace_root_with_handle",
            "reveal_workspace_path_with_handle",
            "list_directory",
            "start_file_watcher",
            "stop_file_watcher",
            "list_workspace_openers",
            "open_workspace_with",
        ]),
    ))
    .expect("failed to build Tauri application");
}
