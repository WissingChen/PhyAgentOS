"""Scripted conversation timeline for the `paos agent` CLI demo.

Replicates the real interactive flow from PhyAgentOS/cli/commands.py:
  $ python -m PhyAgentOS agent
  🍞 Interactive mode (type exit or Ctrl+C to quit)
  You: <input>            (bold blue, prompt_toolkit)
  ⠋ PhyAgentOS is thinking...   (Rich console.status spinner, dim)
    ↳ progress hints      (dim, printed above the spinner line)
  🍞 PhyAgentOS           (cyan response header)
  <markdown body>

Each event is (t, kind, payload). All times are absolute seconds.
"""

from __future__ import annotations

import random

# ---------------------------------------------------------------------------
# Span styles: plain text plus a style key consumed by the renderer.
# ("text", "fg" | "dim" | "bold" | "blue" | "cyan" | "green" | "code" | "cmd")
# ---------------------------------------------------------------------------

SHELL_CMD = "python -m PhyAgentOS agent"
USER_MSG = "帮我把桌上的红色杯子拿到卧室床头柜上"
EXIT_MSG = "exit"

HINTS = [
    "  ↳ Planner: 高层计划 pick(red_cup) → place(red_cup, nightstand)",
    "  ↳ Forge command 已提交 · session 8f3a-c01d · 等待执行",
    "  ↳ 执行完成 · 证据采集: before/after 图像通过校验",
    "  ↳ 验证通过: 3/3 criteria · goal achieved",
]

RESPONSE = [
    # list of lines; each line is a list of (text, style) spans
    [],
    [("🍞 ", "cyan"), ("PhyAgentOS", "cyan")],
    [("✅ ", "fg"), ("任务完成", "bold"), ("：红色杯子已放到卧室床头柜上", "fg")],
    [],
    [("- ", "fg"), ("执行", "bold"), (": ", "fg"), ("pick(red_cup)", "code"),
     (" → ", "fg"), ("place(red_cup, nightstand)", "code"),
     ("，Forge Gateway 确认正常终止", "fg")],
    [("- ", "fg"), ("证据", "bold"), (": ", "fg"), ("before/after", "code"),
     (" 图像 2 张已采集并通过校验（SHA-256 存档）", "fg")],
    [("- ", "fg"), ("判定", "bold"), (": ", "fg"), ("3/3", "code"),
     (" 成功标准通过，无需恢复", "fg")],
]

SPINNER_TEXT = "PhyAgentOS is thinking..."
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"  # Rich "dots" default: 10 frames, 80ms interval


def _type_times(start: float, text: str, cps: float, rng: random.Random) -> list[float]:
    """Per-character timestamps with slight jitter, like real typing."""
    out, t = [], start
    for _ in text:
        t += max(0.02, rng.expovariate(cps))
        out.append(t)
    return out


def build_schedule() -> tuple[list[tuple], float]:
    """Return (events, total_duration).

    Event kinds:
      print        payload: list of lines (each a list of spans)
      input_start  payload: prefix spans for the editable input line
      input_char   payload: one character appended to the input line
      input_submit payload: None (freeze the input line)
      spinner_on   / spinner_off
      hint         payload: one line (spans), inserted above the spinner
    """
    rng = random.Random(42)
    ev: list[tuple] = []

    # -- shell command ------------------------------------------------------
    t = 0.15
    ev.append((t, "input_start", [("$ ", "green")]))
    for ts, ch in zip(_type_times(t, SHELL_CMD, 16, rng), SHELL_CMD):
        ev.append((ts, "input_char", ch))
    t = max(ts for ts, _, _ in ev) + 0.3
    ev.append((t, "input_submit", None))

    # -- banner (console.print(f"{logo} Interactive mode ...") + trailing \n) --
    t += 0.15
    ev.append((t, "print", [
        [("🍞 ", "fg"),
         ("Interactive mode (type ", "fg"), ("exit", "bold"),
         (" or ", "fg"), ("Ctrl+C", "bold"), (" to quit)", "fg")],
        [],
    ]))

    # -- first user turn ------------------------------------------------------
    t += 0.5
    ev.append((t, "input_start", [("You:", "blue"), (" ", "fg")]))
    type_end = max(_type_times(t, USER_MSG, 10, rng))  # CJK typed slower
    for ts, ch in zip(_type_times(t, USER_MSG, 10, rng), USER_MSG):
        ev.append((ts, "input_char", ch))
    t = type_end + 0.2
    ev.append((t, "input_submit", None))
    ev.append((t, "spinner_on", None))

    # hints appear while the spinner is running
    for hint in HINTS:
        t += 1.15 + rng.random() * 0.35
        ev.append((t, "hint", [("  ↳ ", "dim"), (hint.strip(), "dim")]))

    # -- response -------------------------------------------------------------
    t += 0.9
    ev.append((t, "spinner_off", None))
    for i, line in enumerate(RESPONSE):
        ev.append((t + 0.08 + i * 0.09, "print", [line]))

    # -- exit -----------------------------------------------------------------
    t += len(RESPONSE) * 0.09 + 1.4
    ev.append((t, "input_start", [("You:", "blue"), (" ", "fg")]))
    type_end = max(_type_times(t, EXIT_MSG, 5, rng))
    for ts, ch in zip(_type_times(t, EXIT_MSG, 5, rng), EXIT_MSG):
        ev.append((ts, "input_char", ch))
    t = type_end + 0.25
    ev.append((t, "input_submit", None))
    ev.append((t, "print", [[], [("Goodbye!", "fg")]]))

    total = t + 2.0
    ev.sort(key=lambda e: e[0])
    return ev, total
