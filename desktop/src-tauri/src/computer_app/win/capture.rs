//! Capturing the attached window with `PrintWindow` — behind other windows
//! or off-screen — for the agent's screenshots and the preview card.

use super::*;

const PW_RENDERFULLCONTENT: PRINT_WINDOW_FLAGS = PRINT_WINDOW_FLAGS(2);

/// The window with its popups drawn over it, on a canvas covering `frame`
/// (their union). Popups are drawn bottom-most first.
fn capture_with_popups(window: HWND, popups: &[HWND], frame: RECT) -> Result<RgbaImage, String> {
    let base = capture(window)?;
    if popups.is_empty() {
        return Ok(base);
    }
    let width = (frame.right - frame.left).max(1) as u32;
    let height = (frame.bottom - frame.top).max(1) as u32;
    let mut canvas = RgbaImage::from_pixel(width, height, image::Rgba([24, 24, 24, 255]));
    let window_frame = frame_rect(window);
    imageops::overlay(
        &mut canvas,
        &base,
        i64::from(window_frame.left - frame.left),
        i64::from(window_frame.top - frame.top),
    );
    for popup in popups.iter().rev() {
        // A popup that will not render is left out rather than failing the
        // whole screenshot.
        if let Ok(image) = capture(*popup) {
            let popup_frame = frame_rect(*popup);
            imageops::overlay(
                &mut canvas,
                &image,
                i64::from(popup_frame.left - frame.left),
                i64::from(popup_frame.top - frame.top),
            );
        }
    }
    Ok(canvas)
}

// ── Capture ─────────────────────────────────────────────────────────────

/// Render `hwnd` with `PrintWindow`, cropped to its visible frame. Works for
/// windows behind other windows; the window renders itself into our bitmap.
pub(super) fn capture(hwnd: HWND) -> Result<RgbaImage, String> {
    // PrintWindow asks the app to paint synchronously; a hung app would
    // block this thread (and every action queued behind it) indefinitely.
    if unsafe { IsHungAppWindow(hwnd) }.as_bool() {
        return Err("The app is not responding. Wait for it, then try again.".into());
    }
    let mut window_rect = RECT::default();
    unsafe { GetWindowRect(hwnd, &mut window_rect) }
        .map_err(|error| format!("GetWindowRect failed: {error}"))?;
    let width = window_rect.right - window_rect.left;
    let height = window_rect.bottom - window_rect.top;
    if width <= 0 || height <= 0 {
        return Err("The window has no size to capture.".into());
    }

    let pixels = unsafe {
        let screen_dc = GetDC(None);
        if screen_dc.is_invalid() {
            return Err("GetDC failed".into());
        }
        let memory_dc = CreateCompatibleDC(Some(screen_dc));
        let bitmap = CreateCompatibleBitmap(screen_dc, width, height);
        let _ = ReleaseDC(None, screen_dc);
        if memory_dc.is_invalid() || bitmap.is_invalid() {
            if !bitmap.is_invalid() {
                let _ = DeleteObject(bitmap.into());
            }
            if !memory_dc.is_invalid() {
                let _ = DeleteDC(memory_dc);
            }
            return Err("Could not allocate a capture bitmap.".into());
        }
        let previous = SelectObject(memory_dc, bitmap.into());
        let mut rendered = PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT).as_bool();
        if !rendered {
            let window_dc = GetWindowDC(Some(hwnd));
            if !window_dc.is_invalid() {
                rendered =
                    BitBlt(memory_dc, 0, 0, width, height, Some(window_dc), 0, 0, SRCCOPY).is_ok();
                let _ = ReleaseDC(Some(hwnd), window_dc);
            }
        }
        let pixels = if rendered {
            read_pixels(memory_dc, bitmap, width as u32, height as u32)
        } else {
            Err("The window refused to render (PrintWindow and BitBlt both failed).".into())
        };
        let _ = SelectObject(memory_dc, previous);
        let _ = DeleteObject(bitmap.into());
        let _ = DeleteDC(memory_dc);
        pixels?
    };

    let full = RgbaImage::from_raw(width as u32, height as u32, pixels)
        .ok_or("Captured pixels did not match the window size.")?;
    let frame = frame_rect(hwnd);
    let left = (frame.left - window_rect.left).clamp(0, width - 1) as u32;
    let top = (frame.top - window_rect.top).clamp(0, height - 1) as u32;
    let crop_width = ((frame.right - frame.left).max(1) as u32).min(width as u32 - left);
    let crop_height = ((frame.bottom - frame.top).max(1) as u32).min(height as u32 - top);
    Ok(imageops::crop_imm(&full, left, top, crop_width, crop_height).to_image())
}

unsafe fn read_pixels(
    memory_dc: HDC,
    bitmap: HBITMAP,
    width: u32,
    height: u32,
) -> Result<Vec<u8>, String> {
    let mut info = BITMAPINFO {
        bmiHeader: BITMAPINFOHEADER {
            biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
            biWidth: width as i32,
            biHeight: -(height as i32),
            biPlanes: 1,
            biBitCount: 32,
            ..Default::default()
        },
        ..Default::default()
    };
    let mut pixels = vec![0u8; (width * height * 4) as usize];
    let lines = unsafe {
        GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            Some(pixels.as_mut_ptr() as *mut core::ffi::c_void),
            &mut info,
            DIB_RGB_COLORS,
        )
    };
    if lines == 0 {
        return Err("GetDIBits failed".into());
    }
    for pixel in pixels.chunks_exact_mut(4) {
        pixel.swap(0, 2);
        // GetDIBits leaves alpha at 0, which would read as fully transparent.
        pixel[3] = 255;
    }
    Ok(pixels)
}

pub(super) fn encode_png(image: &RgbaImage) -> Result<String, String> {
    let mut bytes = std::io::Cursor::new(Vec::new());
    image
        .write_to(&mut bytes, image::ImageFormat::Png)
        .map_err(|error| format!("PNG encoding failed: {error}"))?;
    Ok(BASE64.encode(bytes.into_inner()))
}

fn encode_jpeg(image: &RgbaImage, quality: u8) -> Result<String, String> {
    let rgb = DynamicImage::ImageRgba8(image.clone()).to_rgb8();
    let mut bytes = Vec::new();
    image::codecs::jpeg::JpegEncoder::new_with_quality(&mut bytes, quality)
        .encode_image(&rgb)
        .map_err(|error| format!("JPEG encoding failed: {error}"))?;
    Ok(BASE64.encode(bytes))
}

pub(super) fn screenshot(target: &Target) -> Result<Value, String> {
    let captured = capture_with_popups(target.window, &target.popups, target.frame)?;
    let (width, height) = target.screenshot_size();
    let image = if target.scale < 1.0 {
        imageops::resize(&captured, width, height, imageops::FilterType::Triangle)
    } else {
        captured
    };
    Ok(json!({
        "kind": "image",
        "data": encode_png(&image)?,
        "media_type": "image/png",
        "width": image.width(),
        "height": image.height(),
        "window": target.describe(),
        "restored": target.restored,
    }))
}

/// A small JPEG of the attached window for the preview card. Never restores
/// a minimized window: watching must not change what is on screen.
pub(super) fn preview_frame(session_id: &str, max_width: u32) -> Result<Value, String> {
    let (attached, stopped) = {
        let registry = registry();
        (
            registry.attached.get(session_id).cloned(),
            registry.stopped.contains(session_id),
        )
    };
    let Some(attached) = attached else {
        return Ok(json!({ "attached": false, "stopped": stopped }));
    };
    let top = to_hwnd(attached.hwnd);
    // Never paint the app while typing is between two of its safe points.
    let gate = input_gate(session_id);
    let _typing_done = hold_gate(&gate);
    let base = json!({
        "attached": true,
        "stopped": stopped,
        "app": attached.app,
        "title": attached.title,
    });
    if !unsafe { IsWindow(Some(top)) }.as_bool() {
        return Ok(merge(base, json!({ "closed": true })));
    }
    let title = window_title(top);
    if unsafe { IsIconic(top) }.as_bool() {
        return Ok(merge(base, json!({ "minimized": true, "title": title })));
    }
    if attached.parked.is_some() {
        keep_opened_windows_along(session_id, top, attached.pid);
    }
    let window = effective_window(top, attached.pid);
    let popups = open_popups(window, top, attached.pid);
    let frame = popups
        .iter()
        .fold(frame_rect(window), |frame, popup| union(frame, frame_rect(*popup)));
    let captured = capture_with_popups(window, &popups, frame)?;
    let (width, height) = (captured.width(), captured.height());
    let preview = if width > max_width {
        let scaled_height = ((height as f64) * (max_width as f64) / (width as f64)).round() as u32;
        imageops::thumbnail(&captured, max_width, scaled_height.max(1))
    } else {
        captured
    };
    Ok(merge(
        base,
        json!({
            "title": title,
            "dialog": window != top,
            "width": width,
            "height": height,
            "media_type": "image/jpeg",
            "data": encode_jpeg(&preview, 72)?,
        }),
    ))
}
