from __future__ import annotations

from app.conductor.models import RegistrationResponse


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
