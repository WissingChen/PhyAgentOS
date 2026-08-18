"""REPLAN³ Mission HUD screen (MOSS style, clean mode for screen recording)."""

import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Static

from mission.events import MissionEvent
from mission.timeline import Timeline
from mission.widgets import (
    CommsFeed,
    DeviationAlert,
    ExperienceCard,
    FinaleOverlay,
    MissionBrief,
    MissionHeader,
    MissionStats,
    ReplanStateMachine,
    SystemVoice,
    ValidationPanel,
)


class MissionScreen(Screen):
    """Full-screen mission HUD driven by a step/auto-played timeline."""

    BINDINGS = [
        Binding("space", "next_beat", "Next", show=False),
        Binding("enter", "next_beat", show=False),
        Binding("right", "next_beat", show=False),
        Binding("left", "prev_beat", show=False),
        Binding("a", "autoplay", show=False),
        Binding("r", "reset", show=False),
        Binding("q", "quit_demo", show=False),
    ]

    def __init__(self, timeline_path: str | None = None, demo: bool = True) -> None:
        super().__init__()
        self._timeline = Timeline.load(timeline_path)
        self._demo = demo
        self._auto_task: asyncio.Task | None = None
        self._prev_theme: str | None = None

    def compose(self) -> ComposeResult:
        yield MissionHeader()
        with Horizontal(id="mission-main"):
            with Vertical(id="mission-left"):
                yield MissionBrief()
                yield DeviationAlert()
                yield ValidationPanel()
                yield ExperienceCard()
            with Vertical(id="mission-right"):
                yield ReplanStateMachine()
                yield CommsFeed()
                yield MissionStats()
        yield SystemVoice()
        yield Static("", id="mission-hint")
        yield FinaleOverlay()

    def on_mount(self) -> None:
        self._prev_theme = self.app.theme
        self.app.theme = "moss"
        self._update_hint()

    def on_unmount(self) -> None:
        self._stop_autoplay()
        if self._prev_theme and not self._demo:
            self.app.theme = self._prev_theme

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def action_next_beat(self) -> None:
        self._stop_autoplay()
        step = self._timeline.advance()
        if step is not None:
            self.apply_event(step[1], t=step[0])
        self._update_hint()

    def action_prev_beat(self) -> None:
        self._stop_autoplay()
        target = max(0, self._timeline.index - 1)
        steps = self._timeline.steps[:target]
        self._reset_hud()
        self._timeline.reset()
        for t, event in steps:
            self.apply_event(event, t=t)
            self._timeline.advance()
        if not steps:
            self.query_one(MissionHeader).set_time_base(0.0)
        self._update_hint()

    def action_reset(self) -> None:
        self._stop_autoplay()
        self._reset_hud()
        self._timeline.reset()
        self.query_one(MissionHeader).set_time_base(0.0)
        self._update_hint()

    def action_autoplay(self) -> None:
        if self._auto_task is not None:
            self._stop_autoplay()
        else:
            self._auto_task = asyncio.create_task(self._autoplay())

    def action_quit_demo(self) -> None:
        if self._demo:
            self.app.exit()
        else:
            self.app.switch_to_chat()

    async def _autoplay(self) -> None:
        last_t = 0.0
        try:
            while True:
                step = self._timeline.peek()
                if step is None:
                    break
                t, _ = step
                await asyncio.sleep(max(0.0, t - last_t))
                last_t = t
                self._timeline.advance()
                self.apply_event(step[1], t=t)
                self._update_hint()
        except asyncio.CancelledError:
            pass
        finally:
            self._auto_task = None

    def _stop_autoplay(self) -> None:
        if self._auto_task is not None:
            self._auto_task.cancel()
            self._auto_task = None

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    def apply_event(self, event: MissionEvent, t: float = 0.0) -> None:
        self.query_one(MissionHeader).set_time_base(t)
        handler = getattr(self, f"_on_{event.kind}", None)
        if handler is not None:
            handler(event.payload)

    def _on_deviation(self, payload: dict) -> None:
        self.query_one(DeviationAlert).show_deviation(payload)
        self.query_one(MissionHeader).set_status("PAUSED", "-paused")

    def _on_voice(self, payload: dict) -> None:
        self.query_one(SystemVoice).say(payload.get("text", ""))

    def _on_voice_clear(self, payload: dict) -> None:
        self.query_one(SystemVoice).clear()

    def _on_brief(self, payload: dict) -> None:
        self.query_one(MissionBrief).reveal("\n".join(payload.get("lines", [])))

    def _on_comm(self, payload: dict) -> None:
        stamp = self.query_one(MissionHeader).stamp()
        self.query_one(CommsFeed).add_comm(payload, stamp)

    def _on_state(self, payload: dict) -> None:
        self.query_one(ReplanStateMachine).set_state(payload.get("step", ""), payload.get("note", ""))
        if payload.get("step") == "REPLAN":
            self.query_one(MissionHeader).set_status("REPLANNING", "-replanning")

    def _on_validation(self, payload: dict) -> None:
        self.query_one(ValidationPanel).reveal("\n".join(payload.get("lines", [])))
        self.query_one(MissionHeader).set_status("RESUMED")

    def _on_stats(self, payload: dict) -> None:
        self.query_one(MissionStats).reveal("\n".join(payload.get("lines", [])))
        self.query_one(MissionHeader).set_status("PASSED", "-passed")

    def _on_experience(self, payload: dict) -> None:
        self.query_one(ExperienceCard).reveal("\n".join(payload.get("lines", [])))

    def _on_finale(self, payload: dict) -> None:
        self.query_one(FinaleOverlay).show(payload)

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def _reset_hud(self) -> None:
        for widget in (
            MissionBrief,
            DeviationAlert,
            ValidationPanel,
            ExperienceCard,
            MissionStats,
            ReplanStateMachine,
            CommsFeed,
            SystemVoice,
            FinaleOverlay,
        ):
            self.query_one(widget).clear()
        self.query_one(MissionHeader).set_status("LIVE")

    def _update_hint(self) -> None:
        hint = self.query_one("#mission-hint", Static)
        if self._timeline.done:
            hint.update("■ TIMELINE END — r reset")
        else:
            hint.update(f"▶ next {self._timeline.index + 1}/{self._timeline.total}")
