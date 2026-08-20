# Risk Surfaces, Verification Methods, and Evidence Lenses

Coverage design always follows **Risk → verification method → executor**. First answer “which risks must be covered, and what Evidence can distinguish correct from incorrect behavior?” Only then choose executors. Agent count is not a coverage metric. Sharing DIRECT facts from `project-map` does not break independence; what must remain isolated are Hypotheses, interpretations of Evidence, Findings, Decisions, and expected answers.

## 1. Core risk surfaces

Build the risk map from the task contract, change boundaries, public entry points, state/data boundaries, and failure consequences. Select only risk surfaces that are realistically relevant to the current artifact; do not mechanically cover every category on every audit.

| Risk surface | Core question | Typical trigger |
|---|---|---|
| `correctness` | Does input→processing→output satisfy core invariants, and do error paths produce correct results? | All nontrivial implementations |
| `state-consistency` | Do transitions, ordering, re-entry, cancellation, and partial completion leave contradictory state? | UI, workflows, sessions, queues, caches, long-running flows |
| `persistence` | Are schema, transactions, idempotency, legacy data, migrations, cache/file persistence, and rollback consistent? | DB, cache, file formats, migrations |
| `concurrency` | Are races, lock ordering, cancellation, timeouts, retries, backpressure, and resource lifecycles safe? | Threads, async, queues, long-lived connections |
| `boundary-conditions` | Are nulls, extremes, invalid input, encoding, paths, capacity, and partial failure handled correctly? | External input, parsing, files, batch work, cross-platform code |
| `security` | Can trust boundaries, authentication/authorization, injection, secrets, privacy, supply-chain, or execution surfaces be realistically exploited? | Identity, network, files, serialization, external input |
| `compatibility` | Are APIs/protocols/CLI, legacy callers, versions, platforms, and actual third-party semantics compatible? | Public interfaces, SDKs, protocols, cross-platform, dependency upgrades |
| `regression` | Is prior behavior broken, do tests distinguish wrong implementations, or have historical defects returned? | All nontrivial changes, fixes, refactors |
| `performance-resource` | Are complexity, memory, I/O, caches, limits, resource ceilings, and degraded paths acceptable? | Hot paths, large data, background jobs, high concurrency |
| `observability-recovery` | Are error propagation, sanitized logs, metrics, alerts, recovery, disaster handling, and retry safety sufficient? | Services, background jobs, critical flows |
| `delivery` | Are commit set, build, feature flags, dependencies, packaging, generated artifacts, exports, upgrade/rollback, and release notes complete? | PRs, branches, release candidates, fix commits |

CLI, UI, migrations, SDKs, and plans are not extra scheduling keys; they determine which risk surfaces activate. For example, UI often activates `state-consistency` / `boundary-conditions` / `compatibility`; data migration often activates `persistence` / `delivery` / `observability-recovery`.

## 2. Verification-method archetypes

An archetype defines **how** to independently discover or refute an issue. Heterogeneity comes from different methods and evidence sources, not different agent names.

| Archetype | Primary action | Best for proving/refuting |
|---|---|---|
| `implementation-trace` | Follow real implementation through calls, data, and error paths to effects | Logic errors, missing guards, incorrect call chains, unreachable assumptions |
| `user-path-trace` | Start from public CLI/API/UI/migration/SDK entry points and follow real user behavior backward | Reachability, integration defects, divergence between public behavior and internals |
| `state-invariant-analysis` | Define state machines/invariants and enumerate transitions, re-entry, cancellation, partial failure | State consistency, concurrency, lifecycle, recovery |
| `test-discrimination` | Determine whether tests fail on PRE-fix/wrong implementations; use isolated mutation when useful | Fake regression protection, brittle mocks, tests of implementation detail only |
| `adversarial-challenge` | Construct counterexamples, attack paths, boundary input, and failure injection | Security, boundaries, error handling, overconfident Hypotheses/Findings |
| `history-regression-analysis` | Inspect historical implementation, reverts, related commits, prior defects, behavior changes | Regression, attribution, compatibility, previously fixed defects that returned |
| `contract-spec-verification` | Compare requirements, schema, protocol, official/version-specific contracts, and public promises | Requirements fidelity, APIs/protocols, third-party/platform semantics, documentation claims |

A method may produce auxiliary Evidence, but **silently switching methods does not let the result count as independent proof under the original archetype**. If an archetype cannot run because the environment is unavailable, record a coverage gap and choose another method that can answer the same risk claim. The substitute must be explicit in the matrix.

## 3. Evidence lenses (auxiliary, not scheduling keys)

Evidence lenses remind the audit which class of promise is being evaluated. They may be attached to risk units but do not determine agent count.

| Evidence lens | Core question | Use when |
|---|---|---|
| `requirements` | Was something omitted, partially implemented, implemented beyond scope, or contrary to spec? | Issue, spec, plan, or acceptance criteria exist |
| `engineering` | Even if requirements are met, can runtime/state/data/recovery still be wrong? | All nontrivial implementations |
| `user-behavior` | Do real entry points produce the expected visible behavior? | CLI, API, UI, migration, SDK, runtime |
| `delivery` | Can the artifact be correctly built, packaged, released, upgraded, and rolled back? | PR, branch, release candidate, fix commit |

One risk unit may carry one primary lens; different methods may share the same lens. **Same lens does not mean same method, and changing lenses does not automatically make the same method heterogeneous.**

## 4. Risk-driven coverage selection

1. List relevant risk surfaces from Audit objectives, changed/touched boundaries, public entry points, state/data boundaries, and failure consequences.
2. For each surface, write a decidable “risk claim/invariant” plus realistic failure consequence, then assign a coverage priority: `highest` (a wrong judgment could directly change the gate or cause major damage), `high` (clear important impact), `normal` (other relevant risk). This is dispatch priority, not Finding severity, and must not be lowered because `Risk tolerance` is looser. Do not fill a surface just to satisfy a checklist when there is no concrete claim.
3. For each high-risk claim, select a verification archetype that can **distinguish true from false** before assigning executors; executor selection is last.
4. Highest-risk invariants require at least two **different archetypes** with information isolation. Prefer different evidence sources, e.g. implementation trace + public path or contract + adversarial challenge.
5. Investigators may share DIRECT facts such as baseline, scope, terminology, public entry points, and changed files without weakening independence. If a prior Hypothesis/Finding/Decision or interpretive conclusion is shared, judgment can no longer be claimed independent. Two executors using the same archetype and evidence path remain redundant review only.
6. Every material Hypothesis being promoted to a Finding completes the minimum disconfirmation required by the task protocol. A Finding with provisional Critical/High Severity must attempt a second heterogeneous-method challenge or equivalent direct disconfirmation before Decision finalization; completion is a prerequisite for `CONFIRMED` method coverage. If impossible, record the coverage gap and map the gate appropriately rather than duplicating agents for formality.
7. Executors may be the main agent or subagents. One executor may cover multiple low-risk units; one high-risk claim may be covered by multiple units/executors. **Do not hard-code “one agent = one risk surface.”**
8. Do not require every risk surface to use every archetype. Choose the smallest method set sufficient to distinguish key failure modes.
9. The main workflow’s `stopPolicy` decides whether a new exploration round continues. This module only identifies whether there is a new material Hypothesis (expected to become a Medium+ Finding if true), Evidence that changes Decision/Severity/gate or crosses a Confidence threshold, a systemic pattern, a new highest/high risk, or a critical conflict. It does not duplicate stop thresholds.

## 5. Common target combinations

| Scenario | Priority risk surfaces | Common heterogeneous methods |
|---|---|---|
| Small backend fix | correctness, boundary-conditions, regression | implementation-trace + test-discrimination |
| Security audit | security, boundary-conditions, state-consistency | adversarial-challenge + user-path-trace / contract-spec-verification |
| Authentication change | security, state-consistency, compatibility, regression | adversarial-challenge + state-invariant-analysis + user-path-trace |
| Data migration | persistence, compatibility, observability-recovery, delivery | state-invariant-analysis + history-regression-analysis + user-path-trace |
| CLI / UI | state-consistency, boundary-conditions, compatibility, regression | user-path-trace + state-invariant-analysis + test-discrimination |
| Author-scoped commits | correctness, regression, delivery | implementation-trace + history-regression-analysis; author identity/range comes from Git scope module |
| Release candidate | compatibility, regression, delivery, observability-recovery | user-path-trace + contract-spec-verification + history-regression-analysis |
| Fix verification | original Finding risk surface + regression | archetype **different from the original primary discovery method** + test-discrimination / user-path-trace |

## 6. Risk dimensions for plan artifacts

Plans are still reviewed by risk claims, not by assigning “plan reviewers”:

| Dimension | Key checks |
|---|---|
| Facts and reuse | Does the plan ignore existing helpers/patterns/components? Are critical APIs, schemas, budgets, and platform facts real? |
| Completeness and order | Dependencies, migration ordering, old/new coexistence, consumers, generated artifacts, release steps |
| Failure modes and rollback | Partial completion, concurrent rollout, retry, rollback, recovery, irreversible steps |
| Acceptance and testing | Is every outcome observable/testable? Can verification distinguish success, failure, and fallback? |
| Security and operations | Permissions, secrets, supply chain, monitoring, capacity, deployment windows, responsibility boundaries |
| External facts | Read primary sources for libraries, protocols, platforms, and historical precedents; do not substitute secondary summaries |
| User tradeoffs | Scope, priority, product semantics, and cost/risk differences between multiple reasonable options |

Before promoting a plan-related material Hypothesis to a Finding, the main agent separates **FACT** from **JUDGMENT**:

- **FACT**: paths, API signatures, existing helpers, dependency versions, schema, platform constraints, historical precedent. Resolve by reading code/config/official sources. By default update the audit conclusion, not the plan itself.
- **JUDGMENT**: scope, priority, product semantics, and cost/risk tradeoffs between multiple reasonable architectures. Present real options and impacts; after forming a Finding, use Decision=`NEEDS-DECISION`.
- If an external fact lacks enough Evidence and becomes a Finding, use Decision=`CONDITIONAL`; do not disguise it as a user-preference question.

A plan is ready only when all conditions hold: critical requirements have task coverage, dependency ordering is real, failure/rollback is handled, acceptance is decidable, and no issue remains that would cause an implementer to act incorrectly or become blocked. Blockers do not automatically downgrade merely because enough review rounds have run.
