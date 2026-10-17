"""Check real clipboard process boundaries without changing the OS clipboard."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from clanker.ui import keyboard, native_clipboard


@pytest.mark.parametrize("macos,remote,expected", [(True, False, True), (True, True, False), (False, False, False)])
def test_only_local_macos_uses_native_clipboard(monkeypatch, macos, remote, expected):
    monkeypatch.setattr(keyboard, "is_macos", lambda: macos)
    for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"):
        monkeypatch.delenv(key, raising=False)
    if remote:
        monkeypatch.setenv("SSH_CONNECTION", "remote session")
    assert native_clipboard.is_local_macos() is expected


async def test_unicode_clipboard_text_goes_to_stdin(monkeypatch):
    process = MagicMock(returncode=0)
    process.communicate = AsyncMock(return_value=(b"", b""))
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(native_clipboard.asyncio, "create_subprocess_exec", create)
    text = "Copy café\n日本語 😀"
    assert await native_clipboard.write_text(text)
    create.assert_awaited_once_with(
        "/usr/bin/pbcopy", stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    process.communicate.assert_awaited_once_with(text.encode("utf-8"))
    process.kill.assert_not_called()


@pytest.mark.parametrize("missing", [False, True])
async def test_clipboard_failures_return_false(monkeypatch, missing):
    create = AsyncMock()
    if missing:
        create.side_effect = FileNotFoundError()
    else:
        create.return_value.returncode = 1
        create.return_value.communicate = AsyncMock(return_value=(b"", b""))
    monkeypatch.setattr(native_clipboard.asyncio, "create_subprocess_exec", create)
    assert not await native_clipboard.write_text("text")


async def test_clipboard_timeout_kills_and_reaps_process(monkeypatch):
    process = MagicMock(returncode=None)
    process.communicate = AsyncMock(side_effect=TimeoutError())
    process.wait = AsyncMock(return_value=-9)
    monkeypatch.setattr(native_clipboard.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    assert not await native_clipboard.write_text("text")
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()


async def test_clipboard_cancellation_kills_and_reaps_process(monkeypatch):
    started = asyncio.Event()

    async def communicate(_):
        started.set()
        await asyncio.Event().wait()

    process = MagicMock(returncode=None)
    process.communicate = communicate
    process.wait = AsyncMock(return_value=-9)
    monkeypatch.setattr(native_clipboard.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    task = asyncio.create_task(native_clipboard.write_text("text"))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()
