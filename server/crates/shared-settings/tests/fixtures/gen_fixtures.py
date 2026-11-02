"""Generate the Python differential fixtures for evoflux-shared-settings.

Run from the repository root:
``uv run python server/crates/shared-settings/tests/fixtures/gen_fixtures.py``.

``load_cases.json``: a ``settings.yaml`` text, what ``load_runtime_settings_report``
makes of it (the file ``save_runtime_settings`` would write and the ignored
fields) or the ``ValueError`` it raises. ``section_cases.json``: a JSON body
validated by one section model (``model_dump(mode="json")`` or pydantic's
errors), the shape the Settings routes answer 422 with.
"""

import json
import pathlib
import tempfile

import yaml
from pydantic import ValidationError

from app.core import runtime_settings as rs

HERE = pathlib.Path(__file__).parent

LOAD_CASES = [
    "",
    "{}\n",
    "# nothing\n",
    "- a list\n",
    "just text\n",
    "a: [1, 2\n",
    "42\n",
    "unknown_section: {a: 1}\ngit:\n  prune_on_fetch: false\n",
    "git:\n  network_timeout_seconds: 5\n  max_diff_bytes: 1.5\n  prune_on_fetch: maybe\n  allow_force_push: 'YES'\n",
    "git:\n  network_timeout_seconds: '12'\n  max_diff_bytes: '70000'\n  default_pull_strategy: rebase\n",
    "git:\n  network_timeout_seconds: true\n  max_diff_bytes: 2.0e+6\n",
    "git: 3\n",
    "git: null\n",
    "git: []\n",
    "context:\n  summary_trigger_tokens: 60000.0\n  keep_recent_turns: 0\n  summary_max_tokens: null\n",
    "context:\n  summary_trigger_tokens: 100\n  keep_recent_turns: 11\n  tool_result_offload_chars: '3000'\n",
    "context:\n  summary_trigger_tokens: yes\n",
    "dream:\n  model: nocolon\n  enabled: true\n",
    "dream:\n  model: 'anthropic:claude'\n  schedule: '*/5 * * * *'\n",
    "dream:\n  model: 5\n",
    "title_generation:\n  enabled: off\n  model: 'x:y'\n",
    "memory_extraction:\n  enabled: no\n  min_assistant_messages: '4'\n  every_n_messages: 2.5\n  max_input_chars: -1\n",
    "memory_vector:\n  enabled: on\n  backend: sqlite\n  dim: 384\n  embedding_model: m\n  index_path: /tmp/x\n",
    "server:\n  host: 0.0.0.0\n  port: '8080'\n  access_key: secret\n",
    "server:\n  port: 99999999999999999999999\n",
    "providers:\n  openai:\n    visible_models: [gpt-4o, o3]\n  anthropic: {}\n",
    "providers:\n  openai:\n    visible_models: [1, gpt]\ngit:\n  prune_on_fetch: 2\n",
    "providers:\n  openai: 3\n",
    "providers: [a]\n",
    "providers:\n  1:\n    visible_models: [a]\n",
    "code_reviews:\n  request_timeout_seconds: 1\n  retry_attempts: 6\n  retry_backoff_seconds: 0\n  max_concurrent_repositories: 0\n  max_pages_per_repository: 21\n  allow_mutations: 'false'\n",
    "browser:\n  allowed_domains: [a.com, b.com]\n  blocked_domains: []\n  allow_evaluate: 0\n  allow_cookie_values: 1\n",
    "browser:\n  allowed_domains: a.com\n",
    "webbridge:\n  enabled: false\n  allowed_domains: [x.com]\n  audit_log_size: '50'\n  sharing:\n    default: block\n    max_artifact_bytes: 0\n  interactions:\n    max_per_minute: 601\n",
    "webbridge:\n  sharing: 7\n  interactions: {allow_background_triggers: true}\n",
    "computer_app:\n  enabled: true\n  permission: allow\n  allowed_apps: [code.exe]\n",
    "computer_app:\n  permission: deny\n",
    "import_auto_sync:\n  enabled: true\n  scan_interval_seconds: 10\n",
    "import_auto_sync:\n  scan_interval_seconds: 3600\n  notify_new_items: false\n",
    "conductor:\n  enabled: true\n  url: 'https://conductor.example.com/'\n  enrollment_token: tok\n  sync_interval_seconds: 30\n  member_primary_role: admin\n  collection_level: L1\n",
    "conductor:\n  url: 'ftp://x'\n  enabled: true\n",
    "conductor:\n  url: 'https://user:pw@example.com'\n",
    "conductor:\n  url: '  http://Example.com:8443//  '\n",
    "conductor:\n  url: 'https://example.com/path'\n",
    "conductor:\n  url: 'https://example.com?q=1'\n",
    "conductor:\n  member_primary_role: owner\n  heartbeat_interval_seconds: 10\n",
    "team_spawn:\n  work: auto\n  coding: true\n",
    "follow_up:\n  delivery: steer\n",
    "follow_up:\n  delivery: later\n",
    "background_tasks:\n  wake_idle: n\n",
    "response_style:\n  style: simple\n",
    "response_style:\n  style: 'off'\n",
    "git:\n  max_diff_bytes: 1\ncontext:\n  keep_recent_turns: 99\nfollow_up:\n  delivery: x\n",
    "git:\n  max_diff_bytes: 64000\n  network_timeout_seconds: 1800\n",
    "git:\n  max_diff_bytes: '  70000  '\n",
    "git:\n  network_timeout_seconds: .inf\n",
    "git:\n  network_timeout_seconds: .nan\n",
    "git:\n  network_timeout_seconds: '1e2'\n",
    "git:\n  max_diff_bytes: 70_000\n",
    "git:\n  max_diff_bytes: 2024-01-01\n",
    "title_generation:\n  model: 2024-01-01\n",
    "title_generation:\n  model: ''\n",
    "dream:\n  model: ''\n",
    "dream:\n  schedule: null\n",
    "server:\n  access_key: null\n  host: ''\n",
    "webbridge:\n  allowed_domains: [a.com, 3]\n",
    "context:\n  keep_recent_tool_batches: 0\n  keep_recent_turns: 10\n",
    "memory_vector:\n  dim: '384'\n  dim2: x\n",
    "title_generation:\n  enabled: 'True'\ndream:\n  enabled: 'on'\n",
    "title_generation:\n  enabled: 'tRuE'\n",
    "title_generation:\n  enabled: 'y'\ndream:\n  enabled: '1'\nmemory_extraction:\n  enabled: 'f'\n",
    "title_generation:\n  enabled: 1.0\ndream:\n  enabled: 0.5\n",
    "server:\n  port: 8080.0\n",
    "server:\n  port: '8080.0'\n",
    "server:\n  port: ' 8080'\n",
    "server:\n  port: '+8080'\n",
    "server:\n  port: '8_080'\n",
    "code_reviews:\n  retry_backoff_seconds: ' 1.5 '\n",
    "code_reviews:\n  retry_backoff_seconds: '1_0.5'\n",
    "code_reviews:\n  retry_backoff_seconds: 'inf'\n",
    "code_reviews:\n  request_timeout_seconds: '3'\n  retry_backoff_seconds: 10\n",
    "providers:\n  openai:\n    visible_models: []\n    extra: 1\n",
    "providers: null\n",
    "providers:\n  openai: null\n",
]

SECTIONS = {
    "title_generation": rs.TitleGenerationSettings,
    "dream": rs.DreamSettings,
    "memory_extraction": rs.MemoryExtractionSettings,
    "git": rs.GitSettings,
    "context": rs.ContextSettings,
    "code_reviews": rs.CodeReviewSettings,
    "webbridge": rs.WebBridgeSettings,
    "computer_app": rs.ComputerAppSettings,
    "import_auto_sync": rs.ImportAutoSyncSettings,
    "conductor": rs.ConductorSettings,
    "team_spawn": rs.TeamSpawnModeSettings,
    "follow_up": rs.FollowUpSettings,
    "background_tasks": rs.BackgroundTaskSettings,
    "response_style": rs.ResponseStyleSettings,
    "browser": rs.BuiltInBrowserSettings,
}

SECTION_CASES = [
    ("git", {"network_timeout_seconds": "12", "max_diff_bytes": 2.0, "prune_on_fetch": "no"}),
    ("git", {"network_timeout_seconds": 5, "max_diff_bytes": 1.5, "prune_on_fetch": 2, "allow_force_push": "maybe", "default_pull_strategy": "x"}),
    ("git", {"max_diff_bytes": True}),
    ("git", {"max_diff_bytes": None}),
    ("git", []),
    ("git", "x"),
    ("context", {"summary_trigger_tokens": "3", "keep_recent_turns": 2.0}),
    ("context", {"summary_trigger_tokens": 2.5}),
    ("context", {"summary_trigger_tokens": "three"}),
    ("context", {"keep_recent_turns": None, "summary_max_tokens": 120001}),
    ("dream", {"model": "nocolon"}),
    ("dream", {"model": "a:b", "enabled": "yes", "schedule": 5}),
    ("team_spawn", {"work": "auto", "coding": "ASK"}),
    ("follow_up", {"delivery": "steer"}),
    ("follow_up", {}),
    ("background_tasks", {"wake_idle": "off"}),
    ("response_style", {"style": None}),
    ("webbridge", {"sharing": {"default": "allow", "blocked_domains": ["x"]}, "interactions": "nope"}),
    ("webbridge", {"allowed_domains": "x.com"}),
    ("computer_app", {"allowed_apps": ["a", 2], "permission": "allow"}),
    ("conductor", {"url": "https://x.example/", "enrollment_token": "t"}),
    ("conductor", {"url": "http://"}),
    ("conductor", {"url": "https://[::1]:8443"}),
    ("conductor", {"url": "https://x.example#frag"}),
    ("conductor", {"url": "HTTPS://X.example"}),
    ("conductor", {"url": "https://x.example/"}),
    ("conductor", {"url": 5}),
    ("browser", {"allow_downloads": 1, "allow_storage": 0.0}),
    ("import_auto_sync", {"scan_interval_seconds": 29}),
    ("memory_extraction", {"model": None, "min_assistant_messages": "5"}),
    ("title_generation", {"enabled": "1", "model": None}),
]


def jsonable(value):
    if isinstance(value, float) and value != value:
        return "nan"
    if isinstance(value, float) and value in (float("inf"), float("-inf")):
        return "inf" if value > 0 else "-inf"
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def error_rows(exc):
    rows = []
    for error in exc.errors():
        row = {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
        if "ctx" in error:
            row["ctx"] = {k: (str(v) if isinstance(v, Exception) else v) for k, v in error["ctx"].items()}
        rows.append(jsonable(row))
    return rows


def load_case(text):
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "settings.yaml"
        path.write_text(text, encoding="utf-8")
        try:
            loaded, ignored = rs.load_runtime_settings_report(path)
        except ValueError as exc:
            return {"yaml": text, "error": str(exc)}
        out = pathlib.Path(tmp) / "out.yaml"
        rs.save_runtime_settings(loaded, out)
        return {
            "yaml": text,
            "saved": out.read_text(encoding="utf-8"),
            "ignored": [[item.field, item.message] for item in ignored],
        }


def section_case(name, body):
    model = SECTIONS[name]
    try:
        value = model.model_validate(body)
    except ValidationError as exc:
        return {"section": name, "body": body, "errors": error_rows(exc)}
    return {"section": name, "body": body, "dump": jsonable(value.model_dump(mode="json"))}


def main():
    (HERE / "load_cases.json").write_text(
        json.dumps([load_case(c) for c in LOAD_CASES], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (HERE / "section_cases.json").write_text(
        json.dumps([section_case(n, b) for n, b in SECTION_CASES], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"yaml {yaml.__version__}: {len(LOAD_CASES)} load cases, {len(SECTION_CASES)} section cases")


if __name__ == "__main__":
    main()
