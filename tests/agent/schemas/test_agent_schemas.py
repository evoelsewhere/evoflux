from datetime import datetime, timezone
from uuid import uuid4

from app.agent.schemas.agent import RunConfig
from app.uuid7 import uuid7


def test_run_config_ignores_non_uuid7_session_id() -> None:
    config = RunConfig(session_id=str(uuid4()))

    assert config.session_created_at is None


def test_run_config_decodes_uuid7_session_creation_time() -> None:
    created_at_before = datetime.now(timezone.utc)
    session_id = str(uuid7())
    created_at_after = datetime.now(timezone.utc)

    config = RunConfig(session_id=session_id)

    assert config.session_created_at is not None
    assert created_at_before <= config.session_created_at <= created_at_after