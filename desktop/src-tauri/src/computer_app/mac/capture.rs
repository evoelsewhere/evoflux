//! Capturing the attached window from the window server — behind other
//! windows or parked — for the agent's screenshots and the preview card.

use super::*;

use std::sync::mpsc;

use block2::RcBlock;
use objc2::rc::Retained;
use objc2::runtime::AnyClass;
use objc2::AllocAnyThread;
use objc2_core_graphics::{CGDataProvider, CGImage as SckImage};
use objc2_foundation::NSError;
use objc2_screen_capture_kit::{
    SCContentFilter, SCScreenshotManager, SCShareableContent, SCStreamConfiguration, SCWindow,
};

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

/// One screenshot pixel per point, whatever the display's scale.
fn point_size(frame: &Rect) -> (u32, u32) {
    (frame.w.round().max(1.0) as u32, frame.h.round().max(1.0) as u32)
}

/// Window images are BGRA in memory, each row padded to `bytes_per_row`.
/// `opaque` drops the alpha: the window itself fills its frame, while its
/// menus keep their rounded corners to be painted over it.
fn rgba_from_bgra(
    width: usize,
    height: usize,
    bytes_per_row: usize,
    bytes: &[u8],
    opaque: bool,
) -> Result<RgbaImage, String> {
    if width == 0 || height == 0 || bytes_per_row < width * 4 || bytes.len() < bytes_per_row * (height - 1) + width * 4 {
        return Err("macOS returned an empty or unexpected image of the window.".into());
    }
    let mut pixels = Vec::with_capacity(width * height * 4);
    for row in bytes.chunks(bytes_per_row).take(height) {
        pixels.extend_from_slice(&row[..width * 4]);
    }
    for pixel in pixels.chunks_exact_mut(4) {
        pixel.swap(0, 2);
        if opaque {
            pixel[3] = 255;
        }
    }
    RgbaImage::from_raw(width as u32, height as u32, pixels)
        .ok_or_else(|| "Captured pixels did not match the window size.".into())
}

// ── ScreenCaptureKit ────────────────────────────────────────────────────
//
// Chromium stops repainting the image the window server keeps of a window
// once all but a point of it is off the display — parked Chrome and
// Electron windows captured through CoreGraphics come out blank. A
// ScreenCaptureKit filter for the window alone has the compositor render it
// wherever it is, without moving or activating it.

/// Handed from ScreenCaptureKit's callback queue to the waiting worker, and
/// kept in the plan cache: filters, configurations and windows are not
/// changed once built.
struct Sendable<T>(T);
unsafe impl<T> Send for Sendable<T> {}

/// A filter and configuration for one window at one size. Listing the
/// shareable windows takes tens of milliseconds and the preview card polls
/// about six times a second, so a plan is reused for a short while as long
/// as the window keeps its size.
struct SckPlan {
    filter: Retained<SCContentFilter>,
    config: Retained<SCStreamConfiguration>,
    size: (u32, u32),
    created_at: Instant,
}

static SCK_PLANS: Lazy<Mutex<HashMap<u32, Sendable<SckPlan>>>> = Lazy::new(Default::default);
const SCK_PLAN_TTL: Duration = Duration::from_secs(2);
const SCK_TIMEOUT: Duration = Duration::from_secs(2);

/// The screenshot API arrived in macOS 14; the framework is weakly linked.
fn sck_available() -> bool {
    AnyClass::get(c"SCScreenshotManager").is_some()
}

fn ns_error_text(error: *mut NSError) -> String {
    unsafe { error.as_ref() }
        .map(|error| error.localizedDescription().to_string())
        .unwrap_or_else(|| "no reason given".into())
}

fn sck_window(window_id: u32) -> Result<Retained<SCWindow>, String> {
    let (sender, receiver) = mpsc::channel();
    let handler = RcBlock::new(move |content: *mut SCShareableContent, error: *mut NSError| {
        let found = match unsafe { content.as_ref() } {
            Some(content) => {
                let windows = unsafe { content.windows() };
                (0..windows.count())
                    .map(|index| windows.objectAtIndex(index))
                    .find(|window| unsafe { window.windowID() } == window_id)
                    .map(Sendable)
                    .ok_or_else(|| format!("ScreenCaptureKit does not list window {window_id}."))
            }
            None => Err(format!("ScreenCaptureKit could not list windows: {}", ns_error_text(error))),
        };
        let _ = sender.send(found);
    });
    unsafe {
        SCShareableContent::getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler(
            true, false, &handler,
        )
    };
    receiver
        .recv_timeout(SCK_TIMEOUT)
        .map_err(|_| "ScreenCaptureKit did not list windows in time.".to_string())?
        .map(|window| window.0)
}

fn sck_plan(
    window_id: u32,
    size: (u32, u32),
) -> Result<(Retained<SCContentFilter>, Retained<SCStreamConfiguration>), String> {
    {
        let mut plans = SCK_PLANS.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        plans.retain(|_, plan| plan.0.created_at.elapsed() < SCK_PLAN_TTL);
        if let Some(Sendable(plan)) = plans.get(&window_id).filter(|plan| plan.0.size == size) {
            return Ok((plan.filter.clone(), plan.config.clone()));
        }
    }
    let window = sck_window(window_id)?;
    let filter = unsafe { SCContentFilter::initWithDesktopIndependentWindow(SCContentFilter::alloc(), &window) };
    let config = unsafe { SCStreamConfiguration::new() };
    unsafe {
        config.setWidth(size.0 as usize);
        config.setHeight(size.1 as usize);
        config.setShowsCursor(false);
        config.setIgnoreShadowsSingleWindow(true);
        // Parked, all but a point of the window is off the display.
        config.setIgnoreGlobalClipSingleWindow(true);
    }
    let plan = SckPlan { filter: filter.clone(), config: config.clone(), size, created_at: Instant::now() };
    SCK_PLANS
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .insert(window_id, Sendable(plan));
    Ok((filter, config))
}

fn sck_image(window_id: u32, size: (u32, u32), opaque: bool) -> Result<RgbaImage, String> {
    let (filter, config) = sck_plan(window_id, size)?;
    let (sender, receiver) = mpsc::channel();
    let handler = RcBlock::new(move |image: *mut SckImage, error: *mut NSError| {
        // The image only lives until the handler returns.
        let result = match unsafe { image.as_ref() } {
            Some(image) => {
                let image = Some(image);
                SckImage::data_provider(image)
                    .and_then(|provider| CGDataProvider::data(Some(&provider)))
                    .ok_or_else(|| "ScreenCaptureKit returned an image without pixels.".to_string())
                    .and_then(|data| {
                        if SckImage::bits_per_pixel(image) != 32 {
                            return Err("ScreenCaptureKit returned an unexpected image of the window.".into());
                        }
                        rgba_from_bgra(
                            SckImage::width(image),
                            SckImage::height(image),
                            SckImage::bytes_per_row(image),
                            unsafe { data.as_bytes_unchecked() },
                            opaque,
                        )
                    })
            }
            None => Err(format!("ScreenCaptureKit could not capture window {window_id}: {}", ns_error_text(error))),
        };
        let _ = sender.send(result);
    });
    unsafe {
        SCScreenshotManager::captureImageWithFilter_configuration_completionHandler(&filter, &config, Some(&handler))
    };
    let result = receiver
        .recv_timeout(SCK_TIMEOUT)
        .map_err(|_| format!("ScreenCaptureKit did not capture window {window_id} in time."))
        .and_then(|result| result);
    if result.is_err() {
        // The window may have gone or changed; look it up afresh next time.
        SCK_PLANS.lock().unwrap_or_else(|poisoned| poisoned.into_inner()).remove(&window_id);
    }
    result
}

/// The window, then its menus, popovers and sheets painted over it, backmost
/// first — each a window of its own to ScreenCaptureKit.
fn capture_sck(window_id: u32, frame: Rect, overlays: &[CgWindow]) -> Result<RgbaImage, String> {
    let mut image = sck_image(window_id, point_size(&frame), true)?;
    for overlay in overlays.iter().rev() {
        match sck_image(overlay.id, point_size(&overlay.bounds), false) {
            Ok(layer) => imageops::overlay(
                &mut image,
                &layer,
                (overlay.bounds.x - frame.x).round() as i64,
                (overlay.bounds.y - frame.y).round() as i64,
            ),
            Err(error) => log::debug!("computer app: left window {} out of the capture: {error}", overlay.id),
        }
    }
    Ok(image)
}

// ── Capture ─────────────────────────────────────────────────────────────

/// Render the window (with the app's own sheets, alerts and menus stacked
/// over it) from the window server's copy of it: works behind other windows
/// and while parked. `web` windows (Chromium) go through ScreenCaptureKit
/// first, where the copy the window server keeps of them goes blank.
fn capture(window_id: u32, pid: i32, frame: Rect, sheets: &[Rect], web: bool) -> Result<RgbaImage, String> {
    if !screen_capture_allowed() {
        // Shows macOS's own prompt the first time; later it only answers.
        unsafe { CGRequestScreenCaptureAccess() };
        return Err(SCREEN_RECORDING_REFUSAL.into());
    }
    // Over the window: its menus, popovers and panels (above the normal
    // level) and its sheets — not another document window of the app that
    // happens to overlap it, which the capture used to paint over it.
    // Frontmost first.
    let overlays: Vec<CgWindow> = cg_windows(kCGWindowListOptionOnScreenAboveWindow, window_id)
        .into_iter()
        .filter(|window| window.pid == pid && window.bounds.intersects(&frame))
        .filter(|window| window.layer != 0 || sheets.iter().any(|sheet| same_frame(sheet, &window.bounds)))
        .collect();
    if web && sck_available() {
        match capture_sck(window_id, frame, &overlays) {
            Ok(image) => return Ok(image),
            Err(error) => log::warn!("computer app: ScreenCaptureKit capture failed, using CoreGraphics: {error}"),
        }
    }
    let options =
        kCGWindowImageBoundsIgnoreFraming | kCGWindowImageNominalResolution | kCGWindowImageShouldBeOpaque;
    let mut ids: Vec<u32> = overlays.iter().map(|window| window.id).collect();
    ids.push(window_id);
    let image = create_image_from_array(frame.to_cg(), window_id_array(&ids), options)
        .or_else(|| create_image(frame.to_cg(), kCGWindowListOptionIncludingWindow, window_id, options))
        .ok_or("macOS returned no image of the window.")?;
    if image.bits_per_pixel() != 32 {
        return Err("macOS returned an empty or unexpected image of the window.".into());
    }
    let data = image.data();
    let captured = rgba_from_bgra(image.width(), image.height(), image.bytes_per_row(), data.bytes(), true)?;
    let (points_w, points_h) = point_size(&frame);
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
    let captured = capture(
        target.window_id,
        target.pid,
        target.frame,
        &sheet_frames(&target.window),
        target.web,
    )?;
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
    let captured = capture(window_id, attached.pid, frame, &sheets, attached.web)?;
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
