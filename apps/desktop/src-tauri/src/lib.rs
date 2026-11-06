//! evo desktop shell.
//!
//! The shell owns no agent logic. It starts `evo-engine --mode rpc` as a child
//! process (see [`engine`]) and relays the engine's JSONL protocol to the web
//! UI: commands go in through the `engine_send` command, and every line the
//! engine prints comes back as an `engine://message` event. Running the engine
//! out of process means a crashing native extension cannot take the window down.

mod apps;
mod browser;
mod db;
mod engine;
mod files;
mod mcp;
mod mesh;
mod plugins;
mod system;
mod worktrees;
mod terminal;
mod window;

use std::sync::Mutex;

use tauri::Manager;

pub fn run() {
    tauri::Builder::default()
        // First: a second launch (Start menu, dock, sign-in) shows this one instead.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| system::show_main(app)))
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec![system::HIDDEN_ARG]),
        ))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .manage(engine::EngineState::default())
        .manage(apps::AppsState::default())
        .manage(match db::Db::open() {
            Ok(db) => db,
            // Without its database the app cannot keep chats; say why and stop.
            Err(error) => panic!("could not open the evo database: {error}"),
        })
        .manage(window::MaterialState(Mutex::new(window::Material::None)))
        .manage(system::SystemState::default())
        .manage(terminal::TerminalState::default())
        .manage(browser::BrowserState::default())
        .setup(|app| {
            // The session mesh hub: mail between chats' engines.
            app.manage(mesh::MeshHub::new(app.handle().clone()));
            if let Some(main) = app.get_window("main") {
                let material = window::apply(&main, None);
                *app.state::<window::MaterialState>()
                    .0
                    .lock()
                    .expect("material lock") = material;
            }
            app.state::<db::Db>().log(evo_store::logs::NewLog::new(
                "info",
                "shell",
                format!("evo desktop {} started", env!("CARGO_PKG_VERSION")),
            ));
            // The main window starts hidden (tauri.conf.json) and shows here,
            // unless evo was started at sign-in into the tray.
            system::setup(app.handle());
            // Connectors: one MCP pool for every chat.
            mcp::setup(app.handle());
            // Plugins' connectors join the pool.
            plugins::setup(app.handle());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                system::on_close_requested(window, api);
            }
            // A chat window owns its chat's engine: closing it stops the engine.
            if let tauri::WindowEvent::Destroyed = event {
                let label = window.label().to_string();
                // A window's terminals end with it.
                window.app_handle().state::<terminal::TerminalState>().kill_window(&label);
                window.app_handle().state::<browser::BrowserState>().close_window(window.app_handle(), &label);
                if label.starts_with(window::CHAT_WINDOW_PREFIX) {
                    let app = window.app_handle().clone();
                    tauri::async_runtime::spawn(async move {
                        let engines = app.state::<engine::EngineState>();
                        let chats: Vec<String> = engines.running().await;
                        for chat in chats.into_iter().filter(|chat| window::chat_window_label(chat) == label) {
                            engines.stop(&chat).await;
                        }
                    });
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            engine::engine_start,
            engine::engine_send,
            engine::engine_stop,
            engine::engine_info,
            engine::engine_running,
            mesh::mesh_pending,
            mesh::mesh_pending_chats,
            mesh::mesh_hosted,
            mesh::mesh_configure,
            mesh::mesh_session_tools,
            mesh::mesh_start_session,
            db::db_info,
            db::db_reveal,
            db::workspaces_list,
            db::workspace_ensure,
            db::workspace_set_collapsed,
            db::workspace_remove,
            db::chats_list,
            db::chats_search,
            db::chat_create,
            db::chat_update,
            db::chat_record_turn,
            db::chat_fork,
            db::chat_move,
            db::chat_set_parent,
            db::chat_set_worktree,
            db::chat_delete,
            db::settings_all,
            db::settings_set,
            db::logs_append,
            db::logs_query,
            db::logs_clear,
            db::logs_export,
            db::usage_summary,
            db::usage_events,
            db::usage_clear,
            window::window_material,
            window::window_set_theme,
            window::window_devtools,
            window::chat_window_open,
            window::chat_window_focus,
            window::chat_window_close,
            system::system_settings,
            mcp::mcp_state,
            mcp::mcp_upsert,
            mcp::mcp_remove,
            mcp::mcp_set_enabled,
            mcp::mcp_reconnect,
            mcp::mcp_set_permission,
            mcp::mcp_chat_tools,
            mcp::mcp_call,
            mcp::mcp_get_prompt,
            mcp::mcp_sign_in,
            mcp::mcp_sign_out,
            mcp::mcp_project_state,
            mcp::mcp_open_project,
            mcp::mcp_set_project_approval,
            mcp::mcp_read_resource,
            plugins::plugins_state,
            plugins::plugin_marketplace_add,
            plugins::plugin_marketplace_update,
            plugins::plugin_marketplace_remove,
            plugins::plugin_install,
            plugins::plugin_install_folder,
            plugins::plugin_uninstall,
            plugins::plugin_update,
            plugins::plugin_set_enabled,
            plugins::plugin_set_config,
            worktrees::worktree_create,
            worktrees::worktree_list,
            worktrees::worktree_changes,
            worktrees::worktree_apply,
            worktrees::worktree_discard,
            worktrees::git_status,
            system::system_set,
            apps::open_apps,
            apps::open_in_app,
            files::fs_list_dir,
            files::fs_stat,
            files::fs_read_file,
            files::fs_write_file,
            files::fs_save_paste,
            files::fs_search,
            files::fs_grep,
            browser::browser_create,
            browser::browser_bounds,
            browser::browser_visible,
            browser::browser_navigate,
            browser::browser_history,
            browser::browser_url,
            browser::browser_close,
            browser::browser_devtools,
            browser::browser_list,
            browser::browser_zoom,
            browser::browser_eval,
            browser::browser_cdp,
            terminal::terminal_shells,
            terminal::terminal_spawn,
            terminal::terminal_write,
            terminal::terminal_resize,
            terminal::terminal_kill,
            terminal::terminal_list,
            terminal::terminal_attach,
        ])
        .build(tauri::generate_context!())
        .expect("error while building the evo desktop app")
        .run(|_app, _event| {
            // Stop the connectors' servers with the app.
            if let tauri::RunEvent::Exit = _event {
                mcp::shutdown(_app);
            }
            // The dock icon reopens the window hidden behind the tray.
            #[cfg(target_os = "macos")]
            if let tauri::RunEvent::Reopen { .. } = _event {
                system::show_main(_app);
            }
        });
}
