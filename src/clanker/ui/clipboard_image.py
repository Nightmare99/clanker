"""Best-effort OS clipboard image reading.

Terminal bracketed paste (``events.Paste``) can only ever carry text -- there
is no escape sequence for binary clipboard data. Detecting and reading an
*image* paste therefore has to bypass the terminal entirely and go straight
to the OS clipboard via a platform tool. Support is inherently best-effort:
which tool is available (or whether one exists at all) varies a lot across
OS/desktop/terminal combinations, so every path here degrades to "no image
found" rather than raising -- callers should treat ``None`` as "nothing to
paste", not an error.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_TIMEOUT_SECONDS = 5
# Matches clanker.tools.file_tools.MAX_IMAGE_FILE_SIZE -- no point accepting
# a clipboard image the read_file path wouldn't accept either.
_MAX_IMAGE_BYTES = 20_000_000

_LINUX_IMAGE_MIME_TYPES = ("image/png", "image/jpeg", "image/bmp", "image/gif")


@dataclass
class ClipboardImage:
    """A successfully read clipboard image."""

    data: bytes
    mime_type: str


def read_clipboard_image() -> ClipboardImage | None:
    """Best-effort read of an image from the OS clipboard.

    Returns ``None`` if there's no image on the clipboard, the platform
    isn't supported, or no suitable clipboard tool is installed. Runs a
    subprocess, so callers on an event loop should offload this (e.g. via
    ``run_in_executor``) rather than calling it directly.
    """
    system = platform.system()
    if system == "Darwin":
        return _read_macos()
    if system == "Linux":
        return _read_linux()
    return None


def clipboard_image_tool_available() -> bool:
    """Whether any platform-appropriate clipboard-image tool is present.

    Lets a caller distinguish "tried, no image on the clipboard" from
    "can't even check" -- the latter deserves a one-time hint (e.g. "install
    xclip"), the former doesn't deserve any message at all.
    """
    system = platform.system()
    if system == "Darwin":
        return shutil.which("osascript") is not None
    if system == "Linux":
        return shutil.which("wl-paste") is not None or shutil.which("xclip") is not None
    return False


def _read_macos() -> ClipboardImage | None:
    if shutil.which("osascript") is None:
        return None

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    # AppleScript can coerce the clipboard to a PNG/TIFF class if (and only
    # if) it holds image data; each `on error` branch is a normal "wrong
    # type on the clipboard" outcome, not a real error.
    script = f"""
    try
        set imgData to (the clipboard as «class PNGf»)
    on error
        try
            set imgData to (the clipboard as «class TIFF»)
        on error
            return "NONE"
        end try
    end try
    set fileRef to open for access POSIX file "{tmp_path}" with write permission
    set eof of fileRef to 0
    write imgData to fileRef
    close access fileRef
    return "OK"
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        if result.returncode != 0 or result.stdout.strip() != "OK":
            return None
        data = tmp_path.read_bytes()
        if not data or len(data) > _MAX_IMAGE_BYTES:
            return None
        return ClipboardImage(data=data, mime_type="image/png")
    except (subprocess.SubprocessError, OSError):
        return None
    finally:
        tmp_path.unlink(missing_ok=True)


def _read_linux() -> ClipboardImage | None:
    if shutil.which("wl-paste") is not None:
        image = _read_wayland()
        if image is not None:
            return image
    if shutil.which("xclip") is not None:
        return _read_x11()
    return None


def _read_wayland() -> ClipboardImage | None:
    try:
        types_result = subprocess.run(
            ["wl-paste", "--list-types"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if types_result.returncode != 0:
        return None

    available = types_result.stdout.split()
    mime_type = next((t for t in _LINUX_IMAGE_MIME_TYPES if t in available), None)
    if mime_type is None:
        return None

    try:
        data_result = subprocess.run(
            ["wl-paste", "--type", mime_type],
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    data = data_result.stdout
    if data_result.returncode != 0 or not data or len(data) > _MAX_IMAGE_BYTES:
        return None
    return ClipboardImage(data=data, mime_type=mime_type)


def _read_x11() -> ClipboardImage | None:
    try:
        targets_result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if targets_result.returncode != 0:
        return None

    available = targets_result.stdout.split()
    mime_type = next((t for t in _LINUX_IMAGE_MIME_TYPES if t in available), None)
    if mime_type is None:
        return None

    try:
        data_result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", mime_type, "-o"],
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    data = data_result.stdout
    if data_result.returncode != 0 or not data or len(data) > _MAX_IMAGE_BYTES:
        return None
    return ClipboardImage(data=data, mime_type=mime_type)
