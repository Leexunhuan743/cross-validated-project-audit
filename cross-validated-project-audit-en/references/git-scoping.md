# Git Artifact Scoping

Load this file only when auditing a Git branch, PR, commit, author-scoped commit set, workspace, or **Git-backed** remediation batch. Report history topology, review patch, and final tree state separately; do not substitute one for another.

## Index

- Pre-dispatch checks
- PRs and feature branches
- Single commits, ranges, and merge commits
- Author-scoped commits
- Workspaces and multiple worktrees
- Squash, rebase, and cherry-pick equivalence
- Submodules, LFS, generated files, and delivery hygiene
- Baseline attribution

## Pre-dispatch checks

Read higher-level instructions first, then run safe read-only queries:

```bash
git status --short
git rev-parse --show-toplevel
git branch --show-current
git worktree list --porcelain
git remote
git for-each-ref --format='%(refname:short)' refs/remotes/
```

Do not clean, stash, reset, overwrite through checkout, or delete workspace state. Tracked changes, staged changes, untracked files, and other worktrees are user data.

Do not print `git remote -v` or raw remote URLs by default. Read remote configuration only when the task genuinely requires it, and strip userinfo, tokens, and sensitive query parameters before writing logs, evidence packs, or reports.

Before dispatch, confirm:

1. Every target ref resolves to a commit.
2. base/head match the user request or PR metadata.
3. Review scope is not accidentally empty because of the wrong directory, a bad ref, or the wrong comparison mode.
4. The target worktree is the artifact the user intended.
5. Local dirty state will not be mistaken for PR content and will not be overwritten by audit actions.

If scope is empty, distinguish “truly no content,” “equivalent patch already merged,” “head is already an ancestor of base,” “wrong comparison mode,” and “wrong target worktree.” Never treat empty output as a conclusion by itself.

If a shallow clone or missing objects make `merge-base` fail, fall back to platform PR metadata/patch and record the limitation explicitly. Treat unresolved topology as a residual gap rather than guessing.

## PRs and feature branches

Prefer exact base/head from the user or current PR metadata and resolve them to immutable commits. If multiple plausible baselines would change the conclusion, ask the user first.

```bash
git rev-parse <base>^{commit} <head>^{commit}
git merge-base <base> <head>
git log --oneline --decorate <base>..<head>
git diff --stat <base>...<head>
git diff --name-status <base>...<head>
git diff --find-renames=50% <base>...<head>
```

- Three-dot diff (`base...head`) starts at merge-base and normally represents the patch the PR intends to introduce.
- Two-dot/tree diff (`base head`) compares the two current trees and represents final-state difference.
- When base has advanced, these may differ. Review the intended change using the platform PR patch or three-dot diff, then inspect two-dot/tree state for integration effects.
- `--find-renames=50%` makes the default similarity threshold explicit. For large rewrites where rename detection is misleading, also inspect `--no-renames`; do not let heuristics hide additions/deletions.
- Platform PR diffs may exclude uncommitted workspace content; do not accidentally include local dirty state in the PR audit.

## Single commits, ranges, and merge commits

Ordinary commit:

```bash
git show --stat --summary <commit>
git show --format=fuller --find-renames <commit>
```

A root commit has no parent; `git show <root>` already displays its full patch. Do not use `<root>^` forms that require a nonexistent parent.

Range:

```bash
git log --oneline --reverse <base>..<head>
git diff <base>...<head>
```

For a merge commit, first determine whether the user wants the merge result, the delta against a particular parent, or conflict-resolution changes:

```bash
git show --cc --stat <merge>
git show --cc <merge>
git diff <merge>^1 <merge>
git diff <merge>^2 <merge>
```

For octopus merges, enumerate all parents. Combined diff is not equivalent to per-parent diff; conflict-resolution defects often appear only in combined or parent-by-parent comparison.

## Author-scoped commits

With `scopeMode=author-commits`, resolve both “who is the author?” and “within what immutable range?” before reviewing. By default attribute using Git **author identity**, not committer, reviewer, or merge executor.

1. Resolve and record immutable `<base>` / `<head>` or the user-specified range. If no range is given and multiple reasonable ranges would change the conclusion, ask first.
2. Enumerate commits in range with author name/email, then normalize identity. `--author` is regex matching and may only be used as candidate filtering. Duplicate names, multiple emails, or bot-mediated commits require checking actual identity rather than guessing from display name.
3. Read the real patch and parent relationship for every selected commit; also collect touched paths/symbols and inspect their actual state at target `head`. Content later reverted, overwritten, or rewritten remains historical audit Evidence but must not be represented as still present in the current tree.
4. For each material Finding requiring change attribution, collect directly verifiable base/head, target-commit, historical-implementation, and reachability Evidence. Final Provenance is decided by the unified task assessment model; this module does not duplicate the attribution enum.
5. Report author identity, range, selected commit set, and excluded ambiguous identities. Never equate “this author changed the file” with “all issues in the file were introduced by this author.”

Safe read-only enumeration examples:

```bash
git log --format='%H%x09%an%x09%ae' <base>..<head>
git show --format=fuller --find-renames <selected-commit>
```

If the request is “all historical commits by this author” and repository history is large, first put time/branch/version bounds into `Audit scope`. If reliable exhaustive enumeration is not possible, label it a partial audit.

## Workspace and multiple worktrees

Inspect separately:

```bash
git diff
git diff --cached
git status --short
git worktree list --porcelain
```

`git diff` excludes untracked files. If the user requests “all local changes,” read relevant untracked files but do not add, delete, or rename them automatically. Branch, HEAD, and dirty state are independent across worktrees; run all commands from the target worktree.

## Squash, rebase, and cherry-pick equivalence

Do not infer content relationships from commit count or an empty range:

```bash
git merge-base <base> <head>
git merge-base --is-ancestor <head> <base>
git diff --stat <base> <head>
git rev-parse <base>^{tree} <head>^{tree}
git cherry -v <base> <head>
```

- A typical squash merge does not preserve original branch commits as ancestors. The original commit range is usually still nonempty even though an equivalent patch may already exist in base.
- Empty `base..head` usually means head is an ancestor of base or they are equal; it is not a generic squash-merge signature.
- `git cherry` uses patch-id to help identify equivalent patches, but can fail for squashes, reordered multi-commit work, partial cherry-picks, and conflict rewrites. Fall back to tree diff and actual behavior.
- When comparing two rebased/cherry-picked sequences, use:

```bash
git range-diff <old-base>..<old-head> <new-base>..<new-head>
```

`range-diff` maps commit sequences; it does not replace final tree diff, tests, or runtime verification.

## Submodules, LFS, generated files, and delivery hygiene

Run only tools that actually exist/configure in the repository:

```bash
git diff --submodule=log <base>...<head>
git submodule status --recursive
git lfs ls-files
git diff --check <base>...<head>
```

- Inspect `.gitattributes` before deciding whether LFS applies. If Git LFS is unavailable, record it as unverified; do not install it automatically.
- For submodule pointer changes, verify the target commit is obtainable, source is trusted, and parent code is compatible.
- Reconcile plan/commit set with changed files: missing files, stray files, conflict markers, patch markers, vendor changes, lockfile/workspace changes, export tables, generated artifacts, and `.gitignore`.
- If generated files are supposed to be committed, confirm source and generated outputs are synchronized. If they are not supposed to be committed, confirm they do not pollute the delivery tree.
- Identify binary/large-file changes with `git diff --numstat -- <path>`. Treat files that cannot be line-reviewed as residual gaps rather than silently skipping or automatically passing them.

## Baseline attribution

When the claim depends on “was this already true before?”, read the baseline version:

```bash
git show <base>:<path>
git blame <head> -- <path>
```

`blame` is only a historical clue and never a responsibility judgment. If a root cause is pre-existing but the target change makes it reachable, expands impact, or blocks recovery, classify the Finding as `EXPOSED` and separately state the pre-existing root cause plus incremental impact. If the issue is purely pre-existing and not materially changed by the target change, use `PRE_EXISTING`.
