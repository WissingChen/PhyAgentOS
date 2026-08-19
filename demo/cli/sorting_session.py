"""分选任务会话时间线 — 从 JSON 配置读取，按时间戳渲染。

与 timeline.py 同构：事件 (t, kind, payload)，由 render_demo.build_frame 消费。
流程: $ python -m PhyAgentOS agent → 横幅 → You: 输入分选任务
      → spinner → ↳ 进度提示 → 🍞 PhyAgentOS 回复（分选流程逐句输出）

JSON 字段（见 sorting_session.json）:
  shell_cmd / shell_cps    shell 命令与打字速度
  banner                   启动横幅（纯文本）
  user_msg / user_cps      用户输入与打字速度
  hints                    进度提示，time 为相对 spinner 开始的秒数
  reply                    回复逐句，time 为相对回复开始的秒数
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from timeline import _type_times

DEFAULT_CONFIG = Path(__file__).parent / "sorting_session.json"


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_schedule(config: dict | None = None,
                   rng: random.Random | None = None) -> tuple[list[tuple], float]:
    """构建 (events, total)。events 为 (时间戳, 事件, 内容) 三元组。"""
    if config is None:
        config = load_config()
    rng = rng or random.Random(7)
    ev: list[tuple] = []

    # -- shell command ------------------------------------------------------
    shell = config["shell_cmd"]
    t = 0.15
    ev.append((t, "input_start", [("$ ", "green")]))
    for ts, ch in zip(_type_times(t, shell, config.get("shell_cps", 16), rng), shell):
        ev.append((ts, "input_char", ch))
    t = max(ts for ts, _, _ in ev) + 0.3
    ev.append((t, "input_submit", None))

    # -- banner ---------------------------------------------------------------
    t += 0.15
    ev.append((t, "print", [[(config["banner"], "fg")]]))

    # -- user turn -------------------------------------------------------------
    user = config["user_msg"]
    t += 0.55
    ev.append((t, "input_start", [("You:", "blue"), (" ", "fg")]))
    for ts, ch in zip(_type_times(t, user, config.get("user_cps", 10), rng), user):
        ev.append((ts, "input_char", ch))
    t = max(ts for ts, _, _ in ev) + 0.2
    ev.append((t, "input_submit", None))
    ev.append((t, "spinner_on", None))

    # -- hints (time 相对 spinner 开始) ----------------------------------------
    for hint in config["hints"]:
        ev.append((t + hint["time"], "hint",
                   [("  ↳ ", "dim"), (hint["text"], "dim")]))

    # -- reply (time 相对回复开始) ----------------------------------------------
    reply_start = t + max(h["time"] for h in config["hints"]) + 1.0
    ev.append((reply_start, "spinner_off", None))
    ev.append((reply_start, "print", [[("🍞 ", "cyan"), ("PhyAgentOS", "cyan")]]))
    for r in config["reply"]:
        ev.append((reply_start + r["time"], "print", [[(r["text"], "fg")]]))

    total = reply_start + max(r["time"] for r in config["reply"]) + 1.5
    ev.sort(key=lambda e: e[0])
    return ev, total
