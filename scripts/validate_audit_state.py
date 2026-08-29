#!/usr/bin/env python3
"""Validate cross-validated-project-audit protocol-v2 state.

The validator intentionally uses only the Python standard library.  It checks
the live state graph and the investigation/verification JSON artifacts that the
state references.  It does not decide whether an audit conclusion is factually
correct; it prevents internally impossible states and over-strong Gate results.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 2
PHASES = {"ACTIVE", "FINAL", "SUPERSEDED"}
SCOPE_MODES = {"project", "change", "pr", "author-commits"}
OBJECTIVE_PROFILES = {"general", "security", "fix-verification"}
EXECUTION_MODES = {"audit-only", "audit-and-fix"}
SCOPE_BASIS = {"USER", "PLATFORM", "REPOSITORY", "ASSUMED"}
SCOPE_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
GATE_TARGETS = {"CHANGE", "RELEASE", "SYSTEM"}
GATE_RESULTS = {"READY", "READY-WITH-CONDITIONS", "BLOCKED", "INCOMPLETE"}
PRIORITIES = {"highest", "high", "normal"}
OBLIGATIONS = {"REQUIRED", "EXPLORATORY"}
UNIT_STATUS = {"planned", "dispatched", "reported", "verified"}
METHODS = {
    "implementation-trace",
    "user-path-trace",
    "state-invariant-analysis",
    "test-discrimination",
    "adversarial-challenge",
    "history-regression-analysis",
    "contract-spec-verification",
}
ISOLATION = {"ISOLATED", "NOT-ISOLATED"}
DECISIONS = {"PENDING", "CONFIRMED", "CONDITIONAL", "NEEDS-DECISION", "REJECTED"}
SEVERITIES = {"Critical", "High", "Medium", "Low"}
CONFIDENCE = {"Very-High", "High", "Medium", "Low"}
DISPOSITIONS = {"REMEDIATING", "RESOLVED-VERIFIED", "ACCEPTED-RISK"}
PATTERN_SCOPE = {"ISOLATED", "SYSTEMIC", "UNKNOWN"}
PROVENANCE = {"INTRODUCED", "EXPOSED", "REGRESSED", "PRE_EXISTING", "UNKNOWN"}
APPLICABILITY = {"APPLIES", "DOES-NOT-APPLY", "UNRESOLVED"}
EVIDENCE_POLARITY = {"supports", "refutes", "context"}
EVIDENCE_STRENGTH = {"ES1", "ES2", "ES3", "ES4"}
REPRODUCIBILITY = {"repeatable", "conditional", "single-observation", "not-applicable"}
HYPOTHESIS_RESULTS = {"supported", "refuted", "unresolved"}
DISCONFIRMATION_RESULTS = {"counter-supported", "counter-refuted", "unresolved"}
RECONCILIATION_RESULTS = {"FINDING", "REFUTED", "RESIDUAL-GAP"}
CHALLENGE_STATUS = {"COMPLETED", "GAP"}
CHALLENGE_MODES = {"HETEROGENEOUS-METHOD", "EQUIVALENT-DIRECT-DISCONFIRMATION"}
FIX_BATCH_KINDS = {"FIX", "VERIFY", "REGRESSION"}
FIX_BATCH_STATUS = {"PENDING", "PASSED", "FAILED"}
RISK_IMPACT = {"Critical", "High", "Medium", "Low"}
RISK_LIKELIHOOD = {"High", "Medium", "Low"}
RISK_REACHABILITY = {"Common", "Conditional", "Privileged"}
RISK_RECOVERABILITY = {"Irreversible", "Manual", "Automatic"}
AUDIT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
GIT_OBJECT_ID_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
ID_PATTERNS = {
    "claim": re.compile(r"^Q[1-9][0-9]*$"),
    "unit": re.compile(r"^R[1-9][0-9]*$"),
    "finding": re.compile(r"^F[1-9][0-9]*$"),
    "fact": re.compile(r"^P[1-9][0-9]*$"),
    "residual": re.compile(r"^G[1-9][0-9]*$"),
}


class Validation:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.hypotheses: set[str] = set()
        self.evidence: set[str] = set()
        self.evidence_polarity: dict[str, str] = {}
        self.investigation_evidence: set[str] = set()
        self.unit_hypotheses: dict[str, set[str]] = {}
        self.unit_evidence: dict[str, set[str]] = {}
        self.hypothesis_evidence: dict[str, set[str]] = {}
        self.hypothesis_recommendations: dict[str, str] = {}
        self.verification_checked: dict[str, set[str]] = {}
        self.verification_evidence: dict[str, set[str]] = {}
        self.verification_method: dict[str, str] = {}
        self.verification_challenge: dict[str, dict[str, Any]] = {}
        self.verification_resolution_challenge: dict[str, dict[str, Any]] = {}
        self.test_discrimination_results: dict[str, str] = {}
        self.audit_id: str | None = None
        self.snapshot: dict[str, Any] | None = None

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path}: {message}")

    def warning(self, path: str, message: str) -> None:
        self.warnings.append(f"{path}: {message}")

    def require(self, obj: dict[str, Any], key: str, path: str, kind: type | tuple[type, ...] | None = None) -> Any:
        if key not in obj:
            self.error(path, f"missing required key {key!r}")
            return None
        value = obj[key]
        if kind is not None and (
            not isinstance(value, kind)
            or (kind is int and isinstance(value, bool))
        ):
            self.error(f"{path}.{key}", f"expected {type_name(kind)}, got {type(value).__name__}")
            return None
        return value

    def enum(self, value: Any, allowed: set[str], path: str) -> None:
        if not isinstance(value, str) or value not in allowed:
            self.error(path, f"invalid value {value!r}; allowed: {', '.join(sorted(allowed))}")

    def nonempty(self, value: Any, path: str) -> None:
        if isinstance(value, str) and not value.strip():
            self.error(path, "must not be empty")
        elif isinstance(value, list) and not value:
            self.error(path, "must not be empty")

    def closed_object(self, value: Any, path: str, allowed: set[str]) -> None:
        """Reject unmodelled protocol fields while reserving non-semantic metadata."""
        if not isinstance(value, dict):
            return
        unknown = set(value) - allowed - {"metadata"}
        if unknown:
            self.error(path, f"unsupported keys: {sorted(unknown)}")
        if "metadata" in value and not isinstance(value["metadata"], dict):
            self.error(f"{path}.metadata", "expected object for non-semantic extension metadata")

    def id(self, value: Any, kind: str, path: str) -> None:
        if not isinstance(value, str) or not ID_PATTERNS[kind].fullmatch(value):
            self.error(path, f"expected {kind} id matching {ID_PATTERNS[kind].pattern}")

    def safe_json_path(self, relative: Any, path: str, expected_directory: str | None = None) -> Path | None:
        if not isinstance(relative, str) or not relative.endswith(".json"):
            self.error(path, "must be a relative .json path")
            return None
        raw_path = Path(relative)
        if raw_path.is_absolute():
            self.error(path, "must be a relative .json path")
            return None
        lexical_candidate = self.root / raw_path
        if is_link_like(lexical_candidate):
            self.error(path, "referenced artifact must not be a symlink or junction")
            return None
        if expected_directory is not None and is_link_like(self.root / expected_directory):
            self.error(path, f"{expected_directory}/ must not be a symlink or junction")
            return None
        candidate = lexical_candidate.resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            self.error(path, "path escapes the audit state directory")
            return None
        if expected_directory is not None:
            expected_parent = (self.root / expected_directory).resolve()
            if raw_path.parent != Path(expected_directory) or candidate.parent != expected_parent:
                self.error(path, f"must be a flat .json file directly under {expected_directory}/")
                return None
        if not candidate.is_file():
            self.error(path, f"referenced file does not exist: {relative}")
            return None
        return candidate


def type_name(kind: type | tuple[type, ...]) -> str:
    if isinstance(kind, tuple):
        return " or ".join(item.__name__ for item in kind)
    return kind.__name__


def is_link_like(path: Path) -> bool:
    """Reject symlinks and Windows junctions at state trust boundaries."""
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and bool(is_junction()):
            return True
        try:
            file_state = path.lstat()
        except FileNotFoundError:
            return False
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(reparse_flag and getattr(file_state, "st_file_attributes", 0) & reparse_flag)
    except OSError:
        return True


def string_items(v: Validation, value: Any, path: str) -> list[str]:
    """Return valid non-empty string entries while recording malformed ones."""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            v.error(f"{path}[{index}]", "expected non-empty string")
        else:
            result.append(item)
    return result


def string_set(value: Any) -> set[str]:
    """Return string members for safe downstream set and membership operations."""
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def permitted_severities(risk: dict[str, Any]) -> set[str]:
    """Return the finite Severity values permitted by the normative risk mapping."""
    ranks = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
    impact = risk.get("impact")
    if impact not in ranks:
        return set()
    permitted = {impact}
    rank = ranks[impact]
    if risk.get("likelihood") == "Low" and (
        risk.get("reachability") == "Privileged" or risk.get("recoverability") == "Automatic"
    ):
        permitted.add(next(name for name, value in ranks.items() if value == max(1, rank - 1)))
    if (
        risk.get("likelihood") == "High"
        and risk.get("reachability") == "Common"
        and risk.get("recoverability") == "Irreversible"
    ):
        permitted.add(next(name for name, value in ranks.items() if value == min(4, rank + 1)))
    return permitted


def validate_allowed_path(v: Validation, value: str, path: str) -> None:
    """Validate a portable, lexical, relative repair-scope path."""
    if "\x00" in value:
        v.error(path, "must not contain NUL")
        return
    if "/" in value and "\\" in value:
        v.error(path, "must use one portable path separator")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized) or normalized.startswith("//"):
        v.error(path, "must be a relative path")
    if ":" in normalized:
        v.error(path, "must not contain a drive or URI colon")
    segments = normalized.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        v.error(path, "must not contain empty, '.', or '..' path segments")


def load_json(path: Path, validation: Validation, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        validation.error(label, f"not valid UTF-8: {exc}")
    except json.JSONDecodeError as exc:
        validation.error(label, f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
    except OSError as exc:
        validation.error(label, f"cannot read: {exc}")
    return None


def validate_snapshot(v: Validation, audit: dict[str, Any]) -> None:
    """Validate the bounded immutable identity variants used for recovery."""
    if "snapshot" not in audit:
        v.error("state.json.audit", "missing required key 'snapshot'")
        return
    snapshot = audit["snapshot"]
    if snapshot is None:
        return
    path = "state.json.audit.snapshot"
    if not isinstance(snapshot, dict):
        v.error(path, "expected object")
        return
    kind = v.require(snapshot, "kind", path, str)
    if isinstance(kind, str):
        v.enum(kind, {"git", "git-worktree", "archive", "deployment", "other"}, f"{path}.kind")
    allowed: set[str] = {"kind"}
    if kind == "git":
        allowed |= {"base", "head"}
        head = v.require(snapshot, "head", path, str)
        if isinstance(head, str) and not GIT_OBJECT_ID_PATTERN.fullmatch(head):
            v.error(f"{path}.head", "expected immutable 40- or 64-hex Git object id")
        base = snapshot.get("base")
        if base is not None and (not isinstance(base, str) or not GIT_OBJECT_ID_PATTERN.fullmatch(base)):
            v.error(f"{path}.base", "expected null or immutable 40- or 64-hex Git object id")
    elif kind == "git-worktree":
        allowed |= {"base", "head", "initialSha256", "finalSha256"}
        head = v.require(snapshot, "head", path, str)
        if isinstance(head, str) and not GIT_OBJECT_ID_PATTERN.fullmatch(head):
            v.error(f"{path}.head", "expected immutable 40- or 64-hex Git object id")
        base = snapshot.get("base")
        if base is not None and (not isinstance(base, str) or not GIT_OBJECT_ID_PATTERN.fullmatch(base)):
            v.error(f"{path}.base", "expected null or immutable 40- or 64-hex Git object id")
        for key in ("initialSha256", "finalSha256"):
            digest = v.require(snapshot, key, path, str)
            if isinstance(digest, str) and not SHA256_PATTERN.fullmatch(digest):
                v.error(f"{path}.{key}", "expected 64-hex SHA-256 worktree manifest identity")
    elif kind == "archive":
        allowed.add("sha256")
        digest = v.require(snapshot, "sha256", path, str)
        if isinstance(digest, str) and not SHA256_PATTERN.fullmatch(digest):
            v.error(f"{path}.sha256", "expected 64-hex SHA-256")
    elif kind == "deployment":
        allowed.add("version")
        version = v.require(snapshot, "version", path, str)
        if isinstance(version, str):
            v.nonempty(version, f"{path}.version")
    elif kind == "other":
        allowed.add("identity")
        identity = v.require(snapshot, "identity", path, str)
        if isinstance(identity, str):
            v.nonempty(identity, f"{path}.identity")
    unknown = set(snapshot) - allowed
    if unknown:
        v.error(path, f"unsupported keys for kind {kind!r}: {sorted(unknown)}")


def validate_evidence(v: Validation, item: Any, path: str, prefix: str) -> None:
    if not isinstance(item, dict):
        v.error(path, "expected object")
        return
    v.closed_object(
        item,
        path,
        {"id", "polarity", "strength", "reproducibility", "source", "observation", "testDiscrimination"},
    )
    evidence_id = v.require(item, "id", path, str)
    if isinstance(evidence_id, str):
        if not evidence_id.startswith(prefix + "-E") or not re.fullmatch(re.escape(prefix) + r"-E[1-9][0-9]*", evidence_id):
            v.error(f"{path}.id", f"must use {prefix}-E<n>")
        if evidence_id in v.evidence:
            v.error(f"{path}.id", f"duplicate evidence id {evidence_id}")
        v.evidence.add(evidence_id)
    for key, allowed in (
        ("polarity", EVIDENCE_POLARITY),
        ("strength", EVIDENCE_STRENGTH),
        ("reproducibility", REPRODUCIBILITY),
    ):
        value = v.require(item, key, path, str)
        if isinstance(value, str):
            v.enum(value, allowed, f"{path}.{key}")
    if isinstance(evidence_id, str) and isinstance(item.get("polarity"), str) and item["polarity"] in EVIDENCE_POLARITY:
        v.evidence_polarity[evidence_id] = item["polarity"]
    strength = item.get("strength")
    reproducibility = item.get("reproducibility")
    if strength in {"ES3", "ES4"} and reproducibility in {"single-observation", "not-applicable"}:
        v.error(
            f"{path}.reproducibility",
            f"{strength} requires repeatable or explicitly conditional reproduction",
        )
    for key in ("source", "observation"):
        value = v.require(item, key, path, str)
        if isinstance(value, str):
            v.nonempty(value, f"{path}.{key}")
    test = item.get("testDiscrimination")
    if test is not None:
        if not isinstance(test, dict):
            v.error(f"{path}.testDiscrimination", "expected object")
        else:
            v.closed_object(test, f"{path}.testDiscrimination", {"result", "test", "basis", "issue"})
            result = v.require(test, "result", f"{path}.testDiscrimination", str)
            if isinstance(result, str):
                v.enum(result, {"YES", "PARTIAL", "NO", "UNKNOWN"}, f"{path}.testDiscrimination.result")
                if isinstance(evidence_id, str) and result in {"YES", "PARTIAL", "NO", "UNKNOWN"}:
                    v.test_discrimination_results[evidence_id] = result
            for key in ("test", "basis"):
                value = v.require(test, key, f"{path}.testDiscrimination", str)
                if isinstance(value, str):
                    v.nonempty(value, f"{path}.testDiscrimination.{key}")
            issue = test.get("issue")
            if issue is not None:
                v.enum(issue, {"ENCODES_FAILURE", "MISSING_REGRESSION"}, f"{path}.testDiscrimination.issue")


def validate_artifact_binding(v: Validation, data: dict[str, Any], label: str) -> None:
    """Bind each evidence-bearing artifact to one audit instance and snapshot."""
    path = f"{label}.auditBinding"
    binding = v.require(data, "auditBinding", label, dict)
    if not isinstance(binding, dict):
        return
    audit_id = v.require(binding, "auditId", path, str)
    if isinstance(audit_id, str) and audit_id != v.audit_id:
        v.error(f"{path}.auditId", f"must equal current audit id {v.audit_id!r}")
    if "snapshot" not in binding:
        v.error(path, "missing required key 'snapshot'")
    elif binding["snapshot"] != v.snapshot:
        v.error(f"{path}.snapshot", "must exactly equal the current audit snapshot")
    unknown = set(binding) - {"auditId", "snapshot"}
    if unknown:
        v.error(path, f"unsupported keys: {sorted(unknown)}")


def validate_authorization_binding(v: Validation, value: Any, path: str, target: str | None = None) -> None:
    """Require risk acceptance to name the exact audit, snapshot and optional Gate."""
    if not isinstance(value, dict):
        v.error(path, "expected authorization object bound to the current audit and snapshot")
        return
    text = v.require(value, "text", path, str)
    if isinstance(text, str):
        v.nonempty(text, f"{path}.text")
    audit_id = v.require(value, "auditId", path, str)
    if isinstance(audit_id, str) and audit_id != v.audit_id:
        v.error(f"{path}.auditId", f"must equal current audit id {v.audit_id!r}")
    if "snapshot" not in value:
        v.error(path, "missing required key 'snapshot'")
    elif value["snapshot"] != v.snapshot:
        v.error(f"{path}.snapshot", "must exactly equal the current audit snapshot")
    allowed = {"text", "auditId", "snapshot"}
    if target is not None:
        allowed.add("target")
        bound_target = v.require(value, "target", path, str)
        if isinstance(bound_target, str) and bound_target != target:
            v.error(f"{path}.target", f"must equal Gate target {target!r}")
    elif "target" in value:
        v.error(f"{path}.target", "must be omitted for audit-wide risk acceptance")
    unknown = set(value) - allowed
    if unknown:
        v.error(path, f"unsupported keys: {sorted(unknown)}")


def validate_investigation(v: Validation, path: Path, unit: dict[str, Any], index: int) -> None:
    label = str(path.relative_to(v.root)).replace("\\", "/")
    data = load_json(path, v, label)
    if not isinstance(data, dict):
        if data is not None:
            v.error(label, "expected object")
        return
    v.closed_object(data, label, {"auditBinding", "unitId", "claimId", "method", "hypotheses", "evidence", "coverageSummary"})
    validate_artifact_binding(v, data, label)
    if data.get("unitId") != unit.get("id"):
        v.error(f"{label}.unitId", f"must equal verificationUnits[{index}].id")
    if data.get("claimId") != unit.get("claimId"):
        v.error(f"{label}.claimId", f"must equal verificationUnits[{index}].claimId")
    if data.get("method") != unit.get("method"):
        v.error(f"{label}.method", f"must equal verificationUnits[{index}].method")
    hypotheses = v.require(data, "hypotheses", label, list)
    evidence = v.require(data, "evidence", label, list)
    summary = v.require(data, "coverageSummary", label, dict)
    local_evidence: set[str] = set()
    if isinstance(evidence, list):
        for e_index, item in enumerate(evidence):
            validate_evidence(v, item, f"{label}.evidence[{e_index}]", str(unit.get("id", "R?")))
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                local_evidence.add(item["id"])
                v.investigation_evidence.add(item["id"])
    if isinstance(unit.get("id"), str):
        v.unit_evidence[unit["id"]] = local_evidence
    if unit.get("status") == "verified" and not local_evidence:
        v.error(f"{label}.evidence", "verified Unit requires at least one DIRECT Evidence")
    if isinstance(hypotheses, list):
        local_hypotheses: set[str] = set()
        for h_index, item in enumerate(hypotheses):
            h_path = f"{label}.hypotheses[{h_index}]"
            if not isinstance(item, dict):
                v.error(h_path, "expected object")
                continue
            v.closed_object(
                item,
                h_path,
                {"id", "statement", "potentialImpact", "conditions", "counterHypothesis", "expectedSafeBehavior", "evidenceSearched", "reasoning", "disconfirmationResult", "result", "recommendation", "evidenceRefs"},
            )
            hypothesis_id = v.require(item, "id", h_path, str)
            prefix = str(unit.get("id", "R?"))
            if isinstance(hypothesis_id, str):
                if not re.fullmatch(re.escape(prefix) + r"-H[1-9][0-9]*", hypothesis_id):
                    v.error(f"{h_path}.id", f"must use {prefix}-H<n>")
                if hypothesis_id in v.hypotheses:
                    v.error(f"{h_path}.id", f"duplicate hypothesis id {hypothesis_id}")
                v.hypotheses.add(hypothesis_id)
                local_hypotheses.add(hypothesis_id)
            for key in ("statement", "potentialImpact", "conditions", "counterHypothesis", "expectedSafeBehavior", "evidenceSearched", "reasoning"):
                value = v.require(item, key, h_path, str)
                if isinstance(value, str):
                    v.nonempty(value, f"{h_path}.{key}")
            disconfirmation_result = v.require(item, "disconfirmationResult", h_path, str)
            if isinstance(disconfirmation_result, str):
                v.enum(disconfirmation_result, DISCONFIRMATION_RESULTS, f"{h_path}.disconfirmationResult")
            hypothesis_result = v.require(item, "result", h_path, str)
            if isinstance(hypothesis_result, str):
                v.enum(hypothesis_result, HYPOTHESIS_RESULTS, f"{h_path}.result")
            recommendation = v.require(item, "recommendation", h_path, str)
            if isinstance(recommendation, str):
                v.enum(recommendation, {"promote-to-finding", "close", "residual-gap"}, f"{h_path}.recommendation")
            refs = v.require(item, "evidenceRefs", h_path, list)
            valid_refs = string_items(v, refs, f"{h_path}.evidenceRefs")
            if isinstance(refs, list) and not valid_refs:
                v.error(f"{h_path}.evidenceRefs", "must contain DIRECT evidence")
            for ref in valid_refs:
                if ref not in local_evidence:
                    v.error(f"{h_path}.evidenceRefs", f"unknown investigation evidence id {ref!r}")
            referenced_polarities = {
                v.evidence_polarity[ref]
                for ref in valid_refs
                if ref in local_evidence and ref in v.evidence_polarity
            }
            if hypothesis_result == "supported" and "supports" not in referenced_polarities:
                v.error(f"{h_path}.evidenceRefs", "supported hypothesis requires supporting DIRECT evidence")
            if hypothesis_result == "refuted" and "refutes" not in referenced_polarities:
                v.error(f"{h_path}.evidenceRefs", "refuted hypothesis requires refuting DIRECT evidence")
            if hypothesis_result == "supported" and recommendation != "promote-to-finding":
                v.error(f"{h_path}.recommendation", "supported hypothesis must be promoted to a Finding")
            if hypothesis_result == "refuted" and recommendation != "close":
                v.error(f"{h_path}.recommendation", "refuted hypothesis must be closed")
            if hypothesis_result == "unresolved" and recommendation not in {"promote-to-finding", "residual-gap"}:
                v.error(f"{h_path}.recommendation", "unresolved hypothesis must become a conditional Finding or residual gap")
            if disconfirmation_result == "counter-supported" and (
                hypothesis_result != "refuted" or recommendation != "close"
            ):
                v.error(f"{h_path}.disconfirmationResult", "counter-supported hypothesis must be closed or replaced by a newly narrowed hypothesis")
            if isinstance(hypothesis_id, str):
                v.hypothesis_evidence[hypothesis_id] = set(valid_refs)
                if isinstance(recommendation, str):
                    v.hypothesis_recommendations[hypothesis_id] = recommendation
        if isinstance(unit.get("id"), str):
            v.unit_hypotheses[unit["id"]] = local_hypotheses
    if isinstance(summary, dict):
        v.closed_object(summary, f"{label}.coverageSummary", {"checked", "verifiedBehaviors", "gaps"})
        for key in ("checked", "verifiedBehaviors", "gaps"):
            if key not in summary or not isinstance(summary[key], list):
                v.error(f"{label}.coverageSummary.{key}", "expected array")
            else:
                string_items(v, summary[key], f"{label}.coverageSummary.{key}")


def validate_verification(v: Validation, path: Path, finding_id: str) -> None:
    label = str(path.relative_to(v.root)).replace("\\", "/")
    data = load_json(path, v, label)
    if not isinstance(data, dict):
        if data is not None:
            v.error(label, "expected object")
        return
    v.closed_object(data, label, {"auditBinding", "findingId", "method", "checkedEvidence", "evidence", "challenge", "resolutionChallenge", "conclusion", "limits"})
    validate_artifact_binding(v, data, label)
    if data.get("findingId") != finding_id:
        v.error(f"{label}.findingId", f"must equal {finding_id}")
    method = v.require(data, "method", label, str)
    if isinstance(method, str):
        v.enum(method, METHODS, f"{label}.method")
        v.verification_method[finding_id] = method
    checked = v.require(data, "checkedEvidence", label, list)
    checked_items: list[str] = []
    if isinstance(checked, list):
        v.nonempty(checked, f"{label}.checkedEvidence")
        checked_items = string_items(v, checked, f"{label}.checkedEvidence")
        if len(set(checked_items)) != len(checked_items):
            v.error(f"{label}.checkedEvidence", "contains duplicate entries")
    for ref in checked_items:
        if ref not in v.investigation_evidence:
            v.error(f"{label}.checkedEvidence", f"unknown investigation evidence id {ref!r}")
    v.verification_checked[finding_id] = set(checked_items)
    evidence = v.require(data, "evidence", label, list)
    new_evidence: set[str] = set()
    if isinstance(evidence, list):
        v.nonempty(evidence, f"{label}.evidence")
        for index, item in enumerate(evidence):
            validate_evidence(v, item, f"{label}.evidence[{index}]", finding_id)
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                new_evidence.add(item["id"])
    v.verification_evidence[finding_id] = new_evidence
    challenge = data.get("challenge")
    if challenge is not None:
        if not isinstance(challenge, dict):
            v.error(f"{label}.challenge", "expected object")
        else:
            v.closed_object(challenge, f"{label}.challenge", {"status", "mode", "unitId", "method", "evidenceRefs", "result", "gapReason"})
            status = v.require(challenge, "status", f"{label}.challenge", str)
            if isinstance(status, str):
                v.enum(status, CHALLENGE_STATUS, f"{label}.challenge.status")
            if status == "COMPLETED":
                mode = v.require(challenge, "mode", f"{label}.challenge", str)
                challenge_method = v.require(challenge, "method", f"{label}.challenge", str)
                refs = v.require(challenge, "evidenceRefs", f"{label}.challenge", list)
                result = v.require(challenge, "result", f"{label}.challenge", str)
                if isinstance(mode, str):
                    v.enum(mode, CHALLENGE_MODES, f"{label}.challenge.mode")
                    if mode == "HETEROGENEOUS-METHOD":
                        unit_id = v.require(challenge, "unitId", f"{label}.challenge", str)
                        if isinstance(unit_id, str):
                            v.id(unit_id, "unit", f"{label}.challenge.unitId")
                    elif "unitId" in challenge:
                        v.error(f"{label}.challenge.unitId", "allowed only for HETEROGENEOUS-METHOD")
                if isinstance(challenge_method, str):
                    v.enum(challenge_method, METHODS, f"{label}.challenge.method")
                valid_refs = string_items(v, refs, f"{label}.challenge.evidenceRefs")
                if isinstance(refs, list):
                    v.nonempty(refs, f"{label}.challenge.evidenceRefs")
                    if len(set(valid_refs)) != len(valid_refs):
                        v.error(f"{label}.challenge.evidenceRefs", "contains duplicate entries")
                if isinstance(result, str):
                    v.enum(result, {"counter-supported", "counter-refuted"}, f"{label}.challenge.result")
                if "gapReason" in challenge:
                    v.error(f"{label}.challenge.gapReason", "must be omitted when status is COMPLETED")
            elif status == "GAP":
                gap_reason = v.require(challenge, "gapReason", f"{label}.challenge", str)
                if isinstance(gap_reason, str):
                    v.nonempty(gap_reason, f"{label}.challenge.gapReason")
                for key in ("mode", "unitId", "method", "evidenceRefs", "result"):
                    if key in challenge:
                        v.error(f"{label}.challenge.{key}", "must be omitted when status is GAP")
            v.verification_challenge[finding_id] = challenge
    resolution_challenge = data.get("resolutionChallenge")
    if resolution_challenge is not None:
        resolution_path = f"{label}.resolutionChallenge"
        if not isinstance(resolution_challenge, dict):
            v.error(resolution_path, "expected object")
        else:
            v.closed_object(resolution_challenge, resolution_path, {"status", "unitId", "method", "evidenceRefs", "result", "gapReason"})
            status = v.require(resolution_challenge, "status", resolution_path, str)
            if isinstance(status, str):
                v.enum(status, {"COMPLETED"}, f"{resolution_path}.status")
            if status == "COMPLETED":
                unit_id = v.require(resolution_challenge, "unitId", resolution_path, str)
                resolution_method = v.require(resolution_challenge, "method", resolution_path, str)
                refs = v.require(resolution_challenge, "evidenceRefs", resolution_path, list)
                result = v.require(resolution_challenge, "result", resolution_path, str)
                if isinstance(unit_id, str):
                    v.id(unit_id, "unit", f"{resolution_path}.unitId")
                if isinstance(resolution_method, str):
                    v.enum(resolution_method, METHODS, f"{resolution_path}.method")
                valid_refs = string_items(v, refs, f"{resolution_path}.evidenceRefs")
                if isinstance(refs, list):
                    v.nonempty(refs, f"{resolution_path}.evidenceRefs")
                    if len(set(valid_refs)) != len(valid_refs):
                        v.error(f"{resolution_path}.evidenceRefs", "contains duplicate entries")
                if isinstance(result, str):
                    v.enum(result, {"resolution-supported", "resolution-refuted"}, f"{resolution_path}.result")
                if "gapReason" in resolution_challenge:
                    v.error(f"{resolution_path}.gapReason", "must be omitted when status is COMPLETED")
            v.verification_resolution_challenge[finding_id] = resolution_challenge
    conclusion = v.require(data, "conclusion", label, str)
    if isinstance(conclusion, str):
        v.nonempty(conclusion, f"{label}.conclusion")
    limits = v.require(data, "limits", label, list)
    string_items(v, limits, f"{label}.limits")


def validate_fix_workflow(
    v: Validation,
    data: dict[str, Any],
    phase: Any,
    execution_mode: Any,
    finding_by_id: dict[str, dict[str, Any]],
    residual_by_id: dict[str, dict[str, Any]],
) -> None:
    """Validate the single-authority repair DAG stored inside state.json."""
    workflow = data.get("fixWorkflow")
    repair_state_exists = any(
        finding.get("disposition") in {"REMEDIATING", "RESOLVED-VERIFIED"}
        for finding in finding_by_id.values()
    )
    if execution_mode == "audit-and-fix" and repair_state_exists and not isinstance(workflow, dict):
        v.error("state.json.fixWorkflow", "required when audit-and-fix has REMEDIATING or RESOLVED-VERIFIED Findings")
        return
    if workflow is None:
        return
    if execution_mode != "audit-and-fix":
        v.error("state.json.fixWorkflow", "allowed only when executionMode=audit-and-fix")
    if not isinstance(workflow, dict):
        v.error("state.json.fixWorkflow", "expected object")
        return
    v.closed_object(workflow, "state.json.fixWorkflow", {"generation", "finalRegressionBatchId", "findingMappings", "batches"})
    if not repair_state_exists:
        v.error("state.json.fixWorkflow", "must be omitted until a Finding enters REMEDIATING or RESOLVED-VERIFIED")

    generation = v.require(workflow, "generation", "state.json.fixWorkflow", int)
    if isinstance(generation, int) and not isinstance(generation, bool) and generation < 1:
        v.error("state.json.fixWorkflow.generation", "must be a positive integer")
    final_id = v.require(workflow, "finalRegressionBatchId", "state.json.fixWorkflow", str)
    if isinstance(final_id, str):
        v.nonempty(final_id, "state.json.fixWorkflow.finalRegressionBatchId")
    mappings = v.require(workflow, "findingMappings", "state.json.fixWorkflow", list)
    mapped_findings: set[str] = set()
    if isinstance(mappings, list):
        v.nonempty(mappings, "state.json.fixWorkflow.findingMappings")
        for index, mapping in enumerate(mappings):
            path = f"state.json.fixWorkflow.findingMappings[{index}]"
            if not isinstance(mapping, dict):
                v.error(path, "expected object")
                continue
            v.closed_object(
                mapping,
                path,
                {"findingId", "rootCausePattern", "knownInstances", "fixScope", "exclusions", "behaviorChange", "acceptanceChecks", "preFixExpectedFailure", "regressionScope", "residualRiskIds"},
            )
            finding_id = v.require(mapping, "findingId", path, str)
            if isinstance(finding_id, str):
                if finding_id not in finding_by_id:
                    v.error(f"{path}.findingId", f"unknown Finding {finding_id!r}")
                if finding_id in mapped_findings:
                    v.error(f"{path}.findingId", f"duplicate mapping for Finding {finding_id!r}")
                mapped_findings.add(finding_id)
            for key in ("rootCausePattern", "fixScope", "behaviorChange", "preFixExpectedFailure", "regressionScope"):
                value = v.require(mapping, key, path, str)
                if isinstance(value, str):
                    v.nonempty(value, f"{path}.{key}")
            for key in ("knownInstances", "exclusions", "acceptanceChecks", "residualRiskIds"):
                values = v.require(mapping, key, path, list)
                valid_values = string_items(v, values, f"{path}.{key}")
                if key in {"knownInstances", "acceptanceChecks"} and isinstance(values, list):
                    v.nonempty(values, f"{path}.{key}")
                if len(set(valid_values)) != len(valid_values):
                    v.error(f"{path}.{key}", "contains duplicate entries")
                if key == "residualRiskIds":
                    for residual_id in valid_values:
                        if residual_id not in residual_by_id:
                            v.error(f"{path}.{key}", f"unknown residual risk {residual_id!r}")

    batches = v.require(workflow, "batches", "state.json.fixWorkflow", list)
    if not isinstance(batches, list):
        return
    v.nonempty(batches, "state.json.fixWorkflow.batches")

    batch_by_id: dict[str, dict[str, Any]] = {}
    batch_paths: dict[str, str] = {}
    for index, batch in enumerate(batches):
        path = f"state.json.fixWorkflow.batches[{index}]"
        if not isinstance(batch, dict):
            v.error(path, "expected object")
            continue
        v.closed_object(
            batch,
            path,
            {"id", "kind", "status", "attempt", "transitionReason", "scope", "allowedPaths", "acceptanceChecks", "dependsOn", "findingIds", "evidenceRefs", "validatedGeneration"},
        )
        batch_id = v.require(batch, "id", path, str)
        if isinstance(batch_id, str):
            if not AUDIT_ID_PATTERN.fullmatch(batch_id) or ".." in batch_id:
                v.error(f"{path}.id", "must be a filename-safe batch id")
            if batch_id in batch_by_id:
                v.error(f"{path}.id", f"duplicate batch id {batch_id!r}")
            batch_by_id[batch_id] = batch
            batch_paths[batch_id] = path
        kind = v.require(batch, "kind", path, str)
        status = v.require(batch, "status", path, str)
        if isinstance(kind, str):
            v.enum(kind, FIX_BATCH_KINDS, f"{path}.kind")
        if isinstance(status, str):
            v.enum(status, FIX_BATCH_STATUS, f"{path}.status")
        attempt = v.require(batch, "attempt", path, int)
        if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt < 1:
            v.error(f"{path}.attempt", "must be a positive integer")
        transition_reason = batch.get("transitionReason")
        if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 1:
            if not isinstance(transition_reason, str) or not transition_reason.strip():
                v.error(f"{path}.transitionReason", "attempt > 1 requires a non-empty retry/invalidation reason")
        elif transition_reason is not None:
            v.error(f"{path}.transitionReason", "allowed only when attempt > 1")
        scope = v.require(batch, "scope", path, str)
        if isinstance(scope, str):
            v.nonempty(scope, f"{path}.scope")
        allowed_paths = v.require(batch, "allowedPaths", path, list)
        valid_paths = string_items(v, allowed_paths, f"{path}.allowedPaths")
        if kind == "FIX" and isinstance(allowed_paths, list):
            v.nonempty(allowed_paths, f"{path}.allowedPaths")
        for path_index, allowed_path in enumerate(valid_paths):
            validate_allowed_path(v, allowed_path, f"{path}.allowedPaths[{path_index}]")
        if len(set(valid_paths)) != len(valid_paths):
            v.error(f"{path}.allowedPaths", "contains duplicate entries")
        acceptance_checks = v.require(batch, "acceptanceChecks", path, list)
        valid_checks = string_items(v, acceptance_checks, f"{path}.acceptanceChecks")
        if isinstance(acceptance_checks, list):
            v.nonempty(acceptance_checks, f"{path}.acceptanceChecks")
        if len(set(valid_checks)) != len(valid_checks):
            v.error(f"{path}.acceptanceChecks", "contains duplicate entries")
        depends = v.require(batch, "dependsOn", path, list)
        valid_depends = string_items(v, depends, f"{path}.dependsOn")
        if len(set(valid_depends)) != len(valid_depends):
            v.error(f"{path}.dependsOn", "contains duplicate entries")
        finding_ids = v.require(batch, "findingIds", path, list)
        valid_findings = string_items(v, finding_ids, f"{path}.findingIds")
        if kind in {"FIX", "VERIFY"} and isinstance(finding_ids, list):
            v.nonempty(finding_ids, f"{path}.findingIds")
        if len(set(valid_findings)) != len(valid_findings):
            v.error(f"{path}.findingIds", "contains duplicate entries")
        for finding_id in valid_findings:
            if finding_id not in finding_by_id:
                v.error(f"{path}.findingIds", f"unknown Finding {finding_id!r}")
            if kind in {"FIX", "VERIFY"} and finding_id not in mapped_findings:
                v.error(f"{path}.findingIds", f"Finding {finding_id!r} has no fixWorkflow findingMapping")
        evidence_refs = v.require(batch, "evidenceRefs", path, list)
        valid_refs = string_items(v, evidence_refs, f"{path}.evidenceRefs")
        if status == "PASSED" and isinstance(evidence_refs, list):
            v.nonempty(evidence_refs, f"{path}.evidenceRefs")
        for ref in valid_refs:
            if ref not in v.evidence:
                v.error(f"{path}.evidenceRefs", f"unknown Evidence {ref!r}")
        validated_generation = batch.get("validatedGeneration")
        if status == "PASSED":
            if validated_generation != generation:
                v.error(f"{path}.validatedGeneration", "PASSED batch must equal fixWorkflow.generation")
        elif validated_generation is not None:
            v.error(f"{path}.validatedGeneration", "allowed only when status=PASSED")

    for batch_id, batch in batch_by_id.items():
        path = batch_paths[batch_id]
        for dependency in string_items(v, batch.get("dependsOn"), f"{path}.dependsOn"):
            if dependency == batch_id:
                v.error(f"{path}.dependsOn", "batch cannot depend on itself")
            elif dependency not in batch_by_id:
                v.error(f"{path}.dependsOn", f"unknown batch {dependency!r}")
            elif batch.get("status") == "PASSED" and batch_by_id[dependency].get("status") != "PASSED":
                v.error(f"{path}.status", f"PASSED batch requires dependency {dependency!r} to be PASSED")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(batch_id: str) -> None:
        if batch_id in visiting:
            v.error("state.json.fixWorkflow.batches", f"dependency cycle detected at batch {batch_id!r}")
            return
        if batch_id in visited:
            return
        visiting.add(batch_id)
        for dependency in string_set(batch_by_id[batch_id].get("dependsOn")):
            if dependency in batch_by_id:
                visit(dependency)
        visiting.remove(batch_id)
        visited.add(batch_id)

    for batch_id in batch_by_id:
        visit(batch_id)

    final_batch = batch_by_id.get(final_id) if isinstance(final_id, str) else None
    if final_batch is None:
        v.error("state.json.fixWorkflow.finalRegressionBatchId", "must reference an existing batch")
    else:
        if final_batch.get("kind") != "REGRESSION":
            v.error("state.json.fixWorkflow.finalRegressionBatchId", "must reference a REGRESSION batch")
        if phase == "FINAL" and final_batch.get("status") != "PASSED":
            v.error("state.json.fixWorkflow.finalRegressionBatchId", "FINAL audit requires the final regression batch to be PASSED")

        ancestors: set[str] = set()
        pending = list(string_set(final_batch.get("dependsOn")))
        while pending:
            dependency = pending.pop()
            if dependency in ancestors or dependency not in batch_by_id:
                continue
            ancestors.add(dependency)
            pending.extend(string_set(batch_by_id[dependency].get("dependsOn")))
        for batch_id, batch in batch_by_id.items():
            if batch.get("status") == "PASSED" and batch.get("kind") in {"FIX", "VERIFY"} and batch_id not in ancestors:
                v.error(
                    "state.json.fixWorkflow.finalRegressionBatchId",
                    f"final regression must transitively depend on PASSED {batch.get('kind')} batch {batch_id!r}",
                )

    if phase == "FINAL":
        for batch_id, batch in batch_by_id.items():
            if batch.get("status") != "PASSED":
                v.error(f"{batch_paths[batch_id]}.status", "every batch must be PASSED in FINAL audit-and-fix state")
        for finding_id, finding in finding_by_id.items():
            if finding.get("disposition") == "REMEDIATING":
                v.error(f"state.json.findings[{finding_id}].disposition", "FINAL audit-and-fix cannot leave a Finding REMEDIATING")

    def finding_is_settled(finding: dict[str, Any]) -> bool:
        if finding.get("decision") == "REJECTED":
            return True
        if finding.get("disposition") in {"RESOLVED-VERIFIED", "ACCEPTED-RISK"}:
            return True
        gates = finding.get("gates")
        if not isinstance(gates, dict) or not gates:
            return False
        return all(
            isinstance(gate, dict)
            and (
                gate.get("applicability") == "DOES-NOT-APPLY"
                or (
                    gate.get("applicability") == "APPLIES"
                    and gate.get("treatment") == "ACCEPTED"
                )
            )
            for gate in gates.values()
        )

    for batch_id, batch in batch_by_id.items():
        if batch.get("kind") == "FIX" and batch.get("status") == "PASSED":
            for finding_id in string_set(batch.get("findingIds")):
                finding = finding_by_id.get(finding_id)
                if not isinstance(finding, dict):
                    continue
                if finding.get("disposition") != "REMEDIATING" and not finding_is_settled(finding):
                    v.error(
                        f"{batch_paths[batch_id]}.status",
                        f"PASSED FIX batch requires Finding {finding_id!r} to be remediating, resolved, rejected, or fully accepted",
                    )
        if batch.get("kind") != "VERIFY" or batch.get("status") != "PASSED":
            continue
        for finding_id in string_set(batch.get("findingIds")):
            finding = finding_by_id.get(finding_id)
            if isinstance(finding, dict) and not finding_is_settled(finding):
                v.error(
                    f"{batch_paths[batch_id]}.status",
                    f"PASSED VERIFY batch requires Finding {finding_id!r} to be resolved, rejected, or fully accepted",
                )
            if (
                isinstance(finding, dict)
                and finding.get("disposition") == "RESOLVED-VERIFIED"
                and not (
                    string_set(batch.get("evidenceRefs"))
                    & string_set(finding.get("resolutionEvidence"))
                )
            ):
                v.error(
                    f"{batch_paths[batch_id]}.evidenceRefs",
                    f"PASSED VERIFY batch for RESOLVED-VERIFIED Finding {finding_id!r} must cite its resolutionEvidence",
                )

    for finding_id, finding in finding_by_id.items():
        disposition = finding.get("disposition")
        if disposition not in {"REMEDIATING", "RESOLVED-VERIFIED"}:
            continue
        if finding_id not in mapped_findings:
            v.error(f"state.json.findings[{finding_id}]", f"{disposition} has no fixWorkflow findingMapping")
        if disposition == "REMEDIATING":
            matching_fix_batches = [
                batch
                for batch in batch_by_id.values()
                if batch.get("kind") == "FIX"
                and finding_id in string_set(batch.get("findingIds"))
            ]
            if not matching_fix_batches:
                v.error(
                    f"state.json.findings[{finding_id}]",
                    "REMEDIATING must be assigned to a FIX batch",
                )
            continue
        resolution_refs = string_set(finding.get("resolutionEvidence"))
        matching_batches = [
            batch
            for batch in batch_by_id.values()
            if batch.get("kind") == "VERIFY"
            and batch.get("status") == "PASSED"
            and finding_id in string_set(batch.get("findingIds"))
            and resolution_refs.intersection(string_set(batch.get("evidenceRefs")))
        ]
        if not matching_batches:
            v.error(
                f"state.json.findings[{finding_id}].resolutionEvidence",
                "RESOLVED-VERIFIED must map to a PASSED VERIFY batch that cites resolutionEvidence",
            )


def validate_live_layout(
    v: Validation,
    root: Path,
    phase: str | None,
    investigation_paths: Iterable[Path],
    verification_paths: Iterable[Path],
) -> None:
    """Enforce the documented flat state-directory allowlist."""
    expected = {
        "investigations": {path.resolve() for path in investigation_paths},
        "verification": {path.resolve() for path in verification_paths},
    }
    allowed_entries = {"state.json", "report.md", "fix-map.md", "investigations", "verification", "probes"}
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        v.error(".", f"cannot inspect state directory layout: {exc}")
        return
    for entry in entries:
        if entry.name not in allowed_entries:
            v.error(entry.name, "unsupported state-directory entry; use state.json metadata or an approved probe")
            continue
        if is_link_like(entry):
            v.error(entry.name, "state-directory entries must not be symlinks or junctions")
        elif entry.name == "state.json" and not entry.is_file():
            v.error(entry.name, "must be a regular file")
        elif entry.name in {"report.md", "fix-map.md"} and not entry.is_file():
            v.error(entry.name, "must be a regular derived-output file")
        elif entry.name in {"investigations", "verification", "probes"} and not entry.is_dir():
            v.error(entry.name, "must be a directory")
    for directory_name, paths in expected.items():
        directory = root / directory_name
        if not directory.exists():
            if paths:
                v.error(directory_name, "missing directory for state-referenced artifacts")
            continue
        if not directory.is_dir():
            continue
        try:
            children = list(directory.iterdir())
        except OSError as exc:
            v.error(directory_name, f"cannot inspect artifact directory: {exc}")
            continue
        for child in children:
            if is_link_like(child) or not child.is_file() or child.suffix != ".json":
                v.error(str(child.relative_to(root)).replace("\\", "/"), "artifact directories may contain only flat referenced .json files")
            elif child.resolve() not in paths:
                v.error(str(child.relative_to(root)).replace("\\", "/"), "artifact is not referenced by state.json")
    probes = root / "probes"
    if phase == "FINAL" and probes.is_dir():
        try:
            if any(probes.iterdir()):
                v.error("probes", "FINAL audit must clean temporary probes")
        except OSError as exc:
            v.error("probes", f"cannot inspect temporary probes: {exc}")


def validate_state(state_path: Path) -> Validation:
    root = state_path.parent
    v = Validation(root)
    if is_link_like(root):
        v.error(str(root), "audit state directory must not be a symlink or junction")
        return v
    if is_link_like(state_path):
        v.error(state_path.name, "state.json must not be a symlink or junction")
        return v
    data = load_json(state_path, v, state_path.name)
    if not isinstance(data, dict):
        if data is not None:
            v.error(state_path.name, "expected object")
        return v

    v.closed_object(
        data,
        "state.json",
        {"schemaVersion", "phase", "audit", "sharedFacts", "claims", "verificationUnits", "findings", "residualRisks", "fixWorkflow", "exploration"},
    )

    if data.get("schemaVersion") != SCHEMA_VERSION:
        v.error("state.json.schemaVersion", f"must equal {SCHEMA_VERSION}")
    phase = v.require(data, "phase", "state.json", str)
    if isinstance(phase, str):
        v.enum(phase, PHASES, "state.json.phase")
    audit = v.require(data, "audit", "state.json", dict)
    shared_facts = v.require(data, "sharedFacts", "state.json", list)
    claims = v.require(data, "claims", "state.json", list)
    units = v.require(data, "verificationUnits", "state.json", list)
    findings = v.require(data, "findings", "state.json", list)
    residual = v.require(data, "residualRisks", "state.json", list)
    if not all(isinstance(value, expected) for value, expected in ((audit, dict), (shared_facts, list), (claims, list), (units, list), (findings, list), (residual, list))):
        return v

    for forbidden_name in ("audit.md", "project-map.md", "coverage.md", "ledger.md"):
        if (root / forbidden_name).exists():
            v.error(forbidden_name, "forbidden parallel live state; state.json is authoritative")
    temporary_states = sorted(path.name for path in root.glob("state.json.*") if path.is_file())
    if temporary_states:
        v.error("state.json", f"unfinished temporary state files remain: {temporary_states}")
    probes = root / "probes"
    if phase == "FINAL" and probes.is_dir():
        try:
            if any(probes.iterdir()):
                v.error("probes", "FINAL audit must clean temporary probes")
        except OSError as exc:
            v.error("probes", f"cannot inspect temporary probes: {exc}")

    requested_gates: set[str] = set()
    gate_decisions: dict[str, Any] = {}
    gate_policies: dict[str, dict[str, Any]] = {}
    exhaustive_coverage_incomplete = False
    exhaustive_coverage_residual_ref: str | None = None
    if isinstance(audit, dict):
        v.closed_object(
            audit,
            "state.json.audit",
            {
                "id", "target", "scope", "objectives", "availableEvidence", "deliverable",
                "scopeMode", "objectiveProfiles", "executionMode", "scopeResolution",
                "startedAt", "updatedAt", "snapshot", "supersedesAuditId", "supersession",
                "gates", "independentValidationRequiredFor", "stop", "scopeCoverage", "riskTolerance",
            },
        )
        for key in ("id", "target", "scope", "deliverable", "startedAt", "updatedAt"):
            value = v.require(audit, key, "state.json.audit", str)
            if isinstance(value, str):
                v.nonempty(value, f"state.json.audit.{key}")
        audit_id = audit.get("id")
        if isinstance(audit_id, str):
            v.audit_id = audit_id
        snapshot = audit.get("snapshot")
        if snapshot is None or isinstance(snapshot, dict):
            v.snapshot = snapshot
        if isinstance(audit_id, str) and (
            not AUDIT_ID_PATTERN.fullmatch(audit_id) or ".." in audit_id
        ):
            v.error("state.json.audit.id", "must be a filename-safe id using letters, digits, '-' or '_'")
        validate_snapshot(v, audit)
        if phase == "FINAL" and audit.get("snapshot") is None:
            v.error("state.json.audit.snapshot", "required in FINAL state to bind conclusions to an immutable identity")
        supersedes = audit.get("supersedesAuditId")
        if supersedes is not None:
            if not isinstance(supersedes, str) or not AUDIT_ID_PATTERN.fullmatch(supersedes) or ".." in supersedes:
                v.error("state.json.audit.supersedesAuditId", "expected filename-safe audit id")
            elif supersedes == audit_id:
                v.error("state.json.audit.supersedesAuditId", "cannot reference the same audit id")
        supersession = audit.get("supersession")
        if phase == "SUPERSEDED":
            if not isinstance(supersession, dict):
                v.error("state.json.audit.supersession", "required object while phase is SUPERSEDED")
            else:
                v.closed_object(supersession, "state.json.audit.supersession", {"byAuditId", "reason", "at"})
                by_id = v.require(supersession, "byAuditId", "state.json.audit.supersession", str)
                reason = v.require(supersession, "reason", "state.json.audit.supersession", str)
                at = v.require(supersession, "at", "state.json.audit.supersession", str)
                if isinstance(by_id, str):
                    if not AUDIT_ID_PATTERN.fullmatch(by_id) or ".." in by_id:
                        v.error("state.json.audit.supersession.byAuditId", "expected filename-safe audit id")
                    elif by_id == audit_id:
                        v.error("state.json.audit.supersession.byAuditId", "cannot reference the same audit id")
                for key, value in (("reason", reason), ("at", at)):
                    if isinstance(value, str):
                        v.nonempty(value, f"state.json.audit.supersession.{key}")
        elif supersession is not None:
            v.error("state.json.audit.supersession", "allowed only while phase is SUPERSEDED")
        objectives = v.require(audit, "objectives", "state.json.audit", list)
        if isinstance(objectives, list):
            v.nonempty(objectives, "state.json.audit.objectives")
        string_items(v, objectives, "state.json.audit.objectives")
        available = audit.get("availableEvidence")
        if available is not None:
            if not isinstance(available, list):
                v.error("state.json.audit.availableEvidence", "expected array")
            else:
                string_items(v, available, "state.json.audit.availableEvidence")
        scope_mode = v.require(audit, "scopeMode", "state.json.audit", str)
        if isinstance(scope_mode, str):
            v.enum(scope_mode, SCOPE_MODES, "state.json.audit.scopeMode")
        profiles = v.require(audit, "objectiveProfiles", "state.json.audit", list)
        if isinstance(profiles, list):
            v.nonempty(profiles, "state.json.audit.objectiveProfiles")
            profile_items = string_items(v, profiles, "state.json.audit.objectiveProfiles")
            for index, value in enumerate(profile_items):
                v.enum(value, OBJECTIVE_PROFILES, f"state.json.audit.objectiveProfiles[{index}]")
            if "general" not in profile_items:
                v.error("state.json.audit.objectiveProfiles", "must include the default profile 'general'")
            if len(set(profile_items)) != len(profile_items):
                v.error("state.json.audit.objectiveProfiles", "contains duplicates")
        execution = v.require(audit, "executionMode", "state.json.audit", str)
        if isinstance(execution, str):
            v.enum(execution, EXECUTION_MODES, "state.json.audit.executionMode")
        scope_resolution = v.require(audit, "scopeResolution", "state.json.audit", dict)
        if isinstance(scope_resolution, dict):
            v.closed_object(scope_resolution, "state.json.audit.scopeResolution", {"basis", "confidence", "assumption"})
            basis = v.require(scope_resolution, "basis", "state.json.audit.scopeResolution", str)
            confidence = v.require(scope_resolution, "confidence", "state.json.audit.scopeResolution", str)
            if isinstance(basis, str):
                v.enum(basis, SCOPE_BASIS, "state.json.audit.scopeResolution.basis")
            if isinstance(confidence, str):
                v.enum(confidence, SCOPE_CONFIDENCE, "state.json.audit.scopeResolution.confidence")
            if basis == "ASSUMED" and not scope_resolution.get("assumption"):
                v.error("state.json.audit.scopeResolution.assumption", "required when basis is ASSUMED")
            if basis != "ASSUMED" and "assumption" in scope_resolution:
                v.error("state.json.audit.scopeResolution.assumption", "allowed only when basis is ASSUMED")
        gates = audit.get("gates")
        if gates is not None:
            if not isinstance(gates, dict):
                v.error("state.json.audit.gates", "expected object")
            else:
                v.closed_object(gates, "state.json.audit.gates", {"targets", "decisions", "policies"})
                targets = v.require(gates, "targets", "state.json.audit.gates", list)
                if isinstance(targets, list):
                    v.nonempty(targets, "state.json.audit.gates.targets")
                    for index, target in enumerate(string_items(v, targets, "state.json.audit.gates.targets")):
                        v.enum(target, GATE_TARGETS, f"state.json.audit.gates.targets[{index}]")
                        if target in GATE_TARGETS:
                            requested_gates.add(target)
                    if len(requested_gates) != len(targets):
                        v.error("state.json.audit.gates.targets", "contains duplicates")
                decisions = gates.get("decisions", {})
                if not isinstance(decisions, dict):
                    v.error("state.json.audit.gates.decisions", "expected object")
                else:
                    gate_decisions = decisions
                    if phase in {"ACTIVE", "SUPERSEDED"} and "decisions" in gates:
                        v.error("state.json.audit.gates.decisions", f"must be omitted while phase is {phase}")
                    for target, decision in decisions.items():
                        if target not in requested_gates:
                            v.error(f"state.json.audit.gates.decisions.{target}", "target was not requested")
                        if not isinstance(decision, dict):
                            v.error(f"state.json.audit.gates.decisions.{target}", "expected object")
                            continue
                        v.closed_object(decision, f"state.json.audit.gates.decisions.{target}", {"result", "basis"})
                        result = v.require(decision, "result", f"state.json.audit.gates.decisions.{target}", str)
                        if isinstance(result, str):
                            v.enum(result, GATE_RESULTS, f"state.json.audit.gates.decisions.{target}.result")
                        basis = v.require(decision, "basis", f"state.json.audit.gates.decisions.{target}", list)
                        if isinstance(basis, list):
                            v.nonempty(basis, f"state.json.audit.gates.decisions.{target}.basis")
                            string_basis = string_items(v, basis, f"state.json.audit.gates.decisions.{target}.basis")
                            if len(set(string_basis)) != len(string_basis):
                                v.error(f"state.json.audit.gates.decisions.{target}.basis", "contains duplicate entries")
                policies = gates.get("policies", {})
                if not isinstance(policies, dict):
                    v.error("state.json.audit.gates.policies", "expected object")
                else:
                    for target, policy in policies.items():
                        p_path = f"state.json.audit.gates.policies.{target}"
                        if target not in requested_gates:
                            v.error(p_path, "target was not requested")
                        if not isinstance(policy, dict):
                            v.error(p_path, "expected object")
                            continue
                        v.closed_object(policy, p_path, {"blockAtOrAbove"})
                        unknown = set(policy) - {"blockAtOrAbove"}
                        if unknown:
                            v.error(p_path, f"unsupported policy keys: {sorted(unknown)}")
                        threshold = v.require(policy, "blockAtOrAbove", p_path, str)
                        if isinstance(threshold, str):
                            v.enum(threshold, {"Medium", "Low"}, f"{p_path}.blockAtOrAbove")
                        if threshold in {"Medium", "Low"}:
                            gate_policies[target] = {"blockAtOrAbove": threshold}
        if "riskTolerance" in audit:
            v.error("state.json.audit.riskTolerance", "free-form riskTolerance is unsupported; use Gate blockAtOrAbove or explicit Finding acceptance")
        independent = audit.get("independentValidationRequiredFor")
        if independent is not None:
            if not isinstance(independent, list) or not independent:
                v.error("state.json.audit.independentValidationRequiredFor", "must be a non-empty array when present")
            else:
                allowed = requested_gates | {"AUDIT"}
                valid_independent = string_items(v, independent, "state.json.audit.independentValidationRequiredFor")
                for index, value in enumerate(valid_independent):
                    v.enum(value, allowed, f"state.json.audit.independentValidationRequiredFor[{index}]")
                if len(set(valid_independent)) != len(valid_independent):
                    v.error("state.json.audit.independentValidationRequiredFor", "contains duplicates")
                if "AUDIT" in valid_independent and len(valid_independent) != 1:
                    v.error("state.json.audit.independentValidationRequiredFor", "AUDIT cannot be combined with Gate targets")
        stop = audit.get("stop")
        if stop is not None:
            if not isinstance(stop, dict):
                v.error("state.json.audit.stop", "expected object")
            else:
                v.closed_object(stop, "state.json.audit.stop", {"policy", "criteria", "reason"})
                policy = v.require(stop, "policy", "state.json.audit.stop", str)
                if isinstance(policy, str):
                    v.enum(policy, {"exhaustive", "user-defined"}, "state.json.audit.stop.policy")
                if policy == "user-defined" and not stop.get("criteria"):
                    v.error("state.json.audit.stop.criteria", "required and non-empty for user-defined policy")
                if "reason" in stop:
                    reason = v.require(stop, "reason", "state.json.audit.stop", str)
                    if isinstance(reason, str):
                        v.nonempty(reason, "state.json.audit.stop.reason")
                scope_coverage = audit.get("scopeCoverage")
                if policy == "exhaustive":
                    coverage_path = "state.json.audit.scopeCoverage"
                    if not isinstance(scope_coverage, dict):
                        v.error(coverage_path, "required object when stop.policy=exhaustive")
                    else:
                        v.closed_object(
                            scope_coverage,
                            coverage_path,
                            {"snapshot", "declaredMembers", "completedMembers", "excludedMembers", "residualRiskId"},
                        )
                        if "snapshot" not in scope_coverage:
                            v.error(coverage_path, "missing required key 'snapshot'")
                        elif scope_coverage["snapshot"] != audit.get("snapshot"):
                            v.error(f"{coverage_path}.snapshot", "must exactly equal the current audit snapshot")
                        declared_raw = v.require(scope_coverage, "declaredMembers", coverage_path, list)
                        completed_raw = v.require(scope_coverage, "completedMembers", coverage_path, list)
                        excluded_raw = v.require(scope_coverage, "excludedMembers", coverage_path, list)
                        declared = string_items(v, declared_raw, f"{coverage_path}.declaredMembers")
                        completed = string_items(v, completed_raw, f"{coverage_path}.completedMembers")
                        if isinstance(declared_raw, list):
                            v.nonempty(declared_raw, f"{coverage_path}.declaredMembers")
                        if len(set(declared)) != len(declared):
                            v.error(f"{coverage_path}.declaredMembers", "contains duplicate entries")
                        if len(set(completed)) != len(completed):
                            v.error(f"{coverage_path}.completedMembers", "contains duplicate entries")
                        declared_set = set(declared)
                        completed_set = set(completed)
                        for member in completed_set - declared_set:
                            v.error(f"{coverage_path}.completedMembers", f"unknown declared member {member!r}")
                        excluded_members: set[str] = set()
                        if isinstance(excluded_raw, list):
                            for index, exclusion in enumerate(excluded_raw):
                                exclusion_path = f"{coverage_path}.excludedMembers[{index}]"
                                if not isinstance(exclusion, dict):
                                    v.error(exclusion_path, "expected object")
                                    continue
                                v.closed_object(exclusion, exclusion_path, {"member", "reason"})
                                member = v.require(exclusion, "member", exclusion_path, str)
                                reason = v.require(exclusion, "reason", exclusion_path, str)
                                if isinstance(member, str):
                                    v.nonempty(member, f"{exclusion_path}.member")
                                    if member not in declared_set:
                                        v.error(f"{exclusion_path}.member", f"unknown declared member {member!r}")
                                    if member in excluded_members:
                                        v.error(f"{exclusion_path}.member", f"duplicate excluded member {member!r}")
                                    excluded_members.add(member)
                                if isinstance(reason, str):
                                    v.nonempty(reason, f"{exclusion_path}.reason")
                        overlap = completed_set & excluded_members
                        if overlap:
                            v.error(coverage_path, f"members cannot be both completed and excluded: {sorted(overlap)}")
                        unresolved = declared_set - completed_set - excluded_members
                        exhaustive_coverage_incomplete = bool(unresolved) or not completed_set
                        residual_ref = scope_coverage.get("residualRiskId")
                        if exhaustive_coverage_incomplete and phase == "FINAL":
                            if not isinstance(residual_ref, str):
                                v.error(
                                    f"{coverage_path}.residualRiskId",
                                    "FINAL incomplete exhaustive coverage requires a material residual risk",
                                )
                            else:
                                v.id(residual_ref, "residual", f"{coverage_path}.residualRiskId")
                                exhaustive_coverage_residual_ref = residual_ref
                        elif residual_ref is not None:
                            v.error(
                                f"{coverage_path}.residualRiskId",
                                "allowed only for incomplete exhaustive coverage",
                            )
                elif scope_coverage is not None:
                    v.error("state.json.audit.scopeCoverage", "allowed only when stop.policy=exhaustive")
        elif "scopeCoverage" in audit:
            v.error("state.json.audit.scopeCoverage", "allowed only when stop.policy=exhaustive")

    fact_ids: set[str] = set()
    for index, item in enumerate(shared_facts):
        path = f"state.json.sharedFacts[{index}]"
        if not isinstance(item, dict):
            v.error(path, "expected object")
            continue
        v.closed_object(item, path, {"id", "fact", "source"})
        fact_id = v.require(item, "id", path, str)
        if isinstance(fact_id, str):
            v.id(fact_id, "fact", f"{path}.id")
            if fact_id in fact_ids:
                v.error(f"{path}.id", f"duplicate fact id {fact_id}")
            fact_ids.add(fact_id)
        for key in ("fact", "source"):
            value = v.require(item, key, path, str)
            if isinstance(value, str):
                v.nonempty(value, f"{path}.{key}")

    claim_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(claims):
        path = f"state.json.claims[{index}]"
        if not isinstance(item, dict):
            v.error(path, "expected object")
            continue
        v.closed_object(
            item,
            path,
            {"id", "riskArea", "statement", "consequence", "scope", "obligation", "priority", "explorationRound", "gateTargets", "discrimination", "sufficiency"},
        )
        claim_id = v.require(item, "id", path, str)
        if isinstance(claim_id, str):
            v.id(claim_id, "claim", f"{path}.id")
            if claim_id in claim_by_id:
                v.error(f"{path}.id", f"duplicate claim id {claim_id}")
            claim_by_id[claim_id] = item
        for key in ("riskArea", "statement", "consequence", "scope"):
            value = v.require(item, key, path, str)
            if isinstance(value, str):
                v.nonempty(value, f"{path}.{key}")
        obligation = v.require(item, "obligation", path, str)
        priority = v.require(item, "priority", path, str)
        if isinstance(obligation, str):
            v.enum(obligation, OBLIGATIONS, f"{path}.obligation")
        if isinstance(priority, str):
            v.enum(priority, PRIORITIES, f"{path}.priority")
        round_id = item.get("explorationRound")
        if obligation == "EXPLORATORY":
            if not isinstance(round_id, str) or not re.fullmatch(r"X[1-9][0-9]*", round_id):
                v.error(f"{path}.explorationRound", "EXPLORATORY claim requires X<n>")
        elif round_id is not None:
            v.error(f"{path}.explorationRound", "only EXPLORATORY claims may set this field")
        claim_gates = item.get("gateTargets")
        if claim_gates is not None:
            if obligation == "EXPLORATORY":
                v.error(f"{path}.gateTargets", "EXPLORATORY claims cannot carry Gate completion obligations; create a REQUIRED claim")
            if not requested_gates:
                v.error(f"{path}.gateTargets", "must be omitted when no Gate was requested")
            elif not isinstance(claim_gates, list):
                v.error(f"{path}.gateTargets", "expected array")
            else:
                v.nonempty(claim_gates, f"{path}.gateTargets")
                valid_targets = string_items(v, claim_gates, f"{path}.gateTargets")
                if len(set(valid_targets)) != len(valid_targets):
                    v.error(f"{path}.gateTargets", "contains duplicate entries")
                for target in valid_targets:
                    if target not in requested_gates:
                        v.error(f"{path}.gateTargets", f"unknown or unrequested Gate target {target!r}")
        discrimination = item.get("discrimination")
        required_plan = ()
        if priority == "highest":
            required_plan = ("safePrediction", "failurePrediction", "discriminatingObservation", "sufficiencyCriterion")
        elif priority == "high":
            required_plan = ("discriminatingObservation", "sufficiencyCriterion")
        if required_plan:
            if not isinstance(discrimination, dict):
                v.error(f"{path}.discrimination", f"required for priority={priority}")
            else:
                v.closed_object(discrimination, f"{path}.discrimination", {"safePrediction", "failurePrediction", "discriminatingObservation", "sufficiencyCriterion"})
                for key in required_plan:
                    value = v.require(discrimination, key, f"{path}.discrimination", str)
                    if isinstance(value, str):
                        v.nonempty(value, f"{path}.discrimination.{key}")
            sufficiency = item.get("sufficiency")
            if phase == "FINAL" and sufficiency is None:
                v.error(f"{path}.sufficiency", "required in FINAL state for highest/high claim")
            elif sufficiency is not None:
                v.enum(sufficiency, {"MET", "NOT-MET"}, f"{path}.sufficiency")
        elif "sufficiency" in item:
            v.error(f"{path}.sufficiency", "normal claim must omit sufficiency")

    unit_by_id: dict[str, dict[str, Any]] = {}
    units_by_claim: dict[str, list[dict[str, Any]]] = {}
    investigation_paths: dict[str, Path] = {}
    terminal_unit_residuals: list[tuple[str, str]] = []
    for index, item in enumerate(units):
        path = f"state.json.verificationUnits[{index}]"
        if not isinstance(item, dict):
            v.error(path, "expected object")
            continue
        v.closed_object(
            item,
            path,
            {"id", "claimId", "method", "status", "executor", "isolation", "reconciliations", "residualRiskId", "investigationFile"},
        )
        unit_id = v.require(item, "id", path, str)
        if isinstance(unit_id, str):
            v.id(unit_id, "unit", f"{path}.id")
            if unit_id in unit_by_id:
                v.error(f"{path}.id", f"duplicate unit id {unit_id}")
            unit_by_id[unit_id] = item
        claim_id = v.require(item, "claimId", path, str)
        if isinstance(claim_id, str):
            if claim_id not in claim_by_id:
                v.error(f"{path}.claimId", f"unknown claim id {claim_id}")
            units_by_claim.setdefault(claim_id, []).append(item)
        method = v.require(item, "method", path, str)
        if isinstance(method, str):
            v.enum(method, METHODS, f"{path}.method")
        status = v.require(item, "status", path, str)
        if isinstance(status, str):
            v.enum(status, UNIT_STATUS, f"{path}.status")
        if status in {"dispatched", "reported", "verified"}:
            executor = v.require(item, "executor", path, str)
            if isinstance(executor, str):
                v.nonempty(executor, f"{path}.executor")
        isolation = item.get("isolation")
        if isolation is not None:
            v.enum(isolation, ISOLATION, f"{path}.isolation")
        if status == "verified":
            reconciliations = v.require(item, "reconciliations", path, list)
            if isinstance(reconciliations, list):
                for r_index, rec in enumerate(reconciliations):
                    r_path = f"{path}.reconciliations[{r_index}]"
                    if not isinstance(rec, dict):
                        v.error(r_path, "expected object")
                        continue
                    v.closed_object(rec, r_path, {"hypothesisId", "result", "evidenceRefs", "findingId", "residualRiskId"})
                    hypothesis_id = v.require(rec, "hypothesisId", r_path, str)
                    if isinstance(hypothesis_id, str):
                        v.nonempty(hypothesis_id, f"{r_path}.hypothesisId")
                    result = v.require(rec, "result", r_path, str)
                    if isinstance(result, str):
                        v.enum(result, RECONCILIATION_RESULTS, f"{r_path}.result")
                    refs = v.require(rec, "evidenceRefs", r_path, list)
                    valid_refs = string_items(v, refs, f"{r_path}.evidenceRefs")
                    if result == "FINDING":
                        finding_ref = v.require(rec, "findingId", r_path, str)
                        if isinstance(finding_ref, str):
                            v.nonempty(finding_ref, f"{r_path}.findingId")
                    if result != "FINDING" and rec.get("findingId") is not None:
                        v.error(f"{r_path}.findingId", "allowed only when result is FINDING")
                    if result == "RESIDUAL-GAP":
                        residual_ref = v.require(rec, "residualRiskId", r_path, str)
                        if isinstance(residual_ref, str):
                            v.nonempty(residual_ref, f"{r_path}.residualRiskId")
                    elif rec.get("residualRiskId") is not None:
                        v.error(f"{r_path}.residualRiskId", "allowed only when result is RESIDUAL-GAP")
                    if isinstance(refs, list) and not valid_refs:
                        v.error(f"{r_path}.evidenceRefs", "must contain DIRECT evidence")
        elif "reconciliations" in item:
            v.error(path, "reconciliations are allowed only when status=verified")
        residual_ref = item.get("residualRiskId")
        if residual_ref is not None:
            if not isinstance(residual_ref, str):
                v.error(f"{path}.residualRiskId", "expected str")
            else:
                v.id(residual_ref, "residual", f"{path}.residualRiskId")
                terminal_unit_residuals.append((f"{path}.residualRiskId", residual_ref))
            if status == "verified":
                v.error(f"{path}.residualRiskId", "must be omitted when status=verified")
        claim = claim_by_id.get(claim_id) if isinstance(claim_id, str) else None
        if (
            phase == "FINAL"
            and isinstance(claim, dict)
            and claim.get("obligation") == "REQUIRED"
            and status != "verified"
            and residual_ref is None
        ):
            v.error(f"{path}.residualRiskId", "FINAL unfinished REQUIRED Unit must map to a material residual risk")
        if "sufficiency" in item:
            v.error(f"{path}.sufficiency", "belongs to the Claim, not the Verification Unit")
        investigation = item.get("investigationFile")
        if status in {"reported", "verified"}:
            file_path = v.safe_json_path(investigation, f"{path}.investigationFile", "investigations")
            if file_path is not None and isinstance(unit_id, str):
                investigation_paths[unit_id] = file_path
        elif investigation is not None:
            v.error(f"{path}.investigationFile", "allowed only after an investigation has reported")

    for index, item in enumerate(units):
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"] in investigation_paths:
            validate_investigation(v, investigation_paths[item["id"]], item, index)

    for unit_id, item in unit_by_id.items():
        if item.get("status") != "verified" or item.get("method") != "test-discrimination":
            continue
        evidence_ids = v.unit_evidence.get(unit_id, set())
        if not any(v.test_discrimination_results.get(evidence_id) == "YES" for evidence_id in evidence_ids):
            v.error(
                f"state.json.verificationUnits[{unit_id}]",
                "verified test-discrimination Unit requires at least one Evidence with testDiscrimination.result=YES",
            )

    # A Claim-level MET is an aggregate evidence assertion, not a free-form flag.
    # NOT-MET remains legal so an audit can finish with an explicit limitation.
    for claim_id, claim in claim_by_id.items():
        claim_units = units_by_claim.get(claim_id, [])
        if phase == "FINAL" and claim.get("obligation") == "REQUIRED" and not claim_units:
            v.error(f"state.json.claims[{claim_id}]", "FINAL REQUIRED Claim requires at least one Verification Unit")
        if phase != "FINAL" or claim.get("sufficiency") != "MET":
            continue
        verified_units = [unit for unit in claim_units if unit.get("status") == "verified"]
        path = f"state.json.claims[{claim_id}].sufficiency"
        if not claim_units:
            v.error(path, "MET requires at least one materialized Verification Unit")
        if not verified_units:
            v.error(path, "MET requires at least one verified Verification Unit")
        if claim.get("obligation") == "REQUIRED" and any(unit.get("status") != "verified" for unit in claim_units):
            v.error(path, "MET requires every Unit inherited by a REQUIRED Claim to be verified")
        evidence_refs = {
            evidence_id
            for unit in verified_units
            for evidence_id in (
                v.unit_evidence.get(unit["id"], set())
                if isinstance(unit.get("id"), str)
                else set()
            )
        }
        if not evidence_refs:
            v.error(path, "MET requires DIRECT Evidence from a verified Verification Unit")
        if claim.get("priority") == "highest" and len(
            {unit["method"] for unit in verified_units if isinstance(unit.get("method"), str)}
        ) < 2:
            v.error(path, "MET for a highest Claim requires two verified heterogeneous methods")

    finding_by_id: dict[str, dict[str, Any]] = {}
    verification_paths: dict[str, Path] = {}
    finding_gate_records: list[tuple[str, str, str | None, set[str]]] = []
    for index, item in enumerate(findings):
        path = f"state.json.findings[{index}]"
        if not isinstance(item, dict):
            v.error(path, "expected object")
            continue
        v.closed_object(
            item,
            path,
            {
                "id", "statement", "causeImpact", "conditions", "locations", "sourceHypotheses", "supportingEvidence", "refutingEvidence",
                "resolutionEvidence", "provenanceEvidence", "decision", "verificationMethod", "patternScope", "disconfirmation", "risk",
                "severity", "severityRationale", "confidence", "disposition", "riskAcceptanceAuthorization", "provenance", "gates", "verificationFile", "exitCriteria",
                "decisionHistory",
            },
        )
        finding_id = v.require(item, "id", path, str)
        if isinstance(finding_id, str):
            v.id(finding_id, "finding", f"{path}.id")
            if finding_id in finding_by_id:
                v.error(f"{path}.id", f"duplicate finding id {finding_id}")
            finding_by_id[finding_id] = item
        for key in ("statement", "causeImpact", "conditions", "verificationMethod", "exitCriteria"):
            value = v.require(item, key, path, str)
            if isinstance(value, str):
                v.nonempty(value, f"{path}.{key}")
        locations = v.require(item, "locations", path, list)
        source_h = v.require(item, "sourceHypotheses", path, list)
        supporting = v.require(item, "supportingEvidence", path, list)
        refuting = v.require(item, "refutingEvidence", path, list)
        if isinstance(locations, list):
            v.nonempty(locations, f"{path}.locations")
            string_items(v, locations, f"{path}.locations")
        if isinstance(source_h, list):
            v.nonempty(source_h, f"{path}.sourceHypotheses")
            source_items = string_items(v, source_h, f"{path}.sourceHypotheses")
            if len(set(source_items)) != len(source_items):
                v.error(f"{path}.sourceHypotheses", "contains duplicate entries")
        if isinstance(supporting, list):
            v.nonempty(supporting, f"{path}.supportingEvidence")
            string_items(v, supporting, f"{path}.supportingEvidence")
        string_items(v, refuting, f"{path}.refutingEvidence")
        for key in ("resolutionEvidence", "provenanceEvidence"):
            if key in item:
                if not isinstance(item[key], list):
                    v.error(f"{path}.{key}", "expected array")
                else:
                    string_items(v, item[key], f"{path}.{key}")
        decision_history = item.get("decisionHistory")
        if decision_history is not None:
            if not isinstance(decision_history, list):
                v.error(f"{path}.decisionHistory", "expected array")
            else:
                for history_index, entry in enumerate(decision_history):
                    entry_path = f"{path}.decisionHistory[{history_index}]"
                    if not isinstance(entry, dict):
                        v.error(entry_path, "expected object")
                        continue
                    v.closed_object(entry, entry_path, {"at", "summary", "evidenceRefs"})
                    for key in ("at", "summary"):
                        value = v.require(entry, key, entry_path, str)
                        if isinstance(value, str):
                            v.nonempty(value, f"{entry_path}.{key}")
                    if "evidenceRefs" in entry:
                        refs = entry["evidenceRefs"]
                        if not isinstance(refs, list):
                            v.error(f"{entry_path}.evidenceRefs", "expected array")
                        else:
                            v.nonempty(refs, f"{entry_path}.evidenceRefs")
                            string_items(v, refs, f"{entry_path}.evidenceRefs")
        decision = v.require(item, "decision", path, str)
        if isinstance(decision, str):
            v.enum(decision, DECISIONS, f"{path}.decision")
        method = item.get("verificationMethod")
        if isinstance(method, str):
            v.enum(method, METHODS, f"{path}.verificationMethod")
        pattern_scope = item.get("patternScope")
        if pattern_scope is not None:
            if not isinstance(pattern_scope, str):
                v.error(f"{path}.patternScope", "expected string")
            else:
                v.enum(pattern_scope, PATTERN_SCOPE, f"{path}.patternScope")
        disconfirmation = v.require(item, "disconfirmation", path, dict)
        if isinstance(disconfirmation, dict):
            v.closed_object(disconfirmation, f"{path}.disconfirmation", {"counterHypothesis", "evidenceSearched", "result"})
            for key in ("counterHypothesis", "evidenceSearched"):
                value = v.require(disconfirmation, key, f"{path}.disconfirmation", str)
                if isinstance(value, str):
                    v.nonempty(value, f"{path}.disconfirmation.{key}")
            result = v.require(disconfirmation, "result", f"{path}.disconfirmation", str)
            if isinstance(result, str):
                v.enum(result, DISCONFIRMATION_RESULTS, f"{path}.disconfirmation.result")
                if decision == "CONFIRMED" and result != "counter-refuted":
                    v.error(f"{path}.disconfirmation.result", "CONFIRMED requires counter-refuted disconfirmation")
                if decision == "NEEDS-DECISION" and result != "counter-refuted":
                    v.error(f"{path}.disconfirmation.result", "NEEDS-DECISION requires fact-level disconfirmation to be counter-refuted")
                if decision == "CONDITIONAL" and result == "counter-supported":
                    v.error(f"{path}.disconfirmation.result", "counter-supported closes or narrows the current Finding; rebuild it before using CONDITIONAL")
        if decision in {"CONFIRMED", "CONDITIONAL", "NEEDS-DECISION"}:
            risk = v.require(item, "risk", path, dict)
            if isinstance(risk, dict):
                v.closed_object(risk, f"{path}.risk", {"impact", "likelihood", "reachability", "recoverability"})
                for key, allowed in (
                    ("impact", RISK_IMPACT),
                    ("likelihood", RISK_LIKELIHOOD),
                    ("reachability", RISK_REACHABILITY),
                    ("recoverability", RISK_RECOVERABILITY),
                ):
                    value = v.require(risk, key, f"{path}.risk", str)
                    if isinstance(value, str):
                        v.enum(value, allowed, f"{path}.risk.{key}")
            severity = v.require(item, "severity", path, str)
            confidence = v.require(item, "confidence", path, str)
            if isinstance(severity, str):
                v.enum(severity, SEVERITIES, f"{path}.severity")
                if isinstance(risk, dict) and isinstance(risk.get("impact"), str):
                    permitted = permitted_severities(risk)
                    if severity not in permitted:
                        v.error(
                            f"{path}.severity",
                            f"{severity} is not permitted by the Impact/Likelihood/Reachability/Recoverability mapping; allowed: {', '.join(sorted(permitted))}",
                        )
                    if severity != risk["impact"]:
                        rationale = v.require(item, "severityRationale", path, str)
                        if isinstance(rationale, str):
                            v.nonempty(rationale, f"{path}.severityRationale")
                    elif "severityRationale" in item:
                        v.error(f"{path}.severityRationale", "allowed only when Severity differs from Impact")
            if isinstance(confidence, str):
                v.enum(confidence, CONFIDENCE, f"{path}.confidence")
                if decision == "CONFIRMED" and confidence not in {"High", "Very-High"}:
                    v.error(f"{path}.confidence", "CONFIRMED requires High or Very-High")
        elif decision == "REJECTED":
            for key in ("risk", "severity", "severityRationale", "confidence", "disposition"):
                if key in item:
                    v.error(f"{path}.{key}", "must be omitted for REJECTED")
            if not isinstance(refuting, list) or not refuting:
                v.error(f"{path}.refutingEvidence", "REJECTED requires DIRECT refuting Evidence")
        elif decision == "PENDING":
            if phase == "FINAL":
                v.error(f"{path}.decision", "PENDING is not allowed in FINAL state")
            for key in ("severity", "severityRationale", "confidence", "disposition"):
                if key in item:
                    v.error(f"{path}.{key}", "must be omitted while Decision is PENDING")
        disposition = item.get("disposition")
        if "riskAcceptanceAuthorization" in item and disposition != "ACCEPTED-RISK":
            v.error(f"{path}.riskAcceptanceAuthorization", "allowed only with disposition=ACCEPTED-RISK")
        if disposition is not None:
            v.enum(disposition, DISPOSITIONS, f"{path}.disposition")
            if decision != "CONFIRMED":
                v.error(f"{path}.disposition", "explicit disposition is allowed only for CONFIRMED findings")
            if disposition == "RESOLVED-VERIFIED" and not item.get("resolutionEvidence"):
                v.error(f"{path}.resolutionEvidence", "required for RESOLVED-VERIFIED")
            authorization = item.get("riskAcceptanceAuthorization")
            if disposition == "ACCEPTED-RISK":
                validate_authorization_binding(v, authorization, f"{path}.riskAcceptanceAuthorization")
            if disposition == "ACCEPTED-RISK" and requested_gates:
                v.error(f"{path}.disposition", "global ACCEPTED-RISK is allowed only when no Gate exists; use per-target treatment")
        provenance = item.get("provenance")
        if provenance is not None:
            v.enum(provenance, PROVENANCE, f"{path}.provenance")
            if not item.get("provenanceEvidence"):
                v.error(f"{path}.provenanceEvidence", "required when provenance is present")
        elif item.get("provenanceEvidence"):
            v.error(f"{path}.provenanceEvidence", "allowed only when provenance is present")
        finding_gates = item.get("gates")
        if phase == "FINAL" and requested_gates and decision != "REJECTED" and finding_gates is None:
            v.error(f"{path}.gates", "required for every FINAL non-REJECTED finding when Gates exist")
        if finding_gates is not None:
            if not requested_gates:
                v.error(f"{path}.gates", "must be omitted when no Gate was requested")
            elif not isinstance(finding_gates, dict):
                v.error(f"{path}.gates", "expected object")
            else:
                if phase == "FINAL" and decision != "REJECTED" and set(finding_gates) != requested_gates:
                    v.error(f"{path}.gates", "FINAL non-REJECTED finding must cover every requested Gate")
                for target, gate in finding_gates.items():
                    g_path = f"{path}.gates.{target}"
                    if target not in requested_gates:
                        v.error(g_path, "target was not requested")
                    if not isinstance(gate, dict):
                        v.error(g_path, "expected object")
                        continue
                    v.closed_object(gate, g_path, {"applicability", "basis", "evidenceRefs", "treatment", "authorization"})
                    applicability = v.require(gate, "applicability", g_path, str)
                    if isinstance(applicability, str):
                        v.enum(applicability, APPLICABILITY, f"{g_path}.applicability")
                    gate_basis = v.require(gate, "basis", g_path, str)
                    if isinstance(gate_basis, str):
                        v.nonempty(gate_basis, f"{g_path}.basis")
                    evidence_refs = gate.get("evidenceRefs")
                    valid_gate_refs: list[str] = []
                    if applicability in {"APPLIES", "DOES-NOT-APPLY"}:
                        evidence_refs = v.require(gate, "evidenceRefs", g_path, list)
                    if evidence_refs is not None:
                        if not isinstance(evidence_refs, list):
                            v.error(f"{g_path}.evidenceRefs", "expected array")
                        else:
                            valid_gate_refs = string_items(v, evidence_refs, f"{g_path}.evidenceRefs")
                            if applicability in {"APPLIES", "DOES-NOT-APPLY"}:
                                v.nonempty(evidence_refs, f"{g_path}.evidenceRefs")
                            if len(set(valid_gate_refs)) != len(valid_gate_refs):
                                v.error(f"{g_path}.evidenceRefs", "contains duplicate entries")
                    if isinstance(finding_id, str):
                        finding_gate_records.append((g_path, finding_id, applicability if isinstance(applicability, str) else None, set(valid_gate_refs)))
                    treatment = gate.get("treatment")
                    if "authorization" in gate and treatment != "ACCEPTED":
                        v.error(f"{g_path}.authorization", "allowed only with treatment=ACCEPTED")
                    if treatment is not None:
                        if treatment != "ACCEPTED":
                            v.error(f"{g_path}.treatment", "only ACCEPTED is allowed")
                        if decision != "CONFIRMED" or applicability != "APPLIES":
                            v.error(f"{g_path}.treatment", "ACCEPTED requires CONFIRMED + APPLIES")
                        validate_authorization_binding(v, gate.get("authorization"), f"{g_path}.authorization", target)
                    if disposition == "RESOLVED-VERIFIED" and applicability != "DOES-NOT-APPLY":
                        v.error(f"{g_path}.applicability", "RESOLVED-VERIFIED requires DOES-NOT-APPLY for every requested Gate")
        verification = item.get("verificationFile")
        if decision != "PENDING":
            verification = v.require(item, "verificationFile", path, str)
        file_path = v.safe_json_path(verification, f"{path}.verificationFile", "verification") if isinstance(verification, str) else None
        if file_path is not None and isinstance(finding_id, str):
            verification_paths[finding_id] = file_path

    for finding_id, path in verification_paths.items():
        validate_verification(v, path, finding_id)

    # Cross-file references are checked after all referenced artifacts are loaded.
    reconciled_to_finding: dict[str, set[str]] = {}
    reconciled_evidence_to_finding: dict[str, set[str]] = {}
    residual_references: list[tuple[str, str]] = []
    for index, item in enumerate(units):
        if not isinstance(item, dict):
            continue
        raw_reconciliations = item.get("reconciliations", [])
        reconciliations = raw_reconciliations if isinstance(raw_reconciliations, list) else []
        if item.get("status") == "verified":
            unit_id = item.get("id")
            expected_hypotheses = v.unit_hypotheses.get(unit_id, set()) if isinstance(unit_id, str) else set()
            reconciled_hypotheses = {
                rec["hypothesisId"]
                for rec in reconciliations
                if isinstance(rec, dict) and isinstance(rec.get("hypothesisId"), str)
            }
            if expected_hypotheses != reconciled_hypotheses:
                missing = sorted(expected_hypotheses - reconciled_hypotheses)
                extra = sorted(reconciled_hypotheses - expected_hypotheses)
                v.error(
                    f"state.json.verificationUnits[{index}].reconciliations",
                    f"must reconcile every investigation hypothesis exactly once; missing={missing}, extra={extra}",
                )
            if len(reconciled_hypotheses) != len(reconciliations):
                v.error(f"state.json.verificationUnits[{index}].reconciliations", "contains duplicate hypothesis reconciliation")
        for r_index, rec in enumerate(reconciliations):
            path = f"state.json.verificationUnits[{index}].reconciliations[{r_index}]"
            if not isinstance(rec, dict):
                continue
            hypothesis_ref = rec.get("hypothesisId")
            if isinstance(hypothesis_ref, str) and hypothesis_ref not in v.hypotheses:
                v.error(f"{path}.hypothesisId", f"unknown hypothesis id {hypothesis_ref!r}")
            evidence_refs = string_set(rec.get("evidenceRefs"))
            unit_id = item.get("id")
            local_evidence = v.unit_evidence.get(unit_id, set()) if isinstance(unit_id, str) else set()
            for ref in evidence_refs:
                if ref not in local_evidence:
                    v.error(f"{path}.evidenceRefs", f"evidence {ref!r} does not belong to this Verification Unit")
            result = rec.get("result")
            polarities = {v.evidence_polarity.get(ref) for ref in evidence_refs if ref in local_evidence}
            if result == "FINDING" and "supports" not in polarities:
                v.error(f"{path}.evidenceRefs", "FINDING reconciliation requires supporting DIRECT evidence from this Unit")
            if result == "REFUTED" and "refutes" not in polarities:
                v.error(f"{path}.evidenceRefs", "REFUTED reconciliation requires refuting DIRECT evidence from this Unit")
            finding_ref = rec.get("findingId")
            hypothesis_recommendation = (
                v.hypothesis_recommendations.get(hypothesis_ref)
                if isinstance(hypothesis_ref, str)
                else None
            )
            expected_reconciliation = {
                "promote-to-finding": "FINDING",
                "close": "REFUTED",
                "residual-gap": "RESIDUAL-GAP",
            }.get(hypothesis_recommendation)
            if expected_reconciliation is not None and rec.get("result") != expected_reconciliation:
                v.error(
                    f"{path}.result",
                    f"must be {expected_reconciliation} for hypothesis recommendation {hypothesis_recommendation}",
                )
            if rec.get("result") == "FINDING" and isinstance(finding_ref, str) and finding_ref not in finding_by_id:
                v.error(f"{path}.findingId", f"unknown finding id {finding_ref!r}")
            elif rec.get("result") == "FINDING" and isinstance(finding_ref, str) and isinstance(hypothesis_ref, str):
                reconciled_to_finding.setdefault(finding_ref, set()).add(hypothesis_ref)
                reconciled_evidence_to_finding.setdefault(finding_ref, set()).update(evidence_refs)
            residual_ref = rec.get("residualRiskId")
            if rec.get("result") == "RESIDUAL-GAP" and isinstance(residual_ref, str):
                residual_references.append((f"{path}.residualRiskId", residual_ref))
    finding_evidence_sets: dict[str, set[str]] = {}
    for index, item in enumerate(findings):
        if not isinstance(item, dict):
            continue
        path = f"state.json.findings[{index}]"
        source_hypotheses = string_set(item.get("sourceHypotheses"))
        finding_id = item.get("id")
        for ref in source_hypotheses:
            if ref not in v.hypotheses:
                v.error(f"{path}.sourceHypotheses", f"unknown hypothesis id {ref!r}")
        linked_hypotheses = reconciled_to_finding.get(finding_id, set()) if isinstance(finding_id, str) else set()
        if source_hypotheses != linked_hypotheses:
            v.error(
                f"{path}.sourceHypotheses",
                f"must exactly match FINDING reconciliations; missing={sorted(linked_hypotheses - source_hypotheses)}, extra={sorted(source_hypotheses - linked_hypotheses)}",
            )
        categorized_evidence: set[str] = set()
        for key in ("supportingEvidence", "refutingEvidence", "resolutionEvidence", "provenanceEvidence"):
            for ref in string_set(item.get(key, [])):
                categorized_evidence.add(ref)
                if ref not in v.evidence:
                    v.error(f"{path}.{key}", f"unknown evidence id {ref!r}")
                    continue
                expected_polarity = {
                    "supportingEvidence": "supports",
                    "refutingEvidence": "refutes",
                    "resolutionEvidence": "refutes",
                    "provenanceEvidence": "context",
                }[key]
                actual_polarity = v.evidence_polarity.get(ref)
                if actual_polarity != expected_polarity:
                    v.error(f"{path}.{key}", f"evidence {ref} has polarity={actual_polarity}, expected {expected_polarity}")
        if isinstance(finding_id, str):
            finding_evidence_sets[finding_id] = categorized_evidence
            for entry in item.get("decisionHistory") or []:
                if not isinstance(entry, dict):
                    continue
                for ref in string_set(entry.get("evidenceRefs") or []):
                    if ref not in v.evidence:
                        v.error(f"{path}.decisionHistory", f"unknown evidence id {ref!r}")
            expected_method = item.get("verificationMethod")
            actual_method = v.verification_method.get(finding_id)
            if actual_method is not None and actual_method != expected_method:
                v.error(f"{path}.verificationMethod", f"does not match verification file method {actual_method!r}")

            source_evidence = {
                ref
                for hypothesis_id in source_hypotheses
                for ref in v.hypothesis_evidence.get(hypothesis_id, set())
            }
            valid_investigation_evidence = source_evidence | reconciled_evidence_to_finding.get(finding_id, set())
            for ref in v.verification_checked.get(finding_id, set()):
                if ref not in valid_investigation_evidence:
                    v.error(
                        f"{path}.verificationFile",
                        f"checkedEvidence {ref!r} is not part of this Finding's investigation chain",
                    )
            new_evidence = v.verification_evidence.get(finding_id, set())
            for ref in new_evidence:
                if ref not in categorized_evidence:
                    v.error(
                        f"{path}.verificationFile",
                        f"new verification evidence {ref!r} is not consumed by this Finding",
                    )
            challenge_evidence = string_set(
                (v.verification_challenge.get(finding_id) or {}).get("evidenceRefs")
            )
            resolution_challenge_evidence = string_set(
                (v.verification_resolution_challenge.get(finding_id) or {}).get("evidenceRefs")
            )
            finding_chain = (
                valid_investigation_evidence
                | new_evidence
                | challenge_evidence
                | resolution_challenge_evidence
            )
            for key in ("supportingEvidence", "refutingEvidence", "resolutionEvidence", "provenanceEvidence"):
                for ref in string_set(item.get(key, [])):
                    if ref not in finding_chain:
                        v.error(
                            f"{path}.{key}",
                            f"evidence {ref!r} is not part of this Finding's source or verification chain",
                        )

            raw_decision = item.get("decision")
            raw_severity = item.get("severity")
            decision = raw_decision if isinstance(raw_decision, str) else None
            severity = raw_severity if isinstance(raw_severity, str) else None
            if decision == "REJECTED" and not (new_evidence & string_set(item.get("refutingEvidence"))):
                v.error(f"{path}.refutingEvidence", "REJECTED requires new refuting Evidence from its verification file")
            if decision in {"CONFIRMED", "NEEDS-DECISION"} and not (
                new_evidence & string_set(item.get("supportingEvidence"))
            ):
                v.error(f"{path}.supportingEvidence", f"{decision} requires new supporting Evidence from its verification file")
            if item.get("disposition") == "RESOLVED-VERIFIED" and not (
                new_evidence & string_set(item.get("resolutionEvidence"))
            ):
                v.error(f"{path}.resolutionEvidence", "RESOLVED-VERIFIED requires new resolution Evidence from its verification file")

            challenge = v.verification_challenge.get(finding_id)
            source_claim_ids = {
                unit_by_id[unit_id].get("claimId")
                for hypothesis_id in source_hypotheses
                for unit_id in [hypothesis_id.split("-H", 1)[0]]
                if unit_id in unit_by_id
            }
            challenge_required = severity in {"Critical", "High"} and decision in {
                "CONFIRMED",
                "CONDITIONAL",
                "NEEDS-DECISION",
            }
            if challenge_required and challenge is None:
                v.error(f"{path}.verificationFile", "Critical/High Finding requires a recorded second challenge")
            if isinstance(challenge, dict):
                status = challenge.get("status")
                if status == "GAP" and decision != "CONDITIONAL":
                    v.error(f"{path}.verificationFile", "challenge GAP is allowed only for a CONDITIONAL Finding")
                if status == "COMPLETED":
                    challenge_refs = string_set(challenge.get("evidenceRefs"))
                    mode = challenge.get("mode")
                    allowed_challenge_refs: set[str] = set()
                    if mode == "EQUIVALENT-DIRECT-DISCONFIRMATION":
                        allowed_challenge_refs = new_evidence
                    elif mode == "HETEROGENEOUS-METHOD":
                        challenge_unit_id = challenge.get("unitId")
                        challenge_unit = unit_by_id.get(challenge_unit_id) if isinstance(challenge_unit_id, str) else None
                        if challenge_unit is None:
                            v.error(f"{path}.verificationFile", "heterogeneous challenge must reference an existing Verification Unit")
                        else:
                            if challenge_unit.get("status") != "verified":
                                v.error(f"{path}.verificationFile", "heterogeneous challenge Unit must be verified")
                            if challenge_unit.get("claimId") not in source_claim_ids:
                                v.error(f"{path}.verificationFile", "heterogeneous challenge Unit must verify a Claim that produced this Finding")
                            if challenge.get("method") != challenge_unit.get("method"):
                                v.error(f"{path}.verificationFile", "heterogeneous challenge method must equal its Verification Unit method")
                            allowed_challenge_refs = v.unit_evidence.get(challenge_unit_id, set())
                    for ref in challenge_refs:
                        if ref not in allowed_challenge_refs:
                            v.error(
                                f"{path}.verificationFile",
                                f"challenge evidence {ref!r} is not produced by the declared challenge path",
                            )
                    challenge_polarities = {
                        v.evidence_polarity.get(ref)
                        for ref in challenge_refs
                        if ref in v.evidence_polarity
                    }
                    if challenge.get("result") == "counter-refuted" and "supports" not in challenge_polarities:
                        v.error(f"{path}.verificationFile", "counter-refuted challenge requires supporting Evidence")
                    if challenge.get("result") == "counter-supported" and "refutes" not in challenge_polarities:
                        v.error(f"{path}.verificationFile", "counter-supported challenge requires refuting Evidence")
                    if (
                        challenge.get("mode") == "HETEROGENEOUS-METHOD"
                        and challenge.get("method") == expected_method
                    ):
                        v.error(f"{path}.verificationFile", "heterogeneous challenge method must differ from the primary verification method")
                    if decision in {"CONFIRMED", "NEEDS-DECISION"} and challenge.get("result") != "counter-refuted":
                        v.error(f"{path}.verificationFile", f"{decision} requires a completed counter-refuted challenge")
                    if decision == "CONDITIONAL" and challenge.get("result") == "counter-supported":
                        v.error(f"{path}.verificationFile", "counter-supported challenge closes or narrows the current Finding")

            resolution_challenge = v.verification_resolution_challenge.get(finding_id)
            resolution_required = (
                severity in {"Critical", "High"}
                and item.get("disposition") == "RESOLVED-VERIFIED"
            )
            if resolution_required and resolution_challenge is None:
                v.error(f"{path}.verificationFile", "Critical/High RESOLVED-VERIFIED Finding requires a resolutionChallenge")
            if isinstance(resolution_challenge, dict):
                status = resolution_challenge.get("status")
                if item.get("disposition") != "RESOLVED-VERIFIED":
                    v.error(f"{path}.verificationFile", "resolutionChallenge is allowed only for RESOLVED-VERIFIED")
                if status != "COMPLETED":
                    v.error(f"{path}.verificationFile", "RESOLVED-VERIFIED requires a completed resolutionChallenge")
                else:
                    challenge_unit_id = resolution_challenge.get("unitId")
                    challenge_unit = unit_by_id.get(challenge_unit_id) if isinstance(challenge_unit_id, str) else None
                    if challenge_unit is None:
                        v.error(f"{path}.verificationFile", "resolutionChallenge must reference an existing Verification Unit")
                    else:
                        if challenge_unit.get("status") != "verified":
                            v.error(f"{path}.verificationFile", "resolutionChallenge Unit must be verified")
                        if challenge_unit.get("claimId") not in source_claim_ids:
                            v.error(f"{path}.verificationFile", "resolutionChallenge Unit must verify a Claim that produced this Finding")
                        if resolution_challenge.get("method") != challenge_unit.get("method"):
                            v.error(f"{path}.verificationFile", "resolutionChallenge method must equal its Verification Unit method")
                        if resolution_challenge.get("method") == expected_method:
                            v.error(f"{path}.verificationFile", "resolutionChallenge method must differ from the primary verification method")
                        allowed_resolution_refs = v.unit_evidence.get(challenge_unit_id, set())
                        for ref in string_set(resolution_challenge.get("evidenceRefs")):
                            if ref not in allowed_resolution_refs:
                                v.error(f"{path}.verificationFile", f"resolution challenge evidence {ref!r} is not produced by its Unit")
                    if resolution_challenge.get("result") != "resolution-supported":
                        v.error(f"{path}.verificationFile", "RESOLVED-VERIFIED requires resolution-supported challenge result")
                    if not (
                        string_set(resolution_challenge.get("evidenceRefs"))
                        & string_set(item.get("resolutionEvidence"))
                    ):
                        v.error(f"{path}.resolutionEvidence", "resolutionChallenge Evidence must be recorded as resolutionEvidence")

    for gate_path, finding_id, applicability, refs in finding_gate_records:
        allowed = finding_evidence_sets.get(finding_id, set())
        for ref in refs:
            if ref not in allowed:
                v.error(f"{gate_path}.evidenceRefs", f"evidence {ref!r} is not linked to Finding {finding_id}")
        polarities = {v.evidence_polarity.get(ref) for ref in refs if ref in allowed}
        if applicability == "APPLIES" and not polarities.intersection({"supports", "context"}):
            v.error(f"{gate_path}.evidenceRefs", "APPLIES requires supporting or contextual current-applicability Evidence")
        if applicability == "DOES-NOT-APPLY" and not polarities.intersection({"refutes", "context"}):
            v.error(f"{gate_path}.evidenceRefs", "DOES-NOT-APPLY requires refuting or contextual current-state Evidence")
        finding = finding_by_id.get(finding_id, {})
        if finding.get("disposition") == "RESOLVED-VERIFIED" and not (
            refs & string_set(finding.get("resolutionEvidence"))
        ):
            v.error(f"{gate_path}.evidenceRefs", "RESOLVED-VERIFIED applicability must cite resolutionEvidence")

    residual_by_gate: dict[str, list[dict[str, Any]]] = {target: [] for target in requested_gates}
    residual_ids: set[str] = set()
    residual_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(residual):
        path = f"state.json.residualRisks[{index}]"
        if not isinstance(item, dict):
            v.error(path, "expected object")
            continue
        v.closed_object(item, path, {"id", "statement", "scope", "material", "affectsGates"})
        residual_id = v.require(item, "id", path, str)
        if isinstance(residual_id, str):
            v.id(residual_id, "residual", f"{path}.id")
            if residual_id in residual_ids:
                v.error(f"{path}.id", f"duplicate residual id {residual_id}")
            residual_ids.add(residual_id)
            residual_by_id[residual_id] = item
        for key in ("statement", "scope"):
            value = v.require(item, key, path, str)
            if isinstance(value, str):
                v.nonempty(value, f"{path}.{key}")
        v.require(item, "material", path, bool)
        affects = item.get("affectsGates")
        if affects is not None:
            if not requested_gates:
                v.error(f"{path}.affectsGates", "must be omitted when no Gate was requested")
            elif not isinstance(affects, list):
                v.error(f"{path}.affectsGates", "expected array")
            else:
                v.nonempty(affects, f"{path}.affectsGates")
                valid_targets = string_items(v, affects, f"{path}.affectsGates")
                if len(set(valid_targets)) != len(valid_targets):
                    v.error(f"{path}.affectsGates", "contains duplicate entries")
                for target in valid_targets:
                    if target not in requested_gates:
                        v.error(f"{path}.affectsGates", f"unknown or unrequested Gate target {target!r}")
                    else:
                        residual_by_gate[target].append(item)

    for path, residual_ref in terminal_unit_residuals:
        residual_item = residual_by_id.get(residual_ref)
        if residual_item is None:
            v.error(path, f"unknown residual risk id {residual_ref!r}")
        elif residual_item.get("material") is not True:
            v.error(path, "unfinished REQUIRED Unit must map to a material residual risk")

    for path, residual_ref in residual_references:
        residual_item = residual_by_id.get(residual_ref)
        if residual_item is None:
            v.error(path, f"unknown residual risk id {residual_ref!r}")
        elif residual_item.get("material") is not True:
            v.error(path, "RESIDUAL-GAP from a material Hypothesis must map to a material residual risk")

    if exhaustive_coverage_residual_ref is not None:
        coverage_path = "state.json.audit.scopeCoverage.residualRiskId"
        residual_item = residual_by_id.get(exhaustive_coverage_residual_ref)
        if residual_item is None:
            v.error(coverage_path, f"unknown residual risk id {exhaustive_coverage_residual_ref!r}")
        elif residual_item.get("material") is not True:
            v.error(coverage_path, "incomplete exhaustive coverage must map to a material residual risk")
        elif requested_gates and not requested_gates.issubset(string_set(residual_item.get("affectsGates"))):
            v.error(coverage_path, "exhaustive coverage residual must affect every requested Gate")

    validate_fix_workflow(v, data, phase, execution, finding_by_id, residual_by_id)

    exploration = data.get("exploration")
    exploratory_claims = [claim for claim in claims if isinstance(claim, dict) and claim.get("obligation") == "EXPLORATORY"]
    if exploratory_claims:
        if not isinstance(exploration, dict):
            v.error("state.json.exploration", "required when EXPLORATORY claims exist")
        else:
            rounds = v.require(exploration, "rounds", "state.json.exploration", list)
            no_delta = v.require(exploration, "noMaterialDeltaRounds", "state.json.exploration", int)
            if isinstance(no_delta, int) and (no_delta < 0 or no_delta > 2):
                v.error("state.json.exploration.noMaterialDeltaRounds", "must be between 0 and 2")
            if isinstance(rounds, list):
                declared: set[str] = set()
                round_claims: dict[str, set[str]] = {}
                for index, item in enumerate(rounds):
                    r_path = f"state.json.exploration.rounds[{index}]"
                    if not isinstance(item, dict):
                        v.error(r_path, "expected object")
                        continue
                    v.closed_object(item, r_path, {"id", "claimIds", "materialDelta"})
                    round_id = v.require(item, "id", r_path, str)
                    if isinstance(round_id, str):
                        if not re.fullmatch(r"X[1-9][0-9]*", round_id):
                            v.error(f"{r_path}.id", "expected X<n>")
                        if round_id in declared:
                            v.error(f"{r_path}.id", f"duplicate exploration round id {round_id}")
                        declared.add(round_id)
                    claim_ids = v.require(item, "claimIds", r_path, list)
                    valid_claim_ids = string_items(v, claim_ids, f"{r_path}.claimIds")
                    if isinstance(claim_ids, list):
                        v.nonempty(claim_ids, f"{r_path}.claimIds")
                    if len(set(valid_claim_ids)) != len(valid_claim_ids):
                        v.error(f"{r_path}.claimIds", "contains duplicate entries")
                    if isinstance(round_id, str):
                        round_claims[round_id] = set(valid_claim_ids)
                    for claim_id in valid_claim_ids:
                        if claim_id not in claim_by_id:
                            v.error(f"{r_path}.claimIds", f"unknown claim id {claim_id!r}")
                        elif claim_by_id[claim_id].get("obligation") != "EXPLORATORY":
                            v.error(f"{r_path}.claimIds", "only EXPLORATORY claims may belong to an exploration round")
                        elif claim_by_id[claim_id].get("explorationRound") != round_id:
                            v.error(f"{r_path}.claimIds", f"Claim {claim_id!r} must point back to round {round_id!r}")
                    v.require(item, "materialDelta", r_path, bool)
                used = {
                    item["explorationRound"]
                    for item in exploratory_claims
                    if isinstance(item.get("explorationRound"), str)
                }
                if not used.issubset(declared):
                    v.error("state.json.exploration.rounds", f"missing rounds used by claims: {sorted(used - declared)}")
                for claim in exploratory_claims:
                    claim_id = claim.get("id")
                    round_id = claim.get("explorationRound")
                    if isinstance(claim_id, str) and isinstance(round_id, str) and claim_id not in round_claims.get(round_id, set()):
                        v.error("state.json.exploration.rounds", f"round {round_id!r} must list EXPLORATORY Claim {claim_id!r}")
    elif exploration is not None:
        v.error("state.json.exploration", "must be omitted when no EXPLORATORY claims exist")

    # Claim-level heterogeneous/independent requirements and Gate derivation.
    independent_required = string_set(audit.get("independentValidationRequiredFor", [])) if isinstance(audit, dict) else set()
    if phase == "FINAL" and not requested_gates and not any(
        claim.get("obligation") == "REQUIRED" for claim in claim_by_id.values()
    ):
        v.error(
            "state.json.claims",
            "FINAL no-Gate audit requires at least one REQUIRED Claim; a non-empty objective list cannot be closed by zero verification scope",
        )
    highest_for_audit = [claim for claim in claim_by_id.values() if claim.get("priority") == "highest"]
    if phase == "FINAL" and "AUDIT" in independent_required and not highest_for_audit:
        if requested_gates:
            v.warning("state.json.audit.independentValidationRequiredFor", "explicit AUDIT independent validation requires at least one highest Claim")
        else:
            v.error("state.json.audit.independentValidationRequiredFor", "FINAL audit-wide independent validation requires at least one highest Claim")
    for claim_id, claim in claim_by_id.items():
        claim_units = units_by_claim.get(claim_id, [])
        required_verified = [u for u in claim_units if u.get("status") == "verified" and claim.get("obligation") == "REQUIRED"]
        methods = {u["method"] for u in required_verified if isinstance(u.get("method"), str)}
        if claim.get("priority") == "highest" and phase == "FINAL" and len(methods) < 2:
            # Legal final outcome can still be INCOMPLETE, so this is a warning here;
            # a falsely strong Gate is rejected below.
            v.warning(f"state.json.claims[{claim_id}]", "highest claim lacks two verified heterogeneous methods")
        constrained = "AUDIT" in independent_required or bool(string_set(claim.get("gateTargets")) & independent_required)
        if constrained and claim.get("priority") == "highest":
            isolated = [u for u in required_verified if u.get("isolation") == "ISOLATED"]
            independent_ok = (
                len({u["method"] for u in isolated if isinstance(u.get("method"), str)}) >= 2
                and len({u["executor"] for u in isolated if isinstance(u.get("executor"), str)}) >= 2
            )
            if not independent_ok:
                if phase == "FINAL" and not requested_gates and "AUDIT" in independent_required:
                    v.error(f"state.json.claims[{claim_id}]", "FINAL audit-wide independent validation requirement is not met")
                else:
                    v.warning(f"state.json.claims[{claim_id}]", "explicit independent validation requirement is not met")

    def gate_expected(target: str) -> tuple[str, list[str]]:
        blocked_reasons: list[str] = []
        incomplete_reasons: list[str] = []
        conditional_reasons: list[str] = []
        incomplete = False
        blocked = False
        conditional = False
        threshold = gate_policies.get(target, {}).get("blockAtOrAbove", "High")
        threshold_rank = {"High": 3, "Medium": 2, "Low": 1}[threshold]
        if exhaustive_coverage_incomplete:
            incomplete = True
            incomplete_reasons.append("EXHAUSTIVE-COVERAGE-GAP")
        scoped_required_claims = [
            claim
            for claim in claim_by_id.values()
            if claim.get("obligation") == "REQUIRED"
            and target in string_set(claim.get("gateTargets"))
        ]
        if not scoped_required_claims:
            incomplete = True
            incomplete_reasons.append("REQUIRED-COVERAGE-GAP")
        highest_for_target = [claim for claim in highest_for_audit if target in string_set(claim.get("gateTargets"))]
        if "AUDIT" in independent_required and not highest_for_audit:
            incomplete = True
            incomplete_reasons.append("INDEPENDENT-VALIDATION-GAP")
        if "AUDIT" in independent_required:
            for audit_claim in highest_for_audit:
                audit_claim_id = audit_claim.get("id")
                audit_units = units_by_claim.get(audit_claim_id, []) if isinstance(audit_claim_id, str) else []
                isolated = [u for u in audit_units if u.get("status") == "verified" and u.get("isolation") == "ISOLATED"]
                methods = {u["method"] for u in isolated if isinstance(u.get("method"), str)}
                executors = {u["executor"] for u in isolated if isinstance(u.get("executor"), str)}
                if len(methods) < 2 or len(executors) < 2:
                    incomplete = True
                    incomplete_reasons.append(f"{audit_claim_id}: audit-wide independent validation incomplete")
        if target in independent_required and not highest_for_target:
            incomplete = True
            incomplete_reasons.append("INDEPENDENT-VALIDATION-GAP")
        for claim_id, claim in claim_by_id.items():
            if claim.get("obligation") != "REQUIRED":
                continue
            if target not in string_set(claim.get("gateTargets")):
                continue
            claim_units = units_by_claim.get(claim_id, [])
            required_units = claim_units
            if not required_units or any(u.get("status") != "verified" for u in required_units):
                incomplete = True
                incomplete_reasons.append(f"{claim_id}: required verification incomplete")
            priority = claim.get("priority")
            if isinstance(priority, str) and priority in {"highest", "high"} and claim.get("sufficiency") != "MET":
                incomplete = True
                incomplete_reasons.append(f"{claim_id}: evidence sufficiency not met")
            if claim.get("priority") == "highest":
                verified = [u for u in required_units if u.get("status") == "verified"]
                if len({u["method"] for u in verified if isinstance(u.get("method"), str)}) < 2:
                    incomplete = True
                    incomplete_reasons.append(f"{claim_id}: heterogeneous verification incomplete")
                if target in independent_required:
                    isolated = [u for u in verified if u.get("isolation") == "ISOLATED"]
                    if (
                        len({u["method"] for u in isolated if isinstance(u.get("method"), str)}) < 2
                        or len({u["executor"] for u in isolated if isinstance(u.get("executor"), str)}) < 2
                    ):
                        incomplete = True
                        incomplete_reasons.append(f"{claim_id}: required independent validation incomplete")
        for finding in findings:
            if not isinstance(finding, dict) or finding.get("decision") == "REJECTED":
                continue
            finding_gates = finding.get("gates")
            raw_gate = finding_gates.get(target, {}) if isinstance(finding_gates, dict) else {}
            gate = raw_gate if isinstance(raw_gate, dict) else {}
            applicability = gate.get("applicability")
            if applicability not in APPLICABILITY:
                incomplete = True
                incomplete_reasons.append(f"{finding.get('id')}: Gate applicability missing or invalid")
                continue
            if finding.get("decision") == "PENDING" and applicability != "DOES-NOT-APPLY":
                incomplete = True
                incomplete_reasons.append(f"{finding.get('id')}: decision pending")
                continue
            if applicability == "UNRESOLVED":
                severity = finding.get("severity")
                severity_rank = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}.get(severity, 0) if isinstance(severity, str) else 0
                if severity_rank >= threshold_rank:
                    incomplete = True
                    incomplete_reasons.append(f"{finding.get('id')}: material Gate applicability unresolved")
                else:
                    conditional = True
                    conditional_reasons.append(f"{finding.get('id')}: non-blocking Gate applicability unresolved")
                continue
            if applicability != "APPLIES":
                continue
            accepted = gate.get("treatment") == "ACCEPTED"
            disposition = finding.get("disposition", "OPEN")
            if disposition == "RESOLVED-VERIFIED" or accepted:
                continue
            decision = finding.get("decision")
            severity = finding.get("severity")
            severity_rank = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}.get(severity, 0) if isinstance(severity, str) else 0
            if isinstance(decision, str) and decision in {"CONDITIONAL", "NEEDS-DECISION"} and severity_rank >= threshold_rank:
                incomplete = True
                incomplete_reasons.append(f"{finding.get('id')}: material decision/evidence gap")
            elif decision == "CONFIRMED" and severity_rank >= threshold_rank:
                blocked = True
                blocked_reasons.append(f"{finding.get('id')}: confirmed {severity} risk")
            elif isinstance(decision, str) and decision in {"CONFIRMED", "CONDITIONAL", "NEEDS-DECISION"}:
                conditional = True
                conditional_reasons.append(f"{finding.get('id')}: non-blocking condition")
        for item in residual_by_gate.get(target, []):
            if item.get("material"):
                incomplete = True
                incomplete_reasons.append(f"{item.get('id')}: material residual risk")
            else:
                conditional = True
                conditional_reasons.append(f"{item.get('id')}: residual risk")
        if blocked:
            return "BLOCKED", blocked_reasons
        if incomplete:
            return "INCOMPLETE", incomplete_reasons
        if conditional:
            return "READY-WITH-CONDITIONS", conditional_reasons
        return "READY", ["ALL-REQUIRED-INPUTS-SATISFIED"]

    if phase == "FINAL" and requested_gates:
        if set(gate_decisions) != requested_gates:
            v.error("state.json.audit.gates.decisions", "FINAL state requires one decision for every requested Gate")
        live_ids = set(claim_by_id) | set(finding_by_id) | {
            item.get("id") for item in residual if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        basis_tokens = {
            "ALL-REQUIRED-INPUTS-SATISFIED",
            "INDEPENDENT-VALIDATION-GAP",
            "REQUIRED-COVERAGE-GAP",
            "EXHAUSTIVE-COVERAGE-GAP",
        }
        for target in requested_gates:
            expected, reasons = gate_expected(target)
            raw_decision = gate_decisions.get(target, {})
            decision_record = raw_decision if isinstance(raw_decision, dict) else {}
            actual = decision_record.get("result")
            if actual is not None and actual != expected:
                v.error(f"state.json.audit.gates.decisions.{target}.result", f"declared {actual}, but state derives {expected}")
            basis = decision_record.get("basis", [])
            if isinstance(basis, list):
                decisive = {
                    reason if reason in basis_tokens else reason.split(":", 1)[0]
                    for reason in reasons
                }
                valid_basis = [entry for entry in basis if isinstance(entry, str)]
                for entry in valid_basis:
                    if isinstance(entry, str) and entry not in live_ids and entry not in basis_tokens:
                        v.error(f"state.json.audit.gates.decisions.{target}.basis", f"unknown id/token {entry!r}")
                    elif isinstance(entry, str) and entry not in decisive:
                        v.error(
                            f"state.json.audit.gates.decisions.{target}.basis",
                            f"{entry!r} does not determine the derived {expected} result",
                        )
                if decisive and not decisive.intersection(valid_basis):
                    v.error(
                        f"state.json.audit.gates.decisions.{target}.basis",
                        f"must cite at least one decisive id/token: {sorted(decisive)}",
                    )

    validate_live_layout(v, root, phase if isinstance(phase, str) else None, investigation_paths.values(), verification_paths.values())
    return v


def state_file(path: Path) -> Path:
    return path / "state.json" if path.is_dir() else path


def validate_state_root(root: Path) -> Validation:
    """Validate the fixed active/archive layout and supersession graph."""
    result = Validation(root)
    if is_link_like(root):
        result.error(str(root), "state root must not be a symlink or junction")
        return result
    try:
        root_entries = list(root.iterdir())
    except OSError as exc:
        result.error(str(root), f"cannot read state root: {exc}")
        return result
    direct: list[Path] = []
    for entry in root_entries:
        if entry.name == "archive":
            if not entry.is_dir() or is_link_like(entry):
                result.error(entry.name, "state-root archive entry must be a real directory")
            continue
        if not entry.is_dir() or is_link_like(entry):
            result.error(entry.name, "unsupported state-root entry; only audit-instance directories and archive/ are allowed")
            continue
        direct.append(entry)
    archive_root = root / "archive"
    archived: list[Path] = []
    if archive_root.exists() and not is_link_like(archive_root):
        try:
            for entry in archive_root.iterdir():
                if not entry.is_dir() or is_link_like(entry):
                    relative = str(entry.relative_to(root)).replace("\\", "/")
                    result.error(relative, "unsupported archive entry; only archived audit-instance directories are allowed")
                    continue
                archived.append(entry)
        except OSError as exc:
            result.error(str(archive_root), f"cannot read archive directory: {exc}")
            return result
    audit_directories = direct + archived
    for directory in audit_directories:
        if is_link_like(directory / "state.json") or not (directory / "state.json").is_file():
            relative = str(directory.relative_to(root)).replace("\\", "/")
            result.error(relative, "audit directory is missing state.json")
    state_paths = [
        path / "state.json"
        for path in audit_directories
        if not is_link_like(path / "state.json") and (path / "state.json").is_file()
    ]
    if not state_paths:
        result.error(str(root), "no audit state directories found")
        return result

    records_by_id: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for path in state_paths:
        validation = validate_state(path)
        relative = str(path.relative_to(root)).replace("\\", "/")
        result.errors.extend(f"{relative}: {error}" for error in validation.errors)
        result.warnings.extend(f"{relative}: {warning}" for warning in validation.warnings)
        data = load_json(path, result, relative)
        if not isinstance(data, dict) or not isinstance(data.get("audit"), dict):
            continue
        audit_id = data["audit"].get("id")
        if not isinstance(audit_id, str):
            continue
        records_by_id.setdefault(audit_id, []).append((path, data))
        directory_name = path.parent.name
        is_archive = path.parent.parent == archive_root
        if is_archive and data.get("phase") == "ACTIVE":
            result.error(relative, "ACTIVE audit cannot be stored under archive")
        name_ok = directory_name == audit_id or (is_archive and directory_name.startswith(f"{audit_id}-"))
        if not name_ok:
            result.error(relative, f"directory name {directory_name!r} does not match audit id {audit_id!r}")

    for audit_id, records in records_by_id.items():
        if len(records) > 1:
            locations = [str(path.relative_to(root)).replace("\\", "/") for path, _ in records]
            result.error(str(root), f"duplicate audit id {audit_id!r} at {locations}")

    unique = {audit_id: records[0] for audit_id, records in records_by_id.items() if len(records) == 1}
    successor_by_old: dict[str, str] = {}
    for new_id, (new_path, new_data) in unique.items():
        new_audit = new_data["audit"]
        old_id = new_audit.get("supersedesAuditId")
        if not isinstance(old_id, str):
            continue
        label = str(new_path.relative_to(root)).replace("\\", "/")
        if old_id not in unique:
            result.error(label, f"supersedes unknown audit id {old_id!r}")
            continue
        if old_id in successor_by_old and successor_by_old[old_id] != new_id:
            result.error(str(root), f"audit {old_id!r} has multiple successors: {successor_by_old[old_id]!r}, {new_id!r}")
        successor_by_old[old_id] = new_id
        _, old_data = unique[old_id]
        old_audit = old_data["audit"]
        supersession = old_audit.get("supersession")
        if old_data.get("phase") != "SUPERSEDED" or not isinstance(supersession, dict) or supersession.get("byAuditId") != new_id:
            result.error(label, f"supersession link to {old_id!r} is not reciprocated by a SUPERSEDED predecessor")

    for old_id, (old_path, old_data) in unique.items():
        supersession = old_data["audit"].get("supersession")
        if not isinstance(supersession, dict):
            continue
        new_id = supersession.get("byAuditId")
        label = str(old_path.relative_to(root)).replace("\\", "/")
        if not isinstance(new_id, str) or new_id not in unique:
            result.error(label, f"supersession references unknown successor {new_id!r}")
            continue
        if unique[new_id][1]["audit"].get("supersedesAuditId") != old_id:
            result.error(label, f"successor {new_id!r} does not link back with supersedesAuditId")

    for start in successor_by_old:
        seen: set[str] = set()
        current = start
        while current in successor_by_old:
            if current in seen:
                result.error(str(root), f"supersession cycle detected at audit {current!r}")
                break
            seen.add(current)
            current = successor_by_old[current]
    return result


def run_self_test(fixtures: Path) -> int:
    failures = 0
    try:
        cases = sorted(path for path in fixtures.iterdir() if path.is_dir())
    except OSError as exc:
        print(f"SELF-TEST FAIL: cannot read {fixtures}: {exc}")
        return 1
    if not cases:
        print(f"SELF-TEST FAIL: no fixture directories under {fixtures}")
        return 1
    expectations_path = fixtures / "expectations.json"
    try:
        expectations = json.loads(expectations_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"SELF-TEST FAIL: cannot read valid expectations manifest {expectations_path}: {exc}")
        return 1
    if not isinstance(expectations, dict):
        print(f"SELF-TEST FAIL: expectations manifest must be an object: {expectations_path}")
        return 1
    for case in cases:
        expected_valid = case.name.startswith("valid-")
        result = validate_state(state_file(case))
        actual_valid = not result.errors
        expected_errors = expectations.get(case.name)
        malformed_expectation = (
            not expected_valid
            and (
                not isinstance(expected_errors, list)
                or not expected_errors
                or any(not isinstance(fragment, str) or not fragment for fragment in expected_errors)
            )
        )
        missing_expected = []
        if not expected_valid and isinstance(expected_errors, list):
            missing_expected = [
                fragment
                for fragment in expected_errors
                if isinstance(fragment, str)
                and fragment
                and not any(fragment in error for error in result.errors)
            ]
        if actual_valid != expected_valid or malformed_expectation or missing_expected:
            failures += 1
            print(f"SELF-TEST FAIL {case.name}: expected {'valid' if expected_valid else 'invalid'}")
            if malformed_expectation:
                print("  ERROR invalid fixture requires a non-empty expected-error fragment list")
            if missing_expected:
                print(f"  ERROR missing expected error fragments: {missing_expected}")
            for error in sorted(result.errors):
                print(f"  ERROR {error}")
        else:
            print(f"SELF-TEST PASS {case.name}: {'valid' if actual_valid else 'rejected as expected'}")
    return 1 if failures else 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="state.json file or audit state directory")
    parser.add_argument("--self-test", type=Path, metavar="FIXTURES", help="run valid-/invalid- fixture directories")
    parser.add_argument("--state-root", type=Path, metavar="ROOT", help="validate active/archive layout and supersession graph")
    args = parser.parse_args(argv)
    if args.self_test is not None:
        if args.state_root is not None or args.paths:
            parser.error("--self-test cannot be combined with paths or --state-root")
        return run_self_test(args.self_test)
    if args.state_root is not None:
        if args.paths:
            parser.error("--state-root cannot be combined with individual paths")
        result = validate_state_root(args.state_root)
        for warning in sorted(result.warnings):
            print(f"WARNING {warning}")
        for error in sorted(result.errors):
            print(f"ERROR {error}")
        if result.errors:
            print(f"FAIL {args.state_root}: {len(result.errors)} error(s), {len(result.warnings)} warning(s)")
            return 1
        print(f"PASS {args.state_root}: 0 errors, {len(result.warnings)} warning(s)")
        return 0
    if not args.paths:
        parser.error("provide at least one state.json/directory, --state-root, or --self-test")
    failed = False
    for raw in args.paths:
        path = state_file(raw)
        result = validate_state(path)
        for warning in sorted(result.warnings):
            print(f"WARNING {warning}")
        for error in sorted(result.errors):
            print(f"ERROR {error}")
        if result.errors:
            failed = True
            print(f"FAIL {path}: {len(result.errors)} error(s), {len(result.warnings)} warning(s)")
        else:
            print(f"PASS {path}: 0 errors, {len(result.warnings)} warning(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
