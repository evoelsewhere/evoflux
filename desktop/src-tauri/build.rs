fn main() {
    // The updater verification key is compiled into release binaries. Make
    // Cargo invalidate cached builds when CI provisions or rotates the key.
    println!("cargo:rerun-if-env-changed=EVOFLUX_UPDATER_PUBLIC_KEY");
    // ScreenCaptureKit only exists from macOS 12.3 and its screenshot API
    // from 14; the app supports macOS 11, so a missing framework must not stop
    // it from launching. The capture code checks for the classes at run time.
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("macos") {
        println!("cargo:rustc-link-arg=-Wl,-weak_framework,ScreenCaptureKit");
    }
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
            "app_install_update",
            "app_remove_backend_server",
            "app_save_backend_server",
            "app_use_external_backend",
            "app_use_bundled_backend",
            "app_new_window",
            "app_menu_action",
            "app_browser_webview_navigate",
            "app_browser_webview_command",
            "app_browser_webview_url",
            "app_browser_webview_agent_action",
            "app_browser_webview_bind_shortcuts",
            "app_browser_webview_is_loading",
            "app_computer_action",
            "app_computer_frame",
            "app_computer_stop",
            "app_computer_interrupt",
            "app_computer_resume",
            "app_computer_reveal",
            "app_computer_list_apps",
            "app_computer_permissions",
            "app_computer_request_permission",
            "app_computer_restart",
            "set_tray_session",
            "list_workspace_files",
            "app_desktop_settings",
            "app_update_desktop_settings",
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
