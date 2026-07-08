"""Tests for the notify tool's optional `title` field.

Covers: the tool schema/callback carrying `title` through end-to-end, and the
console rendering — a title becomes a bold header line above the message;
omitting it drops the header entirely while the colored border (the primary
severity cue) is still always present.
"""

from __future__ import annotations


def _render_to_ansi(callback) -> str:
    """Render Console output with forced color to inspect marks and ANSI codes."""
    from rich.console import Console as RichConsole

    from clanker.ui.console import CLANKER_THEME, Console

    console = Console()
    console._console = RichConsole(
        theme=CLANKER_THEME, force_terminal=True, color_system="truecolor", width=120
    )
    with console._console.capture() as cap:
        callback(console)
    return cap.get()


class TestNotifyToolTitle:
    """The notify tool accepts, validates, and forwards an optional title."""

    def _reset(self):
        from clanker.tools.notify_tools import set_notify_callback

        set_notify_callback(None)

    def test_returns_title_in_result_when_provided(self):
        from clanker.tools.notify_tools import notify, set_notify_callback

        self._reset()
        set_notify_callback(lambda message, level, title: None)
        result = notify.invoke({"message": "Scanning...", "level": "info", "title": "Starting scan"})
        assert result == {
            "ok": True,
            "sent": True,
            "message": "Scanning...",
            "level": "info",
            "title": "Starting scan",
        }
        self._reset()

    def test_title_is_none_when_omitted(self):
        from clanker.tools.notify_tools import notify, set_notify_callback

        self._reset()
        set_notify_callback(lambda message, level, title: None)
        result = notify.invoke({"message": "All good", "level": "success"})
        assert result["title"] is None
        self._reset()

    def test_callback_receives_title_positionally(self):
        from clanker.tools.notify_tools import notify, set_notify_callback

        self._reset()
        captured = []
        set_notify_callback(lambda message, level, title: captured.append((message, level, title)))
        notify.invoke({"message": "Found it", "level": "warning", "title": "Heads up"})
        assert captured == [("Found it", "warning", "Heads up")]
        self._reset()

    def test_fallback_print_includes_title_when_present(self, capsys):
        from clanker.tools.notify_tools import notify, set_notify_callback

        self._reset()
        set_notify_callback(None)  # forces the plain-text fallback path
        notify.invoke({"message": "Build finished", "level": "success", "title": "Done"})
        captured = capsys.readouterr()
        assert "Done" in captured.out
        assert "Build finished" in captured.out
        self._reset()

    def test_fallback_print_omits_title_when_absent(self, capsys):
        from clanker.tools.notify_tools import notify, set_notify_callback

        self._reset()
        set_notify_callback(None)
        notify.invoke({"message": "Build finished", "level": "success"})
        captured = capsys.readouterr()
        assert "[OK] Build finished" in captured.out
        self._reset()


class TestPrintNotifyTitleRendering:
    """print_notify shows the title as a header when given, omits it otherwise."""

    def test_title_rendered_as_bold_header(self) -> None:
        out = _render_to_ansi(
            lambda c: c.print_notify("The message body", "info", title="A Heading")
        )
        assert "A Heading" in out
        assert "The message body" in out
        # Bold styling on the header (ANSI bold = "1;").
        assert "1;38;2;0;190;220" in out

    def test_no_header_line_when_title_omitted(self) -> None:
        out = _render_to_ansi(
            lambda c: c.print_notify("The message body", "info")
        )
        assert "The message body" in out
        # No bold-styled header segment present at all.
        assert "1;38;2;0;190;220" not in out

    def test_border_color_present_regardless_of_title(self) -> None:
        # Severity (border color) must show up whether or not a title is given.
        with_title = _render_to_ansi(
            lambda c: c.print_notify("msg", "error", title="Oops")
        )
        without_title = _render_to_ansi(
            lambda c: c.print_notify("msg", "error")
        )
        assert "38;2;255;90;90" in with_title
        assert "38;2;255;90;90" in without_title

    def test_title_stripped_of_whitespace(self) -> None:
        out = _render_to_ansi(
            lambda c: c.print_notify("msg", "info", title="   Padded   ")
        )
        assert "Padded" in out

    def test_blank_title_treated_as_no_title(self) -> None:
        out = _render_to_ansi(
            lambda c: c.print_notify("msg", "info", title="   ")
        )
        # A whitespace-only title must not render an empty bold header line.
        assert "1;38;2;0;190;220" not in out

    def test_each_level_still_colors_border_with_title(self) -> None:
        colors = {
            "info": "0;190;220",
            "success": "130;220;100",
            "warning": "240;200;60",
            "error": "255;90;90",
        }
        for level, rgb in colors.items():
            out = _render_to_ansi(
                lambda c, level=level: c.print_notify("msg", level, title="T")
            )
            assert rgb in out, f"expected {rgb} in output for level={level}"
