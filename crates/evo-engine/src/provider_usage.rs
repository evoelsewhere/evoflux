//! Plan usage and quota for subscription providers (EvoFlux
//! `codex/usage.py`, `copilot/usage.py`, `opencode/usage.py`).
//!
//! Each answers "how much of my plan is left": rate-limit windows with the
//! share used and when they reset, and counted quotas (Copilot's premium
//! requests). Read-only, on demand from the settings page; nothing here is
//! needed to send a request.

use serde::Serialize;
use serde_json::Value;

/// One limit of a plan.
#[derive(Debug, Clone, Default, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct UsageLimit {
    pub id: String,
    pub name: String,
    /// 0–100.
    pub used_percent: Option<f64>,
    pub window_minutes: Option<i64>,
    /// Unix seconds.
    pub resets_at: Option<i64>,
    /// Counted quotas (requests, credits).
    pub used: Option<f64>,
    pub total: Option<f64>,
    pub unlimited: bool,
    /// The provider says this limit is reached.
    pub reached: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ProviderUsage {
    pub provider: String,
    pub plan: Option<String>,
    pub limits: Vec<UsageLimit>,
}

/// Providers with a usage endpoint.
pub fn supported(provider: &str) -> bool {
    matches!(provider, "codex" | "copilot" | "opencode-go")
}

fn client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .expect("http client")
}

async fn get_json(request: reqwest::RequestBuilder, label: &str) -> Result<Value, String> {
    let response = request
        .header("accept", "application/json")
        .header("user-agent", evo_ai::http::user_agent())
        .send()
        .await
        .map_err(|_| format!("Could not reach {label}"))?;
    let status = response.status();
    if status == reqwest::StatusCode::UNAUTHORIZED || status == reqwest::StatusCode::FORBIDDEN {
        return Err(format!(
            "{label} rejected the credential ({status}); sign in again"
        ));
    }
    if !status.is_success() {
        return Err(format!("{label} answered {status}"));
    }
    response
        .json()
        .await
        .map_err(|_| format!("{label} returned usage evo could not read"))
}

fn number(value: Option<&Value>) -> Option<f64> {
    match value? {
        Value::Number(n) => n.as_f64(),
        Value::String(s) => s.trim().parse().ok(),
        _ => None,
    }
}

fn first<'a>(values: &'a Value, names: &[&str]) -> Option<&'a Value> {
    names
        .iter()
        .find_map(|name| values.get(*name).filter(|v| !v.is_null()))
}

/// RFC 3339 (or Unix seconds) → Unix seconds; `0` and blanks mean "not given".
fn timestamp(value: Option<&Value>) -> Option<i64> {
    parse_timestamp(value).filter(|at| *at > 0)
}

fn parse_timestamp(value: Option<&Value>) -> Option<i64> {
    match value? {
        Value::Number(n) => n.as_i64(),
        Value::String(s) => {
            let (date, time) = s.trim().split_once('T')?;
            let mut d = date.split('-').map(|p| p.parse::<i64>().ok());
            let (y, m, day) = (d.next()??, d.next()??, d.next()??);
            let time = time.trim_end_matches('Z');
            let time = time.split(['+', '.']).next()?;
            let mut t = time.split(':').map(|p| p.parse::<i64>().ok());
            let (h, mi, sec) = (t.next()??, t.next()??, t.next().flatten().unwrap_or(0));
            let y = if m <= 2 { y - 1 } else { y };
            let era = y.div_euclid(400);
            let yoe = y - era * 400;
            let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + day - 1;
            let days = era * 146_097 + yoe * 365 + yoe / 4 - yoe / 100 + doy - 719_468;
            Some(days * 86_400 + h * 3600 + mi * 60 + sec)
        }
        _ => None,
    }
}

fn window_name(minutes: Option<i64>, fallback: &str) -> String {
    match minutes {
        Some(m) if m <= 6 * 60 => format!("{}-hour", (m + 59) / 60),
        Some(m) if (6 * 24 * 60..=8 * 24 * 60).contains(&m) => "Weekly".into(),
        Some(m) if m >= 28 * 24 * 60 => "Monthly".into(),
        Some(m) if m >= 24 * 60 => format!("{}-day", m / (24 * 60)),
        _ => fallback.into(),
    }
}

// ── Codex ───────────────────────────────────────────────────────────────────

fn codex_window(data: &Value, id: &str, label: &str) -> Option<UsageLimit> {
    let used = number(first(data, &["used_percent", "usedPercent"]))?;
    let minutes = first(data, &["window_minutes", "windowDurationMins"])
        .and_then(Value::as_i64)
        .filter(|m| *m > 0)
        .or_else(|| {
            first(data, &["limit_window_seconds", "limitWindowSeconds"])
                .and_then(Value::as_i64)
                .filter(|s| *s > 0)
                .map(|s| (s + 59) / 60)
        });
    Some(UsageLimit {
        id: id.into(),
        name: window_name(minutes, label),
        used_percent: Some(used.clamp(0.0, 100.0)),
        window_minutes: minutes,
        resets_at: timestamp(first(data, &["reset_at", "resets_at", "resetsAt"])),
        reached: used >= 100.0,
        ..Default::default()
    })
}

/// The windows of one Codex limit object (`rate_limit.primary_window`, …).
fn codex_limit(data: &Value, id: &str) -> Vec<UsageLimit> {
    let rate = first(data, &["rate_limit", "rateLimit"]).unwrap_or(data);
    let mut limits = Vec::new();
    for (key, alt, label) in [
        ("primary_window", "primary", "Short window"),
        ("secondary_window", "secondary", "Long window"),
    ] {
        if let Some(window) =
            first(rate, &[key, alt]).and_then(|w| codex_window(w, &format!("{id}:{alt}"), label))
        {
            limits.push(window);
        }
    }
    limits
}

pub(crate) fn parse_codex(payload: &Value) -> ProviderUsage {
    let values = payload
        .get("result")
        .filter(|r| r.is_object())
        .unwrap_or(payload);
    let plan = first(values, &["plan_type", "planType"])
        .and_then(Value::as_str)
        .map(str::to_string);
    let mut limits = Vec::new();
    if let Some(by_id) = values.get("rateLimitsByLimitId").and_then(Value::as_object) {
        let mut ids: Vec<&String> = by_id.keys().collect();
        ids.sort_by_key(|id| (id.as_str() != "codex", id.to_string()));
        for id in ids {
            limits.extend(codex_limit(&by_id[id], id));
        }
    } else if let Some(primary) = values.get("rateLimits").filter(|v| v.is_object()) {
        limits.extend(codex_limit(primary, "codex"));
    } else {
        limits.extend(codex_limit(values, "codex"));
        if let Some(extra) = first(values, &["additional_rate_limits", "additionalRateLimits"])
            .and_then(Value::as_array)
        {
            for (index, item) in extra.iter().enumerate() {
                let id = first(item, &["limit_id", "limitId", "metered_feature"])
                    .and_then(Value::as_str)
                    .map(str::to_string)
                    .unwrap_or_else(|| format!("extra-{index}"));
                let mut windows = codex_limit(item, &id);
                if let Some(name) =
                    first(item, &["limit_name", "limitName"]).and_then(Value::as_str)
                {
                    for window in &mut windows {
                        window.name = format!("{name} · {}", window.name);
                    }
                }
                limits.extend(windows);
            }
        }
    }
    // A monthly spend cap (Codex with credits).
    if let Some(limit) = first(values, &["spend_control", "spendControl"])
        .and_then(|s| first(s, &["individual_limit", "individualLimit"]))
    {
        let total = number(first(limit, &["limit", "total"]));
        let used = number(limit.get("used"));
        let percent = number(first(limit, &["used_percent", "usedPercent"])).or_else(|| {
            match (used, total) {
                (Some(used), Some(total)) if total > 0.0 => Some(used / total * 100.0),
                _ => None,
            }
        });
        limits.push(UsageLimit {
            id: "codex_monthly_usage".into(),
            name: "Monthly usage".into(),
            used_percent: percent.map(|p| p.clamp(0.0, 100.0)),
            window_minutes: Some(30 * 24 * 60),
            resets_at: timestamp(first(limit, &["reset_at", "resetsAt"])),
            used,
            total,
            reached: percent.is_some_and(|p| p >= 100.0),
            ..Default::default()
        });
    }
    ProviderUsage {
        provider: "codex".into(),
        plan,
        limits,
    }
}

async fn codex() -> Result<ProviderUsage, String> {
    let token = crate::provider_login::fresh_codex_token().await?;
    let mut request = client()
        .get("https://chatgpt.com/backend-api/wham/usage")
        .bearer_auth(token)
        .header("originator", "evo");
    if let Some(account) = crate::provider_settings::option("codex", "headers").and_then(|h| {
        h.get("ChatGPT-Account-Id")
            .and_then(Value::as_str)
            .map(str::to_string)
    }) {
        request = request.header("ChatGPT-Account-Id", account);
    }
    Ok(parse_codex(&get_json(request, "ChatGPT").await?))
}

// ── Copilot ─────────────────────────────────────────────────────────────────

const COPILOT_QUOTAS: [(&str, &str); 3] = [
    ("premium_interactions", "Premium requests"),
    ("chat", "Chat"),
    ("completions", "Completions"),
];

pub(crate) fn parse_copilot(payload: &Value) -> ProviderUsage {
    let plan = first(payload, &["copilot_plan", "access_type_sku"])
        .and_then(Value::as_str)
        .map(str::to_string);
    let reset = timestamp(first(
        payload,
        &["quota_reset_date_utc", "quota_reset_date"],
    ));
    let mut limits = Vec::new();
    if let Some(snapshots) = payload.get("quota_snapshots") {
        for (key, name) in COPILOT_QUOTAS {
            let Some(quota) = snapshots.get(key).filter(|q| q.is_object()) else {
                continue;
            };
            let unlimited = quota.get("unlimited") == Some(&Value::Bool(true));
            let total = number(quota.get("entitlement")).filter(|t| *t > 0.0);
            let remaining = number(quota.get("remaining"));
            let used = match (total, remaining) {
                (Some(total), Some(remaining)) => Some(total - remaining.clamp(0.0, total)),
                _ => None,
            };
            let percent = number(quota.get("percent_remaining"))
                .map(|left| 100.0 - left)
                .or_else(|| match (used, total) {
                    (Some(used), Some(total)) => Some(used / total * 100.0),
                    _ => None,
                })
                .map(|p| p.clamp(0.0, 100.0));
            limits.push(UsageLimit {
                id: key.into(),
                name: name.into(),
                used_percent: if unlimited { None } else { percent },
                window_minutes: Some(30 * 24 * 60),
                resets_at: timestamp(quota.get("quota_reset_at")).or(reset),
                used,
                total,
                unlimited,
                reached: !unlimited && percent.is_some_and(|p| p >= 100.0),
            });
        }
    }
    ProviderUsage {
        provider: "copilot".into(),
        plan,
        limits,
    }
}

async fn copilot() -> Result<ProviderUsage, String> {
    let provider = crate::provider_settings::find("copilot")?;
    let token =
        crate::provider_settings::request_key(provider).ok_or("Sign in to GitHub Copilot first")?;
    let request = client()
        .get("https://api.github.com/copilot_internal/user")
        .header("authorization", format!("token {token}"));
    Ok(parse_copilot(&get_json(request, "GitHub").await?))
}

// ── OpenCode Go ─────────────────────────────────────────────────────────────

const GO_WINDOWS: [(&str, &str, i64); 3] = [
    ("rolling", "5-hour", 5 * 60),
    ("weekly", "Weekly", 7 * 24 * 60),
    ("monthly", "Monthly", 30 * 24 * 60),
];

pub(crate) fn parse_opencode_go(payload: &Value) -> Result<ProviderUsage, String> {
    let usage = payload
        .get("usage")
        .ok_or("OpenCode Go returned no usage")?;
    let limits: Vec<UsageLimit> = GO_WINDOWS
        .iter()
        .filter_map(|(key, name, minutes)| {
            let item = usage.get(*key)?;
            let percent = number(item.get("percent"))?.clamp(0.0, 100.0);
            let status_ok = item
                .get("status")
                .and_then(Value::as_str)
                .is_none_or(|s| s == "ok");
            Some(UsageLimit {
                id: (*key).into(),
                name: (*name).into(),
                used_percent: Some(percent),
                window_minutes: Some(*minutes),
                resets_at: timestamp(item.get("resetsAt")),
                reached: percent >= 100.0 || !status_ok,
                ..Default::default()
            })
        })
        .collect();
    if limits.is_empty() {
        return Err("OpenCode Go returned no usage windows".into());
    }
    Ok(ProviderUsage {
        provider: "opencode-go".into(),
        plan: Some("go".into()),
        limits,
    })
}

async fn opencode_go() -> Result<ProviderUsage, String> {
    let provider = crate::provider_settings::find("opencode-go")?;
    let key =
        crate::provider_settings::request_key(provider).ok_or("Add an OpenCode Go key first")?;
    let base = crate::provider_settings::base_url_of(provider);
    let request = client()
        .get(format!("{}/usage", base.trim_end_matches('/')))
        .bearer_auth(key);
    parse_opencode_go(&get_json(request, "OpenCode Go").await?)
}

/// The plan usage of `provider`.
pub async fn get(provider: &str) -> Result<ProviderUsage, String> {
    match provider {
        "codex" => codex().await,
        "copilot" => copilot().await,
        "opencode-go" => opencode_go().await,
        other => Err(format!("{other} does not report plan usage")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn codex_windows() {
        let usage = parse_codex(&json!({
            "plan_type": "plus",
            "rate_limit": {
                "primary_window": {"used_percent": 42.5, "limit_window_seconds": 18000, "reset_at": 1793000000},
                "secondary_window": {"used_percent": 100, "limit_window_seconds": 604800, "reset_at": 1793500000}
            }
        }));
        assert_eq!(usage.plan.as_deref(), Some("plus"));
        assert_eq!(usage.limits.len(), 2);
        assert_eq!(usage.limits[0].name, "5-hour");
        assert_eq!(usage.limits[0].used_percent, Some(42.5));
        assert_eq!(usage.limits[1].name, "Weekly");
        assert!(usage.limits[1].reached);
    }

    #[test]
    fn copilot_premium_requests() {
        let usage = parse_copilot(&json!({
            "copilot_plan": "business",
            "quota_reset_date_utc": "2026-12-01T00:00:00Z",
            "quota_snapshots": {
                "premium_interactions": {"entitlement": 300, "remaining": 120, "percent_remaining": 40, "unlimited": false},
                "chat": {"unlimited": true}
            }
        }));
        let premium = &usage.limits[0];
        assert_eq!(
            (premium.used, premium.total, premium.used_percent),
            (Some(180.0), Some(300.0), Some(60.0))
        );
        assert!(premium.resets_at.is_some());
        assert!(usage.limits[1].unlimited && usage.limits[1].used_percent.is_none());
    }

    #[test]
    fn opencode_go_windows() {
        let usage = parse_opencode_go(&json!({"usage": {
            "rolling": {"percent": 12, "status": "ok", "resetsAt": "2026-11-05T12:00:00Z"},
            "weekly": {"percent": 100, "status": "limited"}
        }}))
        .unwrap();
        assert_eq!(usage.limits.len(), 2);
        assert!(usage.limits[1].reached);
    }
}
