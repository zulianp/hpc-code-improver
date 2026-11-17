# Implement one finding

No user checkpoint in this file. The parent skill owns choice and approval.

## proposal.md

```markdown
# Proposal for F-NNN — <title>
type: bug-fix | refactor | perf | api | test-only | ci
## Root cause
<what is wrong, with file:line, in 3-6 sentences>
## Change
<files and functions; the smallest diff that fixes the root cause>
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

If the honest fix is large, split it into several findings, each independently gate-able, and return to the choice step with the new ids. Do not implement the whole thing under one id.

If the fix requires a protected file, write `.agent/work/F-NNN/ci.patch` and stop. A human applies it.

If no fix keeps both correctness and performance, say so and recommend `wontfix`. Do not implement a compromise.

## Apply

1. The tree must be clean. `git switch -c agent/F-NNN origin/main` (or `default_base` from `.agent/hpcgate.json`).
2. Baseline sanity, on the unchanged branch: `python3 tools/agent/hpcgate.py check --skip-perf`. If the base fails, stop and report. Do not build on a broken base. This is the only use of `--skip-perf`. The gate in step 5 is a full `check`.
3. **Tests first.** Write the tests from the proposal. Commit them alone: `test(F-NNN): ...`.
   - Bug fix: `python3 tools/agent/hpcgate.py tests-on-base --expect fail` must succeed.
   - Refactor or perf: `python3 tools/agent/hpcgate.py tests-on-base --expect pass` must succeed.
   - Perf with no suitable benchmark: add the benchmark in this same commit.
4. **Fix.** The minimal change from the proposal. No unrelated edits, no formatting, no protected files.
5. **Gate:** `python3 tools/agent/hpcgate.py check`. Every stage must PASS (guard, build, test, outputs, perf).
   - On FAIL, read the report and fix the cause. A perf FAIL means this change is slower. Find out why, or revert the optimization. Do not call it noise. If you believe the threshold is wrong, run `check` on an unchanged tree and report that to the user.
   - After 3 failed attempts, revert to the test commit, set status `blocked`, and write why.
6. Commit the fix: `fix(F-NNN): ...` or `perf(F-NNN): ...`. The body contains the verdict line and the report path.
7. Write `.agent/work/F-NNN/apply-log.md`: what changed, the report path, the perf table (median change, p), any `UNVERIFIED-<platform>`, and deviations from the proposal.
8. Set status `applied`.

Never modify a test from step 3 after the fix fails it. If the test was wrong, go back to step 3, explain it in the apply-log, and re-run tests-on-base.

If the diff outgrows the proposal, stop and update the proposal before continuing. Do not ask the user.

## Address a CHANGES review

Inputs: the latest `.agent/work/F-NNN/review-K.md` and `attack-results-*.json`. Trust the attack classification, not the prose. Re-run `python3 tools/agent/hpcgate.py attack F-NNN` yourself.

- `INTRODUCED`: copy the attack into the real suite, match the project's test conventions, register it, and commit `test(F-NNN): regression test from review K, attack A<n>`. It must fail on the current HEAD. Then fix the code. `check` must PASS, and that attack must come back `REFUTED`.
- `PRE-EXISTING`: do not fix it here. Add a new open finding, confidence `CONFIRMED`, evidence pointing at the attack file. Copy the attack to `.agent/work/F-MMM/attack/`.
- Attacks marked worth promoting, including `REFUTED` ones that are fast and not duplicates: promote them the same way.
- Unproven concerns: one or two sentences each in the apply-log (addressed, not applicable, or `UNVERIFIED-<platform>`).

Append `Response to review K` to `apply-log.md` and set status `applied`. The parent skill then spawns a fresh adversary.

`REJECT`: do not patch around it. Write a new proposal with a different approach, or recommend `wontfix`.
