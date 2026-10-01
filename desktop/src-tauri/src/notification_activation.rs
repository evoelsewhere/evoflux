use serde::Deserialize;
use tauri::{AppHandle, Wry};
use url::Url;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AttentionActivation {
    mode: String,
    session_id: String,
    #[serde(default)]
    focus_id: Option<String>,
    event_kind: String,
    #[serde(default)]
    request_id: Option<String>,
    #[serde(default)]
    actions: Vec<AttentionAction>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AttentionAction {
    id: String,
    label: String,
    #[serde(default)]
    input: Option<String>,
}

fn allowed_event_kind(value: &str) -> bool {
    matches!(
        value,
        "question_asked"
            | "permission_asked"
            | "agent_not_configured"
            | "terminal_error"
            | "goal_blocked"
            | "assistant_done"
            | "background_done"
            | "reminder_fired"
    )
}

fn safe_token(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

fn is_uuid(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(index, byte)| match index {
            8 | 13 | 18 | 23 => byte == b'-',
            _ => byte.is_ascii_hexdigit(),
        })
}

fn scheme_for_identifier(identifier: &str) -> Result<&'static str, String> {
    match identifier {
        "com.evoflux.desktop" => Ok("evoflux"),
        "com.evoflux.desktop.dev" => Ok("evoflux-dev"),
        "com.evoflux.desktop.dev.bundled" => Ok("evoflux-dev-bundled"),
        _ => Err("Unsupported EvoFlux desktop identifier".into()),
    }
}

fn activation_url(
    scheme: &str,
    activation: &AttentionActivation,
    action: Option<&AttentionAction>,
) -> Result<String, String> {
    if !matches!(activation.mode.as_str(), "work" | "coding")
        || !is_uuid(&activation.session_id)
        || !allowed_event_kind(&activation.event_kind)
    {
        return Err("Invalid notification activation".into());
    }
    if activation.mode == "coding" && !activation.focus_id.as_deref().is_some_and(is_uuid) {
        return Err("Invalid coding notification target".into());
    }
    if activation.mode == "work" && activation.focus_id.is_some() {
        return Err("Work notifications cannot include a focus id".into());
    }
    if matches!(
        activation.event_kind.as_str(),
        "question_asked" | "permission_asked"
    ) && !activation.request_id.as_deref().is_some_and(safe_token)
    {
        return Err("Interactive notification is missing its request id".into());
    }

    let mut url = Url::parse(&format!("{scheme}://notification"))
        .map_err(|_| "Invalid notification URL scheme".to_string())?;
    {
        let mut query = url.query_pairs_mut();
        query
            .append_pair("v", "1")
            .append_pair("mode", &activation.mode)
            .append_pair("session_id", &activation.session_id)
            .append_pair("event_kind", &activation.event_kind);
        if let Some(focus_id) = activation.focus_id.as_deref() {
            query.append_pair("focus_id", focus_id);
        }
        if let Some(request_id) = activation.request_id.as_deref() {
            query.append_pair("request_id", request_id);
        }
        if let Some(action) = action {
            if !action_allowed_for_event(&action.id, &activation.event_kind)
                || action.label.trim().is_empty()
                || action.label.chars().count() > 48
            {
                return Err("Invalid notification action".into());
            }
            query.append_pair("action_id", &action.id);
            if let Some(input) = action.input.as_deref() {
                if !matches!(action.id.as_str(), "choice" | "answer")
                    || input.is_empty()
                    || input.len() > 2048
                    || input.chars().any(char::is_control)
                {
                    return Err("Invalid notification action input".into());
                }
                query.append_pair("input", input);
            }
        } else {
            query.append_pair("action_id", "open");
        }
    }
    Ok(url.into())
}

fn action_allowed_for_event(action: &str, event: &str) -> bool {
    match event {
        "question_asked" => matches!(action, "choice" | "answer" | "spawn-defaults"),
        "permission_asked" => matches!(action, "permission-once" | "permission-reject"),
        _ => false,
    }
}

fn xml_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

#[tauri::command]
pub async fn app_send_attention_notification(
    app: AppHandle<Wry>,
    title: String,
    body: String,
    activation: Option<AttentionActivation>,
) -> Result<(), String> {
    let title = title.chars().take(120).collect::<String>();
    let body = body.chars().take(360).collect::<String>();
    let identifier = app.config().identifier.clone();
    let scheme = scheme_for_identifier(&identifier)?;

    #[cfg(windows)]
    {
        tauri::async_runtime::spawn_blocking(move || {
            windows::show_toast(&app, &identifier, &title, &body, scheme, &activation)
        })
        .await
        .map_err(|error| format!("Notification worker failed: {error}"))??;
        Ok(())
    }

    #[cfg(not(windows))]
    {
        let _ = (scheme, activation);
        use tauri_plugin_notification::NotificationExt;
        app.notification()
            .builder()
            .title(title)
            .body(body)
            .show()
            .map_err(|error| format!("Native notification failed: {error}"))
    }
}

pub fn install_identity(app: &AppHandle<Wry>) -> Result<(), String> {
    #[cfg(windows)]
    {
        let identifier = app.config().identifier.clone();
        std::thread::spawn(move || windows::install_identity(&identifier))
            .join()
            .map_err(|_| "Notification identity worker panicked".to_string())??;
    }
    #[cfg(not(windows))]
    let _ = app;
    Ok(())
}

/// Forward a notification deep link to an already-running Windows instance
/// before Tauri initializes a second WebView process.
///
/// Windows protocol activation starts the registered executable even when the
/// app is already open. The single-instance plugin normally forwards that URL,
/// but only after the new Tauri process initializes. The WM_COPYDATA handoff
/// lets the already-running app receive the activation without launching a
/// second WebView process. Keep the payload compatible with
/// tauri-plugin-single-instance's
/// Windows adapter (`cwd|arg0|arg1...`).
pub fn forward_notification_activation_to_running_instance() -> bool {
    #[cfg(windows)]
    {
        windows::forward_notification_activation_to_running_instance()
    }
    #[cfg(not(windows))]
    {
        false
    }
}

#[cfg(windows)]
mod windows {
    use super::{activation_url, xml_escape, AttentionActivation, Url};
    use ::windows::core::{Interface, GUID, HSTRING, PWSTR};
    use ::windows::Data::Xml::Dom::XmlDocument;
    use ::windows::Foundation::{IPropertyValue, TypedEventHandler};
    use ::windows::Win32::Storage::EnhancedStorage::{
        PKEY_AppUserModel_ID, PKEY_AppUserModel_ToastActivatorCLSID,
    };
    use ::windows::Win32::System::Com::StructuredStorage::{
        PropVariantClear, PROPVARIANT, PROPVARIANT_0_0, PROPVARIANT_0_0_0,
    };
    use ::windows::Win32::System::Com::{
        CoCreateInstance, CoTaskMemAlloc, IPersistFile, CLSCTX_INPROC_SERVER,
    };
    use ::windows::Win32::System::Console::FreeConsole;
    use ::windows::Win32::System::DataExchange::COPYDATASTRUCT;
    use ::windows::Win32::System::Variant::{VT_CLSID, VT_LPWSTR};
    use ::windows::Win32::System::WinRT::{RoInitialize, RoUninitialize, RO_INIT_MULTITHREADED};
    use ::windows::Win32::UI::Shell::PropertiesSystem::IPropertyStore;
    use ::windows::Win32::UI::Shell::{
        IShellLinkW, SetCurrentProcessExplicitAppUserModelID, ShellLink,
    };
    use ::windows::Win32::UI::WindowsAndMessaging::{
        FindWindowW, SendMessageTimeoutW, SMTO_ABORTIFHUNG, SMTO_BLOCK, WM_COPYDATA,
    };
    use ::windows::UI::Notifications::{
        ToastActivatedEventArgs, ToastNotification, ToastNotificationManager,
    };
    use std::path::PathBuf;
    use tauri::{AppHandle, Emitter, Wry};

    const ACTIVATOR_STUB: GUID = GUID::from_u128(0xe1b8d7c6_3f80_4d78_9b29_b99f87562740);
    const SINGLE_INSTANCE_COPYDATA_ID: usize = 1542;

    pub(super) fn forward_notification_activation_to_running_instance() -> bool {
        let mut args = std::env::args_os();
        let Some(executable) = args.next() else {
            return false;
        };
        let Some(activation) = args.next() else {
            return false;
        };
        if args.next().is_some() {
            return false;
        }
        let activation = activation.to_string_lossy();
        let Ok(url) = Url::parse(&activation) else {
            return false;
        };
        if url.host_str() != Some("notification") {
            return false;
        }
        let identifier = match url.scheme() {
            "evoflux" => "com.evoflux.desktop",
            "evoflux-dev" => "com.evoflux.desktop.dev",
            "evoflux-dev-bundled" => "com.evoflux.desktop.dev.bundled",
            _ => return false,
        };

        // This process exists only to deliver the protocol activation. Detach
        // from any inherited console before exiting after the handoff.
        let _ = unsafe { FreeConsole() };

        let class_name: Vec<u16> = format!("{identifier}-sic")
            .encode_utf16()
            .chain(Some(0))
            .collect();
        let window_name: Vec<u16> = format!("{identifier}-siw")
            .encode_utf16()
            .chain(Some(0))
            .collect();
        let Ok(window) = (unsafe {
            FindWindowW(
                ::windows::core::PCWSTR(class_name.as_ptr()),
                ::windows::core::PCWSTR(window_name.as_ptr()),
            )
        }) else {
            return false;
        };

        let cwd = std::env::current_dir().unwrap_or_default();
        let payload = format!(
            "{}|{}|{}\0",
            cwd.to_string_lossy(),
            executable.to_string_lossy(),
            activation
        );
        let copy_data = COPYDATASTRUCT {
            dwData: SINGLE_INSTANCE_COPYDATA_ID,
            cbData: payload.len() as u32,
            lpData: payload.as_ptr() as *mut std::ffi::c_void,
        };
        let mut response = 0usize;
        let sent = unsafe {
            SendMessageTimeoutW(
                window,
                WM_COPYDATA,
                ::windows::Win32::Foundation::WPARAM(0),
                ::windows::Win32::Foundation::LPARAM(&copy_data as *const _ as isize),
                SMTO_ABORTIFHUNG | SMTO_BLOCK,
                1_500,
                Some(&mut response),
            )
        };
        sent.0 != 0 && response != 0
    }

    fn app_user_model_id(identifier: &str) -> Result<String, String> {
        if !matches!(
            identifier,
            "com.evoflux.desktop" | "com.evoflux.desktop.dev" | "com.evoflux.desktop.dev.bundled"
        ) {
            return Err("Unsupported EvoFlux desktop identifier".into());
        }
        Ok(identifier.to_string())
    }

    fn with_winrt<T>(operation: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
        unsafe { RoInitialize(RO_INIT_MULTITHREADED) }.map_err(|error| {
            format!("Windows notification runtime could not initialize: {error}")
        })?;
        let result = operation();
        unsafe { RoUninitialize() };
        result
    }

    fn prop_variant_string(value: &str) -> Result<PROPVARIANT, String> {
        let wide: Vec<u16> = value.encode_utf16().chain(Some(0)).collect();
        let bytes = wide.len() * std::mem::size_of::<u16>();
        let buffer = unsafe { CoTaskMemAlloc(bytes) }.cast::<u16>();
        if buffer.is_null() {
            return Err("Windows could not allocate notification identity".into());
        }
        unsafe { std::ptr::copy_nonoverlapping(wide.as_ptr(), buffer, wide.len()) };
        let mut value = PROPVARIANT::default();
        value.Anonymous.Anonymous = std::mem::ManuallyDrop::new(PROPVARIANT_0_0 {
            vt: VT_LPWSTR,
            wReserved1: 0,
            wReserved2: 0,
            wReserved3: 0,
            Anonymous: PROPVARIANT_0_0_0 {
                pwszVal: PWSTR(buffer),
            },
        });
        Ok(value)
    }

    fn prop_variant_guid(value: GUID) -> Result<PROPVARIANT, String> {
        let buffer = unsafe { CoTaskMemAlloc(std::mem::size_of::<GUID>()) }.cast::<GUID>();
        if buffer.is_null() {
            return Err("Windows could not allocate notification activator id".into());
        }
        unsafe { buffer.write(value) };
        let mut variant = PROPVARIANT::default();
        variant.Anonymous.Anonymous = std::mem::ManuallyDrop::new(PROPVARIANT_0_0 {
            vt: VT_CLSID,
            wReserved1: 0,
            wReserved2: 0,
            wReserved3: 0,
            Anonymous: PROPVARIANT_0_0_0 { puuid: buffer },
        });
        Ok(variant)
    }

    fn set_shortcut_property(
        store: &IPropertyStore,
        key: *const windows::Win32::Foundation::PROPERTYKEY,
        value: &mut PROPVARIANT,
    ) -> Result<(), String> {
        let result = unsafe { store.SetValue(key, value).and_then(|_| store.Commit()) }
            .map_err(|error| format!("Windows shortcut property could not be saved: {error}"));
        let _ = unsafe { PropVariantClear(value) };
        result
    }

    fn start_menu_link(identifier: &str) -> Result<PathBuf, String> {
        let app_data = std::env::var_os("APPDATA")
            .ok_or_else(|| "Windows user profile path is unavailable".to_string())?;
        let display_name = match identifier {
            "com.evoflux.desktop" => "EvoFlux",
            "com.evoflux.desktop.dev" => "EvoFlux (dev)",
            "com.evoflux.desktop.dev.bundled" => "EvoFlux (dev bundled)",
            _ => return Err("Unsupported EvoFlux desktop identifier".into()),
        };
        let directory = PathBuf::from(app_data)
            .join("Microsoft")
            .join("Windows")
            .join("Start Menu")
            .join("Programs");
        std::fs::create_dir_all(&directory).map_err(|error| {
            format!("Start menu shortcut directory could not be created: {error}")
        })?;
        Ok(directory.join(format!("{display_name}.lnk")))
    }

    fn ensure_shortcut(identifier: &str, aumid: &str) -> Result<(), String> {
        let executable = std::env::current_exe()
            .map_err(|error| format!("App executable path is unavailable: {error}"))?;
        let shortcut_path = start_menu_link(identifier)?;
        let shortcut: IShellLinkW = unsafe {
            CoCreateInstance(&ShellLink, None, CLSCTX_INPROC_SERVER)
                .map_err(|error| format!("Windows shortcut could not be created: {error}"))?
        };
        let executable_text = HSTRING::from(executable.as_os_str());
        unsafe {
            shortcut
                .SetPath(&executable_text)
                .map_err(|error| format!("Windows shortcut target could not be set: {error}"))?;
            shortcut
                .SetIconLocation(&executable_text, 0)
                .map_err(|error| format!("Windows shortcut icon could not be set: {error}"))?;
        }

        let store: IPropertyStore = shortcut
            .cast()
            .map_err(|error| format!("Windows shortcut property store is unavailable: {error}"))?;
        let mut id_value = prop_variant_string(aumid)?;
        set_shortcut_property(&store, &PKEY_AppUserModel_ID, &mut id_value)?;
        let mut activator_value = prop_variant_guid(ACTIVATOR_STUB)?;
        set_shortcut_property(
            &store,
            &PKEY_AppUserModel_ToastActivatorCLSID,
            &mut activator_value,
        )?;

        let persist: IPersistFile = shortcut
            .cast()
            .map_err(|error| format!("Windows shortcut could not be saved: {error}"))?;
        unsafe {
            persist
                .Save(&HSTRING::from(shortcut_path.as_os_str()), true)
                .map_err(|error| format!("Windows shortcut could not be saved: {error}"))?;
        }
        Ok(())
    }

    pub(super) fn install_identity(identifier: &str) -> Result<(), String> {
        let identifier = identifier.to_string();
        let aumid = app_user_model_id(&identifier)?;
        with_winrt(|| {
            ensure_shortcut(&identifier, &aumid)?;
            let app_id = HSTRING::from(aumid);
            unsafe { SetCurrentProcessExplicitAppUserModelID(&app_id) }.map_err(|error| {
                format!("Windows app notification identity could not be set: {error}")
            })
        })
    }

    pub(super) fn show_toast(
        app: &AppHandle<Wry>,
        identifier: &str,
        title: &str,
        body: &str,
        scheme: &str,
        activation: &Option<AttentionActivation>,
    ) -> Result<(), String> {
        let aumid = app_user_model_id(identifier)?;
        let title = xml_escape(title);
        let body = xml_escape(body);
        let mut action_xml = String::new();
        let launch = if let Some(activation) = activation {
            let has_text_reply = activation
                .actions
                .iter()
                .any(|action| action.id == "answer");
            for action in activation.actions.iter().take(3) {
                let url = activation_url(scheme, activation, Some(action))?;
                if action.id == "answer" {
                    action_xml.push_str(&format!(
                        "<action activationType=\"foreground\" arguments=\"{}\" content=\"{}\" hint-inputId=\"answerInput\" />",
                        xml_escape(&url),
                        xml_escape(action.label.trim()),
                    ));
                } else {
                    action_xml.push_str(&format!(
                        "<action activationType=\"protocol\" arguments=\"{}\" content=\"{}\" />",
                        xml_escape(&url),
                        xml_escape(action.label.trim()),
                    ));
                }
            }
            if has_text_reply {
                let reply_label = activation
                    .actions
                    .iter()
                    .find(|action| action.id == "answer")
                    .map(|action| xml_escape(action.label.trim()))
                    .unwrap_or_else(|| "Reply".to_string());
                action_xml.insert_str(0, &format!(
                    "<input id=\"answerInput\" type=\"text\" placeHolderContent=\"{reply_label}\" />"
                ));
            }
            activation_url(scheme, activation, None)?
        } else {
            // A generic branded notification (for example the settings test
            // button) opens EvoFlux without selecting a session.
            format!("{scheme}://notification")
        };
        let launch = xml_escape(&launch);
        if !action_xml.is_empty() {
            action_xml = format!("<actions>{action_xml}</actions>");
        }
        let xml = format!(
            r#"<toast activationType="protocol" launch="{launch}"><visual><binding template="ToastGeneric"><text>{title}</text><text>{body}</text></binding></visual><audio silent="true" />{action_xml}</toast>"#
        );
        with_winrt(|| {
            let app_id = HSTRING::from(aumid);
            unsafe { SetCurrentProcessExplicitAppUserModelID(&app_id) }.map_err(|error| {
                format!("Windows app notification identity could not be set: {error}")
            })?;
            let document = XmlDocument::new().map_err(|error| {
                format!("Windows notification XML could not be created: {error}")
            })?;
            document
                .LoadXml(&HSTRING::from(xml))
                .map_err(|error| format!("Windows notification XML was rejected: {error}"))?;
            let toast = ToastNotification::CreateToastNotification(&document)
                .map_err(|error| format!("Windows toast could not be created: {error}"))?;
            let app_for_activation = app.clone();
            let activation_handler = TypedEventHandler::new(
                move |_: ::windows::core::Ref<'_, ToastNotification>,
                      event_args: ::windows::core::Ref<'_, ::windows::core::IInspectable>| {
                    let Some(event_args) = event_args.as_ref() else {
                        return Ok(());
                    };
                    let Ok(activated) = event_args.cast::<ToastActivatedEventArgs>() else {
                    return Ok(());
                };
                let Ok(arguments) = activated.Arguments() else {
                    return Ok(());
                };
                let mut url = arguments.to_string();
                if let Ok(user_input) = activated.UserInput() {
                    if let Ok(value) = user_input.Lookup(&HSTRING::from("answerInput")) {
                        if let Ok(value) = value.cast::<IPropertyValue>() {
                            if let Ok(input) = value.GetString() {
                                let input = input.to_string();
                                if !input.trim().is_empty() && input.len() <= 2048 {
                                    if let Ok(mut parsed) = Url::parse(&url) {
                                        parsed.query_pairs_mut().append_pair("input", &input);
                                        url = parsed.into();
                                    }
                                }
                            }
                        }
                    }
                }
                let _ = app_for_activation.emit(
                    "notification-action-activation",
                    serde_json::json!({ "url": url }),
                );
                Ok(())
                },
            );
            toast.Activated(&activation_handler).map_err(|error| {
                format!("Windows toast activation could not be registered: {error}")
            })?;
            let notifier =
                ToastNotificationManager::CreateToastNotifierWithId(&app_id).map_err(|error| {
                    format!("Windows notification app identity is not registered: {error}")
                })?;
            notifier
                .Show(&toast)
                .map_err(|error| format!("Windows toast could not be shown: {error}"))
        })
    }
}
