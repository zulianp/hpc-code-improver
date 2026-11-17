# AGENTS.md — HPC Code Improver

This repository uses an agent workflow that finds and fixes problems in
**performance, portability, API design, testing, regression testing and CI/CD**.

Two properties are non-negotiable and outrank every other goal:

1. **Correctness never regresses.** Same results within the documented tolerance, no new undefined behaviour, no weakened tests.
2. **Performance never regresses.** No statistically significant slowdown above the threshold in `.agent/hpcgate.json`.

The gate `python tools/agent/hpcgate.py check` is how both are checked mechanically. A change that has not passed the gate is not done, however convincing the explanation is.

## Roles (each in a separate Cursor chat)

| Role | Command | Writes code? | Sees |
|---|---|---|---|
| Auditor | `/hpc-audit` | no | the repository |
| Implementer | `/hpc-propose`, `/hpc-apply`, `/hpc-address-review` | yes, on `agent/F-NNN` branches only | finding, proposal, review |
| Adversary | `/hpc-review` | only attack tests in `.agent/work/F-NNN/attack/` (then proposes them) | the diff, the finding, gate report — **not** the implementer's chat |

Run the Adversary in a **new chat** each round. Re-using the implementer's chat lets it inherit the implementer's assumptions, and the review stops being adversarial.

## Lifecycle of one finding

```
audit ──> F-NNN in .agent/findings.md (status: open)
   │
propose ──> .agent/work/F-NNN/proposal.md          (status: proposed)   ← human may veto here
   │
apply ──> branch agent/F-NNN: test first, then fix; gate PASS   (status: applied)
   │
review (new chat) ──> .agent/work/F-NNN/review-K.md  verdict: APPROVE | CHANGES | REJECT
   │        ▲
   │        └── address-review (max 2 rounds, then status: escalated → human)
   ▼
APPROVE + gate PASS ──> status: ready-for-human. A human merges. Agents never merge, push to main or tag.
```

## Hard rules for every role

- Never edit: `.agent/hpcgate.json`, `tools/agent/*`, `.cursor/rules/*`, `.cursor/commands/*`, `AGENTS.md`, `.github/workflows/*`. The gate's guard stage blocks these. If one of them is wrong, record it as a finding for a human.
- Never delete, skip, disable, or loosen a test, assertion or tolerance in order to make something pass. Never add `-ffast-math`, `-Ofast`, `/fp:fast` or similar.
- Never pass `--accept-guard`, `--skip-perf`, `--skip-outputs` or `--perf-advisory` on your own. Only a human may, and the report records it.
- One finding = one branch = one minimal diff. No drive-by refactors or formatting changes in the same diff.
- Every claim needs evidence: a `file:line`, a command output, a gate report, or a test. "Should be faster" isn't evidence.
- If you cannot verify something on this machine (e.g. a Windows-only path while on macOS), say so explicitly and mark it `UNVERIFIED-<platform>`. Do not claim it works.
- Use `python` (Windows) / `python3` (macOS) to run the tools. Never write bash-only or PowerShell-only scripts for the workflow; keep tooling in Python.

## Files

- `.agent/findings.md` — the ledger (one table row per finding, details below the table)
- `.agent/work/F-NNN/` — `proposal.md`, `apply-log.md`, `review-K.md`, `attack/`
- `.agent/reports/` — gate reports (`gate-*.md` / `.json`)
- `.agent/hpcgate.json` — gate config (human-owned)
