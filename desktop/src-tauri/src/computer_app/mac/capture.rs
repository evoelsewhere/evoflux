//! Capturing the attached window from the window server — behind other
//! windows or parked — for the agent's screenshots and the preview card.

use super::*;

// ── Capture ─────────────────────────────────────────────────────────────

/// Render the window (with the app's own sheets, alerts and menus stacked
/// over it) from the window server's copy of it: works behind other windows
/// and while parked.
/// Where the window's sheets are: a sheet is a window of its own to the
/// window server, at the same level as another document window.
pub(super) fn sheet_frames(window: &Ax) -> Vec<Rect> {
    window
        .elements("AXChildren")
        .into_iter()
        .filter(|child| child.role() == "AXSheet")
        .filter_map(|sheet| sheet.frame())
        .collect()
}

fn same_frame(a: &Rect, b: &Rect) -> bool {
    (a.x - b.x).abs() < 2.0 && (a.y - b.y).abs() < 2.0 && (a.w - b.w).abs() < 2.0 && (a.h - b.h).abs() < 2.0
}

fn capture(window_id: u32, pid: i32, frame: Rect, sheets: &[Rect]) -> Result<RgbaImage, String> {
    if !screen_capture_allowed() {
        // Shows macOS's own prompt the first time; later it only answers.
        unsafe { CGRequestScreenCaptureAccess() };
        return Err(SCREEN_RECORDING_REFUSAL.into());
    }
    let options =
        kCGWindowImageBoundsIgnoreFraming | kCGWindowImageNominalResolution | kCGWindowImageShouldBeOpaque;
    // Over the window: its menus, popovers and panels (above the normal
    // level) and its sheets — not another document window of the app that
    // happens to overlap it, which the capture used to paint over it.
    let mut ids: Vec<u32> = cg_windows(kCGWindowListOptionOnScreenAboveWindow, window_id)
        .into_iter()
        .filter(|window| window.pid == pid && window.bounds.intersects(&frame))
        .filter(|window| window.layer != 0 || sheets.iter().any(|sheet| same_frame(sheet, &window.bounds)))
        .map(|window| window.id)
        .collect();
    ids.push(window_id);
    let image = create_image_from_array(frame.to_cg(), window_id_array(&ids), options)
        .or_else(|| create_image(frame.to_cg(), kCGWindowListOptionIncludingWindow, window_id, options))
        .ok_or("macOS returned no image of the window.")?;
    let (width, height) = (image.width(), image.height());
    if width == 0 || height == 0 || image.bits_per_pixel() != 32 {
        return Err("macOS returned an empty or unexpected image of the window.".into());
    }
    let bytes_per_row = image.bytes_per_row();
    let data = image.data();
    let bytes = data.bytes();
    let mut pixels = Vec::with_capacity(width * height * 4);
    for row in bytes.chunks(bytes_per_row).take(height) {
        pixels.extend_from_slice(&row[..width * 4]);
    }
    for pixel in pixels.chunks_exact_mut(4) {
        // Window images are BGRA in memory.
        pixel.swap(0, 2);
        pixel[3] = 255;
    }
    let captured = RgbaImage::from_raw(width as u32, height as u32, pixels)
        .ok_or("Captured pixels did not match the window size.")?;
    // One screenshot pixel per point, whatever the display's scale.
    let (points_w, points_h) = (frame.w.round().max(1.0) as u32, frame.h.round().max(1.0) as u32);
    Ok(if captured.width() != points_w || captured.height() != points_h {
        imageops::resize(&captured, points_w, points_h, imageops::FilterType::Triangle)
    } else {
        captured
    })
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
    let captured = capture(target.window_id, target.pid, target.frame, &sheet_frames(&target.window))?;
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
        (registry.attached.get(session_id).cloned(), registry.stopped.contains(session_id))
    };
    let Some(attached) = attached else {
        return Ok(json!({ "attached": false, "stopped": stopped }));
    };
    let base = json!({
        "attached": true,
        "stopped": stopped,
        "app": attached.app,
        "title": attached.title,
    });
    let Some(top) = cg_window(attached.window_id) else {
        return Ok(merge(base, json!({ "closed": true })));
    };
    let app = Ax::application(attached.pid);
    let ax = app.as_ref().and_then(|app| ax_window(app, attached.window_id));
    let title = ax
        .as_ref()
        .and_then(|ax| ax.string("AXTitle"))
        .unwrap_or_else(|| attached.title.clone());
    if ax.as_ref().and_then(|ax| ax.flag("AXMinimized")).unwrap_or(false)
        || app.as_ref().and_then(|app| app.flag("AXHidden")).unwrap_or(false)
    {
        return Ok(merge(base, json!({ "minimized": true, "title": title })));
    }
    let dialog = app.as_ref().and_then(|app| app.element("AXFocusedWindow")).filter(|focus| {
        ax.as_ref().is_some_and(|ax| !focus.same(ax)) && is_dialog(focus)
    });
    let (window_id, frame) = match dialog.as_ref().and_then(Ax::window_id).and_then(cg_window) {
        Some(window) => (window.id, window.bounds),
        None => (top.id, top.bounds),
    };
    let shown = if window_id == top.id { ax.as_ref() } else { dialog.as_ref() };
    let sheets = shown.map(sheet_frames).unwrap_or_default();
    let captured = capture(window_id, attached.pid, frame, &sheets)?;
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
            "dialog": window_id != attached.window_id,
            "width": width,
            "height": height,
            "media_type": "image/jpeg",
            "data": encode_jpeg(&preview, 72)?,
        }),
    ))
}
