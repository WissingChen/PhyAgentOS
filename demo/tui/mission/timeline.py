"""Timeline loading and step/auto playback for demo shoots."""

import json
from pathlib import Path

from mission.events import MissionEvent

DEFAULT_TIMELINE = Path(__file__).parent / "replan3.json"


class Timeline:
    """An ordered list of (t_seconds, MissionEvent) with a play cursor."""

    def __init__(self, steps: list[tuple[float, MissionEvent]]):
        self.steps = steps
        self.index = 0

    @classmethod
    def load(cls, path: str | None = None) -> "Timeline":
        if path:
            text = Path(path).expanduser().read_text(encoding="utf-8")
        else:
            text = DEFAULT_TIMELINE.read_text(encoding="utf-8")
        raw = json.loads(text)
        steps = [
            (
                float(step.get("t", 0.0)),
                MissionEvent(kind=step["event"]["kind"], payload=step["event"].get("payload", {})),
            )
            for step in raw
        ]
        return cls(steps)

    @property
    def total(self) -> int:
        return len(self.steps)

    @property
    def done(self) -> bool:
        return self.index >= len(self.steps)

    def peek(self) -> tuple[float, MissionEvent] | None:
        if self.done:
            return None
        return self.steps[self.index]

    def advance(self) -> tuple[float, MissionEvent] | None:
        step = self.peek()
        if step is not None:
            self.index += 1
        return step

    def reset(self) -> None:
        self.index = 0
