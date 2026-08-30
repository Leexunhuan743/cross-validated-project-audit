#!/usr/bin/env python3
"""Optional helper for building cross-validated-project-audit protocol state.

The validator remains the only authority on whether a state is legal. This
helper exists solely to remove mechanical work that a main agent otherwise
repeats by hand:

  init     create a minimal state.json skeleton for a new audit instance
  check    validate one investigation artifact -- state-backed (receive side)
           or --standalone (investigator self-check that never reads state)
  receive  validate a staged investigation and copy it verbatim to its
           canonical path, reporting structural differences on replacement
  bind     stamp or verify `auditBinding` on investigation/verification JSON
  lint     report mechanical inconsistencies (read-only)
  verify   thin wrapper around validate_audit_state.py

It makes no semantic decisions: it never invents a Claim, a Finding, a
Decision, a Severity or a Gate result. `receive` in particular does not
normalize content, write state references or push `reported` -- those are
main-agent acceptance actions. Standard library only, Python 3.9+.

The one rule it defends rather than automates: a mismatched `auditBinding`
means the artifact was gathered against another audit or snapshot. Such an
artifact must be re-gathered, never re-stamped -- so `bind` refuses to
overwrite it unless `--force` is passed explicitly, and `receive` rejects it
for the same reason.

On-demand candidates not implemented (see the audit disposition log):
`reconcile` (scaffold reconciliations from investigation hypotheses) and
`finalize` (claim sufficiency aggregation). Land `receive` first and observe
the actual payoff before adding more subcommands.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SCOPE_MODES = {"project", "change", "pr", "author-commits"}
SCOPE_BASIS = {"USER", "PLATFORM", "REPOSITORY", "ASSUMED"}
SCOPE_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
EXECUTION_MODES = {"audit-only", "audit-and-fix"}
OBJECTIVE_PROFILES = {"general", "security", "fix-verification"}
SNAPSHOT_KINDS = {"git", "git-worktree", "archive", "deployment", "other"}
STATE_NAME = "state.json"

RECOMMENDATION_TO_RESULT = {
    "promote-to-finding": "FINDING",
    "close": "REFUTED",
    "residual-gap": "RESIDUAL-GAP",
}


def fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def load_json_or_exit(path: Path) -> Any:
    """Read JSON or abort the CLI.

    Deliberately not named `load_json`: validate_audit_state.py has a function
    by that name which records a validation error and returns None so it can
    keep collecting. Same name, opposite behaviour -- here an unreadable file is
    fatal because there is no report left to collect errors into.
    """
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


def load_json_object(raw: str, label: str) -> Any:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: {label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"ERROR: {label} must be a JSON object") from exc
    return value


# --------------------------------------------------------------------------
# shared state access
# --------------------------------------------------------------------------


def load_state(state_dir: Path) -> dict[str, Any]:
    state_path = state_dir / STATE_NAME
    if not state_path.is_file():
        raise SystemExit(f"ERROR: {state_path} not found; run `init` first")
    state = load_json_or_exit(state_path)
    if not isinstance(state, dict):
        raise SystemExit(f"ERROR: {state_path} must contain a JSON object")
    return state


def expected_binding(state: dict[str, Any]) -> dict[str, Any]:
    audit = state.get("audit")
    if not isinstance(audit, dict):
        raise SystemExit("ERROR: state.json has no audit object")
    return {"auditId": audit.get("id"), "snapshot": audit.get("snapshot")}


def resolve_inside(state_dir: Path, relative: str) -> Path:
    lexical = state_dir / relative
    # Light guard only: the validator's is_link_like() is the complete check and
    # also covers Windows junctions. This just stops `bind` from writing through
    # a symlink before the validator ever runs.
    if lexical.is_symlink():
        raise SystemExit(f"ERROR: refusing to follow a symlink: {relative}")
    candidate = lexical.resolve()
    try:
        candidate.relative_to(state_dir.resolve())
    except ValueError:
        raise SystemExit(f"ERROR: path escapes the audit directory: {relative}")
    return candidate


def referenced_artifacts(state: dict[str, Any], state_dir: Path) -> list[str]:
    """Artifacts the state actually points at, in a stable order.

    Unreferenced files are deliberately excluded: the protocol treats them as
    leftovers to quarantine, not as state to maintain.
    """
    found: list[str] = []
    for unit in state.get("verificationUnits") or []:
        if isinstance(unit, dict) and isinstance(unit.get("investigationFile"), str):
            found.append(unit["investigationFile"])
    for finding in state.get("findings") or []:
        if isinstance(finding, dict) and isinstance(finding.get("verificationFile"), str):
            found.append(finding["verificationFile"])
    seen: set[str] = set()
    result = []
    for item in found:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------


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
        # New instances always use v3; v2 remains accepted only for archives.
        "schemaVersion": 3,
        "phase": "ACTIVE",
        "audit": {
            "id": args.id,
            "target": args.target,
            "scope": args.scope,
            "objectives": args.objectives,
            "deliverable": args.deliverable,
            "scopeMode": args.scope_mode,
            # 'general' is always present exactly once; extra profiles come from
            # --profile and are de-duplicated so a repeated flag cannot produce
            # the duplicate entry the validator rejects.
            "objectiveProfiles": ["general"] + sorted(set(args.profile or []) - {"general"}),
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
    (target / "investigations").mkdir(parents=True, exist_ok=True)
    (target / "verification").mkdir(parents=True, exist_ok=True)
    write_json(state_path, state)
    print(f"created {state_path}")
    print("next: add claims, then use `bind` to stamp auditBinding on each artifact")
    return 0


# --------------------------------------------------------------------------
# bind
# --------------------------------------------------------------------------


def stamp_one(path: Path, expected: dict[str, Any], force: bool, check: bool) -> tuple[str, str]:
    """Return (status, message) where status is ok / stale / missing / error."""
    if not path.is_file():
        return "missing", str(path)
    data = load_json_or_exit(path)
    if not isinstance(data, dict):
        return "error", f"{path}: must contain a JSON object"
    existing = data.get("auditBinding")
    if existing == expected:
        return "ok", str(path)
    if existing is not None and not force:
        return "stale", (
            f"{path}: has a different auditBinding; refusing to overwrite it. "
            "A mismatched binding means the artifact was gathered against another "
            "audit or snapshot and must be re-gathered, not re-stamped "
            "(pass --force if you are certain re-stamping is correct)."
        )
    if check:
        return "stale", f"{path}: would be bound to {expected['auditId']!r}"
    # Drop any existing binding first: `{**data}` last would otherwise win and
    # silently restore the stale value we just decided to replace.
    remainder = {k: v for k, v in data.items() if k != "auditBinding"}
    rebuilt = {"auditBinding": expected, **remainder}
    write_json(path, rebuilt)
    return "bound", f"{path}: bound to {expected['auditId']!r}"


def cmd_bind(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    state = load_state(state_dir)
    expected = expected_binding(state)

    if args.artifact:
        # Absolute paths must be checked as well: an absolute --artifact is a
        # path like any other, and skipping the check would let it stamp a
        # binding onto any file outside the state root.
        targets = [resolve_inside(state_dir, args.artifact)]
    else:
        targets = [resolve_inside(state_dir, rel)
                   for rel in referenced_artifacts(state, state_dir)]

    if not targets:
        print("no referenced artifacts; nothing to bind")
        return 0

    problems = 0
    for path in targets:
        status, message = stamp_one(path, expected, args.force, args.check)
        if status == "ok":
            if args.artifact:
                print(f"ok: {message} already bound to {expected['auditId']}")
            continue
        if status == "missing":
            problems += 1
            print(f"ERROR: {message} not found", file=sys.stderr)
        elif status == "error":
            problems += 1
            print(f"ERROR: {message}", file=sys.stderr)
        elif status == "stale":
            problems += 1
            print(f"ERROR: {message}", file=sys.stderr)
        else:
            print(message)

    if problems:
        return 1
    if not args.artifact:
        print(f"all referenced artifacts bound to {expected['auditId']}")
    return 0


# --------------------------------------------------------------------------
# lint
# --------------------------------------------------------------------------


def cmd_lint(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    state = load_state(state_dir)
    expected = expected_binding(state)
    problems: list[str] = []

    unit_by_id = {
        u["id"]: u for u in (state.get("verificationUnits") or [])
        if isinstance(u, dict) and isinstance(u.get("id"), str)
    }
    finding_by_id = {
        f["id"]: f for f in (state.get("findings") or [])
        if isinstance(f, dict) and isinstance(f.get("id"), str)
    }
    promoted_to: dict[str, set[str]] = {fid: set() for fid in finding_by_id}

    # 1. referenced artifacts exist and carry the current binding
    for relative in referenced_artifacts(state, state_dir):
        path = resolve_inside(state_dir, relative)
        if not path.is_file():
            problems.append(f"{relative}: referenced but missing")
            continue
        data = load_json_or_exit(path)
        if not isinstance(data, dict):
            problems.append(f"{relative}: not a JSON object")
            continue
        if data.get("auditBinding") != expected:
            problems.append(f"{relative}: auditBinding does not match state.json")

    # 2. reconciliations mirror the investigation's hypotheses
    for unit_id, unit in unit_by_id.items():
        relative = unit.get("investigationFile")
        if not isinstance(relative, str):
            if unit.get("status") == "verified":
                problems.append(f"{unit_id}: verified unit has no investigationFile")
            continue
        path = resolve_inside(state_dir, relative)
        if not path.is_file():
            continue
        data = load_json_or_exit(path)
        if not isinstance(data, dict):
            continue
        if data.get("unitId") != unit_id:
            problems.append(f"{relative}: unitId {data.get('unitId')!r} != {unit_id}")
        for key in ("method", "claimId"):
            if unit.get(key) is not None and data.get(key) != unit.get(key):
                problems.append(f"{relative}: {key} {data.get(key)!r} != {unit.get(key)!r}")

        local_evidence = {
            e["id"] for e in (data.get("evidence") or [])
            if isinstance(e, dict) and isinstance(e.get("id"), str)
        }
        for hyp in data.get("hypotheses") or []:
            if isinstance(hyp, dict) and isinstance(hyp.get("id"), str):
                if not hyp["id"].startswith(f"{unit_id}-H"):
                    problems.append(f"{unit_id}: hypothesis id {hyp['id']} must use prefix {unit_id}-H<n>")

        recon = unit.get("reconciliations")
        if not isinstance(recon, list):
            if data.get("hypotheses"):
                problems.append(f"{unit_id}: hypotheses exist but reconciliations is missing")
            continue
        by_hyp = {r.get("hypothesisId"): r for r in recon if isinstance(r, dict)}
        for hyp in data.get("hypotheses") or []:
            if not isinstance(hyp, dict):
                continue
            hid = hyp.get("id")
            entry = by_hyp.get(hid)
            if entry is None:
                problems.append(f"{unit_id}: hypothesis {hid} has no reconciliation entry")
                continue
            want = RECOMMENDATION_TO_RESULT.get(hyp.get("recommendation")) \
                if isinstance(hyp.get("recommendation"), str) else None
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

    # 3. sourceHypotheses mirrors the FINDING reconciliations
    for fid, finding in finding_by_id.items():
        declared = set(finding.get("sourceHypotheses") or [])
        incoming = promoted_to.get(fid, set())
        if declared != incoming:
            problems.append(
                f"{fid}: sourceHypotheses does not mirror FINDING reconciliations "
                f"(missing={sorted(incoming - declared)}, extra={sorted(declared - incoming)})"
            )

    # 4. verification files agree with their finding
    for fid, finding in finding_by_id.items():
        relative = finding.get("verificationFile")
        if not isinstance(relative, str):
            continue
        path = resolve_inside(state_dir, relative)
        if not path.is_file():
            continue
        data = load_json_or_exit(path)
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
# verify
# --------------------------------------------------------------------------


def cmd_verify(args: argparse.Namespace) -> int:
    validator_main = _import_validator().main

    return validator_main([str(Path(args.state_dir))])


# --------------------------------------------------------------------------
# check / receive
# --------------------------------------------------------------------------


def _import_validator():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import validate_audit_state as validator

    return validator


def report_validation(v: Any, label: str) -> int:
    for warning in sorted(v.warnings):
        print(f"WARNING {label}: {warning}")
    for error in sorted(v.errors):
        print(f"ERROR {label}: {error}")
    if v.errors:
        print(f"FAIL {label}: {len(v.errors)} error(s)")
        return 1
    print(f"PASS {label}: 0 errors, {len(v.warnings)} warning(s)")
    return 0


def parse_snapshot_arg(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: --snapshot-json is not valid JSON: {exc}") from exc
    if value is not None and not isinstance(value, dict):
        raise SystemExit("ERROR: --snapshot-json must be a JSON object or null")
    return value


def find_unit(state: dict[str, Any], unit_id: str) -> tuple[int | None, dict[str, Any] | None]:
    units = state.get("verificationUnits") or []
    for index, unit in enumerate(units):
        if isinstance(unit, dict) and unit.get("id") == unit_id:
            return index, unit
    return None, None


def validate_investigation_file(state: dict[str, Any], artifact: Path, unit: dict[str, Any], index: int) -> Any:
    """Run the validator's full investigation checks against one file.

    The Validation root is the artifact's own directory so a staged file
    outside the state root still gets a clean relative label; the audit id and
    snapshot underpinning the binding check come from the loaded state.
    """
    validator = _import_validator()
    audit = state.get("audit") if isinstance(state.get("audit"), dict) else {}
    v = validator.Validation(artifact.resolve().parent)
    v.audit_id = audit.get("id")
    v.snapshot = audit.get("snapshot")
    if isinstance(state.get("schemaVersion"), int):
        v.schema_version = state["schemaVersion"]
    validator.validate_investigation(v, artifact, unit, index)
    return v


def cmd_check(args: argparse.Namespace) -> int:
    if args.standalone:
        if args.state_dir:
            return fail("--standalone must not be combined with a state directory")
        missing = [
            name
            for name, value in (
                ("--unit-id", args.unit_id),
                ("--claim-id", args.claim_id),
                ("--method", args.method),
                ("--audit-id", args.audit_id),
                ("--snapshot-json", args.snapshot_json),
            )
            if not value
        ]
        if missing:
            return fail(
                f"--standalone requires {', '.join(missing)}; inject them from the dispatch prompt. "
                "This mode must not read state.json: it contains Gate policy and other investigators' conclusions."
            )
        artifact = Path(args.artifact)
        if not artifact.is_file():
            return fail(f"artifact not found: {artifact}")
        validator = _import_validator()
        fake_unit = {"id": args.unit_id, "claimId": args.claim_id, "method": args.method}
        v = validator.Validation(artifact.resolve().parent)
        v.audit_id = args.audit_id
        v.snapshot = parse_snapshot_arg(args.snapshot_json)
        v.schema_version = args.schema_version
        validator.validate_investigation(v, artifact, fake_unit, 0)
        return report_validation(v, f"standalone check {artifact.name}")

    if not args.state_dir:
        return fail("provide a state directory, or use --standalone for the no-state self-check")
    state_dir = Path(args.state_dir)
    artifact = Path(args.artifact)
    if not artifact.is_file() and not artifact.is_absolute():
        artifact = state_dir / artifact
    if not artifact.is_file():
        return fail(f"artifact not found: {args.artifact}")
    state = load_state(state_dir)
    data = load_json_or_exit(artifact)
    if not isinstance(data, dict):
        return fail(f"{artifact}: must contain a JSON object")
    unit_id = data.get("unitId")
    if not isinstance(unit_id, str) or not unit_id.strip():
        return fail(f"{artifact}: missing or invalid unitId")
    index, unit = find_unit(state, unit_id)
    if unit is None or index is None:
        return fail(f"state.json has no verification unit {unit_id!r}")
    v = validate_investigation_file(state, artifact, unit, index)
    return report_validation(v, f"check {artifact}")


def structural_diff_summary(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in sorted(set(old) - set(new)):
        lines.append(f"- top-level key removed: {key}")
    for key in sorted(set(new) - set(old)):
        lines.append(f"+ top-level key added: {key}")
    for key in sorted(set(old) & set(new)):
        if old[key] != new[key]:
            lines.append(f"~ top-level key changed: {key}")
    for key in ("hypotheses", "evidence"):
        old_ids = {
            item.get("id")
            for item in (old.get(key) or [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        new_ids = {
            item.get("id")
            for item in (new.get(key) or [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for removed in sorted(old_ids - new_ids):
            lines.append(f"- {key} removed: {removed}")
        for added in sorted(new_ids - old_ids):
            lines.append(f"+ {key} added: {added}")
    if not lines:
        lines.append("no structural differences (content-level review remains the main agent's job)")
    return lines


def cmd_receive(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    state = load_state(state_dir)
    staged = Path(args.staged)
    if not staged.is_file():
        return fail(f"staged artifact not found: {staged}")
    data = load_json_or_exit(staged)
    if not isinstance(data, dict):
        return fail(f"{staged}: must contain a JSON object")
    unit_id = data.get("unitId")
    if not isinstance(unit_id, str) or not unit_id.strip():
        return fail(f"{staged}: missing or invalid unitId")
    index, unit = find_unit(state, unit_id)
    if unit is None or index is None:
        return fail(f"state.json has no verification unit {unit_id!r}")
    executor = unit.get("executor")
    if not isinstance(executor, str) or not executor.strip():
        return fail(f"unit {unit_id!r} has no executor yet; dispatch it before receiving its investigation")
    # The state-referenced path wins once the unit has reported, so a re-receive
    # lands on the same file; before that, derive the persona-convention name.
    existing = unit.get("investigationFile")
    if isinstance(existing, str) and existing.strip():
        canonical = resolve_inside(state_dir, existing)
    else:
        canonical = resolve_inside(state_dir, f"investigations/{unit_id}-{executor}.json")

    v = validate_investigation_file(state, staged, unit, index)
    if v.errors:
        for error in sorted(v.errors):
            print(f"ERROR {error}", file=sys.stderr)
        return fail(
            f"{staged}: {len(v.errors)} validation error(s); nothing written. "
            "A mismatched auditBinding means the artifact belongs to another audit or snapshot -- "
            "re-gather it instead of re-stamping."
        )

    replaced = canonical.exists()
    if replaced and not args.force:
        return fail(f"{canonical} already exists; pass --force to replace it (the replacement reports a structural diff)")

    if replaced:
        previous = load_json_or_exit(canonical)
        if isinstance(previous, dict):
            for line in structural_diff_summary(previous, data):
                print(f"DIFF {line}")
        else:
            print("DIFF previous canonical artifact was not a JSON object")

    # Copy the staged bytes verbatim: receive never rewrites content, so the
    # canonical artifact stays a faithful copy of what the investigator
    # delivered and any later normalization is visible against it.
    shutil.copyfile(staged, canonical)
    print(f"{'replaced' if replaced else 'wrote'} {canonical}")
    print(
        "receive does not update state.json: writing the investigationFile reference "
        "and setting status=reported remain main-agent acceptance actions."
    )
    return 0


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Optional helper for building cross-validated-project-audit protocol state.",
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
    p_init.add_argument("--profile", action="append", default=None, metavar="PROFILE",
                        choices=sorted(OBJECTIVE_PROFILES),
                        help="objective profile to enable; 'general' is always included "
                             "(repeat for several, e.g. --profile security)")
    p_init.add_argument("--assumption", help="required and only allowed when --basis is ASSUMED")
    p_init.add_argument("--snapshot-json", help="immutable snapshot object as JSON, e.g. '{\"kind\":\"git\",\"base\":null,\"head\":\"abc\"}'")
    p_init.add_argument("--force", action="store_true", help="overwrite an existing state.json")
    p_init.set_defaults(func=cmd_init)

    p_check = sub.add_parser("check", help="validate one investigation artifact (state-backed or --standalone)")
    p_check.add_argument("state_dir", nargs="?", help="audit instance directory; omit when using --standalone")
    p_check.add_argument("--artifact", required=True, help="staged or referenced investigation JSON")
    p_check.add_argument("--standalone", action="store_true",
                         help="investigator self-check: never read state.json; validate schema, id "
                              "prefixes and internal consistency only")
    p_check.add_argument("--unit-id", help="standalone mode: Unit id from the dispatch prompt")
    p_check.add_argument("--claim-id", help="standalone mode: Claim id from the dispatch prompt")
    p_check.add_argument("--method", help="standalone mode: verification archetype from the dispatch prompt")
    p_check.add_argument("--audit-id", help="standalone mode: audit id from the dispatch prompt")
    p_check.add_argument("--snapshot-json", help="standalone mode: immutable snapshot object as JSON, or null")
    p_check.add_argument("--schema-version", type=int, default=3,
                         help="schema version for standalone checks (default 3)")
    p_check.set_defaults(func=cmd_check)

    p_receive = sub.add_parser("receive", help="validate a staged investigation and copy it to its canonical path")
    p_receive.add_argument("state_dir")
    p_receive.add_argument("--staged", required=True, help="staged investigation JSON outside the state root")
    p_receive.add_argument("--force", action="store_true",
                           help="replace an existing canonical artifact (reports a structural diff)")
    p_receive.set_defaults(func=cmd_receive)

    p_bind = sub.add_parser("bind", help="stamp or verify auditBinding on artifact JSON")
    p_bind.add_argument("state_dir")
    p_bind.add_argument("--artifact", help="stamp only this file; default: every artifact state.json references")
    p_bind.add_argument("--check", action="store_true", help="report only; do not modify files")
    p_bind.add_argument("--force", action="store_true",
                        help="overwrite a mismatched binding (the artifact should normally be re-gathered instead)")
    p_bind.set_defaults(func=cmd_bind)

    p_lint = sub.add_parser("lint", help="report mechanical inconsistencies (read-only)")
    p_lint.add_argument("state_dir")
    p_lint.set_defaults(func=cmd_lint)

    p_verify = sub.add_parser("verify", help="run the validator against an audit instance")
    p_verify.add_argument("state_dir")
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
