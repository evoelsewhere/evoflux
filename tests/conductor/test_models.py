from __future__ import annotations

import pytest

from app.conductor.models import Manifest, canonical_hash


def resource_payload() -> dict:
    return {
        "frontmatter": {"name": "worker", "role": "member"},
        "system_prompt": "Work safely.",
    }


def test_manifest_parses_and_validates_hashes() -> None:
    payload = resource_payload()
    resource = {
        "kind": "agent",
        "slug": "worker",
        "revision": "r1",
        "hash": f"sha256:{canonical_hash(payload)}",
        "payload": payload,
    }
    manifest_data = {
        "schema_version": 1,
        "revision": "m1",
        "resources": [resource],
        "policy": {"allow_local_resources": True},
    }
    normalized = Manifest.model_validate(manifest_data)
    manifest_data["hash"] = canonical_hash(
        normalized.model_dump(mode="json", exclude={"hash"})
    )

    manifest = Manifest.model_validate(manifest_data)

    assert manifest.resources[0].revision == "r1"


def test_manifest_rejects_payload_hash_mismatch() -> None:
    with pytest.raises(ValueError, match="Payload hash mismatch"):
        Manifest.model_validate(
            {
                "schema_version": 1,
                "revision": "m1",
                "resources": [
                    {
                        "kind": "agent",
                        "slug": "worker",
                        "hash": "0" * 64,
                        "payload": resource_payload(),
                    }
                ],
            }
        )


@pytest.mark.parametrize("slug", ["../escape", "/absolute", "foo/../../bar"])
def test_manifest_rejects_unsafe_resource_paths(slug: str) -> None:
    with pytest.raises(ValueError, match="Unsafe resource slug"):
        Manifest.model_validate(
            {
                "schema_version": 1,
                "revision": "m1",
                "resources": [
                    {
                        "kind": "agent",
                        "slug": slug,
                        "payload": resource_payload(),
                    }
                ],
            }
        )


def test_manifest_validates_dependencies() -> None:
    with pytest.raises(ValueError, match="Missing dependency skill/missing"):
        Manifest.model_validate(
            {
                "schema_version": 1,
                "revision": "m1",
                "resources": [
                    {
                        "kind": "agent",
                        "slug": "worker",
                        "payload": resource_payload(),
                        "dependencies": [{"kind": "skill", "slug": "missing"}],
                    }
                ],
            }
        )
