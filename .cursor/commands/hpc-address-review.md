# /hpc-address-review — respond to an adversarial review

Usage: `/hpc-address-review F-NNN` (in the implementer's chat, or a new one)

Inputs: the latest `.agent/work/F-NNN/review-K.md` and `attack-results-*.json`.

## Steps
1. Re-run the attacks yourself: `python tools/agent/hpcgate.py attack F-NNN`. Trust the classification, not the prose.
2. For each `INTRODUCED` attack:
   - Promote it into the real test suite first: copy it from `attack/` to the proper test location, make it follow the project's test conventions, register it in the build, commit it as `test(F-NNN): regression test from review K, attack A<n>`. It must fail on the current HEAD.
   - Fix the code. Then run `python tools/agent/hpcgate.py check` -> PASS, and `attack F-NNN` -> that attack is now `REFUTED`.
3. For `PRE-EXISTING` attacks: don't fix them here. Add each to `.agent/findings.md` as a new finding (status `open`, confidence `CONFIRMED`, evidence = the attack file). Copy the attack into `.agent/work/F-MMM/attack/` so it becomes that finding's test.
4. For attacks the reviewer marked "worth promoting" (even `REFUTED` ones, which are valid regression guards): promote them as in step 2, if they run fast and don't duplicate existing tests. Mention which ones you promoted.
5. Unproven concerns: answer each one in one or two sentences (addressed / not applicable because ... / needs platform X -> left as UNVERIFIED).
6. Append a "Response to review K" section to `apply-log.md`, set the status to `applied`, and tell the user to start a **new chat** for `/hpc-review F-NNN` (round K+1).

## Limits
- At most 2 review rounds. If round 3 would be needed, set status `escalated` and summarise the disagreement for a human. Include the attack ids and their classifications.
- REJECT verdict: don't patch around it. Go back to `/hpc-propose` with a different approach, or recommend `wontfix`.
