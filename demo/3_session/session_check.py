#!/usr/bin/env python3
"""Session 完整性校验 — 模拟 PhyAgentOS 真实闭环中的 Forge session 内容并校验。

对照 PhyAgentOS/verification/contracts.py 的真实契约：
  - ForgeSessionRecord 字段（version/session_id/command_id/root/parent/replan_attempt/
    request/status/时间戳/execution/verification/recovery_request/gateway 响应/error/origin）
  - 状态机 ALLOWED_FORGE_TRANSITIONS（13 态）、TERMINAL_FORGE_STATUSES
  - VerificationVerdict 一致性约束（success 需全 satisfied 等）
  - RecoveryContext（replan_required 必带）、EvidenceArtifact（sha256 64hex）

数据特征（避免"一眼假"）：
  - 时间基准动态（会话发生在 generated_at 之前约 15 分钟内），微秒级时间戳
  - 每个 session 独立时间轴（毫秒抖动、按序错开）
  - session/command id 用 uuid，实例 id / 策略版本 / 字节数 / 文案多样化
  - sha256 与 artifact 内容真实绑定

场景：
  1. 健康闭环 — 6 个物品分选全部成功（6 个 session）
  2. 恢复链闭环 — 牛奶失败 replan_required → child 重试成功（2 个 session）
  3. 注入缺陷 — 与 2 同构但篡改 3 处，校验应逐项识别

Usage:
    python demo/3_session/session_check.py [-o session_result.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------- 真实契约 ---
# PhyAgentOS/verification/contracts.py
TERMINAL_STATUSES = {"replanned", "succeeded", "failed", "timed_out", "cancelled"}
ALLOWED_TRANSITIONS = {
    "accepted": {"capturing_before", "dispatching", "failed", "cancelled"},
    "capturing_before": {"dispatching", "failed", "cancelled"},
    "dispatching": {"running", "finalizing", "failed", "timed_out", "cancelled"},
    "running": {"finalizing", "failed", "timed_out", "cancelled"},
    "finalizing": {"awaiting_verification", "succeeded", "failed", "timed_out", "cancelled"},
    "awaiting_verification": {"verifying", "failed", "cancelled"},
    "verifying": {"awaiting_verification", "awaiting_replan", "succeeded", "failed",
                  "timed_out", "cancelled"},
    "awaiting_replan": {"replanned", "failed", "cancelled"},
}
RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")

# 分选任务执行序列（对应 sorting_session.json 的抓取顺序）
SORTING_ITEMS = [("可乐", "黄色篮子"), ("牛奶", "黄色篮子"), ("雪碧", "黄色篮子"),
                 ("香蕉", "绿色篮子"), ("橙子", "绿色篮子"), ("猕猴桃", "绿色篮子")]

GATEWAYS = [f"gw-{i:02d}" for i in range(1, 9)]
POLICIES = ["forge/planner/v2.1.0", "forge/planner/v2.0.4", "forge/planner/v1.9.2",
            "forge/planner/v2.1.1"]
SUCCESS_REASONS = ["全部成功标准满足，无需恢复",
                   "目标达成，证据完整（before/after 均通过校验）",
                   "命令正常终止，3/3 成功标准满足"]
LESSONS = ["正常执行", "无异常，按计划完成", "证据与执行事实一致"]

BASE: datetime = datetime.now(timezone.utc) - timedelta(minutes=15)  # 运行时重置
_rng = random.Random()


def ts(sec: float) -> str:
    return (BASE + timedelta(seconds=sec)).isoformat(timespec="microseconds")


def new_id() -> str:
    return str(uuid.uuid4())


def sha64(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def make_request(item: str, basket: str, criteria: list[str]) -> dict:
    """ForgeTaskRequest + TaskVerificationContract（contracts.py 字段）。"""
    return {
        "version": "forge_task_request_v1",
        "task_description": f"抓取{item}并放入{basket}",
        "action_type": "pick_and_place",
        "inputs": {"item": item, "source": "桌面", "target": basket},
        "verification": {
            "version": "task_verification_contract_v1",
            "mode": "enforce",
            "goal": f"{item}已放入{basket}",
            "success_criteria": criteria,
            "constraints": ["仅操作目标物品"],
            "evidence_policy": {
                "profile": "semantic_default",
                "required_kinds": ["rgb_image"],
                "required_sources": [],
                "minimum_association": "best_effort",
            },
        },
        "execution_timeout_s": 300.0,
        "source": "paos-agent",
    }


def make_evidence(bundle_id: str, session_id: str, command_id: str, gw: str,
                  times: dict) -> dict:
    """EvidenceBundle：before/after 图像 + SHA-256（绑定内容）+ 质量。"""
    sizes = [150000 + _rng.randint(0, 9000), 147000 + _rng.randint(0, 9000)]
    before_size, after_size = sizes
    win = times["window"]
    return {
        "version": "forge_evidence_bundle_v1",
        "bundle_id": bundle_id,
        "session_id": session_id,
        "command_id": command_id,
        "gateway_instance_id": gw,
        "capture_window": {
            "before_command_at": ts(win["before"]),
            "command_terminal_at": ts(win["terminal"]),
            "after_command_at": ts(win["after"]),
        },
        "artifacts": [
            {"artifact_id": f"{bundle_id}/before.jpg", "phase": "before",
             "kind": "rgb_image", "source_id": "cam-top",
             "received_at": ts(win["before"] + 0.06), "sequence": 0,
             "media_type": "image/jpeg",
             "sha256": sha64(f"{bundle_id}:before:{before_size}"),
             "byte_size": before_size, "uri": f"evidence/{bundle_id}/before.jpg",
             "retained": True},
            {"artifact_id": f"{bundle_id}/after.jpg", "phase": "after",
             "kind": "rgb_image", "source_id": "cam-top",
             "received_at": ts(win["after"] + 0.07), "sequence": 1,
             "media_type": "image/jpeg",
             "sha256": sha64(f"{bundle_id}:after:{after_size}"),
             "byte_size": after_size, "uri": f"evidence/{bundle_id}/after.jpg",
             "retained": True},
        ],
        "quality": {"complete": True, "association_quality": "authoritative",
                    "capture_authority": "paos_forge_adapter",
                    "missing_requirements": [], "stale_artifacts": [], "errors": []},
    }


def make_timeline(start: float) -> dict:
    """单个 session 的独立时间轴（秒，相对 BASE，带毫秒抖动）。"""
    j = lambda: _rng.uniform(0.05, 0.4)
    created = start + j()
    dispatch = created + 1.1 + j()
    terminal = dispatch + 13.5 + j()
    updated = terminal + 0.5 + j()
    return {
        "created": created, "dispatch": dispatch, "terminal": terminal,
        "updated": updated,
        "window": {"before": dispatch - 0.3, "terminal": terminal,
                   "after": terminal + 1.0 + j()},
    }


def make_session(item: str, basket: str, criteria: list[str],
                 timeline: dict, *, parent: str | None = None,
                 replan_attempt: int = 0, root: str | None = None,
                 tamper: dict | None = None) -> tuple[dict, dict]:
    """生成 (ForgeSessionRecord, EvidenceBundle)，id 随机，字段多样化。"""
    t = tamper or {}
    sid, cmd = new_id(), new_id()
    root = root or sid
    gw = _rng.choice(GATEWAYS)
    policy = _rng.choice(POLICIES)
    success = t.get("success", True)

    record = {
        "version": "forge_session_record_v1",
        "session_id": sid,
        "command_id": cmd,
        "root_session_id": root,
        "parent_session_id": parent,
        "replan_attempt": replan_attempt,
        "request": make_request(item, basket, criteria),
        "status": t.get("status", "succeeded" if success else "failed"),
        "created_at": ts(timeline["created"]),
        "updated_at": ts(timeline["updated"]),
        "dispatch_attempted_at": ts(timeline["dispatch"]),
        "terminal_at": ts(timeline["terminal"]),
        "execution": {
            "version": "paos_execution_record_v1",
            "runtime": "forge_gateway",
            "session_id": sid, "command_id": cmd,
            "gateway_api_version": "paos-forge-gateway-mvp-plus.v1",
            "gateway_instance_id": gw,
            "action_type": "pick_and_place", "policy_id": policy,
            "status": t.get("exec_status", "succeeded" if success else "failed"),
            "result_semantics": ("command_completed" if success
                                 else "command_failed"),
            "completion": ({"code": 0, "message": "正常终止"} if success
                           else {"code": 21, "message": "抓取目标丢失"}),
            "timeline": {"created_at": timeline["created"],
                         "updated_at": timeline["updated"],
                         "sent_at": round(timeline["dispatch"] + 0.2, 3),
                         "terminal_observed_at": ts(timeline["terminal"])},
            "outputs": ({"picked": True, "placed_basket": basket} if success
                        else {"picked": False, "placed_basket": None}),
            "error": None if success else {"code": "GRASP_LOST", "message": "pick 失败"},
        },
        "verification": {
            "status": "completed",
            "bundle_ref": f"bundle-{sid}",
            "verdict": {
                "version": "verification_verdict_v1",
                "verdict": t.get("verdict", "success" if success else "failure"),
                "criteria": t.get("criteria", [
                    {"criterion": c, "status": "satisfied",
                     "evidence_refs": [f"bundle-{sid}"]} for c in criteria
                ]),
                "evidence_refs": [f"bundle-{sid}"],
                "reason": (t.get("reason") if t.get("reason")
                           else _rng.choice(SUCCESS_REASONS) if success
                           else f"未满足成功标准: {criteria[0]}"),
                "lesson": _rng.choice(LESSONS),
                "recovery_context": t.get("recovery_context"),
                "verifier_status": "completed",
            },
            "attempts": [{"version": "verification_attempt_v1", "model": "sim",
                          "verdict": t.get("verdict", "success" if success else "failure"),
                          "created_at": ts(timeline["terminal"] + 0.8)}],
            "error": None,
        },
        "recovery_request": t.get("recovery_request"),
        "gateway_create_response": {
            "session_id": sid, "command_id": cmd,
            "request_id": f"req-{new_id()}", "accepted": True,
        },
        "gateway_last_response": {
            "session_id": sid, "command_id": cmd,
            "status": t.get("exec_status", "succeeded" if success else "failed"),
        },
        "before_snapshot_ref": f"bundle-{sid}/before.jpg",
        "completion_notified_at": ts(timeline["updated"] + 0.3),
        "error_code": None if success else "EXEC_FAILED",
        "error_message": None if success else "gateway 执行失败",
        "origin_channel": "cli", "origin_chat_id": "direct",
        "origin_session_key": None,
    }
    bundle = make_evidence(f"bundle-{sid}", sid, cmd, gw, timeline)
    return record, bundle


def make_healthy_scenario() -> dict:
    """场景 1：6 个物品各一个闭环 session，全部成功（完整分选任务）。"""
    flow = ["accepted", "capturing_before", "dispatching", "running", "finalizing",
            "awaiting_verification", "verifying", "succeeded"]
    sessions, evidence = [], []
    for i, (item, basket) in enumerate(SORTING_ITEMS):
        timeline = make_timeline(6.0 + i * 3.2 + _rng.uniform(0, 0.6))
        criteria = [f"{item}已从桌面拿起", f"{item}位于{basket}内", "未触碰其他物品"]
        rec, bundle = make_session(item, basket, criteria, timeline)
        sessions.append(rec)
        evidence.append(bundle)
    return {"name": f"健康闭环 — 6 个物品分选全部成功（{len(sessions)} 个 session）",
            "flow": flow, "sessions": sessions, "evidence": evidence}


def make_recovery_scenario() -> dict:
    """场景 2：牛奶失败 → replan_required → child 重试成功。"""
    criteria = ["牛奶已从桌面拿起", "牛奶位于黄色篮子内", "未触碰其他物品"]

    parent_tl = make_timeline(4.0)
    parent_tamper = {
        "success": False,
        "status": "replanned",
        "exec_status": "failed",
        "verdict": "replan_required",
        "criteria": [
            {"criterion": "牛奶已从桌面拿起", "status": "unsatisfied",
             "evidence_refs": []},
            {"criterion": "牛奶位于黄色篮子内", "status": "unknown",
             "evidence_refs": []},
            {"criterion": "未触碰其他物品", "status": "satisfied",
             "evidence_refs": []},
        ],
        "reason": "pick 失败导致目标未拿起，需要重新规划",
        "recovery_context": {
            "unmet_criteria": ["牛奶已从桌面拿起", "牛奶位于黄色篮子内"],
            "preserved_constraints": ["未触碰其他物品"],
            "guidance": "重新规划 pick 与 place 参数后重试",
        },
    }
    parent, parent_bundle = make_session("牛奶", "黄色篮子", criteria, parent_tl,
                                         tamper=parent_tamper)
    parent["recovery_request"] = {
        "version": "recovery_request_v1",
        "request_id": f"recover-{new_id()}",
        "parent_session_id": parent["session_id"],
        "unmet_criteria": ["牛奶已从桌面拿起", "牛奶位于黄色篮子内"],
        "preserved_constraints": ["未触碰其他物品"],
        "guidance": "重新规划 pick 与 place 参数后重试",
        "evidence_refs": [parent_bundle["bundle_id"]],
        "deadline": ts(parent_tl["terminal"] + 120.0),
        "dispatched_at": ts(parent_tl["terminal"] + 1.2),
    }
    # child 会话在 parent 终止后约 12 秒开始，replan_attempt=1
    child_tl = make_timeline(parent_tl["terminal"] + 12.0)
    child, child_bundle = make_session("牛奶", "黄色篮子", criteria, child_tl,
                                       parent=parent["session_id"], replan_attempt=1,
                                       root=parent["session_id"])

    flow = ["accepted", "capturing_before", "dispatching", "running", "finalizing",
            "awaiting_verification", "verifying", "awaiting_replan", "replanned"]
    child_flow = ["accepted", "capturing_before", "dispatching", "running",
                  "finalizing", "awaiting_verification", "verifying", "succeeded"]
    return {"name": "恢复链闭环 — 牛奶失败 replan → child 重试成功",
            "flow": flow, "child_flow": child_flow,
            "sessions": [parent, child],
            "evidence": [parent_bundle, child_bundle]}


def make_tampered_scenario() -> dict:
    """场景 3：与场景 2 同构，注入 3 处缺陷，校验应逐项识别。"""
    base = make_recovery_scenario()
    child, child_bundle = base["sessions"][1], base["evidence"][1]

    # 缺陷 1: child verdict=success 但存在 unsatisfied criterion
    child["verification"]["verdict"]["criteria"][1] = {
        "criterion": "牛奶位于黄色篮子内", "status": "unsatisfied",
        "evidence_refs": [child_bundle["bundle_id"]],
    }
    # 缺陷 2: child 证据时间窗倒挂（after < terminal）
    win = child_bundle["capture_window"]
    term_dt = datetime.fromisoformat(win["command_terminal_at"])
    after_dt = term_dt - timedelta(seconds=1.4)
    win["after_command_at"] = after_dt.isoformat(timespec="microseconds")
    for art in child_bundle["artifacts"]:
        if art["phase"] == "after":
            art["received_at"] = (after_dt + timedelta(seconds=0.1)).isoformat(
                timespec="microseconds")
    # 缺陷 3: child replan_attempt 未递增（应为 1）
    child["replan_attempt"] = 0
    base["name"] = "注入缺陷 — 与场景 2 同构，3 处篡改"
    return base


# ---------------------------------------------------------------- 校验器 -----
def check_session(rec: dict, evidence: list[dict], flow: list[str]) -> list[dict]:
    """按真实契约逐项校验单个 session 记录。"""
    res: list[dict] = []

    def add(rule: str, desc: str, ok: bool, detail: str = "") -> None:
        res.append({"rule": rule, "desc": desc, "ok": ok, "detail": detail})

    # r1 必填字段
    required = ["session_id", "command_id", "root_session_id", "request",
                "status", "created_at", "updated_at"]
    missing = [f for f in required if not rec.get(f)]
    add("r1", "必填字段完整", not missing, f"缺失: {missing}" if missing else "完整")

    # r2 标识符 path-safe（contracts.py: validate_identifier）
    bad_ids = [v for v in (rec.get("session_id"), rec.get("command_id"),
                           rec.get("root_session_id"))
               if not v or v in {".", ".."} or "/" in v or "\\" in v]
    add("r2", "标识符 path-safe", not bad_ids, f"非法: {bad_ids}" if bad_ids else "合法")

    # r3 状态机转换合法
    illegal = [(a, b) for a, b in zip(flow, flow[1:])
               if b not in ALLOWED_TRANSITIONS.get(a, set())]
    add("r3", "状态机转换合法", not illegal,
        "→".join(flow) if not illegal else f"非法转换: {illegal}")

    # r4 终止状态
    add("r4", "会话终止状态", rec["status"] in TERMINAL_STATUSES,
        f"status={rec['status']}")

    # r5 时间戳单调（created ≤ dispatch ≤ terminal；updated ≥ created）
    created, updated, dispatch = (rec["created_at"], rec["updated_at"],
                                  rec["dispatch_attempted_at"])
    terminal = rec.get("terminal_at")
    monotonic = (created <= updated and created <= dispatch
                 and (terminal is None or (dispatch <= terminal
                                           and created <= terminal)))
    add("r5", "会话时间戳单调", monotonic,
        f"created={created[:26]} dispatch={dispatch[:26]}"
        f" terminal={terminal[:26] if terminal else '-'} updated={updated[:26]}")

    # r6 verdict 一致性（VerificationVerdict validators）
    vd = rec["verification"]["verdict"]
    statuses = [c["status"] for c in vd["criteria"]]
    ok6 = True
    if vd["verdict"] == "success" and any(s != "satisfied" for s in statuses):
        ok6 = False
    if vd["verdict"] in {"failure", "replan_required"} and not any(
            s in {"unsatisfied", "unknown"} for s in statuses):
        ok6 = False
    if vd["verdict"] == "replan_required" and not vd.get("recovery_context"):
        ok6 = False
    add("r6", "verdict 与 criteria 一致性", ok6,
        f"verdict={vd['verdict']} statuses={statuses}")

    # r7 证据完整性
    bundle = next((e for e in evidence
                   if e["bundle_id"] == rec["verification"]["bundle_ref"]), None)
    if bundle is None:
        add("r7", "证据 bundle 存在", False, "未找到 bundle")
    else:
        arts = bundle["artifacts"]
        phases = {a["phase"] for a in arts}
        bad_sha = [a["artifact_id"] for a in arts
                   if not RE_SHA256.match(a["sha256"])]
        win = bundle["capture_window"]
        window_ok = (win["before_command_at"] <= win["command_terminal_at"]
                     <= win["after_command_at"])
        add("r7", "证据完整性（sha256/前后配对/时间窗）",
            {"before", "after"} <= phases and not bad_sha and window_ok,
            f"phases={sorted(phases)} sha违规={bad_sha} 时间窗={'ok' if window_ok else '倒挂'}")

    # r8 执行记录与会话状态一致
    ex = rec["execution"]
    ok8 = (rec["status"] == "succeeded") == (ex["status"] == "succeeded")
    add("r8", "execution 与 session 状态一致", ok8,
        f"session={rec['status']} execution={ex['status']}")

    # r9 恢复链（child.replan_attempt=parent+1、parent 指向、root 一致）
    if rec.get("parent_session_id"):
        parents = [s for s in ALL_SESSIONS if s["session_id"] == rec["parent_session_id"]]
        p = parents[0] if parents else None
        ok9 = (p is not None and rec["replan_attempt"] == p["replan_attempt"] + 1
               and rec["root_session_id"] == p["root_session_id"])
        add("r9", "恢复链（replan_attempt 递增/parent/root）", ok9,
            f"parent={rec['parent_session_id']} replan={rec['replan_attempt']}"
            f" parent_replan={p['replan_attempt'] if p else '?'}")
    else:
        add("r9", "恢复链（根会话无 parent）", True, "根会话")

    # r10 replanned 必须带 recovery_request
    ok10 = (rec["status"] != "replanned") or rec.get("recovery_request") is not None
    add("r10", "replanned 携带 recovery_request", ok10,
        "有" if rec.get("recovery_request") else "无")

    # r11 gateway 身份一致性
    create, last = rec["gateway_create_response"], rec["gateway_last_response"]
    ok11 = (create["session_id"] == rec["session_id"]
            and create["command_id"] == rec["command_id"]
            and last["session_id"] == rec["session_id"]
            and last["command_id"] == rec["command_id"])
    add("r11", "gateway 身份一致性", ok11,
        f"create=({create['session_id'][:8]}..,{create['command_id'][:8]}..) "
        f"record=({rec['session_id'][:8]}..,{rec['command_id'][:8]}..)")

    return res


def run_checks(scenario: dict) -> dict:
    global ALL_SESSIONS
    ALL_SESSIONS = scenario["sessions"]
    all_checks: list[dict] = []
    for rec in scenario["sessions"]:
        flow = scenario.get("flow", [])
        if rec.get("parent_session_id") and scenario.get("child_flow"):
            flow = scenario["child_flow"]
        checks = check_session(rec, scenario["evidence"], flow)
        for c in checks:
            c["session_id"] = rec["session_id"]
        all_checks.extend(checks)
    passed = sum(1 for c in all_checks if c["ok"])
    failed = len(all_checks) - passed
    return {
        "name": scenario["name"],
        "sessions": scenario["sessions"],
        "evidence": scenario["evidence"],
        "checks": all_checks,
        "summary": {"passed": passed, "failed": failed,
                    "verdict": "complete" if failed == 0 else "integrity_breach"},
    }


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser(description="session 完整性校验 → JSON")
    parser.add_argument("-o", "--out", default=str(Path(__file__).parent / "session_result.json"))
    parser.add_argument("--seed", type=int, default=20260820)
    args = parser.parse_args()

    BASE = datetime.now(timezone.utc) - timedelta(minutes=15)
    _rng.seed(args.seed)

    scenarios = [make_healthy_scenario(), make_recovery_scenario(),
                 make_tampered_scenario()]
    results = [run_checks(s) for s in scenarios]

    payload = {
        "task": "Forge session 完整性校验（模拟真实闭环）",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "contract_source": "PhyAgentOS/verification/contracts.py",
        "scenarios": results,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    for r in results:
        s = r["summary"]
        print(f"[{s['verdict']}] {r['name']} — {s['passed']}/{s['passed'] + s['failed']} 项通过")
    for c in [c for r in results for c in r["checks"] if not c["ok"]]:
        print(f"  ✗ {c['rule']} {c['session_id'][:8]}…: {c['desc']} — {c['detail']}")
    print(f"结果已保存: {args.out}")


ALL_SESSIONS: list[dict] = []


if __name__ == "__main__":
    main()
