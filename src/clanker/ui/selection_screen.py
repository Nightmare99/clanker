"""Text selection guarded during response reveals and stale compositor frames."""

from collections.abc import Iterator
from contextlib import contextmanager

from textual.geometry import Offset
from textual.screen import Screen
from textual.widget import Widget


class SelectionScreen(Screen[None]):
    _selection_suspensions: int = 0

    @property
    def allow_select(self) -> bool:
        return self._selection_suspensions == 0 and super().allow_select

    @contextmanager
    def suspend_selection(self) -> Iterator[None]:
        """Disable selection until all overlapping response reveals finish."""
        self._selection_suspensions += 1
        self.clear_selection()
        try:
            yield
        finally:
            self._selection_suspensions -= 1

    def get_widget_and_offset_at(self, x: int, y: int) -> tuple[Widget | None, Offset | None]:
        if not self.allow_select:
            return None, None
        widget, offset = super().get_widget_and_offset_at(x, y)
        # Markdown updates/pruning can detach a block before the next layout.
        # Textual's selection code assumes a hit still has a live parent.
        if widget is not None and not widget.is_attached:
            return None, None
        return widget, offset
