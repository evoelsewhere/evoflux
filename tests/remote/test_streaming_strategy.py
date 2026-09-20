from app.remote.streaming import StreamingStrategyKind, select_streaming_strategy


def test_imessage_uses_block_streaming() -> None:
    assert select_streaming_strategy(adapter="imessage") is StreamingStrategyKind.BLOCK


def test_telegram_defaults_to_edit_streaming() -> None:
    assert select_streaming_strategy(adapter="telegram") is StreamingStrategyKind.EDIT


def test_private_telegram_can_use_draft_streaming() -> None:
    assert (
        select_streaming_strategy(adapter="telegram", provider="private_draft")
        is StreamingStrategyKind.DRAFT
    )
