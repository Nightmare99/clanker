"""Interactive selection prompts for mid-execution agent questions.

Provides :func:`select_options`, an arrow-key multiple-choice menu used by the
``ask_user`` tool. On a real terminal it renders a ``prompt_toolkit`` menu
(up/down to move, space to toggle in multi-select, Enter to confirm, Esc to
cancel). When stdin is not a TTY (piped input, one-shot ``clanker "prompt"``,
CI) it falls back to a numbered list read with ``input()`` -- the same approach
as the bash approval prompt in ``bash_tools.py``.

The return shape is uniform: ``{"selected": [...], "cancelled": bool}``.
``selected`` is always a list (even for single-select) so callers handle one
shape. A free-text "Other" choice puts the typed string into ``selected``.
"""

from __future__ import annotations

import sys

# Sentinel labels for the synthetic menu rows.
_OTHER_LABEL = "Other (type your own)"
_CANCEL_LABEL = "Cancel"


def select_options(
    question: str,
    options: list[str],
    *,
    multi_select: bool = False,
    allow_other: bool = True,
    allow_cancel: bool = True,
) -> dict:
    """Ask the user to choose from ``options``.

    Args:
        question: The prompt shown above the choices.
        options: The selectable option labels.
        multi_select: Allow choosing more than one option.
        allow_other: Offer a free-text "Other" choice.
        allow_cancel: Offer a cancel choice / allow Esc.

    Returns:
        ``{"selected": list[str], "cancelled": bool}``.
    """
    if _stdin_is_interactive():
        try:
            return _select_interactive(
                question,
                options,
                multi_select=multi_select,
                allow_other=allow_other,
                allow_cancel=allow_cancel,
            )
        except Exception:
            # Never let a UI failure strand the tool -- degrade to the
            # numbered prompt, which works anywhere.
            pass
    return _select_fallback(
        question,
        options,
        multi_select=multi_select,
        allow_other=allow_other,
        allow_cancel=allow_cancel,
    )


def _stdin_is_interactive() -> bool:
    """True when we can drive a full-screen prompt (real TTY on both ends)."""
    try:
        return bool(sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty())
    except Exception:
        return False


# ----------------------------------------------------------------------
# Interactive (prompt_toolkit) path
# ----------------------------------------------------------------------
def _select_interactive(
    question: str,
    options: list[str],
    *,
    multi_select: bool,
    allow_other: bool,
    allow_cancel: bool,
) -> dict:
    """Arrow-key menu using prompt_toolkit's Application."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    # Build the row list: real options, then optional Other / Cancel rows.
    rows: list[str] = list(options)
    other_index = -1
    cancel_index = -1
    if allow_other:
        other_index = len(rows)
        rows.append(_OTHER_LABEL)
    if allow_cancel:
        cancel_index = len(rows)
        rows.append(_CANCEL_LABEL)

    state = {"cursor": 0, "checked": set(), "result": None}

    def render():
        lines = [("class:question", f"  {question}\n")]
        if multi_select:
            lines.append(("class:hint", "  space toggles · enter confirms · esc cancels\n\n"))
        else:
            lines.append(("class:hint", "  ↑/↓ to move · enter to select · esc cancels\n\n"))
        for i, label in enumerate(rows):
            cursor = "❯" if i == state["cursor"] else " "
            is_special = i in (other_index, cancel_index)
            if multi_select and not is_special:
                box = "◉" if i in state["checked"] else "◯"
                marker = f"{cursor} {box} "
            else:
                marker = f"{cursor}   "
            style = "class:selected" if i == state["cursor"] else "class:option"
            if is_special:
                style = "class:special.selected" if i == state["cursor"] else "class:special"
            lines.append((style, f"  {marker}{label}\n"))
        return to_formatted_text(lines)

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("c-p")
    def _(event):
        state["cursor"] = (state["cursor"] - 1) % len(rows)

    @kb.add("down")
    @kb.add("c-n")
    def _(event):
        state["cursor"] = (state["cursor"] + 1) % len(rows)

    @kb.add("space")
    def _(event):
        i = state["cursor"]
        if multi_select and i not in (other_index, cancel_index):
            state["checked"].symmetric_difference_update({i})

    @kb.add("enter")
    def _(event):
        state["result"] = "confirm"
        event.app.exit()

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _(event):
        state["result"] = "cancel"
        event.app.exit()

    style = Style.from_dict({
        "question": "bold #00d2b4",
        "hint": "#7f8c8d italic",
        "option": "",
        "selected": "bold #00d2b4",
        "special": "#7f8c8d",
        "special.selected": "bold #f0c060",
    })

    app = Application(
        layout=Layout(HSplit([Window(FormattedTextControl(render), always_hide_cursor=True)])),
        key_bindings=kb,
        style=style,
        full_screen=False,
    )
    app.run()

    # Interpret the outcome.
    if state["result"] == "cancel":
        return {"selected": [], "cancelled": True}

    cursor = state["cursor"]
    if cursor == cancel_index:
        return {"selected": [], "cancelled": True}

    if multi_select:
        chosen_indices = sorted(state["checked"]) or [cursor]
        selected: list[str] = []
        for i in chosen_indices:
            if i == cancel_index:
                return {"selected": [], "cancelled": True}
            if i == other_index:
                other = _read_other_text()
                if other:
                    selected.append(other)
            elif i < len(options):
                selected.append(options[i])
        return {"selected": selected, "cancelled": False}

    if cursor == other_index:
        other = _read_other_text()
        return {"selected": [other] if other else [], "cancelled": not other}
    return {"selected": [options[cursor]], "cancelled": False}


def _read_other_text() -> str:
    """Prompt for a free-text answer after the menu closes."""
    try:
        return input("  Your answer: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


# ----------------------------------------------------------------------
# Non-TTY fallback path (numbered list + input())
# ----------------------------------------------------------------------
def _select_fallback(
    question: str,
    options: list[str],
    *,
    multi_select: bool,
    allow_other: bool,
    allow_cancel: bool,
) -> dict:
    """Numbered-list prompt for non-interactive / piped stdin."""
    print()
    print(f"  {question}")
    for i, label in enumerate(options, 1):
        print(f"    {i}) {label}")
    other_num = -1
    if allow_other:
        other_num = len(options) + 1
        print(f"    {other_num}) {_OTHER_LABEL}")
    if allow_cancel:
        print("    0) Cancel")

    hint = "Enter choice(s), comma-separated" if multi_select else "Enter choice"
    rng = f"[1-{len(options)}]" if not allow_other else f"[1-{other_num}]"
    try:
        raw = input(f"  {hint} {rng}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return {"selected": [], "cancelled": True}

    if not raw or raw == "0":
        return {"selected": [], "cancelled": True}
    if raw.lower() in ("o", "other") and allow_other:
        other = _read_other_text()
        return {"selected": [other] if other else [], "cancelled": not other}

    # Parse one or more comma-separated numbers.
    tokens = [t.strip() for t in raw.split(",")] if multi_select else [raw]
    selected: list[str] = []
    for tok in tokens:
        if not tok.isdigit():
            continue
        n = int(tok)
        if n == 0:
            return {"selected": [], "cancelled": True}
        if allow_other and n == other_num:
            other = _read_other_text()
            if other:
                selected.append(other)
        elif 1 <= n <= len(options):
            selected.append(options[n - 1])

    if not selected:
        return {"selected": [], "cancelled": True}
    if not multi_select:
        selected = selected[:1]
    return {"selected": selected, "cancelled": False}
