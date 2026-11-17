---
name: hpc-improver
description: >-
  Runs the HPC code improver in one Cursor chat: audit, then implement, gate,
  and adversarially review only the findings the user picked, stopping only
  for that choice and for approval of each finished branch. Performance
  changes are shown on a canvas with before and after gate numbers. Use when
  the user asks to audit, improve, speed up, or fix HPC code, or mentions
  findings, hpcgate, a performance regression, portability, or /hpc.
---

# HPC improver

Read `AGENTS.md` for priorities and hard rules. Procedures live in the files linked below. Do not invent a third routine checkpoint. On Windows, run the gate with `python` instead of `python3`.

The user is involved twice:

1. **Choice.** Which open findings to address.
2. **Approval.** Whether each finished branch is accepted.

Between those, do the work in this chat. Do not ask them to run a command, open a new chat, or approve a proposal. If `AskQuestion` is unavailable, ask the same question in chat and wait.

## When they have not chosen yet

If `.agent/hpcgate.json` is missing, stop and follow `.cursor/commands/hpc-setup.md`. The gate config is human-owned. Do not invent it.

Otherwise audit, unless this chat already has a current ledger for the scope they asked about. Follow [audit.md](audit.md). Write findings, then stop.

Present the open findings in chat (id, severity, confidence, one-line impact), recommended first. Then call `AskQuestion` with `allow_multiple: true`, one option per open finding, label `F-NNN · sev · CONF — title`. The prompt says they can pick several and each becomes its own branch. If there are no findings, do not ask.

If their message already names the finding ids, that is the choice. Do not ask again.

## After they choose

Take the selected ids in the order they appear in the ledger. For each one, finish it — including approval — before starting the next.

1. Read the finding, the code it names, callers, callees, build flags, and tests. Quote `path:line`.
2. Write `.agent/work/F-NNN/proposal.md` using the template in [implement.md](implement.md). Set status `proposed`. Continue. This file is the record, not a question.
3. Implement, test first, and run the gate, as in [implement.md](implement.md). Commits on `agent/F-NNN` are part of this phase. Do not merge, push, or open a PR.
4. Review. Spawn a **new** Task subagent, `subagent_type: generalPurpose`. Do not set `resume` to `self`. Do not pass your reasoning, the apply-log, or your hypotheses. The prompt tells it to read [review.md](review.md) and names only: the finding id, `.agent/findings.md`, the proposal path, `git diff <base>...HEAD`, and the latest gate report. It returns the verdict line and the review path.
5. If the verdict is `CHANGES`, address it yourself per [implement.md](implement.md), then spawn a **fresh** adversary (do not resume the previous one). At most 2 review rounds. A third, a `REJECT`, or a fix that cannot keep both invariants: set status `escalated` or recommend `wontfix`, summarise the attack ids and classifications, and stop. That is an exception, not a routine question.
6. Reach this step only when the verdict is `APPROVE` and the latest `python3 tools/agent/hpcgate.py check` is PASS. Leave the status at `applied` until the user answers.

## Approval

Stop on this finding. In chat: branch name, gate verdict line, report path, what changed, and any `UNVERIFIED-<platform>` item.

If the finding area is `performance`, or the proposal type is `perf`, read the canvas skill and [perf-canvas.md](perf-canvas.md) and write the before/after canvas **before** asking. Link it with its absolute path.

Then call `AskQuestion` with two options:

- `approve` — Accept this branch. You merge it; the agent will not.
- `reject` — Leave the branch. Do not start the next finding.

On approve, set status `ready-for-human` and start the next selected finding. On reject, set status `declined` and stop the queue.

## Do not

- Pass `--accept-guard`, `--skip-outputs`, or `--perf-advisory`.
- Pass `--skip-perf` on the gate for a change. The baseline sanity check in [implement.md](implement.md) is the only use of that flag, and it is not the verdict.
- Edit protected files (see `AGENTS.md`).
- Weaken a test, assertion, or tolerance, or add fast-math flags.
- Claim a speedup without the gate numbers on the canvas.
