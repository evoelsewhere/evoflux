//! Port of app/api/schemas/commands.py (response models; the request body is
//! validated by the area crate to reproduce FastAPI's 422 details).

use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CommandSummary {
    pub name: String,
    pub description: String,
    pub source: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CommandListResponse {
    pub commands: Vec<CommandSummary>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CommandRenderResponse {
    pub name: String,
    pub content: String,
}
