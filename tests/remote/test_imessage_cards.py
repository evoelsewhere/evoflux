from app.remote.contracts import RemoteButton
from app.remote.imessage.cards import render_card


def test_render_card_projects_buttons_as_numbered_actions() -> None:
    rendered = render_card(
        "Choose an action",
        [
            RemoteButton(text="Approve", token="a"),
            RemoteButton(text="Reject", token="r"),
        ],
    )
    assert rendered == "Choose an action\n\nReply with a number:\n1. Approve\n2. Reject"


def test_render_card_keeps_plain_text_without_buttons() -> None:
    assert render_card("Done", ()) == "Done"
