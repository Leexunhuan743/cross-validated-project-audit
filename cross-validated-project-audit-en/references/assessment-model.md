# Disconfirmation, Risk Assessment, and Evidence Strength

Load this file when promoting a material Hypothesis to a Finding, when the main agent makes a Decision/Severity judgment, or when comparing Evidence quality. The goal is to separate “how severe is the issue,” “how certain are we,” and “how strong is the evidence,” so uncertainty is never hidden by lowering Severity.

## 1. Disconfirmation is a standard step

Every material Hypothesis being promoted to a Finding must answer once: **What would make this hypothesis false or materially narrower?**

Record four items:

```text
Counter-hypothesis: <strongest realistic safe explanation/limiting condition; if true, the original H is false or materially narrower>
Expected safe behavior: <guard / lock / caller constraint / contract / runtime behavior expected if the counter is true>
Evidence searched: <which callers, guards, locks, lifecycle paths, contracts, runtime behavior, history, etc. were actually checked>
Result: counter-supported / counter-refuted / unresolved
```

Rules:

- Do not use an obviously unrealistic straw-man counterexample. Prefer the most plausible protection that would invalidate the original Hypothesis.
- `counter-supported`: close the original H or restate it more narrowly. If the narrowed H is still material, perform disconfirmation again on the new H; do not promote it directly to a Finding.
- `counter-refuted`: promotion may continue, while preserving any limiting Evidence that was found.
- `unresolved`: prefer keeping it as a residual gap. If there is still enough Evidence to normalize it into a Finding, retain the unresolved condition explicitly, do not set Decision=`CONFIRMED`, and lower Confidence rather than Severity.
- A Finding with provisional Critical/High Severity must attempt a second heterogeneous archetype challenge or equivalent direct disconfirmation before final Decision. It may be `CONFIRMED` only when that requirement is completed and Evidence is sufficient. Otherwise preserve the verification gap in Decision/gate. Ordinary Findings do not require an extra agent merely for formality, but still require the minimum disconfirmation record above.

## 2. Finding risk-assessment dimensions

After a Finding is formed and before Decision is finalized, the main agent assesses the following dimensions. They describe the **real-world risk if the Finding statement is true under its stated trigger conditions**; they do not describe “how certain the main agent is.”

| Dimension | Values | Meaning |
|---|---|---|
| Impact | `Critical` / `High` / `Medium` / `Low` | Consequence magnitude once triggered; security-boundary bypasses, broad irreversible data loss, etc. are high-impact anchors |
| Likelihood | `High` / `Medium` / `Low` | Real-world frequency/probability within the Finding’s stated applicability conditions; not “probability the Finding is true” |
| Reachability | `Common` / `Conditional` / `Privileged` | Reachable through normal real paths, requires specific but realistic conditions, or reachable only through privileged/internal paths |
| Recoverability | `Irreversible` / `Manual` / `Automatic` | Recovery cost after occurrence and whether automatic recovery exists |

### Severity mapping

Use `Impact` as the baseline Severity, then allow only the following limited adjustments so each auditor cannot invent a separate formula:

1. Default: `Severity = Impact`.
2. When `Likelihood=Low` and either `Reachability=Privileged` or `Recoverability=Automatic`, Severity may be lowered by one level; explain why real-world risk is materially constrained.
3. When `Likelihood=High`, `Reachability=Common`, and `Recoverability=Irreversible` all hold, Severity may be raised by one level, capped at `Critical`.
4. Realistically reachable security-boundary bypasses, severe data loss, or broad irreversible failures must not be reduced to Medium/Low merely because triggering is uncommon.
5. Any Severity outside the mapping above requires a specific rationale in Decision rationale.

**Never use Confidence as a Severity adjustment.** For example, “if true this is Critical, but evidence is still weak” should be represented as `Severity=Critical, Confidence=Low/Medium, Decision=CONDITIONAL`, not by silently lowering Severity to Medium.

## 3. Confidence

Confidence is a first-class Finding attribute answering “how certain are we that this Finding statement is true?” It is orthogonal to Severity.

| Confidence | Typical conditions |
|---|---|
| `Very-High` | Repeatable validation through the target platform/version public path, with key counterexamples directly ruled out; or multiple heterogeneous high-strength Evidence items with no material conflict |
| `High` | At least one strong, reviewable, complete evidence chain; disconfirmation completed; no unexplained material refuting Evidence |
| `Medium` | Supporting chain mostly holds, but target environment, trigger condition, repeatability, or a key limiting condition is not fully verified |
| `Low` | Relies mainly on local indications, or material counterevidence/key conditions remain unresolved |

Constraints:

- `CONFIRMED` requires `Confidence ∈ {High, Very-High}`. If insufficient facts/environment/verification Evidence prevent that, use `CONDITIONAL` or keep a residual gap. Use `NEEDS-DECISION` only when facts are sufficient and the remaining issue is an authorized tradeoff. Do not pretend certainty by lowering Severity.
- `REJECTED` means the main agent concludes the Finding does not hold; set Confidence to `—`. Strength of refutation is expressed through Decision rationale and refuting Evidence.
- A Confidence change is a material change in Decision metadata and must be recorded in change history.

## 4. Evidence Strength and reproducibility

Each numbered Evidence item records `Strength` and `Reproducibility` in addition to `Polarity / DIRECT source / Observation`. **There is no ES0: intuition, experience, and guesses are not Evidence; they belong only in Hypothesis/reasoning.**

| Strength | Standard |
|---|---|
| `ES1` | Local DIRECT indication: real code/log/output/contract fragment was observed, but the full call chain, state condition, or impact is not closed |
| `ES2` | Complete traceable chain: call/data/state/contract chain is closed and another investigator can independently re-check cited sources without relying on unstated guesses |
| `ES3` | Executable or deterministic reproduction: minimal steps, input, environment, and observable result are recorded and another person can repeat them; includes repeatable schema/build/load/artifact validation |
| `ES4` | Target-authoritative reproduction: ES3 holds under the target platform/version/build conditions relevant to the claim through a real public entry point; authoritative contracts for the relevant version may independently corroborate it, but non-target environments or internal-helper-only reproduction cannot upgrade to ES4 |

Use only these `Reproducibility` values:

- `repeatable`: reliably reproducible/re-checkable using recorded steps;
- `conditional`: reproducible only under explicitly recorded timing, platform, state, or external prerequisites;
- `single-observation`: currently only one DIRECT observation exists;
- `not-applicable`: pure static authoritative fact has no executable reproduction, but exact source can be re-checked.

Rules:

- Strength measures the **quality of one Evidence item**; Confidence is the main agent’s aggregate certainty about the entire Finding. Do not mix them.
- Multiple ES1 items do not automatically become ES3/ES4 by quantity.
- Passing tests, agent consensus, unsourced logs, or a one-off unreproducible failure cannot by themselves exceed ES1.
- Repeatable refuting Evidence on the target platform/public path may outweigh multiple weaker supporting Evidence items. Preserve and explain conflicting Evidence; do not vote by count.
- `ES3/ES4` must record enough minimal reproduction information for independent repetition. Missing critical inputs, environment, or steps downgrades the item to ES1/ES2.

## 5. Provenance: distinguish change risk from pre-existing risk

Fill Provenance only when the task needs to determine the relationship between a risk and a comparable change/commit range. For whole-project/static-artifact audits where change attribution is not applicable, use `—`. Use `UNKNOWN` only when attribution is required but current history/baseline Evidence is insufficient. Provenance answers “how is this risk related to the target change?” It **does not assign responsibility and does not change Severity/Confidence**.

| Provenance | Decision standard |
|---|---|
| `INTRODUCED` | The target change adds a defect mechanism that did not previously exist, e.g. a new feature/path introduces the error |
| `EXPOSED` | The root cause already existed in base, but the target change makes it realistically reachable for the first time, expands the trigger surface, or turns a latent risk into a material risk |
| `REGRESSED` | Behavior/contract was correct in base and becomes wrong in the target change, or a previously fixed historical defect is reintroduced |
| `PRE_EXISTING` | The risk existed in base and the target change does not materially introduce, regress, expand, or activate it |
| `UNKNOWN` | Current history/baseline Evidence is insufficient for reliable attribution |

Rules:

- Provenance must be supported by base/head, historical implementation, call reachability, or other DIRECT Evidence. Do not infer it from `git blame`, file author, or commit message alone.
- `INTRODUCED` vs `REGRESSED`: use `INTRODUCED` when a new capability/path itself brings in the defect; use `REGRESSED` when a comparable behavior was correct in base and wrong in head.
- `EXPOSED` must identify “pre-existing root cause + new reachability/impact increment from this change.” Do not repackage a purely pre-existing issue as introduced by the change.
- In author-commit audits, Provenance describes the technical relationship between the target commit set and the risk, not personal responsibility.
- When attribution applies but cannot be proven, use `UNKNOWN`; do not guess for report neatness. When attribution itself is not applicable, use `—` rather than disguising “not applicable” as `UNKNOWN`.

## 6. Decision semantics and minimum checks

Final Decision uses exactly these four values; `PENDING` is only a temporary ledger work state, not a final Decision:

| Decision | Semantics |
|---|---|
| `CONFIRMED` | DIRECT Evidence plus disconfirmation sufficiently support that the Finding is real under the stated conditions |
| `CONDITIONAL` | The Finding remains material, but decisive facts, environment, or verification conditions are still open; this is an evidence/condition gap, not a product choice |
| `NEEDS-DECISION` | Key facts are sufficiently established; the remaining issue is a product, compatibility, scope, or risk tradeoff requiring an authorized decision rather than more evidence collection |
| `REJECTED` | DIRECT counterevidence or applicability conditions show that the Finding does not hold, or it has been narrowed until it is no longer material |

Before finalizing a Finding, the main agent checks at minimum:

1. The Finding has Supporting Evidence and disconfirmation was executed and recorded;
2. Impact / Likelihood / Reachability / Recoverability are filled;
3. Where change attribution applies, Provenance is filled and supported by DIRECT Evidence;
4. Severity is mapped under §2 and kept separate from Confidence;
5. Every non-`REJECTED` Finding has Confidence consistent with the highest-quality, conflicting, and refuting Evidence;
6. A Finding with provisional Critical/High Severity attempted a second heterogeneous archetype challenge or equivalent direct disconfirmation before final Decision. Only after that challenge is completed and Evidence is sufficient may it be `CONFIRMED`. If it cannot be completed or decisive fact/environment gaps remain, use `CONDITIONAL`; if facts are sufficient and only an authorization tradeoff remains, use `NEEDS-DECISION`; if the critical gap can affect whether a blocker exists, the gate layer maps it to `INCOMPLETE`.
