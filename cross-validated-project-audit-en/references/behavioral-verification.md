# Real User-Path and Runtime Verification

Load this file only when a Hypothesis/Finding involves user-visible behavior, public API/CLI behavior, migrations, platform semantics, concurrency interleavings, or third-party runtime behavior. The goal is to verify real entry points, not to accumulate passing test results.

## 1. Choose the public entry point

| Artifact | Preferred entry point | Key observations |
|---|---|---|
| CLI | Real command, argument combinations, batch invocation | Exit code, stdout/stderr, error text, state changes |
| API/service | Public endpoint, SDK, or protocol request | Auth context, response, errors, retries, side effects |
| UI | User-visible pages and controls | Gating, navigation, cancel/re-entry, persisted state, keyboard/a11y |
| Data/migration | Real legacy data shape and migration entry point | Compatible reads, partial failure, recovery, retry, rollback |
| Library/SDK | Public exports and representative callers | Signature, defaults, exceptions, version and installed artifact |
| Concurrency/lifecycle | Production scheduling, cancellation, shutdown, resource boundaries | Interleavings, timeout, release, duplicate calls, backpressure |

Prefer entry points that users or callers can actually reach. Test helpers, internal functions, and mocks can support local claims but cannot replace a public path.

## 2. Record a verification profile

For every Hypothesis/Finding requiring runtime Evidence, retain:

```text
Entry point: <command, endpoint, UI path, public function, or migration entry>
Environment: <OS, version, build mode, dependency versions>
Pre-state: <data, config, identity, filesystem state>
Action/command: <repeatable steps; use placeholders for sensitive values>
Expected: <from requirements, contract, or established compatible behavior>
Observed: <observable output, state, or side effect>
Repeatability: <repeatable / conditional / single-observation; align with Evidence Reproducibility>
Cleanup: <temporary resources removed and real systems left untouched>
```

Keep only the minimum reproduction detail needed to establish the issue. Never echo secrets, real user data, private keys, tokens, or sensitive URLs.

## 3. Safe execution order

1. Statically trace the entry point, call chain, guards, and possible impact.
2. Reuse repository tests/tools that have already been inspected and directly relate to the target Hypothesis/Finding.
3. Invoke the smallest public path and bound input, time, resources, and network scope.
4. When state must change, use an isolated copy outside the repository, a temporary worktree, disposable database, or disposable environment.
5. Pause and request authorization before installing tools, downloading dependencies, expanding network access, using credentials/paid resources, writing to external systems, or accessing production.
6. If the target platform is unavailable, inspect the authoritative contract for the relevant version. If that contract fully covers the call chain, version, config, and trigger conditions, it can form strong contract-only Evidence. If the claim still depends on target state or integration semantics, record the target-environment verification gap for the main agent to handle in Decision/gate.
7. If local reproduction is impossible, add temporary instrumentation in the real environment only after obtaining the necessary user authorization and main-agent approval. Use a consistent prefix; have an operator reproduce and return forensic logs; remove instrumentation after diagnosis while preserving defensive logic. Sanitize instrumentation and logs.
8. Clean up probes, temporary instrumentation, temporary files, processes, containers, and test data; then re-check the original workspace and real-environment state.

Do not directly execute unchecked lifecycle, build, install, hook, or test scripts merely for forward verification. Read scripts/config first and identify downloads, arbitrary code execution, secret access, and external side effects.

## 4. Build minimal scenarios by risk

- **Happy path**: first confirm the basic user workflow completes and output matches requirements; do not stop at “process exited” or “page rendered.”
- **Common variation**: cover empty values, boundaries, repeated calls, different ordering, or batch input that a user would naturally try. Do not invent scenarios requiring many rare prerequisites unless impact is Critical and the prerequisites are realistic.
- **Error and cancellation**: cover missing input, obviously invalid input, dependency failure, cancellation, timeout, and partial completion. Check that original errors are preserved, resources are released, and state can be safely retried.
- **Legacy data and callers**: use representative old schema/config/serialized values/call signatures. Verify compatible reads, migration, fallback, and explicit incompatibility gates.
- **Concurrency and lifecycle**: construct the smallest interleaving; define synchronization points, expected invariant, and timeout bound. If stable reproduction is impossible, record the interleaving assumption and environment limitation; do not treat a sporadic signal as confirmed fact.

## 5. Evidence Strength, reproducibility, and Decision

This section **produces/evaluates Evidence only; it does not make Decisions**. Tag every runtime Evidence item using the unified Strength / Reproducibility vocabulary already loaded by the task. Final Decision, Severity, and Confidence belong to the main agent at the Finding/Decision layer.

- A real public path with repeatable steps that stably reproduces the target behavior is normally at least `ES3`; only reproduction through a real public entry point under the target platform/version/build conditions relevant to the claim reaches `ES4`. An authoritative contract for the matching version may increase overall Confidence, but cannot upgrade a non-target environment or internal-helper-only reproduction to `ES4`.
- A complete static call/data/contract chain that can be independently re-checked but lacks executable reproduction is normally `ES2`; a local code/log/output indication whose conditions are not closed is `ES1`. These grades describe Evidence quality, not Confidence.
- Guards, safe counterexamples, unreachable constraints, or real runtime results that negate the claim become DIRECT refuting Evidence.
- When behavior facts are established but acceptance is a product/compatibility policy question, Evidence records facts and impact only; the main agent decides whether user/product judgment is required.
- When Evidence conflicts, compare Strength, Reproducibility, target-version/public-path relevance, and unexplained prerequisites. Repeatable target-environment refutation generally outweighs local simulation or partial static indication. Preserve both sides and investigate the conflict; do not vote by count.

An agent report itself, an unsourced log fragment, passing tests, or a one-off failure cannot alone be decisive Evidence.

## 6. Pair with heterogeneous verification methods

- For runtime/public-behavior risks, prefer pairing `user-path-trace` with a different archetype such as `implementation-trace`, `state-invariant-analysis`, or `contract-spec-verification`.
- Do not leak the expected conclusion from the first independent path into the second. Two agents copying the same public-path execution do not automatically create method heterogeneity.
- The main agent checks current risk coverage for different archetypes and evidence sources. The same code inference cannot masquerade as two independent proofs.
- If probes/tests must be written, the main agent approves the isolated location and cleanup plan. Discovery-stage subagents must not modify project source; the only exception is their own `investigations/` artifact.

## 7. Reporting when verification is unavailable

State: what static tracing/supporting Evidence was completed; which target environment, version, credentials, or external prerequisite is missing; the minimum follow-up verification that would distinguish true from false; and leave gate impact to the unified main-agent reporting/gate layer. This module does not map gates itself.

Do not replace missing evidence with “looks like it should,” “both agents agree,” or simulation on another platform.
