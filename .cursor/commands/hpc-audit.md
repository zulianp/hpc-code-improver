# /hpc-audit — find issues (read-only)

Usage: `/hpc-audit [area]`, where area ∈ performance | portability | api | testing | regression | ci | all (default all), optionally followed by a path to restrict the scope.

You are the Auditor. **Do not modify any source file.** You only write to `.agent/findings.md`.

## Steps
1. Map the repository first and write a 15-line "Repo map" at the top of `.agent/findings.md` (if not present): languages, build system, targets, parallel models (OpenMP/MPI/threads/GPU), test frameworks, benchmark harness, CI system, public API surface, supported platforms as claimed vs as tested in CI.
2. Run what you can locally and keep the outputs as evidence:
   - `python tools/agent/hpcgate.py doctor`
   - a configure+build with warnings raised (`-Wall -Wextra -Wconversion` / `/W4`) into a scratch build dir (not the gate's build dir)
   - the test suite; `clang-tidy` (`bugprone-*`, `performance-*`, `portability-*`, `concurrency-*`) if available
   - the benchmarks once, to find hot spots worth looking at
3. Work through the checklists in the rules for the selected area: hpc-performance, portability, api-design, testing, ci-cd.
4. For each issue, add one finding. Deduplicate against existing findings.

## Finding format
Add a row to the ledger table, then a details block:

```markdown
| ID | Area | Sev | Conf | Status | Title |
|----|------|-----|------|--------|-------|
| F-012 | portability | high | CONFIRMED | open | `long` used for nnz in CSR — truncates on Windows |

### F-012 — `long` used for nnz in CSR — truncates on Windows
- **Evidence:** include/csr.hpp:88 `long nnz = ...`; Windows is LLP64 -> 32-bit. Called from solver.cpp:210 with nnz up to 6e9 in examples/large.cfg.
- **Impact:** silent wrong results on Windows for matrices with nnz > 2^31-1.
- **How to demonstrate:** test constructing CSR metadata with nnz = 2^31+5 (no full allocation needed: see csr.hpp:60 ctor).
- **Proposed direction:** use `std::int64_t` (project `index_t`) for nnz and offsets; check the I/O format.
- **Risk of fix:** ABI change of `CsrView` (public header) -> needs a deprecation note.
- **Type:** bug-fix (tests-on-base --expect fail)   |   or: refactor/perf (--expect pass)
```

Severity: `critical` (wrong results / crash in supported use), `high` (wrong on a supported platform, large perf loss on a main path, missing CI coverage hiding such issues), `medium`, `low`.
Confidence: `CONFIRMED` (reproduced or measured), `LIKELY` (strong static evidence), `SUSPECTED` (needs a test).

## Rules
- Every finding names the concrete failure or cost, with `file:line`. Style preferences aren't findings.
- Rank by severity × confidence × (1 / fix risk). Finish with the top 5 you recommend to tackle first, and why.
- If something can only be checked on another platform, say so (`UNVERIFIED-windows`).
