# Agent configuration contract

Read the target file before editing. Only these frontmatter fields are valid for
this workflow:

| Field | Contract |
| --- | --- |
| `model` | Exact registered `provider:model` identifier |
| `fallback_model` | Exact registered `provider:model` identifier |
| `thinking_level` | A level advertised by the selected model |
| `tools` | Extra exact names from the current tool registry |
| `tools_opt_out` | Exclusions from code-owned mode/tier tools only |
| `skills` | Optional exact discovered skill metadata; bodies are not preloaded |
| `mcp` | Exact configured MCP server names for bulk attachment |
| `responses_api` | Boolean provider transport override |

The prompt body below frontmatter may be changed only when the user explicitly
requests behavior or tone. Preserve existing language and add the smallest
testable instruction.

## Invariants

- Keep exactly one lead; never change `role` as a convenience.
- Keep `model` and `fallback_model` in registered `provider:model` form.
- Never copy example model or tool names without checking the runtime catalog.
- Do not put implicit lifecycle/team tools into `tools`; runtime injects them.
- Do not add a skill to `skills` merely because it was installed. Add metadata
  only when the user explicitly wants this agent assignment.
- Do not edit secrets or `.env`. When a provider credential is required,
  inspect only configured/unconfigured status and tell the user which supported
  credential flow to complete.

## Reload semantics

Existing agent-file edits are detected and applied on the affected agent's next
turn without interrupting an in-flight turn. New or removed agent files alter
team shape and may require runtime restart. A skill body is read on its next
fresh activation and does not rewrite instructions already visible in the
current conversation.
