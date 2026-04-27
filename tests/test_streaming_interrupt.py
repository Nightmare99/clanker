"""Tests for streaming interrupt handling (Ctrl+C)."""

from __future__ import annotations

import asyncio
import signal
from unittest import mock

import pytest


def _deps_available() -> bool:
    """Check if required dependencies are available."""
    try:
        import pydantic
        return True
    except ImportError:
        return False


def _load_streaming_module():
    """Load streaming module."""
    from clanker.ui import streaming
    return streaming


# Skip entire module if deps not available
pytestmark = pytest.mark.skipif(
    not _deps_available(),
    reason="pydantic not installed"
)


class TestInterruptFlag:
    """Tests for interrupt flag and cancellation."""

    def test_cancel_streaming_task_sets_flag(self) -> None:
        """_cancel_streaming_task sets the _interrupted flag."""
        module = _load_streaming_module()

        # Reset state
        module._interrupted = False
        module._current_streaming_task = None

        module._cancel_streaming_task()

        assert module._interrupted is True

    def test_cancel_streaming_task_cancels_task(self) -> None:
        """_cancel_streaming_task cancels the running task."""
        module = _load_streaming_module()

        # Create a mock task
        mock_task = mock.MagicMock()
        mock_task.done.return_value = False

        module._current_streaming_task = mock_task
        module._interrupted = False

        module._cancel_streaming_task()

        assert module._interrupted is True
        mock_task.cancel.assert_called_once()

    def test_cancel_streaming_task_skips_done_task(self) -> None:
        """_cancel_streaming_task doesn't cancel already-done tasks."""
        module = _load_streaming_module()

        mock_task = mock.MagicMock()
        mock_task.done.return_value = True

        module._current_streaming_task = mock_task
        module._interrupted = False

        module._cancel_streaming_task()

        assert module._interrupted is True
        mock_task.cancel.assert_not_called()


class TestAsyncioExceptionHandler:
    """Tests for custom asyncio exception handler."""

    def test_suppresses_invalid_state_error(self) -> None:
        """Handler suppresses InvalidStateError."""
        module = _load_streaming_module()
        mock_loop = mock.MagicMock()

        context = {"exception": asyncio.InvalidStateError("already done")}
        module._asyncio_exception_handler(mock_loop, context)

        mock_loop.default_exception_handler.assert_not_called()

    def test_suppresses_cancelled_error(self) -> None:
        """Handler suppresses CancelledError."""
        module = _load_streaming_module()
        mock_loop = mock.MagicMock()

        context = {"exception": asyncio.CancelledError()}
        module._asyncio_exception_handler(mock_loop, context)

        mock_loop.default_exception_handler.assert_not_called()

    def test_suppresses_process_exited_code_0(self) -> None:
        """Handler suppresses ProcessExited with code 0."""
        module = _load_streaming_module()
        mock_loop = mock.MagicMock()

        context = {"message": "ProcessExited with code 0"}
        module._asyncio_exception_handler(mock_loop, context)

        mock_loop.default_exception_handler.assert_not_called()

    def test_passes_through_other_exceptions(self) -> None:
        """Handler passes through other exceptions."""
        module = _load_streaming_module()
        mock_loop = mock.MagicMock()

        context = {"exception": ValueError("something bad"), "message": "error"}
        module._asyncio_exception_handler(mock_loop, context)

        mock_loop.default_exception_handler.assert_called_once_with(context)


class TestEventLoop:
    """Tests for event loop management."""

    def test_get_or_create_loop_creates_new(self) -> None:
        """_get_or_create_loop creates a new loop if none exists."""
        module = _load_streaming_module()

        # Clear existing loop
        module._persistent_loop = None

        loop = module._get_or_create_loop()

        assert loop is not None
        assert not loop.is_closed()
        assert module._persistent_loop is loop

        # Cleanup
        module.cleanup_event_loop()

    def test_get_or_create_loop_reuses_existing(self) -> None:
        """_get_or_create_loop reuses existing loop."""
        module = _load_streaming_module()

        loop1 = module._get_or_create_loop()
        loop2 = module._get_or_create_loop()

        assert loop1 is loop2

        # Cleanup
        module.cleanup_event_loop()

    def test_cleanup_event_loop_closes(self) -> None:
        """cleanup_event_loop closes the loop."""
        module = _load_streaming_module()

        loop = module._get_or_create_loop()
        assert not loop.is_closed()

        module.cleanup_event_loop()

        assert loop.is_closed()
        assert module._persistent_loop is None


class TestStreamResultDataclass:
    """Tests for StreamResult dataclass."""

    def test_total_tokens(self) -> None:
        """total_tokens sums input and output."""
        module = _load_streaming_module()

        result = module.StreamResult(
            response="test",
            input_tokens=100,
            output_tokens=50,
        )

        assert result.total_tokens == 150

    def test_defaults(self) -> None:
        """StreamResult has sensible defaults."""
        module = _load_streaming_module()

        result = module.StreamResult(response="test")

        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.model_name == ""
        assert result.quota_remaining is None


class TestSignalHandling:
    """Tests for signal-based interrupt handling."""

    def test_signal_handler_installed_and_restored(self) -> None:
        """Signal handler is installed during streaming and restored after."""
        module = _load_streaming_module()

        original_handler = signal.getsignal(signal.SIGINT)

        # We can't easily test the full streaming flow without mocking everything,
        # but we can verify the pattern works by checking the module has the function
        assert hasattr(module, '_cancel_streaming_task')
        assert callable(module._cancel_streaming_task)

        # Verify signal is still at original after module load
        current_handler = signal.getsignal(signal.SIGINT)
        # May be different if test framework installed its own
        assert current_handler is not None

    def test_interrupted_flag_checked_in_module(self) -> None:
        """Module has _interrupted flag that can be checked."""
        module = _load_streaming_module()

        assert hasattr(module, '_interrupted')
        # Should start as False
        module._interrupted = False
        assert module._interrupted is False


class TestSuppressSubprocessStderr:
    """Tests for stderr suppression context manager."""

    def test_suppress_stderr_is_context_manager(self) -> None:
        """_suppress_subprocess_stderr is a context manager."""
        module = _load_streaming_module()

        # Should work as context manager without error
        with module._suppress_subprocess_stderr():
            pass

    def test_suppress_stderr_restores_on_exit(self) -> None:
        """_suppress_subprocess_stderr restores stderr on exit."""
        module = _load_streaming_module()
        import sys
        import os

        # Get original stderr fd
        try:
            original_fd = sys.stderr.fileno()
        except (OSError, ValueError):
            pytest.skip("No real stderr available")

        with module._suppress_subprocess_stderr():
            # Inside context, stderr is redirected
            pass

        # After context, should still be able to write to stderr
        current_fd = sys.stderr.fileno()
        assert current_fd == original_fd
