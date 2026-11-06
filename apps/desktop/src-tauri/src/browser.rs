//! In-app browser: each tab is a child webview laid over the side panel's
//! browser area (the UI keeps its bounds in step with the layout). Pages get
//! `browser_page.js` before their own scripts — console capture and the page
//! outline the agent reads — and no IPC to the app.
//!
//! Page events (load start/finish, title, a new window asked for) go to the
//! owning window as `browser://event`. On Windows, `browser_cdp` calls the
//! WebView2 DevTools Protocol for screenshots and real (trusted) input;
//! elsewhere the UI falls back to script-driven clicks and typing.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Mutex;

use serde::Serialize;
use serde_json::Value;
use tauri::webview::{NewWindowResponse, PageLoadEvent, WebviewBuilder};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, Url, WebviewUrl, Window};

const PAGE_SCRIPT: &str = include_str!("browser_page.js");
pub const TAB_PREFIX: &str = "browser-";

#[derive(Default)]
pub struct BrowserState {
    /// Tab label → the window that owns it.
    tabs: Mutex<HashMap<String, String>>,
    next: AtomicU32,
}

impl BrowserState {
    /// Close every tab of `window` (it closed).
    pub fn close_window(&self, app: &AppHandle, window: &str) {
        let labels: Vec<String> = {
            let mut tabs = self.tabs.lock().expect("browser tabs lock");
            let labels: Vec<String> = tabs.iter().filter(|(_, w)| *w == window).map(|(l, _)| l.clone()).collect();
            for label in &labels {
                tabs.remove(label);
            }
            labels
        };
        for label in labels {
            if let Some(webview) = app.get_webview(&label) {
                let _ = webview.close();
            }
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct BrowserEvent {
    tab: String,
    kind: &'static str,
    url: Option<String>,
    title: Option<String>,
}

fn emit(app: &AppHandle, window: &str, event: BrowserEvent) {
    let _ = app.emit_to(window, "browser://event", event);
}

/// A URL from what the user typed: a URL, a host, a local path, or a search.
pub fn normalize_url(input: &str) -> Result<Url, String> {
    let text = input.trim();
    if text.is_empty() {
        return Url::parse("about:blank").map_err(|e| e.to_string());
    }
    if let Ok(url) = Url::parse(text) {
        if matches!(url.scheme(), "http" | "https" | "file" | "about" | "data") {
            return Ok(url);
        }
        // `localhost:3000` parses with scheme "localhost".
        if !text.contains("://") && text.split(':').next().is_some_and(|host| host == "localhost" || host.contains('.')) {
            return Url::parse(&format!("http://{text}")).map_err(|e| e.to_string());
        }
        if url.scheme().len() == 1 {
            // A Windows path: C:\…
            return Url::from_file_path(text).map_err(|_| format!("not a file path: {text}"));
        }
        return Err(format!("{} links are not opened here", url.scheme()));
    }
    if text.starts_with('/') || text.starts_with("\\\\") {
        return Url::from_file_path(text).map_err(|_| format!("not a file path: {text}"));
    }
    let host_like = !text.contains(' ') && (text.contains('.') || text.starts_with("localhost") || text.starts_with("127.0.0.1"));
    if host_like {
        let local = text.starts_with("localhost") || text.starts_with("127.") || text.starts_with("[::1]");
        let scheme = if local { "http" } else { "https" };
        return Url::parse(&format!("{scheme}://{text}")).map_err(|e| e.to_string());
    }
    let mut search = Url::parse("https://duckduckgo.com/").expect("search url");
    search.query_pairs_mut().append_pair("q", text);
    Ok(search)
}

fn webview(app: &AppHandle, tab: &str) -> Result<tauri::Webview, String> {
    app.get_webview(tab).ok_or_else(|| format!("browser tab {tab} is closed"))
}

/// Open a tab showing `url` at the given bounds (logical pixels in the window).
#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn browser_create(
    app: AppHandle,
    window: Window,
    state: tauri::State<'_, BrowserState>,
    url: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
    visible: bool,
) -> Result<String, String> {
    let url = normalize_url(&url)?;
    let owner = window.label().to_string();
    let host = window;
    let label = format!("{TAB_PREFIX}{}", state.next.fetch_add(1, Ordering::Relaxed) + 1);

    let (load_app, load_owner) = (app.clone(), owner.clone());
    let (title_app, title_owner) = (app.clone(), owner.clone());
    let (popup_app, popup_owner, popup_label) = (app.clone(), owner.clone(), label.clone());
    let builder = WebviewBuilder::new(&label, WebviewUrl::External(url))
        .initialization_script(PAGE_SCRIPT)
        .zoom_hotkeys_enabled(true)
        .devtools(true)
        .on_page_load(move |webview, payload| {
            let kind = match payload.event() {
                PageLoadEvent::Started => "loadStart",
                PageLoadEvent::Finished => "loadEnd",
            };
            emit(
                &load_app,
                &load_owner,
                BrowserEvent { tab: webview.label().to_string(), kind, url: Some(payload.url().to_string()), title: None },
            );
        })
        .on_document_title_changed(move |webview, title| {
            emit(
                &title_app,
                &title_owner,
                BrowserEvent { tab: webview.label().to_string(), kind: "title", url: None, title: Some(title) },
            );
        })
        // Links that open a new window open a new tab instead.
        .on_new_window(move |url, _features| {
            emit(
                &popup_app,
                &popup_owner,
                BrowserEvent { tab: popup_label.clone(), kind: "newWindow", url: Some(url.to_string()), title: None },
            );
            NewWindowResponse::Deny
        });

    let child = host
        .add_child(builder, LogicalPosition::new(x, y), LogicalSize::new(width.max(1.0), height.max(1.0)))
        .map_err(|e| format!("could not open a browser tab: {e}"))?;
    if !visible {
        let _ = child.hide();
    }
    state.tabs.lock().expect("browser tabs lock").insert(label.clone(), owner);
    Ok(label)
}

#[tauri::command]
pub fn browser_bounds(app: AppHandle, tab: String, x: f64, y: f64, width: f64, height: f64) -> Result<(), String> {
    let webview = webview(&app, &tab)?;
    webview
        .set_bounds(tauri::Rect {
            position: LogicalPosition::new(x, y).into(),
            size: LogicalSize::new(width.max(1.0), height.max(1.0)).into(),
        })
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub fn browser_visible(app: AppHandle, tab: String, visible: bool, focus: Option<bool>) -> Result<(), String> {
    let webview = webview(&app, &tab)?;
    if visible {
        webview.show().map_err(|e| e.to_string())?;
        if focus == Some(true) {
            let _ = webview.set_focus();
        }
    } else {
        webview.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Navigate to what the user typed (URL, host or search); returns the URL used.
#[tauri::command]
pub fn browser_navigate(app: AppHandle, tab: String, url: String) -> Result<String, String> {
    let target = normalize_url(&url)?;
    webview(&app, &tab)?.navigate(target.clone()).map_err(|e| e.to_string())?;
    Ok(target.to_string())
}

/// back | forward | reload | stop
#[tauri::command]
pub fn browser_history(app: AppHandle, tab: String, action: String) -> Result<(), String> {
    let webview = webview(&app, &tab)?;
    match action.as_str() {
        "reload" => webview.reload().map_err(|e| e.to_string()),
        "back" => webview.eval("history.back()").map_err(|e| e.to_string()),
        "forward" => webview.eval("history.forward()").map_err(|e| e.to_string()),
        "stop" => webview.eval("window.stop()").map_err(|e| e.to_string()),
        other => Err(format!("unknown browser action {other}")),
    }
}

#[tauri::command]
pub fn browser_url(app: AppHandle, tab: String) -> Result<String, String> {
    webview(&app, &tab)?.url().map(|u| u.to_string()).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn browser_close(app: AppHandle, state: tauri::State<'_, BrowserState>, tab: String) {
    state.tabs.lock().expect("browser tabs lock").remove(&tab);
    if let Some(webview) = app.get_webview(&tab) {
        let _ = webview.close();
    }
}

#[tauri::command]
pub fn browser_devtools(app: AppHandle, tab: String) -> Result<(), String> {
    webview(&app, &tab)?.open_devtools();
    Ok(())
}

#[tauri::command]
pub fn browser_zoom(app: AppHandle, tab: String, scale: f64) -> Result<(), String> {
    webview(&app, &tab)?.set_zoom(scale.clamp(0.25, 5.0)).map_err(|e| e.to_string())
}

/// How long `browser_eval` waits for the page, including a returned promise.
const EVAL_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(30);

/// Turns the result into something JSON can carry: elements as a short tag,
/// errors as their message, Map/Set as arrays, functions as their source.
const EVAL_SERIALIZE: &str = r#"(v) => {
  const seen = new WeakSet();
  const walk = (x, depth) => {
    if (x === undefined) return null;
    if (typeof x === "function") return `[function ${x.name || "anonymous"}]`;
    if (typeof x === "bigint") return `${x}n`;
    if (typeof x === "symbol") return x.toString();
    if (x === null || typeof x !== "object") return x;
    if (seen.has(x)) return "[circular]";
    if (depth > 8) return "[…]";
    seen.add(x);
    if (x instanceof Error) return `${x.name}: ${x.message}`;
    if (typeof Element !== "undefined" && x instanceof Element) {
      const attrs = ["id", "class", "type", "name", "href", "value"]
        .filter((a) => x.hasAttribute(a))
        .map((a) => `${a}="${String(x.getAttribute(a)).slice(0, 60)}"`);
      return `<${[x.tagName.toLowerCase(), ...attrs].join(" ")}>`;
    }
    if (typeof Node !== "undefined" && x instanceof Node) return `[${x.nodeName}]`;
    if (x instanceof Map) return [...x.entries()].map(([k, val]) => [walk(k, depth + 1), walk(val, depth + 1)]);
    if (x instanceof Set || (typeof NodeList !== "undefined" && x instanceof NodeList) || (typeof HTMLCollection !== "undefined" && x instanceof HTMLCollection)) return [...x].map((i) => walk(i, depth + 1));
    if (Array.isArray(x)) return x.map((i) => walk(i, depth + 1));
    if (typeof x.toJSON === "function") { try { return walk(x.toJSON(), depth + 1); } catch {} }
    const out = {};
    for (const key of Object.keys(x)) { try { out[key] = walk(x[key], depth + 1); } catch {} }
    return out;
  };
  return walk(v, 0);
}"#;

/// The page-side wrapper: runs `body` (which yields the value), keeps a
/// returned promise under `key` for polling, and reports exceptions.
fn eval_wrapper(body: &str, key: &str) -> String {
    format!(
        r#"(() => {{
  const __ser = {EVAL_SERIALIZE};
  const __err = (e) => ({{ __error: e instanceof Error ? `${{e.name}}: ${{e.message}}` : String(e) }});
  try {{
    const __r = {body};
    if (__r && typeof __r.then === "function") {{
      const pending = (window.__evoPending = window.__evoPending || {{}});
      pending["{key}"] = {{ done: false }};
      __r.then(
        (v) => {{ pending["{key}"] = {{ done: true, value: __ser(v) }}; }},
        (e) => {{ pending["{key}"] = {{ done: true, error: __err(e).__error }}; }},
      );
      return {{ __pending: "{key}" }};
    }}
    return __ser(__r);
  }} catch (e) {{
    return __err(e);
  }}
}})()"#
    )
}

async fn eval_raw(webview: &tauri::Webview, script: String) -> Result<String, String> {
    let (tx, rx) = tokio::sync::oneshot::channel::<String>();
    let tx = Mutex::new(Some(tx));
    webview
        .eval_with_callback(script, move |json| {
            if let Some(tx) = tx.lock().ok().and_then(|mut slot| slot.take()) {
                let _ = tx.send(json);
            }
        })
        .map_err(|e| e.to_string())?;
    tokio::time::timeout(EVAL_TIMEOUT, rx)
        .await
        .map_err(|_| format!("the page did not answer within {}s", EVAL_TIMEOUT.as_secs()))?
        .map_err(|_| "the page went away".to_string())
}

/// Run `script` in the page; resolves to its JSON result (`null` for undefined).
/// A returned promise is awaited. With `statements`, a script that is not a
/// single expression (`a(); b`) runs as a program and yields its last value.
#[tauri::command]
pub async fn browser_eval(
    app: AppHandle,
    tab: String,
    script: String,
    statements: Option<bool>,
) -> Result<Value, String> {
    let webview = webview(&app, &tab)?;
    let key = format!(
        "e{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0)
    );
    // A single expression runs as written: no eval(), so page security policies don't apply.
    let mut json = eval_raw(
        &webview,
        eval_wrapper(&format!("(() => {{ return ({script}\n); }})()"), &key),
    )
    .await?;
    // An empty answer means the script did not compile as an expression.
    if json.trim().is_empty() {
        if statements != Some(true) {
            return Err("the script is not a valid JavaScript expression".into());
        }
        let source = serde_json::to_string(&script).map_err(|e| e.to_string())?;
        json = eval_raw(
            &webview,
            eval_wrapper(&format!("(0, eval)({source})"), &key),
        )
        .await?;
        if json.trim().is_empty() {
            return Err("the script could not run".into());
        }
    }
    let value: Value = serde_json::from_str(&json).unwrap_or(Value::String(json));
    if let Some(error) = value.get("__error").and_then(Value::as_str) {
        if error.starts_with("EvalError") {
            return Err(format!(
                "{error}\nThis page's security policy blocks running statements; pass one expression instead, e.g. (() => {{ …; return value; }})()"
            ));
        }
        return Err(error.to_string());
    }
    let Some(pending) = value
        .get("__pending")
        .and_then(Value::as_str)
        .map(str::to_string)
    else {
        return Ok(value);
    };
    // A promise: poll until it settles.
    let started = std::time::Instant::now();
    let probe = format!(
        r#"(() => {{ const p = window.__evoPending && window.__evoPending["{pending}"]; if (!p) return {{ gone: true }}; if (p.done) delete window.__evoPending["{pending}"]; return p; }})()"#
    );
    loop {
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
        let json = eval_raw(&webview, probe.clone()).await?;
        let state: Value = serde_json::from_str(&json).unwrap_or(Value::Null);
        if state.get("gone").is_some() || state.is_null() {
            return Err("the page navigated away before the promise settled".into());
        }
        if state.get("done").and_then(Value::as_bool) == Some(true) {
            if let Some(error) = state.get("error").and_then(Value::as_str) {
                return Err(format!("the promise rejected: {error}"));
            }
            return Ok(state.get("value").cloned().unwrap_or(Value::Null));
        }
        if started.elapsed() > EVAL_TIMEOUT {
            let _ = eval_raw(
                &webview,
                format!(r#"window.__evoPending && delete window.__evoPending["{pending}"]"#),
            )
            .await;
            return Err(format!(
                "the promise did not settle within {}s",
                EVAL_TIMEOUT.as_secs()
            ));
        }
    }
}

/// This window's open tabs and their URLs (a reloaded window adopts them).
#[tauri::command]
pub fn browser_list(
    app: AppHandle,
    window: Window,
    state: tauri::State<'_, BrowserState>,
) -> Vec<(String, String)> {
    let tabs = state.tabs.lock().expect("browser tabs lock");
    let mut list: Vec<(String, String)> = tabs
        .iter()
        .filter(|(_, owner)| *owner == window.label())
        .filter_map(|(label, _)| {
            let url = app
                .get_webview(label)?
                .url()
                .map(|u| u.to_string())
                .unwrap_or_default();
            Some((label.clone(), url))
        })
        .collect();
    let number = |label: &str| {
        label
            .trim_start_matches(TAB_PREFIX)
            .parse::<u32>()
            .unwrap_or(0)
    };
    list.sort_by_key(|(label, _)| number(label));
    list
}

/// Call a DevTools Protocol method on the tab (Windows / WebView2 only).
#[tauri::command]
pub async fn browser_cdp(app: AppHandle, tab: String, method: String, params: Option<Value>) -> Result<Value, String> {
    let webview = webview(&app, &tab)?;
    cdp(&webview, method, params.unwrap_or(Value::Object(Default::default()))).await
}

#[cfg(windows)]
async fn cdp(webview: &tauri::Webview, method: String, params: Value) -> Result<Value, String> {
    use webview2_com::CallDevToolsProtocolMethodCompletedHandler;
    use windows_core::HSTRING;

    let (tx, rx) = tokio::sync::oneshot::channel::<Result<String, String>>();
    let params = params.to_string();
    webview
        .with_webview(move |platform| {
            let result = (|| -> Result<(), String> {
                let core = unsafe { platform.controller().CoreWebView2() }.map_err(|e| e.to_string())?;
                let tx = std::sync::Mutex::new(Some(tx));
                let handler = CallDevToolsProtocolMethodCompletedHandler::create(Box::new(move |result, json| {
                    if let Some(tx) = tx.lock().ok().and_then(|mut slot| slot.take()) {
                        let _ = tx.send(result.map(|()| json).map_err(|e| e.message().to_string()));
                    }
                    Ok(())
                }));
                unsafe { core.CallDevToolsProtocolMethod(&HSTRING::from(method), &HSTRING::from(params), &handler) }
                    .map_err(|e| e.to_string())
            })();
            if let Err(error) = result {
                log_cdp_error(&error);
            }
        })
        .map_err(|e| e.to_string())?;
    let json = tokio::time::timeout(std::time::Duration::from_secs(30), rx)
        .await
        .map_err(|_| "the browser did not answer within 30s".to_string())?
        .map_err(|_| "the browser call was dropped".to_string())??;
    serde_json::from_str(&json).map_err(|e| e.to_string())
}

#[cfg(windows)]
fn log_cdp_error(error: &str) {
    eprintln!("browser devtools call failed: {error}");
}

#[cfg(not(windows))]
async fn cdp(_webview: &tauri::Webview, _method: String, _params: Value) -> Result<Value, String> {
    Err("unsupported: the DevTools protocol is only available on Windows".into())
}

#[cfg(test)]
mod tests {
    use super::normalize_url;

    #[test]
    fn urls_hosts_paths_and_searches() {
        assert_eq!(normalize_url("https://example.com/a").unwrap().as_str(), "https://example.com/a");
        assert_eq!(normalize_url("example.com").unwrap().as_str(), "https://example.com/");
        assert_eq!(normalize_url("localhost:3000").unwrap().as_str(), "http://localhost:3000/");
        assert_eq!(normalize_url("127.0.0.1:8080/x").unwrap().as_str(), "http://127.0.0.1:8080/x");
        assert!(normalize_url("rust borrow checker").unwrap().as_str().starts_with("https://duckduckgo.com/?q=rust+borrow+checker"));
        assert!(normalize_url("javascript:alert(1)").is_err());
        #[cfg(windows)]
        assert!(normalize_url(r"C:\Users\x\index.html").unwrap().as_str().starts_with("file:///C:/Users/x/index.html"));
    }
}
