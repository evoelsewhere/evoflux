# Multi-source import

EvoFlux can import conversations and supported local agent resources from
Claude.ai, Claude Code, ChatGPT, Codex, Cursor, and generic supported files.
Open **Settings → Import**, choose a source, and select an export file or data
directory through the native file picker. The Python sidecar reads the selected
local path; exports are not uploaded to a remote service.

The scan presents detected items, counts, warnings, and conflicts before the
user starts an import. New items can be imported or skipped. Existing conflicts
can be re-imported in place; users can select several conflicts and apply the
same action together. Re-import updates the matched session or resource rather
than creating a duplicate. Credentials and API keys are not imported.

ChatGPT conversations use their provider conversation ID, so renaming one does
not create a second import target. A unique legacy match from older title/time
imports is reused; ambiguous matches are skipped for review. If the native file
picker is unavailable, enter the local export path in the import page.

Auto-sync runs only while EvoFlux is open. It periodically scans discovered
sources and automatically imports new sessions, skills, and agents. Existing
conflicts and MCP configuration remain under manual review. When a scan imports
items, fails, or finds items for review, the app sends a notification that
opens Settings → Import. Unchanged scans stay quiet.

Each new import job records per-item outcomes and local undo data. The Previous
imports list can undo a journaled job while keeping its history entry. Undo
removes newly created targets or restores the prior content of re-imported
targets only when their current fingerprint still matches the import. If an
item was edited or removed afterward, Undo leaves it untouched and reports a
partial result. Open **Details** in history to inspect item-level outcomes and
reasons after navigating away or reloading. The Undo confirmation explains
that unchanged EvoFlux targets may be removed or restored, later edits remain,
and source files are not changed. Jobs created before the journal migration
remain visible but cannot be undone.

Imported sessions store their source and import time in `chat_sessions`. The
source label appears in the session row and conversation bar so imported chats
remain distinguishable from native EvoFlux sessions. Imported memory facts also
retain source metadata.

Claude Code imports skills from `~/.claude/skills`; Codex imports shared skills
from the sibling `~/.agents/skills` directory. Imported skills are written to
the configured `SKILLS_DIR`, the same root used by skill discovery, with safe
YAML frontmatter. The preview can search item names and details, filter by
kind, and paginate large exports. The **Settings → Skills** list keeps its
filter visible while scrolling, and the sidebar search opens the command
palette for finding older sessions and matching messages.
Same-name Skills discovered in another local source are flagged for review. The
preview offers **Keep both (EvoFlux copy)**, which writes a distinctly named
copy into EvoFlux's Skill directory and leaves the provider's file untouched.
Auto-sync leaves these conflicts for manual review.

The primary implementation lives in `app/api/routes/import_route.py`,
`app/services/import_service.py`, `app/services/importers/`, and
`web/src/routes/settings.import.tsx`. Per-item undo records are stored in
`import_job_items`, and imported sessions keep a stable source item identity in
`chat_sessions`. Session source metadata is returned by the session API schema
in `app/api/schemas/sessions.py` and rendered by the shared `SessionRow` and
`WorkbenchBar` components.
