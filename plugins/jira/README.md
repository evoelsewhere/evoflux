# EvoFlux Jira reference plugin

This is the first end-to-end reference package for EvoFlux's portable Agent
Plugins platform. It follows Agent Plugins 1.0 and contributes one Skill plus a
stdio MCP server. Jira-specific code stays inside this directory; core contains
no Jira routes, models, services, or React imports.

## Current slice

The current plugin platform milestone supports portable Skills and MCP. This
reference plugin therefore implements the read-only Jira Data Center slice:

- connection verification through `serverInfo`, `myself`, and visible projects;
- visible-project listing and project-scoped permission discovery;
- bounded, explicit-field JQL search;
- bounded issue detail;
- PAT Bearer authentication, preserved context paths such as `/jira9`, blocked
  redirects, bounded retries for idempotent reads, and sanitized errors.

Credentials are host-mediated through the Plugin Center. The Jira URL, PAT,
and TLS preference are stored in a mode-`0600` credential file under the
installation-scoped `PLUGIN_DATA` directory, outside the portable package.
EvoFlux injects them only into this plugin's MCP process as `JIRA_URL`,
`JIRA_API_TOKEN`, and `JIRA_VERIFY_SSL`; credential values are never returned
by the API or displayed after saving.

## Configure in Plugin Center

Open **Plugins**, choose **Credentials** on the Jira card, enter the Jira URL
and PAT, then save. The MCP runtime refreshes automatically. Use the
`connection_test` tool to verify the connection and permissions.

The runtime also appears under **Settings → MCP servers** as
`evoflux-jira / jira` with a `plugin` badge. It is read-only on that page because
its lifecycle belongs to Plugin Center. Loading the bundled
`jira-task-management` Skill automatically grants the Jira MCP tools from the
same installation for that run; alternatively, select the runtime in an agent's
**MCP servers** field for a persistent explicit grant.

## Configure a development connection from the CLI

Find the installation ID with `evoflux plugin list`, derive its plugin-data
directory from the configured EvoFlux data root, then run:

```bash
python plugins/jira/scripts/configure.py \
  --data-dir <EVOFLUX_DATA_DIR>/agent-plugins/data/<installation-id> \
  --url https://jira.example.com/jira9
```

This file-based flow remains a local-development fallback. The token is read
with `getpass`; it is not placed in shell history. Disable TLS
verification only for a controlled development server with `--no-verify-ssl`.

## Package lifecycle

```bash
evoflux plugin inspect plugins/jira
evoflux plugin pack plugins/jira --output dist/evoflux-jira-0.1.2.evoplugin
evoflux plugin install dist/evoflux-jira-0.1.2.evoplugin
evoflux plugin list
```

Tool names are namespaced by the installation ID. The bundled Skill grants its
same-installation tools and selects them by stable suffix. The package declares
the server `webbridge-safe`, so these read-only Jira operations remain available
in a WebBridge conversation without introducing a competing browser backend.

## Tests

```bash
uv run pytest --no-cov -q tests/plugin_platform/test_jira_reference_plugin.py
```

The suite uses a local sanitized Jira fixture server. It never calls a real Jira
instance and never contains a real token.
