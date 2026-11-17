# HPC Code Improver — agent workflow for Cursor

An agent workflow that finds and fixes issues in performance, portability, API design,
testing, regression testing and CI/CD, then **attacks its own fixes**. Correctness and
performance are hard constraints: they are checked by a gate script, not left to the
model's judgement.

Model-agnostic (written for Grok 4.7 in Cursor, works with any agent model). Runs on macOS and
Windows (and Linux); all tooling is Python 3.8+ standard library.

## Install into a repository

Copy these into the repository root:

```
AGENTS.md                       roles, lifecycle, hard rules
.cursor/rules/*.mdc             always-on core rules + per-area checklists (auto-attached by glob)
.cursor/commands/*.md           /hpc-setup /hpc-audit /hpc-propose /hpc-apply /hpc-review /hpc-address-review
tools/agent/hpcgate.py          the gate (check, guard, tests-on-base, attack, doctor)
.agent/hpcgate.example.json     gate config template -> copy to .agent/hpcgate.json
.github/workflows/hpc-gate.yml  CI template (optional)
```

Then run `/hpc-setup` in Cursor once, together with a human. The setup ends with an A/A noise check.

## The loop

```
/hpc-audit ─► findings.md ─► /hpc-propose F-NNN ─► (human may veto) ─► /hpc-apply F-NNN
                                                                           │ test first, then fix,
                                                                           │ gate PASS required
                                     ┌─────────────────────────────────────┘
                                     ▼
                     NEW CHAT: /hpc-review F-NNN   (adversary)
                       hypotheses ─► runnable attack tests ─► hpcgate attack
                                     │
          APPROVE ◄──────────────────┼──────────► CHANGES / REJECT
             │                       │                  │
   ready-for-human (human merges)    │          /hpc-address-review: promote failing
                                     │          attacks into the suite, fix, re-gate
                                     └───────── (max 2 rounds, then escalate)
```

## What the gate enforces (`python tools/agent/hpcgate.py ...`)

| Subcommand | What it proves |
|---|---|
| `check` | guard → build → tests → numeric outputs vs base (rtol/atol) → **interleaved A/B benchmarks** vs base built in a separate git worktree (Mann–Whitney, fails on significant slowdown > threshold) |
| `guard` | the diff doesn't remove assertions, change tolerances, skip tests, add fast-math flags or touch protected files |
| `tests-on-base --expect fail` | a bug-fix test actually catches the bug (fails without the fix) |
| `tests-on-base --expect pass` | a refactor/perf change preserves behaviour (the new tests also pass on the old code) |
| `attack F-NNN` | runs the adversary's attack tests on base AND candidate: **INTRODUCED** (blocks) / **PRE-EXISTING** (new finding) / **REFUTED** (claim withdrawn) / **INVALID** |
| `doctor` | toolchain and resolved per-platform commands |

The base is always rebuilt next to the candidate on the same machine (in worktrees outside the
repo), so there are no stale baselines, and laptop thermal drift is cancelled by alternating run order.

## Why the review is adversarial and evidence-based

- The reviewer runs in a fresh chat and starts from the diff and the promised invariants, not from the implementer's reasoning.
- It has to enumerate hypotheses over a fixed checklist (numerics, edge sizes, memory, concurrency, portability, API, performance, tests, build).
- **A claim can only block if a runnable attack test demonstrates it**, and the attack is classified mechanically against the base. Unproven concerns are listed but never block.
- Attacks are written in the project's own test framework, so the useful ones get promoted into the permanent suite (`/hpc-address-review`); pre-existing defects turn into new findings with a ready-made test.
- Optional: run `/hpc-review` with a different model than the implementer, to reduce correlated blind spots.

## Human-only controls
`--accept-guard "<reason>"`, `--skip-perf`, `--skip-outputs`, `--perf-advisory`, edits to the gate config, rules, commands and CI, and merging. Reports record every override.

## Known limits
- Perf gating on a laptop needs AC power and an idle machine; the A/A check tells you whether your threshold is above the noise. On shared CI runners, perf is advisory.
- The guard is pattern-based. It catches the common ways tests get weakened, not every one. The reviewer's `tests-on-base` and attack steps are the second line of defence.
- Cross-platform claims made on one OS stay `UNVERIFIED-<platform>` until CI runs on that OS.
