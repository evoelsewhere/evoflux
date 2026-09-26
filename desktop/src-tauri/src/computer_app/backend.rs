//! The platform backend behind Computer App Control, and the factory that
//! picks it.
//!
//! Every Tauri command in `mod.rs` talks to a [`ComputerAppBackend`] handed
//! out by [`backend()`], never to a platform module directly. Each platform
//! is one product of the factory:
//!
//! | Platform | Product              | Capture                   | Input                                  |
//! |----------|----------------------|---------------------------|----------------------------------------|
//! | Windows  | `win::WindowsBackend` | `PrintWindow`             | `PostMessage` to the window, UI Automation |
//! | macOS    | `mac::MacBackend`     | `CGWindowListCreateImage` | `CGEventPostToPid`, Accessibility API  |
//! | other    | [`UnsupportedBackend`] | —                        | —                                      |
//!
//! A new platform only has to implement the trait and be returned here.

use serde_json::{json, Value};

use super::action::Action;

/// Why a session the user stopped may not attach, open or close apps.
#[cfg_attr(not(any(target_os = "windows", target_os = "macos")), allow(dead_code))]
pub(crate) const STOPPED_REFUSAL: &str = "The user stopped Computer App Control in this chat. Ask them before trying again: the preview card is showing again, and they can press Allow again there.";

/// What a platform has to provide to drive one app window per chat session.
///
/// Methods that act on an element ref (`run_action`) are called on the
/// session's worker thread, which [`init_worker_thread`] set up; the rest
/// may be called from any thread.
///
/// [`init_worker_thread`]: ComputerAppBackend::init_worker_thread
pub(crate) trait ComputerAppBackend: Sync {
    /// Prepare a freshly spawned worker thread (joins COM on Windows).
    fn init_worker_thread(&self) {}

    /// Whether `session_id` has a window attached (its worker is still needed).
    fn is_attached(&self, session_id: &str) -> bool;

    /// Run one agent action against the session's attached window. `emit`
    /// carries the virtual pointer to the preview card.
    fn run_action(
        &self,
        emit: &dyn Fn(Value),
        session_id: &str,
        action: Action,
        params: &Value,
    ) -> Result<Value, String>;

    /// Running and installed apps for the allow/block list in Settings.
    fn list_apps(&self) -> Value;

    /// One JPEG frame of the session's window for the preview card.
    fn preview_frame(&self, session_id: &str, max_width: u32) -> Result<Value, String>;

    /// The user revoked control: detach and refuse re-attaching until resumed.
    fn stop(&self, session_id: &str) -> Result<(), String>;

    /// The user allowed control again after stopping it.
    fn resume(&self, session_id: &str) -> Result<(), String>;

    /// Bring the attached app to the front for the user.
    fn reveal(&self, session_id: &str) -> Result<Value, String>;

    /// Hand every controlled window back. Called when EvoFlux exits.
    fn release_all(&self);

    /// Put back windows a previous run left parked, and record parked
    /// windows in `state_dir` from now on.
    fn recover_stranded(&self, state_dir: std::path::PathBuf) {
        let _ = state_dir;
    }

    /// The operating-system permissions this backend depends on.
    fn permissions(&self) -> Value {
        json!({ "required": false, "accessibility": true, "screen_recording": true })
    }

    /// Ask the operating system for one permission.
    fn request_permission(&self, kind: &str) -> Result<Value, String> {
        let _ = kind;
        Err("Only macOS asks for permissions to control apps.".into())
    }
}

/// The factory: the backend for the platform EvoFlux was built for.
pub(crate) fn backend() -> &'static dyn ComputerAppBackend {
    #[cfg(target_os = "windows")]
    {
        &super::win::WindowsBackend
    }
    #[cfg(target_os = "macos")]
    {
        &super::mac::MacBackend
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        &UnsupportedBackend
    }
}

/// Every platform without a backend: nothing can be attached, and the UI is
/// told so rather than shown an error for passive calls.
#[cfg_attr(any(target_os = "windows", target_os = "macos"), allow(dead_code))]
pub(crate) struct UnsupportedBackend;

#[cfg_attr(any(target_os = "windows", target_os = "macos"), allow(dead_code))]
fn unsupported<T>() -> Result<T, String> {
    Err("Computer App Control is only available in EvoFlux Desktop on Windows and macOS.".to_string())
}

impl ComputerAppBackend for UnsupportedBackend {
    fn is_attached(&self, _session_id: &str) -> bool {
        false
    }

    fn run_action(&self, _emit: &dyn Fn(Value), _session_id: &str, _action: Action, _params: &Value) -> Result<Value, String> {
        unsupported()
    }

    fn list_apps(&self) -> Value {
        json!({ "apps": [] })
    }

    fn preview_frame(&self, _session_id: &str, _max_width: u32) -> Result<Value, String> {
        Ok(json!({ "attached": false, "supported": false }))
    }

    fn stop(&self, _session_id: &str) -> Result<(), String> {
        unsupported()
    }

    fn resume(&self, _session_id: &str) -> Result<(), String> {
        unsupported()
    }

    fn reveal(&self, _session_id: &str) -> Result<Value, String> {
        unsupported()
    }

    fn release_all(&self) {}
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unsupported_backend_refuses_control_but_answers_passive_calls() {
        let backend = UnsupportedBackend;
        assert!(backend.run_action(&|_| {}, "s", Action::Status, &Value::Null).is_err());
        assert!(backend.stop("s").is_err() && backend.reveal("s").is_err());
        assert_eq!(backend.list_apps(), json!({ "apps": [] }));
        assert_eq!(backend.preview_frame("s", 960).unwrap()["supported"], false);
        assert_eq!(backend.permissions()["required"], false);
    }
}
