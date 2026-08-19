#!/usr/bin/env python3
"""分选任务成功率统计 — 模拟 PhyAgentOS agent 思考流程。

读取 demo/cli/sorting_session.json 的对话文本（桌面物品、分类规则、抓取序列），
按 PhyAgentOS 真实流程逐轮模拟并统计任务成功率：

    感知 → Planner 分类规划 → Forge 命令逐条执行（pick/place）
    → 证据采集（before/after + SHA-256）→ TaskVerifier 判定
    → 失败触发 Planner-owned recovery（重试）→ 统计

Usage:
    python demo/2_sr_count/sr_count.py [--config demo/cli/sorting_session.json]
                                      [--runs 2000] [--op-success 0.92]
                                      [--retries 1] [--seed 42] [--verbose]
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "cli" / "sorting_session.json"

RE_ITEMS = re.compile(r"桌面上存在(.+?)(?=[。，,]|$)")
RE_CATEGORY = re.compile(r"属于(.+?)的有(.+?)(?=[。，,]|$)")
RE_PICK = re.compile(r"(?:先拿取|继续拿取)(.+?)并?放在(.+?)篮子里")

# PhyAgentOS verifier 判词（参考 PhyAgentOS/verification/contracts.py）
VERDICT_NAMES = ("success", "failure", "replan_required", "inconclusive")


@dataclass
class Item:
    name: str
    category: str
    basket: str  # 计划目标篮子


@dataclass
class OpOutcome:
    item: str
    basket: str
    command_id: str
    success: bool
    attempts: int
    evidence_sha: str


@dataclass
class Criterion:
    criterion: str
    status: str  # satisfied | unsatisfied | unknown
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class RoundOutcome:
    run: int
    session_id: str
    verdict: str
    reason: str
    criteria: list[Criterion]
    ops: list[OpOutcome]
    replans: int


def parse_config(cfg: dict) -> tuple[list[Item], list[tuple[str, str]]]:
    """从对话文本抽取物品（含分类与目标篮子）和抓取序列。

    句式来自 sorting_session.json:
      桌面上存在可乐、橙子、...          → 物品清单
      属于饮料的有可乐、牛奶、雪碧        → 分类规则
      先拿取可乐并放在黄色篮子里          → 抓取序列
    """
    items: list[str] = []
    categories: dict[str, list[str]] = {}
    sequence: list[tuple[str, str]] = []

    for r in cfg.get("reply", []):
        m = RE_ITEMS.search(r["text"])
        if m:
            items = [s for s in re.split(r"[、，,]", m.group(1)) if s]
        m = RE_CATEGORY.search(r["text"])
        if m:
            categories[m.group(1).strip()] = [
                s for s in re.split(r"[、，,]", m.group(2)) if s
            ]
        m = RE_PICK.search(r["text"])
        if m:
            sequence.append((m.group(1).strip(), m.group(2).strip()))

    if not items or not sequence:
        raise ValueError("无法从配置中解析物品或抓取序列，请检查句式是否匹配")

    basket_of: dict[str, str] = {}
    for name in items:
        cat = next((c for c, names in categories.items() if name in names), "未知")
        basket = next((b for n, b in sequence if n == name), "")
        basket_of[name] = basket

    return [Item(n, next((c for c, ns in categories.items() if n in ns), "未知"),
                 basket_of.get(n, "")) for n in items], sequence


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def simulate(cfg: dict, runs: int, op_success: float, retries: int,
             rng: random.Random, verbose: bool) -> tuple[list[RoundOutcome], dict]:
    items, sequence = parse_config(cfg)

    stats = {
        "verdicts": {v: 0 for v in VERDICT_NAMES},
        "op_attempts": 0, "op_ok": 0,
        "item_ok": {it.name: 0 for it in items},
        "item_attempts": {it.name: 0 for it in items},
        "replans_total": 0,
    }
    outcomes: list[RoundOutcome] = []

    items_by_name = {it.name: it for it in items}
    # 执行顺序按 JSON 抓取序列（先饮料后水果），篮子取自序列
    plan = [(n, b) for n, b in sequence]

    for run in range(1, runs + 1):
        session_id = f"sort-{run:04d}"
        ops: list[OpOutcome] = []
        replans = 0

        # ---- Planner: 分类规划 ------------------------------------------------
        if verbose and run == 1:
            print(f"\n=== run 1 · session={session_id} ===")
            print("[感知] 桌面物品:", " ".join(it.name for it in items))
            print("[Planner] 分类规则:", {it.name: it.category for it in items})
            print("[Planner] 计划:", " → ".join(
                f"pick({n})→place({b})" for n, b in plan))

        # ---- Forge: 逐命令执行，失败触发 Planner-owned recovery ----------------
        for item, basket in plan:
            attempts = 0
            ok = False
            while not ok and attempts <= retries:
                attempts += 1
                stats["op_attempts"] += 1
                stats["item_attempts"][item] += 1
                cmd_id = f"c-{run:04d}-{item}"
                evidence_sha = sha256_of(f"{session_id}/{cmd_id}/v{attempts}")
                ok = rng.random() < op_success
                if not ok and attempts <= retries:
                    replans += 1  # verifier 判 replan_required → Planner 重试
                if verbose and run == 1:
                    print(f"[Forge] {cmd_id} · pick({item})→place({basket}) "
                          f"· 第{attempts}次 {'成功' if ok else '失败'}")
                if ok:
                    print(f"[证据] before/after 图像通过校验 · sha256={evidence_sha}") \
                        if verbose and run == 1 else None
            stats["op_ok"] += ok
            stats["item_ok"][item] += ok
            ops.append(OpOutcome(item, basket, cmd_id, ok, attempts, evidence_sha))

        # ---- TaskVerifier: 逐 criterion 判定（参考 contracts.py） --------------
        ok_names = {o.item for o in ops if o.success}
        criteria = [
            Criterion("全部目标物品已被抓取",
                      "satisfied" if all(o.success for o in ops) else "unsatisfied",
                      [f"evidence:{o.evidence_sha}" for o in ops]),
            Criterion("每个物品放入正确篮子",
                      "satisfied" if all(
                          o.success and o.basket == items_by_name[o.item].basket
                          for o in ops) else "unsatisfied"),
            Criterion("分类判定无未知类别",
                      "satisfied" if all(it.category != "未知" for it in items)
                      else "unknown"),
        ]
        n_sat = sum(c.status == "satisfied" for c in criteria)
        n_unsat = sum(c.status == "unsatisfied" for c in criteria)

        if n_unsat == 0 and n_sat == len(criteria):
            verdict, reason = "success", "全部成功标准满足"
        elif replans > 0 and n_unsat > 0:
            # 重试已在本轮内消化；仍失败则判 failure
            verdict, reason = "failure", "存在未满足的成功标准"
        else:
            verdict, reason = "failure", "存在未满足的成功标准"

        stats["verdicts"][verdict] += 1
        stats["replans_total"] += replans
        outcomes.append(RoundOutcome(run, session_id, verdict, reason,
                                     criteria, ops, replans))

        if verbose and run == 1:
            for c in criteria:
                print(f"[Verifier] criterion={c.criterion!r} status={c.status}")
            print(f"[Verifier] verdict={verdict} · reason={reason}")

    return outcomes, stats


def report(cfg_path: Path, runs: int, op_success: float, retries: int,
           seed: int, outcomes: list[RoundOutcome], stats: dict) -> None:
    total = len(outcomes)
    success = stats["verdicts"]["success"]
    print("\n=== 分选任务成功率统计 ===")
    print(f"配置: {cfg_path} · runs={runs} · 单次操作成功率={op_success:.2f} "
          f"· 失败重试={retries} · seed={seed}")
    print(f"任务成功率: {success / total:.1%} ({success}/{total})")
    print("verdict 分布:", " · ".join(f"{v}={stats['verdicts'][v]}" for v in VERDICT_NAMES))
    op_rate = stats["op_ok"] / stats["op_attempts"] if stats["op_attempts"] else 0
    print(f"操作: 尝试 {stats['op_attempts']} · 成功 {stats['op_ok']} · "
          f"操作成功率 {op_rate:.1%}")
    print("按物品成功率:", " | ".join(
        f"{n} {stats['item_ok'][n] / stats['item_attempts'][n]:.1%}"
        for n in stats["item_ok"]))
    print(f"重规划(replan)总次数: {stats['replans_total']} · "
          f"平均每轮 {stats['replans_total'] / total:.2f}")


def save_json(out: str, args: argparse.Namespace, stats: dict,
              outcomes: list[RoundOutcome]) -> None:
    """统计结果与每轮明细序列化为 JSON。"""
    total = len(outcomes)
    payload = {
        "task": "分选任务成功率统计",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "config": {
            "config_path": args.config,
            "runs": args.runs,
            "op_success": args.op_success,
            "retries": args.retries,
            "seed": args.seed,
        },
        "summary": {
            "task_success": stats["verdicts"]["success"],
            "task_success_rate": round(stats["verdicts"]["success"] / total, 4),
            "verdicts": stats["verdicts"],
            "op_attempts": stats["op_attempts"],
            "op_ok": stats["op_ok"],
            "op_success_rate": round(stats["op_ok"] / stats["op_attempts"], 4),
            "item_success_rate": {
                n: round(stats["item_ok"][n] / stats["item_attempts"][n], 4)
                for n in stats["item_ok"]
            },
            "replans_total": stats["replans_total"],
            "replans_avg": round(stats["replans_total"] / total, 4),
        },
        "rounds": [dataclasses.asdict(o) for o in outcomes],
    }
    Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"结果已保存: {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="分选任务成功率统计（模拟 PhyAgentOS 流程）")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="会话 JSON 路径")
    parser.add_argument("--runs", type=int, default=30, help="模拟轮数")
    parser.add_argument("--op-success", type=float, default=0.92, help="单次操作成功率")
    parser.add_argument("--retries", type=int, default=1, help="失败重试次数")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", action="store_true", help="打印第一轮完整思考流程")
    parser.add_argument("-o", "--out", default=str(Path(__file__).parent / "sr_results.json"),
                        help="结果 JSON 输出路径")
    args = parser.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    rng = random.Random(args.seed)
    outcomes, stats = simulate(cfg, args.runs, args.op_success, args.retries, rng,
                               verbose=args.verbose)
    report(Path(args.config), args.runs, args.op_success, args.retries,
           args.seed, outcomes, stats)
    save_json(args.out, args, stats, outcomes)


if __name__ == "__main__":
    main()
