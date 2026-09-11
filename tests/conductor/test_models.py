from __future__ import annotations

import pytest

from app.conductor.models import Manifest, RegistrationResponse, canonical_hash


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


def registration_payload() -> dict:
    """The shape Conductor answers `/api/v1/client/register` with."""
    return {
        "installation": {
            "id": "11111111-1111-1111-1111-111111111111",
            "display_name": "EvoFlux laptop",
            "heartbeat_interval_seconds": 60,
        },
        "project": {
            "id": "22222222-2222-2222-2222-222222222222",
            "name": "acme",
            "display_name": "Acme",
            "description": None,
            "logo_url": None,
        },
        "member": {
            "id": "33333333-3333-3333-3333-333333333333",
            "display_name": "Hung",
            "primary_role": "admin",
            "sub_roles": [],
            "tags": [],
        },
        "policy": {
            "collection_level": "L1",
            "telemetry": {},
            "privacy_notice_version": "v1",
        },
    }


def test_registration_response_keeps_the_project_description() -> None:
    response = RegistrationResponse.model_validate(registration_payload())
    assert response.project.description is None
    assert response.project.name == "acme"


def test_a_field_conductor_adds_later_does_not_break_enrolment() -> None:
    """Conductor may ship a field this client has never heard of.

    Refusing it used to fail the whole response, so a control plane one
    version ahead stopped every client from enrolling at all.
    """
    payload = registration_payload()
    payload["project"]["a_field_from_a_newer_conductor"] = "value"
    payload["installation"]["another_new_field"] = 7
    payload["a_whole_new_section"] = {"nested": True}

    response = RegistrationResponse.model_validate(payload)
    assert response.project.name == "acme"
    assert response.installation.heartbeat_interval_seconds == 60
