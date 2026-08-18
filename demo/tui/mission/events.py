"""Mission event protocol shared by the demo timeline player and the real system."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MissionEvent:
    """One HUD beat: a kind plus its payload."""

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
