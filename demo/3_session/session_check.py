#!/usr/bin/env python3
"""Session 完整性校验 — 模拟 PhyAgentOS 真实闭环中的 Forge session 内容并校验。

对照 PhyAgentOS/verification/contracts.py 的真实契约：
  - ForgeSessionRecord 字段（version/session_id/command_id/root/parent/replan_attempt/
    request/status/时间戳/execution/verification/recovery_request/gateway 响应/error/origin）
  - 状态机 ALLOWED_FORGE_TRANSITIONS（13 态）
  - TERMINAL_FORGE_STATUSES
  - VerificationVerdict 一致性约束（success 需全 satisfied 等）
  - RecoveryContext（replan_required 必带）
  - EvidenceArtifact（sha256 64hex、phase before/during/after）

场景：
  1. 健康闭环 — 主 session A 一次 pick/place 全程成功
  2. 恢复链闭环 — A 执行失败 → replan_required → child C 重试成功
  3. 注入缺陷 — 与 2 同构但篡改 3 处（verdict 不一致 / 证据时间窗倒挂 /
     child replan_attempt 未递增），校验应逐项识别

Usage:
    python demo/3_session/session_check.py [-o session_result.json]
"""

from __future__ import annotations

import argparse
import json
import re
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
T0 = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)


def ts(sec: float) -> str:
    return (T0 + timedelta(seconds=sec)).isoformat()


def sha64(seed: str) -> str:
    import hashlib
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


def make_evidence(bundle_id: str, session_id: str, command_id: str,
                  before_at: float, terminal_at: float, after_at: float) -> dict:
    """EvidenceBundle：before/after 图像 + SHA-256 + 质量（contracts.py）。"""
    return {
        "version": "forge_evidence_bundle_v1",
        "bundle_id": bundle_id,
        "session_id": session_id,
        "command_id": command_id,
        "gateway_instance_id": "gw-01",
        "capture_window": {
            "before_command_at": ts(before_at),
            "command_terminal_at": ts(terminal_at),
            "after_command_at": ts(after_at),
        },
        "artifacts": [
            {"artifact_id": f"{bundle_id}/before.jpg", "phase": "before", "kind": "rgb_image",
             "source_id": "cam-top", "received_at": ts(before_at + 0.05),
             "sequence": 0, "media_type": "image/jpeg", "sha256": sha64(f"{bundle_id}:before"),
             "byte_size": 152400, "uri": f"evidence/{bundle_id}/before.jpg", "retained": True},
            {"artifact_id": f"{bundle_id}/after.jpg", "phase": "after", "kind": "rgb_image",
             "source_id": "cam-top", "received_at": ts(after_at + 0.05),
             "sequence": 1, "media_type": "image/jpeg", "sha256": sha64(f"{bundle_id}:after"),
             "byte_size": 148920, "uri": f"evidence/{bundle_id}/after.jpg", "retained": True},
        ],
        "quality": {"complete": True, "association_quality": "authoritative",
                    "capture_authority": "paos_forge_adapter",
                    "missing_requirements": [], "stale_artifacts": [], "errors": []},
    }


def make_session(sid: str, cmd_id: str, root: str, parent: str | None,
                 replan_attempt: int, item: str, basket: str,
                 criteria: list[str], *, tamper: dict | None = None) -> dict:
    """生成一个完整闭环的 ForgeSessionRecord（contracts.py: ForgeSessionRecord）。"""
    t = tamper or {}
    fail_times = t.get("fail_times")
    ev_before, ev_term, ev_after = 10.0, 24.0, 26.0

    record = {
        "version": "forge_session_record_v1",
        "session_id": sid,
        "command_id": cmd_id,
        "root_session_id": root,
        "parent_session_id": parent,
        "replan_attempt": replan_attempt,
        "request": make_request(item, basket, criteria),
        "status": t.get("status", "succeeded"),
        "created_at": ts(6.0),
        "updated_at": ts(ev_after + 2.0),
        "dispatch_attempted_at": ts(8.0),
        "terminal_at": ts(ev_after + 2.0) if t.get("terminal", True) else None,
        "execution": {
            "version": "paos_execution_record_v1",
            "runtime": "forge_gateway",
            "session_id": sid, "command_id": cmd_id,
            "gateway_api_version": "paos-forge-gateway-mvp-plus.v1",
            "gateway_instance_id": "gw-01",
            "action_type": "pick_and_place", "policy_id": "forge/planner/v1",
            "status": t.get("exec_status", "succeeded"),
            "result_semantics": "command_completed",
            "completion": {"code": 0, "message": "正常终止"},
            "timeline": {"created_at": ev_before, "updated_at": ev_after,
                         "sent_at": 8.5, "terminal_observed_at": ts(ev_term)},
            "outputs": {"picked": True, "placed_basket": basket},
            "error": None,
        },
        "verification": {
            "status": "completed",
            "bundle_ref": f"bundle-{sid}",
            "verdict": {
                "version": "verification_verdict_v1",
                "verdict": t.get("verdict", "success"),
                "criteria": t.get("criteria", [
                    {"criterion": c, "status": "satisfied",
                     "evidence_refs": [f"bundle-{sid}"]} for c in criteria
                ]),
                "evidence_refs": [f"bundle-{sid}"],
                "reason": t.get("reason", "全部成功标准满足"),
                "lesson": "正常执行",
                "recovery_context": t.get("recovery_context"),
                "verifier_status": "completed",
            },
            "attempts": [{"version": "verification_attempt_v1", "model": "sim",
                          "verdict": t.get("verdict", "success"),
                          "created_at": ts(28.0)}],
            "error": None,
        },
        "recovery_request": t.get("recovery_request"),
        "gateway_create_response": {
            "session_id": sid, "command_id": cmd_id, "request_id": f"req-{sid}",
            "accepted": True,
        },
        "gateway_last_response": {"session_id": sid, "command_id": cmd_id,
                                  "status": t.get("exec_status", "succeeded")},
        "before_snapshot_ref": f"bundle-{sid}/before.jpg",
        "completion_notified_at": ts(ev_after + 1.0),
        "error_code": None, "error_message": None,
        "origin_channel": "cli", "origin_chat_id": "direct",
        "origin_session_key": None,
    }

    if fail_times:  # 证据时间窗倒挂注入（缺陷场景）
        record["execution"]["timeline"]["terminal_observed_at"] = ts(fail_times)
        record["verification"]["bundle_ref"] = f"bundle-{sid}"
    return record


def make_healthy_scenario() -> dict:
    """场景 1：主 session A 完整闭环成功。"""
    criteria = ["可乐已从桌面拿起", "可乐位于黄色篮子内", "未触碰其他物品"]
    session = make_session("forge-a-0001", "cmd-a-0001", "forge-a-0001", None, 0,
                           "可乐", "黄色篮子", criteria)
    # 状态流转序列（状态机路径）
    flow = ["accepted", "capturing_before", "dispatching", "running", "finalizing",
            "awaiting_verification", "verifying", "succeeded"]
    evidence = [make_evidence("bundle-forge-a-0001", "forge-a-0001", "cmd-a-0001",
                              10.0, 24.0, 26.0)]
    return {"name": "健康闭环 — A 一次 pick/place 全程成功", "flow": flow,
            "sessions": [session], "evidence": evidence}


def make_recovery_scenario() -> dict:
    """场景 2：A 执行失败 → replan_required → child C 重试成功。"""
    criteria = ["牛奶已从桌面拿起", "牛奶位于黄色篮子内", "未触碰其他物品"]

    parent_tamper = {
        "status": "replanned",
        "exec_status": "failed",
        "terminal": True,
        "verdict": "replan_required",
        "criteria": [
            {"criterion": "牛奶已从桌面拿起", "status": "unsatisfied",
             "evidence_refs": ["bundle-forge-a-0002"]},
            {"criterion": "牛奶位于黄色篮子内", "status": "unknown",
             "evidence_refs": []},
            {"criterion": "未触碰其他物品", "status": "satisfied",
             "evidence_refs": ["bundle-forge-a-0002"]},
        ],
        "reason": "抓取失败，需要重新规划",
        "recovery_context": {
            "unmet_criteria": ["牛奶已从桌面拿起", "牛奶位于黄色篮子内"],
            "preserved_constraints": ["未触碰其他物品"],
            "guidance": "重新规划 pick 与 place 参数后重试",
        },
        "recovery_request": {
            "version": "recovery_request_v1",
            "request_id": f"req-recover-forge-a-0002",
            "parent_session_id": "forge-a-0002",
            "unmet_criteria": ["牛奶已从桌面拿起", "牛奶位于黄色篮子内"],
            "preserved_constraints": ["未触碰其他物品"],
            "guidance": "重新规划 pick 与 place 参数后重试",
            "evidence_refs": ["bundle-forge-a-0002"],
            "deadline": ts(120.0), "dispatched_at": ts(35.0),
        },
    }
    parent = make_session("forge-a-0002", "cmd-a-0002", "forge-a-0002", None, 0,
                          "牛奶", "黄色篮子", criteria, tamper=parent_tamper)
    child = make_session("forge-c-0002", "cmd-c-0002", "forge-a-0002",
                         "forge-a-0002", 1, "牛奶", "黄色篮子", criteria)

    flow = ["accepted", "capturing_before", "dispatching", "running", "finalizing",
            "awaiting_verification", "verifying", "awaiting_replan", "replanned"]
    child_flow = ["accepted", "capturing_before", "dispatching", "running",
                  "finalizing", "awaiting_verification", "verifying", "succeeded"]
    evidence = [make_evidence("bundle-forge-a-0002", "forge-a-0002", "cmd-a-0002",
                              10.0, 24.0, 26.0),
                make_evidence("bundle-forge-c-0002", "forge-c-0002", "cmd-c-0002",
                              40.0, 54.0, 56.0)]
    return {"name": "恢复链闭环 — A 失败 replan → C 重试成功",
            "flow": flow, "child_flow": child_flow,
            "sessions": [parent, child], "evidence": evidence}


def make_tampered_scenario() -> dict:
    """场景 3：与场景 2 同构，注入 3 处缺陷，校验应逐项识别。"""
    base = make_recovery_scenario()
    parent, child = base["sessions"]

    # 缺陷 1: child verdict=success 但存在 unsatisfied criterion → 一致性破坏
    child["verification"]["verdict"]["criteria"][1] = {
        "criterion": "牛奶位于黄色篮子内", "status": "unsatisfied",
        "evidence_refs": ["bundle-forge-c-0002"],
    }
    # 缺陷 2: child 证据时间窗倒挂（after < terminal，terminal=54.0）
    child["execution"]["timeline"]["terminal_observed_at"] = ts(58.0)
    for art in base["evidence"][1]["artifacts"]:
        if art["phase"] == "after":
            art["received_at"] = ts(53.5)
    base["evidence"][1]["capture_window"]["after_command_at"] = ts(53.0)
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

    # r1 必填字段（ForgeSessionRecord 必需项）
    required = ["session_id", "command_id", "root_session_id", "request",
                "status", "created_at", "updated_at"]
    missing = [f for f in required if not rec.get(f)]
    add("r1", "必填字段完整", not missing, f"缺失: {missing}" if missing else "完整")

    # r2 标识符 path-safe（contracts.py: validate_identifier）
    bad_ids = [v for v in (rec.get("session_id"), rec.get("command_id"),
                           rec.get("root_session_id"))
               if not v or v in {".", ".."} or "/" in v or "\\" in v]
    add("r2", "标识符 path-safe", not bad_ids, f"非法: {bad_ids}" if bad_ids else "合法")

    # r3 状态机转换合法（ALLOWED_FORGE_TRANSITIONS）
    illegal = [(a, b) for a, b in zip(flow, flow[1:])
               if b not in ALLOWED_TRANSITIONS.get(a, set())]
    add("r3", "状态机转换合法", not illegal,
        "→".join(flow) if not illegal else f"非法转换: {illegal}")

    # r4 终止状态（TERMINAL_FORGE_STATUSES）
    add("r4", "会话终止状态", rec["status"] in TERMINAL_STATUSES,
        f"status={rec['status']}")

    # r5 时间戳单调性（created ≤ dispatch ≤ terminal；updated ≥ created）
    created, updated, dispatch = (rec["created_at"], rec["updated_at"],
                                  rec["dispatch_attempted_at"])
    terminal = rec.get("terminal_at")
    monotonic = (created <= updated and created <= dispatch
                 and (terminal is None or (dispatch <= terminal
                                           and created <= terminal)))
    add("r5", "会话时间戳单调", monotonic,
        f"created={created[:19]} dispatch={dispatch[:19]}"
        f" terminal={terminal[:19] if terminal else '-'} updated={updated[:19]}")

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

    # r7 证据完整性（sha256 64hex、before/after 配对、时间窗顺序）
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

    # r11 gateway 身份一致性（create/last 响应中的 session/command id）
    create, last = rec["gateway_create_response"], rec["gateway_last_response"]
    ok11 = (create["session_id"] == rec["session_id"]
            and create["command_id"] == rec["command_id"]
            and last["session_id"] == rec["session_id"]
            and last["command_id"] == rec["command_id"])
    add("r11", "gateway 身份一致性", ok11,
        f"create=({create['session_id']},{create['command_id']}) "
        f"record=({rec['session_id']},{rec['command_id']})")

    return res


def run_checks(scenario: dict) -> dict:
    """对场景内所有 session 跑校验，汇总。"""
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
    parser = argparse.ArgumentParser(description="session 完整性校验 → JSON")
    parser.add_argument("-o", "--out", default=str(Path(__file__).parent / "session_result.json"))
    args = parser.parse_args()

    scenarios = [make_healthy_scenario(), make_recovery_scenario(),
                 make_tampered_scenario()]
    results = [run_checks(s) for s in scenarios]

    payload = {
        "task": "Forge session 完整性校验（模拟真实闭环）",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "contract_source": "PhyAgentOS/verification/contracts.py",
        "scenarios": results,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    # 终端摘要
    for r in results:
        s = r["summary"]
        print(f"[{s['verdict']}] {r['name']} — {s['passed']}/{s['passed'] + s['failed']} 项通过")
    failed_checks = [c for r in results for c in r["checks"] if not c["ok"]]
    for c in failed_checks:
        print(f"  ✗ {c['rule']} {c['session_id']}: {c['desc']} — {c['detail']}")
    print(f"结果已保存: {args.out}")


ALL_SESSIONS: list[dict] = []  # 供 r9 查找 parent（运行时填充）


if __name__ == "__main__":
    main()
