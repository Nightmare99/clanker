"""Tests for clanker.ui.clipboard_image -- best-effort OS clipboard image reads.

Terminal bracketed paste can't carry binary data, so image paste goes
through platform tools (osascript/xclip/wl-paste) instead. These are pure
unit tests: subprocess/filesystem calls are mocked, no real clipboard tool
is invoked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from clanker.ui import clipboard_image as ci


# -- clipboard_image_tool_available --------------------------------------------


def test_tool_available_macos_when_osascript_present(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None)
    assert ci.clipboard_image_tool_available() is True


def test_tool_available_macos_when_osascript_missing(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: None)
    assert ci.clipboard_image_tool_available() is False


def test_tool_available_linux_with_xclip_only(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/usr/bin/xclip" if name == "xclip" else None)
    assert ci.clipboard_image_tool_available() is True


def test_tool_available_linux_with_wlpaste_only(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/usr/bin/wl-paste" if name == "wl-paste" else None)
    assert ci.clipboard_image_tool_available() is True


def test_tool_available_linux_neither_installed(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ci.shutil, "which", lambda name: None)
    assert ci.clipboard_image_tool_available() is False


def test_tool_available_unsupported_platform(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Windows")
    assert ci.clipboard_image_tool_available() is False


# -- read_clipboard_image: platform routing ------------------------------------


def test_read_clipboard_image_unsupported_platform_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Windows")
    assert ci.read_clipboard_image() is None


# -- macOS backend ---------------------------------------------------------------


def test_macos_no_osascript_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: None)
    assert ci.read_clipboard_image() is None


def test_macos_reads_image_written_by_osascript(monkeypatch) -> None:
    fake_png_bytes = b"\x89PNG\r\n\x1a\nfake-image-data"

    monkeypatch.setattr(ci.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/usr/bin/osascript")

    def fake_run(cmd, **kwargs):
        # The script writes to the temp path baked into the AppleScript source
        # (cmd[-1]); simulate that side effect the same way a real
        # `osascript -e <script>` call would.
        script = cmd[-1]
        marker = 'POSIX file "'
        start = script.index(marker) + len(marker)
        end = script.index('"', start)
        path = script[start:end]
        with open(path, "wb") as f:
            f.write(fake_png_bytes)
        return MagicMock(returncode=0, stdout="OK\n")

    with patch.object(ci.subprocess, "run", side_effect=fake_run):
        image = ci.read_clipboard_image()

    assert image is not None
    assert image.data == fake_png_bytes
    assert image.mime_type == "image/png"


def test_macos_no_image_on_clipboard_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/usr/bin/osascript")

    with patch.object(ci.subprocess, "run", return_value=MagicMock(returncode=0, stdout="NONE\n")):
        assert ci.read_clipboard_image() is None


def test_macos_subprocess_error_returns_none_not_raise(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/usr/bin/osascript")

    with patch.object(ci.subprocess, "run", side_effect=ci.subprocess.TimeoutExpired(cmd="osascript", timeout=5)):
        assert ci.read_clipboard_image() is None


def test_macos_oversized_image_rejected(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(ci, "_MAX_IMAGE_BYTES", 10)

    def fake_run(cmd, **kwargs):
        script = cmd[-1]
        marker = 'POSIX file "'
        start = script.index(marker) + len(marker)
        end = script.index('"', start)
        path = script[start:end]
        with open(path, "wb") as f:
            f.write(b"x" * 100)  # exceeds the 10-byte cap
        return MagicMock(returncode=0, stdout="OK\n")

    with patch.object(ci.subprocess, "run", side_effect=fake_run):
        assert ci.read_clipboard_image() is None


# -- Linux backends --------------------------------------------------------------


def test_linux_no_tools_installed_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ci.shutil, "which", lambda name: None)
    assert ci.read_clipboard_image() is None


def test_linux_wayland_prefers_wlpaste_over_xclip(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ci.shutil, "which", lambda name: f"/usr/bin/{name}")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ["wl-paste", "--list-types"]:
            return MagicMock(returncode=0, stdout="text/plain\nimage/png\n")
        if cmd[:2] == ["wl-paste", "--type"]:
            return MagicMock(returncode=0, stdout=b"pngbytes")
        raise AssertionError(f"xclip should not be called when wl-paste succeeds: {cmd}")

    with patch.object(ci.subprocess, "run", side_effect=fake_run):
        image = ci.read_clipboard_image()

    assert image is not None
    assert image.data == b"pngbytes"
    assert image.mime_type == "image/png"


def test_linux_wayland_no_image_type_falls_back_to_xclip(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ci.shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["wl-paste", "--list-types"]:
            return MagicMock(returncode=0, stdout="text/plain\n")  # no image type
        if cmd[:3] == ["xclip", "-selection", "clipboard"] and "TARGETS" in cmd:
            return MagicMock(returncode=0, stdout="image/png\n")
        if cmd[:3] == ["xclip", "-selection", "clipboard"] and "image/png" in cmd:
            return MagicMock(returncode=0, stdout=b"xclip-png-bytes")
        raise AssertionError(f"unexpected command: {cmd}")

    with patch.object(ci.subprocess, "run", side_effect=fake_run):
        image = ci.read_clipboard_image()

    assert image is not None
    assert image.data == b"xclip-png-bytes"


def test_linux_x11_no_image_target_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(ci.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ci.shutil, "which", lambda name: "/usr/bin/xclip" if name == "xclip" else None)

    with patch.object(
        ci.subprocess, "run", return_value=MagicMock(returncode=0, stdout="text/plain\nUTF8_STRING\n")
    ):
        assert ci.read_clipboard_image() is None
