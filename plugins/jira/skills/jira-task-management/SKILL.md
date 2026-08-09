---
name: jira-task-management
description: "Browse, search, and inspect Jira Data Center projects and issues through the installed EvoFlux Jira plugin. Use for Jira issue lookups, JQL searches, project discovery, and permission checks."
---

# Jira Task Management

Use the Jira MCP tools contributed by this plugin. Their host-qualified names vary
by installation, so select tools by their stable suffixes:

- `connection_test`
- `projects_list`
- `project_permissions_get`
- `issues_search`
- `issue_get`

## Workflow

1. If the requested connection or project is unclear, call `connection_test` and
   then `projects_list` before searching.
2. Use structured `issues_search` filters for ordinary requests. Use raw `jql`
   only when the user supplies JQL or the structured filters cannot express the
   request. Raw JQL and structured filters are mutually exclusive.
3. Keep results bounded. Start with the default page size and paginate only when
   the user needs more results.
4. Call `issue_get` before making detailed claims about an issue. Search rows are
   summaries and may omit fields.
5. Cite issue keys and clearly distinguish Jira data from inference.

## Configuration

- Credentials are configured in **Plugins → evoflux-jira → Credentials**. Never
  ask the user to paste a PAT into chat.
- `scripts/configure.py` is a local-development fallback relative to the
  **Plugin root** shown in the activation wrapper, not relative to this Skill
  directory. Read it with the ordinary file-read tool only when the user asks
  to inspect or use the fallback flow.

## Safety and stop conditions

- This version is read-only. Do not claim that it can create, edit, transition,
  or comment on issues.
- Never request, print, or echo a PAT in chat. Connections are configured by the
  host and injected only into this plugin's MCP process.
- On `authentication_failed`, stop and ask the user to repair the saved
  connection. On `permission_denied`, do not retry with broader queries.
- Do not invent projects, issue fields, totals, or permissions when Jira returns
  incomplete data.
