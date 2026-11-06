"""Trim a models.dev `api.json` into evo's offline seed snapshot.

models.dev is evo's model database: the engine downloads
https://models.dev/api.json, caches it in the application database and
refreshes it in the background. This snapshot only seeds a machine that has
never been online, so it keeps exactly what evo reads (see
`src/models_dev.rs`) and drops models an agent cannot use: deprecated ones
and ones without tool calling.

Usage:
    curl -o api.json https://models.dev/api.json
    python scripts/gen_models_dev_snapshot.py api.json data/models_dev_snapshot.json
"""

import json
import sys
from pathlib import Path

PROVIDER_FIELDS = ("id", "name", "api", "env", "npm", "doc")
MODEL_FIELDS = (
    "id", "name", "attachment", "reasoning", "reasoning_options", "tool_call",
    "interleaved", "modalities", "limit", "cost", "provider", "status",
)


def main() -> None:
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    data = json.loads(source.read_text(encoding="utf-8"))
    out = {}
    models_total = 0
    for key, provider in sorted(data.items()):
        if not isinstance(provider, dict):
            continue
        row = {field: provider[field] for field in PROVIDER_FIELDS if field in provider}
        models = {}
        for model_id, model in sorted((provider.get("models") or {}).items()):
            if model.get("status") == "deprecated" or model.get("tool_call") is False:
                continue
            trimmed = {field: model[field] for field in MODEL_FIELDS if field in model}
            modalities = trimmed.get("modalities")
            if isinstance(modalities, dict):
                trimmed["modalities"] = {"input": modalities.get("input", [])}
            models[model_id] = trimmed
        row["models"] = models
        models_total += len(models)
        out[key] = row
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(out)} providers, {models_total} models -> {target} ({target.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
