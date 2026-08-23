# Agent Plugins compatible-client submission packet

This packet prepares an EvoFlux entry for the Agent Plugins compatible-clients list. It is not authorization to submit upstream, and it must not be used until every release gate below is complete.

## Submission status

**Prepared, not ready to submit.** The implementation and repository evidence exist, but the upstream contribution must point to a public EvoFlux release that contains the feature and to public product-usage evidence. Do not claim an unreleased branch or local development build as an available compatible client.

Target upstream repository: [`agentplugins/agent-plugins-site`](https://github.com/agentplugins/agent-plugins-site). Follow its current [`CONTRIBUTING.md`](https://github.com/agentplugins/agent-plugins-site/blob/main/CONTRIBUTING.md) at submission time because the site and specification are evolving.

## Proposed client record

Confirm the field shape against the upstream `lib/compatible-clients.ts` type before copying this candidate:

```ts
{
  name: "EvoFlux",
  description:
    "Local-first desktop agent harness with portable Agent Skills and MCP plugin runtimes.",
  homepageUrl: "https://github.com/evoelsewhere/evoflux",
  instructionsUrl:
    "https://github.com/evoelsewhere/evoflux/blob/main/docs/guides/agent-plugins.md",
  sourceUrl: "https://github.com/evoelsewhere/evoflux",
  logo: {
    lightSrc: "/images/logos/evoflux/evoflux-app-icon.png",
    darkSrc: "/images/logos/evoflux/evoflux-app-icon.png",
    alt: "EvoFlux logo",
  },
  supports: {
    skills: true,
    mcp: {
      transports: ["stdio", "streamable-http"],
    },
  },
}
```

Do not claim SSE execution. EvoFlux recognizes legacy SSE declarations for diagnostics but skips them at runtime.

## Capability evidence

| Claim | Public implementation evidence | Automated evidence |
|---|---|---|
| Agent Skills | [`app/plugin_platform/skills.py`](../../app/plugin_platform/skills.py) merges enabled plugin Skills into the catalog with explicit precedence. [`app/agent/skills/discovery.py`](../../app/agent/skills/discovery.py) enforces the package Skill boundary. | [`tests/plugin_platform/test_platform.py`](../../tests/plugin_platform/test_platform.py) covers plugin-vs-built-in and project-vs-plugin precedence, discovery, disablement, and package failure boundaries. |
| MCP stdio | [`app/plugin_platform/runtime.py`](../../app/plugin_platform/runtime.py) adapts valid plugin stdio declarations into an installation-scoped manager with `PLUGIN_ROOT`, `PLUGIN_DATA`, and credential mediation. | [`tests/plugin_platform/test_platform.py`](../../tests/plugin_platform/test_platform.py) covers stdio adaptation, placeholder expansion, environment handling, runtime status, and failure isolation. |
| MCP Streamable HTTP | [`app/plugin_platform/runtime.py`](../../app/plugin_platform/runtime.py) builds HTTP server configuration with literal headers, disabled redirects, and no credential injection. | [`tests/plugin_platform/test_platform.py`](../../tests/plugin_platform/test_platform.py) covers Streamable HTTP adaptation and ensures legacy SSE is not started. |
| Package lifecycle | [`app/plugin_platform/validator.py`](../../app/plugin_platform/validator.py), [`app/plugin_platform/installer.py`](../../app/plugin_platform/installer.py), and [`app/api/routes/plugins.py`](../../app/api/routes/plugins.py) implement inspect, import/link, pack, update, enable/disable, and uninstall. | [`tests/plugin_platform/test_platform.py`](../../tests/plugin_platform/test_platform.py) and [`tests/api/test_plugin_routes.py`](../../tests/api/test_plugin_routes.py) cover the lifecycle and adversarial package handling. |
| Trust review | [`app/plugin_platform/trust.py`](../../app/plugin_platform/trust.py) statically extracts commands, remote hosts, environment-field names, and capabilities. [`web/src/components/PluginTrustReviewDialog.tsx`](../../web/src/components/PluginTrustReviewDialog.tsx) gates UI enablement. | Backend tests prove new installations default to disabled and secret/header/environment values are excluded from the disclosure. |
| Public setup | [Use Agent Plugins with EvoFlux](../guides/agent-plugins.md) documents desktop and CLI setup, enable review, credentials, and runtime verification. | Verify all links against the release tag before submitting. |

The minimum implementation ancestry for a qualifying release includes:

- `8af9032f` — canonical reverse-domain EvoFlux extension namespaces with legacy aliases;
- `2673a20d` — install trust review and default-disabled UI/API flows;
- `2698e9c6` — default-disabled CLI install/link flow with explicit automation opt-in;
- the commit containing this submission packet and public setup guide.

## Supported product surfaces

Claim only released desktop builds for macOS, Windows, and Linux. The browser UI is a frontend surface of the local desktop sidecar, not a separately hosted compatible client. Record the first qualifying EvoFlux version and release URL here before submission:

| Item | Required value |
|---|---|
| First compatible release | `TBD` |
| Release/tag URL | `TBD` |
| Release notes mentioning Agent Plugins | `TBD` |
| Public Plugin Center usage image or video | `TBD` |
| Date verified on macOS | `TBD` |
| Date verified on Windows | `TBD` |
| Date verified on Linux | `TBD` |

## Logo assets and provenance

Use the official square EvoFlux app icon from [`web/src/assets/brand/evoflux-app-icon.png`](../../web/src/assets/brand/evoflux-app-icon.png). Its public repository history includes brand update commit `a503bd991474f7bb1f06c8b97449a5124f040a1c`. The vector source is [`web/src/assets/brand/logo.svg`](../../web/src/assets/brand/logo.svg).

For the upstream PR:

1. Create `public/images/logos/evoflux/` in the Agent Plugins site repository.
2. Copy the official 512×512 PNG as `evoflux-app-icon.png`; do not redraw, recolor, or fetch a third-party copy.
3. Use the same self-contained dark-background icon for light and dark site themes unless upstream maintainers request separate exports.
4. Mention the source repository path and provenance commit in the PR description.

## Release gates

- [ ] A public EvoFlux release contains the capability commits and this guide.
- [ ] Release notes explicitly state Agent Skills plus MCP stdio and Streamable HTTP support.
- [ ] The setup URL resolves without authentication and matches the released UI/CLI.
- [ ] Public product evidence shows Plugin Center importing a package, displaying trust review, enabling it, discovering its Skill, and showing its MCP server.
- [ ] macOS, Windows, and Linux release artifacts complete the documented smoke flow, or the record narrows its platform claim.
- [ ] The official logo is copied from this repository with provenance recorded.
- [ ] The upstream record claims only `skills`, `stdio`, and `streamable-http`.
- [ ] The upstream change is a focused compatible-client PR with no unrelated site changes.
- [ ] `pnpm build` succeeds in the current Agent Plugins site checkout.
- [ ] Links, spelling, logo rendering, and responsive client-card layout are checked locally.

## Suggested upstream PR evidence

Include the qualifying release URL, setup-guide URL, source repository, capability evidence table, supported desktop surfaces, logo provenance, and one public product-usage link in the PR body. State explicitly that EvoFlux validates but does not execute legacy SSE plugin declarations. If any gate remains `TBD`, defer the PR rather than weakening the evidence.
