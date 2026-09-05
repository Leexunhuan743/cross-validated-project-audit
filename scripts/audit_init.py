#!/usr/bin/env python3
"""Audit artifact scaffolding helper.

Zero third-party dependencies (Python 3.9+ standard library). Provides scaffolding
and pre-flight commands for primary agents and investigators, preventing hand-written
nested JSON slips, driver enum mismatches, and auditBinding drift:

  1. init: create initial state.json skeleton and prepare directory layout
     python -B scripts/audit_init.py init --audit-id <ID> --target "<TARGET>" --scope "<SCOPE>" ...

  2. investigation: scaffold an investigation artifact for a Verification Unit
     python -B scripts/audit_init.py investigation --audit-id <ID> --unit R1 --claim Q1 \
         --method implementation-trace --executor agent-a

  3. check: pre-flight check one investigation artifact before the lead agent
     accepts it (same artifact-side checks the validator runs at reconciliation)
     python -B scripts/audit_init.py check --audit-id <ID> --unit R1 [--executor agent-a]

  4. verification: scaffold a verification artifact for a Finding and second challenge
     python -B scripts/audit_init.py verification --audit-id <ID> --finding F1 \
         --method implementation-trace --checked-evidence R1-E1

All commands automatically bind to the immutable snapshot and auditId from state.json,
and use atomic file writes (.tmp then rename).
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
BLOCK_LEVELS = ("High", "Medium", "Low")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
METHOD_ARCHETYPES = (
    "implementation-trace",
    "user-path-trace",
    "state-invariant-analysis",
    "test-discrimination",
    "adversarial-challenge",
    "history-regression-analysis",
    "contract-spec-verification",
)

# Fields needed per snapshot kind. ACTIVE state allows null.
SNAPSHOT_FIELDS = {
    "git": ("base", "head"),
    "git-worktree": ("base", "head", "initialSha256", "finalSha256"),
    "archive": ("sha256",),
    "deployment": ("version",),
    "other": ("identity",),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_audit_dir(state_root: str, audit_id: str | None, audit_dir: str | None) -> Path:
    """Resolve an audit directory containing state.json."""
    if audit_dir:
        p = Path(audit_dir).resolve()
        if (p / "state.json").is_file():
            return p
        raise FileNotFoundError(f"state.json not found in directory: {p}")

    root = Path(state_root).resolve()
    if audit_id:
        p = root / audit_id
        if (p / "state.json").is_file():
            return p
        raise FileNotFoundError(f"state.json not found in {p} (verify audit-id)")

    if root.is_dir():
        candidates = [d for d in root.iterdir() if d.is_dir() and (d / "state.json").is_file()]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            names = ", ".join(d.name for d in candidates)
            raise ValueError(f"multiple audits found ({names}), please specify --audit-id or --audit-dir")

    raise FileNotFoundError("audit directory not found; specify --audit-id <ID> or --audit-dir <PATH>")


def load_state(audit_dir: Path) -> dict:
    state_file = audit_dir / "state.json"
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"failed to read {state_file}: {exc}") from exc


def atomic_write_json(target: Path, data: dict, force: bool = False) -> None:
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists; pass --force to overwrite")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(target)


# ---------------------------------------------------------------------------
# Command 1: init (scaffold state.json)
# ---------------------------------------------------------------------------

def build_state(args: argparse.Namespace) -> dict:
    snapshot = None
    if args.snapshot_kind:
        snapshot = {"kind": args.snapshot_kind}
        for field in SNAPSHOT_FIELDS[args.snapshot_kind]:
            value = getattr(args, f"snapshot_{field}", None)
            if value is not None:
                snapshot[field] = value

    confidence = getattr(args, "confidence", None) or ("MEDIUM" if args.basis == "ASSUMED" else "HIGH")
    scope_res = {"basis": args.basis, "confidence": confidence}
    if getattr(args, "assumption", None):
        scope_res["assumption"] = args.assumption

    audit = {
        "id": args.audit_id,
        "target": args.target,
        "scope": args.scope,
        "snapshot": snapshot,
        "objectives": args.objective or [],
        "scopeMode": args.scope_mode,
        "objectiveProfiles": ["general", *args.profile],
        "executionMode": args.execution_mode,
        "scopeResolution": scope_res,
        "startedAt": now_iso(),
        "updatedAt": now_iso(),
    }
    if args.deliverable:
        audit["deliverable"] = args.deliverable
    if args.available_evidence:
        audit["availableEvidence"] = args.available_evidence

    if args.gate:
        targets = list(dict.fromkeys(args.gate))
        audit["gates"] = {"targets": targets}
        if args.block_at:
            policies = {}
            block_list = args.block_at if isinstance(args.block_at, list) else [args.block_at]
            for item in block_list:
                if "=" in item or ":" in item:
                    sep = "=" if "=" in item else ":"
                    tgt, lvl = item.split(sep, 1)
                    tgt, lvl = tgt.strip(), lvl.strip()
                    if tgt not in targets:
                        raise ValueError(f"--block-at target {tgt!r} is not in declared --gate targets ({targets})")
                    if lvl not in BLOCK_LEVELS:
                        raise ValueError(f"--block-at level {lvl!r} must be one of {BLOCK_LEVELS}")
                    policies[tgt] = {"blockAtOrAbove": lvl}
                else:
                    lvl = item.strip()
                    if lvl not in BLOCK_LEVELS:
                        raise ValueError(f"--block-at level {lvl!r} must be one of {BLOCK_LEVELS}")
                    for tgt in targets:
                        policies[tgt] = {"blockAtOrAbove": lvl}
            if policies:
                audit["gates"]["policies"] = policies

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
    if args.assumption and args.basis != "ASSUMED":
        print("error: --assumption requires --basis ASSUMED", file=sys.stderr)
        return 2

    state_dir = Path(args.state_root) / args.audit_id
    target = state_dir / "state.json"
    if target.exists() and not args.force:
        print(f"error: {target} already exists; pass --force to overwrite", file=sys.stderr)
        return 2

    state = build_state(args)
    for area in ("investigations", "probes", "scratch"):
        (state_dir / area).mkdir(parents=True, exist_ok=True)

    try:
        atomic_write_json(target, state, force=args.force)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"created {target}")
    code, output = run_validator(state_dir, script_dir)
    print(output)
    if code != 0:
        print("\nwarning: skeleton failed validation; fix parameters before continuing", file=sys.stderr)
        return code

    steps = []
    if not state["audit"]["objectives"]:
        steps.append("fill audit.objectives — a non-empty objective list cannot be closed by zero claims")
    steps.append("add claims[] and verificationUnits[] (see SKILL.md §3 step 2)")
    steps.append(f"to scaffold an investigation, run: python -B scripts/audit_init.py investigation "
                 f"--audit-id {args.audit_id} --unit R1 --claim Q1 --method <ARCHETYPE> --executor <EXECUTOR>")
    if args.gate:
        steps.append(f"Gate targets {', '.join(state['audit']['gates']['targets'])} registered; derived at completion")
    steps.append("re-run the validator after every material change")
    print("\nnext:")
    for index, step in enumerate(steps, 1):
        print(f"  {index}. {step}")
    return 0


# ---------------------------------------------------------------------------
# Command 2: investigation (scaffold investigation artifact)
# ---------------------------------------------------------------------------

def cmd_investigation(args: argparse.Namespace) -> int:
    try:
        audit_dir = resolve_audit_dir(args.state_root, args.audit_id, args.audit_dir)
        state = load_state(audit_dir)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not SAFE_ID.match(args.unit):
        print(f"error: --unit must match [A-Za-z0-9_-]+ (got {args.unit!r})", file=sys.stderr)
        return 2
    if not SAFE_ID.match(args.claim):
        print(f"error: --claim must match [A-Za-z0-9_-]+ (got {args.claim!r})", file=sys.stderr)
        return 2
    if not SAFE_ID.match(args.executor):
        print(f"error: --executor must match [A-Za-z0-9_-]+ (got {args.executor!r})", file=sys.stderr)
        return 2

    audit_binding = {
        "auditId": state["audit"]["id"],
        "snapshot": state["audit"].get("snapshot"),
    }

    unit_id = args.unit
    claim_id = args.claim
    method = args.method
    evidence_id = f"{unit_id}-E1"
    hypothesis_id = f"{unit_id}-H1"

    if args.clean:
        hypotheses = []
        evidence = [
            {
                "id": evidence_id,
                "polarity": "context",
                "strength": "ES2",
                "reproducibility": "repeatable",
                "source": "TODO: path:line or reproducible command",
                "observation": "TODO: direct observation confirming expected behavior",
            }
        ]
        behaviors = [
            {
                "behavior": "TODO: statement of verified correct behavior",
                "evidenceRefs": [evidence_id],
            }
        ]
    else:
        hypotheses = [
            {
                "id": hypothesis_id,
                "statement": "TODO: material, testable suspicion statement",
                "potentialImpact": "TODO: impact if true",
                "conditions": "TODO: trigger conditions or input bounds",
                "counterHypothesis": "TODO: strongest realistic safe explanation",
                "expectedSafeBehavior": "TODO: expected safe behavior if correct",
                "evidenceSearched": "TODO: scope and paths searched for evidence",
                "disconfirmationResult": "counter-refuted",
                "evidenceRefs": [evidence_id],
                "result": "supported",
                "recommendation": "promote-to-finding",
                "reasoning": "TODO: analytical reasoning connecting evidence to hypothesis",
            }
        ]
        evidence = [
            {
                "id": evidence_id,
                "polarity": "supports",
                "strength": "ES2",
                "reproducibility": "repeatable",
                "source": "TODO: path:line or reproducible command",
                "observation": "TODO: direct observation (not inference)",
            }
        ]
        behaviors = [
            {
                "behavior": "TODO: statement of verified correct behavior",
                "evidenceRefs": [evidence_id],
            }
        ]

    investigation_data = {
        "auditBinding": audit_binding,
        "unitId": unit_id,
        "claimId": claim_id,
        "method": method,
        "hypotheses": hypotheses,
        "evidence": evidence,
        "coverageSummary": {
            "checked": ["TODO: list inspected entrypoints or scopes"],
            "verifiedBehaviors": behaviors,
            "gaps": [],
        },
    }

    target_file = audit_dir / "investigations" / f"{unit_id}-{args.executor}.json"
    try:
        atomic_write_json(target_file, investigation_data, force=args.force)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Create temporary probes and scratch workspaces for this unit
    probes_dir = audit_dir / "probes" / f"{unit_id}-{args.executor}"
    scratch_dir = audit_dir / "scratch" / f"{unit_id}-{args.executor}"
    probes_dir.mkdir(parents=True, exist_ok=True)
    scratch_dir.mkdir(parents=True, exist_ok=True)

    rel_target = target_file.relative_to(Path.cwd()) if target_file.is_relative_to(Path.cwd()) else target_file
    print(f"created investigation skeleton: {rel_target}")
    print(f"created temporary workspaces:\n  probes/{unit_id}-{args.executor}/\n  scratch/{unit_id}-{args.executor}/")
    print("\nnext:")
    print(f"  1. open {rel_target} and fill actual source and observation")
    print(f"  2. place probe / reproduction scripts into probes/{unit_id}-{args.executor}/")
    print(f"  3. run: audit_init.py check --audit-id {state['audit']['id']} --unit {unit_id}")
    print(f"  4. advance Unit to reported in state.json and cite this file")
    print("\nenums -- misspelling or omitting any of these stops the invariant that reads it:")
    print("  result ∈ {supported, refuted, unresolved}")
    print("  recommendation ∈ {promote-to-finding, close, residual-gap}")
    print("  disconfirmationResult ∈ {counter-refuted, counter-supported, unresolved}")
    print("  polarity ∈ {supports, refutes, context}")
    print("  strength ∈ {ES1, ES2, ES3, ES4}")
    print("  reproducibility ∈ {repeatable, conditional, single-observation, not-applicable}")
    print(f"  method: keep {method} -- rewriting it voids the heterogeneity check")
    return 0


# ---------------------------------------------------------------------------
# Command 3: check (pre-flight validation of one investigation artifact)
# ---------------------------------------------------------------------------

def load_validator():
    """Loads validate_audit_state.py from this script's directory. The pre-flight
    check and the full audit run must never drift apart, so it imports the same
    module instead of re-implementing its checks."""
    import importlib.util

    path = Path(__file__).with_name("validate_audit_state.py")
    if not path.is_file():
        raise FileNotFoundError(f"validator not found next to audit_init.py: {path}")
    spec = importlib.util.spec_from_file_location("validate_audit_state", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cmd_check(args: argparse.Namespace) -> int:
    """Applies the artifact-side enum, disconfirmation and binding checks before
    the lead agent accepts the artifact, so enum drift surfaces at write time
    rather than at reconciliation."""
    try:
        audit_dir = resolve_audit_dir(args.state_root, args.audit_id, args.audit_dir)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not SAFE_ID.match(args.unit):
        print(f"error: --unit must match [A-Za-z0-9_-]+ (got {args.unit!r})", file=sys.stderr)
        return 2

    if args.executor:
        targets = [f"investigations/{args.unit}-{args.executor}.json"]
    else:
        investigations = audit_dir / "investigations"
        matches = sorted(p.name for p in investigations.glob(f"{args.unit}-*.json")) if investigations.is_dir() else []
        if not matches:
            print(f"error: no investigations/{args.unit}-*.json under {audit_dir}", file=sys.stderr)
            return 2
        targets = [f"investigations/{name}" for name in matches]

    try:
        validator = load_validator()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    failed = 0
    for rel in targets:
        failed += validator.emit(validator.validate_investigation(Path(audit_dir), rel))
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# Command 4: verification (scaffold verification artifact)
# ---------------------------------------------------------------------------

def cmd_verification(args: argparse.Namespace) -> int:
    try:
        audit_dir = resolve_audit_dir(args.state_root, args.audit_id, args.audit_dir)
        state = load_state(audit_dir)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not SAFE_ID.match(args.finding):
        print(f"error: --finding must match [A-Za-z0-9_-]+ (got {args.finding!r})", file=sys.stderr)
        return 2

    audit_binding = {
        "auditId": state["audit"]["id"],
        "snapshot": state["audit"].get("snapshot"),
    }

    finding_id = args.finding
    method = args.method
    evidence_id = f"{finding_id}-E1"
    checked_ev = args.checked_evidence or ["R1-E1"]

    verification_data = {
        "auditBinding": audit_binding,
        "findingId": finding_id,
        "method": method,
        "checkedEvidence": checked_ev,
        "evidence": [
            {
                "id": evidence_id,
                "polarity": "supports",
                "strength": "ES2",
                "reproducibility": "repeatable",
                "source": "TODO: primary source path:line or command confirmed by primary agent",
                "observation": "TODO: decisive observation confirmed during verification",
            }
        ],
        "conclusion": f"TODO: primary agent's decisive conclusion for {finding_id}",
        "limits": [],
    }

    if not args.no_challenge:
        if args.challenge_mode == "EQUIVALENT-DIRECT-DISCONFIRMATION":
            verification_data["challenge"] = {
                "status": "COMPLETED",
                "mode": "EQUIVALENT-DIRECT-DISCONFIRMATION",
                "evidenceRefs": [evidence_id],
                "result": "counter-refuted",
            }
        else:
            challenge_unit = args.challenge_unit or "R2"
            fallback_method = "state-invariant-analysis" if method == "test-discrimination" else "test-discrimination"
            challenge_method = args.challenge_method or fallback_method
            verification_data["challenge"] = {
                "status": "COMPLETED",
                "mode": "HETEROGENEOUS-METHOD",
                "unitId": challenge_unit,
                "method": challenge_method,
                "evidenceRefs": [f"{challenge_unit}-E1"],
                "result": "counter-refuted",
            }

    target_file = audit_dir / "verification" / f"{finding_id}.json"
    try:
        atomic_write_json(target_file, verification_data, force=args.force)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rel_target = target_file.relative_to(Path.cwd()) if target_file.is_relative_to(Path.cwd()) else target_file
    print(f"created verification skeleton: {rel_target}")
    print("\nnext:")
    print(f"  1. review and replace TODO placeholders with verified observations")
    print(f"  2. verify challenge unit reference and method heterogeneity")
    print(f"  3. set verificationFile: \"verification/{finding_id}.json\" in state.json.findings[]")
    return 0


# ---------------------------------------------------------------------------
# CLI Parser Construction
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audit_init.py",
        description="Audit artifact scaffolding helper (state.json, investigation, and verification)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # 1. init
    init = sub.add_parser("init", help="initialize audit instance and state.json skeleton")
    init.add_argument("--audit-id", required=True, help="filename-safe id, unique within state root")
    init.add_argument("--target", required=True, help="what is being audited")
    init.add_argument("--scope", required=True, help="bounded audit scope")
    init.add_argument("--state-root", default=".audits", help="default: .audits")
    init.add_argument("--scope-mode", default="change", choices=SCOPE_MODES)
    init.add_argument("--objective", action="append", metavar="TEXT",
                      help="repeatable; audit objective")
    init.add_argument("--profile", action="append", default=[], metavar="NAME",
                      help="extra objective profile beyond 'general'")
    init.add_argument("--execution-mode", default="audit-only", choices=("audit-only", "audit-and-fix"))
    init.add_argument("--basis", default="USER", choices=("USER", "PLATFORM", "REPOSITORY", "ASSUMED"))
    init.add_argument("--confidence", choices=("HIGH", "MEDIUM", "LOW"),
                      help="scopeResolution confidence (defaults to MEDIUM for ASSUMED, else HIGH)")
    init.add_argument("--assumption", help="assumption statement required when --basis ASSUMED")
    init.add_argument("--deliverable", help="what the user receives")
    init.add_argument("--available-evidence", action="append", metavar="TEXT")
    init.add_argument("--gate", action="append", choices=GATE_TARGETS,
                      help="repeatable; requested Gate target")
    init.add_argument("--block-at", action="append", metavar="SPEC",
                      help="tighten Gate threshold (e.g. Medium, or per-target RELEASE=Medium; repeatable; requires --gate)")
    init.add_argument("--snapshot-kind", choices=tuple(SNAPSHOT_FIELDS))
    for field in sorted({f for fields in SNAPSHOT_FIELDS.values() for f in fields}):
        init.add_argument(f"--snapshot-{field}", metavar="VALUE", help=f"snapshot field: {field}")
    init.add_argument("--force", action="store_true", help="overwrite existing state.json")
    init.set_defaults(func=cmd_init)

    # 2. investigation
    inv = sub.add_parser("investigation", help="scaffold investigation artifact (investigations/<unit>-<executor>.json)")
    inv.add_argument("--audit-id", help="audit id (searches in .audits/<audit-id>)")
    inv.add_argument("--audit-dir", help="explicit audit instance directory path")
    inv.add_argument("--state-root", default=".audits", help="state root, default: .audits")
    inv.add_argument("--unit", required=True, help="Verification Unit id (e.g. R1)")
    inv.add_argument("--claim", required=True, help="associated Claim id (e.g. Q1)")
    inv.add_argument("--method", required=True, choices=METHOD_ARCHETYPES, help="verification archetype")
    inv.add_argument("--executor", required=True, help="executor identifier (e.g. agent-a, main)")
    inv.add_argument("--clean", action="store_true", help="scaffold a clean unit with empty hypotheses")
    inv.add_argument("--force", action="store_true", help="overwrite existing artifact")
    inv.set_defaults(func=cmd_investigation)

    # 3. check
    chk = sub.add_parser("check", help="pre-flight check an investigation artifact (investigations/<unit>-<executor>.json)")
    chk.add_argument("--audit-id", help="audit id (searches in .audits/<audit-id>)")
    chk.add_argument("--audit-dir", help="explicit audit instance directory path")
    chk.add_argument("--state-root", default=".audits", help="state root, default: .audits")
    chk.add_argument("--unit", required=True, help="Verification Unit id (e.g. R1)")
    chk.add_argument("--executor", help="executor identifier; omit to check every artifact for this unit")
    chk.set_defaults(func=cmd_check)

    # 4. verification
    ver = sub.add_parser("verification", help="scaffold verification artifact (verification/<finding>.json)")
    ver.add_argument("--audit-id", help="audit id (searches in .audits/<audit-id>)")
    ver.add_argument("--audit-dir", help="explicit audit instance directory path")
    ver.add_argument("--state-root", default=".audits", help="state root, default: .audits")
    ver.add_argument("--finding", required=True, help="Finding id (e.g. F1)")
    ver.add_argument("--method", required=True, choices=METHOD_ARCHETYPES, help="primary verification method")
    ver.add_argument("--checked-evidence", action="append", metavar="ID", help="checked evidence id (repeatable)")
    ver.add_argument("--challenge-mode", choices=("HETEROGENEOUS-METHOD", "EQUIVALENT-DIRECT-DISCONFIRMATION"),
                     default="HETEROGENEOUS-METHOD", help="challenge mode")
    ver.add_argument("--challenge-unit", help="heterogeneous challenge unit id (e.g. R2)")
    ver.add_argument("--challenge-method", choices=METHOD_ARCHETYPES, help="challenge method (must differ from --method)")
    ver.add_argument("--no-challenge", action="store_true", help="omit challenge block")
    ver.add_argument("--force", action="store_true", help="overwrite existing artifact")
    ver.set_defaults(func=cmd_verification)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "init" and getattr(args, "block_at", None) and not getattr(args, "gate", None):
        print("error: --block-at requires --gate", file=sys.stderr)
        return 2
    if args.command == "init" and getattr(args, "assumption", None) and getattr(args, "basis", None) != "ASSUMED":
        print("error: --assumption requires --basis ASSUMED", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
