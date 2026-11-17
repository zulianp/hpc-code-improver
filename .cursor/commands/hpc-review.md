# /hpc-review — adversarial review of one applied finding

Usage: `/hpc-review F-NNN` — **start a NEW chat for each review round.** Do not open the implementer's chat or `apply-log.md` before you have written your own hypotheses (step 2). You will see their reasoning later only to check it, never to adopt it.

You are the Adversary. Your job is to **break** the change on branch `agent/F-NNN`, not to approve it. Assume it is wrong until your attacks fail. You are judged on *demonstrated* defects: a claim without a runnable test that fails is worth nothing and cannot block the change.

## 1. Read only these inputs
- The finding entry for F-NNN in `.agent/findings.md` and `.agent/work/F-NNN/proposal.md` (what was promised).
- The diff: `git diff $(git merge-base origin/main HEAD)..HEAD` (adapt the base to `default_base` in `.agent/hpcgate.json`).
- Everything the diff touches: callers, callees, build flags, the tests involved. Read the surrounding code, not only the hunks.
- The latest gate report in `.agent/reports/`.

## 2. Write down hypotheses before you test anything
Write `.agent/work/F-NNN/review-K.md` section "Hypotheses": a numbered list of concrete ways the change could be wrong. Go through every row of this table and write at least one hypothesis per row that applies, or "n/a: <reason>":

| Area | Attack ideas |
|---|---|
| Numerics | FP reordering / FMA contraction changes results beyond rtol; cancellation; NaN/Inf/denormal propagation; mixed precision; the tolerance in the new test is too loose to catch a real error |
| Edge sizes | n = 0, 1, SIMD width ± 1, tile size ± 1, non-power-of-two, > 2^31 elements (index overflow), empty partitions |
| Memory | out-of-bounds in remainder loops, aliasing (in == out, overlapping views), alignment assumptions, lifetime / dangling views, uninitialized reads |
| Concurrency | data races, false sharing, reduction-order nondeterminism, results that depend on the thread count (test 1, 2, 3, 7 threads), nested parallelism, exception safety in parallel regions |
| Portability | `long` on Windows (LLP64), MSVC OpenMP 2.0, Apple Clang without OpenMP, x86 intrinsics on arm64, default FMA contraction on Apple arm64, path/CRLF handling |
| API | changed semantics, units, defaults, ownership, thread safety, ABI layout; callers that relied on the old behaviour |
| Performance | the benchmark doesn't exercise the changed path; only in-cache sizes are measured; the gain is due to dead-code elimination; a regression at other sizes, thread counts or architectures |
| Tests | the new test passes without the fix (check with `tests-on-base`); it tests the implementation, not the behaviour; a golden was regenerated |
| Build/CI | new flags not portable; a target-wide flag leaks into consumers; a configuration that is not covered by CI |

## 3. Prove each hypothesis with a runnable attack
For every hypothesis you believe in, write an attack under `.agent/work/F-NNN/attack/`. Use the project's own test framework (GoogleTest/Catch2/pytest/...), so a useful attack can later be promoted into the suite unchanged.

- A **correctness attack asserts the correct behaviour**: exit 0 = defect absent, non-zero = defect present. Keep it minimal and deterministic: fixed seeds, smallest input that triggers it, tolerance justified in a comment.
- A **performance attack** adds a Google Benchmark case at the sizes/thread counts you suspect. List its name under `benchmarks`.
- Register all attacks in `.agent/work/F-NNN/attack/attacks.json`:

```json
{
  "finding": "F-NNN",
  "attacks": [
    {
      "id": "A1",
      "hypothesis": 3,
      "claim": "remainder loop reads x[n] when n % 8 == 7 (kernel.cpp:142)",
      "kind": "correctness",
      "install": {"A1_remainder_test.cpp": "tests/attack/A1_remainder_test.cpp"},
      "run": {"default": "ctest --test-dir build -R A1_ --output-on-failure",
              "windows": "ctest --test-dir build -C Release -R A1_ --output-on-failure"},
      "timeout_s": 300
    }
  ]
}
```

- Run them all: `python tools/agent/hpcgate.py attack F-NNN`. The tool installs every attack into clean worktrees of the base and the candidate, builds both and classifies each claim:
  - `INTRODUCED`: fails on the candidate, passes on the base. The change caused a defect. **Blocking.**
  - `PRE-EXISTING`: fails on both. A real defect, but not caused here. Not blocking; record it as a new finding.
  - `REFUTED`: passes on the candidate. Your claim is not demonstrated. Strengthen the attack once if you have a concrete reason, otherwise withdraw the claim.
  - `INVALID`: doesn't build or run. Fix the attack. An invalid attack proves nothing.
  - `INTRODUCED?`: fails on the candidate, and the base can't compile the attack (the API changed). Explain by hand why it is or isn't caused by the change.
- Also run `python tools/agent/hpcgate.py tests-on-base --expect fail|pass` (fail for bug fixes, pass for refactor/perf changes) and `python tools/agent/hpcgate.py guard`.
- With ASan/UBSan/TSan available on your platform, run the attacks under them too. A sanitizer report counts as a failing attack if the command exits non-zero.

## 4. Verdict
Complete `review-K.md`:

```markdown
# Review K of F-NNN — <APPROVE | CHANGES | REJECT>
reviewer platform: <OS / arch / compiler>     candidate: <sha>     base: <sha>
attack results: .agent/work/F-NNN/attack-results-<stamp>.json

## Hypotheses
1. ... -> A1 (INTRODUCED) | A2 (REFUTED) | n/a: <reason>

## Demonstrated defects (blocking)
- A1: <claim>. Reproduce: `python tools/agent/hpcgate.py attack F-NNN --only A1`. Root cause: <file:line>. Suggested direction (not a patch): ...

## Pre-existing defects found (new findings)
- A3: ... -> proposed as F-MMM

## Unproven concerns (non-blocking)
- <concern> — why no attack was possible (e.g. needs Windows; I'm on macOS -> UNVERIFIED-windows)

## Checks
- gate: <verdict + report path>   guard: <PASS/FAIL>   tests-on-base: <result vs expected>

## Attacks worth promoting to the permanent suite
- A1: yes — covers the remainder path for all n % 8 values, runs in < 1 s
- A2: no — duplicates tests/foo_test.cpp:40
```

Verdict rules:
- **REJECT**: an `INTRODUCED` correctness defect that the approach cannot avoid, or a demonstrated performance regression that is inherent to the approach.
- **CHANGES**: at least one `INTRODUCED` (or justified `INTRODUCED?`) attack, a guard/test-on-base failure, or a missing test for a promised behaviour.
- **APPROVE**: all of these hold: no blocking attacks, gate PASS, guard PASS, tests-on-base as expected, every hypothesis attacked or marked n/a with a reason.
- Never block on an unproven concern. Never approve while an `INTRODUCED` result stands.

## You must not
- Edit source files outside `.agent/work/F-NNN/`, or commit anything except your attack files and review on the branch.
- Fix the defect yourself. You describe; the implementer fixes.
- Soften a demonstrated defect, or count a `REFUTED` attack as evidence for anything.
