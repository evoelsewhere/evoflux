# AIM commands (draft — staging, not yet auto-discovered)

Four slash commands for the AIM pipeline, authored per `documents/research/aim-framework.md` §4.1 (AIM-0). Format matches `app/services/commands.py` (frontmatter `description:` + a body that becomes the message sent to the session, with `$ARGUMENTS` substituted for whatever the user typed after the command name).

**Status: not yet a live discovery root.** `commands.py` only walks four roots today — project `.EvoFlux/commands/` and `.opencode/commands/`, global `{EVOFLUX_CONFIG_DIR}/commands/` and `~/.config/opencode/commands/` — none of which is `seed/commands/`. Until the AIM-1 rulebook-install mechanism or AIM-2 mode wiring copies these in, they're inert here.

**To try them today**, copy this directory's `.md` files (flat, no subfolder — so the command id matches the name exactly, e.g. `aim-inventory.md` → `/aim-inventory`) into either a coding workspace's `.EvoFlux/commands/` or the global `{EVOFLUX_CONFIG_DIR}/commands/`.
