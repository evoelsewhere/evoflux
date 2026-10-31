//! Port of app/api/schemas/snippets.py.

use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SnippetSummary {
    pub name: String,
    pub description: String,
    pub source: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SnippetListResponse {
    pub snippets: Vec<SnippetSummary>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SnippetRenderResponse {
    pub name: String,
    pub content: String,
}
