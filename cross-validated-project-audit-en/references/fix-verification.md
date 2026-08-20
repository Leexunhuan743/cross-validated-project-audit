# Fix and Fix-Commit Verification

Load this file when `executionMode=audit-and-fix`, when `objectiveProfile` contains `fix-verification`, or when the audited artifact itself is a remediation commit/branch. The goal is not to prove “something changed,” but to prove the original Finding is gone, all confirmed same-pattern instances are handled, tests detect reversion, and no more significant new defects were introduced.

## 1. Build the remediation map

If the current audit has no reusable normalized original Finding, first treat defect claims from the user description, issue/PR, historical report, or commit message only as Hypothesis seeds. Rebuild and decide them through the Skill’s H/E/F/Decision flow. Never treat an old report saying “bug/High/fixed” as automatically confirmed fact. Then build, for every original Finding:

`Finding | Root-cause pattern | Known instances | Fix scope | Explicit exclusions | Behavior change | Acceptance test | PRE-fix should fail | Regression scope | Residual risk`

Write the remediation map into authoritative audit state as `fix-map` (`fix-map.md` in persistent mode; one row per Finding, updated as batches progress).

Read PRE-fix code and the original report, and reconcile the actual diff, callers, public entry points, and tests. Do not rely only on commit messages or “tests pass.”

## 2. Partition batches dynamically

Group fixes using these factors rather than a fixed item count:

- Shared root cause and repair strategy.
- Same subsystem, data boundary, or lifecycle.
- Can be validated by the same acceptance commands.
- Same rollback, compatibility, and data risk.
- Would otherwise mask each other’s failure cause.

High-risk, irreversible, hard-to-rollback issues, or issues with complex evidence requirements, should be isolated. Multiple low-risk instances with the same root cause and validation path may be combined. Every batch declares allowed modification paths, acceptance conditions, and stop conditions.

Then write the batches as an explicit dependency graph, one row per batch:

```text
| Batch | Depends on | Root cause/subsystem | Allowed paths | Acceptance command | Inter-batch gate status/basis |
|---|---|---|---|---|---|
| fix-batch-1 | — | Root cause A | … | … | PENDING |
| verify-batch-1 | fix-batch-1 | — | — | … | PENDING |
| full regression | all verify batches | — | — | … | PENDING |
```

Inter-batch gate status uses only `PENDING` / `PASSED` / `FAILED`.

Store the batch dependency graph at the top of authoritative `fix-map` (`fix-map.md` in persistent mode) and keep it synchronized with batch state.

Inter-batch gate rules:

- Downstream work may begin only after every dependency reaches `PASSED`; `PENDING` / `FAILED` block downstream work.
- `fix-batch-*`: after the fix is implemented, targeted checks pass, and every still-actionable Finding in the batch has entered `FIX-IN-PROGRESS`, the batch may become `PASSED` and unlock its verification batch. Findings explicitly moved to `ACCEPTED-RISK` or Decision=`REJECTED` do not block this batch. Do **not** require `FIXED-VERIFIED` at this stage.
- `verify-batch-*`: may become `PASSED` only after independent review and main-agent verification succeed, actionable Findings reach `FIXED-VERIFIED`, and accepted-risk Findings reach `ACCEPTED-RISK`.
- `full regression`: may become `PASSED` only after all dependent verification batches are `PASSED`, final regression succeeds, and no unresolved new Critical/High issue remains.
- Entering a downstream batch early is a process defect and must be disclosed in the completion checklist/report.

## 3. Confirm pattern scope

Before implementation, re-check the original Finding’s pattern scope:

1. Confirm the root-cause pattern and at least one real instance.
2. Define a safe counterexample to avoid blindly replacing similar code.
3. Search boundedly for same-pattern entry points within authorized subsystems.
4. Record confirmed instances, excluded instances, and uncovered scope.
5. If whole-repository expansion would be required, report the need for a dedicated audit first.

A fix must not address only the first reported location, and must not mass-edit based on “possibly systemic” without verification.

## 4. Implementation and main-agent verification

1. For Git workspaces, before implementation run `git status --short` and `git diff --stat` to capture existing changes. Separate user changes from this remediation; declare commit boundaries for mixed files and do not pull unrelated edits into the fix. For non-Git artifacts, record pre-fix state using their native version/copy mechanism. Implement the smallest root-cause-level fix while protecting the user’s existing work.
2. Run targeted checks, then risk-proportionate regression checks.
3. Prefer discrimination validation on the PRE-fix version. If restoring an old guard, mutating code, or injecting failures is required, do it only in an external copy, temporary worktree, or another disposable environment.
4. For runtime, user-path, platform, concurrency, and third-party semantics, exercise the real public path and record new DIRECT Evidence. If the original Finding has no final Decision yet, the main agent uses that Evidence to decide it. If the Finding already has a final Decision and the current task only verifies remediation, a temporary verification gap must not rewrite the original Decision; keep remediation status `FIX-IN-PROGRESS` and record `VERIFICATION-GAP`.
5. Confirm that all known confirmed instances are fixed or directly excluded. Check replaced-but-still-live helpers, writers, routes, exports, feature flags, and legacy data paths.

## 5. Heterogeneous-method re-review

For every affected subsystem, first choose **at least one verification archetype different from the original primary discovery method**, then assign a read-only executor who did not implement the fix and has not read other re-review conclusions. Provide the Finding→fix map, exact diff, acceptance criteria, baseline failures, pattern scope, and allowed checks. Critical/High fixes must not merely swap in another agent to repeat patch review. Prefer methods that directly distinguish PRE-fix from POST-fix, such as `user-path-trace`, `test-discrimination`, `state-invariant-analysis`, or another suitable archetype. Require the reviewer to answer:

- Is the original Finding actually gone, and what is the direct Evidence?
- Are all confirmed same-pattern instances handled, and are exclusions safe?
- Would the new tests fail under PRE-fix behavior?
- Did the fix break legacy data/callers, error/cancel paths, recovery, or rollback?
- Are replaced old entry points still reachable?
- Did the fix introduce a new material regression Hypothesis? If so, record H/E; the main agent decides final Finding/Decision/Severity/Confidence under the assessment model.

The reviewer remains read-only and must not modify the project just to satisfy review formality. In normal mode, create new risk units in `coverage.md` and write investigation artifacts to `investigations/<unit>-fix-<batch>.md`. In explicit degraded mode without coverage, record risk surface/claim/method/scope in the investigation header and disclose the missing matrix. If the original method cannot run and a replacement archetype is used, update coverage or degraded investigation state explicitly; do not silently substitute it.

For docs/pure-text fixes that meet §8 applicability, the main agent may apply the lightweight criteria directly without forcing a new agent chain. Critical/High Findings still require heterogeneous-method re-review under §7 item 3.

## 6. Verification-batch feedback

- `FIX-STILL-FAILS`: repair and rerun affected checks.
- `CLAIM-REFUTED`: record the main agent’s counterevidence; do not change correct code merely to satisfy an agent opinion.
- `MISSED-INSTANCE`: return to pattern scope and determine whether it is an isolated miss or a scope-definition error.
- `NEW-REGRESSION`: first record new H/E; after main-agent disconfirmation, normalize a Finding and decide Decision/Severity/Confidence. Any new CONFIRMED Critical/High must be resolved before the next batch.
- `VERIFICATION-GAP`: state the missing environment/platform/contract. Do not change the existing Finding’s Decision; an incompletely verified fix remains `FIX-IN-PROGRESS`.

Update authoritative `fix-map` for every batch. Update authoritative ledger only when Decision, remediation status, or decisive Evidence actually changes. Move to the next batch only after the main agent confirms the inter-batch gate has passed.

`FIX-STILL-FAILS` / `CLAIM-REFUTED` / `MISSED-INSTANCE` / `NEW-REGRESSION` / `VERIFICATION-GAP` are intra-batch feedback and do not go in the ledger Decision column. Only final Finding Decision/remediation changes, decisive Evidence changes, or a new regression Finding update `ledger.md`.

After a repaired Finding is verified gone, change authoritative ledger remediation status from `OPEN` / `FIX-IN-PROGRESS` to `FIXED-VERIFIED`. If the risk is explicitly accepted, set `ACCEPTED-RISK`. Remediation status is orthogonal to Decision (whether the issue was real): `CONFIRMED` means the issue was confirmed to exist, not that it remains unfixed.

## 7. Closure gate

1. Every original Finding has final Decision, pattern-scope conclusion, and remediation status. Findings that required repair also have fix location and acceptance Evidence; accepted-risk or rejected Findings record the corresponding basis.
2. All confirmed same-pattern instances are handled or explicitly excluded; uncovered scope is disclosed separately.
3. Critical/High fixes receive at least one verification archetype different from the original primary discovery method, executed by an information-isolated read-only reviewer, plus direct main-agent verification.
4. Update CHANGELOG, generated artifacts, or release notes only when project policy, plan, or the user requires it.
5. For Git-backed artifacts, inspect delivery completeness (missing/stray files, exports, lockfiles, vendor files, markers, generated artifacts, ignore rules). For all artifacts, clean temporary evidence packs, probes, and isolated environments, and confirm the final artifact contains only intended modifications.
6. Reconcile the batch dependency graph: every batch has gate status and acceptance basis, and the gate passed before downstream work began. Any skipped inter-batch gate and rationale is reported.
7. Run final regression and report unrun checks, pre-existing failures, and platform gaps.
8. Docs/pure-text artifacts that meet §8 applicability use the lightweight criteria (main-agent direct review; Critical/High still require heterogeneous-method re-review).

## 8. Fix acceptance for docs/pure-text artifacts (lightweight criteria)

When the audited object is a document, report, plan, or a pure-text configuration for which no parser, schema, build, load, runtime, or other executable/decidable validation path actually exists, the earlier discrimination tests/acceptance commands do not directly apply. Configurations that do have such paths still use the normal verification flow. Under the lightweight criteria:

1. **Item-by-item reconciliation**: for every confirmed issue, check Finding → fix location → pass condition and verify it is implemented. The old wording no longer appears, including synonymous stale rewrites. Historical/change-log references that explicitly record the old value do not count as stale residue.
2. **Residual scan**: scan the full artifact for old phrases, IDs, or deleted filenames related to the fixed pattern and confirm no live references remain.
3. **Re-read and cross-reference**: re-read every changed region. Rebuild “claim → evidence/source” mappings for affected critical claims. Confirm no new inconsistency in counts, numbering ranges, section cross-references, or version citations vs body text.
4. **Trace**: record the revision according to the artifact’s own conventions (version note/change-log section), and synchronize header metadata such as version/date.
5. **Plan artifacts**: re-check every plan-readiness condition defined by the original Audit objectives.
6. **Closure**: when all pass, keep the original Finding Decision unchanged; set remediation status to `FIXED-VERIFIED` for repaired/verified Findings. Re-decide only if new Evidence changes whether the issue itself was real. If fix effectiveness cannot be verified, keep `FIX-IN-PROGRESS`.

Docs/pure-text fixes meeting this section can be reviewed directly by the main agent without forcing a new agent chain; Critical/High Findings still require heterogeneous-method review. All other workflow elements (batching, ledger updates) remain the same as for code artifacts.
