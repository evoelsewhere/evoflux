# Jira Task Management Reference Plugin - Functional Spec

> Status: PROPOSED v2
> Date: 2026-07-29
> Plugin ID: `com.evoflux.jira`
> Platform architecture: [EvoFlux Plugin Platform - Jira Reference Plugin Plan](plugin-platform-jira-reference-plan.md)
> Research source: audited Jira Data Center 10.3.23 / FI2.0 documentation in [`jira-docs`](../../../jira-docs/README.md)

---

## 1. Purpose

This document defines the product behavior and Jira-specific contract for the first full EvoFlux plugin. It does not define new Jira models, routes, services or React components in core.

Jira is delivered as a normal `.evoplugin` package containing:

- a sandboxed Task Management UI;
- a Jira backend running as a managed MCP stdio subprocess;
- a Jira Data Center connection type with URL and PAT/API key;
- optional read-only agent tools;
- tests and sanitized fixtures derived from `jira-docs`.

Core sees only generic plugin contributions, connections, storage, secrets and backend operations. Jira-specific implementation lives under `plugins/jira`.

---

## 2. Product scope

### Goals

- Configure one or more Jira Data Center connections with display name, full base URL and PAT/API key.
- Preserve Jira context paths such as `/jira9`.
- Verify server and authenticated-user identity before saving a connection.
- Browse projects visible to the authenticated user.
- Provide My open work, Recently updated and Project issues views.
- Search through structured filters or advanced JQL.
- Show a paginated issue list and detailed issue view.
- Create issues from project/issue-type metadata.
- Edit only fields allowed by the current issue's `editmeta`.
- Execute only transitions currently advertised by Jira.
- Read and add comments.
- Surface actionable permission, validation, network and upstream errors.
- Prove that the generic Plugin Platform supports real UI, secrets, network logic, dynamic forms and controlled writes.

### Non-goals for Jira v1

- Jira Cloud email/token authentication or OAuth.
- Browser session-cookie authentication.
- Offline issue replication, webhooks or a local issue mirror.
- Attachments, worklog mutation, watchers, voters or bulk mutation.
- Agile board/sprint mutation.
- Jira project/system administration.
- FI2.0 JSPA scraping, PowerBI, cost, HR or resource-allocation pages.
- Automatic agent writes.
- Rally support inside this plugin.

Rally is a separate future plugin generated from the same skeleton. A shared Task Hub is deferred until plugin-to-plugin contracts exist.

---

## 3. Evidence from `jira-docs`

| Design fact | Required behavior | Source |
|---|---|---|
| The audited server is Jira Data Center 10.3.23 and accepts PAT Bearer auth. | V1 sends `Authorization: Bearer <PAT>` and verifies with `/myself`. | [Overview](../../../jira-docs/00-overview.md) |
| The base URL includes `/jira9`. | URL joining must preserve the complete configured context path. | [README](../../../jira-docs/README.md) |
| OPNEXT88 has 35,865 issues. | Every list is bounded and paginated; default page size is 50. | [Issue CRUD](../../../jira-docs/01-issue-crud.md) |
| A full issue can exceed 100 KB because of hundreds of custom fields. | Every issue/search request sends an explicit `fields` list. | [Issue CRUD](../../../jira-docs/01-issue-crud.md) |
| Legacy `createmeta?projectKeys=...` returns 404. | Use the two-step project/issue-type createmeta endpoints. | [Issue CRUD](../../../jira-docs/01-issue-crud.md) |
| Required fields differ across Bug, Task and Sub-task. | Create UI is metadata-driven, not a hard-coded universal form. | [Issue CRUD](../../../jira-docs/01-issue-crud.md) |
| Editability depends on current issue state and screen configuration. | Load `editmeta` when edit begins and revalidate before submit. | [Issue CRUD](../../../jira-docs/01-issue-crud.md) |
| Transitions vary by issue and workflow. | Always fetch transitions for the current issue and write by transition ID. | [Workflow catalog](../../../jira-docs/03-workflow-status-priority-resolution.md) |
| The instance exposes 406 fields and plugin-defined schemas. | Use a schema adapter registry and preserve unknown optional values. | [Field catalog](../../../jira-docs/02-fields-catalog.md) |
| Permissions differ per project. | Query `mypermissions?projectKey=<key>`; global/default context is insufficient. | [Permissions](../../../jira-docs/09-permissions-and-limits.md) |
| Some permission failures return an HTML firewall banner. | Classify using operation, content type and permission context, not HTML text alone. | [Permissions correction](../../../jira-docs/09-permissions-and-limits.md) |
| Assignee autocomplete URL can be supplied in metadata. | Validate it remains on the configured Jira origin before use. | [Issue CRUD](../../../jira-docs/01-issue-crud.md) |
| FI2.0 PMO is custom JSPA HTML, not REST. | Keep it outside this plugin version. | [FI2.0 menu](../../../jira-docs/10-fi20-project-management-menu.md) |

Jira create uses `POST /rest/api/2/issue` (singular).

---

## 4. Plugin contributions

The Jira manifest contributes:

```text
workbench
  id: tasks
  dynamic tool id: plugin:com.evoflux.jira/tasks
  title: Task Management
  modes: forge, coding, aim
  single instance: true

settings
  id: settings
  title: Jira

connectionTypes
  id: jira
  fields: name, base_url, api_key, verify_ssl
  testOperation: connection_test

commands
  Jira: Open Task Management

agentTools (opt-in)
  jira_issue_search
  jira_issue_get
```

The Plugin Platform owns install, permissions, connection persistence, secret references, iframe lifecycle and Workbench tab registration. Jira owns all task UI and Jira REST behavior.

---

## 5. User experience

### 5.1 First run

Jira appears in Plugin Center's bundled **Available** catalog. The user:

1. opens Plugins from the sidebar;
2. selects Jira Task Management;
3. reviews permissions;
4. installs and enables the plugin;
5. selects **Configure connection**;
6. enters connection name, Jira URL, PAT and TLS preference;
7. runs Test & save;
8. opens Task Management.

The Jira plugin must not be silently auto-enabled or receive a token before permission approval.

### 5.2 Connection form

Fields:

1. **Connection name**: required; defaults from hostname but remains editable.
2. **Jira URL**: full origin plus optional context path, for example `https://insight.fsoft.com.vn/jira9`.
3. **API key / PAT**: required on create, write-only and blank when editing a saved connection.
4. **Verify TLS**: enabled by default; disabling is an advanced action with a warning.

Successful verification displays:

- server title and Jira version;
- authenticated display name;
- visible-project count or a warning if no project is visible.

It does not display or return the PAT.

### 5.3 Task Management panel

The UI must adapt to Workbench widths from 360-1080 px, maximized desktop and mobile.

```text
Compact dock                            Wide/maximized
┌──────────────────────────┐           ┌──────────────────┬──────────────────┐
│ Jira ▾  OPNEXT88 ▾   ⚙  │           │ Jira ▾ OPNEXT ▾ │ OPNEXT88-276574  │
│ My open | Recent | All   │           │ Search / filters │ Summary          │
│ Search  Filter           │           │──────────────────│ Status/Priority  │
│──────────────────────────│           │ Key    Summary   │ Description      │
│ OPNEXT88-…  Summary      │           │ ...    ...       │ Fields           │
│ OPNEXT88-…  Summary      │           │ ...    ...       │ Activity/Comment │
│                          │           │ Page 1 of N      │ [Transition] ... │
└──────────────────────────┘           └──────────────────┴──────────────────┘
Open issue -> detail with Back
```

- Compact/mobile uses one navigation level at a time.
- Wide/maximized uses list-detail split view.
- Filters run on the server; never filter only the current page client-side.
- Selected connection/project/view uses plugin storage, not host localStorage.
- Secret values never enter plugin storage.
- **Open in Jira** uses the host `openExternal` bridge method.

### 5.4 Journeys

#### J1 - Browse

Choose connection, project and view. The initial view is My open work. Results show key, summary, type, status, priority, assignee and updated time.

#### J2 - Search

Structured filters cover text, status, assignee, priority and issue type. Advanced mode accepts raw JQL. The two modes are mutually exclusive. Jira validation errors appear next to the query without discarding it.

#### J3 - Inspect

Opening a row loads bounded core fields, links, comments and a capped recent changelog. Resolved custom-field names appear under Advanced; unknown values do not break the detail page.

#### J4 - Create

Choose project and issue type, load all create-metadata pages, render supported controls, validate required fields and submit provider-native values. An unsupported required schema blocks submission and names the field ID/type explicitly.

#### J5 - Edit

Opening edit mode loads current `editmeta`. Submit only changed fields. Preserve the draft if Jira rejects the update.

#### J6 - Transition

Load current transitions and render any transition-specific required fields. Confirm transitions to a done category or transitions requiring resolution. Refresh detail, transitions, edit metadata and visible issue lists after success.

#### J7 - Comment

Add a Jira wiki-markup comment. Preserve the draft on failure and refresh comments/activity on success.

---

## 6. Connection behavior

### 6.1 Validation sequence

`connection_test` performs:

1. normalize and validate URL;
2. `GET /rest/api/2/serverInfo`;
3. `GET /rest/api/2/myself`;
4. probe visible projects;
5. return a sanitized identity/capability payload.

The host persists public connection metadata and secret references only after verification succeeds.

### 6.2 URL rules

- Allow `https` and optionally `http` with a visible warning.
- Reject embedded username/password, query strings and fragments.
- Preserve the configured path prefix.
- Normalize trailing slash without removing context path.
- Do not follow redirects to a different origin while carrying authorization.
- Metadata-provided links/autocomplete URLs must match the configured origin.

### 6.3 Multiple connections

- Each connection has a host-generated UUID and independent secret reference.
- Updating public fields without a new PAT preserves the existing secret.
- Empty secret input is not interpreted as delete.
- Deleting a connection deletes only its plugin-managed secret reference.
- Disabling the plugin preserves connections unless the user chooses Remove plugin and data.

---

## 7. Backend operation contract

Jira backend operations are MCP tools callable through the Plugin Platform bridge. Reserved lifecycle operations are not listed here.

### Connections and discovery

```text
connection_test
projects_list
project_permissions_get
issue_types_list
field_catalog_refresh
```

### Issues

```text
issues_search
issue_get
create_schema_get
issue_create
edit_schema_get
issue_update
transitions_list
issue_transition
comments_list
comment_add
```

Each operation uses strict Pydantic input/output models with unknown upstream Jira payload fields ignored or retained only in a bounded provider-data field.

### Page response

```json
{
  "items": [],
  "page": {
    "start_at": 0,
    "page_size": 50,
    "total": 35865,
    "is_last": false
  }
}
```

### Error envelope

```json
{
  "error": {
    "code": "permission_denied",
    "message": "You do not have permission to transition this issue.",
    "retryable": false,
    "field_errors": {},
    "request_id": "..."
  }
}
```

Stable codes:

```text
invalid_connection
authentication_failed
permission_denied
validation_failed
not_found
unsupported_capability
endpoint_unavailable
rate_limited
upstream_unavailable
network_error
tls_error
malformed_upstream_response
```

Raw HTML error pages, headers and tokens never cross into the plugin UI.

---

## 8. Jira endpoint map

### Connection and discovery

| Operation | Jira endpoint |
|---|---|
| Server identity | `GET /rest/api/2/serverInfo` |
| Authenticated user | `GET /rest/api/2/myself` |
| Visible projects | `GET /rest/api/2/project` |
| Field catalog | `GET /rest/api/2/field` |
| Per-project permissions | `GET /rest/api/2/mypermissions?projectKey={key}` |

### Issue work

| Operation | Jira endpoint | Notes |
|---|---|---|
| Search | `GET /rest/api/2/search` | Send `fields`, `startAt` and `maxResults`. |
| Detail | `GET /rest/api/2/issue/{key}` | Bounded fields; changelog on demand. |
| Issue types | `GET /rest/api/2/issue/createmeta/{projectKey}/issuetypes` | Paginate. |
| Create schema | `GET /rest/api/2/issue/createmeta/{projectKey}/issuetypes/{issueTypeId}` | Paginate all fields. |
| Create | `POST /rest/api/2/issue` | Singular endpoint. |
| Edit schema | `GET /rest/api/2/issue/{key}/editmeta` | Current issue context. |
| Update | `PUT /rest/api/2/issue/{key}` | Changed fields only. |
| Transitions | `GET /rest/api/2/issue/{key}/transitions?expand=transitions.fields` | Dynamic per issue. |
| Transition | `POST /rest/api/2/issue/{key}/transitions` | Never automatically retry. |
| Comments | `GET/POST /rest/api/2/issue/{key}/comment` | Paginate reads. |
| User lookup | Metadata-provided URL or supported user endpoint | Same-origin validation. |

### Suggested caches

All caches are scoped by plugin connection:

- field catalog: 24 hours, manually refreshable;
- projects and issue types: 5 minutes;
- create schema: 5 minutes by project/type;
- per-project permissions: 60 seconds;
- edit schema and transitions: active issue only;
- search/detail: plugin UI query cache, invalidated after writes.

---

## 9. Dynamic field handling

Use a registry keyed by Jira `schema.type`, `schema.items` and optional custom type.

| Jira metadata | UI control |
|---|---|
| string / textarea | text input / textarea |
| number | numeric input |
| date / datetime | date / datetime picker |
| option / priority / issue type | select with `allowedValues` |
| array of option/component/version | multi-select |
| user | async same-origin user combobox |
| project | fixed project display/select |
| parent | issue reference picker |
| labels | token input |

Rules:

- Required metadata is authoritative.
- Unknown optional schemas appear read-only or under Advanced.
- Unknown required schemas block submission.
- Do not hard-code FI2.0 field IDs in generic form logic.
- Preserve original IDs when display values are normalized, including duplicate resolution names.
- `state_category` is display/filter data only; transitions always write by transition ID.

---

## 10. HTTP and safety behavior

The Jira backend must:

- use only the connection secret delivered by the host;
- send PAT only in the Authorization header;
- keep TLS verification enabled by default;
- set bounded connect/read timeouts;
- cap response/body excerpts retained for errors;
- inspect status/content type before JSON parsing;
- never log authorization headers, PATs, full comments or raw issue payloads;
- retry bounded idempotent reads on 429/502/503/504;
- honor `Retry-After` when valid;
- never automatically retry create/update/transition/comment operations;
- always paginate large list endpoints;
- use an explicit field set for search/detail;
- sanitize upstream messages before returning them to UI.

Permission data is a UI hint, not an authorization guarantee. Jira remains authoritative at mutation time.

---

## 11. Agent tools

Initial opt-in tools:

```text
plugin_com_evoflux_jira_jira_issue_search
plugin_com_evoflux_jira_jira_issue_get
```

They return bounded structured output and never expose the PAT.

Write tools are deferred. When introduced, every write requires host confirmation showing:

- Jira connection;
- project/issue key;
- exact changed fields, transition or comment preview;
- effect classification.

UI-only backend operations are not callable by agents unless explicitly added to `agentTools` in a reviewed manifest update.

---

## 12. Source layout

```text
plugins/jira/
├── manifest.json
├── README.md
├── LICENSE
├── ui/
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── plugin.ts
│   │   ├── views/TasksView.tsx
│   │   ├── views/SettingsView.tsx
│   │   ├── components/TaskList.tsx
│   │   ├── components/TaskDetail.tsx
│   │   ├── components/DynamicIssueForm.tsx
│   │   └── queries.ts
│   └── tests/
├── backend/
│   ├── pyproject.toml
│   └── src/evoflux_jira/
│       ├── __main__.py
│       ├── plugin.py
│       ├── client.py
│       ├── models.py
│       ├── fields.py
│       ├── mapper.py
│       └── errors.py
└── tests/
    ├── fixtures/
    ├── contract/
    └── security/
```

No Jira source belongs under `app/services`, `app/api/routes`, `app/models` or statically imported web components.

---

## 13. Testing strategy

CI uses sanitized fixtures derived from `jira-docs`; it never calls the real Jira instance.

### Backend tests

- URL joining preserves `/jira9`.
- Embedded credentials/query/fragment are rejected.
- PAT is sent as Bearer and absent from logs/errors.
- Cross-origin redirects do not receive authorization.
- JSON and HTML 401/403/404 responses map to stable errors.
- Search uses bounded fields and paginates 35,865 results safely.
- Create metadata uses the two-step endpoint and collects all pages.
- Unknown custom fields do not break common mapping.
- Transition writes use IDs and are not retried.
- Per-project permissions include `projectKey`.
- Backend process restart rehydrates only its own connection secrets.

### UI tests

- First-run and saved-secret blank behavior.
- Structured filter/JQL exclusivity.
- Loading, empty, pagination and error states.
- Bug, Task and Sub-task dynamic required fields.
- Unsupported required custom field blocks create.
- Permission-disabled and upstream-denied transitions.
- Draft preservation after failed writes.
- Compact, wide, maximized and mobile layouts.
- UI works with iframe network access disabled.

### Plugin contract tests

- Manifest and permissions validate.
- Jira bundle installs through the generic installer.
- Dynamic Workbench contribution opens without a core Jira import.
- Disable closes the Jira tab and stops its backend.
- Re-enable restores connections without exposing secrets.
- Broken update rolls back to the previous plugin version.
- Uninstall with data removal deletes only Jira-owned storage/secrets.

---

## 14. Jira delivery slices

These slices start after the corresponding Plugin Platform host/SDK milestones are available.

### J0 - Fixtures and transport

- Convert audited responses into sanitized fixtures.
- Implement URL normalization, PAT auth, response/error parsing and pagination.
- Define operation input/output models.

Exit: backend contract tests pass without a live Jira server.

### J1 - Connection and discovery

- Jira connection contribution.
- `serverInfo`, `myself`, projects, field catalog and permissions.
- Settings UI and Test & save behavior.

Exit: multiple Jira connections verify and persist through generic host storage/secrets.

### J2 - Read-only Task Management

- Workbench UI contribution.
- Default views, filters, advanced JQL and paginated task list.
- Issue detail, links, comments and recent history.
- Read-only opt-in agent tools.

Exit: user can reliably find and inspect issues in a 35k+ issue project.

### J3 - Controlled writes

- Metadata-driven create.
- `editmeta`-driven updates.
- Dynamic transitions and transition fields.
- Comment creation.
- Confirmations, draft retention and query invalidation.

Exit: create/edit/transition/comment journeys pass against fixtures and a staging Jira project.

### J4 - Hardening and reference quality

- Accessibility and responsive polish.
- Rate-limit/retry UX and diagnostics.
- 406-field performance tests.
- Contributor-quality README explaining how Jira uses every Plugin SDK surface.
- Rebuild/install/update/rollback/uninstall E2E.

Exit: Jira can serve as the canonical fullstack plugin example.

### Later Jira plugin versions

1. Attachments and worklogs.
2. Agile board/sprint views and controlled mutations.
3. Confirmed agent write tools.
4. Optional FI2.0 companion plugin, not mixed into the standard Jira package.

---

## 15. Acceptance criteria

- [ ] Jira ships as `com.evoflux.jira-<version>.evoplugin` through the generic packer.
- [ ] Plugin Center installs and enables it without a core code branch for Jira.
- [ ] Task Management appears as `plugin:com.evoflux.jira/tasks` in Forge, Coding and AIM Workbench launchers.
- [ ] The panel works at 360 px, wide dock, maximized desktop and mobile sizes.
- [ ] Multiple URL/PAT connections are isolated and secrets are write-only.
- [ ] Test & save verifies server and user identity before persistence.
- [ ] Context paths such as `/jira9` are preserved.
- [ ] Search/detail always use explicit fields and safe pagination.
- [ ] Create uses the two-step metadata endpoint and all metadata pages.
- [ ] Unsupported required fields block submission explicitly.
- [ ] Edit fields and transitions come from the current issue metadata.
- [ ] Create, edit, transition and comment work when Jira permits them.
- [ ] HTML/JSON upstream failures become sanitized actionable errors.
- [ ] Disabling/uninstalling Jira does not restart or destabilize EvoFlux.
- [ ] No core file contains Jira endpoints, field IDs, service logic or UI imports.
- [ ] A clean rebuild of the Jira source passes the same contract as a third-party plugin.

---

## 16. Recommended defaults

| Question | Default |
|---|---|
| Auto-install Jira? | No. Show it in bundled Available plugins and require install/permission approval. |
| Connections | Support several from J1. |
| Authentication | Jira Data Center PAT/Bearer only in v1. |
| Default view | My open work. |
| Raw JQL | Available behind Advanced mode. |
| Default project | Remember per connection in plugin storage; never hard-code OPNEXT88. |
| Local issue cache | No durable mirror. Use bounded runtime/UI caches. |
| Agent writes | Deferred until human write flows and confirmation contracts are stable. |
| FI2.0 | Separate future companion plugin because it is instance-specific HTML/JSPA. |
| Rally | Separate plugin using the same skeleton and SDK. |

---

## 17. Definition of done

The Jira reference plugin is done when a clean EvoFlux installation can install its `.evoplugin` package, approve permissions, configure URL/PAT, browse a large Jira Data Center project and perform metadata-valid create/edit/transition/comment operations without exposing credentials.

It must remain correct across projects with different issue types, fields, workflows and permissions. Most importantly, the same source must build and install through the public Plugin SDK and generic host with no Jira-specific change in EvoFlux core.