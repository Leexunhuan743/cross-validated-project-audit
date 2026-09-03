#!/usr/bin/env python3
"""Core-invariant checker for cross-validated audit state.

Guards only what a model cannot reliably hold across a long audit:

  0. identity & references  -- no duplicate id overwrites, no dangling ref
  1. invariant prerequisites-- a driver field's absence is an error, not a skip
  2. contract fields        -- the contract cannot be silently loosened
  3. snapshot binding       -- old Evidence cannot be replayed as current
  4. evidence graph         -- references resolve and polarities line up
  5. disconfirmation        -- a second challenge is real, not a relabel
  6. conclusion vs evidence -- no Severity/Decision stronger than the record
  7. finding-gate binding   -- applicability is an evidence claim, not an opinion
  8. Gate derivation        -- declared result equals the derived result
  9. fix-batch freshness    -- a stale PASSED cannot be consumed as current
 10. coverage & exploration -- exhaustive and exploration claims are bounded
 11. risk-acceptance binding-- a signature cannot be replayed across instances

`--state-root` additionally checks the supersession graph: reciprocal links,
one successor per predecessor, and no cycles.

Form-level shape (required keys, id patterns, path lexing, directory layout,
unmodelled keys) is NOT checked: fixtures are the shape reference. A missing
field never crashes the checker -- it inspects what is present and stays silent
on what is absent.

Driver *enums* are the one exception, and for the same reason as passes 0 and 1
rather than in spite of it: these values are compared against literals
(`phase == "FINAL"`, `severity in {"Critical", "High"}`,
`disconfirmationResult == "counter-supported"`), so a near-miss value does not
yield a wrong verdict, it yields no verdict -- the guard falls through and the
invariant silently stops running for that object. `phase: "final"` reads as
"not FINAL" and exempts the record from every closing obligation;
`strength: "ES3 "` reads as "not ES3" and exempts the Evidence from the
reproducibility requirement. See DRIVER_ENUMS for the closed sets.

So passes 0 and 1 narrow the silence to the three cases where silence disables
a check rather than merely skipping a field: a duplicated id silently
overwrites its predecessor, a dangling reference silently resolves to nothing,
an absent driver field (e.g. `decision`, `risk`) silently skips the invariant
that reads it, and an off-set driver value silently skips it too. Each of those
reports an error instead.

A PASS therefore means "no invariant was violated, and none was silently
disabled". It still never means "the audit is good" -- only that the record
does not contradict itself.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITY_RANK = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
# Each Finding evidence bucket may only cite Evidence of one polarity.
POLARITY_FOR = {
    "supportingEvidence": "supports",
    "refutingEvidence": "refutes",
    "resolutionEvidence": "refutes",
    "provenanceEvidence": "context",
}
DECISIVE_TOKENS = {
    "ALL-REQUIRED-INPUTS-SATISFIED",
    "INDEPENDENT-VALIDATION-GAP",
    "REQUIRED-COVERAGE-GAP",
    "EXHAUSTIVE-COVERAGE-GAP",
}
RECONCILIATION_EVIDENCE = {"FINDING": "supports", "REFUTED": "refutes"}
# Decisions that carry a rating and therefore owe the fields that rate them.
RATED_DECISIONS = {"CONFIRMED", "CONDITIONAL", "NEEDS-DECISION"}
# Risk tolerance has exactly two legitimate shapes; a free-form field is a third.
FORBIDDEN_AUDIT_FIELDS = ("riskTolerance",)
ROUND_ID_PATTERN = re.compile(r"X[1-9][0-9]*")


# ---------------------------------------------------------------------------
# Driver enums
# ---------------------------------------------------------------------------
# Nearly every invariant below is a string comparison against a literal:
# `phase == "FINAL"`, `disconfirmationResult == "counter-supported"`,
# `strength in {"ES3", "ES4"}`, `severity in {"Critical", "High"}`,
# `obligation == "REQUIRED"`. A one-character slip in any of them -- `final`,
# `counter-supporte`, `"ES3 "`, `critical`, `required` -- does not produce a
# wrong verdict, it produces no verdict at all: the guard falls through and the
# invariant it was protecting silently stops running for that object.
#
# That is strictly worse than an obviously bad value, because a bad value still
# gets reported by some check, while a near-miss value reports nothing and
# leaves the record looking clean. So these particular strings get a closed
# set. This is not schema validation -- the aim is not tidiness but the fact
# that these values are the on/off switches for real checks.
#
# Values come from SKILL.md plus what the fixtures actually exercise.
# `verificationUnits[].status` keeps `planned` even though SKILL.md never
# enumerates the Unit lifecycle: an un-dispatched Unit is a real state and
# valid-blocked-with-incomplete-scope relies on it.
#
# `risk.likelihood` / `reachability` / `recoverability` are deliberately absent:
# SKILL.md only quotes the handful of values used by the two Severity
# corrections, so a closed set here would be a guess. `risk.impact` is safe
# because it shares SEVERITY_RANK with `severity`, and an off-set impact
# already fails the Severity-vs-Impact check -- the entry here only gives that
# failure a readable message.
DRIVER_ENUMS: dict[str, set] = {
    "state.phase": {"ACTIVE", "FINAL", "SUPERSEDED"},
    "audit.scopeMode": {"project", "change", "pr", "author-commits"},
    "audit.executionMode": {"audit-only", "audit-and-fix"},
    "audit.stop.policy": {"exhaustive", "user-defined"},
    "audit.scopeResolution.basis": {"USER", "PLATFORM", "REPOSITORY", "ASSUMED"},
    "audit.scopeResolution.confidence": {"HIGH", "MEDIUM", "LOW"},
    "audit.snapshot.kind": {"git", "git-worktree", "archive", "deployment", "other"},
    "audit.gates.targets[]": {"CHANGE", "RELEASE", "SYSTEM"},
    "audit.gates.policies[].blockAtOrAbove": {"High", "Medium", "Low"},
    "claims[].obligation": {"REQUIRED", "EXPLORATORY"},
    "claims[].priority": {"highest", "high", "normal"},
    "claims[].sufficiency": {"MET", "NOT-MET"},
    "verificationUnits[].status": {"planned", "pending", "reported", "verified"},
    "verificationUnits[].isolation": {"ISOLATED", "NOT-ISOLATED"},
    "verificationUnits[].reconciliations[].result": {"FINDING", "REFUTED", "RESIDUAL-GAP"},
    "findings[].decision": {"CONFIRMED", "CONDITIONAL", "NEEDS-DECISION", "REJECTED", "PENDING"},
    "findings[].severity": set(SEVERITY_RANK),
    "findings[].confidence": {"Very-High", "High", "Medium", "Low"},
    "findings[].disposition": {"OPEN", "REMEDIATING", "RESOLVED-VERIFIED", "ACCEPTED-RISK"},
    "findings[].provenance": {"INTRODUCED", "EXPOSED", "REGRESSED", "PRE_EXISTING", "UNKNOWN"},
    "findings[].risk.impact": set(SEVERITY_RANK),
    "findings[].gates[].applicability": {"APPLIES", "DOES-NOT-APPLY", "UNRESOLVED"},
    # Artifact-side: every artifact form shares these three shapes.
    "evidence[].polarity": {"supports", "refutes", "context"},
    "evidence[].strength": {"ES1", "ES2", "ES3", "ES4"},
    "evidence[].reproducibility": {"repeatable", "conditional", "single-observation", "not-applicable"},
    "evidence[].testDiscrimination.result": {"YES", "PARTIAL", "NO", "UNKNOWN"},
    "investigations().hypotheses[].result": {"supported", "refuted", "unresolved"},
    "investigations().hypotheses[].recommendation": {"promote-to-finding", "close", "residual-gap"},
    "investigations().hypotheses[].disconfirmationResult": {
        "counter-supported", "counter-refuted", "unresolved",
    },
    "verification().challenge.status": {"COMPLETED", "GAP"},
    "verification().challenge.mode": {"HETEROGENEOUS-METHOD", "EQUIVALENT-DIRECT-DISCONFIRMATION"},
    "verification().challenge.result": {"counter-supported", "counter-refuted", "unresolved"},
    "verification().resolutionChallenge.status": {"COMPLETED"},
    "fixWorkflow.batches[].kind": {"FIX", "VERIFY", "REGRESSION"},
    "fixWorkflow.batches[].status": {"PENDING", "PASSED", "FAILED"},
}


# A misspelled driver key is not an omitted optional field -- it is a driver
# that never arrived, so it gets named rather than silently ignored.
FINDING_KEY_TYPOS = {
    "severityy": "severity",
    "severityRational": "severityRationale",
    "decison": "decision",
    "confidenc": "confidence",
    "dispostion": "disposition",
    "verificatonMethod": "verificationMethod",
}


def rows(value: object) -> list:
    return value if isinstance(value, list) else []


def strset(value: object) -> set:
    return {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()


def permitted_severities(risk: object) -> set:
    """The closed Impact-baseline mapping with its two adjacent corrections."""
    if not isinstance(risk, dict):
        return set()
    ranks = SEVERITY_RANK
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


class Report:
    def __init__(self, label: str) -> None:
        self.label = label
        self.errors: list[str] = []

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"ERROR {path}: {message}")

    @property
    def ok(self) -> bool:
        return not self.errors


class Audit:
    """Loads state.json plus the artifacts it references, and indexes them."""

    def __init__(self, root: Path, report: Report) -> None:
        self.root = root
        self.report = report
        self.state: dict = {}
        self.evidence_polarity: dict = {}
        self.unit_evidence: dict = {}
        self.hypothesis_evidence: dict = {}
        self.unit_hypotheses: dict = {}
        self.verification_new: dict = {}
        self.verification_checked: dict = {}
        self.challenge: dict = {}
        self.resolution_challenge: dict = {}
        self.verification_method: dict = {}
        self.test_discrimination_results: dict = {}
        self.hypothesis_unit: dict = {}
        self.investigations: dict = {}
        self.verifications: dict = {}

    # -- loading ---------------------------------------------------------
    def load(self) -> bool:
        path = self.root / "state.json"
        if not path.is_file():
            self.report.error(str(path), "state.json is missing")
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.report.error(str(path), f"unreadable state.json: {exc}")
            return False
        if not isinstance(data, dict):
            self.report.error(str(path), "state.json must be an object")
            return False
        self.state = data
        self._load_artifacts()
        return True

    def _load_artifacts(self) -> None:
        for unit in rows(self.state.get("verificationUnits")):
            if not isinstance(unit, dict):
                continue
            rel = unit.get("investigationFile")
            unit_id = unit.get("id")
            if isinstance(rel, str) and isinstance(unit_id, str):
                data = self._read(rel, "investigations", f"unit {unit_id}")
                if data is not None:
                    self.investigations[unit_id] = data
        for finding in rows(self.state.get("findings")):
            if not isinstance(finding, dict):
                continue
            rel = finding.get("verificationFile")
            finding_id = finding.get("id")
            if isinstance(rel, str) and isinstance(finding_id, str):
                data = self._read(rel, "verification", f"finding {finding_id}")
                if data is not None:
                    self.verifications[finding_id] = data

    def _read(self, rel: str, directory: str, label: str) -> object:
        raw = Path(rel)
        if not rel.endswith(".json") or raw.is_absolute() or ".." in raw.parts:
            self.report.error(f"state.json.{label}", f"artifact path must be a relative .json under {directory}/")
            return None
        if raw.parent != Path(directory):
            self.report.error(f"state.json.{label}", f"must be a flat .json file directly under {directory}/")
            return None
        path = self.root / raw
        if not path.is_file():
            self.report.error(f"state.json.{label}", f"referenced artifact is missing: {rel}")
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.report.error(str(path), f"unreadable: {exc}")
            return None
        if not isinstance(data, dict):
            self.report.error(str(path), "artifact must be an object")
            return None
        self._index_artifact(data, str(path))
        return data

    def _index_artifact(self, data: dict, label: str) -> None:
        for item in rows(data.get("evidence")):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                self.evidence_polarity[item["id"]] = item.get("polarity")
                discrimination = item.get("testDiscrimination")
                self.test_discrimination_results[item["id"]] = (
                    discrimination.get("result") if isinstance(discrimination, dict) else None
                )
        unit_id = data.get("unitId")
        if isinstance(unit_id, str):
            self.unit_evidence[unit_id] = {
                item["id"] for item in rows(data.get("evidence")) if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            self.unit_hypotheses[unit_id] = {
                item["id"] for item in rows(data.get("hypotheses")) if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
        for hyp in rows(data.get("hypotheses")):
            if isinstance(hyp, dict) and isinstance(hyp.get("id"), str):
                self.hypothesis_evidence[hyp["id"]] = strset(hyp.get("evidenceRefs"))
                if isinstance(unit_id, str):
                    self.hypothesis_unit[hyp["id"]] = unit_id
        finding_id = data.get("findingId")
        if isinstance(finding_id, str):
            self.verification_new[finding_id] = {
                item["id"] for item in rows(data.get("evidence")) if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            self.verification_checked[finding_id] = strset(data.get("checkedEvidence"))
            self.verification_method[finding_id] = data.get("method")
            self.challenge[finding_id] = data.get("challenge") if isinstance(data.get("challenge"), dict) else None
            self.resolution_challenge[finding_id] = (
                data.get("resolutionChallenge") if isinstance(data.get("resolutionChallenge"), dict) else None
            )

    # -- convenience -----------------------------------------------------
    @property
    def audit(self) -> dict:
        value = self.state.get("audit")
        return value if isinstance(value, dict) else {}

    @property
    def phase(self) -> str:
        value = self.state.get("phase")
        return value if isinstance(value, str) else ""

    @property
    def claims(self) -> list:
        return [item for item in rows(self.state.get("claims")) if isinstance(item, dict)]

    @property
    def units(self) -> list:
        return [item for item in rows(self.state.get("verificationUnits")) if isinstance(item, dict)]

    @property
    def findings(self) -> list:
        return [item for item in rows(self.state.get("findings")) if isinstance(item, dict)]

    @property
    def residuals(self) -> list:
        return [item for item in rows(self.state.get("residualRisks")) if isinstance(item, dict)]

    def units_by_claim(self, claim_id: object) -> list:
        return [unit for unit in self.units if unit.get("claimId") == claim_id]

    def unit(self, unit_id: object) -> dict:
        for unit in self.units:
            if unit.get("id") == unit_id:
                return unit
        return {}

    def finding_source_claims(self, finding_id: object) -> set:
        """The Claims whose Units produced this Finding's hypotheses."""
        finding = next((f for f in self.findings if f.get("id") == finding_id), {})
        return {
            self.unit(self.hypothesis_unit[hyp_id]).get("claimId")
            for hyp_id in strset(finding.get("sourceHypotheses"))
            if hyp_id in self.hypothesis_unit
        }

    def finding_chain(self, finding_id: object) -> set:
        """Every Evidence id reachable from a Finding's source and verification path."""
        finding = next((f for f in self.findings if f.get("id") == finding_id), {})
        chain: set = set()
        for hyp_id in strset(finding.get("sourceHypotheses")):
            chain |= self.hypothesis_evidence.get(hyp_id, set())
        for unit in self.units:
            for rec in rows(unit.get("reconciliations")):
                if isinstance(rec, dict) and rec.get("findingId") == finding_id:
                    chain |= strset(rec.get("evidenceRefs"))
        chain |= self.verification_new.get(finding_id, set())
        chain |= strset((self.challenge.get(finding_id) or {}).get("evidenceRefs"))
        chain |= strset((self.resolution_challenge.get(finding_id) or {}).get("evidenceRefs"))
        return chain


# --------------------------------------------------------------------------
# 0. identity & references / 1. invariant prerequisites
# --------------------------------------------------------------------------
# This checker does no form-level validation, so a missing field silently skips
# every invariant that reads it: the guard reading it becomes a live silent
# skip rather than dead defensive code. This pass checks only the fields that
# *drive* an invariant decision -- just enough to turn "silently skipped" into
# an error, without re-introducing a schema. It never validates id formats,
# path lexing, directory layout or optional-field shape.
#
# It does close the driver *enums*, because a near-miss value is not a missing
# field but a live guard that never fires: `phase: "final"` does not read as a
# wrong phase, it reads as "not FINAL", which exempts the whole record from
# every closing obligation. See the DRIVER_ENUMS comment.
def check_driver_enums_and_keys(a: Audit, r: Report) -> None:
    """Closes the value sets that invariants compare against, and requires the
    driver fields whose absence would exempt an object from those invariants."""
    def guard(path: str, value: object, key: str, where: str = "") -> None:
        allowed = DRIVER_ENUMS[key]
        if value is None:
            return
        if not isinstance(value, str):
            r.error(path, f"{where or key} must be a string, got {type(value).__name__}")
            return
        if value != value.strip():
            r.error(path, f"{value!r} has surrounding whitespace; the guard comparing it to "
                          f"{sorted(allowed)} will never match and the invariant is skipped")
            return
        if value not in allowed:
            r.error(path, f"invalid value {value!r}; must be exactly one of {sorted(allowed)}")

    def require(path: str, container: dict, field: str, key: str) -> None:
        value = container.get(field)
        if not (isinstance(value, str) and value.strip()):
            r.error(path, f"required driver field; omitting it skips every invariant that reads it "
                          f"(must be one of {sorted(DRIVER_ENUMS[key])})")
            return
        guard(path, value, key)

    # -- root and contract -------------------------------------------------
    if a.state.get("schemaVersion") != 3:
        r.error("state.json.schemaVersion",
                f"must be 3 (got {a.state.get('schemaVersion')!r}); the protocol accepts only v3 states")
    if "phase" not in a.state:
        r.error("state.json.phase", f"required driver field; without it every closing obligation "
                                    f"is skipped (must be one of {sorted(DRIVER_ENUMS['state.phase'])})")
    else:
        require("state.json.phase", a.state, "phase", "state.phase")
    guard("state.json.audit.scopeMode", a.audit.get("scopeMode"), "audit.scopeMode")
    guard("state.json.audit.executionMode", a.audit.get("executionMode"), "audit.executionMode")
    stop = a.audit.get("stop")
    if isinstance(stop, dict):
        guard("state.json.audit.stop.policy", stop.get("policy"), "audit.stop.policy")
    resolution = a.audit.get("scopeResolution")
    if isinstance(resolution, dict):
        guard("state.json.audit.scopeResolution.basis", resolution.get("basis"),
              "audit.scopeResolution.basis")
        guard("state.json.audit.scopeResolution.confidence", resolution.get("confidence"),
              "audit.scopeResolution.confidence")
    snapshot = a.audit.get("snapshot")
    if isinstance(snapshot, dict):
        guard("state.json.audit.snapshot.kind", snapshot.get("kind"), "audit.snapshot.kind")
    gates = a.audit.get("gates")
    if isinstance(gates, dict):
        for target in rows(gates.get("targets")):
            guard("state.json.audit.gates.targets", target, "audit.gates.targets[]")
        policies = gates.get("policies")
        if isinstance(policies, dict):
            for target, policy in policies.items():
                if isinstance(policy, dict) and "blockAtOrAbove" in policy:
                    guard(f"state.json.audit.gates.policies[{target}].blockAtOrAbove",
                          policy.get("blockAtOrAbove"), "audit.gates.policies[].blockAtOrAbove")

    # -- claims ------------------------------------------------------------
    for claim in a.claims:
        claim_id = claim.get("id", "unknown")
        require(f"state.json.claims[{claim_id}].obligation", claim, "obligation", "claims[].obligation")
        require(f"state.json.claims[{claim_id}].priority", claim, "priority", "claims[].priority")
        guard(f"state.json.claims[{claim_id}].sufficiency", claim.get("sufficiency"),
              "claims[].sufficiency")

    # -- units -------------------------------------------------------------
    for unit in a.units:
        unit_id = unit.get("id", "unknown")
        require(f"state.json.verificationUnits[{unit_id}].status", unit, "status",
                    "verificationUnits[].status")
        guard(f"state.json.verificationUnits[{unit_id}].isolation", unit.get("isolation"),
              "verificationUnits[].isolation")
        for index, rec in enumerate(rows(unit.get("reconciliations"))):
            if isinstance(rec, dict):
                guard(f"state.json.verificationUnits[{unit_id}].reconciliations[{index}].result",
                      rec.get("result"), "verificationUnits[].reconciliations[].result")

    # -- findings ----------------------------------------------------------
    for finding in a.findings:
        finding_id = finding.get("id", "unknown")
        for typo, intended in FINDING_KEY_TYPOS.items():
            if typo in finding:
                r.error(f"state.json.findings[{finding_id}].{typo}",
                        f"misspelled key; did you mean {intended!r}? a misspelled driver is a "
                        "driver that never arrived, not an omitted optional field")
        decision = finding.get("decision")
        if not (isinstance(decision, str) and decision.strip()):
            # Already reported by pass 1 as a missing driver; skip the enum echo.
            pass
        else:
            guard(f"state.json.findings[{finding_id}].decision", decision, "findings[].decision")
        for field in ("severity", "confidence", "disposition", "provenance"):
            guard(f"state.json.findings[{finding_id}].{field}", finding.get(field),
                  f"findings[].{field}")
        risk = finding.get("risk")
        if isinstance(risk, dict):
            guard(f"state.json.findings[{finding_id}].risk.impact", risk.get("impact"),
                  "findings[].risk.impact")
        for gate in rows(finding.get("gates")):
            if isinstance(gate, dict):
                target = gate.get("target", "?")
                guard(f"state.json.findings[{finding_id}].gates[{target}].applicability",
                      gate.get("applicability"), "findings[].gates[].applicability")

    # -- artifacts ---------------------------------------------------------
    # Both artifact kinds carry `evidence`, and _index_artifact files the
    # verification evidence into the same polarity / test-discrimination
    # indexes, so a typo there disables the Finding-level polarity checks too.
    for label, data in list(a.investigations.items()) + list(a.verifications.items()):
        for index, item in enumerate(rows(data.get("evidence"))):
            if not isinstance(item, dict):
                continue
            ev_path = f"artifact({label}).evidence[{index}]"
            for field in ("polarity", "strength", "reproducibility"):
                guard(f"{ev_path}.{field}", item.get(field), f"evidence[].{field}")
            discrimination = item.get("testDiscrimination")
            if isinstance(discrimination, dict):
                guard(f"{ev_path}.testDiscrimination.result", discrimination.get("result"),
                      "evidence[].testDiscrimination.result")
        for index, hyp in enumerate(rows(data.get("hypotheses"))):
            if not isinstance(hyp, dict):
                continue
            hyp_path = f"artifact({label}).hypotheses[{index}]"
            guard(f"{hyp_path}.result", hyp.get("result"), "investigations().hypotheses[].result")
            guard(f"{hyp_path}.recommendation", hyp.get("recommendation"),
                  "investigations().hypotheses[].recommendation")
            guard(f"{hyp_path}.disconfirmationResult", hyp.get("disconfirmationResult"),
                  "investigations().hypotheses[].disconfirmationResult")
    for finding_id, data in a.verifications.items():
        for block, keys in (
            ("challenge", ("status", "mode", "result")),
            ("resolutionChallenge", ("status",)),
        ):
            value = data.get(block)
            if not isinstance(value, dict):
                continue
            for key in keys:
                guard(f"verification({finding_id}).{block}.{key}", value.get(key),
                      f"verification().{block}.{key}")

    # -- fix workflow ------------------------------------------------------
    workflow = a.state.get("fixWorkflow")
    if isinstance(workflow, dict):
        for batch in rows(workflow.get("batches")):
            if not isinstance(batch, dict):
                continue
            batch_id = batch.get("id", "unknown")
            guard(f"state.json.fixWorkflow.batches[{batch_id}].kind", batch.get("kind"),
                  "fixWorkflow.batches[].kind")
            guard(f"state.json.fixWorkflow.batches[{batch_id}].status", batch.get("status"),
                  "fixWorkflow.batches[].status")


def check_identity_and_references(a: Audit, r: Report) -> None:
    """Every later check indexes by id. A duplicate silently overwrites, a dangling
    reference silently resolves to nothing -- both turn an invariant into a no-op."""
    for label, ids in (
        ("state.json.claims", [c.get("id") for c in a.claims]),
        ("state.json.verificationUnits", [u.get("id") for u in a.units]),
        ("state.json.findings", [f.get("id") for f in a.findings]),
        ("state.json.residualRisks", [i.get("id") for i in a.residuals]),
    ):
        for dup in sorted({i for i in ids if isinstance(i, str) and ids.count(i) > 1}):
            r.error(label, f"duplicate id {dup!r}; later entries silently overwrite earlier ones")
    claim_ids = {c.get("id") for c in a.claims}
    unit_ids = {u.get("id") for u in a.units}
    finding_ids = {f.get("id") for f in a.findings}
    residual_ids = {i.get("id") for i in a.residuals}
    for unit in a.units:
        unit_id = unit.get("id")
        ref = unit.get("claimId")
        if ref not in claim_ids:
            r.error(f"state.json.verificationUnits[{unit_id}].claimId",
                    f"unknown claim id {ref!r}; the Unit inherits no obligation and is silently unchecked")
        ref = unit.get("residualRiskId")
        if isinstance(ref, str) and ref not in residual_ids:
            r.error(f"state.json.verificationUnits[{unit_id}].residualRiskId", f"unknown residual risk {ref!r}")
    data_hypotheses: dict = {}
    for unit_id, data in a.investigations.items():
        seen: set = set()
        for hyp in rows(data.get("hypotheses")):
            if not isinstance(hyp, dict) or not isinstance(hyp.get("id"), str):
                continue
            if hyp["id"] in seen:
                r.error(f"investigations({unit_id}).hypotheses", f"duplicate hypothesis id {hyp['id']!r}")
            seen.add(hyp["id"])
            data_hypotheses.setdefault(hyp["id"], unit_id)
        ev: set = set()
        for item in rows(data.get("evidence")):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                if item["id"] in ev:
                    r.error(f"investigations({unit_id}).evidence", f"duplicate evidence id {item['id']!r}")
                ev.add(item["id"])
    for finding in a.findings:
        finding_id = finding.get("id")
        for ref in strset(finding.get("sourceHypotheses")):
            if ref not in data_hypotheses and ref not in a.hypothesis_evidence:
                r.error(f"state.json.findings[{finding_id}].sourceHypotheses",
                        f"unknown hypothesis id {ref!r}; the Finding then traces back to no Evidence")
    for unit in a.units:
        unit_id = unit.get("id")
        reconciliations = rows(unit.get("reconciliations"))
        # A Unit that has not reported cannot have reduced anything; allowing it
        # would let an unreported investigation carry conclusions.
        if reconciliations and unit.get("status") != "verified":
            r.error(f"state.json.verificationUnits[{unit_id}].reconciliations",
                    "allowed only when status=verified; an unverified Unit has no reduction to report")
        seen: set = set()
        for index, rec in enumerate(reconciliations):
            if not isinstance(rec, dict):
                continue
            path = f"state.json.verificationUnits[{unit_id}].reconciliations[{index}]"
            hyp_id = rec.get("hypothesisId")
            if hyp_id in seen:
                r.error(path, f"duplicate hypothesis reconciliation {hyp_id!r}")
            seen.add(hyp_id)
            result = rec.get("result")
            target = rec.get("findingId")
            # Each reduction carries exactly the payload its result implies; a
            # stray one is an undeclared Finding or an undeclared gap.
            if result == "FINDING":
                if isinstance(target, str) and target not in finding_ids:
                    r.error(f"{path}.findingId", f"unknown finding id {target!r}")
            elif target is not None:
                r.error(f"{path}.findingId", "allowed only when result is FINDING")
            residual_ref = rec.get("residualRiskId")
            if result == "RESIDUAL-GAP":
                if isinstance(residual_ref, str) and residual_ref not in residual_ids:
                    r.error(f"{path}.residualRiskId", f"unknown residual risk {residual_ref!r}")
                elif isinstance(residual_ref, str) and not next(
                    (i for i in a.residuals if i.get("id") == residual_ref), {}
                ).get("material"):
                    r.error(f"{path}.residualRiskId",
                            "a RESIDUAL-GAP from a material Hypothesis must map to a material residual risk")
            elif residual_ref is not None:
                r.error(f"{path}.residualRiskId", "allowed only when result is RESIDUAL-GAP")
    # Only the "does this id exist at all" diagnosis belongs here; whether the
    # referenced Unit is verified or method-compatible is check_disconfirmation's job.
    for finding_id, challenge in a.challenge.items():
        ref = challenge.get("unitId") if isinstance(challenge, dict) else None
        if isinstance(ref, str) and ref not in unit_ids:
            r.error(f"verification({finding_id}).challenge.unitId", f"unknown Verification Unit {ref!r}")
    for finding_id, resolution in a.resolution_challenge.items():
        ref = resolution.get("unitId") if isinstance(resolution, dict) else None
        if isinstance(ref, str) and ref not in unit_ids:
            r.error(f"verification({finding_id}).resolutionChallenge.unitId", f"unknown Verification Unit {ref!r}")


def check_invariant_prerequisites(a: Audit, r: Report) -> None:
    # Runs first: a near-miss driver value must be caught before any later pass
    # compares against it, or the later pass silently reads the object as exempt.
    check_driver_enums_and_keys(a, r)
    for field in FORBIDDEN_AUDIT_FIELDS:
        if field in a.audit:
            r.error(f"state.json.audit.{field}",
                    f"free-form {field} is unsupported; express risk tolerance through Gate "
                    "policies.<target>.blockAtOrAbove or an explicitly authorized Finding acceptance")
    check_identity_and_references(a, r)
    for unit in a.units:
        if unit.get("status") == "verified" and not isinstance(unit.get("method"), str):
            r.error(f"state.json.verificationUnits[{unit.get('id')}].method",
                    "a verified Unit requires a method; without it the heterogeneity, "
                    "independence and test-discrimination checks are all skipped")
    for finding in a.findings:
        finding_id = finding.get("id")
        decision = finding.get("decision")
        if not isinstance(decision, str):
            r.error(f"state.json.findings[{finding_id}].decision",
                    "a Finding requires a decision; without it every conclusion-vs-evidence "
                    "check for this Finding is skipped")
            continue
        if decision == "PENDING":
            # FINAL+PENDING is reported by check_conclusions. An unfinished
            # Finding owes no rating, and must not carry one: a rating on a
            # PENDING decision is a conclusion published before it was reached.
            for key in ("severity", "severityRationale", "confidence", "disposition"):
                if finding.get(key) is not None:
                    r.error(f"state.json.findings[{finding_id}].{key}",
                            "must be omitted while Decision is PENDING")
            continue
        if decision in RATED_DECISIONS:
            for field in ("severity", "risk", "confidence"):
                if finding.get(field) is None:
                    r.error(f"state.json.findings[{finding_id}].{field}",
                            f"required to judge a {decision} Finding; omitting it skips the "
                            "conclusion-vs-evidence check instead of satisfying it")


# --------------------------------------------------------------------------
# 2. contract fields
# --------------------------------------------------------------------------
def check_contract_fields(a: Audit, r: Report) -> None:
    """The contract decides what counts as covered; a loose contract loosens everything downstream."""
    gates = a.audit.get("gates") if isinstance(a.audit.get("gates"), dict) else {}
    requested = strset(gates.get("targets"))
    # A Gate verdict is a terminal statement; declaring one while the audit is
    # still open freezes a conclusion that the remaining work may contradict.
    if a.phase in {"ACTIVE", "SUPERSEDED"} and "decisions" in gates:
        r.error("state.json.audit.gates.decisions", f"must be omitted while phase is {a.phase}")
    # Supersession is how a frozen instance says what replaced it: required when
    # frozen, meaningless (and unreachable by the graph check) otherwise.
    if a.phase == "SUPERSEDED":
        if not isinstance(a.audit.get("supersession"), dict):
            r.error("state.json.audit.supersession", "required object while phase is SUPERSEDED")
    elif a.audit.get("supersession") is not None:
        r.error("state.json.audit.supersession", "allowed only while phase is SUPERSEDED")
    profiles = a.audit.get("objectiveProfiles")
    if isinstance(profiles, list):
        items = [p for p in profiles if isinstance(p, str)]
        # `general` keeps a profiled audit honest: a security-only or
        # fix-only profile would silently narrow what gets looked at.
        if "general" not in items:
            r.error("state.json.audit.objectiveProfiles", "must include the default profile 'general'")
        if len(set(items)) != len(items):
            r.error("state.json.audit.objectiveProfiles", "contains duplicates")
    independent = a.audit.get("independentValidationRequiredFor")
    if independent is not None:
        items = [p for p in independent if isinstance(p, str)] if isinstance(independent, list) else []
        if not isinstance(independent, list) or not independent:
            r.error("state.json.audit.independentValidationRequiredFor",
                    "must be a non-empty array when present; an empty requirement is a silent no-op")
        else:
            if "AUDIT" in items and len(items) != 1:
                r.error("state.json.audit.independentValidationRequiredFor",
                        "AUDIT cannot be combined with Gate targets")
            if len(set(items)) != len(items):
                r.error("state.json.audit.independentValidationRequiredFor", "contains duplicates")
            allowed = requested | {"AUDIT"}
            for index, value in enumerate(items):
                if value not in allowed:
                    r.error(f"state.json.audit.independentValidationRequiredFor[{index}]",
                            f"{value!r} is not a requested Gate target or 'AUDIT'")
    prior_contact = a.audit.get("priorContact")
    if prior_contact is not None:
        items = [p for p in prior_contact if isinstance(p, str)] if isinstance(prior_contact, list) else []
        if not isinstance(prior_contact, list) or not prior_contact:
            r.error("state.json.audit.priorContact", "must be a non-empty array when present")
        else:
            if len(set(items)) != len(items):
                r.error("state.json.audit.priorContact", "contains duplicates")
            for index, value in enumerate(items):
                if value not in {"implementer", "informal-verifier"}:
                    r.error(f"state.json.audit.priorContact[{index}]",
                            "must be 'implementer' or 'informal-verifier'; there is no 'none' placeholder")
    for claim in a.claims:
        claim_id = claim.get("id")
        obligation = claim.get("obligation")
        targets = strset(claim.get("gateTargets"))
        # Gate obligations cannot ride on an EXPLORATORY claim: exploration is
        # explicitly outside the completion obligation.
        if targets and obligation != "REQUIRED":
            r.error(f"state.json.claims[{claim_id}].gateTargets",
                    "only a REQUIRED Claim may carry Gate completion obligations")
        for target in targets - requested:
            r.error(f"state.json.claims[{claim_id}].gateTargets", f"target {target!r} was not requested")
        if targets and not requested:
            r.error(f"state.json.claims[{claim_id}].gateTargets", "must be omitted when no Gate was requested")
        # The X<n> id belongs to the exploration *round*, not to the Claim: a
        # Claim stays Q<n> whatever its obligation. Requiring it on the round is
        # what makes the round/Claim cross-reference mechanically checkable.
        round_ref = claim.get("explorationRound")
        if obligation == "EXPLORATORY":
            if not (isinstance(round_ref, str) and ROUND_ID_PATTERN.fullmatch(round_ref)):
                r.error(f"state.json.claims[{claim_id}].explorationRound",
                        "an EXPLORATORY Claim requires an X<n> exploration round id")
        elif round_ref is not None:
            r.error(f"state.json.claims[{claim_id}].explorationRound",
                    "only EXPLORATORY claims may set this field")


# --------------------------------------------------------------------------
# 3. snapshot binding
# --------------------------------------------------------------------------
def check_bindings(a: Audit, r: Report) -> None:
    audit_id = a.audit.get("id")
    snapshot = a.audit.get("snapshot")
    # A FINAL conclusion is a statement about one immutable identity. Without
    # one, "FINAL" only means "we stopped", and nothing can be re-checked later.
    if a.phase in {"FINAL", "SUPERSEDED"} and snapshot is None:
        r.error("state.json.audit.snapshot",
                "required in FINAL state to bind conclusions to an immutable identity; "
                "a branch name or 'current deployment' is not an identity")
    for label, data in list(a.investigations.items()) + list(a.verifications.items()):
        binding = data.get("auditBinding")
        path = f"artifact({label}).auditBinding"
        if not isinstance(binding, dict):
            r.error(path, "artifact must declare auditBinding={auditId, snapshot}")
            continue
        if "auditId" not in binding:
            r.error(f"{path}.auditId", "auditBinding must declare an explicit auditId key; a missing "
                                       "one reads as None and silently matches a state that has none")
        elif binding.get("auditId") != audit_id:
            r.error(f"{path}.auditId", "must equal the current audit id; re-take the Evidence instead of re-tagging")
        # The key must exist, not merely compare equal: while the audit is still
        # ACTIVE the state snapshot is legitimately null, and `None == None`
        # would let an artifact that never declared a snapshot pass as bound.
        # Such an artifact can be replayed into any later instance unchallenged.
        if "snapshot" not in binding:
            r.error(f"{path}.snapshot", "auditBinding must declare an explicit snapshot key (null is a "
                                        "valid value while the identity is undetermined, absence is not); "
                                        "an omitted key reads as None and silently matches a null snapshot")
        elif binding.get("snapshot") != snapshot:
            r.error(f"{path}.snapshot", "must exactly equal the current audit snapshot")
    # An artifact is filed under a Unit by path, but it also declares which Unit
    # it belongs to. If those disagree, Evidence can be silently filed elsewhere.
    for unit_id, data in a.investigations.items():
        unit = a.unit(unit_id)
        for key in ("unitId", "claimId", "method"):
            declared = data.get(key)
            if isinstance(declared, str) and unit.get(key) is not None and declared != unit.get(key):
                r.error(f"investigations({unit_id}).{key}",
                        f"must equal verificationUnits[{unit_id}].{key} ({unit.get(key)!r}); "
                        "the artifact is filed under a Unit it does not belong to")
    for finding_id, data in a.verifications.items():
        if isinstance(data.get("findingId"), str) and data["findingId"] != finding_id:
            r.error(f"verification({finding_id}).findingId",
                    f"must equal the Finding it is filed under ({finding_id!r})")


# --------------------------------------------------------------------------
# 4. evidence graph
# --------------------------------------------------------------------------
def check_evidence_graph(a: Audit, r: Report) -> None:
    for unit in a.units:
        unit_id = unit.get("id")
        declared = {rec.get("hypothesisId") for rec in rows(unit.get("reconciliations")) if isinstance(rec, dict)}
        observed = a.unit_hypotheses.get(unit_id, set())
        if declared != observed:
            r.error(f"state.json.verificationUnits[{unit_id}].reconciliations",
                    "must reconcile every investigation hypothesis exactly once "
                    f"(missing={sorted(observed - declared)}, extra={sorted(declared - observed)})")
        own_evidence = a.unit_evidence.get(unit_id, set())
        for index, rec in enumerate(rows(unit.get("reconciliations"))):
            if not isinstance(rec, dict):
                continue
            path = f"state.json.verificationUnits[{unit_id}].reconciliations[{index}]"
            result = rec.get("result")
            refs = strset(rec.get("evidenceRefs"))
            for ref in refs - own_evidence:
                r.error(f"{path}.evidenceRefs", f"{ref!r} is not Evidence produced by this Unit")
            wanted = RECONCILIATION_EVIDENCE.get(result)
            if wanted and not {ref for ref in refs if a.evidence_polarity.get(ref) == wanted}:
                r.error(f"{path}.evidenceRefs", f"{result} requires at least one {wanted} Evidence")
    for finding in a.findings:
        finding_id = finding.get("id")
        chain = a.finding_chain(finding_id)
        for key, wanted in POLARITY_FOR.items():
            for ref in strset(finding.get(key)):
                if ref not in chain:
                    r.error(f"state.json.findings[{finding_id}].{key}",
                            f"{ref!r} is not part of this Finding's source or verification chain")
                elif a.evidence_polarity.get(ref) not in (wanted, None):
                    r.error(f"state.json.findings[{finding_id}].{key}",
                            f"{ref!r} has polarity {a.evidence_polarity.get(ref)!r}, expected {wanted}")
        expected_sources = {
            rec.get("hypothesisId")
            for unit in a.units
            for rec in rows(unit.get("reconciliations"))
            if isinstance(rec, dict) and rec.get("findingId") == finding_id
        }
        if strset(finding.get("sourceHypotheses")) != expected_sources:
            r.error(f"state.json.findings[{finding_id}].sourceHypotheses",
                    "must exactly match the hypotheses reconciled as FINDING")
        for ref in a.verification_checked.get(finding_id, set()) - chain:
            r.error(f"state.json.findings[{finding_id}].verificationFile",
                    f"checkedEvidence {ref!r} is not part of this Finding's investigation chain")
        for ref in a.verification_new.get(finding_id, set()):
            consumed = any(ref in strset(finding.get(key)) for key in POLARITY_FOR)
            if not consumed:
                r.error(f"state.json.findings[{finding_id}]",
                        f"new verification Evidence {ref!r} is not consumed by any Finding evidence field")
    for unit_id, data in a.investigations.items():
        summary = data.get("coverageSummary")
        behaviors = rows(summary.get("verifiedBehaviors")) if isinstance(summary, dict) else []
        for index, behavior in enumerate(behaviors):
            path = f"investigations({unit_id}).coverageSummary.verifiedBehaviors[{index}]"
            if not isinstance(behavior, dict):
                # A bare string is unverifiable: it names a behavior with nothing
                # to re-check it against, and is the v2 shape.
                r.error(path, "must be a {behavior, evidenceRefs} object; a bare string "
                              "claims a verified behavior with nothing to re-check it against")
                continue
            if not (isinstance(behavior.get("behavior"), str) and behavior["behavior"].strip()):
                r.error(f"{path}.behavior", "must name the behavior that was verified")
            for ref in strset(behavior.get("evidenceRefs")) - a.unit_evidence.get(unit_id, set()):
                r.error(f"{path}.evidenceRefs", f"{ref!r} is not Evidence of this artifact")


# --------------------------------------------------------------------------
# 5. disconfirmation
# --------------------------------------------------------------------------
def check_disconfirmation(a: Audit, r: Report) -> None:
    # Strength-vs-reproducibility is a property of the Evidence, not of any
    # hypothesis: it used to sit inside the hypotheses loop, so an artifact
    # with `hypotheses: []` -- every clean Unit -- skipped it entirely. It is
    # also checked on verification artifacts, whose `F<n>-E<m>` Evidence feeds
    # the same polarity and test-discrimination indexes as an investigation.
    for label, data in list(a.investigations.items()) + list(a.verifications.items()):
        for index, item in enumerate(rows(data.get("evidence"))):
            if (isinstance(item, dict) and item.get("strength") in {"ES3", "ES4"}
                    and item.get("reproducibility") not in {"repeatable", "conditional"}):
                r.error(f"artifact({label}).evidence[{index}]", f"{item.get('id')} is {item.get('strength')} "
                        "but not repeatable/conditional; a single observation cannot carry that strength")
    for unit_id, data in a.investigations.items():
        for index, hyp in enumerate(rows(data.get("hypotheses"))):
            if not isinstance(hyp, dict):
                continue
            path = f"investigations({unit_id}).hypotheses[{index}]"
            result, recommendation = hyp.get("result"), hyp.get("recommendation")
            pairs = {"supported": {"promote-to-finding"}, "refuted": {"close"},
                     "unresolved": {"promote-to-finding", "residual-gap"}}
            if result in pairs and recommendation not in pairs[result]:
                r.error(f"{path}.recommendation", f"result={result} requires one of {sorted(pairs[result])}")
            if hyp.get("disconfirmationResult") == "counter-supported" and result != "refuted":
                r.error(f"{path}.result", "a counter-supported hypothesis must be closed (result=refuted)")
            refs = strset(hyp.get("evidenceRefs"))
            if result == "supported" and not {ref for ref in refs if a.evidence_polarity.get(ref) == "supports"}:
                r.error(f"{path}.evidenceRefs", "supported requires at least one supports Evidence")
            if result == "refuted" and not {ref for ref in refs if a.evidence_polarity.get(ref) == "refutes"}:
                r.error(f"{path}.evidenceRefs", "refuted requires at least one refutes Evidence")
    for finding in a.findings:
        finding_id = finding.get("id")
        severity, decision, disposition = finding.get("severity"), finding.get("decision"), finding.get("disposition")
        primary_method = finding.get("verificationMethod")
        declared_method = a.verification_method.get(finding_id)
        if isinstance(declared_method, str) and isinstance(primary_method, str) and declared_method != primary_method:
            r.error(f"verification({finding_id}).method",
                    f"must equal the Finding's verificationMethod {primary_method!r}; the challenge "
                    "'method must differ' checks use it as the baseline and would otherwise be bypassable")
        challenge = a.challenge.get(finding_id)
        if challenge is None:
            if severity in {"Critical", "High"} and decision in {"CONFIRMED", "CONDITIONAL", "NEEDS-DECISION"}:
                r.error(f"state.json.findings[{finding_id}].verificationFile",
                        "Critical/High Finding requires a recorded second challenge")
            if disposition == "RESOLVED-VERIFIED" and severity in {"Critical", "High"}:
                r.error(f"state.json.findings[{finding_id}].verificationFile",
                        "Critical/High RESOLVED-VERIFIED requires a resolutionChallenge")
            continue
        path = f"verification({finding_id}).challenge"
        status = challenge.get("status")
        # Every GAP check lives in this block: a GAP challenge carries a reason
        # and nothing else, so leaving any branch of it below an early `continue`
        # silently downgrades "gap explained" to "gap declared".
        if status == "GAP":
            if decision != "CONDITIONAL":
                r.error(f"{path}.status", "GAP is only allowed on a CONDITIONAL Finding")
            for key in ("mode", "unitId", "method", "evidenceRefs", "result"):
                if key in challenge:
                    r.error(f"{path}.{key}", "must be omitted when status is GAP")
            if not (isinstance(challenge.get("gapReason"), str) and challenge["gapReason"].strip()):
                r.error(f"{path}.gapReason", "must record why the challenge could not be completed")
            continue
        if status != "COMPLETED":
            r.error(f"{path}.status", "challenge must be COMPLETED or GAP")
            continue
        mode = challenge.get("mode")
        challenge_refs = strset(challenge.get("evidenceRefs"))
        polarities = {a.evidence_polarity.get(ref) for ref in challenge_refs}
        if challenge.get("result") == "counter-refuted" and "supports" not in polarities:
            r.error(f"{path}.result", "counter-refuted challenge requires supporting Evidence")
        if challenge.get("result") == "counter-supported" and "refutes" not in polarities:
            r.error(f"{path}.result", "counter-supported challenge requires refuting Evidence")
        if decision in {"CONFIRMED", "NEEDS-DECISION"} and challenge.get("result") != "counter-refuted":
            r.error(f"{path}.result", f"{decision} requires a completed counter-refuted challenge")
        if decision == "CONDITIONAL" and challenge.get("result") == "counter-supported":
            r.error(f"{path}.result", "counter-supported challenge closes or narrows the current Finding")
        if mode == "HETEROGENEOUS-METHOD":
            unit = a.unit(challenge.get("unitId"))
            if unit.get("status") != "verified":
                r.error(f"{path}.unitId", "heterogeneous challenge must reference a verified Unit")
            # A challenge drawn from an unrelated Claim is a second opinion on
            # something else; it cannot rebut this Finding's evidence.
            source_claims = a.finding_source_claims(finding_id)
            if unit.get("claimId") not in source_claims:
                r.error(f"{path}.unitId",
                        "heterogeneous challenge Unit must verify a Claim that produced this Finding")
            if challenge.get("method") != unit.get("method"):
                r.error(f"{path}.method", "heterogeneous challenge method must equal its Unit method")
            if challenge.get("method") == primary_method:
                r.error(f"{path}.method", "heterogeneous challenge method must differ from the primary verification method")
            for ref in challenge_refs - a.unit_evidence.get(unit.get("id"), set()):
                r.error(f"{path}.evidenceRefs", f"{ref!r} is not Evidence of the challenged Unit")
        elif "unitId" in challenge:
            r.error(f"{path}.unitId", "allowed only for HETEROGENEOUS-METHOD")
        # A COMPLETED challenge asserts evidence; a GAP one explains its absence.
        # Carrying both lets a gap be dressed up as a completed challenge.
        # Reaching here means status == COMPLETED: the GAP path returns above.
        if "gapReason" in challenge:
            r.error(f"{path}.gapReason", "must be omitted when status is COMPLETED")
        if mode == "EQUIVALENT-DIRECT-DISCONFIRMATION":
            for ref in challenge_refs - a.verification_new.get(finding_id, set()):
                r.error(f"{path}.evidenceRefs", f"{ref!r} must be new Evidence from this verification file")
        resolution = a.resolution_challenge.get(finding_id)
        if resolution is not None:
            if disposition != "RESOLVED-VERIFIED":
                r.error(f"verification({finding_id}).resolutionChallenge",
                        "allowed only for RESOLVED-VERIFIED")
            elif resolution.get("status") != "COMPLETED":
                r.error(f"verification({finding_id}).resolutionChallenge.status",
                        "must be COMPLETED; there is no GAP for a resolution challenge")
            else:
                path = f"verification({finding_id}).resolutionChallenge"
                unit = a.unit(resolution.get("unitId"))
                if unit.get("status") != "verified":
                    r.error(f"{path}.unitId", "resolutionChallenge must reference a verified Unit")
                if unit.get("claimId") not in a.finding_source_claims(finding_id):
                    r.error(f"{path}.unitId",
                            "resolutionChallenge Unit must verify a Claim that produced this Finding")
                if resolution.get("method") != unit.get("method"):
                    r.error(f"{path}.method", "resolutionChallenge method must equal its Verification Unit method")
                if resolution.get("method") == primary_method:
                    r.error(f"{path}.method", "resolutionChallenge method must differ from the primary verification method")
                if not strset(resolution.get("evidenceRefs")) & strset(finding.get("resolutionEvidence")):
                    r.error(f"{path}.evidenceRefs", "must be cited by the Finding's resolutionEvidence")
                if "gapReason" in resolution:
                    r.error(f"{path}.gapReason",
                            "must be omitted; there is no GAP state for a resolution challenge")


# --------------------------------------------------------------------------
# 6. conclusion vs evidence
# --------------------------------------------------------------------------
def check_conclusions(a: Audit, r: Report) -> None:
    if a.phase == "FINAL":
        for finding in a.findings:
            if finding.get("decision") == "PENDING":
                r.error(f"state.json.findings[{finding.get('id')}].decision", "FINAL cannot keep a PENDING decision")
        # Closing on zero Claims closes on nothing. Every other FINAL obligation
        # below lives inside a `for claim in a.claims` loop, so an empty list
        # walks straight through them and the audit reports PASS having verified
        # no Claim at all. A Gate does not rescue this: with no REQUIRED Claim
        # there is nothing to derive a Gate from either, so the check applies
        # whether or not Gates were requested -- it is a floor on the record,
        # not a Gate rule.
        if not any(claim.get("obligation") == "REQUIRED" for claim in a.claims):
            r.error("state.json.claims", "a FINAL audit requires at least one REQUIRED Claim; "
                                         "non-empty objectives cannot be closed by zero verified "
                                         "objects -- keep the audit ACTIVE until a decidable Claim exists")
        # In a Gate-driven audit, a Critical/High challenge GAP mechanically drives
        # the Gate to INCOMPLETE unless explicitly accepted per-target. Without a
        # Gate, that safety net is absent: an audit could otherwise declare FINAL
        # while leaving a critical verification hole completely unacknowledged.
        # Closing requires keeping the audit ACTIVE, completing the challenge,
        # or defining a Gate with an explicit per-target risk acceptance.
        gates = a.audit.get("gates") if isinstance(a.audit.get("gates"), dict) else {}
        requested_gates = strset(gates.get("targets"))
        if not requested_gates:
            for finding in a.findings:
                finding_id = finding.get("id")
                severity = finding.get("severity")
                if severity in {"Critical", "High"}:
                    challenge = a.challenge.get(finding_id, {})
                    if challenge.get("status") == "GAP":
                        r.error(
                            f"state.json.findings[{finding_id}].verificationFile",
                            f"a FINAL audit without Gates cannot close with a {severity} challenge GAP; "
                            "keep the audit ACTIVE, complete the challenge, or request a Gate with explicit risk acceptance"
                        )
    residual_by_id = {item.get("id"): item for item in a.residuals}
    # A verified Unit that produced no DIRECT Evidence has verified nothing, and
    # a test that merely passes does not discriminate between safe and failing.
    # (Artifacts that failed to load are already reported by Audit._read.)
    for unit in a.units:
        unit_id = unit.get("id")
        if unit.get("status") != "verified" or unit_id not in a.investigations:
            continue
        evidence = a.unit_evidence.get(unit_id, set())
        if not evidence:
            r.error(f"state.json.verificationUnits[{unit_id}]",
                    "a verified Unit requires at least one DIRECT Evidence")
            continue
        if unit.get("method") == "test-discrimination" and not any(
            a.test_discrimination_results.get(ref) == "YES" for ref in evidence
        ):
            r.error(f"state.json.verificationUnits[{unit_id}]",
                    "a verified test-discrimination Unit requires at least one Evidence with "
                    "testDiscrimination.result=YES; passing tests alone are ES1, not verification")
    for unit in a.units:
        if a.phase == "FINAL" and unit.get("status") != "verified":
            claim = next((c for c in a.claims if c.get("id") == unit.get("claimId")), {})
            if claim.get("obligation") == "REQUIRED":
                ref = unit.get("residualRiskId")
                if not isinstance(ref, str):
                    r.error(f"state.json.verificationUnits[{unit.get('id')}]",
                            "FINAL unfinished REQUIRED Unit must map to a residual risk")
                elif not residual_by_id.get(ref, {}).get("material"):
                    r.error(f"state.json.verificationUnits[{unit.get('id')}].residualRiskId",
                            "must reference a material residual risk")
    for claim in a.claims:
        claim_id = claim.get("id")
        priority = claim.get("priority")
        discrimination = claim.get("discrimination") if isinstance(claim.get("discrimination"), dict) else {}
        # A discrimination plan is what makes a Claim decidable at all. Without
        # one, "verified" only means "someone looked", not "the claim was tested".
        if priority == "highest":
            required_plan = ("safePrediction", "failurePrediction", "discriminatingObservation", "sufficiencyCriterion")
        elif priority == "high":
            required_plan = ("discriminatingObservation", "sufficiencyCriterion")
        else:
            required_plan = ()
        for key in required_plan:
            value = discrimination.get(key)
            if not (isinstance(value, str) and value.strip()):
                r.error(f"state.json.claims[{claim_id}].discrimination.{key}", f"required for priority={priority}")
        if required_plan and a.phase == "FINAL" and claim.get("sufficiency") is None:
            r.error(f"state.json.claims[{claim_id}].sufficiency",
                    f"FINAL requires a finalized sufficiency for a {priority} Claim")
        # A REQUIRED Claim with no Unit is a completion obligation nobody
        # performed; closing on it would be closing on nothing.
        if a.phase == "FINAL" and claim.get("obligation") == "REQUIRED" and not a.units_by_claim(claim_id):
            r.error(f"state.json.claims[{claim_id}]",
                    "FINAL REQUIRED Claim requires at least one Verification Unit")
        if priority == "normal" and claim.get("sufficiency") is not None:
            r.error(f"state.json.claims[{claim_id}].sufficiency", "normal claim must omit sufficiency")
        if a.phase != "FINAL" or claim.get("sufficiency") != "MET":
            continue
        claim_units = a.units_by_claim(claim_id)
        verified = [u for u in claim_units if u.get("status") == "verified"]
        path = f"state.json.claims[{claim_id}].sufficiency"
        if not verified:
            r.error(path, "MET requires at least one verified Verification Unit")
        if claim.get("obligation") == "REQUIRED" and any(u.get("status") != "verified" for u in claim_units):
            r.error(path, "MET requires every Unit inherited by a REQUIRED Claim to be verified")
        if not {ref for u in verified for ref in a.unit_evidence.get(u.get("id"), set())}:
            r.error(path, "MET requires DIRECT Evidence from a verified Verification Unit")
        if claim.get("priority") == "highest" and len(
            {u.get("method") for u in verified if isinstance(u.get("method"), str)}
        ) < 2:
            r.error(path, "MET for a highest Claim requires two verified heterogeneous methods")
    for finding in a.findings:
        finding_id = finding.get("id")
        decision, severity, risk = finding.get("decision"), finding.get("severity"), finding.get("risk")
        new_evidence = a.verification_new.get(finding_id, set())
        if finding.get("disposition") is not None and decision != "CONFIRMED":
            r.error(f"state.json.findings[{finding_id}].disposition",
                    "explicit disposition is allowed only for CONFIRMED findings")
        if decision == "REJECTED":
            if not new_evidence & strset(finding.get("refutingEvidence")):
                r.error(f"state.json.findings[{finding_id}].refutingEvidence",
                        "REJECTED requires new refuting Evidence from its verification file")
            # A rejected risk was never established: it carries no rating, no
            # remediation and no deviation rationale.
            for key in ("risk", "severity", "severityRationale", "confidence"):
                if finding.get(key) is not None:
                    r.error(f"state.json.findings[{finding_id}].{key}",
                            "must be omitted for a REJECTED Finding; a rejected risk has no rating")
            continue
        # The Finding-level disconfirmation record is where "I looked for the
        # strongest counter-evidence" is attested; the verification challenge is
        # a second, later check. Both are required, and they are not the same.
        disconfirmation = finding.get("disconfirmation")
        if isinstance(disconfirmation, dict):
            result = disconfirmation.get("result")
            if decision in {"CONFIRMED", "NEEDS-DECISION"} and result != "counter-refuted":
                r.error(f"state.json.findings[{finding_id}].disconfirmation.result",
                        f"{decision} requires counter-refuted disconfirmation")
            if decision == "CONDITIONAL" and result == "counter-supported":
                r.error(f"state.json.findings[{finding_id}].disconfirmation.result",
                        "counter-supported closes or narrows the current Finding; "
                        "rebuild it before using CONDITIONAL")
        elif decision in {"CONFIRMED", "NEEDS-DECISION", "CONDITIONAL"}:
            r.error(f"state.json.findings[{finding_id}].disconfirmation",
                    f"{decision} requires a recorded disconfirmation attempt; without it the "
                    "disconfirmation obligation cannot be checked and silently passes")
        # Provenance and its evidence are a pair: neither may stand alone.
        if finding.get("provenance") is None and finding.get("provenanceEvidence"):
            r.error(f"state.json.findings[{finding_id}].provenanceEvidence",
                    "allowed only when provenance is present")
        if decision in {"CONFIRMED", "NEEDS-DECISION"} and not new_evidence & strset(finding.get("supportingEvidence")):
            r.error(f"state.json.findings[{finding_id}].supportingEvidence",
                    f"{decision} requires new supporting Evidence from its verification file")
        if finding.get("disposition") == "RESOLVED-VERIFIED" and not new_evidence & strset(finding.get("resolutionEvidence")):
            r.error(f"state.json.findings[{finding_id}].resolutionEvidence",
                    "RESOLVED-VERIFIED requires new resolution Evidence from its verification file")
        # A missing or unusable risk must not silently skip the closed mapping:
        # "drop the risk field" would otherwise be a way to rate any severity.
        if severity in SEVERITY_RANK:
            if not isinstance(risk, dict) or risk.get("impact") not in SEVERITY_RANK:
                r.error(f"state.json.findings[{finding_id}].risk",
                        "a rated severity requires risk.impact from the Impact baseline; "
                        "the closed Severity/Impact mapping cannot be skipped by omitting risk")
            else:
                allowed = permitted_severities(risk)
                if severity not in allowed:
                    r.error(f"state.json.findings[{finding_id}].severity",
                            f"severity {severity} is outside the closed Impact mapping {sorted(allowed)}")
                # Every deviation from the baseline must be argued; an argued
                # non-deviation is a contradiction.
                rationale = finding.get("severityRationale")
                if severity != risk["impact"]:
                    if not (isinstance(rationale, str) and rationale.strip()):
                        r.error(f"state.json.findings[{finding_id}].severityRationale",
                                f"severity {severity} deviates from impact {risk['impact']} and requires a rationale")
                elif rationale is not None:
                    r.error(f"state.json.findings[{finding_id}].severityRationale",
                            "allowed only when severity differs from risk.impact")
        if decision == "CONFIRMED" and finding.get("confidence") not in {"High", "Very-High"}:
            r.error(f"state.json.findings[{finding_id}].confidence",
                    "CONFIRMED requires High or Very-High confidence")
        if finding.get("disposition") == "RESOLVED-VERIFIED":
            gates = finding.get("gates")
            if isinstance(gates, dict):
                for target, gate in gates.items():
                    if isinstance(gate, dict) and gate.get("applicability") != "DOES-NOT-APPLY":
                        r.error(f"state.json.findings[{finding_id}].gates.{target}.applicability",
                                "RESOLVED-VERIFIED requires DOES-NOT-APPLY for every requested Gate")
        finding_gates = finding.get("gates")
        for target, gate in (finding_gates.items() if isinstance(finding_gates, dict) else []):
            if not isinstance(gate, dict):
                continue
            path = f"state.json.findings[{finding_id}].gates.{target}"
            if gate.get("treatment") == "ACCEPTED" and (decision != "CONFIRMED" or gate.get("applicability") != "APPLIES"):
                r.error(f"{path}.treatment", "ACCEPTED requires CONFIRMED + APPLIES")
            authorization = gate.get("authorization")
            if isinstance(authorization, dict):
                check_authorization(a, r, authorization, f"{path}.authorization", gate.get("treatment"), target)
        if finding.get("disposition") == "ACCEPTED-RISK":
            authorization = finding.get("riskAcceptanceAuthorization")
            if isinstance(authorization, dict):
                check_authorization(a, r, authorization, f"state.json.findings[{finding_id}].riskAcceptanceAuthorization",
                                    "ACCEPTED-RISK", None)


# --------------------------------------------------------------------------
# 11. risk-acceptance binding
# --------------------------------------------------------------------------
def check_authorization(a: Audit, r: Report, value: dict, path: str, treatment: object, target: object) -> None:
    """A risk acceptance is bound to one audit instance, snapshot and Gate."""
    if treatment not in {"ACCEPTED", "ACCEPTED-RISK"}:
        r.error(path, "allowed only with an accepted risk")
        return
    if not isinstance(value.get("text"), str) or not value["text"].strip():
        r.error(f"{path}.text", "must record what was authorized")
    if value.get("auditId") != a.audit.get("id"):
        r.error(f"{path}.auditId", "must equal the current audit id; acceptance cannot be replayed across instances")
    if value.get("snapshot") != a.audit.get("snapshot"):
        r.error(f"{path}.snapshot", "must exactly equal the current audit snapshot")
    if target is None:
        if "target" in value:
            r.error(f"{path}.target", "must be omitted for audit-wide risk acceptance")
    elif value.get("target") != target:
        r.error(f"{path}.target", f"must equal Gate target {target!r}")


# --------------------------------------------------------------------------
# 7. finding-gate binding
# --------------------------------------------------------------------------
def check_finding_gates(a: Audit, r: Report) -> None:
    """Gate applicability is an evidence claim, not an opinion about a Finding."""
    gates = a.audit.get("gates") if isinstance(a.audit.get("gates"), dict) else {}
    requested = strset(gates.get("targets"))
    for finding in a.findings:
        finding_id = finding.get("id")
        decision = finding.get("decision")
        finding_gates = finding.get("gates")
        if not isinstance(finding_gates, dict):
            if a.phase == "FINAL" and requested and decision != "REJECTED":
                r.error(f"state.json.findings[{finding_id}].gates",
                        "required for every FINAL non-REJECTED Finding when Gates exist")
            continue
        if not requested:
            r.error(f"state.json.findings[{finding_id}].gates", "must be omitted when no Gate was requested")
            continue
        if a.phase == "FINAL" and decision != "REJECTED" and set(finding_gates) != requested:
            r.error(f"state.json.findings[{finding_id}].gates",
                    "FINAL non-REJECTED Finding must cover every requested Gate; "
                    f"missing={sorted(requested - set(finding_gates))}")
        # Only Evidence already claimed by this Finding may back its Gate stance;
        # free-floating Evidence would let applicability escape the Finding's record.
        claimed: set = set()
        for key in POLARITY_FOR:
            claimed |= strset(finding.get(key))
        resolution = strset(finding.get("resolutionEvidence"))
        for target, gate in finding_gates.items():
            path = f"state.json.findings[{finding_id}].gates.{target}"
            if target not in requested:
                r.error(path, "target was not requested")
                continue
            if not isinstance(gate, dict):
                continue
            refs = strset(gate.get("evidenceRefs"))
            for ref in refs - claimed:
                r.error(f"{path}.evidenceRefs", f"{ref!r} is not linked to Finding {finding_id}")
            polarities = {a.evidence_polarity.get(ref) for ref in refs & claimed}
            applicability = gate.get("applicability")
            if applicability == "APPLIES" and not polarities & {"supports", "context"}:
                r.error(f"{path}.evidenceRefs",
                        "APPLIES requires supporting or contextual current-applicability Evidence")
            if applicability == "DOES-NOT-APPLY" and not polarities & {"refutes", "context"}:
                r.error(f"{path}.evidenceRefs",
                        "DOES-NOT-APPLY requires refuting or contextual current-state Evidence")
            if finding.get("disposition") == "RESOLVED-VERIFIED" and not refs & resolution:
                r.error(f"{path}.evidenceRefs", "RESOLVED-VERIFIED applicability must cite resolutionEvidence")
        # An audit-wide acceptance is not available once a Gate exists: the Gate
        # is decided per target, so the acceptance must be too.
        if finding.get("disposition") == "ACCEPTED-RISK" and requested:
            r.error(f"state.json.findings[{finding_id}].disposition",
                    "global ACCEPTED-RISK is allowed only when no Gate exists; use per-target treatment")


# --------------------------------------------------------------------------
# 8. Gate derivation
# --------------------------------------------------------------------------
def derive_gate(a: Audit, target: str) -> tuple:
    gates = a.audit.get("gates") if isinstance(a.audit.get("gates"), dict) else {}
    policies = gates.get("policies") if isinstance(gates.get("policies"), dict) else {}
    threshold = policies.get(target, {}).get("blockAtOrAbove", "High") if isinstance(policies.get(target), dict) else "High"
    threshold_rank = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}.get(threshold, 3)
    independent_required = strset(a.audit.get("independentValidationRequiredFor"))
    blocked, incomplete, conditional = [], [], []
    coverage = a.audit.get("scopeCoverage")
    if isinstance(coverage, dict):
        declared = strset(coverage.get("declaredMembers"))
        completed = strset(coverage.get("completedMembers"))
        excluded = {item.get("member") for item in rows(coverage.get("excludedMembers")) if isinstance(item, dict)}
        if declared - completed - excluded or not completed:
            incomplete.append("EXHAUSTIVE-COVERAGE-GAP")
    highest_for_audit = [c for c in a.claims if c.get("priority") == "highest"]
    scoped = [c for c in a.claims if c.get("obligation") == "REQUIRED" and target in strset(c.get("gateTargets"))]
    if not scoped:
        incomplete.append("REQUIRED-COVERAGE-GAP")
    if "AUDIT" in independent_required:
        if not highest_for_audit:
            incomplete.append("INDEPENDENT-VALIDATION-GAP")
        for claim in highest_for_audit:
            isolated = [u for u in a.units_by_claim(claim.get("id"))
                        if u.get("status") == "verified" and u.get("isolation") == "ISOLATED"]
            if len({u.get("method") for u in isolated}) < 2 or len({u.get("executor") for u in isolated}) < 2:
                incomplete.append(f"{claim.get('id')}: audit-wide independent validation incomplete")
    if target in independent_required and not [
        c for c in highest_for_audit if target in strset(c.get("gateTargets"))
    ]:
        incomplete.append("INDEPENDENT-VALIDATION-GAP")
    for claim in a.claims:
        claim_id = claim.get("id")
        if claim.get("obligation") != "REQUIRED" or target not in strset(claim.get("gateTargets")):
            continue
        claim_units = a.units_by_claim(claim_id)
        if not claim_units or any(u.get("status") != "verified" for u in claim_units):
            incomplete.append(f"{claim_id}: required verification incomplete")
        if claim.get("priority") in {"highest", "high"} and claim.get("sufficiency") != "MET":
            incomplete.append(f"{claim_id}: evidence sufficiency not met")
        if claim.get("priority") == "highest":
            verified = [u for u in claim_units if u.get("status") == "verified"]
            if len({u.get("method") for u in verified if isinstance(u.get("method"), str)}) < 2:
                incomplete.append(f"{claim_id}: heterogeneous verification incomplete")
            if target in independent_required:
                isolated = [u for u in verified if u.get("isolation") == "ISOLATED"]
                if len({u.get("method") for u in isolated}) < 2 or len({u.get("executor") for u in isolated}) < 2:
                    incomplete.append(f"{claim_id}: required independent validation incomplete")
    for finding in a.findings:
        if finding.get("decision") == "REJECTED":
            continue
        gate = (finding.get("gates") or {}).get(target) if isinstance(finding.get("gates"), dict) else None
        gate = gate if isinstance(gate, dict) else {}
        applicability = gate.get("applicability")
        finding_id = finding.get("id")
        severity_rank = SEVERITY_RANK.get(finding.get("severity"), 0) if isinstance(finding.get("severity"), str) else 0
        if applicability not in {"APPLIES", "DOES-NOT-APPLY", "UNRESOLVED"}:
            incomplete.append(f"{finding_id}: Gate applicability missing or invalid")
            continue
        decision = finding.get("decision")
        if decision == "PENDING" and applicability != "DOES-NOT-APPLY":
            incomplete.append(f"{finding_id}: decision pending")
            continue
        if applicability == "UNRESOLVED":
            (incomplete if severity_rank >= threshold_rank else conditional).append(
                f"{finding_id}: {'material' if severity_rank >= threshold_rank else 'non-blocking'} Gate applicability unresolved")
            continue
        if applicability != "APPLIES":
            continue
        if finding.get("disposition") == "RESOLVED-VERIFIED" or gate.get("treatment") == "ACCEPTED":
            continue
        if decision in {"CONDITIONAL", "NEEDS-DECISION"} and severity_rank >= threshold_rank:
            incomplete.append(f"{finding_id}: material decision/evidence gap")
        elif decision == "CONFIRMED" and severity_rank >= threshold_rank:
            blocked.append(f"{finding_id}: confirmed {finding.get('severity')} risk")
        elif decision in {"CONFIRMED", "CONDITIONAL", "NEEDS-DECISION"}:
            conditional.append(f"{finding_id}: non-blocking condition")
    for item in a.residuals:
        if target in strset(item.get("affectsGates")):
            (incomplete if item.get("material") else conditional).append(f"{item.get('id')}: residual risk")
    if blocked:
        return "BLOCKED", blocked
    if incomplete:
        return "INCOMPLETE", incomplete
    if conditional:
        return "READY-WITH-CONDITIONS", conditional
    return "READY", ["ALL-REQUIRED-INPUTS-SATISFIED"]


def check_gates(a: Audit, r: Report) -> None:
    gates = a.audit.get("gates") if isinstance(a.audit.get("gates"), dict) else {}
    requested = strset(gates.get("targets"))
    if not requested:
        return
    decisions = gates.get("decisions") if isinstance(gates.get("decisions"), dict) else {}
    if a.phase == "FINAL":
        if set(decisions) != requested:
            r.error("state.json.audit.gates.decisions", "FINAL requires one decision for every requested Gate")
        live_ids = {c.get("id") for c in a.claims} | {f.get("id") for f in a.findings} | {i.get("id") for i in a.residuals}
        for target in requested:
            expected, reasons = derive_gate(a, target)
            record = decisions.get(target) if isinstance(decisions.get(target), dict) else {}
            actual = record.get("result")
            if isinstance(actual, str) and actual != expected:
                r.error(f"state.json.audit.gates.decisions.{target}.result",
                        f"declared {actual}, but state derives {expected}")
            basis = [entry for entry in rows(record.get("basis")) if isinstance(entry, str)]
            decisive = {reason if reason in DECISIVE_TOKENS else reason.split(":", 1)[0] for reason in reasons}
            for entry in basis:
                if entry not in live_ids and entry not in DECISIVE_TOKENS:
                    r.error(f"state.json.audit.gates.decisions.{target}.basis", f"unknown id/token {entry!r}")
                elif entry not in decisive:
                    r.error(f"state.json.audit.gates.decisions.{target}.basis",
                            f"{entry!r} does not determine the derived {expected} result")
            if decisive and not decisive.intersection(basis):
                r.error(f"state.json.audit.gates.decisions.{target}.basis",
                        f"must cite at least one decisive id/token: {sorted(decisive)}")


# --------------------------------------------------------------------------
# 9. fix-batch freshness
# --------------------------------------------------------------------------
def check_fix_workflow(a: Audit, r: Report) -> None:
    workflow = a.state.get("fixWorkflow")
    if not isinstance(workflow, dict):
        return
    if a.audit.get("executionMode") != "audit-and-fix":
        r.error("state.json.fixWorkflow", "allowed only when executionMode=audit-and-fix")
        return
    generation = workflow.get("generation")
    batches = [item for item in rows(workflow.get("batches")) if isinstance(item, dict)]
    batch_by_id = {item.get("id"): item for item in batches}
    for batch in batches:
        batch_id = batch.get("id")
        if batch.get("status") == "PASSED":
            if batch.get("validatedGeneration") != generation:
                r.error(f"state.json.fixWorkflow.batches[{batch_id}].validatedGeneration",
                        "PASSED batch must equal fixWorkflow.generation; re-validate before consuming it")
            if not strset(batch.get("evidenceRefs")):
                r.error(f"state.json.fixWorkflow.batches[{batch_id}].evidenceRefs", "PASSED batch requires Evidence")
        elif "validatedGeneration" in batch:
            r.error(f"state.json.fixWorkflow.batches[{batch_id}].validatedGeneration",
                    "allowed only on a PASSED batch")
        for dep in strset(batch.get("dependsOn")):
            if dep == batch_id or dep not in batch_by_id:
                r.error(f"state.json.fixWorkflow.batches[{batch_id}].dependsOn",
                        "dependencies must exist and must not self-reference")
            elif batch.get("status") == "PASSED" and batch_by_id[dep].get("status") != "PASSED":
                r.error(f"state.json.fixWorkflow.batches[{batch_id}].dependsOn",
                        f"dependency {dep} must be PASSED")
    # cycle detection over the dependency graph
    visiting: set = set()
    def walk(batch_id: object) -> None:
        if batch_id in visiting:
            r.error("state.json.fixWorkflow.batches", f"dependency cycle at {batch_id!r}")
            return
        if batch_id not in batch_by_id:
            return
        visiting.add(batch_id)
        for dep in strset(batch_by_id[batch_id].get("dependsOn")):
            walk(dep)
        visiting.discard(batch_id)
    for batch_id in batch_by_id:
        walk(batch_id)
    mappings = {item.get("findingId") for item in rows(workflow.get("findingMappings")) if isinstance(item, dict)}
    for batch in batches:
        if batch.get("kind") in {"FIX", "VERIFY"}:
            for finding_id in strset(batch.get("findingIds")) - mappings:
                r.error(f"state.json.fixWorkflow.batches[{batch.get('id')}].findingIds",
                        f"{finding_id} has no fix mapping")
    # A PASSED batch attests that its Findings reached a settled state. Without
    # this, "all batches PASSED" could be declared while a Fixing is still open.
    def settled(finding: dict) -> bool:
        if finding.get("decision") == "REJECTED":
            return True
        if finding.get("disposition") in {"RESOLVED-VERIFIED", "ACCEPTED-RISK"}:
            return True
        gates = finding.get("gates")
        if not isinstance(gates, dict) or not gates:
            return False
        return all(
            isinstance(gate, dict) and (
                gate.get("applicability") == "DOES-NOT-APPLY"
                or (gate.get("applicability") == "APPLIES" and gate.get("treatment") == "ACCEPTED")
            )
            for gate in gates.values()
        )

    for batch in batches:
        path = f"state.json.fixWorkflow.batches[{batch.get('id')}]"
        kind, status = batch.get("kind"), batch.get("status")
        # A retry must say what invalidated the previous attempt, otherwise a
        # failed batch can be silently re-run until it passes.
        attempt = batch.get("attempt")
        reason = batch.get("transitionReason")
        if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 1:
            if not (isinstance(reason, str) and reason.strip()):
                r.error(f"{path}.transitionReason", "attempt > 1 requires a non-empty retry/invalidation reason")
        elif reason is not None:
            r.error(f"{path}.transitionReason", "allowed only when attempt > 1")
        if status != "PASSED":
            continue
        for finding_id in strset(batch.get("findingIds")):
            finding = next((f for f in a.findings if f.get("id") == finding_id), None)
            if not isinstance(finding, dict):
                continue
            if kind == "FIX" and finding.get("disposition") != "REMEDIATING" and not settled(finding):
                r.error(f"{path}.status",
                        f"PASSED FIX batch requires Finding {finding_id!r} to be remediating, "
                        "resolved, rejected, or fully accepted")
            if kind == "VERIFY" and not settled(finding):
                r.error(f"{path}.status",
                        f"PASSED VERIFY batch requires Finding {finding_id!r} to be resolved, "
                        "rejected, or fully accepted")
    for finding in a.findings:
        finding_id, disposition = finding.get("id"), finding.get("disposition")
        covering = [b for b in batches if finding_id in strset(b.get("findingIds"))]
        if disposition == "REMEDIATING" and not [b for b in covering if b.get("kind") == "FIX"]:
            r.error(f"state.json.findings[{finding_id}].disposition", "REMEDIATING requires a FIX batch")
        if disposition == "RESOLVED-VERIFIED" and not [
            b for b in covering
            if b.get("kind") == "VERIFY" and b.get("status") == "PASSED"
            and strset(b.get("evidenceRefs")) & strset(finding.get("resolutionEvidence"))
        ]:
            r.error(f"state.json.findings[{finding_id}].resolutionEvidence",
                    "RESOLVED-VERIFIED must map to a PASSED VERIFY batch that cites its resolutionEvidence")
    if a.phase == "FINAL":
        for batch in batches:
            if batch.get("status") != "PASSED":
                r.error(f"state.json.fixWorkflow.batches[{batch.get('id')}].status",
                        "every batch must be PASSED in a FINAL audit-and-fix audit")
        for finding in a.findings:
            if finding.get("disposition") == "REMEDIATING":
                r.error(f"state.json.findings[{finding.get('id')}].disposition",
                        "FINAL audit-and-fix cannot leave a Finding REMEDIATING")
        final_id = workflow.get("finalRegressionBatchId")
        final_batch = batch_by_id.get(final_id)
        if not isinstance(final_batch, dict) or final_batch.get("kind") != "REGRESSION":
            r.error("state.json.fixWorkflow.finalRegressionBatchId", "must reference a REGRESSION batch")
        else:
            reached: set = set()
            stack = list(strset(final_batch.get("dependsOn")))
            while stack:
                current = stack.pop()
                if current in reached or current not in batch_by_id:
                    continue
                reached.add(current)
                stack.extend(strset(batch_by_id[current].get("dependsOn")))
            for batch in batches:
                if batch.get("status") == "PASSED" and batch.get("kind") in {"FIX", "VERIFY"} and batch.get("id") not in reached:
                    r.error("state.json.fixWorkflow.finalRegressionBatchId",
                            f"final regression must transitively depend on PASSED batch {batch.get('id')!r}")


# --------------------------------------------------------------------------
# 10. coverage & exploration
# --------------------------------------------------------------------------
def check_coverage(a: Audit, r: Report) -> None:
    stop = a.audit.get("stop") if isinstance(a.audit.get("stop"), dict) else {}
    coverage = a.audit.get("scopeCoverage")
    if stop.get("policy") == "exhaustive":
        if not isinstance(coverage, dict):
            r.error("state.json.audit.scopeCoverage", "exhaustive policy requires a declared scope inventory")
            return
        path = "state.json.audit.scopeCoverage"
        if coverage.get("snapshot") != a.audit.get("snapshot"):
            r.error(f"{path}.snapshot", "must exactly equal the current audit snapshot")
        declared = strset(coverage.get("declaredMembers"))
        completed = strset(coverage.get("completedMembers"))
        excluded = {item.get("member") for item in rows(coverage.get("excludedMembers")) if isinstance(item, dict)}
        if not declared:
            r.error(f"{path}.declaredMembers", "must declare a non-empty inventory")
        for member in completed - declared:
            r.error(f"{path}.completedMembers", f"unknown declared member {member!r}")
        for index, item in enumerate(rows(coverage.get("excludedMembers"))):
            if isinstance(item, dict) and item.get("member") not in declared:
                r.error(f"{path}.excludedMembers[{index}].member", "unknown declared member")
            if isinstance(item, dict) and not (isinstance(item.get("reason"), str) and item["reason"].strip()):
                r.error(f"{path}.excludedMembers[{index}].reason", "exclusions need a reason")
        for member in completed & excluded:
            r.error(path, f"members cannot be both completed and excluded: {member!r}")
        unresolved = declared - completed - excluded
        residual = coverage.get("residualRiskId")
        if (unresolved or not completed) and a.phase == "FINAL":
            target = next((i for i in a.residuals if i.get("id") == residual), None)
            if not isinstance(residual, str):
                r.error(f"{path}.residualRiskId", "FINAL incomplete exhaustive coverage requires a residual risk")
            elif not (isinstance(target, dict) and target.get("material")):
                r.error(f"{path}.residualRiskId", "must reference a material residual risk")
            else:
                # An uncovered scope voids the whole verdict, not one Gate: a
                # residual that spares some target lets that target stay READY.
                requested = strset((a.audit.get("gates") or {}).get("targets")) if isinstance(
                    a.audit.get("gates"), dict) else set()
                if requested and not requested.issubset(strset(target.get("affectsGates"))):
                    r.error(f"{path}.residualRiskId",
                            "exhaustive coverage residual must affect every requested Gate")
        elif residual is not None and not unresolved:
            r.error(f"{path}.residualRiskId", "allowed only for incomplete exhaustive coverage")
    elif coverage is not None:
        r.error("state.json.audit.scopeCoverage",
                "allowed only when stop.policy=exhaustive; an inventory without a "
                "completion obligation is a coverage claim nothing enforces")
    independent_required = strset(a.audit.get("independentValidationRequiredFor"))
    if not independent_required:
        return
    highest = [c for c in a.claims if c.get("priority") == "highest"]
    if "AUDIT" in independent_required and not highest and a.phase == "FINAL":
        r.error("state.json.audit.independentValidationRequiredFor",
                "FINAL audit-wide independent validation requires at least one highest Claim")


def check_exploration(a: Audit, r: Report) -> None:
    """Exploration is bounded by evidence, not by patience: two barren rounds end it."""
    exploratory = [c for c in a.claims if c.get("obligation") == "EXPLORATORY"]
    exploration = a.state.get("exploration")
    if not exploratory:
        if exploration is not None:
            r.error("state.json.exploration", "must be omitted when no EXPLORATORY claims exist")
        return
    if not isinstance(exploration, dict):
        r.error("state.json.exploration", "required when EXPLORATORY claims exist")
        return
    no_delta = exploration.get("noMaterialDeltaRounds")
    if not isinstance(no_delta, int) or isinstance(no_delta, bool):
        r.error("state.json.exploration.noMaterialDeltaRounds", "required when EXPLORATORY claims exist")
    elif not 0 <= no_delta <= 2:
        r.error("state.json.exploration.noMaterialDeltaRounds",
                "must be between 0 and 2; three barren rounds means exploration already ran out of warrant")
    declared: set = set()
    round_claims: dict = {}
    for index, item in enumerate(rows(exploration.get("rounds"))):
        path = f"state.json.exploration.rounds[{index}]"
        if not isinstance(item, dict):
            r.error(path, "expected object")
            continue
        round_id = item.get("id")
        if not isinstance(round_id, str) or not ROUND_ID_PATTERN.fullmatch(round_id):
            r.error(f"{path}.id", "expected an X<n> round id")
            continue
        if round_id in declared:
            r.error(f"{path}.id", f"duplicate exploration round id {round_id!r}")
        declared.add(round_id)
        claimed = strset(item.get("claimIds"))
        round_claims[round_id] = claimed
        if not claimed:
            r.error(f"{path}.claimIds", "a round must list at least one EXPLORATORY Claim")
        for claim_id in claimed:
            claim = next((c for c in exploratory if c.get("id") == claim_id), None)
            if claim is None:
                r.error(f"{path}.claimIds", f"{claim_id!r} is not an EXPLORATORY Claim")
            elif claim.get("explorationRound") != round_id:
                r.error(f"{path}.claimIds", f"Claim {claim_id!r} must point back to round {round_id!r}")
        if not isinstance(item.get("materialDelta"), bool):
            r.error(f"{path}.materialDelta", "expected a boolean")
    used = {c.get("explorationRound") for c in exploratory if isinstance(c.get("explorationRound"), str)}
    for round_id in sorted(used - declared):
        r.error("state.json.exploration.rounds", f"missing round used by claims: {round_id!r}")
    for claim in exploratory:
        claim_id, round_id = claim.get("id"), claim.get("explorationRound")
        if isinstance(claim_id, str) and isinstance(round_id, str) and claim_id not in round_claims.get(round_id, set()):
            r.error("state.json.exploration.rounds",
                    f"round {round_id!r} must list EXPLORATORY Claim {claim_id!r}")


# --------------------------------------------------------------------------
# supersession graph (--state-root)
# --------------------------------------------------------------------------
def validate_state_root(root: Path) -> Report:
    report = Report(str(root))
    if not root.is_dir():
        report.error(str(root), "state root is missing")
        return report
    instances: dict = {}
    for state_path in sorted(root.glob("*/state.json")):
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("audit"), dict):
            instances[state_path.parent.name] = data
    successor_by_old: dict = {}
    for new_id, data in instances.items():
        old_id = data["audit"].get("supersedesAuditId")
        if not isinstance(old_id, str):
            continue
        if old_id not in instances:
            report.error(new_id, f"supersedes unknown audit id {old_id!r}")
            continue
        if old_id in successor_by_old and successor_by_old[old_id] != new_id:
            report.error(str(root), f"audit {old_id!r} has multiple successors")
        successor_by_old[old_id] = new_id
        old = instances[old_id]
        supersession = old["audit"].get("supersession") if isinstance(old["audit"].get("supersession"), dict) else {}
        if old.get("phase") != "SUPERSEDED" or supersession.get("byAuditId") != new_id:
            report.error(new_id, f"supersession link to {old_id!r} is not reciprocated by a SUPERSEDED predecessor")
    for old_id, data in instances.items():
        supersession = data["audit"].get("supersession")
        if not isinstance(supersession, dict):
            continue
        new_id = supersession.get("byAuditId")
        if not isinstance(new_id, str) or new_id not in instances:
            report.error(old_id, f"supersession references unknown successor {new_id!r}")
        elif instances[new_id]["audit"].get("supersedesAuditId") != old_id:
            report.error(old_id, f"successor {new_id!r} does not link back with supersedesAuditId")
    for start in successor_by_old:
        seen, current = set(), start
        while current in successor_by_old and current not in seen:
            seen.add(current)
            current = successor_by_old[current]
        if current in seen:
            report.error(str(root), f"supersession chain cycles at {current!r}")
    return report


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------
def validate_audit(root: Path) -> Report:
    report = Report(str(root))
    audit = Audit(root, report)
    if not audit.load():
        return report
    check_invariant_prerequisites(audit, report)
    check_contract_fields(audit, report)
    check_bindings(audit, report)
    check_evidence_graph(audit, report)
    check_disconfirmation(audit, report)
    check_conclusions(audit, report)
    check_finding_gates(audit, report)
    check_gates(audit, report)
    check_fix_workflow(audit, report)
    check_coverage(audit, report)
    check_exploration(audit, report)
    return report


def emit(report: Report) -> int:
    for line in report.errors:
        print(line)
    if report.ok:
        print(f"PASS {report.label}: 0 errors")
        return 0
    print(f"FAIL {report.label}: {len(report.errors)} error(s)")
    return 1


def run_self_test(fixtures: Path) -> int:
    expectations_path = fixtures / "expectations.json"
    expectations = {}
    if expectations_path.is_file():
        try:
            loaded = json.loads(expectations_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                expectations = loaded
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    failures = 0
    for case in sorted(p for p in fixtures.iterdir() if p.is_dir()):
        expected_ok = case.name.startswith("valid-")
        report = validate_audit(case)
        expected_messages = expectations.get(case.name) or []
        if report.ok != expected_ok:
            print(f"SELF-TEST FAIL {case.name}: expected {'PASS' if expected_ok else 'rejection'}")
            failures += 1
            continue
        if not expected_ok:
            joined = " | ".join(report.errors)
            missing = [m for m in expected_messages if m not in joined]
            if missing:
                print(f"SELF-TEST FAIL {case.name}: rejected for the wrong reason; missing {missing}")
                failures += 1
                continue
            # The exact count is a regression tripwire: a message-substring check
            # still passes when a new check adds unrelated noise to a case that
            # was meant to isolate one failure. An unrecorded count is skipped
            # rather than guessed, so adding a fixture costs nothing.
            expected_count = expectations.get(f"{case.name}.error_count")
            if isinstance(expected_count, int) and len(report.errors) != expected_count:
                print(f"SELF-TEST FAIL {case.name}: expected {expected_count} error(s), "
                      f"got {len(report.errors)}")
                for line in report.errors:
                    print(f"    {line}")
                failures += 1
                continue
        print(f"SELF-TEST PASS {case.name}: {'valid' if expected_ok else 'rejected as expected'}")
    print("SELF-TEST " + ("PASS" if not failures else f"FAIL ({failures} case(s))"))
    return 1 if failures else 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", help="audit instance directory holding state.json")
    parser.add_argument("--state-root", help="validate the active/archive layout and supersession graph")
    parser.add_argument("--self-test", help="run the fixture suite in this directory")
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_test(Path(args.self_test))
    if args.state_root:
        return emit(validate_state_root(Path(args.state_root)))
    if not args.target:
        parser.error("provide an audit directory, --state-root, or --self-test")
    return emit(validate_audit(Path(args.target)))


if __name__ == "__main__":
    sys.exit(main())
