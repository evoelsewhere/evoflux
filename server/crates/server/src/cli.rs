//! Port of the `serve` arguments of `app/cli/commands/serve.py`, plus the
//! gateway's `--python-root` for development layouts.

use std::ffi::OsString;
use std::path::PathBuf;

pub const USAGE: &str = "usage: evoflux-server serve [--host HOST] [--port PORT] [--handshake] \
[--generate-token] [--parent-pid PID] [--python-root DIR]";

/// Flags of `evoflux-server serve`; same meaning and defaults as Python's `serve`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ServeArgs {
    /// Bind host (default `127.0.0.1`: desktop must stay local).
    pub host: String,
    /// Bind port; `0` picks an OS-assigned ephemeral port.
    pub port: u16,
    /// Emit the `EVOFLUX_HANDSHAKE` line on stdout once ready.
    pub handshake: bool,
    /// Generate a random desktop token and require it for API access.
    pub generate_token: bool,
    /// Exit when this process is no longer alive.
    pub parent_pid: Option<u32>,
    /// The sidecar root (`python/` and `site-packages/`); `EVOFLUX_SIDECAR_ROOT` otherwise.
    pub python_root: Option<PathBuf>,
}

impl Default for ServeArgs {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".to_owned(),
            port: 0,
            handshake: false,
            generate_token: false,
            parent_pid: None,
            python_root: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Command {
    Serve(ServeArgs),
    Help,
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
#[error("{0}\n{USAGE}")]
pub struct UsageError(pub String);

/// Parse the arguments after the program name. Like argparse, a value may be
/// given as `--flag value` or `--flag=value`.
pub fn parse(args: impl IntoIterator<Item = OsString>) -> Result<Command, UsageError> {
    let mut args = args.into_iter();
    match args.next().as_deref().and_then(|a| a.to_str()) {
        Some("serve") => {}
        Some("-h" | "--help") => return Ok(Command::Help),
        Some(other) => return Err(UsageError(format!("unknown command {other:?}"))),
        None => return Err(UsageError("missing command".to_owned())),
    }
    let mut parsed = ServeArgs::default();
    while let Some(raw) = args.next() {
        let Some(arg) = raw.to_str() else {
            return Err(UsageError(format!("unrecognized argument {raw:?}")));
        };
        let (flag, inline) = match arg.split_once('=') {
            Some((flag, value)) if flag.starts_with("--") => (flag, Some(value.to_owned())),
            _ => (arg, None),
        };
        let mut value = |name: &str| -> Result<OsString, UsageError> {
            match inline.clone() {
                Some(value) => Ok(OsString::from(value)),
                None => args
                    .next()
                    .ok_or_else(|| UsageError(format!("argument {name}: expected one argument"))),
            }
        };
        match flag {
            "-h" | "--help" => return Ok(Command::Help),
            "--host" => parsed.host = text(flag, value(flag)?)?,
            "--port" => parsed.port = number(flag, value(flag)?)?,
            "--parent-pid" => parsed.parent_pid = Some(number(flag, value(flag)?)?),
            "--python-root" => parsed.python_root = Some(PathBuf::from(value(flag)?)),
            "--handshake" | "--generate-token" if inline.is_some() => {
                return Err(UsageError(format!(
                    "argument {flag}: ignored explicit argument"
                )));
            }
            "--handshake" => parsed.handshake = true,
            "--generate-token" => parsed.generate_token = true,
            _ => return Err(UsageError(format!("unrecognized arguments: {arg}"))),
        }
    }
    Ok(Command::Serve(parsed))
}

fn text(flag: &str, value: OsString) -> Result<String, UsageError> {
    value
        .into_string()
        .map_err(|v| UsageError(format!("argument {flag}: invalid value {v:?}")))
}

fn number<T: std::str::FromStr>(flag: &str, value: OsString) -> Result<T, UsageError> {
    let value = text(flag, value)?;
    value
        .trim()
        .parse()
        .map_err(|_| UsageError(format!("argument {flag}: invalid int value: {value:?}")))
}
