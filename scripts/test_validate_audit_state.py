#!/usr/bin/env python3
"""Regression tests for semantic invariants in validate_audit_state.py."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Callable

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from validate_audit_state import run_self_test, validate_state, validate_state_root  # noqa: E402


FIXTURES = SCRIPT_DIR / "fixtures"


class SemanticInvariantTests(unittest.TestCase):
    maxDiff = None

    def mutated_validation(
        self,
        fixture: str,
        mutate_state: Callable[[dict], None] | None = None,
        mutate_files: Callable[[Path], None] | None = None,
    ):
        with tempfile.TemporaryDirectory(prefix="cvpa-validator-") as raw:
            target = Path(raw) / fixture
            shutil.copytree(FIXTURES / fixture, target)
            state_path = target / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if mutate_state is not None:
                mutate_state(state)
                state_path.write_text(
                    json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            if mutate_files is not None:
                mutate_files(target)
            return validate_state(state_path)

    def mutated_errors(
        self,
        fixture: str,
        mutate_state: Callable[[dict], None] | None = None,
        mutate_files: Callable[[Path], None] | None = None,
    ) -> list[str]:
        return self.mutated_validation(fixture, mutate_state, mutate_files).errors

    def assert_error_contains(self, errors: list[str], fragment: str) -> None:
        self.assertTrue(
            any(fragment in error for error in errors),
            f"expected error containing {fragment!r}; got:\n" + "\n".join(errors),
        )

    # gate decision and basis -----------------------------------------------

    def test_active_state_cannot_cache_gate_decision(self) -> None:
        errors = self.mutated_errors(
            "valid-release-gate",
            lambda state: state.__setitem__("phase", "ACTIVE"),
        )
        self.assert_error_contains(errors, "must be omitted while phase is ACTIVE")

    def test_gate_basis_must_reference_decisive_live_object(self) -> None:
        def mutate(state: dict) -> None:
            state["audit"]["gates"]["decisions"]["RELEASE"]["basis"] = ["F999"]

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "unknown id/token 'F999'")
        self.assert_error_contains(errors, "must cite at least one decisive id/token")

    def test_gate_basis_cannot_include_live_but_non_decisive_object(self) -> None:
        def mutate(state: dict) -> None:
            state["audit"]["gates"]["decisions"]["RELEASE"]["basis"] = ["F1", "Q2"]

        errors = self.mutated_errors("valid-blocked-with-incomplete-scope", mutate)
        self.assert_error_contains(errors, "'Q2' does not determine the derived BLOCKED result")

    def test_gate_basis_cannot_repeat_decisive_object(self) -> None:
        def mutate(state: dict) -> None:
            state["audit"]["gates"]["decisions"]["RELEASE"]["basis"] = ["F1", "F1"]

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "contains duplicate entries")

    def test_checked_evidence_must_exist_in_investigation(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["checkedEvidence"] = ["R1-E999"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-fix-verification", mutate_files=mutate_files)
        self.assert_error_contains(errors, "unknown investigation evidence id 'R1-E999'")

    def test_artifact_references_must_be_portable_relative_paths(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "state.json"
            state = json.loads(path.read_text(encoding="utf-8"))
            state["verificationUnits"][0]["investigationFile"] = str(
                (target / "investigations" / "R1-a.json").resolve()
            )
            state["findings"][0]["verificationFile"] = str(
                (target / "verification" / "F1.json").resolve()
            )
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=mutate_files)
        self.assertGreaterEqual(
            sum("must be a relative .json path" in error for error in errors),
            2,
        )

    def test_referenced_artifact_symlink_is_rejected_before_external_read(self) -> None:
        def mutate_files(target: Path) -> None:
            artifact = target / "investigations" / "R1-main.json"
            external = target.parent / "external-invalid.json"
            external.write_text("{ invalid external json", encoding="utf-8")
            artifact.unlink()
            try:
                os.symlink(external, artifact)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

        errors = self.mutated_errors("valid-ordinary-no-gate", mutate_files=mutate_files)
        self.assert_error_contains(errors, "referenced artifact must not be a symlink or junction")
        self.assertFalse(any("invalid JSON" in error for error in errors), errors)

    def test_formal_artifacts_cannot_be_stored_under_probes(self) -> None:
        def investigation_state(state: dict) -> None:
            state["phase"] = "ACTIVE"
            state["audit"]["snapshot"] = None
            state["verificationUnits"][0]["investigationFile"] = "probes/R1-main.json"

        def investigation_file(target: Path) -> None:
            source = target / "investigations" / "R1-main.json"
            data = json.loads(source.read_text(encoding="utf-8"))
            data["auditBinding"]["snapshot"] = None
            probes = target / "probes"
            probes.mkdir()
            (probes / "R1-main.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            source.unlink()

        errors = self.mutated_errors("valid-ordinary-no-gate", investigation_state, investigation_file)
        self.assert_error_contains(errors, "investigationFile: must be a flat .json file directly under investigations/")

        def verification_state(state: dict) -> None:
            state["phase"] = "ACTIVE"
            state["audit"]["gates"].pop("decisions")
            state["findings"][0]["verificationFile"] = "probes/F1.json"

        def verification_file(target: Path) -> None:
            source = target / "verification" / "F1.json"
            probes = target / "probes"
            probes.mkdir()
            shutil.move(str(source), str(probes / "F1.json"))

        errors = self.mutated_errors("valid-release-gate", verification_state, verification_file)
        self.assert_error_contains(errors, "verificationFile: must be a flat .json file directly under verification/")

    def test_main_verification_requires_checked_and_new_direct_evidence(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["checkedEvidence"] = []
            data["evidence"] = []
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=mutate_files)
        self.assert_error_contains(errors, "checkedEvidence: must not be empty")
        self.assert_error_contains(errors, "evidence: must not be empty")

    def test_active_pending_finding_may_omit_verification_file(self) -> None:
        def mutate(state: dict) -> None:
            state["phase"] = "ACTIVE"
            state["audit"]["gates"].pop("decisions")
            finding = state["findings"][0]
            finding["decision"] = "PENDING"
            finding["supportingEvidence"] = ["R1-E1"]
            finding["gates"]["RELEASE"]["evidenceRefs"] = ["R1-E1"]
            for key in ("risk", "severity", "confidence", "verificationFile"):
                finding.pop(key, None)

        def mutate_files(target: Path) -> None:
            (target / "verification" / "F1.json").unlink()

        errors = self.mutated_errors("valid-release-gate", mutate, mutate_files)
        self.assertEqual(errors, [])

    def test_supporting_evidence_must_have_supports_polarity(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0]["supportingEvidence"] = ["R2-E1"]

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "polarity=context, expected supports")

    def test_finding_hypotheses_must_match_reconciliations_both_ways(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0]["sourceHypotheses"] = ["R1-H1", "R2-H999"]

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "must exactly match FINDING reconciliations")

    def test_gate_forbids_global_risk_acceptance(self) -> None:
        def mutate(state: dict) -> None:
            finding = state["findings"][0]
            finding["disposition"] = "ACCEPTED-RISK"
            finding["riskAcceptanceAuthorization"] = {
                "text": "release owner accepted F1",
                "auditId": "release-001",
                "snapshot": {"kind": "deployment", "version": "release-candidate-2026-08-22"},
            }

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "global ACCEPTED-RISK is allowed only when no Gate exists")

    def test_target_acceptance_excludes_low_finding_from_conditions(self) -> None:
        def mutate(state: dict) -> None:
            finding = state["findings"][0]
            finding["severity"] = "Low"
            finding["risk"]["impact"] = "Low"
            finding["gates"]["RELEASE"].update(
                {
                    "treatment": "ACCEPTED",
                    "authorization": {
                        "text": "release owner accepted F1 for RELEASE",
                        "auditId": "release-001",
                        "snapshot": {"kind": "deployment", "version": "release-candidate-2026-08-22"},
                        "target": "RELEASE",
                    },
                }
            )
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY",
                "basis": ["ALL-REQUIRED-INPUTS-SATISFIED"],
            }

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assertEqual(errors, [])

    def test_risk_acceptance_authorization_cannot_cross_audit_or_target(self) -> None:
        def mutate(state: dict) -> None:
            finding = state["findings"][0]
            finding["severity"] = "Low"
            finding["risk"]["impact"] = "Low"
            finding["gates"]["RELEASE"].update(
                {
                    "treatment": "ACCEPTED",
                    "authorization": {
                        "text": "accepted for an older candidate",
                        "auditId": "release-old",
                        "snapshot": {"kind": "deployment", "version": "older-candidate"},
                        "target": "SYSTEM",
                    },
                }
            )

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "authorization.auditId: must equal current audit id")
        self.assert_error_contains(errors, "authorization.snapshot: must exactly equal the current audit snapshot")
        self.assert_error_contains(errors, "authorization.target: must equal Gate target")

    def test_gate_authorization_cannot_exist_without_accepted_treatment(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0]["gates"]["RELEASE"]["authorization"] = {
                "text": "stale authorization",
                "auditId": "release-001",
                "snapshot": {"kind": "deployment", "version": "release-candidate-2026-08-22"},
                "target": "RELEASE",
            }

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "authorization: allowed only with treatment=ACCEPTED")

    def test_open_is_implicit_and_cannot_be_materialized(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0]["disposition"] = "OPEN"

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "invalid value 'OPEN'")

    def test_scope_assumption_is_allowed_only_for_assumed_basis(self) -> None:
        def mutate(state: dict) -> None:
            state["audit"]["scopeResolution"]["assumption"] = "an unnecessary assumption"

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "allowed only when basis is ASSUMED")

    def test_objective_profiles_require_general_once(self) -> None:
        def omit_general(state: dict) -> None:
            state["audit"]["objectiveProfiles"] = ["security"]

        def duplicate_general(state: dict) -> None:
            state["audit"]["objectiveProfiles"].append("general")

        errors = self.mutated_errors("valid-release-gate", omit_general)
        self.assert_error_contains(errors, "must include the default profile 'general'")
        errors = self.mutated_errors("valid-release-gate", duplicate_general)
        self.assert_error_contains(errors, "objectiveProfiles: contains duplicates")

    def test_protocol_objects_reject_unknown_fields_but_allow_metadata(self) -> None:
        def unknown_top(state: dict) -> None:
            state["unrecognizedProtocolField"] = True

        def unknown_audit(state: dict) -> None:
            state["audit"]["unrecognizedAuditField"] = True

        def unknown_finding(state: dict) -> None:
            state["findings"][0]["unrecognizedFindingField"] = True

        def unknown_disconfirmation(state: dict) -> None:
            state["findings"][0]["disconfirmation"]["unexpected"] = True

        def unknown_gate(state: dict) -> None:
            state["findings"][0]["gates"]["RELEASE"]["unexpected"] = True

        for mutation in (unknown_top, unknown_audit, unknown_finding, unknown_disconfirmation, unknown_gate):
            with self.subTest(mutation=mutation.__name__):
                errors = self.mutated_errors("valid-release-gate", mutation)
                self.assert_error_contains(errors, "unsupported keys")

        def add_metadata(state: dict) -> None:
            state["metadata"] = {"tool": "local-harness"}
            state["audit"]["metadata"] = {"display": "release audit"}
            state["findings"][0]["metadata"] = {"ticket": "SEC-12"}

        errors = self.mutated_errors("valid-release-gate", add_metadata)
        self.assertEqual(errors, [])

    def test_nested_artifact_protocol_objects_reject_unknown_fields(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "investigations" / "R1-a.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["hypotheses"][0]["unexpected"] = True
            data["coverageSummary"]["unexpected"] = True
            data["evidence"][0]["testDiscrimination"] = {
                "result": "YES",
                "test": "reproduction",
                "basis": "failure is encoded",
                "unexpected": True,
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=mutate_files)
        self.assertGreaterEqual(sum("unsupported keys" in error for error in errors), 3)

    def test_state_directory_rejects_unmodelled_live_artifact(self) -> None:
        def mutate_files(target: Path) -> None:
            (target / "findings.json").write_text("{}\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=mutate_files)
        self.assert_error_contains(errors, "findings.json: unsupported state-directory entry")

    def test_state_directory_rejects_unreferenced_and_nested_artifacts(self) -> None:
        def mutate_files(target: Path) -> None:
            (target / "investigations" / "extra.json").write_text("{}\n", encoding="utf-8")
            nested = target / "verification" / "nested"
            nested.mkdir()
            (nested / "F2.json").write_text("{}\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=mutate_files)
        self.assert_error_contains(errors, "investigations/extra.json: artifact is not referenced by state.json")
        self.assert_error_contains(errors, "verification/nested: artifact directories may contain only flat referenced .json files")

    def test_audit_wide_independent_requirement_covers_off_gate_highest_claims(self) -> None:
        def mutate(state: dict) -> None:
            state["audit"]["independentValidationRequiredFor"] = ["AUDIT"]
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY",
                "basis": ["ALL-REQUIRED-INPUTS-SATISFIED"],
            }
            state["claims"][0].pop("gateTargets")
            gate = state["findings"][0]["gates"]["RELEASE"]
            gate["treatment"] = "ACCEPTED"
            gate["authorization"] = {
                "text": "release owner accepted F1 for RELEASE",
                "auditId": "release-001",
                "snapshot": {"kind": "deployment", "version": "release-candidate-2026-08-22"},
                "target": "RELEASE",
            }

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "declared READY, but state derives INCOMPLETE")

    def test_independent_requirement_targets_must_be_unique(self) -> None:
        def mutate(state: dict) -> None:
            state["audit"]["independentValidationRequiredFor"] = ["RELEASE", "RELEASE"]

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "contains duplicates")

    def test_verified_unit_requires_direct_evidence(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "investigations" / "R1-main.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["evidence"] = []
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-ordinary-no-gate", mutate_files=mutate_files)
        self.assert_error_contains(errors, "verified Unit requires at least one DIRECT Evidence")

    def test_test_discrimination_requires_nonempty_test_and_basis(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "investigations" / "R1-main.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["evidence"][0]["testDiscrimination"] = {
                "result": "UNKNOWN",
                "test": "   ",
                "basis": "",
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-ordinary-no-gate", mutate_files=mutate_files)
        self.assert_error_contains(errors, "testDiscrimination.test: must not be empty")
        self.assert_error_contains(errors, "testDiscrimination.basis: must not be empty")

    def test_es3_es4_require_reproducible_observations(self) -> None:
        def mutate_files(target: Path, strength: str, reproducibility: str) -> None:
            path = target / "investigations" / "R1-main.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["evidence"][0]["strength"] = strength
            data["evidence"][0]["reproducibility"] = reproducibility
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        for strength in ("ES3", "ES4"):
            for reproducibility in ("single-observation", "not-applicable"):
                with self.subTest(strength=strength, reproducibility=reproducibility):
                    errors = self.mutated_errors(
                        "valid-ordinary-no-gate",
                        mutate_files=lambda target, s=strength, r=reproducibility: mutate_files(target, s, r),
                    )
                    self.assert_error_contains(errors, f"{strength} requires repeatable or explicitly conditional reproduction")

    def test_confirmed_finding_requires_refuted_counter_hypothesis(self) -> None:
        for result in ("counter-supported", "unresolved"):
            with self.subTest(result=result):
                def mutate(state: dict, value: str = result) -> None:
                    state["findings"][0]["disconfirmation"]["result"] = value

                errors = self.mutated_errors("valid-release-gate", mutate)
                self.assert_error_contains(errors, "CONFIRMED requires counter-refuted disconfirmation")

    def test_needs_decision_requires_fact_level_disconfirmation_to_be_closed(self) -> None:
        def mutate(state: dict) -> None:
            finding = state["findings"][0]
            finding["decision"] = "NEEDS-DECISION"
            finding["disconfirmation"]["result"] = "unresolved"

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "NEEDS-DECISION requires fact-level disconfirmation")

    def test_hypothesis_reconciliation_must_follow_recorded_outcome(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "investigations" / "R1-a.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            hypothesis = data["hypotheses"][0]
            hypothesis["result"] = "refuted"
            hypothesis["recommendation"] = "promote-to-finding"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=mutate_files)
        self.assert_error_contains(errors, "refuted hypothesis must be closed")

    def test_hypothesis_requires_direct_evidence_reference(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "investigations" / "R1-a.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["hypotheses"][0]["evidenceRefs"] = []
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=mutate_files)
        self.assert_error_contains(errors, "evidenceRefs: must contain DIRECT evidence")

    def test_supported_hypothesis_cannot_be_silently_reconciled_as_refuted(self) -> None:
        def mutate(state: dict) -> None:
            reconciliation = state["verificationUnits"][0]["reconciliations"][0]
            reconciliation["result"] = "REFUTED"
            reconciliation.pop("findingId")
            state["findings"] = []
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY",
                "basis": ["ALL-REQUIRED-INPUTS-SATISFIED"],
            }

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "must be FINDING for hypothesis recommendation promote-to-finding")

    def test_refuted_hypothesis_requires_refuting_direct_evidence(self) -> None:
        def mutate_state(state: dict) -> None:
            reconciliation = state["verificationUnits"][0]["reconciliations"][0]
            reconciliation["result"] = "REFUTED"
            reconciliation.pop("findingId")
            state["findings"] = []
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY",
                "basis": ["ALL-REQUIRED-INPUTS-SATISFIED"],
            }

        def mutate_files(target: Path) -> None:
            path = target / "investigations" / "R1-a.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            hypothesis = data["hypotheses"][0]
            hypothesis["result"] = "refuted"
            hypothesis["recommendation"] = "close"
            hypothesis["disconfirmationResult"] = "counter-supported"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_state, mutate_files)
        self.assert_error_contains(errors, "refuted hypothesis requires refuting DIRECT evidence")

    def test_residual_gap_reconciliation_requires_existing_residual_risk(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "investigations" / "R1-a.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            hypothesis = data["hypotheses"][0]
            hypothesis["result"] = "unresolved"
            hypothesis["recommendation"] = "residual-gap"
            hypothesis["disconfirmationResult"] = "unresolved"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def base_mutation(state: dict) -> dict:
            reconciliation = state["verificationUnits"][0]["reconciliations"][0]
            reconciliation["result"] = "RESIDUAL-GAP"
            reconciliation.pop("findingId")
            state["findings"] = []
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY",
                "basis": ["ALL-REQUIRED-INPUTS-SATISFIED"],
            }
            return reconciliation

        def missing_reference(state: dict) -> None:
            base_mutation(state)

        def unknown_reference(state: dict) -> None:
            base_mutation(state)["residualRiskId"] = "G999"

        errors = self.mutated_errors("valid-release-gate", missing_reference, mutate_files)
        self.assert_error_contains(errors, "missing required key 'residualRiskId'")
        errors = self.mutated_errors("valid-release-gate", unknown_reference, mutate_files)
        self.assert_error_contains(errors, "unknown residual risk id 'G999'")

    def test_malformed_nested_values_are_rejected_without_validator_crash(self) -> None:
        def bad_profile(state: dict) -> None:
            state["audit"]["objectiveProfiles"] = [{"bad": 1}]

        def bad_finding_source(state: dict) -> None:
            state["findings"][0]["sourceHypotheses"] = [{"bad": 1}]

        def bad_gate_basis(state: dict) -> None:
            state["audit"]["gates"]["decisions"]["RELEASE"]["basis"] = [{"bad": 1}]

        def bad_reconciliation_target(state: dict) -> None:
            state["verificationUnits"][0]["reconciliations"][0]["findingId"] = {"bad": 1}

        def bad_evidence_polarity(state: dict) -> None:
            # polarity lives inside the investigation artifact, so the real
            # mutation happens in mutate_bad_evidence below; this placeholder
            # only exists to name the subTest case.
            pass

        def null_reconciliations(state: dict) -> None:
            state["verificationUnits"][0]["reconciliations"] = None

        def bad_claim_priority(state: dict) -> None:
            state["claims"][0]["priority"] = {"bad": 1}

        def null_gate_decision(state: dict) -> None:
            state["audit"]["gates"]["decisions"]["RELEASE"] = None

        def bad_finding_gates(state: dict) -> None:
            state["findings"][0]["gates"] = []

        def mutate_bad_evidence(target: Path) -> None:
            path = target / "investigations" / "R1-a.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["evidence"][0]["polarity"] = {"bad": 1}
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        cases = (
            (bad_profile, None, "expected non-empty string"),
            (bad_finding_source, None, "expected non-empty string"),
            (bad_gate_basis, None, "expected non-empty string"),
            (bad_reconciliation_target, None, "expected str, got dict"),
            (bad_evidence_polarity, mutate_bad_evidence, "expected str, got dict"),
            (null_reconciliations, None, "expected list, got NoneType"),
            (bad_claim_priority, None, "expected str, got dict"),
            (null_gate_decision, None, "expected object"),
            (bad_finding_gates, None, "expected object"),
        )
        for mutation, file_mutation, expected in cases:
            with self.subTest(expected=expected, mutation=mutation.__name__):
                errors = self.mutated_errors(
                    "valid-release-gate",
                    mutate_state=mutation,
                    mutate_files=file_mutation,
                )
                self.assert_error_contains(errors, expected)

    def test_illegal_gate_policy_is_reported_without_validator_crash(self) -> None:
        def invalid_value(state: dict) -> None:
            state["audit"]["gates"]["policies"]["RELEASE"]["blockAtOrAbove"] = "Bogus"

        def missing_value(state: dict) -> None:
            del state["audit"]["gates"]["policies"]["RELEASE"]["blockAtOrAbove"]

        def unknown_key(state: dict) -> None:
            state["audit"]["gates"]["policies"]["RELEASE"]["allowWarnings"] = True

        def unrequested_target(state: dict) -> None:
            state["audit"]["gates"]["policies"]["CHANGE"] = {"blockAtOrAbove": "Medium"}

        cases = (
            (invalid_value, "invalid value 'Bogus'"),
            (missing_value, "missing required key 'blockAtOrAbove'"),
            (unknown_key, "unsupported policy keys: ['allowWarnings']"),
            (unrequested_target, "target was not requested"),
        )
        for mutation, expected in cases:
            with self.subTest(expected=expected):
                errors = self.mutated_errors("valid-release-gate", mutation)
                self.assert_error_contains(errors, expected)

    def test_met_requires_nonempty_verified_evidence_producer(self) -> None:
        def zero_units(state: dict) -> None:
            claim = state["claims"][0]
            claim["priority"] = "high"
            claim["discrimination"] = {
                "discriminatingObservation": "a real parser input reaches a safe outcome",
                "sufficiencyCriterion": "DIRECT Evidence records that outcome",
            }
            claim["sufficiency"] = "MET"
            state["verificationUnits"] = []

        errors = self.mutated_errors("valid-ordinary-no-gate", zero_units)
        self.assert_error_contains(errors, "MET requires at least one materialized Verification Unit")
        self.assert_error_contains(errors, "MET requires DIRECT Evidence")

    def test_met_rejects_unfinished_required_unit(self) -> None:
        def planned_unit(state: dict) -> None:
            unit = state["verificationUnits"][0]
            unit["status"] = "planned"
            for key in ("executor", "investigationFile", "reconciliations"):
                unit.pop(key, None)

        errors = self.mutated_errors("valid-fix-verification", planned_unit)
        self.assert_error_contains(errors, "every Unit inherited by a REQUIRED Claim to be verified")

    def test_highest_met_requires_two_heterogeneous_verified_methods(self) -> None:
        def remove_second_method(state: dict) -> None:
            state["verificationUnits"] = [state["verificationUnits"][0]]

        errors = self.mutated_errors("valid-release-gate", remove_second_method)
        self.assert_error_contains(errors, "MET for a highest Claim requires two verified heterogeneous methods")

    def test_residual_ids_must_be_unique_g_numbers(self) -> None:
        def invalid_id(state: dict) -> None:
            state["residualRisks"][0]["id"] = "gap-one"

        def duplicate_id(state: dict) -> None:
            state["residualRisks"].append(
                {
                    "id": "G1",
                    "statement": "a second unrelated runtime gap",
                    "scope": "another client",
                    "material": False,
                    "affectsGates": ["RELEASE"],
                }
            )

        errors = self.mutated_errors("valid-blocked-with-incomplete-scope", invalid_id)
        self.assert_error_contains(errors, "expected residual id matching ^G[1-9][0-9]*$")
        errors = self.mutated_errors("valid-blocked-with-incomplete-scope", duplicate_id)
        self.assert_error_contains(errors, "duplicate residual id G1")

    def test_sufficiency_belongs_to_claim_not_unit(self) -> None:
        def mutate(state: dict) -> None:
            state["verificationUnits"][0]["sufficiency"] = "MET"

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "belongs to the Claim, not the Verification Unit")

    def test_empty_gate_coverage_cannot_claim_ready(self) -> None:
        def mutate(state: dict) -> None:
            state["claims"] = []
            state["verificationUnits"] = []
            state["findings"] = []
            state["residualRisks"] = []
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY",
                "basis": ["ALL-REQUIRED-INPUTS-SATISFIED"],
            }

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "declared READY, but state derives INCOMPLETE")
        self.assert_error_contains(errors, "REQUIRED-COVERAGE-GAP")

    def test_empty_gate_coverage_can_end_explicitly_incomplete(self) -> None:
        def mutate(state: dict) -> None:
            state["claims"] = []
            state["verificationUnits"] = []
            state["findings"] = []
            state["residualRisks"] = []
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "INCOMPLETE",
                "basis": ["REQUIRED-COVERAGE-GAP"],
            }

        def mutate_files(target: Path) -> None:
            for directory in (target / "investigations", target / "verification"):
                for artifact in directory.iterdir():
                    artifact.unlink()

        self.assertEqual(self.mutated_errors("valid-release-gate", mutate, mutate_files), [])

    def test_exhaustive_scope_requires_nonempty_bound_coverage_and_fail_closed_gate(self) -> None:
        def missing_coverage(state: dict) -> None:
            state["audit"]["stop"] = {"policy": "exhaustive"}

        errors = self.mutated_errors("valid-release-gate", missing_coverage)
        self.assert_error_contains(errors, "scopeCoverage: required object")

        def incomplete_coverage(state: dict) -> None:
            state["audit"]["stop"] = {"policy": "exhaustive"}
            state["audit"]["scopeCoverage"] = {
                "snapshot": state["audit"]["snapshot"],
                "declaredMembers": ["src/http.py", "src/persistence.py"],
                "completedMembers": ["src/http.py"],
                "excludedMembers": [],
                "residualRiskId": "G1",
            }
            state["residualRisks"] = [
                {
                    "id": "G1",
                    "statement": "persistence scope was not read",
                    "scope": "exhaustive repository coverage",
                    "material": True,
                    "affectsGates": ["RELEASE"],
                }
            ]
            finding = state["findings"][0]
            finding["risk"]["impact"] = "Low"
            finding["severity"] = "Low"
            finding["gates"]["RELEASE"].update(
                {
                    "treatment": "ACCEPTED",
                    "authorization": {
                        "text": "accepted F1 for exhaustive coverage regression",
                        "auditId": state["audit"]["id"],
                        "snapshot": state["audit"]["snapshot"],
                        "target": "RELEASE",
                    },
                }
            )
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "INCOMPLETE",
                "basis": ["EXHAUSTIVE-COVERAGE-GAP"],
            }

        self.assertEqual(self.mutated_errors("valid-release-gate", incomplete_coverage), [])

        def complete_coverage(state: dict) -> None:
            state["audit"]["stop"] = {"policy": "exhaustive"}
            state["audit"]["scopeCoverage"] = {
                "snapshot": state["audit"]["snapshot"],
                "declaredMembers": ["src/http.py", "generated/client.bin"],
                "completedMembers": ["src/http.py"],
                "excludedMembers": [
                    {"member": "generated/client.bin", "reason": "generated output covered through source"}
                ],
            }

        self.assertEqual(self.mutated_errors("valid-release-gate", complete_coverage), [])

    def test_rejected_finding_requires_new_direct_refutation(self) -> None:
        def mutate(state: dict) -> None:
            finding = state["findings"][0]
            finding["decision"] = "REJECTED"
            finding["refutingEvidence"] = []
            for key in ("risk", "severity", "confidence", "disposition"):
                finding.pop(key, None)
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY",
                "basis": ["ALL-REQUIRED-INPUTS-SATISFIED"],
            }

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "REJECTED requires DIRECT refuting Evidence")
        self.assert_error_contains(errors, "REJECTED requires new refuting Evidence")

    def test_rejected_finding_may_keep_supporting_history_after_new_refutation(self) -> None:
        def mutate_state(state: dict) -> None:
            finding = state["findings"][0]
            finding["decision"] = "REJECTED"
            finding["supportingEvidence"] = ["R1-E1"]
            finding["refutingEvidence"] = ["F1-E1"]
            finding["gates"]["RELEASE"] = {
                "applicability": "DOES-NOT-APPLY",
                "basis": "the direct recheck disproves the Finding for this candidate",
                "evidenceRefs": ["F1-E1"],
            }
            for key in ("risk", "severity", "confidence", "disposition"):
                finding.pop(key, None)
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY",
                "basis": ["ALL-REQUIRED-INPUTS-SATISFIED"],
            }

        def mutate_files(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["evidence"][0]["polarity"] = "refutes"
            data["conclusion"] = "a direct recheck disproves the Finding"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        self.assertEqual(self.mutated_errors("valid-release-gate", mutate_state, mutate_files), [])

    def test_rejected_finding_must_omit_risk(self) -> None:
        def mutate(state: dict) -> None:
            finding = state["findings"][0]
            finding["decision"] = "REJECTED"
            finding["refutingEvidence"] = ["F1-E1"]
            for key in ("severity", "confidence", "disposition"):
                finding.pop(key, None)

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "risk: must be omitted for REJECTED")

    def test_gate_applicability_requires_linked_evidence(self) -> None:
        def missing(state: dict) -> None:
            state["findings"][0]["gates"]["RELEASE"].pop("evidenceRefs")

        def unrelated(state: dict) -> None:
            state["findings"][0]["gates"]["RELEASE"]["evidenceRefs"] = ["R2-E1"]

        errors = self.mutated_errors("valid-release-gate", missing)
        self.assert_error_contains(errors, "missing required key 'evidenceRefs'")
        errors = self.mutated_errors("valid-release-gate", unrelated)
        self.assert_error_contains(errors, "is not linked to Finding F1")

    def test_does_not_apply_label_cannot_bypass_gate_without_evidence(self) -> None:
        def mutate(state: dict) -> None:
            gate = state["findings"][0]["gates"]["RELEASE"]
            gate["applicability"] = "DOES-NOT-APPLY"
            gate.pop("evidenceRefs")
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY",
                "basis": ["ALL-REQUIRED-INPUTS-SATISFIED"],
            }

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "missing required key 'evidenceRefs'")

    def test_exploratory_claim_cannot_carry_gate_targets(self) -> None:
        def mutate(state: dict) -> None:
            claim = state["claims"][0]
            claim["obligation"] = "EXPLORATORY"
            claim["explorationRound"] = "X1"
            state["exploration"] = {
                "rounds": [{"id": "X1", "claimIds": ["Q1"], "materialDelta": False}],
                "noMaterialDeltaRounds": 1,
            }

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "EXPLORATORY claims cannot carry Gate completion obligations")

    def test_exploration_rounds_require_nonempty_bidirectional_exploratory_claim_membership(self) -> None:
        def valid_exploration(state: dict) -> None:
            claim = state["claims"][0]
            claim["obligation"] = "EXPLORATORY"
            claim.pop("gateTargets")
            claim["explorationRound"] = "X1"
            state["exploration"] = {
                "rounds": [{"id": "X1", "claimIds": ["Q1"], "materialDelta": False}],
                "noMaterialDeltaRounds": 1,
            }

        self.assertEqual(self.mutated_errors("valid-release-gate", valid_exploration), [])

        def empty_round(state: dict) -> None:
            valid_exploration(state)
            state["exploration"]["rounds"][0]["claimIds"] = []

        errors = self.mutated_errors("valid-release-gate", empty_round)
        self.assert_error_contains(errors, "claimIds: must not be empty")
        self.assert_error_contains(errors, "must list EXPLORATORY Claim 'Q1'")

        def wrong_back_reference(state: dict) -> None:
            valid_exploration(state)
            state["claims"][0]["explorationRound"] = "X2"

        errors = self.mutated_errors("valid-release-gate", wrong_back_reference)
        self.assert_error_contains(errors, "must point back to round 'X1'")

    def test_severity_is_constrained_by_risk_mapping_and_documented_adjustments(self) -> None:
        def illegal_downgrade(state: dict) -> None:
            finding = state["findings"][0]
            finding["risk"] = {
                "impact": "Critical", "likelihood": "High", "reachability": "Common", "recoverability": "Irreversible",
            }
            finding["severity"] = "Low"
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY-WITH-CONDITIONS",
                "basis": ["F1"],
            }

        errors = self.mutated_errors("valid-release-gate", illegal_downgrade)
        self.assert_error_contains(errors, "Low is not permitted by the Impact/Likelihood/Reachability/Recoverability mapping")

        def illegal_upgrade(state: dict) -> None:
            finding = state["findings"][0]
            finding["risk"] = {
                "impact": "Medium", "likelihood": "Low", "reachability": "Privileged", "recoverability": "Manual",
            }
            finding["severity"] = "Critical"
            finding["severityRationale"] = "attempted unsupported two-level escalation"

        errors = self.mutated_errors("valid-release-gate", illegal_upgrade)
        self.assert_error_contains(errors, "Critical is not permitted by the Impact/Likelihood/Reachability/Recoverability mapping")

        def valid_limited_adjustment(state: dict) -> None:
            finding = state["findings"][0]
            finding["risk"] = {
                "impact": "Medium", "likelihood": "Low", "reachability": "Privileged", "recoverability": "Manual",
            }
            finding["severity"] = "Low"
            finding["severityRationale"] = "low likelihood and privileged reachability limit realistic exposure"
            finding["gates"]["RELEASE"].update(
                {
                    "treatment": "ACCEPTED",
                    "authorization": {
                        "text": "release owner accepted F1 for RELEASE",
                        "auditId": "release-001",
                        "snapshot": {"kind": "deployment", "version": "release-candidate-2026-08-22"},
                        "target": "RELEASE",
                    },
                }
            )
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY",
                "basis": ["ALL-REQUIRED-INPUTS-SATISFIED"],
            }

        self.assertEqual(self.mutated_errors("valid-release-gate", valid_limited_adjustment), [])

    def test_stop_reason_is_a_nonempty_state_fact_when_present(self) -> None:
        def valid_reason(state: dict) -> None:
            state["audit"]["stop"] = {
                "policy": "user-defined",
                "criteria": "review budget reached",
                "reason": "the user-defined review budget was reached",
            }

        self.assertEqual(self.mutated_errors("valid-ordinary-no-gate", valid_reason), [])

        def blank_reason(state: dict) -> None:
            valid_reason(state)
            state["audit"]["stop"]["reason"] = "  "

        errors = self.mutated_errors("valid-ordinary-no-gate", blank_reason)
        self.assert_error_contains(errors, "stop.reason: must not be empty")

    def test_no_gate_audit_independent_requirement_without_highest_is_invalid(self) -> None:
        def mutate(state: dict) -> None:
            state["audit"]["independentValidationRequiredFor"] = ["AUDIT"]

        result = self.mutated_validation("valid-ordinary-no-gate", mutate)
        self.assert_error_contains(result.errors, "FINAL audit-wide independent validation requires at least one highest Claim")

    def test_final_no_gate_audit_cannot_close_a_nonempty_objective_list_with_zero_required_claims(self) -> None:
        def no_claims(state: dict) -> None:
            state["claims"] = []
            state["verificationUnits"] = []

        errors = self.mutated_errors("valid-ordinary-no-gate", no_claims)
        self.assert_error_contains(errors, "FINAL no-Gate audit requires at least one REQUIRED Claim")

        def exploratory_only(state: dict) -> None:
            state["claims"][0]["obligation"] = "EXPLORATORY"
            state["claims"][0]["explorationRound"] = "X1"
            state["exploration"] = {
                "rounds": [{"id": "X1", "claimIds": ["Q1"], "materialDelta": False}],
                "noMaterialDeltaRounds": 0,
            }

        errors = self.mutated_errors("valid-ordinary-no-gate", exploratory_only)
        self.assert_error_contains(errors, "FINAL no-Gate audit requires at least one REQUIRED Claim")

    def test_verified_test_discrimination_unit_requires_yes_evidence(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "investigations" / "R1-main.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["evidence"][0]["testDiscrimination"]["result"] = "NO"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-fix-verification", mutate_files=mutate_files)
        self.assert_error_contains(errors, "verified test-discrimination Unit requires at least one Evidence with testDiscrimination.result=YES")

    def test_source_hypotheses_must_be_unique(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0]["sourceHypotheses"] = ["R1-H1", "R1-H1"]

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "sourceHypotheses: contains duplicate entries")

    def test_reconciliation_evidence_must_belong_to_its_unit(self) -> None:
        def cross_unit(state: dict) -> None:
            state["verificationUnits"][0]["reconciliations"][0]["evidenceRefs"] = ["R2-E1"]

        def later_verification(state: dict) -> None:
            state["verificationUnits"][0]["reconciliations"][0]["evidenceRefs"] = ["F1-E1"]

        errors = self.mutated_errors("valid-release-gate", cross_unit)
        self.assert_error_contains(errors, "does not belong to this Verification Unit")
        errors = self.mutated_errors("valid-release-gate", later_verification)
        self.assert_error_contains(errors, "does not belong to this Verification Unit")

    def test_checked_evidence_must_belong_to_finding_chain(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["checkedEvidence"] = ["R2-E1"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=mutate_files)
        self.assert_error_contains(errors, "is not part of this Finding's investigation chain")

    def test_new_verification_evidence_must_be_consumed_by_finding(self) -> None:
        def mutate_state(state: dict) -> None:
            state["findings"][0]["supportingEvidence"] = ["R1-E1"]
            state["findings"][0]["gates"]["RELEASE"]["evidenceRefs"] = ["R1-E1"]

        errors = self.mutated_errors("valid-release-gate", mutate_state)
        self.assert_error_contains(errors, "new verification evidence 'F1-E1' is not consumed")

    def test_verification_method_must_match_finding(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["method"] = "adversarial-challenge"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=mutate_files)
        self.assert_error_contains(errors, "does not match verification file method")

    def test_high_confirmed_finding_requires_completed_challenge(self) -> None:
        def remove_challenge(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop("challenge")
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        def gap_challenge(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["challenge"] = {"status": "GAP", "gapReason": "runtime unavailable"}
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-blocked-with-incomplete-scope", mutate_files=remove_challenge)
        self.assert_error_contains(errors, "requires a recorded second challenge")
        errors = self.mutated_errors("valid-blocked-with-incomplete-scope", mutate_files=gap_challenge)
        self.assert_error_contains(errors, "challenge GAP is allowed only for a CONDITIONAL Finding")

    def test_high_conditional_finding_may_record_challenge_gap(self) -> None:
        def mutate_state(state: dict) -> None:
            finding = state["findings"][0]
            finding["decision"] = "CONDITIONAL"
            finding["confidence"] = "Medium"
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "INCOMPLETE",
                "basis": ["F1"],
            }

        def mutate_files(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["challenge"] = {"status": "GAP", "gapReason": "target runtime unavailable"}
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        self.assertEqual(
            self.mutated_errors("valid-blocked-with-incomplete-scope", mutate_state, mutate_files),
            [],
        )

    def test_heterogeneous_challenge_method_must_differ(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["challenge"] = {
                "status": "COMPLETED",
                "mode": "HETEROGENEOUS-METHOD",
                "unitId": "R1",
                "method": data["method"],
                "evidenceRefs": ["R1-E1"],
                "result": "counter-refuted",
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-fix-verification", mutate_files=mutate_files)
        self.assert_error_contains(errors, "heterogeneous challenge method must differ")

    def test_conditional_finding_cannot_keep_counter_supported_disconfirmation(self) -> None:
        def mutate(state: dict) -> None:
            finding = state["findings"][0]
            finding["decision"] = "CONDITIONAL"
            finding["confidence"] = "Medium"
            finding["disconfirmation"]["result"] = "counter-supported"

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "counter-supported closes or narrows")

    def test_final_unfinished_required_unit_requires_material_residual_mapping(self) -> None:
        def unfinished(state: dict) -> None:
            unit = state["verificationUnits"][0]
            unit["status"] = "planned"
            for key in ("executor", "investigationFile", "reconciliations"):
                unit.pop(key, None)

        errors = self.mutated_errors("valid-ordinary-no-gate", unfinished)
        self.assert_error_contains(errors, "must map to a material residual risk")

        def mapped(state: dict) -> None:
            unfinished(state)
            state["verificationUnits"][0]["residualRiskId"] = "G1"
            state["residualRisks"] = [
                {
                    "id": "G1",
                    "statement": "the planned trace could not be executed",
                    "scope": "parser public entrypoint",
                    "material": True,
                }
            ]

        def remove_investigation(target: Path) -> None:
            (target / "investigations" / "R1-main.json").unlink()

        self.assertEqual(self.mutated_errors("valid-ordinary-no-gate", mapped, remove_investigation), [])

    def test_snapshot_uses_a_bounded_recoverable_schema(self) -> None:
        def missing_snapshot(state: dict) -> None:
            state["audit"].pop("snapshot")

        def array_snapshot(state: dict) -> None:
            state["audit"]["snapshot"] = []

        def invalid_git_snapshot(state: dict) -> None:
            state["audit"]["snapshot"] = {"kind": "git", "head": "main"}

        errors = self.mutated_errors("valid-ordinary-no-gate", missing_snapshot)
        self.assert_error_contains(errors, "audit: missing required key 'snapshot'")
        errors = self.mutated_errors("valid-ordinary-no-gate", array_snapshot)
        self.assert_error_contains(errors, "audit.snapshot: expected object")
        errors = self.mutated_errors("valid-ordinary-no-gate", invalid_git_snapshot)
        self.assert_error_contains(errors, "expected immutable 40- or 64-hex Git object id")

        def valid_git_worktree_snapshot(state: dict) -> None:
            snapshot = {
                "kind": "git-worktree",
                "base": "1" * 40,
                "head": "1" * 40,
                "initialSha256": "2" * 64,
                "finalSha256": "3" * 64,
            }
            state["audit"]["snapshot"] = snapshot

        def bind_git_worktree_artifact(target: Path) -> None:
            path = target / "investigations" / "R1-main.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["auditBinding"]["snapshot"] = {
                "kind": "git-worktree",
                "base": "1" * 40,
                "head": "1" * 40,
                "initialSha256": "2" * 64,
                "finalSha256": "3" * 64,
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        self.assertEqual(
            self.mutated_errors(
                "valid-ordinary-no-gate",
                valid_git_worktree_snapshot,
                bind_git_worktree_artifact,
            ),
            [],
        )

        def invalid_git_worktree_manifest(state: dict) -> None:
            valid_git_worktree_snapshot(state)
            state["audit"]["snapshot"]["finalSha256"] = "not-a-manifest"

        errors = self.mutated_errors("valid-ordinary-no-gate", invalid_git_worktree_manifest)
        self.assert_error_contains(errors, "expected 64-hex SHA-256 worktree manifest identity")

    def test_superseded_phase_requires_link_and_cannot_cache_gate(self) -> None:
        def missing_link(state: dict) -> None:
            state["phase"] = "SUPERSEDED"

        errors = self.mutated_errors("valid-ordinary-no-gate", missing_link)
        self.assert_error_contains(errors, "supersession: required object")

        def valid_superseded(state: dict) -> None:
            state["phase"] = "SUPERSEDED"
            state["audit"]["supersession"] = {
                "byAuditId": "ordinary-002",
                "reason": "authoritative target changed",
                "at": "2026-08-22T01:00:00Z",
            }

        self.assertEqual(self.mutated_errors("valid-ordinary-no-gate", valid_superseded), [])

        def superseded_gate(state: dict) -> None:
            state["phase"] = "SUPERSEDED"
            state["audit"]["supersession"] = {
                "byAuditId": "release-002",
                "reason": "candidate changed",
                "at": "2026-08-22T01:00:00Z",
            }

        errors = self.mutated_errors("valid-release-gate", superseded_gate)
        self.assert_error_contains(errors, "must be omitted while phase is SUPERSEDED")

    def test_state_root_validates_bidirectional_supersession_and_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cvpa-state-root-") as raw:
            root = Path(raw)
            old_dir = root / "ordinary-old"
            new_dir = root / "ordinary-new"
            shutil.copytree(FIXTURES / "valid-ordinary-no-gate", old_dir)
            shutil.copytree(FIXTURES / "valid-ordinary-no-gate", new_dir)

            old_path = old_dir / "state.json"
            old = json.loads(old_path.read_text(encoding="utf-8"))
            old["audit"]["id"] = "ordinary-old"
            old["phase"] = "SUPERSEDED"
            old["audit"]["supersession"] = {
                "byAuditId": "ordinary-new",
                "reason": "scope changed",
                "at": "2026-08-22T01:00:00Z",
            }
            old_path.write_text(json.dumps(old, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            old_artifact_path = old_dir / "investigations" / "R1-main.json"
            old_artifact = json.loads(old_artifact_path.read_text(encoding="utf-8"))
            old_artifact["auditBinding"]["auditId"] = "ordinary-old"
            old_artifact_path.write_text(json.dumps(old_artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            new_path = new_dir / "state.json"
            new = json.loads(new_path.read_text(encoding="utf-8"))
            new["audit"]["id"] = "ordinary-new"
            new["audit"]["supersedesAuditId"] = "ordinary-old"
            new_path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            new_artifact_path = new_dir / "investigations" / "R1-main.json"
            new_artifact = json.loads(new_artifact_path.read_text(encoding="utf-8"))
            new_artifact["auditBinding"]["auditId"] = "ordinary-new"
            new_artifact_path.write_text(json.dumps(new_artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            self.assertEqual(validate_state_root(root).errors, [])

            archive_dir = root / "archive" / "ordinary-new"
            archive_dir.parent.mkdir()
            shutil.copytree(new_dir, archive_dir)
            duplicate_errors = validate_state_root(root).errors
            self.assert_error_contains(duplicate_errors, "duplicate audit id 'ordinary-new'")

    def test_state_root_rejects_partial_audit_directory_and_archived_active_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cvpa-state-root-layout-") as raw:
            root = Path(raw)
            partial = root / "partial-audit"
            partial.mkdir()
            errors = validate_state_root(root).errors
            self.assert_error_contains(errors, "audit directory is missing state.json")

        with tempfile.TemporaryDirectory(prefix="cvpa-state-root-archive-") as raw:
            root = Path(raw)
            archived = root / "archive" / "ordinary-001"
            shutil.copytree(FIXTURES / "valid-ordinary-no-gate", archived)
            state_path = archived / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["phase"] = "ACTIVE"
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            errors = validate_state_root(root).errors
            self.assert_error_contains(errors, "ACTIVE audit cannot be stored under archive")

    def test_state_root_rejects_stray_root_and_archive_entries(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cvpa-state-root-closed-") as raw:
            root = Path(raw)
            shutil.copytree(FIXTURES / "valid-ordinary-no-gate", root / "ordinary-001")
            (root / "shadow-state.json").write_text("{}\n", encoding="utf-8")
            archive = root / "archive"
            archive.mkdir()
            (archive / "shadow-ledger.md").write_text("stale\n", encoding="utf-8")

            errors = validate_state_root(root).errors
            self.assert_error_contains(errors, "shadow-state.json: unsupported state-root entry")
            self.assert_error_contains(errors, "archive/shadow-ledger.md: unsupported archive entry")

    def test_state_root_rejects_symlinked_state_when_platform_allows_symlinks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cvpa-state-root-symlink-") as raw:
            root = Path(raw)
            audit = root / "ordinary-001"
            shutil.copytree(FIXTURES / "valid-ordinary-no-gate", audit)
            original = audit / "state.json"
            external = root / "external-state.json"
            external.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
            original.unlink()
            try:
                os.symlink(external, original)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            errors = validate_state_root(root).errors
            self.assert_error_contains(errors, "ordinary-001: audit directory is missing state.json")

    def test_direct_validation_rejects_symlinked_audit_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cvpa-audit-dir-symlink-") as raw:
            root = Path(raw)
            real_audit = root / "real-audit"
            shutil.copytree(FIXTURES / "valid-ordinary-no-gate", real_audit)
            linked_audit = root / "linked-audit"
            try:
                os.symlink(real_audit, linked_audit, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlink creation unavailable: {exc}")
            errors = validate_state(linked_audit / "state.json").errors
            self.assert_error_contains(errors, "audit state directory must not be a symlink or junction")

    def test_evidence_artifacts_are_bound_to_current_audit_and_snapshot(self) -> None:
        def mutate(state: dict) -> None:
            state["audit"]["id"] = "ordinary-successor"
            state["audit"]["snapshot"] = {"kind": "other", "identity": "new-snapshot"}

        errors = self.mutated_errors("valid-ordinary-no-gate", mutate)
        self.assert_error_contains(errors, "auditBinding.auditId: must equal current audit id")
        self.assert_error_contains(errors, "auditBinding.snapshot: must exactly equal the current audit snapshot")

    def test_heterogeneous_challenge_must_be_backed_by_its_declared_unit(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["challenge"] = {
                "status": "COMPLETED",
                "mode": "HETEROGENEOUS-METHOD",
                "unitId": "R999",
                "method": "implementation-trace",
                "evidenceRefs": ["F1-E2"],
                "result": "counter-refuted",
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-fix-verification", mutate_files=mutate_files)
        self.assert_error_contains(errors, "heterogeneous challenge must reference an existing Verification Unit")
        self.assert_error_contains(errors, "not produced by the declared challenge path")

    def test_high_resolved_finding_requires_independent_resolution_challenge(self) -> None:
        def remove(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop("resolutionChallenge")
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-fix-verification", mutate_files=remove)
        self.assert_error_contains(errors, "requires a resolutionChallenge")

    def test_resolution_challenge_gap_is_not_a_legal_state(self) -> None:
        def mutate(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["resolutionChallenge"] = {
                "status": "GAP",
                "gapReason": "independent runtime environment unavailable",
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-fix-verification", mutate_files=mutate)
        self.assert_error_contains(errors, "invalid value 'GAP'")
        self.assert_error_contains(errors, "requires a completed resolutionChallenge")

    def test_audit_and_fix_workflow_is_authoritative_and_validates_its_dag(self) -> None:
        def no_repair_needed(state: dict) -> None:
            state["audit"]["executionMode"] = "audit-and-fix"

        self.assertEqual(self.mutated_errors("valid-ordinary-no-gate", no_repair_needed), [])

        def premature_workflow(state: dict) -> None:
            state["audit"]["executionMode"] = "audit-and-fix"
            state["fixWorkflow"] = {}

        errors = self.mutated_errors("valid-ordinary-no-gate", premature_workflow)
        self.assert_error_contains(errors, "must be omitted until a Finding enters REMEDIATING or RESOLVED-VERIFIED")

        def valid(state: dict) -> None:
            state["audit"]["executionMode"] = "audit-and-fix"
            state["fixWorkflow"] = {
                "generation": 1,
                "finalRegressionBatchId": "regression-1",
                "findingMappings": [
                    {
                        "findingId": "F1",
                        "rootCausePattern": "unchecked copy length",
                        "knownInstances": ["src/parser.c:90"],
                        "fixScope": "parser public entrypoint",
                        "exclusions": [],
                        "behaviorChange": "oversized input is rejected before copy",
                        "acceptanceChecks": ["pre-fix fails and post-fix passes"],
                        "preFixExpectedFailure": "oversized input reaches the copy",
                        "regressionScope": "parser callers and boundary lengths",
                        "residualRiskIds": [],
                    }
                ],
                "batches": [
                    {
                        "id": "fix-1", "kind": "FIX", "status": "PASSED", "attempt": 1,
                        "scope": "parser guard", "allowedPaths": ["src/parser.c"],
                        "acceptanceChecks": ["targeted parser regression"],
                        "dependsOn": [], "findingIds": ["F1"], "evidenceRefs": ["F1-E2"],
                        "validatedGeneration": 1,
                    },
                    {
                        "id": "verify-1", "kind": "VERIFY", "status": "PASSED", "attempt": 1,
                        "scope": "independent fix verification", "allowedPaths": [],
                        "acceptanceChecks": ["independent trace and discriminating regression"],
                        "dependsOn": ["fix-1"], "findingIds": ["F1"], "evidenceRefs": ["F1-E1", "R2-E1"],
                        "validatedGeneration": 1,
                    },
                    {
                        "id": "regression-1", "kind": "REGRESSION", "status": "PASSED", "attempt": 1,
                        "scope": "parser regression surface", "allowedPaths": [],
                        "acceptanceChecks": ["full parser regression"],
                        "dependsOn": ["verify-1"], "findingIds": ["F1"], "evidenceRefs": ["F1-E1"],
                        "validatedGeneration": 1,
                    },
                ],
            }

        self.assertEqual(self.mutated_errors("valid-fix-verification", valid), [])

        def unknown_workflow_fields(state: dict) -> None:
            valid(state)
            state["fixWorkflow"]["manualOverride"] = True
            state["fixWorkflow"]["findingMappings"][0]["parallelLedger"] = {"status": "accepted"}
            state["fixWorkflow"]["batches"][0]["unrecognizedBatchField"] = True

        errors = self.mutated_errors("valid-fix-verification", unknown_workflow_fields)
        self.assertGreaterEqual(sum("unsupported keys" in error for error in errors), 3)

        def cycle(state: dict) -> None:
            valid(state)
            state["fixWorkflow"]["batches"][0]["dependsOn"] = ["regression-1"]

        errors = self.mutated_errors("valid-fix-verification", cycle)
        self.assert_error_contains(errors, "dependency cycle detected")

        def retry_without_reason(state: dict) -> None:
            valid(state)
            state["fixWorkflow"]["batches"][1]["attempt"] = 2

        errors = self.mutated_errors("valid-fix-verification", retry_without_reason)
        self.assert_error_contains(errors, "attempt > 1 requires a non-empty retry/invalidation reason")

        def missing(state: dict) -> None:
            state["audit"]["executionMode"] = "audit-and-fix"

        errors = self.mutated_errors("valid-fix-verification", missing)
        self.assert_error_contains(errors, "required when audit-and-fix has REMEDIATING or RESOLVED-VERIFIED Findings")

        def remediating_without_mapping(state: dict) -> None:
            valid(state)
            finding = state["findings"][0]
            finding["disposition"] = "REMEDIATING"
            finding.pop("resolutionEvidence")
            state["fixWorkflow"]["findingMappings"] = []

        def remove_resolution_challenge(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data.pop("resolutionChallenge")
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors(
            "valid-fix-verification",
            remediating_without_mapping,
            remove_resolution_challenge,
        )
        self.assert_error_contains(errors, "REMEDIATING has no fixWorkflow findingMapping")

        def remediating_with_green_batches(state: dict) -> None:
            valid(state)
            finding = state["findings"][0]
            finding["disposition"] = "REMEDIATING"
            finding.pop("resolutionEvidence")

        errors = self.mutated_errors(
            "valid-fix-verification",
            remediating_with_green_batches,
            remove_resolution_challenge,
        )
        self.assert_error_contains(errors, "FINAL audit-and-fix cannot leave a Finding REMEDIATING")
        self.assert_error_contains(errors, "PASSED VERIFY batch requires Finding 'F1' to be resolved, rejected, or fully accepted")

        def verify_uses_old_supporting_evidence(state: dict) -> None:
            valid(state)
            state["fixWorkflow"]["batches"][1]["evidenceRefs"] = ["F1-E2"]

        errors = self.mutated_errors("valid-fix-verification", verify_uses_old_supporting_evidence)
        self.assert_error_contains(errors, "must cite its resolutionEvidence")

        def passed_fix_for_pending_finding(state: dict) -> None:
            valid(state)
            state["phase"] = "ACTIVE"
            finding = state["findings"][0]
            finding["decision"] = "PENDING"
            for key in ("risk", "severity", "confidence", "disposition", "resolutionEvidence"):
                finding.pop(key, None)

        errors = self.mutated_errors("valid-fix-verification", passed_fix_for_pending_finding)
        self.assert_error_contains(
            errors,
            "PASSED FIX batch requires Finding 'F1' to be remediating, resolved, rejected, or fully accepted",
        )

        def orphan_passed_fix(state: dict) -> None:
            valid(state)
            state["fixWorkflow"]["batches"].append(
                {
                    "id": "fix-orphan", "kind": "FIX", "status": "PASSED", "attempt": 1,
                    "scope": "uncovered auxiliary repair", "allowedPaths": ["src/aux.c"],
                    "acceptanceChecks": ["auxiliary regression"], "dependsOn": [],
                    "findingIds": ["F1"], "evidenceRefs": ["F1-E2"], "validatedGeneration": 1,
                }
            )

        errors = self.mutated_errors("valid-fix-verification", orphan_passed_fix)
        self.assert_error_contains(errors, "final regression must transitively depend on PASSED FIX batch 'fix-orphan'")

    def test_fix_allowed_paths_are_portable_relative_paths(self) -> None:
        def with_workflow(state: dict, allowed_path: str) -> None:
            state["phase"] = "ACTIVE"
            state["audit"]["executionMode"] = "audit-and-fix"
            state["findings"][0]["disposition"] = "REMEDIATING"
            state["findings"][0].pop("resolutionEvidence", None)
            state["fixWorkflow"] = {
                "generation": 1,
                "finalRegressionBatchId": "fix-1",
                "findingMappings": [
                    {
                        "findingId": "F1",
                        "rootCausePattern": "unchecked length",
                        "knownInstances": ["src/parser.c:90"],
                        "fixScope": "parser guard",
                        "exclusions": [],
                        "behaviorChange": "reject oversized input",
                        "acceptanceChecks": ["targeted regression"],
                        "preFixExpectedFailure": "copy is reached",
                        "regressionScope": "parser callers",
                        "residualRiskIds": [],
                    }
                ],
                "batches": [
                    {
                        "id": "fix-1", "kind": "FIX", "status": "PENDING", "attempt": 1,
                        "scope": "parser guard", "allowedPaths": [allowed_path],
                        "acceptanceChecks": ["targeted regression"], "dependsOn": [],
                        "findingIds": ["F1"], "evidenceRefs": [],
                    }
                ],
            }

        errors = self.mutated_errors("valid-fix-verification", lambda state: with_workflow(state, "../../.env"))
        self.assert_error_contains(errors, "allowedPaths[0]: must not contain empty, '.', or '..' path segments")

        errors = self.mutated_errors("valid-fix-verification", lambda state: with_workflow(state, "C:/worktree/src"))
        self.assert_error_contains(errors, "allowedPaths[0]: must be a relative path")

    def test_final_gate_finding_cannot_omit_gate_coverage(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0].pop("gates")

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "gates: required for every FINAL non-REJECTED finding")

    def test_malformed_decision_and_severity_report_errors_without_crashing(self) -> None:
        def malformed_decision(state: dict) -> None:
            state["findings"][0]["decision"] = {"bad": True}

        def malformed_severity(state: dict) -> None:
            state["findings"][0]["severity"] = ["High"]

        errors = self.mutated_errors("valid-release-gate", malformed_decision)
        self.assert_error_contains(errors, "decision: expected str")
        errors = self.mutated_errors("valid-release-gate", malformed_severity)
        self.assert_error_contains(errors, "severity: expected str")

    def test_checked_evidence_cannot_self_reference_verification_output(self) -> None:
        def mutate_files(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["checkedEvidence"] = ["F1-E1"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=mutate_files)
        self.assert_error_contains(errors, "unknown investigation evidence id 'F1-E1'")

    def test_confirmed_finding_requires_new_supporting_verification_evidence(self) -> None:
        def mutate_state(state: dict) -> None:
            finding = state["findings"][0]
            finding["supportingEvidence"] = ["R1-E1"]
            finding["provenanceEvidence"] = ["F1-E1"]
            finding["gates"]["RELEASE"]["evidenceRefs"] = ["R1-E1"]

        def mutate_files(target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["evidence"][0]["polarity"] = "context"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_state, mutate_files)
        self.assert_error_contains(errors, "CONFIRMED requires new supporting Evidence")

    def test_finding_evidence_must_belong_to_its_source_or_declared_verification_chain(self) -> None:
        def mutate(state: dict) -> None:
            finding = state["findings"][0]
            finding["provenance"] = "PRE_EXISTING"
            finding["provenanceEvidence"] = ["R2-E1"]
            finding["gates"]["RELEASE"]["applicability"] = "DOES-NOT-APPLY"
            finding["gates"]["RELEASE"]["evidenceRefs"] = ["R2-E1"]
            state["audit"]["gates"]["decisions"]["RELEASE"] = {
                "result": "READY",
                "basis": ["ALL-REQUIRED-INPUTS-SATISFIED"],
            }

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "R2-E1' is not part of this Finding's source or verification chain")

        def orphan_provenance(state: dict) -> None:
            state["findings"][0]["provenanceEvidence"] = ["R2-E1"]

        errors = self.mutated_errors("valid-release-gate", orphan_provenance)
        self.assert_error_contains(errors, "provenanceEvidence: allowed only when provenance is present")

    def test_completed_challenge_requires_evidence_polarity_for_its_result(self) -> None:
        def mutate(state: dict, target: Path) -> None:
            path = target / "verification" / "F1.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["challenge"]["evidenceRefs"] = ["R2-E1"]
            independent = target / "investigations" / "R2-independent.json"
            independent_data = json.loads(independent.read_text(encoding="utf-8"))
            independent_data["evidence"][0]["polarity"] = "context"
            independent.write_text(json.dumps(independent_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors(
            "valid-fix-verification",
            mutate_files=lambda target: mutate({}, target),
        )
        self.assert_error_contains(errors, "counter-refuted challenge requires supporting Evidence")

    def test_final_snapshot_and_material_residual_are_fail_closed(self) -> None:
        def missing_snapshot(state: dict) -> None:
            state["audit"].pop("snapshot")

        errors = self.mutated_errors("valid-ordinary-no-gate", missing_snapshot)
        self.assert_error_contains(errors, "required in FINAL state")

        def nonmaterial_residual(state: dict) -> None:
            unit = state["verificationUnits"][0]
            unit["status"] = "planned"
            for key in ("executor", "investigationFile", "reconciliations"):
                unit.pop(key, None)
            unit["residualRiskId"] = "G1"
            state["residualRisks"] = [
                {"id": "G1", "statement": "trace unavailable", "scope": "parser", "material": False}
            ]

        errors = self.mutated_errors("valid-ordinary-no-gate", nonmaterial_residual)
        self.assert_error_contains(errors, "must map to a material residual risk")

    def test_authorization_text_must_not_be_whitespace(self) -> None:
        def mutate(state: dict) -> None:
            finding = state["findings"][0]
            finding["severity"] = "Low"
            finding["risk"]["impact"] = "Low"
            finding["gates"]["RELEASE"].update(
                {
                    "treatment": "ACCEPTED",
                    "authorization": {
                        "text": "   ",
                        "auditId": "release-001",
                        "snapshot": {"kind": "deployment", "version": "release-candidate-2026-08-22"},
                        "target": "RELEASE",
                    },
                }
            )

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "authorization.text: must not be empty")

    # fixture self-test -----------------------------------------------------

    def test_missing_self_test_directory_reports_clean_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cvpa-missing-fixtures-") as raw:
            missing = Path(raw) / "missing"
            output = StringIO()
            with redirect_stdout(output):
                code = run_self_test(missing)
            self.assertEqual(code, 1)
            self.assertIn("SELF-TEST FAIL: cannot read", output.getvalue())

    def test_self_test_requires_the_intended_invalid_fixture_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cvpa-self-test-expectations-") as raw:
            fixtures = Path(raw)
            shutil.copytree(
                FIXTURES / "invalid-disposition-combination",
                fixtures / "invalid-disposition-combination",
            )
            (fixtures / "expectations.json").write_text(
                json.dumps(
                    {"invalid-disposition-combination": ["an error that cannot occur"]},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            output = StringIO()
            with redirect_stdout(output):
                code = run_self_test(fixtures)
            self.assertEqual(code, 1)
            self.assertIn("missing expected error fragments", output.getvalue())

    def test_self_test_error_count_pin_rejects_unexpected_error_counts(self) -> None:
        """The error_count pin catches duplicated/lost errors that the fragment
        check would still PASS; a wrong declared count must fail the self-test
        even when every fragment is present."""
        with tempfile.TemporaryDirectory(prefix="cvpa-self-test-count-") as raw:
            fixtures = Path(raw)
            shutil.copytree(
                FIXTURES / "invalid-disposition-combination",
                fixtures / "invalid-disposition-combination",
            )
            (fixtures / "expectations.json").write_text(
                json.dumps(
                    {
                        "invalid-disposition-combination": [
                            "explicit disposition is allowed only for CONFIRMED findings"
                        ],
                        "invalid-disposition-combination.error_count": 99,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            output = StringIO()
            with redirect_stdout(output):
                code = run_self_test(fixtures)
            self.assertEqual(code, 1)
            self.assertIn("expected 99 errors, got 1", output.getvalue())

    # decision history ------------------------------------------------------

    def test_decision_history_accepts_valid_entries(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0]["decisionHistory"] = [
                {
                    "at": "2026-08-22T00:15:00Z",
                    "summary": "Confidence Medium -> High after the runtime trace confirmed the gap",
                    "evidenceRefs": ["F1-E1"],
                }
            ]

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assertEqual([], errors)

    def test_decision_history_rejects_unknown_evidence(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0]["decisionHistory"] = [
                {"at": "2026-08-22T00:15:00Z", "summary": "Confidence raised", "evidenceRefs": ["F9-E9"]}
            ]

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "unknown evidence id 'F9-E9'")

    def test_decision_history_entry_requires_timestamp_and_summary(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0]["decisionHistory"] = [{"at": "2026-08-22T00:15:00Z"}]

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "missing required key 'summary'")

    def test_decision_history_rejects_unknown_fields(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0]["decisionHistory"] = [
                {"at": "2026-08-22T00:15:00Z", "summary": "Decision changed", "verdict": "CONFIRMED"}
            ]

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "unsupported keys")

    def test_decision_history_rejects_empty_evidence_refs(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0]["decisionHistory"] = [
                {"at": "2026-08-22T00:15:00Z", "summary": "Decision changed", "evidenceRefs": []}
            ]

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "must not be empty")

    # optional protocol fields ---------------------------------------------

    def test_pattern_scope_is_optional(self) -> None:
        def mutate(state: dict) -> None:
            del state["findings"][0]["patternScope"]

        self.assertEqual([], self.mutated_errors("valid-release-gate", mutate))

    def test_pattern_scope_value_is_still_validated_when_present(self) -> None:
        def mutate(state: dict) -> None:
            state["findings"][0]["patternScope"] = "WIDESPREAD"

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "invalid value 'WIDESPREAD'")

    def test_available_evidence_is_optional(self) -> None:
        def mutate(state: dict) -> None:
            del state["audit"]["availableEvidence"]

        self.assertEqual([], self.mutated_errors("valid-release-gate", mutate))

    def test_available_evidence_must_be_an_array_when_present(self) -> None:
        def mutate(state: dict) -> None:
            state["audit"]["availableEvidence"] = "source and tests"

        errors = self.mutated_errors("valid-release-gate", mutate)
        self.assert_error_contains(errors, "expected array")

    # new conditional fields and error pointers ------------------------------

    def test_dispatches_are_optional_but_validated_when_present(self) -> None:
        def empty(state: dict) -> None:
            state["dispatches"] = []

        errors = self.mutated_errors("valid-ordinary-no-gate", empty)
        self.assert_error_contains(errors, "must be a non-empty array when present")

        def missing_reason(state: dict) -> None:
            state["dispatches"] = [{"unit": "R7"}]

        errors = self.mutated_errors("valid-ordinary-no-gate", missing_reason)
        self.assert_error_contains(errors, "missing required key 'reason'")

        def unknown_key(state: dict) -> None:
            state["dispatches"] = [{"unit": "R7", "reason": "cancelled by the platform", "attempt": 2}]

        errors = self.mutated_errors("valid-ordinary-no-gate", unknown_key)
        self.assert_error_contains(errors, "unsupported keys")

        def recorded(state: dict) -> None:
            state["dispatches"] = [
                {"unit": "R7", "reason": "cancelled by the platform concurrency limit",
                 "residue": "%TEMP%/cvpa-r7 scratch (cleaned)"}
            ]

        self.assertEqual([], self.mutated_errors("valid-ordinary-no-gate", recorded))

    def test_prior_contact_members_are_constrained(self) -> None:
        def implementer(state: dict) -> None:
            state["audit"]["priorContact"] = ["implementer"]

        self.assertEqual([], self.mutated_errors("valid-ordinary-no-gate", implementer))

        def combined(state: dict) -> None:
            state["audit"]["priorContact"] = ["implementer", "informal-verifier"]

        self.assertEqual([], self.mutated_errors("valid-ordinary-no-gate", combined))

        def placeholder_member(state: dict) -> None:
            state["audit"]["priorContact"] = ["none"]

        errors = self.mutated_errors("valid-ordinary-no-gate", placeholder_member)
        self.assert_error_contains(errors, "invalid value 'none'")

        def duplicate_member(state: dict) -> None:
            state["audit"]["priorContact"] = ["implementer", "implementer"]

        errors = self.mutated_errors("valid-ordinary-no-gate", duplicate_member)
        self.assert_error_contains(errors, "contains duplicates")

    def test_peripheral_observations_accept_only_nonempty_strings(self) -> None:
        def recorded(target: Path) -> None:
            path = target / "investigations" / "R1-main.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["coverageSummary"]["peripheralObservations"] = ["dashboard-runtime.js:12 looks suspicious"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        self.assertEqual([], self.mutated_errors("valid-ordinary-no-gate", mutate_files=recorded))

        def malformed(target: Path) -> None:
            path = target / "investigations" / "R1-main.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["coverageSummary"]["peripheralObservations"] = [42]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-ordinary-no-gate", mutate_files=malformed)
        self.assert_error_contains(errors, "expected non-empty string")

    def test_validator_errors_carry_document_pointers(self) -> None:
        def no_discrimination(target: Path) -> None:
            path = target / "investigations" / "R1-main.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["evidence"][0]["testDiscrimination"]["result"] = "NO"
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-fix-verification", mutate_files=no_discrimination)
        self.assert_error_contains(errors, "review-dimensions.md「Test discrimination 记录」")

        def bad_disposition(state: dict) -> None:
            state["findings"][0]["decision"] = "CONDITIONAL"
            state["findings"][0]["confidence"] = "Medium"
            state["findings"][0]["disposition"] = "REMEDIATING"

        errors = self.mutated_errors("valid-release-gate", bad_disposition)
        self.assert_error_contains(errors, "audit-ledger.md「Finding」")

    # schema v3 referenced verifiedBehaviors ---------------------------------

    def test_schema_version_accepts_two_and_three_only(self) -> None:
        def v2_remains_valid(state: dict) -> None:
            state["schemaVersion"] = 2

        self.assertEqual([], self.mutated_errors("valid-blocked-with-incomplete-scope", v2_remains_valid))

        def unknown_version(state: dict) -> None:
            state["schemaVersion"] = 4

        errors = self.mutated_errors("valid-release-gate", unknown_version)
        self.assert_error_contains(errors, "must be one of [2, 3]")

    def test_v3_verified_behaviors_reject_bare_strings(self) -> None:
        def bare_string(target: Path) -> None:
            path = target / "investigations" / "R1-a.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["coverageSummary"]["verifiedBehaviors"] = ["malformed tokens are rejected"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=bare_string)
        self.assert_error_contains(errors, "schemaVersion 3 requires {behavior, evidenceRefs} objects")

    def test_v3_verified_behavior_requires_nonempty_local_evidence_refs(self) -> None:
        def missing_refs(target: Path) -> None:
            path = target / "investigations" / "R1-a.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            del data["coverageSummary"]["verifiedBehaviors"][0]["evidenceRefs"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=missing_refs)
        self.assert_error_contains(errors, "missing required key 'evidenceRefs'")

        def empty_refs(target: Path) -> None:
            path = target / "investigations" / "R1-a.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["coverageSummary"]["verifiedBehaviors"][0]["evidenceRefs"] = []
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=empty_refs)
        self.assert_error_contains(errors, "must reference DIRECT evidence from this artifact")

        def foreign_ref(target: Path) -> None:
            path = target / "investigations" / "R1-a.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["coverageSummary"]["verifiedBehaviors"][0]["evidenceRefs"] = ["R2-E1"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        errors = self.mutated_errors("valid-release-gate", mutate_files=foreign_ref)
        self.assert_error_contains(errors, "unknown evidence id 'R2-E1' in this artifact")

    def test_v2_verified_behaviors_stay_string_arrays(self) -> None:
        def string_form(target: Path) -> None:
            path = target / "investigations" / "R1-a.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["coverageSummary"]["verifiedBehaviors"] = ["upload path checked"]
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        self.assertEqual([], self.mutated_errors("valid-blocked-with-incomplete-scope", mutate_files=string_form))

    # reporting hygiene -----------------------------------------------------

    def test_uncleaned_probes_are_reported_once(self) -> None:
        """The probe check used to run twice, doubling the error count."""

        def add_probe(target: Path) -> None:
            (target / "probes").mkdir(exist_ok=True)
            (target / "probes" / "scratch.txt").write_text("junk", encoding="utf-8")

        errors = self.mutated_errors("valid-ordinary-no-gate", mutate_files=add_probe)
        matching = [error for error in errors if "FINAL audit must clean temporary probes" in error]
        self.assertEqual(1, len(matching), f"probes reported {len(matching)} times:\n" + "\n".join(errors))

    def test_unfinished_temporary_state_is_reported_once(self) -> None:
        """It used to trip both the layout allowlist and the dedicated check."""

        def add_temp(target: Path) -> None:
            (target / "state.json.bak").write_text("{}", encoding="utf-8")

        errors = self.mutated_errors("valid-ordinary-no-gate", mutate_files=add_temp)
        matching = [error for error in errors if "state.json" in error and "temporary" in error]
        self.assertEqual(1, len(matching), f"temporary state reported {len(matching)} times:\n" + "\n".join(errors))
        # the layout allowlist must not also flag it as an unsupported entry
        self.assertFalse(
            any("unsupported state-directory entry" in error for error in errors),
            "temporary state file is also flagged by the layout allowlist:\n" + "\n".join(errors),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
