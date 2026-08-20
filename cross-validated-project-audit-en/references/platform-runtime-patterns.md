# Platform, Language, and Runtime Patterns

Load this file only when the risk map triggers semantics specific to an OS, encoding, language, build mode, or third-party library. Every item requires the target platform, locked version, or authoritative contract for the relevant version. Model memory or simulation on another platform is only Hypothesis/context and cannot masquerade as decisive target-platform Evidence.

## Windows path and rename semantics

- Trailing dots, trailing spaces, reserved names, case folding, and path normalization can make recorded names diverge from real filesystem entries.
- Replacing an existing target, cross-volume moves, renaming open files, and file-vs-directory behavior may differ from POSIX.
- Verify using the real production filesystem functions on the target Windows version with representative paths.
- String comparisons or simulations on Linux can seed a Hypothesis or provide context, but cannot alone support a `CONFIRMED` Decision for a Windows filesystem Finding.

## Unicode, bytes, and normalization boundaries

- Distinguish Unicode code points, grapheme clusters, UTF bytes, display width, and storage length.
- Cover combining characters, normalization forms, CJK, emoji, case folding, and invalid-byte handling.
- Feed inputs through the real production function, then inspect display, serialization, storage, and comparison results separately.
- If the system contract explicitly accepts ASCII only or enforces normalization at the boundary, do not report irrelevant Unicode scenarios as defects.

## PowerShell matching and pipeline semantics

- `-match/-notmatch`, wildcards, equality, array broadcasting, pipeline output, and exit codes are not equivalent.
- Version substrings, regex escaping, and automatic type conversion commonly cause false positives.
- Reproduce the original operator, input shape, and error preference in the target PowerShell version; do not simulate it with another language’s equality rules.
- Distinguish script return values, process exit codes, and writes to the error stream rather than checking only visible console text.

## Rust overflow, shifts, and build modes

- Distinguish integer overflow, out-of-range shift amount, shifted-out bits, debug/release behavior, and explicit wrapping/checked operations.
- Lock the toolchain, profile, and target type, then execute the real expression or production function.
- Do not upgrade defensive-only states, type-system-impossible states, or real-input-unreachable states into runtime defects.
- When build-mode differences cannot be verified, record the verification gap and missing condition; this module does not make the Decision directly.

## Node.js, npm, and package-publication semantics

- Distinguish ESM/CJS resolution (`type`, extensions, default/named export interop) from `require` cache behavior. Reproduce in the target Node version; do not rely on memory.
- On Windows, `child_process` handling of `.bat/.cmd`, shell differences, and spaces in paths require explicit `shell`/`windowsHide` decisions. Exit codes and signals are not cross-platform equivalents.
- Published package contents are controlled by `files`/`.npmignore`/`exports`; installed artifacts may differ from the source tree. When auditing the release surface, use the actual `npm pack --dry-run` manifest.
- Default behavior for uncaught exceptions, unhandled rejections, and `process.exitCode` changes across versions. Lock the target Node contract for lifecycle claims.

## Third-party libraries, protocols, and release/debug differences

- Lock the actual version, features, platform, compiler options, and call mode. Do not substitute the newest documentation for the current-version contract.
- Prefer the smallest real public API path. When execution is impossible, cite official docs, source, or release notes for the relevant version.
- Check defaults, error types, thread safety, encoding, persistence, compatibility windows, and deprecation behavior.
- Same package name, agent consensus, or behavior from an older version cannot independently confirm current semantics.

## Conclusion rules

| Evidence | Typical quality/decision impact |
|---|---|
| Repeatable reproduction through the real public path on the target platform/version | Usually `ES4`; can support high Confidence, but final Decision still belongs to the main agent after disconfirmation and impact assessment |
| Authoritative contract for the matching version plus a complete code path | Usually `ES2`; can confirm pure static contract facts, but if the Finding depends on real state/integration behavior it cannot masquerade as runtime reproduction |
| Simulation on another platform or experiment on a different version | Context/weaker support only; cannot independently confirm target-platform semantics |
| Model memory or an unlocatable claim | Not Evidence; only a Hypothesis/reasoning lead |
| Target environment/version evidence unavailable | Disclose the verification gap and its effect; this module does not speculate about Decision or gate |
