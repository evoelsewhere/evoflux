//! AWS credentials from the environment and the shared config files, for
//! Bedrock (EvoFlux leans on boto3's default chain for the same thing).
//!
//! A Bedrock credential of the form `aws-profile:<name>` (empty name: the
//! default chain) is resolved here at request time, in this order:
//!
//! 1. `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN`
//!    (default chain only);
//! 2. `~/.aws/credentials` (`AWS_SHARED_CREDENTIALS_FILE`): static keys;
//! 3. `~/.aws/config` (`AWS_CONFIG_FILE`): static keys, `credential_process`,
//!    or IAM Identity Center (SSO) — the token `aws sso login` cached under
//!    `~/.aws/sso/cache`, exchanged for role credentials.
//!
//! Temporary credentials are cached until five minutes before they expire.
//! Assume-role profiles (`role_arn`) and instance roles are not resolved.

use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};

use serde_json::Value;

use super::bedrock::IamCredential;

/// Prefix of a Bedrock credential that names an AWS profile.
pub const PROFILE_CREDENTIAL_PREFIX: &str = "aws-profile:";

type Section = BTreeMap<String, String>;

fn home() -> Option<PathBuf> {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
}

fn aws_file(env: &str, name: &str) -> Option<PathBuf> {
    std::env::var_os(env)
        .map(PathBuf::from)
        .or_else(|| home().map(|home| home.join(".aws").join(name)))
}

/// `[section]` → `key = value` pairs of an AWS INI file.
fn parse_ini(text: &str) -> HashMap<String, Section> {
    let mut sections: HashMap<String, Section> = HashMap::new();
    let mut current: Option<String> = None;
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') || line.starts_with(';') {
            continue;
        }
        if let Some(name) = line.strip_prefix('[').and_then(|l| l.strip_suffix(']')) {
            let name = name.trim().to_string();
            sections.entry(name.clone()).or_default();
            current = Some(name);
        } else if let (Some(section), Some((key, value))) = (current.as_ref(), line.split_once('='))
        {
            sections
                .entry(section.clone())
                .or_default()
                .insert(key.trim().to_ascii_lowercase(), value.trim().to_string());
        }
    }
    sections
}

fn read_ini(path: Option<PathBuf>) -> HashMap<String, Section> {
    path.and_then(|path| std::fs::read_to_string(path).ok())
        .map(|text| parse_ini(&text))
        .unwrap_or_default()
}

fn static_keys(section: &Section) -> Option<IamCredential> {
    Some(IamCredential {
        access_key_id: section.get("aws_access_key_id")?.clone(),
        secret_access_key: section.get("aws_secret_access_key")?.clone(),
        session_token: section.get("aws_session_token").cloned(),
    })
}

/// Unix seconds of an RFC 3339 / ISO 8601 UTC time (`2026-11-05T10:00:00Z`).
fn parse_time(value: &str) -> Option<i64> {
    let value = value.trim();
    let (date, time) = value.split_once('T')?;
    let mut date = date.split('-').map(|p| p.parse::<i64>().ok());
    let (y, m, d) = (date.next()??, date.next()??, date.next()??);
    let time = time.trim_end_matches('Z');
    let time = time.split(['+', '.']).next()?;
    let mut hms = time.split(':').map(|p| p.parse::<i64>().ok());
    let (h, mi, s) = (
        hms.next()??,
        hms.next()??,
        hms.next().flatten().unwrap_or(0),
    );
    // Days from civil (Howard Hinnant).
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + doe - 719_468;
    Some(days * 86_400 + h * 3600 + mi * 60 + s)
}

fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Run a profile's `credential_process` and read its JSON (version 1).
async fn credential_process(command: &str) -> Result<(IamCredential, Option<i64>), String> {
    let command = command.to_string();
    let output = tokio::task::spawn_blocking(move || {
        #[cfg(windows)]
        let mut process = {
            let mut process = std::process::Command::new("cmd");
            process.args(["/C", &command]);
            process
        };
        #[cfg(not(windows))]
        let mut process = {
            let mut process = std::process::Command::new("sh");
            process.args(["-c", &command]);
            process
        };
        process.output()
    })
    .await
    .map_err(|error| error.to_string())?
    .map_err(|error| format!("credential_process could not start: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "credential_process failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    let json: Value = serde_json::from_slice(&output.stdout)
        .map_err(|_| "credential_process printed no credentials JSON".to_string())?;
    let get = |name: &str| json.get(name).and_then(Value::as_str).map(str::to_string);
    let credential = IamCredential {
        access_key_id: get("AccessKeyId").ok_or("credential_process: no AccessKeyId")?,
        secret_access_key: get("SecretAccessKey")
            .ok_or("credential_process: no SecretAccessKey")?,
        session_token: get("SessionToken"),
    };
    Ok((credential, get("Expiration").and_then(|e| parse_time(&e))))
}

/// The access token `aws sso login` cached for `start_url`.
fn sso_token(start_url: &str) -> Result<String, String> {
    let dir = home()
        .map(|home| home.join(".aws").join("sso").join("cache"))
        .ok_or("no home directory")?;
    let entries = std::fs::read_dir(&dir).map_err(|_| sso_login_hint())?;
    let mut best: Option<(i64, String)> = None;
    for entry in entries.flatten() {
        let Ok(text) = std::fs::read_to_string(entry.path()) else {
            continue;
        };
        let Ok(json) = serde_json::from_str::<Value>(&text) else {
            continue;
        };
        if json
            .get("startUrl")
            .and_then(Value::as_str)
            .map(|u| u.trim_end_matches('/'))
            != Some(start_url.trim_end_matches('/'))
        {
            continue;
        }
        let (Some(token), Some(expires)) = (
            json.get("accessToken").and_then(Value::as_str),
            json.get("expiresAt")
                .and_then(Value::as_str)
                .and_then(parse_time),
        ) else {
            continue;
        };
        if best.as_ref().is_none_or(|(at, _)| expires > *at) {
            best = Some((expires, token.to_string()));
        }
    }
    match best {
        Some((expires, token)) if expires > now() + 60 => Ok(token),
        Some(_) => Err(format!("The AWS SSO session expired. {}", sso_login_hint())),
        None => Err(sso_login_hint()),
    }
}

fn sso_login_hint() -> String {
    "Sign in with `aws sso login --profile <profile>` and try again.".into()
}

/// IAM Identity Center: exchange the cached SSO token for role credentials.
async fn sso_credentials(
    http: &reqwest::Client,
    profile: &Section,
    sessions: &HashMap<String, Section>,
) -> Result<(IamCredential, Option<i64>), String> {
    let session = profile
        .get("sso_session")
        .and_then(|name| sessions.get(&format!("sso-session {name}")));
    let field = |name: &str| {
        profile
            .get(name)
            .or_else(|| session.and_then(|s| s.get(name)))
            .cloned()
    };
    let start_url = field("sso_start_url").ok_or("SSO profile has no sso_start_url")?;
    let region = field("sso_region").ok_or("SSO profile has no sso_region")?;
    let account = field("sso_account_id").ok_or("SSO profile has no sso_account_id")?;
    let role = field("sso_role_name").ok_or("SSO profile has no sso_role_name")?;
    let token = sso_token(&start_url)?;
    let url = reqwest::Url::parse_with_params(
        &format!("https://portal.sso.{region}.amazonaws.com/federation/credentials"),
        &[
            ("role_name", role.as_str()),
            ("account_id", account.as_str()),
        ],
    )
    .map_err(|_| format!("Invalid SSO region: {region}"))?;
    let response = http
        .get(url)
        .header("x-amz-sso_bearer_token", token)
        .send()
        .await
        .map_err(|error| format!("Could not reach AWS SSO: {error}"))?;
    if !response.status().is_success() {
        return Err(format!(
            "AWS SSO refused the role ({}). {}",
            response.status(),
            sso_login_hint()
        ));
    }
    let json: Value = response.json().await.map_err(|error| error.to_string())?;
    let role = json
        .get("roleCredentials")
        .ok_or("AWS SSO returned no role credentials")?;
    let get = |name: &str| role.get(name).and_then(Value::as_str).map(str::to_string);
    let credential = IamCredential {
        access_key_id: get("accessKeyId").ok_or("AWS SSO: no accessKeyId")?,
        secret_access_key: get("secretAccessKey").ok_or("AWS SSO: no secretAccessKey")?,
        session_token: get("sessionToken"),
    };
    let expires = role
        .get("expiration")
        .and_then(Value::as_i64)
        .map(|ms| ms / 1000);
    Ok((credential, expires))
}

type Cache = Mutex<HashMap<String, (IamCredential, Option<i64>)>>;

fn cache() -> &'static Cache {
    static CACHE: OnceLock<Cache> = OnceLock::new();
    CACHE.get_or_init(Default::default)
}

/// Resolve `profile` (empty: the default chain) to IAM credentials.
pub async fn resolve(http: &reqwest::Client, profile: &str) -> Result<IamCredential, String> {
    if profile.is_empty() {
        let env = |name: &str| std::env::var(name).ok().filter(|v| !v.trim().is_empty());
        if let (Some(access_key_id), Some(secret_access_key)) =
            (env("AWS_ACCESS_KEY_ID"), env("AWS_SECRET_ACCESS_KEY"))
        {
            return Ok(IamCredential {
                access_key_id,
                secret_access_key,
                session_token: env("AWS_SESSION_TOKEN"),
            });
        }
    }
    let name = if profile.is_empty() {
        std::env::var("AWS_PROFILE")
            .ok()
            .filter(|p| !p.is_empty())
            .unwrap_or_else(|| "default".into())
    } else {
        profile.to_string()
    };
    if let Some((credential, expires)) = cache().lock().ok().and_then(|c| c.get(&name).cloned()) {
        if expires.is_none_or(|at| at > now() + 300) {
            return Ok(credential);
        }
    }
    let resolved = resolve_uncached(http, &name).await?;
    if let Ok(mut cache) = cache().lock() {
        cache.insert(name, resolved.clone());
    }
    Ok(resolved.0)
}

async fn resolve_uncached(
    http: &reqwest::Client,
    name: &str,
) -> Result<(IamCredential, Option<i64>), String> {
    let credentials = read_ini(aws_file("AWS_SHARED_CREDENTIALS_FILE", "credentials"));
    if let Some(keys) = credentials.get(name).and_then(static_keys) {
        return Ok((keys, None));
    }
    let config = read_ini(aws_file("AWS_CONFIG_FILE", "config"));
    let section_name = if name == "default" {
        "default".to_string()
    } else {
        format!("profile {name}")
    };
    let Some(section) = config.get(&section_name).or_else(|| config.get(name)) else {
        return Err(format!(
            "AWS profile \"{name}\" was not found in ~/.aws/credentials or ~/.aws/config"
        ));
    };
    if let Some(keys) = static_keys(section) {
        return Ok((keys, None));
    }
    if let Some(command) = section.get("credential_process") {
        return credential_process(command).await;
    }
    if section.contains_key("sso_session") || section.contains_key("sso_start_url") {
        return sso_credentials(http, section, &config).await;
    }
    if section.contains_key("role_arn") {
        return Err(format!(
            "AWS profile \"{name}\" assumes a role (role_arn), which evo cannot resolve yet; use an SSO, credential_process or key profile"
        ));
    }
    Err(format!(
        "AWS profile \"{name}\" has no credentials evo can use"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ini_sections_and_keys() {
        let ini = parse_ini(
            "[default]\naws_access_key_id = AK\naws_secret_access_key=SK\n\n[profile dev]\nsso_session = corp\n# comment\n[sso-session corp]\nsso_region = us-east-1\n",
        );
        assert_eq!(static_keys(&ini["default"]).unwrap().access_key_id, "AK");
        assert_eq!(ini["profile dev"]["sso_session"], "corp");
        assert_eq!(ini["sso-session corp"]["sso_region"], "us-east-1");
    }

    #[tokio::test]
    async fn resolves_a_named_profile_from_the_shared_files() {
        let dir = std::env::temp_dir().join(format!("evo-aws-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let credentials = dir.join("credentials");
        let config = dir.join("config");
        std::fs::write(
            &credentials,
            "[work]
aws_access_key_id = AKWORK
aws_secret_access_key = SKWORK
",
        )
        .unwrap();
        std::fs::write(
            &config,
            "[profile roles]
role_arn = arn:aws:iam::1:role/x
source_profile = work
",
        )
        .unwrap();
        // Only this test reads these variables.
        std::env::set_var("AWS_SHARED_CREDENTIALS_FILE", &credentials);
        std::env::set_var("AWS_CONFIG_FILE", &config);
        let http = reqwest::Client::new();
        let work = resolve(&http, "work").await.unwrap();
        assert_eq!(
            (work.access_key_id.as_str(), work.secret_access_key.as_str()),
            ("AKWORK", "SKWORK")
        );
        let roles = resolve(&http, "roles").await.err().unwrap();
        assert!(roles.contains("role_arn"), "{roles}");
        assert!(resolve(&http, "missing")
            .await
            .err()
            .unwrap()
            .contains("not found"));
        std::env::remove_var("AWS_SHARED_CREDENTIALS_FILE");
        std::env::remove_var("AWS_CONFIG_FILE");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn parses_aws_times() {
        assert_eq!(parse_time("1970-01-01T00:00:00Z"), Some(0));
        assert_eq!(parse_time("2026-10-26T07:33:20Z"), Some(1_793_000_000));
        assert_eq!(
            parse_time("2026-10-26T07:33:20.123+00:00"),
            Some(1_793_000_000)
        );
    }
}
