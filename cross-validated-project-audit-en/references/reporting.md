# Audit Reporting and Gates

Read this file before producing the final audit result. Reports aggregate by **Finding → Decision**, not by dumping agent, Hypothesis, or Evidence entries one by one. Default output has two layers: a decision-ready **Executive report** first, then a traceable **Audit appendix**. Users should not need to read the ledger before knowing whether they can merge or release.

First read the task contract in `audit.md`. A user-specified Deliverable always takes precedence. If none is specified: release/merge/gate request → gate report; `objectiveProfile` contains `fix-verification` → fix-verification report; otherwise → finding report. Expand the traceability appendix only when the user requests it or §3 conditions trigger it.

## 0. Deliverable contract

| Deliverable | Minimum required content |
|---|---|
| Gate report | Executive: gate + Top risks + Required actions + Residual uncertainty; Appendix: scope/baseline + Findings/Decision + coverage/evidence index |
| Finding report | Executive: Top risks + Required actions/recommendations + Residual uncertainty; Appendix: scope/baseline + Findings/Decision + verified-correct behavior + coverage/evidence index |
| Fix-verification report | Executive: whether the fix passed + unresolved risks + Required actions + Residual uncertainty; Appendix: original Finding → remediation status → verification Evidence + missed instances/new regressions |
| Traceability report | Corresponding base report + full Audit appendix (ledger, Evidence, coverage, investigations, probes/commit-matrix index) |
| User-defined | Satisfy requested fields and still disclose actual scope, key Evidence, and residual risks |

Single-source rules:

1. `findings/F<n>.md` provides Finding statement, location/scope, Provenance, impact chain, trigger conditions, disconfirmation, Impact/Likelihood/Reachability/Recoverability, Severity mapping, and H/E references;
2. `ledger.md` provides Decision, final Severity, Confidence, main verification method, remediation status, pattern scope, and Decision rationale;
3. In normal mode, `coverage.md` provides risk coverage, H→F/refuted/gap reconciliation, and heterogeneous-method completion. If explicit degraded mode omits coverage, disclose the gap and limit completeness/gate claims accordingly;
4. `investigations/` exists for Hypothesis/Evidence traceability only and does not directly produce final issue conclusions.

## 1. Default output: Executive report + Audit appendix

### Executive report

Keep only decision-relevant information, in this order:

1. **Gate / Decision**: when a gate is requested, output `READY` / `READY-WITH-CONDITIONS` / `BLOCKED` / `INCOMPLETE` plus one-line rationale. When no gate is requested, write “Gate: not requested” and do not invent a release decision.
2. **Top risks (max 3)**: prioritize Critical/High, then release/user impact and Confidence. Each item contains only F id, short title, Severity/Confidence, Provenance, and one-line real-world impact.
3. **Required actions**: only actions necessary to clear BLOCKED/INCOMPLETE or satisfy explicit user acceptance, each with an exit condition.
4. **Recommendations**: non-blocking `PRE_EXISTING` risks, Medium/Low Findings, or improvements worth addressing. Omit if none.
5. **Residual uncertainty**: unverified platforms/environments, critical Evidence/coverage gaps, stop reason, and residual risks. In audits where change attribution actually matters, include `UNKNOWN` Provenance that could change an important conclusion.

Do not dump the full ledger, agent process, command logs, or every Low Finding into the Executive report. The user should see first: can it merge/release, what are the biggest risks, what must be done, and what is still unknown?

### Audit appendix

Default to a **compact traceable appendix** containing:

- task contract, actual scope, base/head, critical assumptions/exclusions;
- Findings/Decision table including Provenance, Severity, Confidence, remediation status;
- required risk coverage and heterogeneous-method completion;
- index of key Supporting/Refuting Evidence;
- path/summary index for artifacts that actually exist: investigations, verification, probes, fix-map, commit/author matrix, etc.

When the user requests “full traceability/evidence chain” or §3 triggers, expand the full ledger, material H/E chain, and necessary command/environment detail. Ordinary reports should not copy all investigation text from authoritative audit state.

## 2. Finding report fields

Each reported Finding contains: F id, Finding statement, location/scope, Provenance, Impact / Likelihood / Reachability / Recoverability, Severity, Confidence, cause→real impact, trigger/applicability conditions, Disconfirmation summary, key Supporting/Refuting Evidence including Strength/Reproducibility, main verification method, Decision, pattern scope, suggested fix, and a decidable exit condition. Final Decision / Severity / Confidence come only from `ledger.md`; an investigator’s “potential impact” or local result cannot override the main-agent Decision.

## 3. Traceability mode

Expand by default when: the user requests a full evidence chain; the gate is disputed; Critical/High Findings have conflicting Evidence; or missing critical material/environment/heterogeneous methods produce `INCOMPLETE`.

Show the hierarchy:

```text
Risk unit → Hypothesis → Evidence → Finding → Decision
```

Include: `project-map` shared-fact summary when present; coverage or degraded-mode equivalent records; disposition mapping for material Hypotheses; each Finding’s H/E sources; REJECTED Findings whose counterevidence changes the conclusion; and gate-relevant commands/environment/baseline failures. Do not dump full investigation bodies by default.

## 4. Gate mapping

The following defines `Risk tolerance=standard`. Any non-standard policy must be normalized into decidable additional conditions before dispatch; users may tighten defaults. To release a confirmed risk that still exists, the corresponding Finding must explicitly have remediation status `ACCEPTED-RISK`; never lower Severity/Confidence or rewrite Evidence. Confidence expresses certainty only and does not directly alter default gate priority. A critical low-Confidence risk lacking enough Evidence for decision should be represented through `CONDITIONAL` / `INCOMPLETE`.

For `change` / `pr` / `author-commits` gates where attribution matters, first distinguish **change-attributable** (`INTRODUCED` / `REGRESSED` / `EXPOSED`) from `PRE_EXISTING`. A purely `PRE_EXISTING` Finding that the target change does not expand/activate is still reported, but by default is not described as “introduced by this change” and does not by itself block that change. If Audit objectives cover whole-system/release-candidate readiness, or that pre-existing risk makes the target change unsafe to integrate/run, it may still affect the gate based on release relevance. When attribution applies, `UNKNOWN` that could change a Critical/High gate is a critical attribution gap. When attribution does not apply, use `—`; it is not a gap.

| Priority | Condition | Gate |
|---|---|---|
| 1 | A Finding has Decision=`CONFIRMED`, Severity=Critical/High, is release-relevant to the current gate target, and remediation status is `OPEN` / `FIX-IN-PROGRESS` | `BLOCKED` |
| 2 | Any Finding still has Decision=`PENDING`; or critical Evidence, target environment, material-Hypothesis disposition, or required heterogeneous coverage is missing; or a Severity=Critical/High Finding has Decision=`NEEDS-DECISION` / `CONDITIONAL`; or a material Hypothesis expected to become Critical/High if true remains a residual gap because decisive verification is unavailable and blocker existence cannot be reliably determined | `INCOMPLETE` |
| 3 | Neither of the above, but there is a Finding with Decision=`CONFIRMED`, Severity=Medium/Low, and remediation status `OPEN` / `FIX-IN-PROGRESS`; a noncritical `NEEDS-DECISION` / `CONDITIONAL`; a non-blocking residual risk; or another condition item | `READY-WITH-CONDITIONS` |
| 4 | None of the above, and required heterogeneous coverage for highest-risk invariants is fully verified | `READY` |

Take the first match strictly under `BLOCKED > INCOMPLETE > READY-WITH-CONDITIONS > READY`. Hypothesis supported/refuted/unresolved states are **not gate states**. Gate inputs come only from final disposition of material H, Finding Decision/Severity/remediation status/applicable Provenance, and completeness gaps in required coverage/Evidence/environment.

## 5. Blocking and exit conditions

Every BLOCKED Finding must include:

```text
[ ] <required action>
    Exit condition: <observable, testable, decidable pass condition>
```

A Hypothesis without sufficient Evidence cannot directly block. If still material, it may become a Finding with an explicit gap and Decision=`CONDITIONAL`. `NEEDS-DECISION` is only for cases where key facts are sufficient and the remaining issue is a product/compatibility/scope/risk tradeoff. Use `CONFIRMED` only when Evidence is sufficient to confirm the issue. Report wording itself does not clear a gate.

## 6. Wording when no issue is confirmed

When heterogeneous coverage, Hypothesis disposition, and key checks meet the requirements:

> No confirmed defects were found within the audited scope and executed checks.

When they do not:

> Completed review found no confirmed defects, but unclosed risk coverage, Hypothesis, or Evidence gaps remain; this is not a comprehensive no-defect conclusion.

Never claim “absolutely safe,” “no bugs,” or “all scenarios are correct.”

## 7. Pre-output consistency check

The main workflow owns whether the audit is complete and when exploration stops. This file only checks whether final output faithfully reflects authoritative audit state:

- [ ] Gate is mechanically mapped from the real state of authoritative findings + ledger + current coverage/equivalent degraded records. Missing full coverage in degraded mode is reflected as a completeness limitation; report wording does not override Decision.
- [ ] Executive report answers Gate/Top risks/Required actions/Residual uncertainty first; Recommendations are separate from Required actions.
- [ ] Where Provenance applies, change-attributable / `PRE_EXISTING` / `UNKNOWN` are correctly distinguished; when not applicable, `—` is shown; old risk is not mislabeled as introduced by this change.
- [ ] Audit appendix traces key Finding → Supporting/Refuting Evidence → coverage; ordinary output does not dump irrelevant investigations/logs.
- [ ] `stopReason`, residual risks, critical verification gaps, and recovery/archive paths when applicable are disclosed; fix-verification reporting matches `fix-map` and remediation status.
