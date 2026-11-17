#!/usr/bin/env python3
"""hpcgate: correctness + performance no-regression gate for agent-made changes.

Cross-platform (macOS, Windows, Linux). Python >= 3.8, standard library only.

Model: the *base* is a git ref (default HEAD), the *candidate* is the current
working tree. The base is checked out into a throw-away git worktree and built
there, so both sides are built with the same toolchain on the same machine at
the same time. This avoids stale baselines, which are the main source of false
"no regression" verdicts.

Gate stages (each can be skipped only by an explicit flag, and skips are
recorded in the report):
  1. build      candidate (and base, if needed)
  2. test       candidate test suite must pass
  3. outputs    candidate numeric outputs == base outputs within rtol/atol
  4. perf       interleaved A/B benchmark runs; fail on a statistically
                significant slowdown larger than max_regression

Usage:
  python tools/agent/hpcgate.py check [--base REF] [--perf-advisory]
                                      [--skip-perf] [--skip-outputs]
  python tools/agent/hpcgate.py doctor

Exit codes: 0 = pass, 1 = gate failed, 2 = configuration/usage error.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = Path(".agent/hpcgate.json")
REPORT_DIR = Path(".agent/reports")


# --------------------------------------------------------------------------- utils
class GateError(Exception):
    pass


def log(msg: str) -> None:
    print(f"[hpcgate] {msg}", flush=True)


def platform_key() -> str:
    s = sys.platform
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "darwin"
    return "linux"


def pick(cmd_spec, key: str):
    """Command specs may be a string or {"default":..., "windows":..., "darwin":...}."""
    if cmd_spec is None:
        return None
    if isinstance(cmd_spec, str):
        return cmd_spec
    return cmd_spec.get(key, cmd_spec.get("default"))


def run(cmd: str, cwd: Path, label: str, timeout: int | None = None) -> subprocess.CompletedProcess:
    log(f"{label}: {cmd}  (cwd={cwd})")
    p = subprocess.run(cmd, cwd=str(cwd), shell=True, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if p.returncode != 0:
        tail = "\n".join(p.stdout.splitlines()[-60:])
        raise GateError(f"{label} failed (exit {p.returncode}) in {cwd}:\n{tail}")
    return p


def git(args: list, cwd: Path) -> str:
    p = subprocess.run(["git"] + args, cwd=str(cwd), text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout.strip()


def resolve_base(root: Path, cfg: dict, arg) -> str:
    """Explicit --base wins. Otherwise merge-base(default_base, HEAD), so that commits on an
    agent branch are part of the candidate. Falls back to HEAD (= uncommitted changes only)."""
    if arg:
        return arg
    db = cfg.get("default_base")
    if db:
        return git(["merge-base", db, "HEAD"], root)
    return "HEAD"


def load_config(root: Path) -> dict:
    path = root / CONFIG_PATH
    if not path.exists():
        raise GateError(f"missing {CONFIG_PATH}; copy .agent/hpcgate.example.json and edit it")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    for k in ("build", "test"):
        if k not in cfg:
            raise GateError(f"config is missing required key '{k}'")
    return cfg


# --------------------------------------------------------------------------- stats
def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def mann_whitney_greater(cand: list, base: list) -> float:
    """One-sided p-value for H1: candidate samples tend to be larger (slower).

    Normal approximation with tie correction and continuity correction.
    Adequate for n >= ~5 per side; with fewer samples the gate will mostly
    refuse to call anything significant, which is the conservative direction
    for *passing* but means you should configure enough repetitions.
    """
    n1, n2 = len(cand), len(base)
    if n1 == 0 or n2 == 0:
        return 1.0
    allv = sorted([(v, 0) for v in cand] + [(v, 1) for v in base])
    ranks = [0.0] * len(allv)
    i = 0
    tie_term = 0.0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = r
        t = j - i + 1
        tie_term += t ** 3 - t
        i = j + 1
    r1 = sum(r for r, (_, g) in zip(ranks, allv) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0
    n = n1 + n2
    var = n1 * n2 / 12.0 * ((n + 1) - tie_term / (n * (n - 1))) if n > 1 else 0.0
    if var <= 0:
        return 1.0
    z = (u1 - mu - 0.5) / math.sqrt(var)
    return 1.0 - _phi(z)


# --------------------------------------------------------------------------- benchmarks
_UNIT = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}


def parse_bench(path: Path, fmt: str, metric: str) -> dict:
    """Return {benchmark_name: [samples in seconds (lower is better)]}."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out: dict = {}
    if fmt == "google-benchmark":
        for b in data.get("benchmarks", []):
            if b.get("run_type", "iteration") != "iteration":
                continue  # skip mean/median/stddev aggregates
            if b.get("error_occurred"):
                raise GateError(f"benchmark {b.get('name')} reported an error: {b.get('error_message')}")
            name = b.get("run_name", b["name"])
            scale = _UNIT.get(b.get("time_unit", "ns"), 1e-9)
            out.setdefault(name, []).append(float(b[metric]) * scale)
    elif fmt == "samples-json":
        # {"name": [t1, t2, ...]} in any consistent unit; lower is better
        for name, samples in data.items():
            out[name] = [float(x) for x in samples]
    else:
        raise GateError(f"unknown bench_format '{fmt}'")
    if not out:
        raise GateError(f"no benchmark samples found in {path}")
    return out


def run_bench_once(cfg: dict, cwd: Path, out_file: Path, key: str) -> dict:
    cmd = pick(cfg["bench"], key).replace("{out}", str(out_file.resolve()))
    if out_file.exists():
        out_file.unlink()
    run(cmd, cwd, f"bench[{cwd.name}]", timeout=cfg.get("bench_timeout_s"))
    return parse_bench(out_file, cfg.get("bench_format", "google-benchmark"),
                       cfg.get("bench_metric", "real_time"))


def perf_stage(cfg: dict, root: Path, base_dir: Path, scratch: Path, key: str) -> dict:
    perf = cfg.get("perf", {})
    rounds = int(perf.get("rounds", 5))
    max_reg = float(perf.get("max_regression", 0.03))
    alpha = float(perf.get("alpha", 0.05))
    base_s: dict = {}
    cand_s: dict = {}
    for r in range(rounds):
        # Alternate order every round so thermal/frequency drift hits both sides equally.
        order = [("base", base_dir), ("cand", root)] if r % 2 == 0 else [("cand", root), ("base", base_dir)]
        for side, cwd in order:
            res = run_bench_once(cfg, cwd, scratch / f"bench_{side}_{r}.json", key)
            tgt = base_s if side == "base" else cand_s
            for k, v in res.items():
                tgt.setdefault(k, []).extend(v)
    results = []
    failed = False
    names = sorted(set(base_s) | set(cand_s))
    for n in names:
        if n not in base_s or n not in cand_s:
            results.append({"name": n, "status": "NEW" if n not in base_s else "REMOVED"})
            if n not in cand_s:
                failed = True  # a benchmark silently disappearing is treated as a regression
            continue
        mb, mc = statistics.median(base_s[n]), statistics.median(cand_s[n])
        rel = (mc - mb) / mb if mb > 0 else 0.0
        p = mann_whitney_greater(cand_s[n], base_s[n])
        status = "OK"
        if rel > max_reg and p < alpha:
            status = "REGRESSION"
            failed = True
        elif rel < -max_reg and mann_whitney_greater(base_s[n], cand_s[n]) < alpha:
            status = "IMPROVED"
        results.append({"name": n, "status": status, "base_median": mb, "cand_median": mc,
                        "rel_change": rel, "p_slower": p,
                        "n_base": len(base_s[n]), "n_cand": len(cand_s[n])})
    return {"failed": failed, "max_regression": max_reg, "alpha": alpha,
            "rounds": rounds, "results": results}


# --------------------------------------------------------------------------- numeric outputs
_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$|^[+-]?(nan|inf|infinity)$", re.I)
_SPLIT = re.compile(r"[\s,;]+")


def _tokens(path: Path) -> list:
    with open(path, encoding="utf-8", errors="replace") as f:
        return [t for t in _SPLIT.split(f.read()) if t]


def compare_numeric(base_dir: Path, cand_dir: Path, rtol: float, atol: float) -> dict:
    files_b = {p.relative_to(base_dir).as_posix() for p in base_dir.rglob("*") if p.is_file()}
    files_c = {p.relative_to(cand_dir).as_posix() for p in cand_dir.rglob("*") if p.is_file()}
    problems = []
    for missing in sorted(files_b - files_c):
        problems.append(f"{missing}: produced by base, missing from candidate")
    for extra in sorted(files_c - files_b):
        problems.append(f"{extra}: new file in candidate (not compared)")
    worst = {"rel": 0.0, "where": None}
    for rel in sorted(files_b & files_c):
        tb, tc = _tokens(base_dir / rel), _tokens(cand_dir / rel)
        if len(tb) != len(tc):
            problems.append(f"{rel}: token count differs ({len(tb)} vs {len(tc)})")
            continue
        for i, (a, b) in enumerate(zip(tb, tc)):
            if _NUM.match(a) and _NUM.match(b):
                x, y = float(a), float(b)
                if math.isnan(x) or math.isnan(y):
                    if not (math.isnan(x) and math.isnan(y)):
                        problems.append(f"{rel}[{i}]: NaN mismatch ({a} vs {b})")
                    continue
                if math.isinf(x) or math.isinf(y):
                    if x != y:
                        problems.append(f"{rel}[{i}]: inf mismatch ({a} vs {b})")
                    continue
                d = abs(x - y)
                if d > atol + rtol * abs(x):
                    problems.append(f"{rel}[{i}]: {a} vs {b} (|diff|={d:.3e})")
                r = d / abs(x) if x != 0 else d
                if r > worst["rel"]:
                    worst = {"rel": r, "where": f"{rel}[{i}]"}
            elif a != b:
                problems.append(f"{rel}[{i}]: text differs ('{a}' vs '{b}')")
            if len(problems) > 200:
                problems.append("... truncated")
                break
    hard = [p for p in problems if "not compared" not in p]
    return {"failed": bool(hard), "rtol": rtol, "atol": atol, "files": len(files_b & files_c),
            "worst_relative_diff": worst, "problems": problems}


def outputs_stage(cfg: dict, root: Path, base_dir: Path, scratch: Path, key: str) -> dict:
    num = cfg.get("numeric", {})
    dirs = {}
    for side, cwd in (("base", base_dir), ("cand", root)):
        d = scratch / f"outputs_{side}"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        cmd = pick(cfg["outputs"], key).replace("{out_dir}", str(d.resolve()))
        run(cmd, cwd, f"outputs[{side}]", timeout=cfg.get("outputs_timeout_s"))
        dirs[side] = d
    return compare_numeric(dirs["base"], dirs["cand"],
                           float(num.get("rtol", 1e-12)), float(num.get("atol", 0.0)))


# --------------------------------------------------------------------------- worktree
def prepare_worktree(root: Path, ref: str, tag: str = "base") -> Path:
    # Outside the repo so Cursor indexing, grep and CMake globs never see a second copy of the sources.
    wt = root.parent / f".{root.name}.hpcgate-{tag}"
    sha = git(["rev-parse", "--verify", ref + "^{commit}"], root)
    if wt.exists():
        try:
            git(["-C", str(wt), "checkout", "--detach", "--force", sha], root)
            git(["-C", str(wt), "clean", "-fdq", "-e", "build*/"], root)  # keep build dir for speed
            return wt
        except GateError:
            shutil.rmtree(wt, ignore_errors=True)
            git(["worktree", "prune"], root)
    git(["worktree", "add", "--detach", str(wt), sha], root)
    sub = subprocess.run(["git", "submodule", "update", "--init", "--recursive"], cwd=str(wt))
    if sub.returncode != 0:
        log(f"warning: submodule update failed in {tag} worktree")
    return wt


def prepare_base(root: Path, ref: str) -> Path:
    return prepare_worktree(root, ref, "base")


def build(cfg: dict, cwd: Path, key: str, label: str) -> None:
    conf = pick(cfg.get("configure"), key)
    if conf:
        run(conf, cwd, f"configure[{label}]")
    run(pick(cfg["build"], key), cwd, f"build[{label}]")


# --------------------------------------------------------------------------- guard
DEFAULT_TEST_GLOBS = ["tests/*", "test/*", "*/tests/*", "*/test/*", "*_test.*", "*_tests.*",
                      "test_*.*", "*/test_*.*", "*Test.*", "*Tests.*"]
PROTECTED_PATHS = [".agent/hpcgate.json", "tools/agent/*", ".cursor/rules/*", ".cursor/commands/*",
                   "AGENTS.md", ".github/workflows/*"]
# Lines whose *removal* from a test file weakens it.
_ASSERT = re.compile(r"\b(assert\w*|EXPECT_\w+|ASSERT_\w+|REQUIRE\w*|CHECK\w*|BOOST_\w*CHECK\w*|"
                     r"TEST_ASSERT\w*|static_assert|assertAlmostEqual|allclose|isclose)\b")
_TOL = re.compile(r"\b(rtol|atol|tol|tolerance|eps|epsilon)\b\s*[=:(,]", re.I)
# Added lines: (pattern, description, blocking?)
_SUSPICIOUS_ADD = [
    (re.compile(r"-ffast-math|-Ofast|/fp:fast|-funsafe-math|-fassociative-math|-ffinite-math"), "fast-math flag", True),
    (re.compile(r"GTEST_SKIP|DISABLED_|pytest\.mark\.(skip|xfail)|@unittest\.skip|\bSKIP\(|WILL_FAIL"), "test skipped/disabled", True),
    (_TOL, "tolerance added (reviewer: is it justified by an error estimate?)", False),
    (re.compile(r"#\s*pragma\s+(GCC|clang)\s+diagnostic\s+ignored|#\s*pragma\s+warning\s*\(\s*disable"), "warning suppressed", False),
    (re.compile(r"NOLINT"), "lint suppressed", False),
]


def _is_test(path: str, globs: list) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(path, g) for g in globs)


def changed_files(root: Path, base: str) -> list:
    tracked = git(["diff", "--name-only", base], root).splitlines()
    untracked = git(["ls-files", "--others", "--exclude-standard"], root).splitlines()
    return sorted(set(f for f in tracked + untracked if f))


def guard_stage(cfg: dict, root: Path, base: str) -> dict:
    import fnmatch
    globs = cfg.get("test_globs", DEFAULT_TEST_GLOBS)
    protected = cfg.get("protected_paths", PROTECTED_PATHS)
    findings, warnings = [], []
    files = changed_files(root, base)
    for f in files:
        if any(fnmatch.fnmatch(f, g) for g in protected):
            findings.append(f"{f}: protected file modified (gate/rules/CI must only be changed by a human)")
    diff = git(["diff", "-U0", base], root)
    cur_old = cur = None
    for line in diff.splitlines():
        if line.startswith("--- "):
            cur_old = line[6:] if line.startswith("--- a/") else None
            continue
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else None
            continue
        if line.startswith("-") and cur_old:
            body = line[1:].strip()[:160]
            if _is_test(cur_old, globs) and _ASSERT.search(line):
                findings.append(f"{cur_old}: assertion removed/changed: {body}")
            elif _TOL.search(line):
                findings.append(f"{cur_old}: tolerance removed/changed: {body}")
        elif line.startswith("+") and cur:
            for rx, what, blocking in _SUSPICIOUS_ADD:
                if rx.search(line):
                    (findings if blocking else warnings).append(f"{cur}: {what}: {line[1:].strip()[:160]}")
    return {"failed": bool(findings), "changed_files": files, "findings": findings, "warnings": warnings}


def cmd_tests_on_base(args) -> int:
    """Copy the candidate's changed test files onto the base and run the tests there.

    --expect fail : bug fix. The new/changed test must FAIL on base (it reproduces the bug).
    --expect pass : refactor/perf change. Tests must PASS on base too (behaviour preserved,
                    i.e. the tests are characterization tests, not tests fitted to new behaviour).
    """
    root = Path(git(["rev-parse", "--show-toplevel"], Path.cwd()))
    cfg = load_config(root)
    args.base = resolve_base(root, cfg, args.base)
    key = platform_key()
    globs = cfg.get("test_globs", DEFAULT_TEST_GLOBS)
    tests = [f for f in changed_files(root, args.base) if _is_test(f, globs)]
    if not tests:
        log("no changed test files: a change without a test is not reviewable -> FAIL")
        return 1
    wt = prepare_base(root, args.base)
    for f in tests:
        src, dst = root / f, wt / f
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        elif dst.exists():
            dst.unlink()
        log(f"applied to base: {f}")
    outcome = "pass"
    try:
        build(cfg, wt, key, "base+tests")
        run(pick(cfg["test"], key), wt, "test[base+tests]", timeout=cfg.get("test_timeout_s"))
    except GateError as e:
        outcome = "fail"
        log(str(e)[-3000:])
    ok = outcome == args.expect
    log(f"tests on base: {outcome.upper()} (expected {args.expect.upper()}) -> {'OK' if ok else 'MISMATCH'}")
    if not ok and args.expect == "fail":
        log("the new test does not detect the bug: it passes without the fix")
    if not ok and args.expect == "pass":
        log("tests encode NEW behaviour (or do not compile on base): a 'behaviour-preserving' change is not")
    return 0 if ok else 1



# --------------------------------------------------------------------------- attacks
ATTACK_SCHEMA = """attacks.json (in .agent/work/F-NNN/attack/):
{
  "finding": "F-012",
  "attacks": [
    {
      "id": "A1",
      "claim": "row_offsets overflow int32 for nnz > 2^31 (csr.hpp:88)",
      "kind": "correctness",               # or "perf"
      "install": {"A1_overflow_test.cpp": "tests/attack/A1_overflow_test.cpp"},
      "run": {"default": "ctest --test-dir build -R A1_ --output-on-failure",
              "windows": "ctest --test-dir build -C Release -R A1_ --output-on-failure"},
      "benchmarks": ["BM_spmv_large"],     # kind=perf only: names to judge
      "timeout_s": 600
    }
  ]
}
Correctness attacks assert the CORRECT behaviour: exit 0 = defect absent, non-zero = defect present.
Perf attacks install a benchmark; the configured bench command must pick it up."""


def _install(attack: dict, src_dir: Path, wt: Path) -> None:
    for src, dst in attack.get("install", {}).items():
        s, d = src_dir / src, wt / dst
        if not s.exists():
            raise GateError(f"attack {attack['id']}: missing file {s}")
        if Path(dst).is_absolute() or ".." in Path(dst).parts:
            raise GateError(f"attack {attack['id']}: install target must be repo-relative: {dst}")
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)


def _run_quiet(cmd: str, cwd: Path, timeout) -> tuple:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), shell=True, text=True, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        return -999, f"TIMEOUT after {timeout}s\n{e.stdout or ''}"


def cmd_attack(args) -> int:
    """Run the adversary's attack tests on base AND candidate and classify each claim.

    candidate | base   | verdict
    ----------+--------+-----------------------------------------------------------
    FAIL      | PASS   | INTRODUCED  -> defect caused by this change (blocks APPROVE)
    FAIL      | FAIL   | PRE-EXISTING -> real defect, not caused here (new finding)
    PASS      | any    | REFUTED     -> claim not demonstrated (cannot block)
    build err | -      | INVALID     -> attack does not compile/run; fix the attack
    """
    root = Path(git(["rev-parse", "--show-toplevel"], Path.cwd()))
    cfg = load_config(root)
    key = platform_key()
    base = resolve_base(root, cfg, args.base)
    if git(["status", "--porcelain", "--untracked-files=no"], root):
        raise GateError("commit the candidate first: attacks run on HEAD, not on uncommitted changes")
    adir = root / ".agent" / "work" / args.finding / "attack"
    man = adir / "attacks.json"
    if not man.exists():
        raise GateError(f"missing {man}\n{ATTACK_SCHEMA}")
    with open(man, encoding="utf-8") as f:
        spec = json.load(f)
    attacks = [a for a in spec.get("attacks", []) if not args.only or a["id"] in args.only]
    if not attacks:
        raise GateError("no attacks selected")

    sides = {"cand": prepare_worktree(root, "HEAD", "cand"), "base": prepare_worktree(root, base, "base")}
    for wt in sides.values():
        for a in attacks:
            _install(a, adir, wt)
    built = {}
    for name, wt in sides.items():
        try:
            build(cfg, wt, key, f"{name}+attacks")
            built[name] = None
        except GateError as e:
            built[name] = str(e)

    results = []
    for a in attacks:
        r = {"id": a["id"], "claim": a.get("claim", ""), "kind": a.get("kind", "correctness")}
        if built["cand"] is not None:
            r.update(verdict="INVALID", detail="candidate build with attack failed:\n" + built["cand"][-2000:])
        elif r["kind"] == "perf":
            if built["base"] is not None:
                r.update(verdict="INVALID", detail="base build with attack failed:\n" + built["base"][-2000:])
            else:
                scratch = root / ".agent" / "scratch" / f"attack-{args.finding}-{a['id']}"
                scratch.mkdir(parents=True, exist_ok=True)
                pr = perf_stage(cfg, sides["cand"], sides["base"], scratch, key)
                want = set(a.get("benchmarks", []))
                rows = [x for x in pr["results"] if not want or x["name"] in want]
                if not rows:
                    r.update(verdict="INVALID", detail="none of the named benchmarks ran")
                else:
                    reg = [x for x in rows if x["status"] == "REGRESSION"]
                    r.update(verdict="INTRODUCED" if reg else "REFUTED", detail=rows)
        else:
            cmd = pick(a["run"], key)
            to = a.get("timeout_s", cfg.get("test_timeout_s"))
            rc_c, out_c = _run_quiet(cmd, sides["cand"], to)
            if rc_c == 0:
                r.update(verdict="REFUTED", detail="attack passes on candidate")
            else:
                if built["base"] is not None:
                    r.update(verdict="INTRODUCED?",
                             detail="fails on candidate; base does not build with the attack "
                                    "(API changed?) so origin is undetermined\n" + out_c[-2000:])
                else:
                    rc_b, out_b = _run_quiet(cmd, sides["base"], to)
                    r.update(verdict="PRE-EXISTING" if rc_b != 0 else "INTRODUCED",
                             detail=out_c[-2000:])
            r["command"] = cmd
        results.append(r)
        log(f"{a['id']}: {r['verdict']}  — {r['claim']}")

    out = root / ".agent" / "work" / args.finding / f"attack-results-{_dt.datetime.now():%Y%m%d-%H%M%S}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"finding": args.finding, "base": base, "head": git(["rev-parse", "HEAD"], root),
                   "host": f"{platform.system()} {platform.machine()}", "results": results}, f, indent=2)
    log(f"results: {out}")
    blocking = [r for r in results if r["verdict"] in ("INTRODUCED", "INTRODUCED?")]
    return 1 if blocking else 0


# --------------------------------------------------------------------------- report
def write_report(root: Path, report: dict) -> Path:
    d = root / REPORT_DIR
    d.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    jp = d / f"gate-{stamp}.json"
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    lines = [f"# hpcgate report {stamp}", "",
             f"- verdict: **{report['verdict']}**",
             f"- base: `{report['base_ref']}` ({report['base_sha'][:12]})",
             f"- candidate: working tree on `{report['head_sha'][:12]}` (dirty={report['dirty']})",
             f"- host: {report['host']}", ""]
    for name, st in report["stages"].items():
        lines.append(f"## {name}: {st.get('status')}")
        if name == "perf" and "results" in st:
            lines += ["", "| benchmark | status | base median | cand median | change | p(slower) |",
                      "|---|---|---|---|---|---|"]
            for r in st["results"]:
                if "rel_change" in r:
                    lines.append(f"| {r['name']} | {r['status']} | {r['base_median']:.4g} | "
                                 f"{r['cand_median']:.4g} | {100*r['rel_change']:+.2f}% | {r['p_slower']:.3f} |")
                else:
                    lines.append(f"| {r['name']} | {r['status']} | | | | |")
        if name == "guard":
            lines += [f"- BLOCK: {x}" for x in st.get("findings", [])]
            lines += [f"- warn: {x}" for x in st.get("warnings", [])]
        if name == "outputs" and "problems" in st:
            lines.append(f"\nworst relative diff: {st['worst_relative_diff']}")
            for p in st["problems"][:50]:
                lines.append(f"- {p}")
        if st.get("error"):
            lines += ["", "```", st["error"][-4000:], "```"]
        lines.append("")
    mp = jp.with_suffix(".md")
    with open(mp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return mp


# --------------------------------------------------------------------------- commands
def cmd_check(args) -> int:
    root = Path(git(["rev-parse", "--show-toplevel"], Path.cwd()))
    cfg = load_config(root)
    args.base = resolve_base(root, cfg, args.base)
    key = platform_key()
    scratch = root / ".agent" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    report = {
        "verdict": "PASS", "base_ref": args.base,
        "base_sha": git(["rev-parse", args.base], root),
        "head_sha": git(["rev-parse", "HEAD"], root),
        "dirty": bool(git(["status", "--porcelain", "--untracked-files=no"], root)),
        "host": f"{platform.system()} {platform.machine()} py{platform.python_version()}",
        "stages": {},
    }
    stages = report["stages"]

    def fail(stage: str, err: str):
        stages[stage] = {"status": "FAIL", "error": err}
        report["verdict"] = "FAIL"

    need_base = (not args.skip_perf and "bench" in cfg) or (not args.skip_outputs and "outputs" in cfg)
    base_dir = None
    g = guard_stage(cfg, root, args.base)
    if g["failed"] and args.accept_guard:
        g["status"] = f"ACCEPTED BY HUMAN: {args.accept_guard}"
    else:
        g["status"] = "FAIL" if g["failed"] else "PASS"
        if g["failed"]:
            report["verdict"] = "FAIL"
    stages["guard"] = g
    if report["verdict"] == "FAIL":
        for f in g["findings"]:
            log(f"guard: {f}")
        mp = write_report(root, report)
        log(f"report: {mp}")
        log("VERDICT: FAIL (guard)")
        return 1
    try:
        build(cfg, root, key, "candidate")
        stages["build"] = {"status": "PASS"}
    except GateError as e:
        fail("build", str(e))
    if report["verdict"] == "PASS":
        try:
            run(pick(cfg["test"], key), root, "test", timeout=cfg.get("test_timeout_s"))
            stages["test"] = {"status": "PASS"}
        except GateError as e:
            fail("test", str(e))
    if report["verdict"] == "PASS" and need_base:
        try:
            base_dir = prepare_base(root, args.base)
            build(cfg, base_dir, key, "base")
            stages["base_build"] = {"status": "PASS"}
        except GateError as e:
            fail("base_build", str(e))

    if report["verdict"] == "PASS":
        if "outputs" not in cfg:
            stages["outputs"] = {"status": "NOT CONFIGURED"}
        elif args.skip_outputs:
            stages["outputs"] = {"status": "SKIPPED (flag)"}
        else:
            try:
                res = outputs_stage(cfg, root, base_dir, scratch, key)
                res["status"] = "FAIL" if res["failed"] else "PASS"
                stages["outputs"] = res
                if res["failed"]:
                    report["verdict"] = "FAIL"
            except GateError as e:
                fail("outputs", str(e))

    if report["verdict"] == "PASS":
        if "bench" not in cfg:
            stages["perf"] = {"status": "NOT CONFIGURED"}
        elif args.skip_perf:
            stages["perf"] = {"status": "SKIPPED (flag)"}
        else:
            try:
                res = perf_stage(cfg, root, base_dir, scratch, key)
                if res["failed"] and args.perf_advisory:
                    res["status"] = "REGRESSION (advisory only)"
                else:
                    res["status"] = "FAIL" if res["failed"] else "PASS"
                    if res["failed"]:
                        report["verdict"] = "FAIL"
                stages["perf"] = res
            except GateError as e:
                fail("perf", str(e))

    mp = write_report(root, report)
    log(f"report: {mp}")
    log(f"VERDICT: {report['verdict']}")
    return 0 if report["verdict"] == "PASS" else 1


def cmd_guard(args) -> int:
    root = Path(git(["rev-parse", "--show-toplevel"], Path.cwd()))
    cfg = load_config(root)
    g = guard_stage(cfg, root, resolve_base(root, cfg, args.base))
    for f in g["findings"]:
        print(f"BLOCK {f}")
    for w in g["warnings"]:
        print(f"warn  {w}")
    print("guard:", "FAIL" if g["failed"] else "PASS", f"({len(g['changed_files'])} files changed)")
    return 1 if g["failed"] else 0


def cmd_doctor(_args) -> int:
    ok = True
    print(f"python   {sys.version.split()[0]}  ({sys.executable})")
    print(f"platform {platform_key()} / {platform.machine()}")
    for tool in ("git", "cmake", "ctest", "ninja", "clang", "clang++", "gcc", "cl", "clang-tidy", "clang-format"):
        print(f"{tool:12s} {shutil.which(tool) or '-'}")
    try:
        root = Path(git(["rev-parse", "--show-toplevel"], Path.cwd()))
        cfg = load_config(root)
        key = platform_key()
        for k in ("configure", "build", "test", "bench", "outputs"):
            print(f"cfg.{k:10s} {pick(cfg.get(k), key) or '(not configured)'}")
        if "bench" not in cfg:
            print("WARNING: no 'bench' configured -> performance cannot be gated")
        if "outputs" not in cfg:
            print("WARNING: no 'outputs' configured -> numerical results are only checked by tests")
    except GateError as e:
        print(f"ERROR: {e}")
        ok = False
    return 0 if ok else 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hpcgate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="build, test, compare outputs and benchmarks against a base ref")
    c.add_argument("--base", default=None, help="git ref to compare against (default: merge-base with cfg.default_base, else HEAD)")
    c.add_argument("--skip-perf", action="store_true", help="skip benchmarks (recorded in report)")
    c.add_argument("--skip-outputs", action="store_true", help="skip numeric output comparison")
    c.add_argument("--perf-advisory", action="store_true",
                   help="report perf regressions without failing (use on noisy shared CI runners)")
    c.add_argument("--accept-guard", metavar="REASON",
                   help="HUMAN ONLY: accept guard findings (e.g. an intended tolerance change); reason is recorded")
    c.set_defaults(func=cmd_check)
    t = sub.add_parser("tests-on-base", help="run the candidate's changed tests against the base code")
    t.add_argument("--base", default=None)
    t.add_argument("--expect", choices=["fail", "pass"], required=True,
                   help="fail = bug fix (test must catch the bug); pass = refactor/perf (behaviour preserved)")
    t.set_defaults(func=cmd_tests_on_base)
    gd = sub.add_parser("guard", help="fast static check of the diff (no build): weakened tests, fast-math, protected files")
    gd.add_argument("--base", default=None)
    gd.set_defaults(func=cmd_guard)
    at = sub.add_parser("attack", help="run the adversary's attack tests on base and candidate, classify claims")
    at.add_argument("finding", help="finding id, e.g. F-012")
    at.add_argument("--base", default=None)
    at.add_argument("--only", nargs="*", help="attack ids to run (default: all)")
    at.set_defaults(func=cmd_attack)
    d = sub.add_parser("doctor", help="show detected toolchain and resolved config")
    d.set_defaults(func=cmd_doctor)
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except GateError as e:
        log(f"ERROR: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
