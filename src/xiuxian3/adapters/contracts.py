"""Platform-neutral command and message contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Scene(str, Enum):
    GROUP = "group"
    PRIVATE = "private"
    CHANNEL_GROUP = "channel_group"
    CHANNEL_PRIVATE = "channel_private"
    UNKNOWN = "unknown"


class MessageCapability(str, Enum):
    TEXT = "text"
    MARKDOWN = "markdown"
    KEYBOARD = "keyboard"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    REFERENCE = "reference"


@dataclass(frozen=True, slots=True)
class CommandContext:
    actor_id: str | None
    scene: Scene
    group_id: str | None
    message_id: str | None
    text: str
    raw_text_digest: str
    reply_to_message_id: str | None
    capabilities: frozenset[MessageCapability]
    can_write_assets: bool


@dataclass(frozen=True, slots=True)
class ReplyPlan:
    text: str
    markdown: str | None = None
    keyboard: tuple[str, ...] | None = None
    image_url: str | None = None
    audio_url: str | None = None
    video_url: str | None = None
    file_url: str | None = None
    reference_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class RenderedReply:
    text: str
    markdown: str | None = None
    keyboard: tuple[str, ...] | None = None
    image_url: str | None = None
    audio_url: str | None = None
    video_url: str | None = None
    file_url: str | None = None
    reference_message_id: str | None = None


class ReplyRenderer:
    """Select a lossless-enough presentation supported by one adapter."""

    def __init__(self, capabilities: set[MessageCapability] | frozenset[MessageCapability]) -> None:
        self.capabilities = frozenset(capabilities) | {MessageCapability.TEXT}

    def render(self, plan: ReplyPlan) -> RenderedReply:
        return RenderedReply(
            text=plan.text,
            markdown=plan.markdown if MessageCapability.MARKDOWN in self.capabilities else None,
            keyboard=plan.keyboard if MessageCapability.KEYBOARD in self.capabilities else None,
            image_url=plan.image_url if MessageCapability.IMAGE in self.capabilities else None,
            audio_url=plan.audio_url if MessageCapability.AUDIO in self.capabilities else None,
            video_url=plan.video_url if MessageCapability.VIDEO in self.capabilities else None,
            file_url=plan.file_url if MessageCapability.FILE in self.capabilities else None,
            reference_message_id=(
                plan.reference_message_id
                if MessageCapability.REFERENCE in self.capabilities
                else plan.reference_message_id
            ),
        )