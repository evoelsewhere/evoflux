use tauri::{AppHandle, Manager, UserAttentionType};

const MAIN_WINDOW: &str = "main";
#[cfg(target_os = "windows")]
const OVERLAY_SIZE: u32 = 16;
#[cfg(target_os = "windows")]
const OVERLAY_BYTES: usize = (OVERLAY_SIZE * OVERLAY_SIZE * 4) as usize;

#[tauri::command]
pub fn app_update_notification_badge(
    app: AppHandle,
    unread_count: u32,
    overlay_rgba: Option<Vec<u8>>,
    request_attention: bool,
) -> Result<(), String> {
    let window = app
        .get_webview_window(MAIN_WINDOW)
        .ok_or_else(|| "EvoFlux main window is unavailable".to_string())?;

    #[cfg(target_os = "windows")]
    {
        if unread_count == 0 {
            window
                .set_overlay_icon(None)
                .map_err(|error| format!("Could not clear taskbar badge: {error}"))?;
        } else {
            let rgba = overlay_rgba
                .ok_or_else(|| "Windows taskbar badge image is unavailable".to_string())?;
            if rgba.len() != OVERLAY_BYTES {
                return Err("Windows taskbar badge image has an invalid size".into());
            }
            let icon = tauri::image::Image::new_owned(rgba, OVERLAY_SIZE, OVERLAY_SIZE);
            window
                .set_overlay_icon(Some(icon))
                .map_err(|error| format!("Could not update taskbar badge: {error}"))?;
        }
    }

    #[cfg(target_os = "macos")]
    window
        .set_badge_count((unread_count > 0).then_some(unread_count as i64))
        .map_err(|error| format!("Could not update Dock badge: {error}"))?;

    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    let _ = (unread_count, overlay_rgba);

    if request_attention {
        window
            .request_user_attention(Some(UserAttentionType::Informational))
            .map_err(|error| format!("Could not request desktop attention: {error}"))?;
    }

    Ok(())
}
