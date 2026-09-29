//! Keep computer awake: stop the system idling into sleep while EvoFlux runs,
//! so scheduled tasks, long agent turns and Remote Control keep going with
//! nobody at the keyboard. The display may still turn off.
//!
//! - Windows: a `PowerRequestSystemRequired` power request, listed by
//!   `powercfg /requests` with the reason below. Sleep the user asks for
//!   still happens.
//! - macOS: `caffeinate -i`, which also exits on its own when EvoFlux does.
//!   Sleep the user asks for still happens.
//! - Linux: a logind idle/sleep inhibitor lock held through
//!   `systemd-inhibit`; desktops name EvoFlux when the user suspends.

use anyhow::Result;
use std::sync::Mutex;

static HELD: Mutex<Option<platform::Assertion>> = Mutex::new(None);

#[cfg(any(target_os = "windows", target_os = "linux"))]
const REASON: &str = "Keep computer awake is on in EvoFlux Settings";

/// Hold or release the sleep assertion. Calling it again with the same
/// value is a no-op.
pub fn set(enabled: bool) -> Result<()> {
    let mut held = HELD.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    if enabled == held.is_some() {
        return Ok(());
    }
    // Dropping the previous assertion releases it.
    *held = if enabled {
        Some(platform::Assertion::acquire()?)
    } else {
        None
    };
    Ok(())
}

pub fn release() {
    let _ = set(false);
}

#[cfg(target_os = "windows")]
mod platform {
    use super::REASON;
    use anyhow::{Context, Result};
    use windows::core::PWSTR;
    use windows::Win32::Foundation::{CloseHandle, HANDLE};
    use windows::Win32::System::Power::{
        PowerClearRequest, PowerCreateRequest, PowerRequestSystemRequired, PowerSetRequest,
    };
    use windows::Win32::System::Threading::{
        POWER_REQUEST_CONTEXT_SIMPLE_STRING, REASON_CONTEXT, REASON_CONTEXT_0,
    };

    /// `POWER_REQUEST_CONTEXT_VERSION`; its binding sits behind a feature
    /// this crate has no other use for.
    const CONTEXT_VERSION: u32 = 0;

    pub struct Assertion(HANDLE);

    // A power request handle is not tied to the thread that created it.
    unsafe impl Send for Assertion {}

    impl Assertion {
        pub fn acquire() -> Result<Self> {
            // PowerCreateRequest copies the string, so it only has to live
            // for the call.
            let mut reason: Vec<u16> = REASON.encode_utf16().chain(Some(0)).collect();
            let context = REASON_CONTEXT {
                Version: CONTEXT_VERSION,
                Flags: POWER_REQUEST_CONTEXT_SIMPLE_STRING,
                Reason: REASON_CONTEXT_0 {
                    SimpleReasonString: PWSTR(reason.as_mut_ptr()),
                },
            };
            let handle = unsafe { PowerCreateRequest(&context) }.context("create power request")?;
            if let Err(error) = unsafe { PowerSetRequest(handle, PowerRequestSystemRequired) } {
                unsafe {
                    let _ = CloseHandle(handle);
                }
                return Err(error).context("set system-required power request");
            }
            Ok(Self(handle))
        }
    }

    impl Drop for Assertion {
        fn drop(&mut self) {
            unsafe {
                let _ = PowerClearRequest(self.0, PowerRequestSystemRequired);
                let _ = CloseHandle(self.0);
            }
        }
    }
}

#[cfg(any(target_os = "macos", target_os = "linux"))]
mod platform {
    use anyhow::{anyhow, Context, Result};
    use std::os::unix::process::CommandExt;
    use std::process::{Child, Command, Stdio};
    use std::time::Duration;

    /// A helper process that holds the assertion for as long as it runs.
    /// Both helpers also watch EvoFlux's pid, so a crash cannot leave the
    /// machine unable to sleep.
    pub struct Assertion(Child);

    fn helper_command(pid: u32) -> Command {
        #[cfg(target_os = "macos")]
        {
            let mut command = Command::new("/usr/bin/caffeinate");
            command.args(["-i", "-w", &pid.to_string()]);
            command
        }
        #[cfg(target_os = "linux")]
        {
            let mut command = Command::new("systemd-inhibit");
            command
                .arg("--what=idle:sleep")
                .arg("--who=EvoFlux")
                .arg(format!("--why={}", super::REASON))
                .arg("--mode=block")
                .args(["tail", &format!("--pid={pid}"), "-f", "/dev/null"]);
            command
        }
    }

    impl Assertion {
        pub fn acquire() -> Result<Self> {
            let mut command = helper_command(std::process::id());
            // Its own process group, so releasing also stops the `tail`
            // that systemd-inhibit runs.
            command
                .process_group(0)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            let mut child = command
                .spawn()
                .context("start the keep-awake helper")?;
            // systemd-inhibit exits straight away when logind refuses the lock.
            std::thread::sleep(Duration::from_millis(200));
            if let Some(status) = child.try_wait().context("check the keep-awake helper")? {
                return Err(anyhow!("the keep-awake helper exited ({status})"));
            }
            Ok(Self(child))
        }
    }

    impl Drop for Assertion {
        fn drop(&mut self) {
            use nix::sys::signal::{killpg, Signal};
            use nix::unistd::Pid;

            if let Ok(pid) = i32::try_from(self.0.id()) {
                let _ = killpg(Pid::from_raw(pid), Signal::SIGTERM);
            }
            let _ = self.0.wait();
        }
    }
}

#[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
mod platform {
    use anyhow::{anyhow, Result};

    pub struct Assertion;

    impl Assertion {
        pub fn acquire() -> Result<Self> {
            Err(anyhow!("Keep computer awake is not available on this platform"))
        }
    }
}
