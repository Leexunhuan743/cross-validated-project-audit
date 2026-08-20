# Audit Ledger and Recovery

The main audit agent reads this file and initializes audit state **before dispatching any subagent**. It then updates state at natural milestones (fact map complete, risk unit dispatched, investigation result received, Finding finalized, Decision finalized, pattern scope finalized, gate output). Prefer persistence under `.audits/`. If the environment is not writable, use an isomorphic in-session Markdown state as the **authoritative audit state** for the current run and disclose reduced recoverability. Goal: when persistence is available, an interrupted session can resume without re-running completed investigations; across rounds, prior facts, Findings, Decisions, disconfirmation, and residual risks remain queryable. A subagent saying “done,” response length, and return order are never authoritative.

Audit state uses **Markdown as the sole authored format**: directly readable/writable by humans and agents, with no escaping or machine-format maintenance burden. Machine formats such as JSONL are not hand-authored within the Skill-only implementation; when the platform exposes session/event logs, a companion plugin may deterministically project them with a reducer.

## 1. Persistent state directory and session fallback

When persistence is available, write audit state under `.audits/` in the **working directory**. During initialization, handle ignore rules in this order; if the location ultimately proves unwritable, switch to isomorphic session state in step 5:

1. If the working directory is a Git repository, run `git check-ignore .audits/`. If already ignored, write nothing.
2. If not ignored, run `git rev-parse --git-path info/exclude` to resolve the real exclude file path. In a linked worktree, `.git` may be a file rather than a directory, so do not assume `.git/info/exclude` is directly writable. Avoid duplicate entries, append `.audits/`, then run `git check-ignore -q .audits/` again to confirm the rule actually works. If still not ignored, disclose that; if the exclude file is unwritable but `.audits/` itself is writable, disclose and continue, and never commit audit-state contents.
3. Write the project `.gitignore` only when the user explicitly wants the ignore rule committed with the repository; disclose that project change in the report.
4. If the working directory is not a Git repository, use `.audits/` directly with no ignore rule.
5. If `.audits/` is unwritable, use an in-session ledger with the same Markdown structure and disclose the limitation.

All other project files remain under the read-only contract.

```text
<working-dir>/.audits/<ownerKey>--<auditId>/
├── audit.md             # task contract, baseline, stop policy, final gate
├── project-map.md       # shared minimal DIRECT fact map; no hypotheses, Findings, Decisions
├── coverage.md          # risk coverage matrix (Risk → method → executor)
├── ledger.md            # Finding → Decision current-state table + decision change log
├── fix-map.md           # optional: remediation map and batch dependency graph
├── investigations/      # independent investigation artifacts: Hypothesis + Evidence
│   └── <unit>-<agent>.md
├── findings/            # main-agent normalized Findings; one file per Finding
│   └── F<n>.md
├── verification/        # main-agent empirical verification; verification/F<n>.md
└── probes/              # main-agent-approved isolated probes; clean up at end
```

- `auditId`: normalize the audit name with NFKC and trim surrounding whitespace into `canonicalName`; `slug = sanitizeKey(canonicalName)` (retain only letters, digits, `-`, `_`; collapse everything else to `-`; forbid path separators, `..`, and empty IDs). The short digest is the first 8 lowercase hex characters of `SHA-256(UTF-8(canonicalName))`. `auditId = <first 23 chars of slug>-<shortDigest>`; when slug is empty use `audit-<shortDigest>`. The digest reduces normalized-name collision probability; it does not guarantee collision freedom.
- When persistence is available, record the resolved absolute active-state path as `stateDir` and use that path for access. Under session fallback, write `stateDir=session-only`. Before archiving a persistent audit, compute and store final `archiveDir`; after archive, recovery/review locates state using `archiveDir` or the instance-search rules in §5.

## 2. Four-layer semantic model

Keep these four layers distinct throughout the audit:

1. **Hypothesis (H)**: a falsifiable suspicion or defect theory, e.g. “cross-window synchronization may use the wrong window.” It is not a Finding and cannot enter the final report directly.
2. **Evidence (E)**: a direct observation from actual reading, execution, or an authoritative contract for the relevant version. It may support, refute, or constrain a Hypothesis/Finding. **Reasoning is not Evidence**; reasoning lives in a reasoning field and cites Evidence.
3. **Finding (F)**: a concrete, independently decidable issue statement normalized by the main agent from one or more Hypotheses. It must include a real impact path, trigger/applicability conditions, and Evidence references. A Finding is not synonymous with “confirmed issue.”
4. **Decision**: the main agent’s final disposition of a Finding: `CONFIRMED` / `NEEDS-DECISION` / `CONDITIONAL` / `REJECTED`, with separate Severity, Confidence, and remediation status. The Finding itself records Provenance under the unified assessment vocabulary (`—` when attribution is not applicable), distinguishing change-attributable risk from pre-existing risk. Provenance is not responsibility attribution and does not participate in Severity/Confidence calculation. Finding-level blocking/conditions are Decision-driven; critical completeness gaps in coverage, Evidence, or material Hypotheses may independently map to `INCOMPLETE`.

The relationship is not “every H must become an F.” Evidence may directly refute and close a Hypothesis; a material Hypothesis with insufficient evidence may remain a residual gap. A **material Hypothesis** is one that, if true, could become at least a Medium Finding, change gate/Decision/Severity, move Confidence across a Decision threshold, reveal a systemic pattern, or introduce a highest/high risk. Pure style speculation or guesses with no real impact are not material. Only issues worth a main-agent decision are promoted to Findings.

## 3. File templates

### 3.1 `audit.md` (task and stop state)

```markdown
| Key | Value |
|---|---|
| auditId | lep-2026-08-a1b2c3d4 |
| name | LEPTON cross-audit v1.5 |
| ownerKey | <platform session id or safe fallback> |
| stateDir | <resolved absolute active-state path> / session-only |
| archiveDir | — |
| target | <repository/branch/commit/PR/workspace/plan/config/migration/feature/fix artifact> |
| scopeMode | project / change / pr / author-commits |
| objectiveProfile | general / security / fix-verification / security,fix-verification |
| executionMode | audit-only / audit-and-fix |
| scope | <actual included audit paths, subsystems, commit range, or plan sections; exclusions go only in `excluded`> |
| objectives | <questions this audit must answer> |
| riskTolerance | standard / <policy normalized into decidable conditions> |
| availableEvidence | <availability of repository, diff, PR metadata, requirements, CI, logs, target environment, authoritative contracts, etc.; never secrets> |
| deliverable | <gate report/finding report/traceability report/fix-verification report/user-specified output> |
| base | <immutable baseline; use — when not applicable> |
| head | <immutable target; use — when not applicable> |
| stopPolicy | standard / exhaustive / user-defined |
| noMaterialDeltaRounds | 0 |
| stopReason | — |
| gate | READY / READY-WITH-CONDITIONS / BLOCKED / INCOMPLETE / — (no gate requested) |
| assumptions | one item per line |
| excluded | one item per line (scope + reason) |
| residualRisks | one item per line (residual risk/evidence gap at end) |
| startedAt / updatedAt | ISO8601 |
```

- `ownerKey` must uniquely identify the main session/main agent. Prefer a platform session ID or equivalent; sanitize it for filename safety before using it in a path, forbidding path separators and Windows-invalid filename characters. Do not use placeholders such as `default`, `main`, `unknown`, empty string, or the audit name itself. If no usable platform ID exists, use compact `startedAt` (e.g. `20260815T215947+08`) + at least 4 random characters; check the directory before creation and regenerate on collision.
- `auditId`, `ownerKey`, and `stateDir` do not change after initialization; fill `archiveDir` only when archiving. The six task-contract fields and derived fields must all have values before dispatch.
- `stopPolicy` is internal and does not add user-facing input burden: default `standard`; use `exhaustive` when the user explicitly requires file-by-file/line-by-line/exhaustive review; use `user-defined` when the user supplies an explicit investigation budget/stop criterion. `noMaterialDeltaRounds` only persists the count of consecutive exploration rounds with no material delta. The main workflow owns when to update it and when to stop expansion; this file does not duplicate those thresholds.

### 3.2 `project-map.md` (share facts, isolate judgment)

`project-map.md` is a **supplemental fact layer** over the task contract in `audit.md`. target/base/head/scope/excluded live only in `audit.md` and are not duplicated here. Store only DIRECT project facts that multiple risk units will reuse, so every agent does not have to rebuild the same background from README and repository root. Do not store Hypotheses, Findings, Decisions, severity judgments, Risk tolerance, other investigators’ conclusions, or hints such as “there may be a bug here.”

```markdown
# Project map

## Project / subsystem map
- <subsystem> → <responsibility/entry point/key dependencies>

## Terminology
- <term> = <actual project meaning> (source: ...)

## Public entrypoints
- <CLI/API/UI/SDK/migration/...> → <entry location>

## Changed / touched areas
- <path> → <change/touch fact; use — when a whole-project audit has no explicit change>

## Shared facts
| Fact ID | DIRECT fact | Source |
|---|---|---|
| P1 | ... | path:line / command / authoritative contract |

## Known baseline failures
- <existing failure and direct source>
```

- The main agent builds a minimal map before dispatch. Collect only facts reused across risk units; do not scan unrelated files merely to make the map “complete.” `P<n>` is a shared factual-context ID. It may be cited as Finding context, but material Decisions should still cite at least one investigation/verification Evidence item (`R*-E*` / `F*-E*`).
- Subagents receive only the map summary or file access relevant to their risk unit. The risk map itself lives in `coverage.md`; investigators see only assigned risk claims and do not batch-read judgment from other units. Investigators may refute supplemental facts in `project-map.md`: return `MAP-CORRECTION` + DIRECT Evidence, then the main agent corrects the shared map. If a corrected fact was a material premise for a coverage unit, identify affected units: push the correction to in-progress units; create a minimal supplemental review unit for already-completed ones; until that supplemental review completes, the old unit cannot by itself satisfy required coverage for that risk claim.
- `MAP-CORRECTION` applies only to supplemental facts in `project-map.md`. If an investigator finds target/base/head/scope/excluded in `audit.md` potentially wrong or conflicting, return it as a task-contract/baseline conflict for main-agent re-resolution and possible coverage replanning. Do not silently edit the map to bypass the contract.
- **Share facts, isolate judgment**: you may share target/base/head/scope/excluded from `audit.md` plus terminology, entry points, changed files, and DIRECT project facts from `project-map.md`; you must isolate other investigators’ Hypotheses, interpretations of Evidence, Findings, Decisions, and the main agent’s expected answer.

### 3.3 `ledger.md` (Finding → Decision)

The ledger stores only the **Decision summary for main-agent-normalized Findings**. It does not store raw investigator Hypotheses/Evidence. Finding content and risk dimensions live in `findings/F<n>.md`; investigation sources live under `investigations/`; main-agent direct verification lives under `verification/`. Severity / Confidence / Evidence Strength use the unified assessment vocabulary already loaded by the task protocol.

```markdown
| Finding | Decision | Severity | Confidence | Main verification method | Remediation status | Pattern scope | Decision rationale |
|---|---|---|---|---|---|---|---|
| F1 | CONFIRMED | High | High | user-path-trace (see verification/F1.md) | OPEN | ISOLATED | F1-E1(ES3) + R2-E3(ES2) support; counter-hypothesis refuted |
```

- `Decision`: `CONFIRMED` / `NEEDS-DECISION` / `CONDITIONAL` / `REJECTED`; `PENDING` may be used temporarily but must not remain at task closure.
- `Severity`: `Critical` / `High` / `Medium` / `Low` / `—`. Map from Impact / Likelihood / Reachability / Recoverability under the unified assessment model. **Confidence is never a downgrade reason.** Every non-`REJECTED` Finding requires Severity; `REJECTED` uses `—`, so gate logic never guesses from missing values.
- `Confidence`: `Very-High` / `High` / `Medium` / `Low` / `—`, representing certainty that the Finding is true, not impact magnitude. Every non-`REJECTED` Finding requires Confidence, and `CONFIRMED` may use only `High` / `Very-High`; `REJECTED` uses `—`.
- `Main verification method`: use the unified verification archetypes from the task risk map. The main agent’s direct re-check of decisive Evidence and any new Evidence go in `verification/F<n>.md`. Only Decision=`PENDING` may temporarily use `unknown`; replace it with an actual method before final Decision.
- `Remediation status` is orthogonal to Decision, but legal combinations are fixed: `PENDING` / `CONDITIONAL` / `NEEDS-DECISION` use only `OPEN`; `CONFIRMED` may use `OPEN` / `FIX-IN-PROGRESS` / `FIXED-VERIFIED` / `ACCEPTED-RISK`; `REJECTED` uses `—`. After evidence is completed or an authorized decision is made, update Decision first, then move into the corresponding remediation status.
- `ACCEPTED-RISK` may be set only by the current user explicitly, or by a pre-normalized authorized risk policy that unambiguously covers the Finding. The main agent must not “accept” risk on its own. Store the authorization basis in the Decision/remediation change record.
- `Pattern scope`: `ISOLATED` / `SYSTEMIC` / `UNKNOWN`; use `UNKNOWN` when no same-pattern search was performed.
- `Decision rationale` must cite Evidence IDs from the Finding/verification state. Never use voting rationales such as “both agents agreed.”

Decision change records are append-only:

```markdown
| Time | Finding | Change |
|---|---|---|
| ISO8601 | F1 | Decision PENDING → CONFIRMED; Severity High; Confidence High; based on F1-E1(ES3), R2-E3(ES2) |
```

Append a record whenever Decision, Severity, Confidence, remediation status, pattern scope, or decisive Evidence/disconfirmation changes materially. If a Finding’s Provenance changes in a way that affects gate/attribution, append that too. Do not record purely cosmetic edits.

### 3.4 `coverage.md` (risk coverage matrix)

```markdown
| Unit | Risk surface | Risk claim/invariant | Failure consequence/priority | Verification method | Executor | Evidence lens | Path/subsystem | Investigation file | Finding | Status | Reconciliation |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | boundary-conditions | `get_block` must not underflow | Wrong result; highest | implementation-trace | SA-fix | engineering | vendor/lepton_jpeg | investigations/R1-SA-fix.md | F1 | verified | R1-H1→F1; R1-H2→refuted(R1-E4) |
| R2 | boundary-conditions | `get_block` must not underflow | Wrong result; highest | state-invariant-analysis | SB-check | engineering | vendor/lepton_jpeg | investigations/R2-SB-check.md | F1 | verified | R2-H1→F1 |
```

- `Unit` uses an audit-unique ID (`R1` / `R2`). One unit means “one risk claim + one verification method + one bounded scope.” A second method creates a second unit.
- `Status` advances one-way: `planned → dispatched → reported → verified`. `reported` means the investigation file arrived; `verified` may be written only after the main agent reconciles that unit’s H/E.
- `Reconciliation` must dispose every material Hypothesis as `H→F<n>`, `H→refuted(E...)`, or `H→residual-gap(...)`. Before `H→F<n>`, confirm all four disconfirmation fields are complete. An investigator saying “no issue” or providing only supporting Evidence cannot make the unit verified.
- `Finding` lists F IDs contributed by the unit; use `—` when none. The same F may be supported by multiple heterogeneous units.
- A highest-risk invariant counts as heterogeneously independently covered only when at least two **different archetype**, information-isolated units are both `verified`.

### 3.5 `investigations/<unit>-<agent>.md` (Hypothesis + Evidence)

Investigators record only Hypotheses, Evidence, reasoning, verified-correct behavior, and gaps. They **must not create final Finding IDs, Decisions, or final Severity**.

```markdown
## R1-H1 Hypothesis
- Coverage unit: R1
- Risk surface: boundary-conditions
- Verification method: implementation-trace
- Hypothesis: <specific falsifiable statement>
- Potential impact: <real effect if true; do not assign final severity>
- Applicability/trigger conditions: <...>
- Counter-hypothesis: <strongest realistic safe explanation; if true the original H is false or materially narrower>
- Expected safe behavior: <guard/lock/caller constraint/contract/runtime behavior expected if the counter is true>
- Evidence searched for disconfirmation: <actual checked scope>
- Disconfirmation result: counter-supported / counter-refuted / unresolved
- Evidence refs: R1-E1, R1-E2
- Investigation result: supported / refuted / unresolved
- Reasoning: <reasoning from Evidence → Hypothesis; explicitly reasoning, not Evidence>
- Recommendation: promote-to-finding / close / residual-gap

### R1-E1 Evidence
- Polarity: supports / refutes / context
- Strength: ES1 / ES2 / ES3 / ES4
- Reproducibility: repeatable / conditional / single-observation / not-applicable
- DIRECT source: <actual path:line, command result, target-version contract, etc.>
- Observation: <observation facts only>
```

- Evidence must be DIRECT. “Based on experience” or “looks like it might” belongs in reasoning/Hypothesis and is never numbered E. Assess every Evidence item using the unified Strength / Reproducibility vocabulary from the task protocol.
- A Hypothesis may cite multiple supporting and refuting Evidence items. **Every material Hypothesis recommended for `promote-to-finding` must complete Counter-hypothesis / Expected safe behavior / Evidence searched / Disconfirmation result.** No actual disconfirmation search means no direct promotion.
- `Investigation result` is the investigator’s local judgment, not a Decision; the main agent may disagree.
- If there is no material Hypothesis, write “no material hypothesis” and still list checked scope, key Evidence/verified-correct behavior, and gaps.
- H/E IDs are unique within the audit by unit prefix, e.g. `R2-H3` / `R2-E7`.

### 3.6 `findings/F<n>.md` (main-agent normalized Finding)

Only the main agent may create/modify Findings. One Finding may aggregate multiple independent Hypotheses. If the main agent discovers an issue itself, it first records H/E in `investigations/<unit>-main.md` and then promotes it; do not bypass the four-layer chain.

```markdown
# F1 <short title>

- Risk surface: <one primary risk surface; optional secondary surfaces>
- Finding statement: <specific decidable issue statement>
- Location/scope: <path:line / public entrypoint / config / plan section>
- Provenance: INTRODUCED / EXPOSED / REGRESSED / PRE_EXISTING / UNKNOWN / — (change attribution not applicable)
- Cause → impact: <real-world impact chain>
- Trigger/applicability conditions: <...>
- Source hypotheses: R1-H1, R2-H1
- Supporting evidence: R1-E1, R2-E3, F1-E1
- Refuting/limiting evidence: <E ids or —>
- Disconfirmation summary: <counter-hypothesis + searched Evidence + result; cite source H/E>
- Impact: Critical / High / Medium / Low
- Likelihood: High / Medium / Low
- Reachability: Common / Conditional / Privileged
- Recoverability: Irreversible / Manual / Automatic
- Severity mapping: <explain baseline/limited adjustment under the unified assessment model; never adjust with Confidence>
- Provenance evidence: <base/head/history/reachability Evidence supporting provenance; use — when not applicable>
- Suggested verification/exit condition: <observable, testable, decidable>
```

- A Finding is a “decidable issue object,” not a synonym for `CONFIRMED`. Provenance, risk dimensions, Severity mapping, and disconfirmation remain in the Finding file; ledger keeps only final Decision / Severity / Confidence, avoiding mixing historical attribution with risk judgment.
- New Evidence from main-agent verification goes in `verification/F<n>.md`, using IDs `F<n>-E<m>`. Each item keeps the same five fields as investigation Evidence: `Polarity / Strength / Reproducibility / DIRECT source / Observation`. The Finding file cites those IDs.
- When multiple investigators describe the same logical issue, create one Finding preserving all source Hypotheses/Evidence. Split only when different root causes or materially different real-world impacts require independent decisions.

## 4. State-write discipline

- Normal mode writes `audit.md` + `project-map.md` + planned risk units in `coverage.md` before dispatch. Explicit degraded mode that omits project-map/coverage first creates the minimum state and investigation task headers required by the degraded protocol.
- After dispatch, coverage→`dispatched`; when the investigation file arrives→`reported`; after the main agent reconciles every material Hypothesis into Finding/refuted/residual-gap→`verified`.
- After Finding creation/merge, update `findings/F<n>.md`; after Decision finalization, update `ledger.md`; main-agent empirical verification goes in `verification/F<n>.md`. Never fabricate a jump from `planned` to `verified` during final cleanup.
- After every authoritative-state update, reconcile it with the current conclusion. A mismatch between authoritative state and final report is a defect.
- If a subagent cannot write persistent state, it returns the full text inline; the main agent writes it into the matching investigation state and marks it “written by main agent on behalf of investigator.” This does not change state authority.
- Never echo credentials, tokens, or real user data. Persist only sanitized Evidence needed for the audit purpose.

## 5. Recovery

1. After selecting the correct state instance, read `audit.md` and `ledger.md` first. In normal mode also read `project-map.md` / `coverage.md`; in degraded mode read the state artifacts that actually exist and preserve disclosure of omitted ones.
2. When `coverage.md` exists, for units that are `reported` but not `verified`, read the investigation file and finish H→F/refuted/gap reconciliation without re-running investigators. In degraded mode without coverage, continue the four-layer chain through `investigations/` → `findings/` → `ledger.md`.
3. If a Finding exists but Decision=`PENDING`, continue disconfirmation, risk-dimension/Confidence assessment, main-agent verification, and decision. Reuse existing `verification/` Evidence rather than recollecting it.
4. Under `audit-and-fix` / `fix-verification`, also restore remediation statuses `OPEN` / `FIX-IN-PROGRESS` and any `fix-map.md` batches not yet `PASSED`.
5. Restore `noMaterialDeltaRounds` and residual risks; do not rerun completed exploration rounds.
6. In a **persistent-mode** new session, match `*--<auditId>` under `.audits/`, then search `.audits/archive/`. If multiple instances match, read target, base/head, scope, derived fields, and time to identify the correct one; if still ambiguous, ask the user. If none match, explicitly disclose “historical state not found.” Session-only fallback does not promise cross-session recovery.
7. Final reporting notes the recovery path, interruption point, and number of units/Findings continued after recovery.

## 6. Archive and cross-round review

- At audit end, all modes first clean probes and temporary resources. In **persistent mode**, then move the state directory to `.audits/archive/<ownerKey>--<auditId>/` and include the archive path in the report. Session-only fallback discloses that state was not persisted and cross-session recovery is limited.
- Archive path as a whole must be unique. On conflict, add disambiguation only on the `ownerKey` side (e.g. `<ownerKey>-<startedAt>--<auditId>`); never overwrite or silently discard.
- On a later audit of the same artifact/scope, read historical `audit.md`, any existing `project-map`, Finding/Decision, disconfirmation, pattern scope, and residual risks first. **Share previously confirmed facts, but independently form new Hypotheses/judgments.** Do not mechanically redo background collection, and do not make the old Decision the expected answer for the new round.
- Apply the evidence-sanitization discipline to sensitive archived content.

## 7. Degradation and disclosure

- Persistence unavailable: use isomorphic session state and disclose “audit state not persisted; cross-session recoverability reduced.” As long as H/E/F/Decision and the state required by the current mode remain complete in authoritative session state, this limitation alone does not invalidate completion of a factual audit. If the Deliverable explicitly requires recoverable/persistent evidence, disclose that as an unmet condition.
- If the request does trigger this Skill but subagent capability is unavailable or the user explicitly requests a speed degradation, the audit may omit a full `coverage.md` and non-reused `project-map.md`, but it must still preserve at minimum `audit.md` + `investigations/main.md` + `findings/` + `ledger.md`, ensuring four-layer H/E/F/Decision traceability. Also disclose the missing risk coverage matrix and heterogeneous independent coverage. Ordinary narrow questions that do not need cross-validation should not trigger this Skill merely because degradation exists.
- Degradation never changes the four-layer semantics or assessment model: Hypothesis is not Finding, reasoning is not Evidence, Finding is not Decision; Confidence is not Severity, and numerous low-strength Evidence items do not become high-strength evidence by count.

## 8. Ledger vs session logs

- Platform session/event logs are the **process event source** (replayable); they may contain unsanitized source text and session boundaries do not equal audit boundaries.
- This state structure is the **reduced audit state**: `project-map`=shared facts, `investigations`=independent H/E, `findings`=normalized issue objects, `ledger`=Decision, `coverage`=risk coverage. Persistent and session-only modes have the same responsibilities and must not mix roles.
