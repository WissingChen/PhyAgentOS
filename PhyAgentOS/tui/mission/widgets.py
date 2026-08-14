"""MOSS-style mission HUD widgets."""

import time

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Static

TYPE_INTERVAL = 0.02

STATE_STEPS = ["OBSERVE", "PAUSE", "DIAGNOSE", "REPLAN"]


def _typewrite(static: Static, full_text: str, interval: float = TYPE_INTERVAL) -> None:
    """Reveal text character by character on a Static."""
    state = {"n": 0}

    def tick() -> None:
        state["n"] += 1
        static.update(full_text[: state["n"]])
        if state["n"] >= len(full_text):
            timer.stop()

    timer = static.set_interval(interval, tick)


class MissionHeader(Horizontal):
    """Left: mission branding. Right: mission clock + status lamp."""

    def __init__(self) -> None:
        super().__init__()
        self._base_t = 0.0
        self._base_wall = time.monotonic()

    def compose(self) -> ComposeResult:
        yield Static("◤ PhyAgentOS // MISSION REPLAN³", classes="mh-title")
        yield Static("T+00:00", classes="mh-clock")
        yield Static("● LIVE", classes="mh-lamp")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)

    def set_time_base(self, t: float) -> None:
        """Snap mission time to a timeline position; keeps ticking from there."""
        self._base_t = t
        self._base_wall = time.monotonic()
        self._tick()

    def _mission_seconds(self) -> int:
        return int(self._base_t + (time.monotonic() - self._base_wall))

    def _tick(self) -> None:
        elapsed = self._mission_seconds()
        self.query_one(".mh-clock", Static).update(f"T+{elapsed // 60:02d}:{elapsed % 60:02d}")

    def stamp(self) -> str:
        elapsed = self._mission_seconds()
        return f"T+{elapsed // 60:02d}:{elapsed % 60:02d}"

    def set_status(self, text: str, css_class: str = "") -> None:
        lamp = self.query_one(".mh-lamp", Static)
        lamp.update(f"● {text}")
        lamp.remove_class("-paused", "-replanning", "-passed")
        if css_class:
            lamp.add_class(css_class)


class MissionPanel(Vertical):
    """Bordered HUD panel, hidden until its first event reveals it."""

    PANEL_TITLE = ""
    BODY_CLASS = "panel-body"

    def __init__(self, title: str | None = None) -> None:
        super().__init__()
        self._title = title or self.PANEL_TITLE

    def compose(self) -> ComposeResult:
        yield Static(self._title, classes="panel-title")
        yield Static("", classes="panel-body")

    def on_mount(self) -> None:
        self.display = False

    def reveal(self, text: str) -> None:
        self.display = True
        _typewrite(self.query_one(".panel-body", Static), text)

    def clear(self) -> None:
        self.display = False
        self.query_one(".panel-body", Static).update("")


class DeviationAlert(MissionPanel):
    """Big-number deviation readout with a pulsing alert border."""

    PANEL_TITLE = "⚠ DEVIATION DETECTED // 偏差告警"

    def __init__(self) -> None:
        super().__init__()
        self._blink_timer = None

    def show_deviation(self, payload: dict) -> None:
        expected = payload.get("expected", "?")
        measured = payload.get("measured", "?")
        label = payload.get("label", "pH")
        try:
            delta = f"{abs(float(measured) - float(expected)):.2f}"
        except (TypeError, ValueError):
            delta = "?"
        lines = [
            f"EXPECTED {label}   {expected}",
            f"MEASURED {label}   {measured}",
            f"Δ DEVIATION     {delta}",
            "",
            *payload.get("lines", []),
        ]
        self.display = True
        self._blink_timer = self.set_interval(0.55, self._blink)
        _typewrite(self.query_one(".panel-body", Static), "\n".join(lines), interval=0.035)

    def _blink(self) -> None:
        self.toggle_class("-alert-on")

    def clear(self) -> None:
        if self._blink_timer is not None:
            self._blink_timer.stop()
            self._blink_timer = None
        self.remove_class("-alert-on")
        super().clear()


class MissionBrief(MissionPanel):
    PANEL_TITLE = "MISSION BRIEF // 任务"


class ValidationPanel(MissionPanel):
    PANEL_TITLE = "VALIDATION // 验收"


class ExperienceCard(MissionPanel):
    PANEL_TITLE = "EXPERIENCE SAVED // 长期记忆"


class MissionStats(MissionPanel):
    PANEL_TITLE = "MISSION REPORT // 任务报告"


class ReplanStateMachine(Vertical):
    """OBSERVE → PAUSE → DIAGNOSE → REPLAN node strip."""

    def compose(self) -> ComposeResult:
        yield Static("REPLAN LOOP // 纠错闭环", classes="panel-title")
        with Horizontal(classes="sm-nodes"):
            for i, name in enumerate(STATE_STEPS):
                if i:
                    yield Static("─▶", classes="sm-link")
                yield Static(name, classes="sm-node", id=f"sm-{name.lower()}")
        yield Static("", classes="sm-note")

    def on_mount(self) -> None:
        self.display = False

    def set_state(self, step: str, note: str = "") -> None:
        self.display = True
        try:
            current = STATE_STEPS.index(step)
        except ValueError:
            current = -1
        for i, name in enumerate(STATE_STEPS):
            node = self.query_one(f"#sm-{name.lower()}", Static)
            node.remove_class("-done", "-active")
            if i < current:
                node.add_class("-done")
            elif i == current:
                node.add_class("-active")
        note_widget = self.query_one(".sm-note", Static)
        note_widget.update("")
        if note:
            _typewrite(note_widget, f"▶ {note}")

    def clear(self) -> None:
        self.display = False
        for name in STATE_STEPS:
            self.query_one(f"#sm-{name.lower()}", Static).remove_class("-done", "-active")
        self.query_one(".sm-note", Static).update("")


class CommsFeed(Vertical):
    """Scrolling robot communication log; only the newest line is typewritten."""

    def __init__(self) -> None:
        super().__init__()
        self._lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("COMMS // 三方通信", classes="panel-title")
        yield ScrollableContainer(classes="comms-lines")

    def add_comm(self, payload: dict, stamp: str) -> None:
        line = f'[{stamp}] {payload.get("src", "?")} → {payload.get("dst", "?")} : "{payload.get("text", "")}"'
        self._lines.append(line)
        feed = self.query_one(".comms-lines", ScrollableContainer)
        static = Static("", classes="comm-line")
        feed.mount(static)
        self.call_after_refresh(self._type_new_line, feed, static, line)

    def _type_new_line(
        self, feed: ScrollableContainer, static: Static, line: str
    ) -> None:
        _typewrite(static, line)
        feed.scroll_end(animate=False)

    def clear(self) -> None:
        self._lines.clear()
        self.query_one(".comms-lines", ScrollableContainer).remove_children()


class SystemVoice(Static):
    """Bottom subtitle banner for PhyAgentOS voice lines."""

    def on_mount(self) -> None:
        self.display = False

    def say(self, text: str) -> None:
        self.display = True
        _typewrite(self, f"PhyAgentOS ▶ {text}", interval=0.045)

    def clear(self) -> None:
        self.display = False
        self.update("")


class FinaleOverlay(Vertical):
    """Full-screen brand freeze frame."""

    def on_mount(self) -> None:
        self.display = False

    def compose(self) -> ComposeResult:
        yield Static("", classes="finale-title")
        yield Static("", classes="finale-subtitle")
        yield Static("", classes="finale-lines")
        yield Static("", classes="finale-footer")

    def show(self, payload: dict) -> None:
        self.display = True
        _typewrite(self.query_one(".finale-title", Static), payload.get("title", ""), interval=0.12)
        _typewrite(
            self.query_one(".finale-subtitle", Static), payload.get("subtitle", ""), interval=0.05
        )
        _typewrite(
            self.query_one(".finale-lines", Static),
            "\n".join(payload.get("lines", [])),
            interval=0.03,
        )
        _typewrite(
            self.query_one(".finale-footer", Static), payload.get("footer", ""), interval=0.05
        )

    def clear(self) -> None:
        self.display = False
        for cls in ("finale-title", "finale-subtitle", "finale-lines", "finale-footer"):
            self.query_one(f".{cls}", Static).update("")
