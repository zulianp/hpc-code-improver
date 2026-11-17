# HPC Code Improver — agent workflow for Cursor

An agent workflow that finds and fixes issues in performance, portability, API design,
testing, regression testing and CI/CD, then **attacks its own fixes**. Correctness and
performance are hard constraints: they are checked by a gate script, not left to the
model's judgement.

Model-agnostic (written for Grok 4.7 in Cursor, works with any agent model). Runs on macOS and
Windows (and Linux); all tooling is Python 3.8+ standard library.

## Install

Run this from inside the repository you want to improve. You need git and Python 3.8+.

**macOS / Linux**
```sh
curl -fsSL https://raw.githubusercontent.com/zulianp/hpc-code-improver/main/install.py | python3 - install
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/zulianp/hpc-code-improver/main/install.py -OutFile $env:TEMP\hpci.py; python $env:TEMP\hpci.py install
```

**While this repository is private**, authenticate through the GitHub CLI (`gh auth login` once). The installer picks up the same token for the download.
```sh
# macOS / Linux
curl -fsSL -H "Authorization: Bearer $(gh auth token)" -H "Accept: application/vnd.github.raw" \
  https://api.github.com/repos/zulianp/hpc-code-improver/contents/install.py | python3 - install
```
```powershell
# Windows (PowerShell)
irm -Headers @{Authorization="Bearer $(gh auth token)"; Accept="application/vnd.github.raw"} https://api.github.com/repos/zulianp/hpc-code-improver/contents/install.py -OutFile $env:TEMP\hpci.py; python $env:TEMP\hpci.py install
```
Instead of `gh`, you can set `GH_TOKEN` (or `GITHUB_TOKEN`) to a token with read access to the repo.

Then open the repository in Cursor and run `/hpc-setup` once, together with a human. It creates `.agent/hpcgate.json` and ends with an A/A noise check.

After that, `/hpc` (or asking the agent to improve the code) follows the `hpc-improver` skill. You pick which findings to address, and you approve or reject each finished branch. The agent does the proposal, the fix, the gate, and the adversarial review without stopping. A performance change is shown on a canvas, base against candidate, from the gate report.

### Update, status, uninstall

Running the install command again updates the kit. For the other actions, run the same one-liner with `uninstall` or `status` in place of `install`, or use the copy the installer leaves in your repo:

```sh
python3 tools/agent/hpc-improver-install.py status       # what is installed, what was modified
python3 tools/agent/hpc-improver-install.py install      # update to the latest main
python3 tools/agent/hpc-improver-install.py uninstall    # remove the kit, keep your .agent data
python3 tools/agent/hpc-improver-install.py uninstall --purge   # also remove .agent data and gate worktrees
```
On Windows, use `python` in place of `python3`.

| Option | Effect |
|---|---|
| `--ref v1.0` | install a specific branch, tag or commit (default `main`) |
| `--with-ci` | also install `.github/workflows/hpc-gate.yml` |
| `--target DIR` | install into the git repo containing `DIR` (default: current directory) |
| `--dry-run` | show what would change, write nothing |
| `--force` | overwrite (install) or remove (uninstall) kit files you modified locally |
| `--purge` | uninstall: also delete `.agent/hpcgate.json`, findings, work, reports and the gate's worktrees |
| `--source PATH` | install from a local kit checkout or `.tar.gz` (offline) |

How the installer stays safe:
- It records every file it installs, with a checksum, in `.agent/.hpc-improver-manifest.json`. Updates and uninstall only touch files that are unchanged since installation; files you edited are reported and left alone unless you pass `--force`.
- If your repo already has a file the kit ships (typically your own `AGENTS.md`), the installer saves it as `<file>.pre-hpc-improver` and restores it on uninstall. To keep your own content, merge it into the kit's `AGENTS.md` by hand.
- It adds a marked block to `.gitignore` (`.agent/scratch/`, `.agent/reports/`, `tests/attack/`) and removes exactly that block on uninstall.
- Uninstall keeps your data (gate config, findings, reviews, attack tests) unless you pass `--purge`.

### What gets installed

```
AGENTS.md                            roles, lifecycle, hard rules
.cursor/rules/*.mdc                  always-on core rules + per-area checklists (auto-attached by glob)
.cursor/commands/*.md                /hpc-setup (once) and /hpc
.cursor/skills/hpc-improver/         the loop: audit, implement, isolated review, perf canvas
tools/agent/hpcgate.py               the gate (check, guard, tests-on-base, attack, doctor)
tools/agent/hpc-improver-install.py  copy of the installer (offline update/uninstall)
.agent/hpcgate.example.json          gate config template -> /hpc-setup turns it into .agent/hpcgate.json
.github/workflows/hpc-gate.yml       CI template (only with --with-ci)
```

## The loop

```
/hpc ─► audit ─► findings.md ─► YOU CHOOSE which findings
                                  │
                                  ▼  (no further questions)
                    proposal recorded ─► test first, then fix, gate PASS
                                  │
                                  ▼
                    adversary subagent (does not see this chat)
                      hypotheses ─► runnable attack tests ─► hpcgate attack
                                  │
          APPROVE + gate PASS ────┼──────────► CHANGES / REJECT
                 │                │                  │
                 ▼                │          same chat: promote failing attacks,
          perf: canvas,           │          fix, re-gate, fresh adversary
          YOU APPROVE the branch  └───────── (max 2 rounds, then escalate)
                 │
          ready-for-human (you merge)
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

- The reviewer is a new subagent. It does not receive this chat, and it starts from the diff and the promised invariants, not from the implementer's reasoning.
- It has to enumerate hypotheses over a fixed checklist (numerics, edge sizes, memory, concurrency, portability, API, performance, tests, build).
- **A claim can only block if a runnable attack test demonstrates it**, and the attack is classified mechanically against the base. Unproven concerns are listed but never block.
- Attacks are written in the project's own test framework, so the useful ones get promoted into the permanent suite in the same chat; pre-existing defects turn into new findings with a ready-made test.
- Optional: start the adversary subagent on a different model than the implementer, to reduce correlated blind spots.

## Human-only controls
`--accept-guard "<reason>"`, `--skip-perf`, `--skip-outputs`, `--perf-advisory`, edits to the gate config, rules, commands, the improver skill, and CI, and merging. Reports record every override.

## Known limits
- Perf gating on a laptop needs AC power and an idle machine; the A/A check tells you whether your threshold is above the noise. On shared CI runners, perf is advisory.
- The guard is pattern-based. It catches the common ways tests get weakened, not every one. The reviewer's `tests-on-base` and attack steps are the second line of defence.
- Cross-platform claims made on one OS stay `UNVERIFIED-<platform>` until CI runs on that OS.
