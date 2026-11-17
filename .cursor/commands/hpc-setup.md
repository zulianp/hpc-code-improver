# /hpc-setup — onboard a repository to the HPC Code Improver (run once, with a human)

1. Run `python tools/agent/hpcgate.py doctor` and report the detected toolchain.
2. Inspect the build system, tests and benchmarks. Draft `.agent/hpcgate.json` from `.agent/hpcgate.example.json` as **`.agent/hpcgate.proposed.json`**. The real config is human-owned. Fill in:
   - `configure`/`build`/`test` for macOS and Windows (multi-config generators need `--config Release` / `-C Release`).
   - `bench`: an existing Google Benchmark binary (or a script that writes `samples-json`) that covers the main kernels. If none exists, record finding F-001 "no benchmark harness: performance cannot be gated" as top priority.
   - `outputs`: a command that runs 2-5 representative small problems and writes numeric results. If none exists, propose one as a finding.
   - `numeric.rtol/atol`: justify them in the proposal (what differs legitimately between runs).
3. Attack test registration: make sure the build compiles tests placed in `tests/attack/` when they exist (e.g. for CMake + GoogleTest, in `tests/CMakeLists.txt`):
   ```cmake
   file(GLOB ATTACK_TESTS CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/attack/*_test.cpp)
   foreach(src IN LISTS ATTACK_TESTS)
     get_filename_component(name ${src} NAME_WE)
     add_executable(${name} ${src})
     target_link_libraries(${name} PRIVATE <your_lib> GTest::gtest_main)
     add_test(NAME ${name} COMMAND ${name})
   endforeach()
   ```
   Propose this as a patch for the human. `tests/attack/` must also be in `.gitignore` so attack files only get into the suite through promotion.
4. After the human has installed `.agent/hpcgate.json`, run the **A/A noise check** on a clean tree: `python tools/agent/hpcgate.py check`. With no changes, perf must PASS. Run it 3 times. If any run reports a REGRESSION, the threshold is below this machine's noise. Recommend a larger `max_regression`, more `rounds`, or quieter conditions (AC power, no other load, Windows "High performance" power plan, macOS: no Low Power Mode).
5. Create `.agent/findings.md` with the ledger header, and add to `.gitignore`: `.agent/scratch/`, `.agent/reports/`, `tests/attack/`.
6. Stop. The improvement loop is `.cursor/skills/hpc-improver/SKILL.md` (`/hpc`). The user picks findings and approves finished branches. Do not continue into an audit unless they ask.
