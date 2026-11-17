#!/usr/bin/env python3
"""Install / update / uninstall the HPC Code Improver kit into a git repository.

Cross-platform (macOS, Windows, Linux), Python >= 3.8, standard library only.

  python3 install.py install   [--target DIR] [--ref REF] [--with-ci] [--force] [--dry-run]
  python3 install.py uninstall [--target DIR] [--purge] [--force] [--dry-run]
  python3 install.py status    [--target DIR]

Usually run as a one-liner, piped from GitHub (see README). It then downloads the
kit at --ref (default: main) as a tarball. For a private repository a token is taken
from HPC_IMPROVER_TOKEN, GH_TOKEN, GITHUB_TOKEN, or `gh auth token`, in that order.

Safety:
- Existing files the kit would overwrite (e.g. your own AGENTS.md) are backed up to
  <file>.pre-hpc-improver and restored on uninstall.
- Every installed file is recorded with its SHA-256 in .agent/.hpc-improver-manifest.json.
  Updates and uninstall only touch files that are unchanged since installation;
  locally modified kit files are left alone (reported) unless --force.
- Your data (.agent/hpcgate.json, findings.md, work/, reports/) is kept on uninstall
  unless --purge.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = os.environ.get("HPC_IMPROVER_REPO", "zulianp/hpc-code-improver")
MANIFEST = Path(".agent/.hpc-improver-manifest.json")
BACKUP_SUFFIX = ".pre-hpc-improver"
GITIGNORE_LINES = [".agent/scratch/", ".agent/reports/", "tests/attack/"]
GITIGNORE_MARK = "# hpc-code-improver (managed: removed by uninstall)"

# Files that belong to the kit (relative to the kit root). Directories are expanded.
KIT_ITEMS = ["AGENTS.md", ".cursor/rules", ".cursor/commands", ".cursor/skills",
             "tools/agent/hpcgate.py", ".agent/hpcgate.example.json"]
CI_ITEMS = [".github/workflows/hpc-gate.yml"]
SELF_DEST = "tools/agent/hpc-improver-install.py"  # copy of this script, for offline uninstall/update
# Created by using the kit; removed only with --purge.
USER_DATA = [".agent/hpcgate.json", ".agent/hpcgate.proposed.json", ".agent/findings.md",
             ".agent/work", ".agent/reports", ".agent/scratch"]


def say(msg: str) -> None:
    print(f"[hpc-improver] {msg}", flush=True)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def git_root(start: Path) -> Path:
    p = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(start),
                       text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        sys.exit(f"[hpc-improver] {start} is not inside a git repository (run `git init` first or pass --target)")
    return Path(p.stdout.strip())


# --------------------------------------------------------------------------- fetch kit
def _token():
    for var in ("HPC_IMPROVER_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    if shutil.which("gh"):
        p = subprocess.run(["gh", "auth", "token"], text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    return None


def _safe_extract(tf: tarfile.TarFile, dest: Path) -> None:
    dest = dest.resolve()
    for m in tf.getmembers():
        target = (dest / m.name).resolve()
        if not str(target).startswith(str(dest) + os.sep) and target != dest:
            raise SystemExit(f"[hpc-improver] refusing unsafe path in archive: {m.name}")
        if m.issym() or m.islnk():
            raise SystemExit(f"[hpc-improver] refusing link in archive: {m.name}")
    if sys.version_info >= (3, 12):
        tf.extractall(dest, filter="data")
    else:
        tf.extractall(dest)


def _extract_tarball(data: bytes, tmp: Path) -> Path:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        _safe_extract(tf, tmp)
    tops = [p for p in tmp.iterdir() if p.is_dir()]
    if len(tops) != 1 or not (tops[0] / "tools/agent/hpcgate.py").exists():
        raise SystemExit("[hpc-improver] downloaded archive does not look like the kit")
    return tops[0]


def fetch_kit(args, tmp: Path) -> tuple:
    """Return (kit_root, description)."""
    if args.source:
        src = Path(args.source).expanduser().resolve()
        if src.is_file():  # local tarball
            return _extract_tarball(src.read_bytes(), tmp), f"archive {src}"
        if not (src / "tools/agent/hpcgate.py").exists():
            sys.exit(f"[hpc-improver] {src} is not a kit checkout")
        return src, f"local {src}"
    here = Path(__file__).resolve().parent if "__file__" in globals() and Path(__file__).exists() else None
    if here and (here / "tools/agent/hpcgate.py").exists() and not args.ref_given:
        return here, f"local {here}"
    url = f"https://api.github.com/repos/{REPO}/tarball/{args.ref}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "hpc-improver-installer"})
    tok = _token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    say(f"downloading {REPO}@{args.ref}{' (authenticated)' if tok else ''}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        hint = (" - the repository is private: set GH_TOKEN/GITHUB_TOKEN or log in with `gh auth login`"
                if e.code in (401, 403, 404) and not tok else "")
        sys.exit(f"[hpc-improver] download failed: HTTP {e.code}{hint}")
    except urllib.error.URLError as e:
        sys.exit(f"[hpc-improver] download failed: {e.reason}")
    root = _extract_tarball(data, tmp)
    return root, f"{REPO}@{args.ref} ({root.name.rsplit('-', 1)[-1]})"


def kit_files(kit: Path, with_ci: bool) -> list:
    out = []
    for item in KIT_ITEMS + (CI_ITEMS if with_ci else []):
        p = kit / item
        if p.is_dir():
            out += sorted(q.relative_to(kit).as_posix() for q in p.rglob("*") if q.is_file())
        elif p.is_file():
            out.append(item)
        else:
            say(f"warning: kit item missing: {item}")
    return out


# --------------------------------------------------------------------------- manifest
def load_manifest(root: Path) -> dict:
    p = root / MANIFEST
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"files": {}, "backups": {}, "created_dirs": [], "gitignore": False}


def save_manifest(root: Path, m: dict, dry: bool) -> None:
    if dry:
        return
    p = root / MANIFEST
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2, sort_keys=True)
        f.write("\n")


# --------------------------------------------------------------------------- gitignore
def gitignore_add(root: Path, dry: bool) -> bool:
    gi = root / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if GITIGNORE_MARK in text:
        return True
    block = "\n".join([GITIGNORE_MARK] + GITIGNORE_LINES + [GITIGNORE_MARK]) + "\n"
    if not dry:
        sep = "" if text == "" or text.endswith("\n") else "\n"
        with open(gi, "w", encoding="utf-8", newline="") as f:
            f.write(text + sep + block)
    say("updated .gitignore")
    return True


def gitignore_remove(root: Path, dry: bool) -> None:
    gi = root / ".gitignore"
    if not gi.exists():
        return
    lines = gi.read_text(encoding="utf-8").splitlines(keepends=True)
    out, inside = [], False
    for ln in lines:
        if ln.strip() == GITIGNORE_MARK:
            inside = not inside
            continue
        if not inside:
            out.append(ln)
    new = "".join(out)
    if dry:
        return
    if new.strip():
        with open(gi, "w", encoding="utf-8", newline="") as f:
            f.write(new)
    else:
        gi.unlink()
    say("cleaned .gitignore")


# --------------------------------------------------------------------------- commands
def cmd_install(args) -> int:
    root = git_root(Path(args.target))
    m = load_manifest(root)
    action = "updating" if m["files"] else "installing"
    with tempfile.TemporaryDirectory() as td:
        kit, desc = fetch_kit(args, Path(td))
        say(f"{action} kit from {desc} into {root}")
        plan = [(rel, kit / rel) for rel in kit_files(kit, args.with_ci or m.get("with_ci", False))]
        self_src = kit / "install.py"
        if self_src.exists():
            plan.append((SELF_DEST, self_src))
        skipped = 0
        new_files = {}
        for rel, src in plan:
            dst = root / rel
            new_hash = sha256(src)
            if dst.exists():
                cur = sha256(dst)
                if cur == new_hash:
                    new_files[rel] = new_hash
                    continue
                if rel in m["files"]:
                    if cur != m["files"][rel] and not args.force:
                        say(f"keep   {rel}  (modified locally; --force to overwrite)")
                        new_files[rel] = m["files"][rel]
                        skipped += 1
                        continue
                else:  # a file of the user's that the kit would replace
                    bak = rel + BACKUP_SUFFIX
                    if not args.dry_run:
                        shutil.copy2(dst, root / bak)
                    m["backups"][rel] = bak
                    say(f"backup {rel} -> {bak}")
            else:
                for parent in reversed(Path(rel).parents):
                    if str(parent) != "." and not (root / parent).exists():
                        m["created_dirs"].append(parent.as_posix())
                        if not args.dry_run:
                            (root / parent).mkdir()
            if not args.dry_run:
                shutil.copy2(src, dst)
            new_files[rel] = new_hash
            say(f"write  {rel}")
        # Files of an older kit version that are no longer shipped: remove if unmodified.
        for rel, h in m["files"].items():
            if rel not in new_files:
                p = root / rel
                if p.exists() and sha256(p) == h and not args.dry_run:
                    p.unlink()
                    say(f"remove {rel}  (no longer part of the kit)")
        m["files"] = new_files
        m["source"] = desc
        m["with_ci"] = bool(args.with_ci or m.get("with_ci", False))
        m["gitignore"] = gitignore_add(root, args.dry_run)
        m["created_dirs"] = sorted(set(m["created_dirs"]))
        save_manifest(root, m, args.dry_run)
    say(("dry run: nothing written. " if args.dry_run else "") + f"done ({len(new_files)} kit files, {skipped} kept)")
    if not (root / ".agent/hpcgate.json").exists():
        say("next: open the repo in Cursor and run /hpc-setup (creates .agent/hpcgate.json with you)")
    return 0


def cmd_uninstall(args) -> int:
    root = git_root(Path(args.target))
    m = load_manifest(root)
    if not m["files"]:
        say("no installation found (missing .agent/.hpc-improver-manifest.json)")
        return 1
    kept = []
    for rel, h in sorted(m["files"].items()):
        p = root / rel
        if not p.exists():
            continue
        if sha256(p) != h and not args.force:
            kept.append(rel)
            say(f"keep   {rel}  (modified locally; --force to remove)")
            continue
        if not args.dry_run:
            p.unlink()
        say(f"remove {rel}")
    for rel, bak in m["backups"].items():
        b = root / bak
        if b.exists() and not (root / rel).exists():
            if not args.dry_run:
                shutil.move(str(b), str(root / rel))
            say(f"restore {rel}")
    if m.get("gitignore"):
        gitignore_remove(root, args.dry_run)
    if args.purge:
        for rel in USER_DATA:
            p = root / rel
            if p.is_dir() and not args.dry_run:
                shutil.rmtree(p)
            elif p.is_file() and not args.dry_run:
                p.unlink()
            if p.exists() or args.dry_run:
                say(f"purge  {rel}")
        for tag in ("base", "cand"):
            wt = root.parent / f".{root.name}.hpcgate-{tag}"
            if wt.exists():
                if not args.dry_run:
                    subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=str(root))
                say(f"purge  worktree {wt}")
    if not args.dry_run:
        if not kept:
            (root / MANIFEST).unlink(missing_ok=True)
        else:
            m["files"] = {k: v for k, v in m["files"].items() if k in kept}
            save_manifest(root, m, False)
        # remove now-empty directories the installer created (deepest first), then .agent if empty
        for d in sorted(m["created_dirs"] + [".agent"], key=lambda s: -s.count("/")):
            p = root / d
            try:
                if p.is_dir() and not any(p.iterdir()):
                    p.rmdir()
            except OSError:
                pass
    left = [r for r in USER_DATA if (root / r).exists()]
    if left and not args.purge:
        say("kept your data: " + ", ".join(left) + "  (use --purge to remove)")
    say("dry run: nothing removed" if args.dry_run else "uninstalled")
    return 0


def cmd_status(args) -> int:
    root = git_root(Path(args.target))
    m = load_manifest(root)
    if not m["files"]:
        say(f"not installed in {root}")
        return 1
    mod = [r for r, h in m["files"].items() if (root / r).exists() and sha256(root / r) != h]
    miss = [r for r in m["files"] if not (root / r).exists()]
    say(f"installed in {root} from {m.get('source')}: {len(m['files'])} files, "
        f"{len(mod)} modified, {len(miss)} missing")
    for r in mod:
        say(f"  modified: {r}")
    for r in miss:
        say(f"  missing:  {r}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="install.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="install", choices=["install", "uninstall", "status"])
    ap.add_argument("--target", default=".", help="directory inside the target git repo (default: current)")
    ap.add_argument("--ref", default=None, help="kit branch/tag/commit to install (default: main)")
    ap.add_argument("--source", help="install from a local kit checkout or .tar.gz instead of GitHub")
    ap.add_argument("--with-ci", action="store_true", help="also install .github/workflows/hpc-gate.yml")
    ap.add_argument("--force", action="store_true", help="overwrite/remove kit files even if modified locally")
    ap.add_argument("--purge", action="store_true", help="uninstall: also remove .agent data and gate worktrees")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    args = ap.parse_args(argv)
    args.ref_given = args.ref is not None
    args.ref = args.ref or "main"
    return {"install": cmd_install, "uninstall": cmd_uninstall, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
