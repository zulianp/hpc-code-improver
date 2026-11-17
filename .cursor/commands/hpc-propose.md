# /hpc-propose — design the fix for one finding (no code changes yet)

Usage: `/hpc-propose F-NNN`

You are the Implementer, in design mode. Write `.agent/work/F-NNN/proposal.md`, set the finding's status to `proposed`, and stop. A human may veto or amend the proposal before `/hpc-apply`.

## proposal.md template
```markdown
# Proposal for F-NNN — <title>
type: bug-fix | refactor | perf | api | test-only | ci
## Root cause
<what is wrong, with file:line, in 3-6 sentences>
## Change
<files and functions to change; the smallest diff that fixes the root cause>
## Invariants that must hold afterwards
- results identical (bitwise) | identical within rtol=<x> because <error argument>
- public API/ABI unchanged | changed: <what> (deprecation plan: ...)
- thread safety / determinism unchanged
## Tests (written BEFORE the fix)
- <test name>: what it asserts; expected: fails on base (bug-fix) / passes on base (characterization)
## Performance
- benchmark(s) that exercise the path: <names>; new benchmark needed: yes/no
- expected effect: <direction and rough size, with reasoning>; risk of slowdown in: <cases>
## Portability
- platforms affected; what can be verified here; what is UNVERIFIED-<platform>
## Alternatives considered
- <alt>: rejected because ...
## What could go wrong (self-review)
- <the 3 most likely ways this change is wrong>
```

## Rules
- If the honest fix is large, propose a staged plan: several findings, each independently gate-able.
- If the fix requires changing a protected file (CI, gate config), write the patch to `.agent/work/F-NNN/ci.patch` for a human. Don't plan to apply it yourself.
- If you can't find a fix that keeps both invariants (correctness, performance), say so and recommend `wontfix` or a human decision.
