# AGENTS.md — HPC Code Improver

This repository uses an agent workflow that finds and fixes problems in
**performance, portability, API design, testing, regression testing and CI/CD**.

Two properties are non-negotiable and outrank every other goal:

1. **Correctness never regresses.** Same results within the documented tolerance, no new undefined behaviour, no weakened tests.
2. **Performance never regresses.** No statistically significant slowdown above the threshold in `.agent/hpcgate.json`.

The gate `python tools/agent/hpcgate.py check` is how both are checked mechanically. A change that has not passed the gate is not done, however convincing the explanation is.

## How a chat runs

Follow `.cursor/skills/hpc-improver/SKILL.md`. The user has two decisions:

1. **Choice.** After the audit, they pick which open findings to address.
2. **Approval.** After a finding is implemented and the review verdict is `APPROVE` with a gate PASS, they accept or reject that branch. For a performance finding, the approval view is a canvas of the gate's base and candidate medians.

They do not approve the proposal, and they do not start a second chat for review. `/hpc` is the entry point. `/hpc-setup` still runs once, with a human, because `.agent/hpcgate.json` is human-owned.

## Roles

| Role | Who | Writes code? | Sees |
|---|---|---|---|
| Auditor and implementer | this chat | yes, on `agent/F-NNN` branches only, after the user has chosen that finding | the repository, the finding, the proposal, the review |
| Adversary | a new Task subagent each round (`generalPurpose`). Never `resume: "self"` | only attack tests in `.agent/work/F-NNN/attack/` | the diff, the finding, the proposal, the gate report. Not this chat, not `apply-log.md` until its hypotheses are written |

The subagent does not receive the parent conversation. Pass it the finding id and the paths in the skill, and tell it to read `.cursor/skills/hpc-improver/review.md`.

## Lifecycle of one finding

```
audit ──> findings.md (status: open) ──> USER CHOOSES
   │
proposal (recorded, no stop) ──> branch agent/F-NNN: test first, then fix; gate PASS
   │
adversary subagent ──> review-K.md: APPROVE | CHANGES | REJECT
   │        ▲
   │        └── address the review in this chat (max 2 rounds, then status: escalated)
   ▼
APPROVE + gate PASS ──> canvas when the finding is performance
                     ──> USER APPROVES ──> status: ready-for-human
```

A human merges. Agents never merge, push to main, or tag. Commits on `agent/F-NNN` during implementation are part of the loop, because the gate requires the test commit to land before the fix.

## Hard rules for every role

- Never edit: `.agent/hpcgate.json`, `tools/agent/*`, `.cursor/rules/*`, `.cursor/commands/*`, `.cursor/skills/*`, `AGENTS.md`, `.github/workflows/*`. The gate's guard stage blocks these. If one of them is wrong, record it as a finding for a human.
- Never delete, skip, disable, or loosen a test, assertion or tolerance in order to make something pass. Never add `-ffast-math`, `-Ofast`, `/fp:fast` or similar.
- Never pass `--accept-guard`, `--skip-outputs` or `--perf-advisory`. Never pass `--skip-perf` except the baseline sanity check in `.cursor/skills/hpc-improver/implement.md`, which is not the verdict for the change. Only a human may pass the others, and the report records it.
- One finding = one branch = one minimal diff. No drive-by refactors or formatting changes in the same diff.
- Every claim needs evidence: a `file:line`, a command output, a gate report, or a test. "Should be faster" isn't evidence.
- If you cannot verify something on this machine (e.g. a Windows-only path while on macOS), say so explicitly and mark it `UNVERIFIED-<platform>`. Do not claim it works.
- Use `python` (Windows) / `python3` (macOS) to run the tools. Never write bash-only or PowerShell-only scripts for the workflow; keep tooling in Python.

## Files

- `.agent/findings.md` — the ledger (one table row per finding, details below the table)
- `.agent/work/F-NNN/` — `proposal.md`, `apply-log.md`, `review-K.md`, `attack/`
- `.agent/reports/` — gate reports (`gate-*.md` / `.json`)
- `.agent/hpcgate.json` — gate config (human-owned)
- `.cursor/skills/hpc-improver/` — the loop the agent follows (protected)
