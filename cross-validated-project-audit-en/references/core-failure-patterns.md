# High-Value Cross-Project Failure Patterns

Load this file only when you need Hypothesis seeds, systematic pattern search, or when the initial risk map has a clear blind spot. Every item below is a **Hypothesis seed**, not an automatic Finding. Return to the current artifact, obtain DIRECT Evidence, and actively search for disconfirmation/safe counterexamples.

## Index

- Tests lack discrimination
- Tests mirror the implementation instead of production paths
- Failure branches are swallowed
- Tests or compatibility code keep old risk alive
- New validation blocks legacy data
- Full-object writeback causes lost updates
- Multi-boundary operations leave partial state
- Retry is not idempotent
- Shutdown or waits are unbounded
- New entry points activate latent defects
- Implementation exists but is not wired, or old paths still dominate
- Documentation or plans overclaim
- Delivery tree does not match intent
- Pattern-scope usage

## Tests lack discrimination

- **Trigger signal**: a new test still passes after restoring the old implementation, removing the guard, or switching success/failure behavior.
- **Search for disconfirmation**: does the test truly reach the target branch and assert the error type, state, or side effect?
- **Minimal verification**: run on the PRE-fix version, or apply a minimal mutation in an isolated copy.
- **Close the Hypothesis when**: the test is explicitly only a smoke test and the target behavior is covered by other discriminating tests.

## Tests mirror the implementation instead of production paths

- **Trigger signal**: a test helper reimplements the production algorithm, a mock bypasses the real boundary, or only a duplicate parser is tested.
- **Search for disconfirmation**: is there another test that calls the public entry point or production choke point and covers the same invariant?
- **Minimal verification**: trace the actual call chain from the user/caller entry point and compare it with the test path.
- **Close the Hypothesis when**: a pure function is genuinely shared by production and tests and the helper does not duplicate logic.

## Failure branches are swallowed

- **Trigger signal**: broad exception handling, assertions only that “it does not crash,” skipped assertions on failure, or errors replaced with success defaults.
- **Search for disconfirmation**: does the caller explicitly treat the error as ignorable while preserving observable state?
- **Minimal verification**: force the failure branch and inspect return value, state, logs, and side effects.
- **Close the Hypothesis when**: the error is intentionally downgraded and contract, metrics, and recovery behavior are consistent with that design.

## Tests or compatibility code keep old risk alive

- **Trigger signal**: a new implementation replaces an old helper/writer/route/export, but the old path is still referenced by tests, feature flags, or callers.
- **Search for disconfirmation**: is the old path safely encapsulated, present only in non-shipping historical fixtures, or covered by an explicit compatibility sunset?
- **Minimal verification**: search symbols, exports, routes, registries, feature/test-only builds, and final package contents.
- **Close the Hypothesis when**: the old entry point remains intentionally supported and is as safe as the new one.

## New validation blocks legacy data

- **Trigger signal**: a migration, rename, or fix path validates historical values with new rules first, so old records can never be processed.
- **Search for disconfirmation**: is there a legacy-value exemption, normalization, explicit migration, or compatible read path?
- **Minimal verification**: send representative old records through the real migration/modification entry point.
- **Close the Hypothesis when**: the product intentionally rejects legacy data and provides an executable migration/cleanup gate.

## Full-object writeback causes lost updates

- **Trigger signal**: a whole row/object is written back from an old snapshot, overwriting monotonic or independent fields produced concurrently.
- **Search for disconfirmation**: do transaction isolation, version predicates, locks, or field-level updates prevent overwrite?
- **Minimal verification**: draw the read/write timeline, construct two interleaved updates, and inspect the final state.
- **Close the Hypothesis when**: ownership is single-writer and that invariant is enforced by code or storage.

## Multi-boundary operations leave partial state

- **Trigger signal**: file written before metadata, multi-table or external/local operations without a transaction, compensation, or recovery marker.
- **Search for disconfirmation**: is there atomic rename, transactionality, idempotent compensation, startup recovery, or an invisible staging area?
- **Minimal verification**: inject failure at every I/O boundary and inspect public content, temporary state, indexes, and retry behavior.
- **Close the Hypothesis when**: intermediate state is invisible, automatically recoverable, and brief inconsistency is contractually allowed.

## Retry is not idempotent

- **Trigger signal**: after partial success, retrying the whole batch duplicates messages, charges, version advancement, writes, or resource creation.
- **Search for disconfirmation**: are idempotency keys, completion prefixes, dedup storage, transaction boundaries, or precise retry classifications present?
- **Minimal verification**: make the first call fail at the last boundary, then retry with identical input.
- **Close the Hypothesis when**: the operation contract is explicitly at-least-once and consumers safely deduplicate.

## Shutdown or waits are unbounded

- **Trigger signal**: `wait`, receive, join, handshake, or drain has no timeout, cancellation, or failure propagation.
- **Search for disconfirmation**: does an upper layer impose a hard deadline, and is the resource guaranteed to terminate?
- **Minimal verification**: block the producer/handler and check whether shutdown can finish within a bounded time and release resources.
- **Close the Hypothesis when**: the process-level contract permits an indefinite service and this wait is not on a user-triggerable shutdown path.

## New entry points activate latent defects

- **Trigger signal**: a new route, export, UI entry point, or feature flag connects previously dormant code so an old defect becomes reachable.
- **Search for disconfirmation**: was the old code already callable only under controlled conditions, or does the new entry point add complete protection?
- **Minimal verification**: trace from the new entry point through permission, state, serialization, timezone, and error paths.
- **Close the Hypothesis when**: the latent defect remains unreachable and stable constraints enforce that unreachability.

## Implementation exists but is not wired, or old paths still dominate

- **Trigger signal**: new code is not exported, registered, routed, or included in the build; callers still bypass it and use old behavior.
- **Search for disconfirmation**: is it reliably wired through auto-discovery, code generation, or runtime registration?
- **Minimal verification**: inspect entry points, exports, registries, feature flags, generated artifacts, and final package contents.
- **Close the Hypothesis when**: the code is intentionally disabled for a later phase and the current requirement does not claim availability.

## Documentation or plans overclaim

- **Trigger signal**: conditional, in-process, or platform-specific behavior is documented as an absolute guarantee.
- **Search for disconfirmation**: do production paths, tests, or authoritative contracts support the full claim?
- **Minimal verification**: map every user-visible claim to “claim → implementation → test/evidence.”
- **Close the Hypothesis when**: wording clearly limits conditions, version, platform, and known exceptions.

## Delivery tree does not match intent

- **Trigger signal**: missing lockfile, workspace member, vendor marker, generated artifact, export, docs, test, or config; or unrelated files are included.
- **Search for disconfirmation**: does project policy automatically generate or intentionally exclude those files?
- **Minimal verification**: compare requirements, commit set, name-status, build config, and final artifacts item by item.
- **Close the Hypothesis when**: missing items are reliably generated by the release process and that process plus inputs have been verified.

## Pattern-scope usage

After the main agent confirms an instance, record:

```text
Root-cause pattern:
Confirmed instances:
Safe counterexample:
Search scope and method:
Uncovered scope:
Scope decision: ISOLATED / SYSTEMIC / UNKNOWN
```

Never declare a systemic defect merely from the same function name, similar strings, or multiple agents agreeing.
