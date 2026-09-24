"""Bounded pydantic models for the subset of the Telegram Bot API wire
format this adapter uses.

Every model ignores unknown fields (``extra="ignore"``) because Telegram's
API is additive and this adapter only ever reads a handful of fields from a
much larger payload. Nothing here is imported outside ``app/remote/telegram/``.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class TelegramUser(BaseModel):
    """https://core.telegram.org/bots/api#user"""

    model_config = ConfigDict(extra="ignore")

    id: int
    is_bot: bool = False
    username: str | None = None
    first_name: str | None = None


class TelegramChat(BaseModel):
    """https://core.telegram.org/bots/api#chat"""

    model_config = ConfigDict(extra="ignore")

    id: int
    type: str


class TelegramPhotoSize(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_id: str
    width: int
    height: int
    file_size: int | None = None


class TelegramDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_id: str
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


class TelegramMessage(BaseModel):
    """https://core.telegram.org/bots/api#message

    Only the fields this adapter reads or needs to echo back (to address an
    edit) are modeled. Media, entities, and formatting fields are
    deliberately absent: this adapter never sends or interprets them.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    message_id: int
    date: int
    chat: TelegramChat
    from_user: TelegramUser | None = Field(default=None, alias="from")
    text: str | None = None
    caption: str | None = None
    photo: list[TelegramPhotoSize] | None = None
    document: TelegramDocument | None = None


class TelegramCallbackQuery(BaseModel):
    """https://core.telegram.org/bots/api#callbackquery"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    from_user: TelegramUser = Field(alias="from")
    message: TelegramMessage | None = None
    data: str | None = None


class TelegramUpdate(BaseModel):
    """https://core.telegram.org/bots/api#update

    Only ``message`` and ``callback_query`` are modeled because the adapter
    requests ``allowed_updates=["message", "callback_query"]`` and Telegram
    never delivers any other update kind once that filter is set.
    """

    model_config = ConfigDict(extra="ignore")

    update_id: int
    message: TelegramMessage | None = None
    callback_query: TelegramCallbackQuery | None = None


class TelegramInlineKeyboardButton(BaseModel):
    """https://core.telegram.org/bots/api#inlinekeyboardbutton

    ``callback_data`` is always an opaque, connection-owned capability token
    minted by the (later) remote service — never a raw session ID, path, or
    command (spec: "Remote interaction contract").
    """

    model_config = ConfigDict(extra="ignore")

    text: str
    callback_data: str


class TelegramInlineKeyboardMarkup(BaseModel):
    """https://core.telegram.org/bots/api#inlinekeyboardmarkup"""

    model_config = ConfigDict(extra="ignore")

    inline_keyboard: list[list[TelegramInlineKeyboardButton]]


class TelegramResponseParameters(BaseModel):
    """https://core.telegram.org/bots/api#responseparameters"""

    model_config = ConfigDict(extra="ignore")

    retry_after: int | None = None
    migrate_to_chat_id: int | None = None


class TelegramResponse(BaseModel, Generic[T]):
    """The envelope every Bot API method response is wrapped in."""

    model_config = ConfigDict(extra="ignore")

    ok: bool
    result: T | None = None
    error_code: int | None = None
    description: str | None = None
    parameters: TelegramResponseParameters | None = None


__all__ = [
    "TelegramCallbackQuery",
    "TelegramChat",
    "TelegramInlineKeyboardButton",
    "TelegramInlineKeyboardMarkup",
    "TelegramMessage",
    "TelegramResponse",
    "TelegramResponseParameters",
    "TelegramUpdate",
    "TelegramUser",
]
