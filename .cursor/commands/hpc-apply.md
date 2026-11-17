# /hpc-apply — implement one proposed fix, test first, gate-verified

Usage: `/hpc-apply F-NNN`

You are the Implementer. Precondition: `.agent/work/F-NNN/proposal.md` exists and the finding's status is `proposed` (or `approved` by a human).

## Steps
1. Branch: `git switch -c agent/F-NNN origin/main` (or the configured `default_base`). The tree must be clean.
2. Baseline sanity: `python tools/agent/hpcgate.py check --skip-perf`. If the base itself fails, stop and report. Don't build on a broken base.
3. **Tests first.** Write the tests from the proposal. Commit them alone: `test(F-NNN): ...`.
   - Bug fix: `python tools/agent/hpcgate.py tests-on-base --expect fail` must succeed (the test detects the bug).
   - Refactor/perf: `python tools/agent/hpcgate.py tests-on-base --expect pass` must succeed (the tests pin current behaviour).
   - Perf without a suitable benchmark: add the benchmark in this commit too.
4. **Fix.** Implement the minimal change from the proposal. Don't touch unrelated code, formatting or protected files.
5. **Gate:** `python tools/agent/hpcgate.py check`. All stages must PASS (guard, build, test, outputs, perf).
   - On FAIL: read the report, fix the cause, re-run. A perf FAIL means the change is slower. Either find out why, or revert the optimization. Never argue noise. If you believe the threshold is wrong, run an A/A check (`check` on an unchanged tree) and report it to a human.
   - After 3 failed attempts: revert to the test commit, set status `blocked`, and write down why.
6. Commit the fix: `fix(F-NNN): ...` / `perf(F-NNN): ...` with the gate verdict and the report path in the message body.
7. Write `.agent/work/F-NNN/apply-log.md`: what changed, gate report path, perf table (median change, p), any `UNVERIFIED-<platform>` items, deviations from the proposal and why.
8. Set the status to `applied`. Then tell the user: **"Open a new chat and run `/hpc-review F-NNN`."**

## Rules
- Never use `--accept-guard`, `--skip-*`, `--perf-advisory`.
- Never modify a test written in step 3 after seeing the fix fail it. If the test was wrong, go back to step 3, explain why in the apply-log, and re-run tests-on-base.
- Keep the diff reviewable: if it grows beyond the proposal, stop and update the proposal first.
