#!/usr/bin/env python3
"""Tests for audit_state_helper.py.

The helpers are optional, so these tests pin the one thing that matters:
they must automate mechanical work without ever making a semantic decision,
and they must never silently corrupt a state.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from audit_state_helper import main  # noqa: E402
from validate_audit_state import validate_state  # noqa: E402

FIXTURES = SCRIPT_DIR / "fixtures"
FIXTURE = "valid-release-gate"
PY_ARGS = ["python", "-B"]


class HelperTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cvpa-helper-")
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

    def unit_file(self) -> Path:
        state = self.state()
        for unit in state["verificationUnits"]:
            if unit.get("investigationFile"):
                return self.dir / unit["investigationFile"]
        self.fail("fixture has no investigationFile")

    def run_helper(self, *argv: str) -> tuple[int, str]:
        import io
        from contextlib import redirect_stdout, redirect_stderr
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue() + err.getvalue()

    # init ------------------------------------------------------------------

    def test_init_creates_a_skeleton(self) -> None:
        target = self.raw / "fresh"
        code, out = self.run_helper(
            "init", str(target),
            "--audit-id", "fresh-1",
            "--target", "the login endpoint",
            "--scope", "public login path",
            "--objective", "decide whether auth can be bypassed",
        )
        self.assertEqual(0, code, out)
        state = json.loads((target / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(2, state["schemaVersion"])
        self.assertEqual("ACTIVE", state["phase"])
        self.assertEqual("fresh-1", state["audit"]["id"])
        self.assertIsNone(state["audit"]["snapshot"])
        self.assertEqual([], state["claims"])
        self.assertEqual([], state["findings"])
        self.assertTrue((target / "investigations").is_dir())
        self.assertTrue((target / "verification").is_dir())

    def test_init_refuses_to_overwrite_without_force(self) -> None:
        target = self.raw / "fresh"
        self.run_helper("init", str(target), "--audit-id", "a",
                        "--target", "t", "--scope", "s", "--objective", "o")
        code, out = self.run_helper("init", str(target), "--audit-id", "b",
                                    "--target", "t", "--scope", "s", "--objective", "o")
        self.assertEqual(1, code)
        self.assertIn("already exists", out)

    def test_init_skeleton_passes_the_validator(self) -> None:
        """The skeleton is only useful if the validator already accepts it.

        An earlier version emitted empty startedAt/updatedAt and produced a
        skeleton that failed immediately; this pins that regression.
        """
        target = self.raw / "skeleton"
        code, out = self.run_helper(
            "init", str(target),
            "--audit-id", "skeleton-1",
            "--target", "the login endpoint",
            "--scope", "public login path",
            "--objective", "decide whether auth can be bypassed",
        )
        self.assertEqual(0, code, out)
        result = validate_state(target / "state.json")
        self.assertEqual([], result.errors, "\n".join(result.errors))

    def test_init_accepts_a_git_snapshot(self) -> None:
        target = self.raw / "withgit"
        code, out = self.run_helper(
            "init", str(target), "--audit-id", "g1",
            "--target", "t", "--scope", "s", "--objective", "o",
            "--snapshot-kind", "git", "--head", "a" * 40,
        )
        self.assertEqual(0, code, out)
        snapshot = json.loads((target / "state.json").read_text(encoding="utf-8"))["audit"]["snapshot"]
        self.assertEqual({"kind": "git", "head": "a" * 40, "base": None}, snapshot)

    def test_init_requires_an_objective(self) -> None:
        target = self.raw / "noobj"
        # argparse signals usage errors with SystemExit, which is the CLI convention
        with self.assertRaises(SystemExit) as ctx:
            self.run_helper("init", str(target), "--audit-id", "x",
                            "--target", "t", "--scope", "s")
        self.assertEqual(2, ctx.exception.code)

    # bind ------------------------------------------------------------------

    def test_bind_updates_stale_binding(self) -> None:
        state = self.state()
        state["audit"]["snapshot"] = {"kind": "git", "base": None, "head": "b" * 40}
        self.save(state)

        code, out = self.run_helper("bind", str(self.dir), "--no-validate")
        self.assertEqual(0, code, out)

        for relative in state["findings"][0]["verificationFile"],:
            data = json.loads((self.dir / relative).read_text(encoding="utf-8"))
            self.assertEqual(state["audit"]["id"], data["auditBinding"]["auditId"])
            self.assertEqual(state["audit"]["snapshot"], data["auditBinding"]["snapshot"])

    def test_bind_is_idempotent(self) -> None:
        self.run_helper("bind", str(self.dir), "--no-validate")
        before = self.unit_file().read_text(encoding="utf-8")
        code, out = self.run_helper("bind", str(self.dir), "--no-validate")
        self.assertEqual(0, code, out)
        self.assertEqual(before, self.unit_file().read_text(encoding="utf-8"))

    def test_bind_check_does_not_modify(self) -> None:
        state = self.state()
        state["audit"]["snapshot"] = {"kind": "git", "base": None, "head": "c" * 40}
        self.save(state)
        before = self.unit_file().read_text(encoding="utf-8")

        code, out = self.run_helper("bind", str(self.dir), "--check")
        self.assertEqual(1, code)
        self.assertIn("would update", out)
        self.assertEqual(before, self.unit_file().read_text(encoding="utf-8"))

    def test_bind_reports_missing_artifact(self) -> None:
        (self.dir / "verification" / "F1.json").unlink()
        code, out = self.run_helper("bind", str(self.dir), "--check")
        self.assertEqual(1, code)
        self.assertIn("missing referenced artifacts", out)

    def test_bind_keeps_auditbinding_first(self) -> None:
        # rewriting must not reorder keys: auditBinding stays the first entry
        path = self.unit_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("auditBinding")
        data["auditBinding"] = {"auditId": "stale", "snapshot": None}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        self.run_helper("bind", str(self.dir), "--no-validate")
        keys = list(json.loads(path.read_text(encoding="utf-8")).keys())
        self.assertEqual("auditBinding", keys[0])

    # lint ------------------------------------------------------------------

    def test_lint_accepts_the_reference_fixture(self) -> None:
        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(0, code, out)

    def test_lint_detects_stale_binding(self) -> None:
        path = self.unit_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["auditBinding"] = {"auditId": "wrong-id", "snapshot": None}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

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
        path = self.unit_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["hypotheses"][0]["id"] = "X9-H1"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("must use prefix R1-H<n>", out)

    def test_lint_detects_wrong_verification_evidence_prefix(self) -> None:
        path = self.dir / "verification" / "F1.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["evidence"][0]["id"] = "F9-E1"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("must use prefix F1-E<n>", out)

    def test_lint_detects_verification_method_drift(self) -> None:
        path = self.dir / "verification" / "F1.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["method"] = "user-path-trace"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("method 'user-path-trace' != verificationMethod", out)

    def test_lint_detects_unknown_finding_reference(self) -> None:
        state = self.state()
        state["verificationUnits"][0]["reconciliations"][0]["findingId"] = "F99"
        self.save(state)

        code, out = self.run_helper("lint", str(self.dir))
        self.assertEqual(1, code)
        self.assertIn("unknown finding 'F99'", out)

    def test_lint_is_read_only(self) -> None:
        before = {p: p.read_text(encoding="utf-8")
                  for p in self.dir.rglob("*.json")}
        self.run_helper("lint", str(self.dir))
        after = {p: p.read_text(encoding="utf-8")
                 for p in self.dir.rglob("*.json")}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
