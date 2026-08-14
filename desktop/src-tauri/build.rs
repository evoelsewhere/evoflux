fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "request_voice_permissions",
            "save_workspace_file",
            "backend_health",
            "backend_logs_path",
            "app_new_window",
            "app_browser_webview_navigate",
            "app_browser_webview_command",
            "app_browser_webview_url",
            "app_browser_webview_agent_action",
            "set_tray_session",
            "list_workspace_files",
            "read_workspace_file",
            "open_workspace_root_with_handle",
            "reveal_workspace_path_with_handle",
            "list_workspace_openers",
            "open_workspace_with",
        ]),
    ))
    .expect("failed to build Tauri application");
}
