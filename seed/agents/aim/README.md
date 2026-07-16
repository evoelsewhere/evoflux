# AIM roster (draft — not yet wired into a runtime mode)

These seven blueprints (`aim-lead` + six members) are the core, stack-agnostic AIM team, authored per `documents/research/aim-framework.md` §3.10. They follow the exact blueprint format the Forge and Coding rosters use (`app/agent/loader.py:parse_agent_md` / `AgentConfig`), so they load correctly once something points at this directory.

**Status: content-only (AIM-0).** There is no `mode: aim` yet — `ChatSession.mode` and the loader don't recognize `"aim"` as a team mode until AIM-2 ships. Until then these files aren't installed into any `AGENTS_DIR` automatically; a rulebook can still overlay per-stack skills onto them once the rulebook-install mechanism (AIM-1) exists.

Unlike the Forge/Coding rosters, none of these names have a built-in system prompt in `app/agent/builtin_prompts.py` — the full prompt lives in each file's body.
