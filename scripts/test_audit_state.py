#!/usr/bin/env python3
"""Tests for audit_state.py.

The helper is optional, so these tests pin the things that actually matter:
it must remove mechanical work without ever making a semantic decision, and
it must refuse to launder evidence gathered against another audit.
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from audit_state import main, resolve_inside  # noqa: E402
from validate_audit_state import validate_state  # noqa: E402

FIXTURES = SCRIPT_DIR / "fixtures"
FIXTURE = "valid-release-gate"


class AuditStateTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cvpa-state-")
        self.raw = Path(self._tmp.name)
        self.dir = self.raw / FIXTURE
        shutil.copytree(FIXTURES / FIXTURE, self.dir)
        self.state_path = self.dir / "state.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # helpers ---------------------------------------------------------------

    def state(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def save(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def artifact_paths(self) -> list[Path]:
        state = self.state()
        paths = []
        for unit in state["verificationUnits"]:
            if unit.get("investigationFile"):
                paths.append(self.dir / unit["investigationFile"])
        for finding in state["findings"]:
            if finding.get("verificationFile"):
                paths.append(self.dir / finding["verificationFile"])
        return paths

    def read_artifact(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def write_artifact(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def run_helper(self, *argv: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue() + err.getvalue()

    def init_args(self, target: Path, **overrides: str | None) -> list[str]:
        args = ["init", str(target), "--id", "demo-1",
                "--target", "the login endpoint",
                "--scope", "public login path",
                "--objectives", "decide whether auth can be bypassed"]
        for key, value in overrides.items():
            flag = f"--{key.replace('_', '-')}"
            # a None value means a valueless flag such as --force
            args.append(flag) if value is None else args.extend([flag, value])
        return args

    # init ------------------------------------------------------------------

    def test_init_creates_a_skeleton(self) -> None:
        target = self.raw / "fresh"
        code, out = self.run_helper(*self.init_args(target))
        self.assertEqual(0, code, out)
        state = json.loads((target / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(3, state["schemaVersion"])
        self.assertEqual("ACTIVE", state["phase"])
        self.assertEqual("demo-1", state["audit"]["id"])
        self.assertIsNone(state["audit"]["snapshot"])
        self.assertEqual([], state["claims"])
        self.assertTrue((target / "investigations").is_dir())
        self.assertTrue((target / "verification").is_dir())

    def test_init_skeleton_passes_the_validator(self) -> None:
        """An earlier variant emitted empty timestamps and failed immediately."""
        target = self.raw / "skeleton"
        code, out = self.run_helper(*self.init_args(target))
        self.assertEqual(0, code, out)
        result = validate_state(target / "state.json")
        self.assertEqual([], result.errors, "\n".join(result.errors))

    def test_init_refuses_to_overwrite_without_force(self) -> None:
        target = self.raw / "fresh"
        self.run_helper(*self.init_args(target))
        code, out = self.run_helper(*self.init_args(target))
        self.assertEqual(1, code)
        self.assertIn("already exists", out)

    def test_init_force_overwrites(self) -> None:
        target = self.raw / "fresh"
        self.run_helper(*self.init_args(target))
        code, _ = self.run_helper(*self.init_args(target, force=None))
        self.assertEqual(0, code)

    def test_init_accepts_a_snapshot_object(self) -> None:
        target = self.raw / "withgit"
        snapshot = json.dumps({"kind": "git", "base": None, "head": "a" * 40})
        code, out = self.run_helper(*self.init_args(target, snapshot_json=snapshot))
        self.assertEqual(0, code, out)
        stored = json.loads((target / "state.json").read_text(encoding="utf-8"))["audit"]["snapshot"]
        self.assertEqual("git", stored["kind"])
        self.assertEqual("a" * 40, stored["head"])

    def test_init_requires_an_objective(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            self.run_helper("init", str(self.raw / "noobj"), "--id", "x",
                     "--target", "t", "--scope", "s")
        self.assertEqual(2, ctx.exception.code)

    def test_init_requires_assumption_when_basis_is_assumed(self) -> None:
        code, out = self.run_helper(*self.init_args(self.raw / "a1", basis="ASSUMED"))
        self.assertEqual(1, code)
        self.assertIn("--basis ASSUMED requires a non-empty --assumption", out)

    def test_init_rejects_assumption_unless_basis_is_assumed(self) -> None:
        code, out = self.run_helper(*self.init_args(self.raw / "a2", assumption="guessed the range"))
        self.assertEqual(1, code)
        self.assertIn("--assumption is only allowed when --basis is ASSUMED", out)

    def test_init_rejects_an_illegal_audit_id(self) -> None:
        code, out = self.run_helper(*self.init_args(self.raw / "a3", **{"id": "bad/id"}))
        self.assertEqual(1, code)
        self.assertIn("must match", out)

    def test_init_profile_adds_an_extra_objective_profile(self) -> None:
        """SKILL.md asks security / fix-verification audits to add a profile."""
        target = self.raw / "profiled"
        code, out = self.run_helper(*self.init_args(target, profile="security"))
        self.assertEqual(0, code, out)
        state = json.loads((target / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(["general", "security"], state["audit"]["objectiveProfiles"])

    def test_init_profile_is_deduplicated_and_general_appears_once(self) -> None:
        """A repeated --profile must not create the duplicate the validator rejects."""
        target = self.raw / "deduped"
        args = self.init_args(target)
        args += ["--profile", "security", "--profile", "security", "--profile", "general"]
        code, out = self.run_helper(*args)
        self.assertEqual(0, code, out)
        state = json.loads((target / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(["general", "security"], state["audit"]["objectiveProfiles"])

    # bind ------------------------------------------------------------------

    def test_bind_accepts_an_already_matching_binding(self) -> None:
        code, out = self.run_helper("bind", str(self.dir))
        self.assertEqual(0, code, out)
        self.assertIn("all referenced artifacts bound to", out)

    def test_bind_stamps_an_unbound_artifact(self) -> None:
        path = self.artifact_paths()[0]
        data = self.read_artifact(path)
        data.pop("auditBinding", None)
        self.write_artifact(path, data)

        code, out = self.run_helper("bind", str(self.dir))
        self.assertEqual(0, code, out)
        refreshed = self.read_artifact(path)
        self.assertEqual(self.state()["audit"]["id"], refreshed["auditBinding"]["auditId"])
        self.assertEqual("auditBinding", list(refreshed.keys())[0])

    def test_bind_refuses_to_overwrite_a_mismatched_binding(self) -> None:
        """Re-stamping would launder evidence gathered against another audit."""
        path = self.artifact_paths()[0]
        data = self.read_artifact(path)
        data["auditBinding"] = {"auditId": "another-audit", "snapshot": None}
        self.write_artifact(path, data)

        code, out = self.run_helper("bind", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("refusing to overwrite", out)
        self.assertIn("must be re-gathered", out)
        self.assertEqual("another-audit", self.read_artifact(path)["auditBinding"]["auditId"])

    def test_bind_force_overwrites_a_mismatched_binding(self) -> None:
        path = self.artifact_paths()[0]
        data = self.read_artifact(path)
        data["auditBinding"] = {"auditId": "another-audit", "snapshot": None}
        self.write_artifact(path, data)

        code, out = self.run_helper("bind", str(self.dir), "--force")
        self.assertEqual(0, code, out)
        self.assertEqual(self.state()["audit"]["id"],
                         self.read_artifact(path)["auditBinding"]["auditId"])

    def test_bind_check_is_read_only(self) -> None:
        path = self.artifact_paths()[0]
        data = self.read_artifact(path)
        data.pop("auditBinding", None)
        self.write_artifact(path, data)
        before = path.read_text(encoding="utf-8")

        code, out = self.run_helper("bind", str(self.dir), "--check")
        self.assertEqual(1, code)
        self.assertIn("would be bound", out)
        self.assertEqual(before, path.read_text(encoding="utf-8"))

    def test_bind_reports_missing_artifact(self) -> None:
        (self.dir / "verification" / "F1.json").unlink()
        code, out = self.run_helper("bind", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("not found", out)

    def test_bind_artifact_targets_a_single_file(self) -> None:
        paths = self.artifact_paths()
        for path in paths:
            data = self.read_artifact(path)
            data.pop("auditBinding", None)
            self.write_artifact(path, data)

        code, _ = self.run_helper("bind", str(self.dir), "--artifact", "investigations/R1-a.json")
        self.assertEqual(0, code)
        self.assertIn("auditBinding", self.read_artifact(paths[0]))
        self.assertNotIn("auditBinding", self.read_artifact(paths[1]))

    def test_bind_covers_every_referenced_artifact(self) -> None:
        for path in self.artifact_paths():
            data = self.read_artifact(path)
            data.pop("auditBinding", None)
            self.write_artifact(path, data)

        self.run_helper("bind", str(self.dir))
        audit_id = self.state()["audit"]["id"]
        for path in self.artifact_paths():
            self.assertEqual(audit_id, self.read_artifact(path)["auditBinding"]["auditId"])

    # path safety ----------------------------------------------------------

    def test_bind_artifact_rejects_an_absolute_path_outside_the_state_root(self) -> None:
        """An absolute --artifact must be checked, not trusted and written to."""
        outside = self.raw / "outside-artifact.json"
        original = {"unitId": "R1"}
        outside.write_text(json.dumps(original), encoding="utf-8")

        with self.assertRaises(SystemExit) as ctx:
            self.run_helper("bind", str(self.dir), "--artifact", str(outside.resolve()), "--force")
        self.assertIn("escapes the audit directory", str(ctx.exception))
        self.assertEqual(original, json.loads(outside.read_text(encoding="utf-8")))

    def test_resolve_inside_refuses_to_follow_a_symlink(self) -> None:
        """The validator has the full symlink/junction check; this is the light guard."""
        target = self.artifact_paths()[0]
        link = self.dir / "investigations" / "linked.json"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks cannot be created in this environment")

        with self.assertRaises(SystemExit) as ctx:
            resolve_inside(self.dir, "investigations/linked.json")
        self.assertIn("refusing to follow a symlink", str(ctx.exception))

    # lint ------------------------------------------------------------------

    def test_lint_accepts_the_reference_fixture(self) -> None:
        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(0, code, out)

    def test_lint_detects_stale_binding(self) -> None:
        path = self.artifact_paths()[0]
        data = self.read_artifact(path)
        data["auditBinding"] = {"auditId": "wrong-id", "snapshot": None}
        self.write_artifact(path, data)

        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("auditBinding does not match", out)

    def test_lint_detects_recommendation_result_mismatch(self) -> None:
        state = self.state()
        state["verificationUnits"][0]["reconciliations"][0]["result"] = "REFUTED"
        self.save(state)

        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("recommendation=promote-to-finding", out)
        self.assertIn("expected FINDING", out)

    def test_lint_detects_source_hypotheses_mismatch(self) -> None:
        state = self.state()
        state["findings"][0]["sourceHypotheses"] = ["R1-H1", "R9-H1"]
        self.save(state)

        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("sourceHypotheses does not mirror", out)
        self.assertIn("R9-H1", out)

    def test_lint_detects_wrong_hypothesis_prefix(self) -> None:
        path = self.dir / "investigations" / "R1-a.json"
        data = self.read_artifact(path)
        data["hypotheses"][0]["id"] = "X9-H1"
        self.write_artifact(path, data)

        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("must use prefix R1-H<n>", out)

    def test_lint_detects_wrong_verification_evidence_prefix(self) -> None:
        path = self.dir / "verification" / "F1.json"
        data = self.read_artifact(path)
        data["evidence"][0]["id"] = "F9-E1"
        self.write_artifact(path, data)

        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("must use prefix F1-E<n>", out)

    def test_lint_detects_verification_method_drift(self) -> None:
        path = self.dir / "verification" / "F1.json"
        data = self.read_artifact(path)
        data["method"] = "user-path-trace"
        self.write_artifact(path, data)

        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("!= verificationMethod", out)

    def test_lint_detects_unknown_finding_reference(self) -> None:
        state = self.state()
        state["verificationUnits"][0]["reconciliations"][0]["findingId"] = "F99"
        self.save(state)

        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("unknown finding 'F99'", out)

    def test_lint_is_read_only(self) -> None:
        before = {p: p.read_text(encoding="utf-8") for p in self.dir.rglob("*.json")}
        self.run_helper("lint", str(self.dir))
        after = {p: p.read_text(encoding="utf-8") for p in self.dir.rglob("*.json")}
        self.assertEqual(before, after)

    # check -----------------------------------------------------------------

    def test_check_state_mode_accepts_a_referenced_artifact(self) -> None:
        code, out = self.run_helper("check", str(self.dir), "--artifact", "investigations/R1-a.json")
        self.assertEqual(0, code, out)

    def test_check_state_mode_flags_content_drift(self) -> None:
        data = self.read_artifact(self.dir / "investigations" / "R1-a.json")
        data["hypotheses"][0]["recommendation"] = "close"
        staged = self.raw / "drifted.json"
        self.write_artifact(staged, data)

        code, out = self.run_helper("check", str(self.dir), "--artifact", str(staged))
        self.assertEqual(1, code)
        self.assertIn("supported hypothesis must be promoted to a Finding", out)

    def test_check_standalone_runs_without_state(self) -> None:
        staged = self.raw / "standalone.json"
        self.write_artifact(staged, self.read_artifact(self.dir / "investigations" / "R1-a.json"))
        code, out = self.run_helper(
            "check", "--standalone", "--artifact", str(staged),
            "--audit-id", "release-001",
            "--snapshot-json", json.dumps({"kind": "deployment", "version": "release-candidate-2026-08-22"}),
            "--unit-id", "R1", "--claim-id", "Q1", "--method", "implementation-trace",
        )
        self.assertEqual(0, code, out)
        self.assertIn("PASS", out)

    def test_check_standalone_flags_an_inconsistent_hypothesis(self) -> None:
        data = self.read_artifact(self.dir / "investigations" / "R1-a.json")
        data["hypotheses"][0]["result"] = "refuted"
        data["hypotheses"][0]["recommendation"] = "promote-to-finding"
        staged = self.raw / "inconsistent.json"
        self.write_artifact(staged, data)
        code, out = self.run_helper(
            "check", "--standalone", "--artifact", str(staged),
            "--audit-id", "release-001",
            "--snapshot-json", json.dumps({"kind": "deployment", "version": "release-candidate-2026-08-22"}),
            "--unit-id", "R1", "--claim-id", "Q1", "--method", "implementation-trace",
        )
        self.assertEqual(1, code)
        self.assertIn("refuted hypothesis must be closed", out)

    def test_check_standalone_requires_injected_context(self) -> None:
        code, out = self.run_helper("check", "--standalone", "--artifact", "x.json")
        self.assertEqual(1, code)
        self.assertIn("--standalone requires", out)

    # receive ---------------------------------------------------------------

    def test_receive_writes_a_byte_identical_canonical_copy(self) -> None:
        target = self.dir / "investigations" / "R1-a.json"
        original = target.read_bytes()
        target.unlink()
        staged = self.raw / "staged.json"
        staged.write_bytes(original)
        state_before = self.state_path.read_text(encoding="utf-8")

        code, out = self.run_helper("receive", str(self.dir), "--staged", str(staged))
        self.assertEqual(0, code, out)
        self.assertEqual(original, target.read_bytes())
        self.assertEqual(state_before, self.state_path.read_text(encoding="utf-8"))
        self.assertIn("main-agent acceptance actions", out)

    def test_receive_refuses_a_mismatched_binding(self) -> None:
        target = self.dir / "investigations" / "R1-a.json"
        data = self.read_artifact(target)
        data["auditBinding"]["auditId"] = "another-audit"
        staged = self.raw / "foreign.json"
        self.write_artifact(staged, data)
        target.unlink()

        code, out = self.run_helper("receive", str(self.dir), "--staged", str(staged))
        self.assertEqual(1, code)
        self.assertIn("must equal current audit id", out)
        self.assertFalse(target.exists())

    def test_receive_refuses_to_replace_without_force(self) -> None:
        staged = self.raw / "same.json"
        staged.write_bytes((self.dir / "investigations" / "R1-a.json").read_bytes())
        code, out = self.run_helper("receive", str(self.dir), "--staged", str(staged))
        self.assertEqual(1, code)
        self.assertIn("already exists", out)

    def test_receive_force_reports_a_structural_diff(self) -> None:
        data = self.read_artifact(self.dir / "investigations" / "R1-a.json")
        extra_hypothesis = dict(data["hypotheses"][0])
        extra_hypothesis["id"] = "R1-H2"
        data["hypotheses"].append(extra_hypothesis)
        staged = self.raw / "extended.json"
        self.write_artifact(staged, data)

        code, out = self.run_helper("receive", str(self.dir), "--staged", str(staged), "--force")
        self.assertEqual(0, code, out)
        self.assertIn("hypotheses added: R1-H2", out)
        refreshed = self.read_artifact(self.dir / "investigations" / "R1-a.json")
        self.assertEqual("R1-H2", refreshed["hypotheses"][1]["id"])

    def test_receive_rejects_staged_for_an_unknown_unit(self) -> None:
        data = self.read_artifact(self.dir / "investigations" / "R1-a.json")
        data["unitId"] = "R9"
        staged = self.raw / "unknown-unit.json"
        self.write_artifact(staged, data)

        code, out = self.run_helper("receive", str(self.dir), "--staged", str(staged))
        self.assertEqual(1, code)
        self.assertIn("no verification unit 'R9'", out)

    # verify ----------------------------------------------------------------

    def test_verify_delegates_to_the_validator(self) -> None:
        code, out = self.run_helper("verify", str(self.dir))
        self.assertEqual(0, code, out)
        self.assertIn("PASS", out)

    def test_verify_fails_fast_on_a_broken_state(self) -> None:
        state = self.state()
        state["findings"][0]["decision"] = "NOT-A-DECISION"
        self.save(state)
        code, out = self.run_helper("verify", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("FAIL", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
