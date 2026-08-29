#!/usr/bin/env python3
"""Optional mechanical helpers for protocol-v2 audit state.

These helpers exist because writing state by hand is mostly repetition:
the same ``auditBinding`` is copied into every artifact, hypothesis ids
follow a fixed prefix convention, and ``reconciliations`` must mirror the
investigation's hypotheses. Getting any of them wrong produces errors that
have nothing to do with the audit itself.

Scope, deliberately narrow:

* they only perform mechanical work and report mechanical inconsistencies;
* they never infer semantics - severity, decision, sufficiency, applicability
  and gate results stay the main agent's responsibility;
* they are optional. ``validate_audit_state.py`` remains the only authority
  on whether a state is legal, and this module does not replace it.

Commands
--------
init <dir>   create a minimal, valid state skeleton
bind <dir>   propagate audit.id / audit.snapshot into every referenced artifact
lint <dir>   report mechanical inconsistencies (read-only, never writes)

Every command exits 0 on success and 1 on problems, so it can be chained
before the validator.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
SNAPSHOT_KINDS = {"git", "git-worktree", "archive", "deployment", "other"}


def utc_now() -> str:
    """Current UTC time as the ISO8601 form the protocol fixtures use."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class HelperError(Exception):
    """Raised for user-facing problems (bad arguments, missing files)."""


# --------------------------------------------------------------------------
# shared io
# --------------------------------------------------------------------------


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise HelperError(f"missing file: {path}")
    except json.JSONDecodeError as exc:
        raise HelperError(f"{path} is not valid JSON: {exc}")


def write_json(path: Path, data: Any) -> None:
    """Write via a temp file and replace, so a crash never leaves a half file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_state(state_dir: Path) -> tuple[dict[str, Any], Path]:
    state_path = state_dir / "state.json"
    state = read_json(state_path)
    if not isinstance(state, dict):
        raise HelperError(f"{state_path} must contain a JSON object")
    return state, state_path


def referenced_artifacts(state: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return the investigation / verification paths the state actually points at.

    Unreferenced artifacts are ignored on purpose: the protocol treats them as
    leftovers to quarantine, not as state to maintain.
    """
    investigations: list[str] = []
    verifications: list[str] = []
    for unit in state.get("verificationUnits") or []:
        if isinstance(unit, dict) and isinstance(unit.get("investigationFile"), str):
            investigations.append(unit["investigationFile"])
    for finding in state.get("findings") or []:
        if isinstance(finding, dict) and isinstance(finding.get("verificationFile"), str):
            verifications.append(finding["verificationFile"])
    return investigations, verifications


def resolve_inside(state_dir: Path, relative: str) -> Path:
    candidate = (state_dir / relative).resolve()
    try:
        candidate.relative_to(state_dir.resolve())
    except ValueError:
        raise HelperError(f"path escapes the audit directory: {relative}")
    return candidate


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------


def build_skeleton(audit_id: str, target: str, scope: str, objectives: list[str],
                   deliverable: str, snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "phase": "ACTIVE",
        "audit": {
            "id": audit_id,
            "target": target,
            "scope": scope,
            "objectives": objectives,
            "deliverable": deliverable,
            "scopeMode": "change",
            "objectiveProfiles": ["general"],
            "executionMode": "audit-only",
            "scopeResolution": {"basis": "USER", "confidence": "HIGH"},
            "snapshot": snapshot,
            "startedAt": utc_now(),
            "updatedAt": utc_now(),
        },
        "sharedFacts": [],
        "claims": [],
        "verificationUnits": [],
        "findings": [],
        "residualRisks": [],
    }


def cmd_init(args: argparse.Namespace) -> int:
    state_dir = Path(args.dir)
    if (state_dir / "state.json").exists() and not args.force:
        raise HelperError(f"{state_dir / 'state.json'} already exists (use --force to overwrite)")

    snapshot: dict[str, Any] | None = None
    if args.snapshot_kind:
        if args.snapshot_kind not in SNAPSHOT_KINDS:
            raise HelperError(f"unknown snapshot kind {args.snapshot_kind!r}")
        snapshot = {"kind": args.snapshot_kind}
        if args.head:
            snapshot["head"] = args.head
        if args.base:
            snapshot["base"] = args.base
        if args.snapshot_kind == "git":
            snapshot.setdefault("base", None)

    state = build_skeleton(
        audit_id=args.audit_id,
        target=args.target,
        scope=args.scope,
        objectives=args.objective,
        deliverable=args.deliverable,
        snapshot=snapshot,
    )
    (state_dir / "investigations").mkdir(parents=True, exist_ok=True)
    (state_dir / "verification").mkdir(parents=True, exist_ok=True)
    write_json(state_dir / "state.json", state)
    print(f"created {state_dir / 'state.json'}")
    print("next: add claims[] and verificationUnits[], then run `bind` after each artifact lands")
    return 0


# --------------------------------------------------------------------------
# bind
# --------------------------------------------------------------------------


def expected_binding(state: dict[str, Any]) -> dict[str, Any] | None:
    audit = state.get("audit")
    if not isinstance(audit, dict):
        return None
    audit_id = audit.get("id")
    if not isinstance(audit_id, str) or not audit_id:
        return None
    return {"auditId": audit_id, "snapshot": audit.get("snapshot")}


def cmd_bind(args: argparse.Namespace) -> int:
    state_dir = Path(args.dir)
    state, state_path = load_state(state_dir)
    binding = expected_binding(state)
    if binding is None:
        raise HelperError("state.json.audit.id must be a non-empty string before binding")

    investigations, verifications = referenced_artifacts(state)
    targets = [(state_dir, rel) for rel in investigations + verifications]

    changed: list[str] = []
    stale: list[str] = []
    missing: list[str] = []

    for base, relative in targets:
        path = resolve_inside(base, relative)
        if not path.is_file():
            missing.append(relative)
            continue
        data = read_json(path)
        if not isinstance(data, dict):
            stale.append(f"{relative}: not a JSON object")
            continue
        current = data.get("auditBinding")
        if current == binding:
            continue
        stale.append(relative)
        if not args.check:
            # keep key order stable: auditBinding first, then the rest
            rebuilt = {"auditBinding": binding}
            rebuilt.update({k: v for k, v in data.items() if k != "auditBinding"})
            write_json(path, rebuilt)
            changed.append(relative)

    if missing:
        print("missing referenced artifacts:")
        for item in missing:
            print(f"  - {item}")
    if stale:
        verb = "would update" if args.check else "updated"
        print(f"{verb} auditBinding in {len(stale)} artifact(s):")
        for item in stale:
            print(f"  - {item}")
    if not missing and not stale:
        print(f"all referenced artifacts already bound to {binding['auditId']}")

    if args.check:
        return 1 if (missing or stale) else 0
    if changed and not args.no_validate:
        print()
        print(f"run: python -B scripts/validate_audit_state.py {state_path.parent}")
    return 1 if missing else 0


# --------------------------------------------------------------------------
# lint
# --------------------------------------------------------------------------


def cmd_lint(args: argparse.Namespace) -> int:
    state_dir = Path(args.dir)
    state, _ = load_state(state_dir)
    problems: list[str] = []
    binding = expected_binding(state)

    unit_by_id = {
        u["id"]: u for u in (state.get("verificationUnits") or [])
        if isinstance(u, dict) and isinstance(u.get("id"), str)
    }
    finding_by_id = {
        f["id"]: f for f in (state.get("findings") or [])
        if isinstance(f, dict) and isinstance(f.get("id"), str)
    }

    # 1. every referenced artifact exists and carries the current binding
    investigations, verifications = referenced_artifacts(state)
    for relative in investigations + verifications:
        path = resolve_inside(state_dir, relative)
        if not path.is_file():
            problems.append(f"{relative}: referenced but missing")
            continue
        data = read_json(path)
        if not isinstance(data, dict):
            problems.append(f"{relative}: not a JSON object")
            continue
        if binding is not None and data.get("auditBinding") != binding:
            problems.append(f"{relative}: auditBinding does not match state.json")

    # 2. reconciliations must mirror the investigation's hypotheses
    expected_result = {
        "promote-to-finding": "FINDING",
        "close": "REFUTED",
        "residual-gap": "RESIDUAL-GAP",
    }
    promoted_to: dict[str, set[str]] = {fid: set() for fid in finding_by_id}

    for unit_id, unit in unit_by_id.items():
        relative = unit.get("investigationFile")
        if not isinstance(relative, str):
            if unit.get("status") == "verified":
                problems.append(f"{unit_id}: verified unit has no investigationFile")
            continue
        path = resolve_inside(state_dir, relative)
        if not path.is_file():
            continue
        data = read_json(path)
        if not isinstance(data, dict):
            continue

        local_evidence = {
            e["id"] for e in (data.get("evidence") or [])
            if isinstance(e, dict) and isinstance(e.get("id"), str)
        }
        for hyp in data.get("hypotheses") or []:
            if not isinstance(hyp, dict):
                continue
            hid = hyp.get("id")
            if isinstance(hid, str) and not str(hid).startswith(f"{unit_id}-H"):
                problems.append(f"{unit_id}: hypothesis id {hid} must use prefix {unit_id}-H<n>")
            recommendation = hyp.get("recommendation")
            want = expected_result.get(recommendation) if isinstance(recommendation, str) else None
            if recommendation is not None and want is None:
                problems.append(f"{unit_id}: unknown recommendation {recommendation!r}")

        recon = unit.get("reconciliations")
        if not isinstance(recon, list):
            if data.get("hypotheses"):
                problems.append(f"{unit_id}: hypotheses exist but reconciliations is missing")
            continue
        by_hyp = {
            r.get("hypothesisId"): r for r in recon
            if isinstance(r, dict)
        }
        for hyp in data.get("hypotheses") or []:
            if not isinstance(hyp, dict):
                continue
            hid = hyp.get("id")
            entry = by_hyp.get(hid)
            if entry is None:
                problems.append(f"{unit_id}: hypothesis {hid} has no reconciliation entry")
                continue
            want = expected_result.get(hyp.get("recommendation")) if isinstance(hyp.get("recommendation"), str) else None
            if want and entry.get("result") != want:
                problems.append(
                    f"{unit_id}: {hid} recommendation={hyp.get('recommendation')} "
                    f"but result={entry.get('result')} (expected {want})"
                )
            if entry.get("result") == "FINDING":
                fid = entry.get("findingId")
                if fid not in finding_by_id:
                    problems.append(f"{unit_id}: {hid} points at unknown finding {fid!r}")
                else:
                    promoted_to[fid].add(hid)
            for ref in entry.get("evidenceRefs") or []:
                if isinstance(ref, str) and ref not in local_evidence:
                    problems.append(f"{unit_id}: reconciliation evidence {ref} is not in {relative}")

    # 3. sourceHypotheses must be the exact mirror of FINDING reconciliations
    for fid, finding in finding_by_id.items():
        declared = set(finding.get("sourceHypotheses") or [])
        incoming = promoted_to.get(fid, set())
        if declared != incoming:
            missing = sorted(incoming - declared)
            extra = sorted(declared - incoming)
            problems.append(
                f"{fid}: sourceHypotheses does not mirror FINDING reconciliations "
                f"(missing={missing}, extra={extra})"
            )

    # 4. artifact ids must agree with the object they belong to
    for unit_id, unit in unit_by_id.items():
        relative = unit.get("investigationFile")
        if not isinstance(relative, str):
            continue
        path = resolve_inside(state_dir, relative)
        if not path.is_file():
            continue
        data = read_json(path)
        if isinstance(data, dict):
            if data.get("unitId") != unit_id:
                problems.append(f"{relative}: unitId {data.get('unitId')!r} != {unit_id}")
            for key, value in (("method", unit.get("method")), ("claimId", unit.get("claimId"))):
                if value is not None and data.get(key) != value:
                    problems.append(f"{relative}: {key} {data.get(key)!r} != {value!r}")

    for fid, finding in finding_by_id.items():
        relative = finding.get("verificationFile")
        if not isinstance(relative, str):
            continue
        path = resolve_inside(state_dir, relative)
        if not path.is_file():
            continue
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        if data.get("findingId") != fid:
            problems.append(f"{relative}: findingId {data.get('findingId')!r} != {fid}")
        method = finding.get("verificationMethod")
        if isinstance(method, str) and data.get("method") != method:
            problems.append(f"{relative}: method {data.get('method')!r} != verificationMethod {method!r}")
        for ev in data.get("evidence") or []:
            if isinstance(ev, dict) and isinstance(ev.get("id"), str):
                if not ev["id"].startswith(f"{fid}-E"):
                    problems.append(f"{relative}: evidence id {ev['id']} must use prefix {fid}-E<n>")

    if not problems:
        print(f"no mechanical problems found in {state_dir}")
        return 0
    print(f"{len(problems)} mechanical problem(s) in {state_dir}:")
    for item in problems:
        print(f"  - {item}")
    print()
    print("these are mechanical only; semantic legality is decided by validate_audit_state.py")
    return 1


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audit_state_helper.py",
        description="Mechanical helpers for protocol-v2 audit state (optional).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create a minimal state skeleton")
    p_init.add_argument("dir")
    p_init.add_argument("--audit-id", required=True)
    p_init.add_argument("--target", required=True)
    p_init.add_argument("--scope", required=True)
    p_init.add_argument("--objective", action="append", default=[],
                        help="repeatable; at least one required")
    p_init.add_argument("--deliverable", default="finding report")
    p_init.add_argument("--snapshot-kind", choices=sorted(SNAPSHOT_KINDS))
    p_init.add_argument("--head")
    p_init.add_argument("--base")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_bind = sub.add_parser("bind", help="propagate auditBinding into referenced artifacts")
    p_bind.add_argument("dir")
    p_bind.add_argument("--check", action="store_true",
                        help="report only; do not modify files")
    p_bind.add_argument("--no-validate", action="store_true",
                        help="suppress the follow-up validator hint")
    p_bind.set_defaults(func=cmd_bind)

    p_lint = sub.add_parser("lint", help="report mechanical inconsistencies (read-only)")
    p_lint.add_argument("dir")
    p_lint.set_defaults(func=cmd_lint)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init" and not args.objective:
        parser.error("init requires at least one --objective")
    try:
        return args.func(args)
    except HelperError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
