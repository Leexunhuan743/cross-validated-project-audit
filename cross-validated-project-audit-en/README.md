# cross-validated-project-audit-en

A general project-audit Skill that first normalizes a request into a simple task contract, then builds a shared fact map and risk map, chooses heterogeneous investigation paths using “Risk → verification method → executor,” and strictly separates `Hypothesis → Evidence → Finding → Decision`, with the main agent making the final decisions. Supports whole-project audits, bounded change audits, PR audits, author-scoped commit audits, security audits, and fix verification; can produce release/merge gates or other requested audit deliverables.

## Task entry

Users do not need to learn the internal state machine. They only need to describe the goal in natural language. The Skill first normalizes it into:

```text
Audit target
Audit scope
Audit objectives
Risk tolerance
Available evidence
Deliverable
```

It then derives internally:

- `scopeMode`: `project` / `change` / `pr` / `author-commits`
- `objectiveProfile`: `general`, optionally layered with `security` / `fix-verification`
- `executionMode`: `audit-only` / `audit-and-fix`

Security and fix verification are objective profiles and are not mutually exclusive with PR/project/author scope. For example, “check whether this PR’s security fix really works” can be represented as `scopeMode=pr` + `objectiveProfile=security,fix-verification`.

## Quick examples

| You can ask | Typical internal interpretation | Default focus |
|---|---|---|
| “Audit this entire project” | `scopeMode=project` | Major subsystem risks, critical invariants, residual risk |
| “Review this PR and tell me whether it can merge” | `scopeMode=pr` + gate report | Change-attributable risk, regressions, delivery completeness |
| “Audit this branch/commit/workspace” | `scopeMode=change` | The target change, affected context, and actual current tree state |
| “Audit commits by this author within this range” | `scopeMode=author-commits` | Author identity, immutable commit range, history, and current state |
| “Perform a security audit” | Current scope + `objectiveProfile=security` | Trust boundaries, reachability, state/boundary conditions, attack paths |
| “Verify that this fix really resolves the issue” | Current scope + `objectiveProfile=fix-verification` | Original Finding removal, same-pattern instances, regressions, test discrimination |
| “Audit it and then fix the local issues” | Any scope above + `executionMode=audit-and-fix` | Audit first, then batch fixes by Finding with independent re-verification |

## Core mechanisms

- **Contract before method**: lock target, scope, objectives, risk tolerance, evidence, and deliverable before dispatch; ask only about ambiguities that would change the conclusion.
- **Four semantic layers**: investigators produce Hypotheses + DIRECT Evidence; after disconfirmation, the main agent normalizes Findings and independently finalizes Decision, Severity, and Confidence at the Decision layer.
- **Risk before agents**: define risk surfaces and decidable invariants first, choose verification methods second, assign agents last. Agent count is not a coverage metric.
- **Share facts, isolate judgment**: `audit.md` provides target/base/head/scope; `project-map.md` adds reusable DIRECT facts such as terminology, entry points, and changed files. Isolate Hypotheses, Findings, Decisions, and expected answers.
- **Method heterogeneity reduces correlated error**: highest-risk invariants require at least two different archetypes; two agents repeating the same method count only as redundant review.
- **Disconfirmation first**: every material Hypothesis being promoted to a Finding must record a counter-hypothesis, expected safe behavior, actual disconfirmation search, and result.
- **Severity ≠ Confidence**: risk dimensions map to Severity, while Confidence independently expresses certainty. Each Evidence item separately records Strength + Reproducibility.
- **Change risk ≠ pre-existing risk**: when attribution matters, record Provenance as `INTRODUCED / EXPOSED / REGRESSED / PRE_EXISTING / UNKNOWN`; use `—` when attribution is not applicable, so an old bug found during review is not falsely reported as introduced by the change.
- **Decision-oriented reporting**: default output begins with an Executive report (Gate / Top risks / Required actions / Residual uncertainty), followed by a traceable Audit appendix.
- **Persistent state and recovery**: normal mode persists task contract, scope, ledger, coverage matrix, and findings under `.audits/`; when not writable, use isomorphic session state and disclose reduced cross-session recoverability.
- **Explicit stop conditions**: stop after required coverage, material Hypotheses, Finding Decisions, and residual risks are closed. After two consecutive rounds with no material delta, do not expand without justification. When decisive Evidence is objectively unavailable, an `INCOMPLETE` result can still complete the audit task.

## Output and gates

The default report is decision-first: **Executive report → Audit appendix**. The Executive report answers whether the target can merge/release, the largest risks, required actions, and what remains unverified. Full H/E/F/Decision chains, coverage, probes, and commit matrices stay in the appendix or traceability mode.

| Gate | Meaning |
|---|---|
| `READY` | The task contract and required coverage are closed, with no known blocker or outstanding condition |
| `READY-WITH-CONDITIONS` | No blocker remains, but explicit non-blocking conditions, unresolved Medium/Low items, or residual risks remain |
| `BLOCKED` | A confirmed Critical/High risk relevant to the current gate remains unresolved |
| `INCOMPLETE` | Decisive Evidence, environment access, material-Hypothesis disposition, or required coverage is insufficient to reliably decide whether the target can pass |

`INCOMPLETE` does not necessarily mean the audit process was abandoned. If decisive evidence is objectively unavailable and the gap is explicitly recorded, `INCOMPLETE` can be the correct conclusion of a fully executed audit.

## Usage

- Automatic triggering: trigger and exclusion scope are defined by the `SKILL.md` frontmatter description.
- Default `executionMode=audit-only`; enter `audit-and-fix` only when the user asks to implement local fixes. Commit, push, PR actions, deploy, and production/external writes still require separate authorization.
- `Risk tolerance` affects gate policy and explicit risk acceptance only; it does not change facts, severity, or evidence strength.
- Not for quick summaries, pure style checks, or ordinary narrow questions that do not need cross-validation.

## Installation

- Place this repository in the agent’s skills directory, keeping the folder name `cross-validated-project-audit-en`, e.g. `~/.omp/agent/skills/cross-validated-project-audit-en/`.
- `SKILL.md` must be at the directory root. Keep `references/`, `agents/`, and `assets/` with it; they are loaded on demand via relative paths.
- `agents/openai.yaml` is lazy metadata (omp consumes only `SKILL.md` frontmatter and does not read this file), so no changes are required. `assets/icon.svg` is the Skill icon.
- No explicit invocation is required: the Skill loads automatically when the description trigger matches.

## File structure and on-demand loading

`SKILL.md` is the sole orchestration entry point. References do not chain-load each other. The main agent loads only the modules needed for the current stage/risk.

| File | Type | Load when | Content |
|---|---|---|---|
| `SKILL.md` | core | Every use | Task contract, core principles, module loading, and §1–§7 workflow |
| `references/audit-ledger.md` | core-state | Initialize/restore/write H/E/F/Decision | Four-layer state, project map, coverage, recovery, and archive |
| `references/review-dimensions.md` | core-risk | Building risk coverage | 11 core risk surfaces, 7 archetypes, evidence lenses, and plan risks |
| `references/assessment-model.md` | core-decision | H→Finding / Decision finalization | Disconfirmation, risk dimensions, Provenance, Severity, Confidence, Evidence Strength |
| `references/auditor-persona.md` | conditional | Before actually dispatching subagents | Investigator template and independence discipline |
| `references/git-scoping.md` | conditional | Git/PR/commit/author/history | Scope, identity/commit range, historical Provenance evidence, delivery hygiene |
| `references/behavioral-verification.md` | conditional | Runtime/public-path claims | Public-entry verification, 8-step safe execution order, runtime Evidence |
| `references/platform-runtime-patterns.md` | conditional | Platform/encoding/language-specific semantics | Windows, Unicode, PowerShell, Rust, Node/npm, third-party differences |
| `references/core-failure-patterns.md` | conditional | Need hypothesis seeds/pattern search | 13 failure patterns and safe counterexamples |
| `references/fix-verification.md` | conditional | Fix verification/implementing fixes | Fix mapping, batch gates, heterogeneous re-review, regression validation |
| `references/reporting.md` | output | Final output/gate | Executive report, Audit appendix, gate mapping, output consistency checks |
| `agents/openai.yaml` | metadata | No read required | Lazy metadata |

## Intentional tradeoffs

- **Simple entry, orthogonal internals**: the user expresses only the six task-contract fields; scope type, security objective, fix verification, and whether local modification is allowed are internally separated into orthogonal fields instead of overloading one “mode.”
- **Risk-driven orchestration**: risk surfaces are the coverage key, verification methods are the independence key, and agents are merely execution resources. Shared facts reduce repeated work while judgment isolation preserves independence.
- **Centralized principles, progressive detail**: Git commands, state templates, platform semantics, and similar details remain in references; rules are not duplicated merely to force a uniform format.
- **Harness-agnostic**: does not hard-code task/hub/agent:// orchestration APIs. Subagent/main-agent scheduling uses whatever the current platform supports.
