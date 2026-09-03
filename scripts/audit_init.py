#!/usr/bin/env python3
"""极简初始化辅助：生成一个合法的 state.json 骨架，然后交给 validator 验一遍。

它只做一件事——让主代理不必凭空手写上百行嵌套 JSON。它不接管流程，不生成
Claim，不替你做任何判断，也不重复 validator 的任何检查：骨架合不合法由
validate_audit_state.py 说了算，本脚本只负责把它生成出来再调用一次。

    python -B scripts/audit_init.py init --audit-id my-audit-001 \
        --target "auth change" --scope "src/auth/**" --gate RELEASE

生成的骨架 phase=ACTIVE、claims/findings 全空。这是刻意的：一个空的合法起点，
比一个填了占位内容、看起来完整却要你逐项删改的模板更好用。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 3
SCOPE_MODES = ("project", "change", "pr", "author-commits")
GATE_TARGETS = ("CHANGE", "RELEASE", "SYSTEM")
BLOCK_LEVELS = ("Medium", "Low")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")

# 每种 snapshot kind 需要的字段。ACTIVE 阶段允许 null，所以全部可选。
SNAPSHOT_FIELDS = {
    "git": ("base", "head"),
    "git-worktree": ("base", "head", "initialSha256", "finalSha256"),
    "archive": ("sha256",),
    "deployment": ("version",),
    "other": ("identity",),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_state(args: argparse.Namespace) -> dict:
    snapshot = None
    if args.snapshot_kind:
        snapshot = {"kind": args.snapshot_kind}
        for field in SNAPSHOT_FIELDS[args.snapshot_kind]:
            value = getattr(args, f"snapshot_{field}", None)
            if value is not None:
                snapshot[field] = value
        # git 变体的 base 可显式为 null；未提供的字段不写入，避免混入其它变体。

    audit = {
        "id": args.audit_id,
        "target": args.target,
        "scope": args.scope,
        "snapshot": snapshot,
        "objectives": args.objective or [],
        "scopeMode": args.scope_mode,
        "objectiveProfiles": ["general", *args.profile],
        "executionMode": args.execution_mode,
        "scopeResolution": {"basis": args.basis, "confidence": "HIGH"},
        "startedAt": now_iso(),
        "updatedAt": now_iso(),
    }
    if args.deliverable:
        audit["deliverable"] = args.deliverable
    if args.available_evidence:
        audit["availableEvidence"] = args.available_evidence

    if args.gate:
        # decisions 在 ACTIVE 必须缺席——Gate 是从状态推导的，不是初始就写好的。
        audit["gates"] = {"targets": list(dict.fromkeys(args.gate))}
        if args.block_at:
            audit["gates"]["policies"] = {
                target: {"blockAtOrAbove": args.block_at} for target in audit["gates"]["targets"]
            }

    return {
        "schemaVersion": SCHEMA_VERSION,
        "phase": "ACTIVE",
        "audit": audit,
        "sharedFacts": [],
        "claims": [],
        "verificationUnits": [],
        "findings": [],
        "residualRisks": [],
    }


def run_validator(state_dir: Path, script_dir: Path) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, "-B", str(script_dir / "validate_audit_state.py"), str(state_dir)],
        capture_output=True,
        text=True,
    )
    return result.returncode, (result.stdout or result.stderr).strip()


def cmd_init(args: argparse.Namespace) -> int:
    script_dir = Path(__file__).resolve().parent
    if not SAFE_ID.match(args.audit_id):
        print(f"error: --audit-id must match [A-Za-z0-9_-]+ (got {args.audit_id!r})", file=sys.stderr)
        return 2
    if args.snapshot_kind == "git" and not args.snapshot_head:
        print("error: --snapshot-kind git requires --snapshot-head", file=sys.stderr)
        return 2

    state_dir = Path(args.state_root) / args.audit_id
    target = state_dir / "state.json"
    if target.exists() and not args.force:
        print(f"error: {target} already exists; pass --force to overwrite", file=sys.stderr)
        return 2

    state = build_state(args)
    # 三区顶层目录一次建好，调查者派发后直接写 <unit>-<executor> 子路径即可，
    # 不必自己 mkdir 父目录。子目录按 unit + executor 分片，留到派发时再建。
    for area in ("investigations", "probes", "scratch"):
        (state_dir / area).mkdir(parents=True, exist_ok=True)
    # 先写临时文件再 rename，避免中断时留下半截 JSON。
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)

    print(f"created {target}")
    code, output = run_validator(state_dir, script_dir)
    print(output)
    if code != 0:
        print("\nwarning: skeleton failed validation; fix the generated file before continuing",
              file=sys.stderr)
        return code

    steps = []
    if not state["audit"]["objectives"]:
        steps.append("fill audit.objectives — a non-empty objective list cannot be closed by zero claims")
    steps.append("add claims[] / verificationUnits[] — see SKILL.md §3 步骤 2")
    if args.gate:
        steps.append(f"Gate targets {', '.join(state['audit']['gates']['targets'])} are registered; "
                     "decisions are derived at 收口, not now")
    steps.append("re-run the validator after every material change")
    print("\nnext:")
    for index, step in enumerate(steps, 1):
        print(f"  {index}. {step}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audit_init.py",
        description="generate a legal, empty state.json skeleton for a new audit instance",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create .audits/<audit-id>/state.json")

    init.add_argument("--audit-id", required=True, help="filename-safe id, unique within the state root")
    init.add_argument("--target", required=True, help="what is being audited")
    init.add_argument("--scope", required=True, help="bounded audit scope")
    init.add_argument("--state-root", default=".audits", help="default: .audits")
    init.add_argument("--scope-mode", default="change", choices=SCOPE_MODES)
    init.add_argument("--objective", action="append", metavar="TEXT",
                      help="repeatable; an audit with no objective has nothing to close")
    init.add_argument("--profile", action="append", default=[], metavar="NAME",
                      help="extra objective profile beyond 'general'")
    init.add_argument("--execution-mode", default="audit-only", choices=("audit-only", "audit-and-fix"))
    init.add_argument("--basis", default="USER",
                      choices=("USER", "PLATFORM", "REPOSITORY", "ASSUMED"))
    init.add_argument("--deliverable", help="what the user receives")
    init.add_argument("--available-evidence", action="append", metavar="TEXT")
    init.add_argument("--gate", action="append", choices=GATE_TARGETS,
                      help="repeatable; only when the user asked for a merge/release/system decision")
    init.add_argument("--block-at", choices=BLOCK_LEVELS,
                      help="tighten the threshold below the default High (requires --gate)")
    init.add_argument("--snapshot-kind", choices=tuple(SNAPSHOT_FIELDS))
    # base/head 同时属于 git 与 git-worktree，去重后只注册一次。
    for field in sorted({f for fields in SNAPSHOT_FIELDS.values() for f in fields}):
        init.add_argument(f"--snapshot-{field}", metavar="VALUE", help=f"snapshot field: {field}")
    init.add_argument("--force", action="store_true", help="overwrite an existing state.json")
    init.set_defaults(func=cmd_init)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "init" and args.block_at and not args.gate:
        print("error: --block-at requires --gate", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
