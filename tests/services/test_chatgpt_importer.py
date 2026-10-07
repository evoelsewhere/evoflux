from app.services.importers.chatgpt import _parse_conversations


def _conversation(*, title: str, conversation_id: str | None = "conversation-123"):
    conversation = {
        "title": title,
        "create_time": 1_700_000_000,
        "update_time": 1_700_000_100,
        "mapping": {
            "root": {"children": ["user-message"]},
            "user-message": {
                "message": {
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["hello"]},
                    "create_time": 1_700_000_000,
                },
                "children": [],
            },
        },
    }
    if conversation_id is not None:
        conversation["id"] = conversation_id
    return conversation


def test_chatgpt_conversation_id_is_stable_when_title_changes():
    before = _parse_conversations([_conversation(title="Old title")])[0]
    after = _parse_conversations([_conversation(title="New title")])[0]

    assert before.source_id == "chatgpt:conversation-123"
    assert after.source_id == before.source_id


def test_chatgpt_conversation_without_id_keeps_legacy_identity_fallback():
    item = _parse_conversations(
        [_conversation(title="Legacy title", conversation_id=None)]
    )[0]

    assert item.source_id == "chatgpt:Legacy title:1700000000"
