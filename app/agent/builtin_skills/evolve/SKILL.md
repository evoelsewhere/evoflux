---
name: evolve
description: "Use this skill when a repeated need should become durable platform capability rather than one more manual pass: a new Agent Skill, an Agent Plugin, an MCP server attachment, an agent configuration change, or a change to EvoFlux itself. It selects the correct extension surface, checks for an existing extension first, and hands off to the owning workflow. Do not use it to perform ordinary task work, and do not treat it as permission to bypass trust, permission, or review boundaries."
---

# Turn a repeated need into durable capability

Extension is a deliberate act, not a reflex. Notice the signal, confirm nothing
already covers it, choose the surface that owns the behavior, then hand off to
the workflow that owns that surface. This skill routes; it does not implement.
Do not load bundled references when this skill activates.

## Notice the signal

Raise extension as an option when one of these holds, and say which one:

- The same command or tool sequence has been repeated three or more times.
- The user has corrected the same behavior more than once.
- Durable project knowledge was learned that a future session will need.
- An external system must be reachable and no configured tool reaches it.
- A capability is missing from the agent rather than from the task.

A single occurrence is not a signal. Neither is a preference the user has not
repeated. Propose; do not silently build.

## Choose the surface

| Need | Surface | Owning workflow |
|---|---|---|
| Persist how to do something, loaded on demand | Agent Skill | `skill-installer`, with `skill-creator` for its content |
| Package skills, an MCP server, and credentials for reuse or distribution | Agent Plugin | `plugin-development` |
| Reach an external system through a configured server | MCP server | `mcp-installer` |
| Change one agent's model, prompt, tools, skills, or MCP attachment | Agent configuration | `self-healing` |
| Intercept the agent loop in host process code | Legacy Python hook plugin | `plugin-installer` |
| Change the product itself | EvoFlux repository change | the repository's EASD workflow and `coding-*` skills |

Two rules decide most cases. Knowledge that shapes how work is done belongs in
a Skill. Executable reach into a system belongs in an MCP server or a plugin.
Reserve a repository change for behavior that must hold for every user, not for
one project's convenience.

## Check before creating

List what already exists on the relevant surface — installed skills, plugins,
configured MCP servers, the agent's own configuration — before proposing a new
one. Improving an existing extension beats adding a near-duplicate that
competes with it for activation.

Scope it to the narrowest surface that solves the need. A project skill under
the repository's own skills directory is the right home for project-specific
knowledge; a user-level extension is for behavior the user wants everywhere.

## Boundaries this skill does not move

Extension never widens trust. A new extension is subject to the same
permission, sandbox, workspace-authorization, and untrusted-content rules as
everything else, and a newly installed plugin or MCP server stays disabled
until the user reviews its commands, hosts, environment fields, and declared
capabilities.

Never write credentials into a skill body, a plugin package, or a repository
file. Never install from a URL or package the user did not ask for. Never
present an extension as active before the user has enabled it.

A change to EvoFlux itself is ordinary product work: it follows the
repository's specification, review, and verification contract, and does not
become exempt because an agent proposed it.

## Hand off

State the signal, the chosen surface, why the alternatives lose, and the
narrowest scope that works. Then invoke the owning workflow from the table and
let it do the building. Return to the user with what was created, where it
lives, and what they must enable or review.
