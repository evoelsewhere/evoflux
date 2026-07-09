fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "request_voice_permissions",
            "save_workspace_file",
            "backend_health",
            "backend_logs_path",
            "app_new_window",
            "set_tray_session",
            "list_workspace_files",
            "read_workspace_file",
        ]),
    ))
    .expect("failed to build Tauri application");
}
