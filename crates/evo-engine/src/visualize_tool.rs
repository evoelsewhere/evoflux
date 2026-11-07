//! The widget tools: `visualize_read_me` and `show_widget`.
//!
//! A port of v3 `app/agent/tools/builtin/visualize/{read_me,show_widget,
//! guidelines,geometry}.py` (tag `v3.1.1`). The model loads the design
//! guidelines once (`visualize_read_me {modules}`), then renders an HTML
//! widget inline in the chat (`show_widget`). Diagram SVGs get the v3
//! geometry preflight ([`check_svg_layout`]); layout errors come back to the
//! model, which corrects them and calls again.
//!
//! The engine only validates and echoes the widget: the desktop renders it
//! from the tool call's arguments (v3 also rebuilt widgets from the arguments
//! on replay). v3's chunked `widget_delta` stream events have no counterpart
//! here.
//!
//! Both tools only read, so they need no approval and are safe to replay.

use std::sync::Arc;

use async_trait::async_trait;
use evo_agent::agent_tool::AgentTool;
use evo_agent::error::AgentError;
use evo_agent::types::{AgentToolResult, TextContentOrImage, ToolExecutionMode, ToolResultPartial};
use evo_ai::types::{Schema, Tool};
use serde_json::{json, Map, Value};
use tokio_util::sync::CancellationToken;

pub const READ_ME_TOOL: &str = "visualize_read_me";
pub const SHOW_WIDGET_TOOL: &str = "show_widget";

// ── Guidelines (v3 `guidelines.py`, text verbatim, "EvoFlux" → "evo") ──────

/// The modules `visualize_read_me` knows, in v3 order.
pub const AVAILABLE_MODULES: [&str; 6] = [
    "interactive",
    "chart",
    "mockup",
    "art",
    "diagram",
    "gallery",
];

const CORE_GUIDELINES: &str = include_str!("visualize/core.md");

fn module_section(module: &str) -> Option<&'static str> {
    Some(match module {
        "interactive" => include_str!("visualize/interactive.md"),
        "chart" => include_str!("visualize/chart.md"),
        "mockup" => include_str!("visualize/mockup.md"),
        "art" => include_str!("visualize/art.md"),
        "diagram" => include_str!("visualize/diagram.md"),
        "gallery" => include_str!("visualize/gallery.md"),
        _ => return None,
    })
}

/// The core guidelines plus each requested module once, in request order
/// (v3 `get_guidelines`). Unknown modules are skipped.
pub fn get_guidelines(modules: &[String]) -> String {
    let mut content = CORE_GUIDELINES.replace("\r\n", "\n");
    let mut seen: Vec<&str> = Vec::new();
    for module in modules {
        let Some(section) = module_section(module) else {
            continue;
        };
        if seen.contains(&section) {
            continue;
        }
        seen.push(section);
        content.push_str("\n\n");
        content.push_str(&section.replace("\r\n", "\n"));
    }
    content
}

/// What `visualize_read_me` returns for `modules` (v3 `visualize_read_me`).
pub fn read_me(modules: &[String]) -> String {
    let valid: Vec<String> = modules
        .iter()
        .filter(|module| AVAILABLE_MODULES.contains(&module.as_str()))
        .cloned()
        .collect();
    if valid.is_empty() {
        return format!(
            "Invalid modules. Available options: {}\n\nRequested: {}",
            AVAILABLE_MODULES.join(", "),
            modules.join(", ")
        );
    }
    get_guidelines(&valid)
}

// ── Tools ───────────────────────────────────────────────────────────────────

pub struct ReadMeTool {
    schema: Tool,
}

pub struct ShowWidgetTool {
    schema: Tool,
}

pub fn create_read_me_tool() -> Arc<dyn AgentTool> {
    Arc::new(ReadMeTool {
        schema: Tool {
            name: READ_ME_TOOL.into(),
            description: format!(
                "Load design guidelines for creating interactive HTML widgets. Call this once before your \
                 first show_widget call to understand the design system. Available modules: {}",
                AVAILABLE_MODULES.join(", ")
            ),
            parameters: Schema::new(json!({
                "type": "object",
                "properties": {
                    "modules": {
                        "type": "array",
                        "items": { "type": "string" },
                        "description": "List of design modules to load. Options: interactive, chart, mockup, art, diagram"
                    }
                },
                "required": ["modules"]
            })),
            constrained_sampling: None,
        },
    })
}

pub fn create_show_widget_tool() -> Arc<dyn AgentTool> {
    Arc::new(ShowWidgetTool {
        schema: Tool {
            name: SHOW_WIDGET_TOOL.into(),
            description: "Render an interactive HTML widget inline in the conversation. Call visualize_read_me \
                 first. Diagram SVGs receive a geometry preflight; correct returned layout errors and retry \
                 before the widget is shown."
                .into(),
            parameters: Schema::new(json!({
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Snake_case identifier for the widget"
                    },
                    "loading_messages": {
                        "type": "array",
                        "items": { "type": "string" },
                        "description": "1-4 short messages shown while widget loads"
                    },
                    "widget_code": {
                        "type": "string",
                        "description": "HTML content to render. No <!DOCTYPE>, <html>, <head>, or <body> tags."
                    },
                    "i_have_seen_read_me": {
                        "type": "boolean",
                        "description": "Must be true. Confirms you called visualize_read_me first."
                    },
                    "width": {
                        "type": "integer",
                        "description": "Widget width in pixels",
                        "minimum": WIDTH.0,
                        "maximum": WIDTH.1,
                        "default": WIDTH.2
                    },
                    "height": {
                        "type": "integer",
                        "description": "Widget height in pixels",
                        "minimum": HEIGHT.0,
                        "maximum": HEIGHT.1,
                        "default": HEIGHT.2
                    }
                },
                "required": ["title", "loading_messages", "widget_code", "i_have_seen_read_me"]
            })),
            constrained_sampling: None,
        },
    })
}

/// (min, max, default) in pixels, as v3's `Field(ge, le)` and defaults.
const WIDTH: (i64, i64, i64) = (200, 1200, 800);
const HEIGHT: (i64, i64, i64) = (150, 900, 600);

fn text_result(text: String, details: Value) -> AgentToolResult {
    AgentToolResult {
        content: vec![TextContentOrImage::text(text)],
        details,
        ..Default::default()
    }
}

#[async_trait]
impl AgentTool for ReadMeTool {
    fn schema(&self) -> &Tool {
        &self.schema
    }

    fn label(&self) -> &str {
        READ_ME_TOOL
    }

    fn execution_mode(&self) -> ToolExecutionMode {
        ToolExecutionMode::Parallel
    }

    async fn execute(
        &self,
        _tool_call_id: &str,
        params: Value,
        _signal: CancellationToken,
        _on_update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let modules = string_list(&params, "modules")?;
        let text = read_me(&modules);
        Ok(text_result(text, json!({ "modules": modules })))
    }
}

#[async_trait]
impl AgentTool for ShowWidgetTool {
    fn schema(&self) -> &Tool {
        &self.schema
    }

    fn label(&self) -> &str {
        SHOW_WIDGET_TOOL
    }

    fn execution_mode(&self) -> ToolExecutionMode {
        // v3: `concurrency_safe=False`.
        ToolExecutionMode::Sequential
    }

    async fn execute(
        &self,
        _tool_call_id: &str,
        params: Value,
        _signal: CancellationToken,
        _on_update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let input = ShowWidgetInput::parse(&params)?;
        let result = show_widget(input);
        let text = serde_json::to_string(&result).unwrap_or_default();
        Ok(text_result(text, result))
    }
}

/// `show_widget`'s arguments after validation (v3's pydantic signature).
#[derive(Debug, Clone)]
pub struct ShowWidgetInput {
    pub title: String,
    pub loading_messages: Vec<String>,
    pub widget_code: String,
    pub i_have_seen_read_me: bool,
    pub width: i64,
    pub height: i64,
}

impl ShowWidgetInput {
    /// Validate raw arguments: required fields, types, and the width/height
    /// bounds (v3 `ge`/`le`). An `Err` is the tool's error, as v3's argument
    /// validation was.
    pub fn parse(params: &Value) -> Result<Self, AgentError> {
        let invalid = |message: String| {
            AgentError::Validation(format!("show_widget input invalid: {message}"))
        };
        let object = params
            .as_object()
            .ok_or_else(|| invalid("arguments must be an object".into()))?;
        let string = |key: &str| -> Result<String, AgentError> {
            match object.get(key) {
                Some(Value::String(text)) => Ok(text.clone()),
                Some(_) => Err(invalid(format!("{key}: Input should be a valid string"))),
                None => Err(invalid(format!("{key}: Field required"))),
            }
        };
        let title = string("title")?;
        let widget_code = string("widget_code")?;
        let loading_messages = string_list(params, "loading_messages")?;
        let i_have_seen_read_me = match object.get("i_have_seen_read_me") {
            Some(Value::Bool(flag)) => *flag,
            Some(Value::String(text)) if text.eq_ignore_ascii_case("true") => true,
            Some(Value::String(text)) if text.eq_ignore_ascii_case("false") => false,
            Some(_) => {
                return Err(invalid(
                    "i_have_seen_read_me: Input should be a valid boolean".into(),
                ))
            }
            None => return Err(invalid("i_have_seen_read_me: Field required".into())),
        };
        let bounded = |key: &str,
                       (min, max, default): (i64, i64, i64)|
         -> Result<i64, AgentError> {
            let value = match object.get(key) {
                None | Some(Value::Null) => return Ok(default),
                Some(value) => integer(value)
                    .ok_or_else(|| invalid(format!("{key}: Input should be a valid integer")))?,
            };
            if value < min {
                return Err(invalid(format!(
                    "{key}: Input should be greater than or equal to {min}"
                )));
            }
            if value > max {
                return Err(invalid(format!(
                    "{key}: Input should be less than or equal to {max}"
                )));
            }
            Ok(value)
        };
        Ok(Self {
            title,
            loading_messages,
            widget_code,
            i_have_seen_read_me,
            width: bounded("width", WIDTH)?,
            height: bounded("height", HEIGHT)?,
        })
    }
}

fn integer(value: &Value) -> Option<i64> {
    match value {
        Value::Number(number) => number.as_i64().or_else(|| {
            number
                .as_f64()
                .filter(|f| f.fract() == 0.0 && f.abs() < 9e15)
                .map(|f| f as i64)
        }),
        Value::String(text) => text.trim().parse().ok(),
        _ => None,
    }
}

fn string_list(params: &Value, key: &str) -> Result<Vec<String>, AgentError> {
    let invalid =
        |message: String| AgentError::Validation(format!("input invalid: {key}: {message}"));
    match params.get(key) {
        Some(Value::Array(items)) => items
            .iter()
            .map(|item| {
                item.as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| invalid("Input should be a valid string".into()))
            })
            .collect(),
        Some(_) => Err(invalid("Input should be a valid list".into())),
        None => Err(invalid("Field required".into())),
    }
}

/// The `show_widget` result (v3 verbatim): an error object when the read-me
/// was not confirmed or the SVG layout check failed, else the widget echoed
/// back with its layout check.
pub fn show_widget(input: ShowWidgetInput) -> Value {
    if !input.i_have_seen_read_me {
        return json!({
            "error": "You must call visualize_read_me before using show_widget",
            "success": false,
        });
    }
    let mut layout_check = json!({ "status": "skipped", "errors": [], "warnings": [] });
    if input.widget_code.to_lowercase().contains("<svg") {
        let mut check = check_svg_layout(&input.widget_code);
        let has_errors = check
            .get("errors")
            .and_then(Value::as_array)
            .is_some_and(|errors| !errors.is_empty());
        if has_errors {
            return json!({
                "error": "Diagram layout preflight found issues. Correct the reported geometry and call show_widget again.",
                "success": false,
                "layout_check": check,
            });
        }
        let has_warnings = check
            .get("warnings")
            .and_then(Value::as_array)
            .is_some_and(|warnings| !warnings.is_empty());
        if let Some(object) = check.as_object_mut() {
            object.insert(
                "status".into(),
                json!(if has_warnings {
                    "manual_review"
                } else {
                    "passed"
                }),
            );
        }
        layout_check = check;
    }
    let message = format!("Widget '{}' rendered successfully", input.title);
    json!({
        "success": true,
        "title": input.title,
        "width": input.width,
        "height": input.height,
        "widget_code": input.widget_code,
        "loading_messages": input.loading_messages,
        "layout_check": layout_check,
        "message": message,
    })
}

// ── SVG geometry preflight (v3 `geometry.py`) ───────────────────────────────
//
// Conservative: explicit untransformed rect nodes and absolute M/L/H/V
// connector paths. Unrecognized path commands are warnings, never proof that
// the geometry is clear.

#[derive(Debug, Clone)]
struct Rect {
    key: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}

impl Rect {
    fn right(&self) -> f64 {
        self.x + self.width
    }

    fn bottom(&self) -> f64 {
        self.y + self.height
    }

    fn contains(&self, x: f64, y: f64, tolerance: f64) -> bool {
        self.x - tolerance <= x
            && x <= self.right() + tolerance
            && self.y - tolerance <= y
            && y <= self.bottom() + tolerance
    }

    fn contains_box(&self, other: &Rect) -> bool {
        self.x <= other.x
            && self.y <= other.y
            && self.right() >= other.right()
            && self.bottom() >= other.bottom()
    }
}

#[derive(Debug, Clone)]
struct Lifeline {
    x: f64,
    y1: f64,
    y2: f64,
}

type Point = (f64, f64);
type Segment = (Point, Point);

const NODE_CLASSES: [&str; 11] = [
    "node",
    "state",
    "entity",
    "participant",
    "actor",
    "service-node",
    "er-box",
    "entity-box",
    "state-box",
    "actor-box",
    "seq-head",
];
const EDGE_CLASSES: [&str; 5] = ["edge", "connector", "transition", "relationship", "er-edge"];

/// Length of the number (v3 `_NUMBER`:
/// `[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?`) starting at `start`.
fn number_len(bytes: &[u8], start: usize) -> Option<usize> {
    let digits = |from: usize| {
        bytes[from..]
            .iter()
            .take_while(|b| b.is_ascii_digit())
            .count()
    };
    let mut i = start;
    if matches!(bytes.get(i), Some(b'+' | b'-')) {
        i += 1;
    }
    let whole = digits(i);
    if whole > 0 {
        i += whole;
        if bytes.get(i) == Some(&b'.') {
            i += 1;
            i += digits(i);
        }
    } else if bytes.get(i) == Some(&b'.') && digits(i + 1) > 0 {
        i += 1 + digits(i + 1);
    } else {
        return None;
    }
    if matches!(bytes.get(i), Some(b'e' | b'E')) {
        let mut j = i + 1;
        if matches!(bytes.get(j), Some(b'+' | b'-')) {
            j += 1;
        }
        let exponent = digits(j);
        if exponent > 0 {
            i = j + exponent;
        }
    }
    Some(i - start)
}

/// Every number in `text`, left to right (`re.findall(_NUMBER, text)`).
fn find_numbers(text: &str) -> Vec<f64> {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        match number_len(bytes, i) {
            Some(len) => {
                if let Ok(value) = text[i..i + len].parse() {
                    out.push(value);
                }
                i += len;
            }
            None => i += 1,
        }
    }
    out
}

/// The number at the start of `value` (after trimming), else `default`
/// (v3 `_number`).
fn number_attr(value: Option<&str>, default: f64) -> f64 {
    let Some(value) = value else { return default };
    let value = value.trim();
    number_len(value.as_bytes(), 0)
        .and_then(|len| value[..len].parse().ok())
        .unwrap_or(default)
}

/// Path tokens: single ASCII letters and numbers (v3 `_PATH_TOKEN`).
fn path_tokens(path: &str) -> Vec<&str> {
    let bytes = path.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i].is_ascii_alphabetic() {
            out.push(&path[i..i + 1]);
            i += 1;
        } else if let Some(len) = number_len(bytes, i) {
            out.push(&path[i..i + len]);
            i += len;
        } else {
            i += 1;
        }
    }
    out
}

fn path_segments(path: &str) -> Result<Vec<Segment>, String> {
    let tokens = path_tokens(path);
    if tokens.is_empty() {
        return Err("empty path".into());
    }
    let coordinate = |index: usize| -> Result<f64, String> {
        tokens
            .get(index)
            .and_then(|token| token.parse::<f64>().ok())
            .ok_or_else(|| "incomplete path coordinates".to_string())
    };
    let mut segments = Vec::new();
    let mut current: Option<Point> = None;
    let mut index = 0;
    while index < tokens.len() {
        let command = tokens[index];
        index += 1;
        match command {
            "M" | "L" => {
                let point = (coordinate(index)?, coordinate(index + 1)?);
                index += 2;
                if let (Some(start), "L") = (current, command) {
                    segments.push((start, point));
                }
                current = Some(point);
            }
            "H" => {
                let Some(start) = current else {
                    return Err("horizontal segment has no start point".into());
                };
                let point = (coordinate(index)?, start.1);
                index += 1;
                segments.push((start, point));
                current = Some(point);
            }
            "V" => {
                let Some(start) = current else {
                    return Err("vertical segment has no start point".into());
                };
                let point = (start.0, coordinate(index)?);
                index += 1;
                segments.push((start, point));
                current = Some(point);
            }
            other => return Err(format!("unsupported path command {other}")),
        }
        if index < tokens.len() && !tokens[index].as_bytes()[0].is_ascii_alphabetic() {
            return Err("repeated path coordinates are unsupported".into());
        }
    }
    Ok(segments)
}

fn segment_crosses_interior(segment: &Segment, node: &Rect) -> bool {
    let ((x1, y1), (x2, y2)) = *segment;
    if y1 == y2 {
        return node.y < y1
            && y1 < node.bottom()
            && x1.min(x2).max(node.x) < x1.max(x2).min(node.right());
    }
    if x1 == x2 {
        return node.x < x1
            && x1 < node.right()
            && y1.min(y2).max(node.y) < y1.max(y2).min(node.bottom());
    }
    false
}

fn endpoint_on_boundary(segment: &Segment, node: &Rect, is_start: bool) -> bool {
    let tolerance = 1.5;
    let (point, neighbor) = if is_start {
        (segment.0, segment.1)
    } else {
        (segment.1, segment.0)
    };
    let (x, y) = point;
    if !node.contains(x, y, tolerance) {
        return false;
    }
    let horizontal = (segment.0 .1 - segment.1 .1).abs() <= tolerance;
    let vertical = (segment.0 .0 - segment.1 .0).abs() <= tolerance;
    if horizontal {
        if (x - node.x).abs() <= tolerance {
            return neighbor.0 < node.x - tolerance;
        }
        if (x - node.right()).abs() <= tolerance {
            return neighbor.0 > node.right() + tolerance;
        }
    }
    if vertical {
        if (y - node.y).abs() <= tolerance {
            return neighbor.1 < node.y - tolerance;
        }
        if (y - node.bottom()).abs() <= tolerance {
            return neighbor.1 > node.bottom() + tolerance;
        }
    }
    false
}

fn point_on_box_boundary(point: Point, node: &Rect) -> bool {
    let tolerance = 1.5;
    let (x, y) = point;
    node.contains(x, y, tolerance)
        && ((x - node.x).abs() <= tolerance
            || (x - node.right()).abs() <= tolerance
            || (y - node.y).abs() <= tolerance
            || (y - node.bottom()).abs() <= tolerance)
}

fn endpoint_on_lifeline(segment: &Segment, lifeline: &Lifeline, is_start: bool) -> bool {
    let tolerance = 10.0;
    let (point, neighbor) = if is_start {
        (segment.0, segment.1)
    } else {
        (segment.1, segment.0)
    };
    let (x, y) = point;
    if (segment.0 .1 - segment.1 .1).abs() > 1.5
        || (x - lifeline.x).abs() > tolerance
        || !(lifeline.y1.min(lifeline.y2) <= y && y <= lifeline.y1.max(lifeline.y2))
    {
        return false;
    }
    if (x - lifeline.x).abs() <= 1.5 {
        return (neighbor.0 - x).abs() > 1.5;
    }
    // v3 uses the same rule for both ends.
    if x > lifeline.x {
        neighbor.0 > x
    } else {
        neighbor.0 < x
    }
}

/// v3 `_NODE_LABEL.fullmatch(class)`:
/// `(?:^|-)(?:node|state|entity|participant|actor)(?:-name)?-label$|(?:^|-)(?:er-name|head-name)$`.
/// A full match leaves room for one leading `-` only.
fn is_node_label(class: &str) -> bool {
    let body = class.strip_prefix('-').unwrap_or(class);
    if body == "er-name" || body == "head-name" {
        return true;
    }
    let Some(stem) = body.strip_suffix("-label") else {
        return false;
    };
    let stem = stem.strip_suffix("-name").unwrap_or(stem);
    ["node", "state", "entity", "participant", "actor"].contains(&stem)
}

/// v3 `_EXTERNAL_LABEL.fullmatch(class)`: `(?:^|-)(?:edge|connector|transition)-label$`.
fn is_external_label(class: &str) -> bool {
    let body = class.strip_prefix('-').unwrap_or(class);
    ["edge-label", "connector-label", "transition-label"].contains(&body)
}

/// The first `<svg …>…</svg>` in `source` (case-insensitive), else all of it.
fn svg_fragment(source: &str) -> &str {
    let lower = source.to_ascii_lowercase();
    let mut from = 0;
    while let Some(found) = lower[from..].find("<svg") {
        let start = from + found;
        let after = start + 4;
        let boundary = source[after..]
            .chars()
            .next()
            .is_none_or(|c| !(c.is_alphanumeric() || c == '_'));
        if boundary {
            let mut search = after;
            while let Some(close) = lower[search..].find("</svg") {
                let close = search + close;
                let rest = &source[close + 5..];
                let trimmed = rest.trim_start();
                if trimmed.starts_with('>') {
                    let end = close + 5 + (rest.len() - trimmed.len()) + 1;
                    return &source[start..end];
                }
                search = close + 5;
            }
            return source;
        }
        from = after;
    }
    source
}

/// `font-size\s*:\s*(NUMBER)` in a style attribute.
fn style_font_size(style: &str) -> Option<f64> {
    let mut from = 0;
    while let Some(found) = style[from..].find("font-size") {
        let start = from + found + "font-size".len();
        let rest = style[start..].trim_start();
        if let Some(rest) = rest.strip_prefix(':') {
            let rest = rest.trim_start();
            if let Some(len) = number_len(rest.as_bytes(), 0) {
                if let Ok(value) = rest[..len].parse() {
                    return Some(value);
                }
            }
        }
        from = start;
    }
    None
}

/// One SVG element, flattened from the parsed tree.
struct Element {
    tag: String,
    attributes: Vec<(String, String)>,
    in_defs: bool,
    /// All descendant text (`"".join(element.itertext())`).
    text: String,
}

impl Element {
    fn attr(&self, name: &str) -> Option<&str> {
        self.attributes
            .iter()
            .find(|(key, _)| key == name)
            .map(|(_, value)| value.as_str())
    }

    fn classes(&self) -> Vec<&str> {
        let mut out: Vec<&str> = Vec::new();
        for class in self.attr("class").unwrap_or("").split_whitespace() {
            if !out.contains(&class) {
                out.push(class);
            }
        }
        out
    }

    fn id_or(&self, fallback: impl FnOnce() -> String) -> String {
        self.attr("id").map(str::to_owned).unwrap_or_else(fallback)
    }
}

/// Parse `svg` into its root `viewBox` and every element in document order.
fn parse_svg(svg: &str) -> Result<(Option<String>, Vec<Element>), String> {
    let document = evo_office::preview::html::parse_xml(svg).map_err(|error| error.to_string())?;
    let root = document.root_element();
    let view_box = root.attribute("viewBox").map(str::to_owned);
    let elements = root
        .descendants()
        .filter(|node| node.is_element())
        .map(|node| Element {
            tag: node.tag_name().name().to_string(),
            attributes: node
                .attributes()
                .filter(|attribute| attribute.namespace().is_none())
                .map(|attribute| (attribute.name().to_string(), attribute.value().to_string()))
                .collect(),
            in_defs: node
                .ancestors()
                .skip(1)
                .any(|ancestor| ancestor.tag_name().name() == "defs"),
            text: node
                .descendants()
                .filter(|child| child.is_text())
                .filter_map(|child| child.text())
                .collect(),
        })
        .collect();
    Ok((view_box, elements))
}

/// Report overlap, connector and viewBox errors for recognizable SVG
/// geometry (v3 `check_svg_layout`). The result object has `errors`,
/// `warnings`, `nodes_checked`, `connectors_checked` and `viewBox`.
pub fn check_svg_layout(source: &str) -> Value {
    let svg = svg_fragment(source);
    let mut errors: Vec<String> = Vec::new();
    let mut warnings: Vec<String> = Vec::new();
    let (view_box_attr, elements) = match parse_svg(svg) {
        Ok(parsed) => parsed,
        Err(error) => {
            return json!({
                "errors": [format!("invalid SVG: {error}")],
                "warnings": [],
                "nodes_checked": 0,
                "connectors_checked": 0,
            })
        }
    };

    let view_values = find_numbers(view_box_attr.as_deref().unwrap_or(""));
    let view_box = if view_values.len() == 4 {
        Some(Rect {
            key: "viewBox".into(),
            x: view_values[0],
            y: view_values[1],
            width: view_values[2],
            height: view_values[3],
        })
    } else {
        errors.push("missing or invalid viewBox".into());
        None
    };

    let mut nodes: Vec<Rect> = Vec::new();
    let mut lifelines: Vec<Lifeline> = Vec::new();
    let mut connectors: Vec<(String, Vec<Segment>)> = Vec::new();
    for element in &elements {
        if element.in_defs {
            continue;
        }
        let tag = element.tag.as_str();
        let classes = element.classes();
        let attr = |name: &str| number_attr(element.attr(name), 0.0);
        if tag == "rect" && classes.iter().any(|class| NODE_CLASSES.contains(class)) {
            if element
                .attr("transform")
                .is_some_and(|transform| !transform.is_empty())
            {
                let key = element.id_or(|| (nodes.len() + 1).to_string());
                warnings.push(format!("node {key} has transform; bounds not checked"));
                continue;
            }
            let node = Rect {
                key: element.id_or(|| format!("node-{}", nodes.len() + 1)),
                x: attr("x"),
                y: attr("y"),
                width: attr("width"),
                height: attr("height"),
            };
            if node.width <= 0.0 || node.height <= 0.0 {
                errors.push(format!("node {} has non-positive dimensions", node.key));
            } else {
                nodes.push(node);
            }
        } else if tag == "path" && classes.iter().any(|class| EDGE_CLASSES.contains(class)) {
            match path_segments(element.attr("d").unwrap_or("")) {
                Err(warning) => {
                    let key = element.id_or(|| (connectors.len() + 1).to_string());
                    warnings.push(format!("connector {key}: {warning}; inspect manually"));
                }
                Ok(segments) if !segments.is_empty() => {
                    let key = element.id_or(|| format!("connector-{}", connectors.len() + 1));
                    connectors.push((key, segments));
                }
                Ok(_) => {}
            }
        } else if tag == "line" && classes.contains(&"lifeline") {
            let (x1, y1, x2, y2) = (attr("x1"), attr("y1"), attr("x2"), attr("y2"));
            if (x1 - x2).abs() <= 1.5 {
                lifelines.push(Lifeline { x: x1, y1, y2 });
            }
            if let Some(view_box) = &view_box {
                if x1.min(x2) < view_box.x
                    || x1.max(x2) > view_box.right()
                    || y1.min(y2) < view_box.y
                    || y1.max(y2) > view_box.bottom()
                {
                    errors.push("lifeline extends outside viewBox".into());
                }
            }
        } else if let (Some(view_box), true) = (
            &view_box,
            matches!(tag, "rect" | "circle" | "ellipse" | "line"),
        ) {
            let (x, y, right, bottom) = match tag {
                "rect" => {
                    let (x, y) = (attr("x"), attr("y"));
                    (x, y, x + attr("width"), y + attr("height"))
                }
                "circle" => {
                    let (cx, cy, radius) = (attr("cx"), attr("cy"), attr("r"));
                    (cx - radius, cy - radius, cx + radius, cy + radius)
                }
                "ellipse" => {
                    let (cx, cy, rx, ry) = (attr("cx"), attr("cy"), attr("rx"), attr("ry"));
                    (cx - rx, cy - ry, cx + rx, cy + ry)
                }
                _ => {
                    let (x1, y1, x2, y2) = (attr("x1"), attr("y1"), attr("x2"), attr("y2"));
                    (x1.min(x2), y1.min(y2), x1.max(x2), y1.max(y2))
                }
            };
            let stroke = number_attr(element.attr("stroke-width"), 1.0) / 2.0;
            if x - stroke < view_box.x
                || y - stroke < view_box.y
                || right + stroke > view_box.right()
                || bottom + stroke > view_box.bottom()
            {
                errors.push(format!("{tag} artwork extends outside viewBox"));
            }
        }
    }

    for (index, first) in nodes.iter().enumerate() {
        for second in &nodes[index + 1..] {
            let intersects = first.x < second.right()
                && second.x < first.right()
                && first.y < second.bottom()
                && second.y < first.bottom();
            let intentional_nesting = first.contains_box(second) || second.contains_box(first);
            if intersects && !intentional_nesting {
                errors.push(format!(
                    "node overlap: {} overlaps {}",
                    first.key, second.key
                ));
            }
        }
    }

    if let Some(view_box) = &view_box {
        for node in &nodes {
            if node.x < view_box.x
                || node.y < view_box.y
                || node.right() > view_box.right()
                || node.bottom() > view_box.bottom()
            {
                errors.push(format!("node {} extends outside viewBox", node.key));
            }
        }
    }

    for element in &elements {
        if element.tag != "text" {
            continue;
        }
        let classes = element.classes();
        // v3 takes an arbitrary member of a Python set; the first class here.
        let class_name = classes.first().copied().unwrap_or("text");
        let content = element
            .text
            .split_whitespace()
            .collect::<Vec<_>>()
            .join(" ");
        if content.is_empty() {
            continue;
        }
        let x = number_attr(element.attr("x"), 0.0);
        let baseline = number_attr(element.attr("y"), 0.0);
        let font_size = style_font_size(element.attr("style").unwrap_or(""))
            .unwrap_or_else(|| number_attr(element.attr("font-size"), 12.0));
        let text_width = content.chars().count() as f64 * font_size * 0.58;
        let left = match element.attr("text-anchor").unwrap_or("start") {
            "middle" => x - text_width / 2.0,
            "end" => x - text_width,
            _ => x,
        };
        let right = left + text_width;
        let top = baseline - font_size;
        if let Some(view_box) = &view_box {
            if left < view_box.x
                || top < view_box.y
                || right > view_box.right()
                || baseline > view_box.bottom()
            {
                errors.push(format!("{class_name} label extends outside viewBox"));
            }
        }
        if classes.iter().any(|class| is_node_label(class)) {
            let containing: Vec<&Rect> = nodes
                .iter()
                .filter(|node| node.contains(x, baseline, 0.0))
                .collect();
            if containing.is_empty() {
                errors.push(format!(
                    "{class_name} label anchor is outside every node box"
                ));
            } else if !containing.iter().any(|node| {
                left >= node.x + 6.0
                    && right <= node.right() - 6.0
                    && top >= node.y + 2.0
                    && baseline <= node.bottom() - 2.0
            }) {
                errors.push(format!(
                    "{class_name} label does not fit inside its node box"
                ));
            }
        } else if classes.iter().any(|class| is_external_label(class)) {
            if let Some(node) = nodes.iter().find(|node| {
                left < node.right() && right > node.x && top < node.bottom() && baseline > node.y
            }) {
                errors.push(format!("{class_name} label overlaps node {}", node.key));
            }
        }
    }

    for (key, segments) in &connectors {
        let first = &segments[0];
        let last = &segments[segments.len() - 1];
        let end = last.1;
        let start_nodes: Vec<&Rect> = nodes
            .iter()
            .filter(|node| endpoint_on_boundary(first, node, true))
            .collect();
        let end_nodes: Vec<&Rect> = nodes
            .iter()
            .filter(|node| endpoint_on_boundary(last, node, false))
            .collect();
        let start_on_lifeline = lifelines
            .iter()
            .any(|line| endpoint_on_lifeline(first, line, true));
        let end_on_lifeline = lifelines
            .iter()
            .any(|line| endpoint_on_lifeline(last, line, false));
        if start_nodes.is_empty() && !start_on_lifeline {
            errors.push(format!(
                "connector {key} start endpoint misses a valid source boundary or lifeline"
            ));
        }
        if end_nodes.is_empty() && !end_on_lifeline {
            let containing_end = nodes.iter().find(|node| node.contains(end.0, end.1, 0.0));
            let boundary_end = nodes.iter().find(|node| point_on_box_boundary(end, node));
            if let Some(node) = boundary_end {
                errors.push(format!(
                    "connector {key} touches node {} on a non-facing target boundary",
                    node.key
                ));
            } else if let Some(node) = containing_end {
                errors.push(format!("connector {key} ends inside node {}", node.key));
            } else {
                errors.push(format!(
                    "connector {key} end endpoint misses a valid target boundary"
                ));
            }
        }
        let allowed: Vec<&str> = start_nodes
            .iter()
            .chain(&end_nodes)
            .map(|node| node.key.as_str())
            .collect();
        if let Some(node) = nodes.iter().find(|node| {
            !allowed.contains(&node.key.as_str())
                && segments
                    .iter()
                    .any(|segment| segment_crosses_interior(segment, node))
        }) {
            errors.push(format!(
                "connector {key} crosses non-endpoint node {}",
                node.key
            ));
        }
        if let Some(view_box) = &view_box {
            let inside = |(x, y): Point| {
                view_box.x <= x
                    && x <= view_box.right()
                    && view_box.y <= y
                    && y <= view_box.bottom()
            };
            if segments.iter().any(|(a, b)| !(inside(*a) && inside(*b))) {
                errors.push(format!("connector {key} extends outside viewBox"));
            }
        }
    }

    if nodes.is_empty() && lifelines.is_empty() {
        warnings.push("no explicit node rectangles found; overlap checks are limited".into());
    }
    if connectors.is_empty() {
        warnings.push("no supported connector paths found; endpoint checks are limited".into());
    }
    let mut result = Map::new();
    result.insert("errors".into(), json!(errors));
    result.insert("warnings".into(), json!(warnings));
    result.insert("nodes_checked".into(), json!(nodes.len()));
    result.insert("connectors_checked".into(), json!(connectors.len()));
    result.insert("viewBox".into(), json!(view_box_attr));
    Value::Object(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn widget(code: &str) -> ShowWidgetInput {
        ShowWidgetInput::parse(&json!({
            "title": "test_widget",
            "loading_messages": ["Loading..."],
            "widget_code": code,
            "i_have_seen_read_me": true,
        }))
        .unwrap()
    }

    fn errors(result: &Value) -> Vec<String> {
        result["errors"]
            .as_array()
            .unwrap()
            .iter()
            .map(|e| e.as_str().unwrap().to_string())
            .collect()
    }

    fn any_error(result: &Value, needle: &str) -> bool {
        errors(result).iter().any(|e| e.contains(needle))
    }

    // ── visualize_read_me (v3 TestVisualizeReadMe) ──

    #[test]
    fn read_me_single_module() {
        let text = read_me(&["interactive".into()]);
        assert!(text.contains("Interactive Components"));
        assert!(
            text.starts_with("\n# evo Widget Design System"),
            "{}",
            &text[..40]
        );
        assert!(!text.contains("EvoFlux"));
    }

    #[test]
    fn read_me_multiple_modules() {
        let text = read_me(&["interactive".into(), "chart".into()]);
        assert!(text.contains("Interactive Components"));
        assert!(text.contains("Chart.js Integration"));
    }

    #[test]
    fn read_me_invalid_and_empty_modules() {
        let text = read_me(&["invalid".into()]);
        assert_eq!(
            text,
            "Invalid modules. Available options: interactive, chart, mockup, art, diagram, gallery\n\nRequested: invalid"
        );
        assert!(read_me(&[]).contains("Invalid modules"));
    }

    #[test]
    fn read_me_gallery_module() {
        let text = read_me(&["gallery".into()]);
        assert!(text.contains("Widget Gallery"));
        assert!(text.contains("Metric Dashboard"));
    }

    #[test]
    fn guidelines_skip_unknown_and_repeat_modules() {
        let once = get_guidelines(&["chart".into()]);
        let repeated = get_guidelines(&["chart".into(), "bogus".into(), "chart".into()]);
        assert_eq!(once, repeated);
        assert_eq!(once.matches("Chart.js Integration").count(), 1);
    }

    // ── show_widget (v3 TestShowWidget) ──

    #[test]
    fn basic_widget() {
        let result = show_widget(widget("<div>Test</div>"));
        assert_eq!(result["success"], true);
        assert_eq!(result["title"], "test_widget");
        assert_eq!(result["width"], 800);
        assert_eq!(result["height"], 600);
        assert_eq!(result["loading_messages"], json!(["Loading..."]));
        assert_eq!(
            result["layout_check"],
            json!({"status": "skipped", "errors": [], "warnings": []})
        );
        assert_eq!(
            result["message"],
            "Widget 'test_widget' rendered successfully"
        );
    }

    #[test]
    fn requires_read_me() {
        let mut input = widget("<div>Test</div>");
        input.i_have_seen_read_me = false;
        let result = show_widget(input);
        assert_eq!(
            result,
            json!({"error": "You must call visualize_read_me before using show_widget", "success": false})
        );
    }

    #[test]
    fn custom_dimensions_and_bounds() {
        let base = json!({"title": "w", "loading_messages": ["a"], "widget_code": "<p/>", "i_have_seen_read_me": true});
        let with = |extra: Value| {
            let mut params = base.clone();
            params
                .as_object_mut()
                .unwrap()
                .extend(extra.as_object().unwrap().clone());
            ShowWidgetInput::parse(&params)
        };
        let input = with(json!({"width": 1000, "height": 500})).unwrap();
        let result = show_widget(input);
        assert_eq!(result["width"], 1000);
        assert_eq!(result["height"], 500);
        for (extra, needle) in [
            (
                json!({"width": 199}),
                "width: Input should be greater than or equal to 200",
            ),
            (
                json!({"width": 1201}),
                "width: Input should be less than or equal to 1200",
            ),
            (
                json!({"height": 149}),
                "height: Input should be greater than or equal to 150",
            ),
            (
                json!({"height": 901}),
                "height: Input should be less than or equal to 900",
            ),
        ] {
            let error = with(extra).unwrap_err().to_string();
            assert!(error.contains(needle), "{error}");
        }
        assert!(ShowWidgetInput::parse(&json!({"title": "w"})).is_err());
        assert!(with(json!({"loading_messages": "nope"})).is_err());
    }

    #[test]
    fn html_content_preserved() {
        let html = "<div class='test'><p>Hello World</p></div>";
        assert_eq!(show_widget(widget(html))["widget_code"], html);
    }

    #[test]
    fn svg_widgets_get_the_layout_check() {
        let good = r#"<div><SVG viewBox="0 0 240 100" xmlns="http://www.w3.org/2000/svg">
          <path class="edge" d="M80 40 H160"/>
          <rect class="node" x="20" y="20" width="60" height="40"/>
          <rect class="node" x="160" y="20" width="60" height="40"/>
        </SVG></div>"#;
        let result = show_widget(widget(good));
        assert_eq!(result["success"], true, "{result}");
        assert_eq!(result["layout_check"]["status"], "passed");
        assert_eq!(result["layout_check"]["nodes_checked"], 2);

        let no_edges = r#"<svg viewBox="0 0 100 100"><rect class="node" x="10" y="10" width="20" height="20"/></svg>"#;
        let result = show_widget(widget(no_edges));
        assert_eq!(result["layout_check"]["status"], "manual_review");

        let bad = r#"<svg viewBox="0 0 100 100"><circle cx="150" cy="50" r="4"/></svg>"#;
        let result = show_widget(widget(bad));
        assert_eq!(result["success"], false);
        assert_eq!(
            result["error"],
            "Diagram layout preflight found issues. Correct the reported geometry and call show_widget again."
        );
        assert!(any_error(
            &result["layout_check"],
            "circle artwork extends outside viewBox"
        ));
    }

    #[tokio::test]
    async fn tools_return_json_text() {
        let tool = create_show_widget_tool();
        let result = tool
            .execute(
                "id",
                json!({"title": "t", "loading_messages": ["x"], "widget_code": "<b>hi</b>", "i_have_seen_read_me": true}),
                CancellationToken::new(),
                Arc::new(|_| {}),
            )
            .await
            .unwrap();
        let TextContentOrImage::Text(text) = &result.content[0] else {
            panic!()
        };
        let parsed: Value = serde_json::from_str(&text.text).unwrap();
        assert_eq!(parsed, result.details);
        assert_eq!(parsed["success"], true);

        let tool = create_read_me_tool();
        let result = tool
            .execute(
                "id",
                json!({"modules": ["art"]}),
                CancellationToken::new(),
                Arc::new(|_| {}),
            )
            .await
            .unwrap();
        let TextContentOrImage::Text(text) = &result.content[0] else {
            panic!()
        };
        assert!(text.text.contains("SVG Illustration Guide"));
    }

    // ── geometry (v3 tests/skills/test_diagram_layout.py) ──

    #[test]
    fn accepts_separated_nodes_with_boundary_to_boundary_connector() {
        let svg = r#"<svg viewBox="0 0 240 100" xmlns="http://www.w3.org/2000/svg">
          <path class="edge" d="M80 40 H160"/>
          <rect class="node" x="20" y="20" width="60" height="40"/>
          <rect class="node" x="160" y="20" width="60" height="40"/>
        </svg>"#;
        assert!(errors(&check_svg_layout(svg)).is_empty());
    }

    #[test]
    fn reports_overlapping_nodes_and_connector_ending_inside_target() {
        let svg = r#"<svg viewBox="0 0 240 100" xmlns="http://www.w3.org/2000/svg">
          <path class="edge" d="M80 40 H180"/>
          <rect class="node" x="20" y="20" width="70" height="40"/>
          <rect class="node" x="80" y="20" width="60" height="40"/>
          <rect class="node" x="160" y="20" width="60" height="40"/>
        </svg>"#;
        let result = check_svg_layout(svg);
        assert!(any_error(&result, "overlap"));
        assert!(any_error(&result, "endpoint"));
    }

    #[test]
    fn reports_artwork_outside_viewbox_and_route_through_unrelated_node() {
        let svg = r#"<svg viewBox="0 0 240 100" xmlns="http://www.w3.org/2000/svg">
          <path class="edge" d="M60 40 H180"/>
          <rect class="node" x="20" y="20" width="40" height="40"/>
          <rect class="node" x="100" y="20" width="40" height="40"/>
          <rect class="node" x="180" y="20" width="40" height="40"/>
          <circle cx="250" cy="50" r="4"/>
        </svg>"#;
        let result = check_svg_layout(svg);
        assert!(any_error(&result, "viewBox"));
        assert!(any_error(&result, "crosses"));
    }

    #[test]
    fn rejects_connector_that_touches_the_wrong_target_side() {
        let svg = r#"<svg viewBox="0 0 240 100" xmlns="http://www.w3.org/2000/svg">
          <path class="edge" d="M80 20 H180"/>
          <rect class="node" x="20" y="20" width="60" height="40"/>
          <rect class="node" x="160" y="20" width="60" height="40"/>
        </svg>"#;
        assert!(any_error(&check_svg_layout(svg), "target boundary"));
    }

    #[test]
    fn reports_node_label_that_does_not_fit_inside_its_box() {
        let svg = r#"<svg viewBox="0 0 180 100" xmlns="http://www.w3.org/2000/svg">
          <rect class="node" x="20" y="20" width="96" height="40"/>
          <text class="node-label" x="68" y="44" text-anchor="middle">Long database replication endpoint</text>
        </svg>"#;
        let result = check_svg_layout(svg);
        assert!(errors(&result)
            .iter()
            .any(|e| e.contains("label") && e.contains("node")));
    }

    #[test]
    fn accepts_sequence_edges_attached_to_lifelines() {
        let svg = r#"<svg viewBox="0 0 240 120" xmlns="http://www.w3.org/2000/svg">
          <line class="lifeline" x1="80" y1="40" x2="80" y2="110"/>
          <line class="lifeline" x1="160" y1="40" x2="160" y2="110"/>
          <path class="edge" d="M80 60 H152"/>
          <rect class="node" x="40" y="10" width="80" height="30"/>
          <rect class="node" x="120" y="10" width="80" height="30"/>
        </svg>"#;
        assert!(errors(&check_svg_layout(svg)).is_empty());
    }

    #[test]
    fn checks_sequence_participant_headers_and_labels() {
        let svg = r#"<svg viewBox="0 0 240 120" xmlns="http://www.w3.org/2000/svg">
          <rect class="seq-head" x="30" y="10" width="80" height="30"/>
          <text class="head-name" x="70" y="29" text-anchor="middle">Buyer</text>
          <rect class="seq-head" x="130" y="10" width="80" height="30"/>
          <text class="head-name" x="170" y="29" text-anchor="middle">Checkout</text>
          <line class="lifeline" x1="70" y1="40" x2="70" y2="110"/>
          <line class="lifeline" x1="170" y1="40" x2="170" y2="110"/>
          <path class="edge" d="M70 60 H170"/>
        </svg>"#;
        let result = check_svg_layout(svg);
        assert!(errors(&result).is_empty(), "{result}");
        assert_eq!(result["nodes_checked"], 2);
        assert_eq!(result["connectors_checked"], 1);
    }

    #[test]
    fn recognizes_er_boxes_and_crow_foot_edges() {
        let svg = r#"<svg viewBox="0 0 220 80" xmlns="http://www.w3.org/2000/svg">
          <path class="er-edge" d="M80 40 H140"/>
          <rect class="er-box" x="20" y="20" width="60" height="40"/>
          <rect class="er-box" x="140" y="20" width="60" height="40"/>
        </svg>"#;
        let result = check_svg_layout(svg);
        assert!(errors(&result).is_empty(), "{result}");
        assert_eq!(result["nodes_checked"], 2);
        assert_eq!(result["connectors_checked"], 1);
    }

    // ── geometry details beyond the v3 tests ──

    #[test]
    fn invalid_svg_and_missing_viewbox() {
        let result = check_svg_layout("<svg><rect></svg>");
        assert!(errors(&result)[0].starts_with("invalid SVG: "), "{result}");
        assert_eq!(result["nodes_checked"], 0);
        assert!(result.get("viewBox").is_none());

        let result =
            check_svg_layout(r#"<svg><rect class="node" x="0" y="0" width="0" height="5"/></svg>"#);
        assert!(any_error(&result, "missing or invalid viewBox"));
        assert!(any_error(
            &result,
            "node node-1 has non-positive dimensions"
        ));
        assert_eq!(result["viewBox"], Value::Null);
    }

    #[test]
    fn path_parsing_matches_v3() {
        assert_eq!(path_segments("M0 0 L10 0 V5 H-2.5").unwrap().len(), 3);
        assert_eq!(
            path_segments("M1e1,2 L.5 3").unwrap(),
            vec![((10.0, 2.0), (0.5, 3.0))]
        );
        assert_eq!(path_segments("").unwrap_err(), "empty path");
        assert_eq!(
            path_segments("M0 0 C1 1 2 2 3 3").unwrap_err(),
            "unsupported path command C"
        );
        assert_eq!(
            path_segments("H5").unwrap_err(),
            "horizontal segment has no start point"
        );
        assert_eq!(
            path_segments("M0 0 V").unwrap_err(),
            "incomplete path coordinates"
        );
        assert_eq!(
            path_segments("M0 0 L1 1 2 2").unwrap_err(),
            "repeated path coordinates are unsupported"
        );
        let svg =
            r#"<svg viewBox="0 0 100 100"><path id="e1" class="edge" d="M0 0 Q 1 1 2 2"/></svg>"#;
        let result = check_svg_layout(svg);
        assert_eq!(
            result["warnings"][0],
            "connector e1: unsupported path command Q; inspect manually"
        );
    }

    #[test]
    fn defs_transforms_and_labels() {
        let svg = r#"<svg viewBox="0 0 200 100" xmlns="http://www.w3.org/2000/svg">
          <defs><rect class="node" x="-50" y="-50" width="10" height="10"/></defs>
          <rect id="t" class="node" x="0" y="0" width="10" height="10" transform="translate(5 5)"/>
          <rect class="node" x="20" y="20" width="60" height="40"/>
          <rect class="node" x="120" y="20" width="60" height="40"/>
          <text class="edge-label" x="30" y="40">over</text>
          <text class="node-label" x="150" y="45" style="font-size: 8px">ok</text>
          <text class="node-label" x="5" y="95">out</text>
        </svg>"#;
        let result = check_svg_layout(svg);
        assert_eq!(
            result["warnings"][0],
            "node t has transform; bounds not checked"
        );
        assert_eq!(result["nodes_checked"], 2);
        assert!(any_error(&result, "edge-label label overlaps node node-1"));
        assert!(any_error(
            &result,
            "node-label label anchor is outside every node box"
        ));
        assert_eq!(errors(&result).len(), 2, "{result}");
    }

    #[test]
    fn label_class_patterns() {
        for class in [
            "node-label",
            "state-name-label",
            "-actor-label",
            "er-name",
            "-head-name",
            "head-name",
        ] {
            assert!(is_node_label(class), "{class}");
        }
        for class in [
            "nodelabel",
            "node-label-x",
            "label",
            "x-actor-label",
            "seq-head-name",
            "node-name-name-label",
        ] {
            assert!(!is_node_label(class), "{class}");
        }
        assert!(is_external_label("edge-label") && is_external_label("-transition-label"));
        assert!(!is_external_label("edgelabel") && !is_external_label("a-edge-label"));
    }

    #[test]
    fn svg_fragment_extraction() {
        assert_eq!(
            svg_fragment("a <SVG x='1'>b</svg >c"),
            "<SVG x='1'>b</svg >"
        );
        assert_eq!(svg_fragment("<svgx></svgx><svg>y</svg>"), "<svg>y</svg>");
        assert_eq!(svg_fragment("<svg>open"), "<svg>open");
        assert_eq!(number_attr(Some(" 12px"), 0.0), 12.0);
        assert_eq!(number_attr(Some("auto"), 3.0), 3.0);
        assert_eq!(style_font_size("color: red; font-size : 9.5px"), Some(9.5));
    }
}
