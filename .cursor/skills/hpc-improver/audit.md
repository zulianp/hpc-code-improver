# Audit (read-only)

Write only to `.agent/findings.md`. Do not modify source.

Scope comes from the user: `performance | portability | api | testing | regression | ci | all` (default all), plus an optional path.

## Evidence

1. If the ledger has no repo map, write one of at most 15 lines at the top: languages, build system, targets, parallel models (OpenMP/MPI/threads/GPU), test frameworks, benchmark harness, CI, public API, platforms claimed versus platforms CI actually runs.
2. Run what this machine can run, and keep the outputs:
   - `python3 tools/agent/hpcgate.py doctor` (on Windows, `python`)
   - a configure+build with warnings (`-Wall -Wextra -Wconversion` or `/W4`) in a scratch directory, not the gate's build directory
   - the test suite; `clang-tidy` checks `bugprone-*`, `performance-*`, `portability-*`, `concurrency-*` when clang-tidy is installed
   - the benchmarks once, to see which paths are hot
3. Walk the checklists in `.cursor/rules/` for the selected area.
4. Deduplicate against existing findings.

## One finding

Add a ledger row, then a details block:

```markdown
| ID | Area | Sev | Conf | Status | Title |
|----|------|-----|------|--------|-------|
| F-012 | portability | high | CONFIRMED | open | `long` used for nnz in CSR — truncates on Windows |

### F-012 — `long` used for nnz in CSR — truncates on Windows
- **Evidence:** include/csr.hpp:88 `long nnz = ...`; Windows is LLP64, so `long` is 32-bit. Called from solver.cpp:210 with nnz up to 6e9 in examples/large.cfg.
- **Impact:** silent wrong results on Windows for matrices with nnz > 2^31-1.
- **How to demonstrate:** construct CSR metadata with nnz = 2^31+5 (no full allocation; see csr.hpp:60).
- **Proposed direction:** use `std::int64_t` (project `index_t`) for nnz and offsets; check the I/O format.
- **Risk of fix:** ABI change of `CsrView` (public header). Needs a deprecation note.
- **Type:** bug-fix (tests-on-base --expect fail)   |   or: refactor/perf (--expect pass)
```

Severity: `critical` (wrong results or a crash in supported use), `high` (wrong on a supported platform, a large loss on a main path, or missing CI that would hide either), `medium`, `low`.

Confidence: `CONFIRMED` (reproduced or measured), `LIKELY` (strong static evidence), `SUSPECTED` (needs a test).

## Rules

- Every finding names a concrete failure or cost, with `file:line`. A style preference is not a finding.
- Rank by severity × confidence × (1 / fix risk). End the ledger with the top 5 to do first, and why.
- If a check needs another platform, mark it `UNVERIFIED-<platform>`. Do not claim it.
