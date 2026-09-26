//! The two macOS permissions Computer App Control depends on:
//! Accessibility (to read and operate apps) and Screen Recording (to capture
//! their windows).

use super::*;

#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGPreflightScreenCaptureAccess() -> bool;
    pub(super) fn CGRequestScreenCaptureAccess() -> bool;
}

/// Whether EvoFlux may use the Accessibility API. With `prompt`, macOS shows
/// its "allow in System Settings" dialog the first time.
pub(super) fn accessibility_trusted(prompt: bool) -> bool {
    let key = unsafe { CFString::wrap_under_get_rule(kAXTrustedCheckOptionPrompt) };
    let value = if prompt { CFBoolean::true_value() } else { CFBoolean::false_value() };
    let options = CFDictionary::from_CFType_pairs(&[(key.as_CFType(), value.as_CFType())]);
    unsafe { AXIsProcessTrustedWithOptions(options.as_concrete_TypeRef()) != 0 }
}

pub(super) const ACCESSIBILITY_REFUSAL: &str = "macOS has not given EvoFlux Accessibility access, which Computer App Control needs to read and operate apps. Ask the user to allow EvoFlux in System Settings → Privacy & Security → Accessibility, then try again.";
pub(super) const SCREEN_RECORDING_REFUSAL: &str = "macOS has not given EvoFlux Screen Recording access, so app windows cannot be captured. Ask the user to allow EvoFlux in System Settings → Privacy & Security → Screen & System Audio Recording and restart EvoFlux. snapshot, find, invoke and set_value work without it.";

pub(super) fn screen_capture_allowed() -> bool {
    unsafe { CGPreflightScreenCaptureAccess() }
}

/// What Settings → Computer App Control shows: which of the two macOS
/// permissions EvoFlux has.
pub(super) fn permissions() -> Value {
    json!({
        "required": true,
        "accessibility": accessibility_trusted(false),
        "screen_recording": screen_capture_allowed(),
    })
}

/// Ask for one permission from Settings. The system call puts EvoFlux in
/// the pane's list (macOS only shows its own prompt the first time), and the
/// pane itself is opened so the user lands on the switch to turn on.
pub(super) fn request_permission(kind: &str) -> Result<Value, String> {
    let pane = match kind {
        "accessibility" => {
            accessibility_trusted(true);
            "Privacy_Accessibility"
        }
        "screen_recording" => {
            unsafe { CGRequestScreenCaptureAccess() };
            "Privacy_ScreenCapture"
        }
        other => return Err(format!("Unknown macOS permission {other:?}.")),
    };
    std::process::Command::new("open")
        .arg(format!("x-apple.systempreferences:com.apple.preference.security?{pane}"))
        .spawn()
        .map_err(|error| format!("Could not open System Settings: {error}"))?;
    Ok(permissions())
}
