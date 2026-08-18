"""Standalone entry for the REPLAN³ Mission HUD demo (MOSS style).

Usage:
    python demo/tui/run_demo.py [--timeline path/to/timeline.json]

All demo code lives under demo/; the production package is untouched.
Keys: SPACE/→ next beat · ← prev · A autoplay · R reset · Q/Esc quit.
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from textual.binding import Binding  # noqa: E402
from textual.theme import Theme  # noqa: E402

import PhyAgentOS.tui.app as tui_app  # noqa: E402
from PhyAgentOS.tui.app import PhyAgentOSApp  # noqa: E402
from mission_screen import MissionScreen  # noqa: E402

MOSS = Theme(
    name="moss",
    primary="#ffa028",
    secondary="#8a5a19",
    accent="#ffc25e",
    foreground="#ffd9a0",
    background="#050505",
    surface="#0d0b08",
    panel="#14110b",
    boost="#2a2214",
    success="#35c759",
    warning="#ffb340",
    error="#ff4a3d",
    dark=True,
)


class MissionDemoApp(PhyAgentOSApp):
    """Base TUI shell running only the mission HUD, with demo CSS layered on top.

    Textual dispatches on_mount to every class in the MRO, so the base
    class's startup side effects are neutralized by overriding the called
    methods instead of on_mount itself.
    """

    CSS_PATH = [Path(tui_app.__file__).parent / "styles.tcss", HERE / "mission.tcss"]
    BINDINGS = [Binding("escape", "back_or_quit", "Quit")]

    def __init__(self, timeline_path: str | None = None):
        super().__init__()
        self.register_theme(MOSS)
        self._timeline_path = timeline_path

    def on_mount(self) -> None:
        self.theme = "moss"
        self.push_screen(MissionScreen(timeline_path=self._timeline_path, demo=True))

    def _start_gateway(self) -> None:
        """Demo runs offline; no gateway."""

    def switch_to_chat(self) -> None:
        """Stay on the mission HUD."""

    async def restart_gateway(self) -> None:
        """Demo runs offline; no gateway."""

    def action_back_or_quit(self) -> None:
        self.exit()


def main() -> None:
    parser = argparse.ArgumentParser(description="REPLAN³ Mission HUD demo")
    parser.add_argument("--timeline", default=None, help="Custom mission timeline JSON")
    args = parser.parse_args()
    MissionDemoApp(timeline_path=args.timeline).run()


if __name__ == "__main__":
    main()
