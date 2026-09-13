"""Lossless input drafts, including expanded pastes and image attachments."""

import base64
from dataclasses import dataclass, field

from clanker.ui.clipboard_image import ClipboardImage


@dataclass
class PromptDraft:
    text: str = ""
    pastes: list[tuple[str, str]] = field(default_factory=list)
    images: list[tuple[str, ClipboardImage]] = field(default_factory=list)

    def expanded_text(self) -> str:
        text = self.text
        for label, pasted in self.pastes:
            text = text.replace(label, pasted, 1)
        return text

    def to_dict(self) -> dict:
        return {
            "text": self.text, "pastes": self.pastes,
            "images": [
                {"label": label, "mime_type": image.mime_type,
                 "data": base64.b64encode(image.data).decode("ascii")}
                for label, image in self.images
            ],
        }

    @classmethod
    def from_dict(cls, value: dict) -> "PromptDraft":
        return cls(
            text=value["text"], pastes=[tuple(p) for p in value.get("pastes", [])],
            images=[
                (item["label"], ClipboardImage(
                    data=base64.b64decode(item["data"], validate=True), mime_type=item["mime_type"]
                )) for item in value.get("images", [])
            ],
        )
