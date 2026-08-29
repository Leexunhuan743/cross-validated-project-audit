#!/usr/bin/env python3
"""Optional helper for building protocol-v2 audit state.

The validator remains the only authority on whether a state is legal. This
helper exists solely to remove mechanical work that a main agent otherwise
repeats by hand:

  init    create a minimal state.json skeleton for a new audit instance
  bind    stamp or verify `auditBinding` on an investigation/verification JSON
  verify  thin wrapper around validate_audit_state.py

It makes no semantic decisions: it never invents a Claim, a Finding, a
Decision, a Severity or a Gate result. Standard library only, Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SCOPE_MODES = {"project", "change", "pr", "author-commits"}
SCOPE_BASIS = {"USER", "PLATFORM", "REPOSITORY", "ASSUMED"}
SCOPE_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
EXECUTION_MODES = {"audit-only", "audit-and-fix"}
STATE_NAME = "state.json"


def fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"ERROR: cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: {path} is not valid JSON: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_init(args: argparse.Namespace) -> int:
    if not AUDIT_ID_PATTERN.fullmatch(args.id):
        return fail(f"audit id {args.id!r} must match {AUDIT_ID_PATTERN.pattern}")
    if args.scope_mode not in SCOPE_MODES:
        return fail(f"--scope-mode must be one of {sorted(SCOPE_MODES)}")
    if args.basis not in SCOPE_BASIS:
        return fail(f"--basis must be one of {sorted(SCOPE_BASIS)}")
    if args.confidence not in SCOPE_CONFIDENCE:
        return fail(f"--confidence must be one of {sorted(SCOPE_CONFIDENCE)}")
    if args.execution_mode not in EXECUTION_MODES:
        return fail(f"--execution-mode must be one of {sorted(EXECUTION_MODES)}")

    snapshot: Any = None
    if args.snapshot_json:
        snapshot = load_json_object(args.snapshot_json, "--snapshot-json")

    # Only ASSUMED carries an assumption; anything else would be a placeholder.
    scope_resolution: dict[str, Any] = {"basis": args.basis, "confidence": args.confidence}
    if args.basis == "ASSUMED":
        if not args.assumption:
            return fail("--basis ASSUMED requires a non-empty --assumption")
        scope_resolution["assumption"] = args.assumption
    elif args.assumption:
        return fail("--assumption is only allowed when --basis is ASSUMED")

    state = {
        "schemaVersion": 2,
        "phase": "ACTIVE",
        "audit": {
            "id": args.id,
            "target": args.target,
            "scope": args.scope,
            "objectives": args.objectives,
            "deliverable": args.deliverable,
            "scopeMode": args.scope_mode,
            "objectiveProfiles": ["general"],
            "executionMode": args.execution_mode,
            "scopeResolution": scope_resolution,
            "snapshot": snapshot,
            "startedAt": now_iso(),
            "updatedAt": now_iso(),
        },
        "sharedFacts": [],
        "claims": [],
        "verificationUnits": [],
        "findings": [],
        "residualRisks": [],
    }
    target = Path(args.state_dir)
    state_path = target / STATE_NAME
    if state_path.exists() and not args.force:
        return fail(f"{state_path} already exists; pass --force to overwrite")
    write_json(state_path, state)
    print(f"created {state_path}")
    print("next: add claims, then use `bind` to stamp auditBinding on each artifact")
    return 0


def load_json_object(raw: str, label: str) -> Any:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: {label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"ERROR: {label} must be a JSON object") from exc
    return value


def cmd_bind(args: argparse.Namespace) -> int:
    state_path = Path(args.state_dir) / STATE_NAME
    if not state_path.is_file():
        return fail(f"{state_path} not found; run `init` first")
    state = load_json(state_path)
    audit = state.get("audit") if isinstance(state, dict) else None
    if not isinstance(audit, dict):
        return fail(f"{state_path} has no audit object")
    expected = {"auditId": audit.get("id"), "snapshot": audit.get("snapshot")}

    artifact_path = Path(args.artifact)
    if not artifact_path.is_file():
        return fail(f"artifact {artifact_path} not found")
    data = load_json(artifact_path)
    if not isinstance(data, dict):
        return fail(f"{artifact_path} must contain a JSON object")

    existing = data.get("auditBinding")
    if existing is not None:
        if existing == expected:
            print(f"ok: {artifact_path} already bound to {expected['auditId']}")
            return 0
        return fail(
            f"{artifact_path} has a different auditBinding; refusing to overwrite it. "
            "A mismatched binding means the artifact was gathered against another "
            "audit or snapshot and must be re-gathered, not re-stamped."
        )

    data = {"auditBinding": expected, **data}
    write_json(artifact_path, data)
    print(f"bound {artifact_path} to {expected['auditId']}")
    if not is_referenced_by_state(state, artifact_path, Path(args.state_dir)):
        print(
            "note: state.json does not reference this artifact yet. That is the expected "
            "intermediate state — publish the canonical artifact first, then add the matching "
            "verificationUnits[].investigationFile or findings[].verificationFile in one atomic "
            "state replacement. Never write the state reference first."
        )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from validate_audit_state import main as validator_main  # noqa: PLC0415

    return validator_main([str(Path(args.state_dir))])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Optional helper for building cross-validated-project-audit protocol-v2 state.",
        epilog="The validator is the authority; this helper only removes mechanical repetition.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create a minimal state.json skeleton")
    p_init.add_argument("state_dir", help="audit instance directory, e.g. <stateRoot>/<auditId>")
    p_init.add_argument("--id", required=True, help="audit id (letters, digits, - or _)")
    p_init.add_argument("--target", required=True)
    p_init.add_argument("--scope", required=True)
    p_init.add_argument("--objectives", required=True, nargs="+")
    p_init.add_argument("--deliverable", default="finding report")
    p_init.add_argument("--scope-mode", default="change", choices=sorted(SCOPE_MODES))
    p_init.add_argument("--execution-mode", default="audit-only", choices=sorted(EXECUTION_MODES))
    p_init.add_argument("--basis", default="USER", choices=sorted(SCOPE_BASIS))
    p_init.add_argument("--confidence", default="HIGH", choices=sorted(SCOPE_CONFIDENCE))
    p_init.add_argument("--assumption", help="required and only allowed when --basis is ASSUMED")
    p_init.add_argument("--snapshot-json", help="immutable snapshot object as JSON, e.g. '{\"kind\":\"git\",\"base\":null,\"head\":\"abc\"}'")
    p_init.add_argument("--force", action="store_true", help="overwrite an existing state.json")
    p_init.set_defaults(func=cmd_init)

    p_bind = sub.add_parser("bind", help="stamp or verify auditBinding on an artifact JSON")
    p_bind.add_argument("state_dir")
    p_bind.add_argument("--artifact", required=True, help="investigations/ or verification/ JSON file")
    p_bind.set_defaults(func=cmd_bind)

    p_verify = sub.add_parser("verify", help="run the validator against an audit instance")
    p_verify.add_argument("state_dir")
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
