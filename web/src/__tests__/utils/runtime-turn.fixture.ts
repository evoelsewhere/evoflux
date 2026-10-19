import type { MessageResponse } from '@/api/types'

// Real GET /api/team/{sid}/history payload slice for the seeded runtime turn
// (session 8468b3eb-f6a6-467f-b851-41c31ec874f5) - captured verbatim, including the
// API arrival order: all eight messages share one created_at, and the replace_id
// replace (call_rt2) is delivered BEFORE the block_id create (call_rt1).
// Null/absent optional fields are cast at the bottom.

export const runtimeTurnMessages = [
  {
    "id": "01f2287c-ccea-4a07-8e2a-1f7c4838f2e7",
    "role": "tool",
    "content": "{\"success\": true, \"block_count\": 2, \"types\": [\"layout\", \"custom\"], \"block_id\": \"launch-plan\", \"pushed\": true}",
    "tool_calls": null,
    "tool_call_id": "call_rt1",
    "name": "ui_block",
    "is_summary": false,
    "created_at": "2026-10-14T00:30:40.865362Z"
  },
  {
    "id": "08d54c20-69d4-40d4-9a2b-893274f05594",
    "role": "assistant",
    "content": null,
    "tool_calls": [
      {
        "id": "call_rt2",
        "type": "function",
        "function": {
          "name": "ui_block",
          "arguments": "{\"title\": \"Launch plan\", \"replace_id\": \"launch-plan\", \"blocks\": [{\"type\": \"layout\", \"orientation\": \"columns\", \"sections\": [{\"title\": \"Milestones\", \"children\": [{\"type\": \"steps\", \"title\": \"Roadmap\", \"steps\": [{\"title\": \"Contract sign-off\", \"status\": \"done\"}, {\"title\": \"Catalog build\", \"status\": \"done\"}, {\"title\": \"Hardening\", \"status\": \"active\"}]}]}, {\"title\": \"Tasks\", \"children\": [{\"type\": \"checklist\", \"title\": \"This sprint\", \"items\": [{\"label\": \"Review PRs\", \"checked\": true}, {\"label\": \"Ship catalog\", \"checked\": true}, {\"label\": \"Security pass\"}, {\"label\": \"Publish changelog\", \"detail\": \"runtime-intelligence entry\"}]}]}]}]}"
        }
      }
    ],
    "tool_call_id": null,
    "name": null,
    "is_summary": false,
    "created_at": "2026-10-14T00:30:40.865362Z"
  },
  {
    "id": "30ecab9f-a94d-45fa-81ec-a75930b3763a",
    "role": "assistant",
    "content": "Here is the current launch plan, laid out for review:\n\n| Milestone | Owner | Effort | Status |\n|---|---|---:|---|\n| Wireframes | Ada | 3 | Done |\n| API contract | Bo | 5 | In progress |\n| Sidecar auth | Chi | 8 | In progress |\n| Web catalog | Duy | 5 | Done |\n| Sandbox hardening | Em | 8 | Backlog |\n| Docs pass | Fa | 3 | Backlog |\n| Perf pass | Giang | 5 | Backlog |\n| Release cut | Han | 2 | Backlog |\n\nI have also pinned a living plan block below â€” I will update it in place as the plan changes.",
    "tool_calls": null,
    "tool_call_id": null,
    "name": null,
    "is_summary": false,
    "created_at": "2026-10-14T00:30:40.865362Z"
  },
  {
    "id": "77bc1e50-59f7-4bd1-8106-c7216f254c30",
    "role": "assistant",
    "content": "Catalog is done and hardening started â€” updating the plan in place:",
    "tool_calls": null,
    "tool_call_id": null,
    "name": null,
    "is_summary": false,
    "created_at": "2026-10-14T00:30:40.865362Z"
  },
  {
    "id": "887e1a67-dc7c-43c4-b353-24a3d86ec06b",
    "role": "tool",
    "content": "{\"success\": true, \"block_count\": 1, \"types\": [\"layout\"], \"replace_id\": \"launch-plan\", \"pushed\": true}",
    "tool_calls": null,
    "tool_call_id": "call_rt2",
    "name": "ui_block",
    "is_summary": false,
    "created_at": "2026-10-14T00:30:40.865362Z"
  },
  {
    "id": "9950d831-92b1-47b4-b3b9-0f7199a8f381",
    "role": "assistant",
    "content": null,
    "tool_calls": [
      {
        "id": "call_rt1",
        "type": "function",
        "function": {
          "name": "ui_block",
          "arguments": "{\"title\": \"Launch plan\", \"block_id\": \"launch-plan\", \"blocks\": [{\"type\": \"layout\", \"orientation\": \"columns\", \"sections\": [{\"title\": \"Milestones\", \"children\": [{\"type\": \"steps\", \"title\": \"Roadmap\", \"steps\": [{\"title\": \"Contract sign-off\", \"status\": \"done\"}, {\"title\": \"Catalog build\", \"status\": \"active\"}, {\"title\": \"Hardening\", \"status\": \"pending\"}]}]}, {\"title\": \"Tasks\", \"children\": [{\"type\": \"checklist\", \"title\": \"This sprint\", \"items\": [{\"label\": \"Review PRs\", \"checked\": true}, {\"label\": \"Ship catalog\", \"detail\": \"ui-block-types + dispatch\"}, {\"label\": \"Security pass\"}]}]}]}, {\"type\": \"custom\", \"title\": \"Burn-up sketch\", \"html\": \"<div style=\\\"font-family: system-ui; padding: 12px; color: var(--color-text-primary, #e6edf3)\\\"><h3 style=\\\"margin: 0 0 8px\\\">Week 1-4 burn-up</h3><svg width=\\\"100%\\\" height=\\\"90\\\" viewBox=\\\"0 0 320 90\\\"><polyline points=\\\"10,80 90,62 170,40 310,12\\\" fill=\\\"none\\\" stroke=\\\"var(--color-accent, #4f9cff)\\\" stroke-width=\\\"3\\\"/><text x=\\\"12\\\" y=\\\"88\\\" font-size=\\\"9\\\" fill=\\\"currentColor\\\">w1</text><text x=\\\"300\\\" y=\\\"10\\\" font-size=\\\"9\\\" fill=\\\"currentColor\\\">w4</text></svg><p style=\\\"margin: 6px 0 0; font-size: 12px; opacity: .8\\\">Agent-authored HTML, sandboxed, themed.</p></div>\", \"height\": 200}]}"
        }
      }
    ],
    "tool_call_id": null,
    "name": null,
    "is_summary": false,
    "created_at": "2026-10-14T00:30:40.865362Z"
  },
  {
    "id": "b002fe63-40a3-4672-a63c-ec1c571c6fdd",
    "role": "assistant",
    "content": "Done â€” same block, updated in place: hardening is now active and the changelog task is on the board.",
    "tool_calls": null,
    "tool_call_id": null,
    "name": null,
    "is_summary": false,
    "created_at": "2026-10-14T00:30:40.865362Z"
  },
  {
    "id": "bfb4af21-902e-4191-a5da-bf127232771d",
    "role": "user",
    "content": "Show me the launch plan runtime demo â€” then update the plan live.",
    "tool_calls": null,
    "tool_call_id": null,
    "name": null,
    "is_summary": false,
    "created_at": "2026-10-14T00:30:40.865362Z"
  }
] as unknown as MessageResponse[]
