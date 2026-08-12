---
name: universal-audit-review
description: "Run a multi-agent audit or review of any project artifact — a feature branch, a commit, an implemented feature, or an implementation plan — with 4-15 READ-ONLY subagents across security/logic/UI/CLI/tests/i18n/concurrency/git/regression dimensions, then personally re-verify every finding and adjudicate ADOPT/DECIDE/REJECT. Use when the user asks to 审计/审核/审查/审阅 a 分支/commit/PR/计划/已实现功能 全面/多角度/从各个方面, or asks 修复得对不对/commit 是否合理. Also covers the fix-verify loop when the user requires fixes with per-batch verification."
---

# Universal audit & review — multi-agent, personally re-verified

Audit any project artifact with read-only subagents, then **re-verify every finding yourself**. The core loop — baseline → dispatch → re-verify → adjudicate → fix → verify — is the same for every artifact; only the scoping differs.

## When to use (pick the artifact)

| Artifact | Scope | Dispatch |
|---|---|---|
| **Feature branch / PR** | `git log --oneline base..head` + `git diff --stat base head` | 8-10 agents |
| **Fix commit** (post-audit remediation) | prior audit report + fix diff, finding→fix mapping | 10-15 agents |
| **Implemented feature** (delivered work) | plan file + branch state | 8-10 agents |
| **Implementation plan** (pre-execution) | plan file + its key claims | 4 agents |

## Baseline (inline, before any agent)

1. **Topology pre-check**: `git log --oneline <base>..<head>` AND `git diff --stat <base> <head>`. A squash-merge makes `base..head` empty while the branch content IS the base's tree — audit framing changes completely. Verify with `git log -1 <squash-commit>` + `git diff --stat origin/master <branch-head>`.
2. **Establish the baseline**: build / vet / full test green; record the **pre-existing-failure list** (env-only tests, corpus-dependent vendor tests) so agents never re-report them.
3. **Read the full diff yourself** before dispatching. Personal knowledge of every subsystem is what lets you write per-agent scopes and adjudicate later.
4. **Write the verified-facts table**: API signatures, budgets, precedents, hard rules (panic=abort, clippy zero, i18n parity, patch markers) — agents don't re-derive what you already verified.

## Dispatch (one `task` call, all READ-ONLY)

Dimension template — assign one agent per dimension, crop to the artifact:

- **security-reviewer**: redaction/sanitization boundaries (real P1s hide here), credential handling, vendored-crate crash surface
- **reviewer**: core logic / UI-dialog state machines (index math!) / CLI contract (error text, exit codes) / test discrimination / concurrency-memory (bounded waits, RAII release, thread lifetime) / regression truth
- **scout**: docs consistency (overclaim detection) / git delivery integrity (stray files, markers, exports) / interop-release evidence

Every agent gets: exact paths, the diff (or its path), the verified-facts table, pre-existing-failure list, severity rubric (P0 runtime-break/data-loss/leak; P1 normal-path bug/regression; P2 edge/robustness; P3 style/doc), a "verified by reading vs inferred" marking requirement, and a **verified-correct list** (positive coverage for you). Pre-export per-subsystem diffs to a shared file (e.g. `.audit-share/<name>-diff.txt`) — scouts often cannot run git/bash. Do NOT pass `"outputSchema": false` (preflight rejects it; omit the field).

## Re-verify every P0/P1/P2 (non-negotiable)

- Read the actual code site; trace the interleaving; run the logic yourself. Agents misread — the strongest single-source finding still needs your eyes.
- **Cross-validation rule**: a finding from 2+ independent agents = near-certain truth; single-source findings need the strongest evidence.
- **Empirical probes are the killer tool**: throwaway programs (delete after) that call the REAL functions — feed sanitizers CJK/Cyrillic input, compute old-vs-new titles, actually run `os.Mkdir`/`os.Rename` for Windows FS claims. Verify platform claims on the host OS.
- Use `git show <base>:<file>` to see PRE-patch code when a finding questions patch rationale.

## Adjudicate explicitly

Every finding gets a verdict in the final report: **ADOPT** (with fix) / **DECIDE** (needs user) / **REJECT** (with reason). Rejection is legitimate — e.g. an agent re-implementing a PowerShell substring gate in Node with equality-compare false-positives. Classify pre-existing vs patch-introduced honestly (`git show base:file` for the old side) — a finding that predates the branch is still reportable, graded differently.

## Fix-verify loop (only when the user wants fixes)

1. **Batch by severity**: P0/P1 (data/download behavior, lifecycle/security) first; 3-5 fixes per batch so verification stays reviewable. Todo list per batch.
2. **Per batch: STOP and verify before the next.** Build + targeted tests green → dispatch 3-4 READ-ONLY scouts, one per subsystem touched, with: exact fix list, acceptance criteria, severity rubric, evidence format (file:line + verified/inferred), and the instruction to hunt NEW regressions and test discrimination — not just confirm the fix.
3. **Adjudicate their output yourself**: confirmed flaws → fix immediately, re-run affected tests; REFUTED claims → document why; NEW P1/P2 from verifiers → fix before proceeding.
4. **Second round after all batches**: fix remaining P2/P3 (cheap ones), update CHANGELOG, gofmt only touched files.
5. **Cleanup LAST**: remove `.audit-share/`, temp probes, worktrees; `git status --porcelain` shows only intended changes; run `lat check` where the repo uses lat.md.

## Completion criteria

- Every accepted finding has a code-level re-verification note in the final report
- Per-agent verdict table (dimension / finding / your evidence / verdict) + verified-correct list
- Residual gaps stated honestly: release-build-only risks, untested UI interactions, temp-dir-only interop probes
- Report: severity table with file:line + evidence, prioritized fix list

## Known traps (from practice — verify each before accepting)

- **Test discrimination**: would each new test FAIL if the fix were reverted? A test passing on pre-fix code is false confidence (an ordering test that trips the same SQL trigger on both paths).
- **Docs overclaim**: CHANGELOG/API/lat.md claims exceed code — "409 on concurrent rename" is cross-process-only when an in-process lock serializes; "URL userinfo not logged" may have no code path for that sink.
- **Fix breaks the legacy data it claims to migrate**: adding a validation rule then validating OLD names on the rename path wedges pre-existing records (downloads error every run; recovery = direct DB edit). Exempt old names or normalize before compare, with a legacy-record migration test.
- **Dead code left behind**: the fix's new helper replaces a full-row writer that stays alive in tests — the old hazard re-embodies in test-only code.
- **Newly-activated paths expose latent bugs**: wiring a previously-dead endpoint activates a latent timezone round-trip defect (stored UTC, displayed wall-clock, re-parsed as browser-local → shifts per edit).
- **Unbounded waits in shutdown hardening**: `activeMutations.Wait()` / `<-startupDone` with no timeout hang forever on a stuck handler; a blocking session.Open with no timeout defeats the startupDone handshake.
- **Gate semantics**: PowerShell `-notmatch` with a regex-escaped substring PASSES for a 4-part version extension ("1.4.1" ⊂ "1.4.1.0"); equality-compare replications false-positive. Verify actual match semantics.
- **Rust shift semantics**: `<<` panics ONLY on shift amount >= bit width; shifted-out VALUE bits are silently discarded in debug AND release. "Debug overflow panic" claims for small bounded literals are wrong → DEFENSIVE-ONLY, not a panic fix.
- **Windows path semantics**: trailing dots/spaces pass validation but Win32 strips them → record/dir divergence; `os.Rename` onto an existing EMPTY dir fails on Windows (no silent replace).
- **Vacuous tests**: local mirror helpers instead of production functions; `if success { assert }` swallowing the failure branch. Pin production functions (make pub if needed) and assert specific error text.
- **Squash-merged master**: `base..head` empty ≠ branch empty — always diff base against the branch head.
- **Lost-update full-row writes**: `UPDATE ... SET a=?,b=?,c=?` from a T0 snapshot silently revert concurrent monotonic writes.
