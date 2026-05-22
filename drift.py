#!/usr/bin/env python3
"""drift — surface git workspace decay across many projects.

For each git repo under one or more root directories, report: branch,
ahead/behind vs upstream, dirty file count, last commit age, and days-since
any working-tree file was touched. Designed to answer 'what have I been
ignoring?' in one screen.

Stdlib only. No mutation. Reads `git` via subprocess.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict


__version__ = "0.3"

DEFAULT_ROOTS = [pathlib.Path.home()]


def _run(cmd: list[str], cwd: pathlib.Path) -> str:
    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        return r.stdout
    except (subprocess.SubprocessError, OSError):
        return ""


@dataclass
class Repo:
    path: pathlib.Path
    branch: str = ""
    upstream: str = ""
    ahead: int = 0
    behind: int = 0
    dirty: int = 0
    last_commit_ts: float = 0.0
    last_working_change_ts: float = 0.0
    has_commits: bool = True
    detached: bool = False
    error: str = ""

    @property
    def last_commit_age_days(self) -> float:
        if self.last_commit_ts <= 0:
            return float("inf")
        return (time.time() - self.last_commit_ts) / 86400

    @property
    def last_touch_age_days(self) -> float:
        ts = max(self.last_working_change_ts, self.last_commit_ts)
        if ts <= 0:
            return float("inf")
        return (time.time() - ts) / 86400


def _is_repo(p: pathlib.Path) -> bool:
    git = p / ".git"
    if git.is_file():
        # Worktree pointer file
        return True
    if git.is_dir():
        # Real repo dirs have HEAD; empty/stray .git dirs do not.
        return (git / "HEAD").exists()
    return False


def find_repos(root: pathlib.Path, max_depth: int = 3) -> list[pathlib.Path]:
    """Return git repos under root up to max_depth (depth 0 = root itself)."""
    found: list[pathlib.Path] = []
    if not root.exists():
        return found

    def walk(p: pathlib.Path, depth: int) -> None:
        if _is_repo(p):
            found.append(p)
            return  # don't recurse into a repo's subdirs
        if depth >= max_depth:
            return
        try:
            for child in p.iterdir():
                if not child.is_dir():
                    continue
                if child.name.startswith("."):
                    continue
                if child.name in {"node_modules", "venv", ".venv", "__pycache__", "target"}:
                    continue
                walk(child, depth + 1)
        except (PermissionError, OSError):
            return

    walk(root, 0)
    return found


def inspect_repo(path: pathlib.Path) -> Repo:
    repo = Repo(path=path)
    # Branch. symbolic-ref disambiguates the three states that
    # `rev-parse --abbrev-ref HEAD` collapses into the literal "HEAD":
    #   - on a branch (even unborn): returns the branch name
    #   - detached: fails, so we fall back to the short sha
    branch = _run(["git", "symbolic-ref", "--short", "HEAD"], path).strip()
    if branch:
        repo.branch = branch
    else:
        sha = _run(["git", "rev-parse", "--short", "HEAD"], path).strip()
        repo.detached = True
        repo.branch = f"detached@{sha}" if sha else "?"

    upstream = _run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], path
    ).strip()
    repo.upstream = upstream

    if upstream:
        counts = _run(
            ["git", "rev-list", "--left-right", "--count", f"HEAD...{upstream}"], path
        ).strip()
        try:
            ahead, behind = counts.split()
            repo.ahead = int(ahead)
            repo.behind = int(behind)
        except ValueError:
            pass

    # Dirty file count (porcelain v1 = one line per change)
    porcelain = _run(["git", "status", "--porcelain"], path)
    repo.dirty = sum(1 for line in porcelain.splitlines() if line.strip())

    # Last commit timestamp. Empty output => unborn branch (no commits yet).
    last = _run(["git", "log", "-1", "--format=%ct"], path).strip()
    if last.isdigit():
        repo.last_commit_ts = float(last)
        repo.has_commits = True
    else:
        repo.has_commits = False

    # Last working-tree touch: newest mtime among files git considers dirty
    # (modified-tracked + untracked-not-ignored). This is the "I edited but
    # didn't commit" signal — and it's cheap because we only stat dirty files,
    # not the whole tree.
    repo.last_working_change_ts = _latest_dirty_mtime(path)

    return repo


def _latest_dirty_mtime(repo_root: pathlib.Path) -> float:
    """Newest mtime among modified-tracked and untracked-not-ignored files."""
    out = _run(
        ["git", "ls-files", "-m", "-o", "--exclude-standard", "-z"], repo_root
    )
    newest = 0.0
    for rel in out.split("\0"):
        if not rel:
            continue
        try:
            m = (repo_root / rel).stat().st_mtime
            if m > newest:
                newest = m
        except OSError:
            continue
    return newest


# ----- formatting ------------------------------------------------------------


def _age_str(days: float) -> str:
    if days == float("inf"):
        return "  ∞"
    if days < 1:
        return "  <1d"
    if days < 30:
        return f"{int(days):3d}d"
    if days < 365:
        return f"{int(days/30):3d}mo"
    return f"{days/365:.1f}y"


class _C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


def _paint(text: str, code: str, on: bool) -> str:
    return f"{code}{text}{_C.RESET}" if on and text else text


def _want_color(args: argparse.Namespace) -> bool:
    if args.color == "always":
        return True
    if args.color == "never":
        return False
    # auto: honor the NO_COLOR convention, otherwise color only a real TTY
    if os.environ.get("NO_COLOR") is not None:
        return False
    return sys.stdout.isatty()


def _flag_tokens(repo: Repo, args: argparse.Namespace) -> list[tuple[str, str]]:
    """(text, color) for each flag. Single source of truth for plain + colored."""
    toks: list[tuple[str, str]] = []
    if repo.dirty >= args.dirty_warn:
        toks.append((f"D{repo.dirty}", _C.YELLOW))
    if repo.ahead > 0:
        toks.append((f"↑{repo.ahead}", _C.CYAN))
    if repo.behind > 0:
        toks.append((f"↓{repo.behind}", _C.CYAN))
    if not repo.has_commits:
        toks.append(("no-commits", _C.MAGENTA))
    elif not repo.upstream:
        toks.append(("no-upstream", _C.DIM))
    # "stalled" = dirty work that hasn't been *touched* (committed or edited)
    # in a while. Using last-touch rather than last-commit means a repo with
    # old commits but recent edits is correctly seen as active, not abandoned.
    if _is_stalled(repo, args):
        toks.append(("stalled", _C.BOLD + _C.RED))
    return toks


def _badge(repo: Repo, args: argparse.Namespace) -> str:
    return " ".join(text for text, _ in _flag_tokens(repo, args))


def _badge_colored(repo: Repo, args: argparse.Namespace, on: bool) -> str:
    return " ".join(_paint(text, code, on) for text, code in _flag_tokens(repo, args))


def report(repos: list[Repo], args: argparse.Namespace) -> int:
    repos = sorted(repos, key=_sort_key(args.sort))

    if args.json:
        out = []
        for r in repos:
            d = asdict(r)
            d["path"] = str(r.path)
            d["last_commit_age_days"] = round(r.last_commit_age_days, 2)
            d["last_touch_age_days"] = round(r.last_touch_age_days, 2)
            out.append(d)
        json.dump({"repos": out}, sys.stdout, indent=2, default=str)
        print()
        return _exit_code(repos, args)

    on = _want_color(args)

    print(f"drift · {len(repos)} repos")
    print()
    header = f"  {'repo':<30} {'branch':<22} {'dirty':>5} {'ahead/behind':>14} {'last commit':>12}  flags"
    sep = f"  {'-'*30} {'-'*22} {'-'*5} {'-'*14} {'-'*12}  {'-'*16}"
    print(_paint(header, _C.BOLD, on))
    print(_paint(sep, _C.DIM, on))
    for r in repos:
        tokens = _flag_tokens(r, args)
        if args.only_flagged and not tokens:
            continue
        name = r.path.name[:30]
        branch = (r.branch or "?")[:22]
        ahead_behind = f"{r.ahead}/{r.behind}" if r.upstream else "—"
        line = (
            f"  {name:<30} {branch:<22} {r.dirty:>5} {ahead_behind:>14} "
            f"{_age_str(r.last_commit_age_days):>12}  {_badge_colored(r, args, on)}"
        )
        # Clean, current repos recede so the ones needing attention pop.
        if on and not tokens:
            line = _paint(line, _C.DIM, on)
        print(line)

    print()
    return _exit_code(repos, args)


def _sort_key(mode: str):
    """Row ordering. 'signal' = most actionable first; 'age' = most neglected first."""
    if mode == "age":
        return lambda r: -r.last_touch_age_days
    if mode == "dirty":
        return lambda r: (-r.dirty, -r.last_touch_age_days)
    if mode == "name":
        return lambda r: r.path.name.lower()
    # signal (default): dirty, then divergence, then oldest commit
    return lambda r: (-r.dirty, -(r.ahead + r.behind), -r.last_commit_age_days)


def _is_stalled(repo: Repo, args: argparse.Namespace) -> bool:
    return repo.last_touch_age_days >= args.stale_days and repo.dirty > 0


def _exit_code(repos: list[Repo], args: argparse.Namespace) -> int:
    # Non-zero only when something actually needs attention: dirty work above
    # the threshold, or stalled work. A clean repo that's merely old (a
    # finished, shipped project) is not a problem and must not fail scripts.
    for r in repos:
        if r.dirty >= args.dirty_warn or _is_stalled(r, args):
            return 1
    return 0


# ----- entry point -----------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="drift",
        description="Surface git workspace decay across many projects.",
    )
    p.add_argument("--version", action="version", version=f"drift {__version__}")
    p.add_argument(
        "roots",
        nargs="*",
        default=[str(pathlib.Path.home())],
        help="Root dirs to scan (default: $HOME). Each is walked up to --max-depth.",
    )
    p.add_argument("--max-depth", type=int, default=2)
    p.add_argument("--dirty-warn", type=int, default=1, help="Dirty file count that earns a D-flag (default 1).")
    p.add_argument("--stale-days", type=float, default=14.0, help="Days-since-last-touch (commit or edit) threshold for 'stalled' flag (default 14).")
    p.add_argument("--only-flagged", action="store_true", help="Hide repos with no flags (clean and current).")
    p.add_argument(
        "--sort",
        choices=["signal", "age", "dirty", "name"],
        default="signal",
        help="Row order: signal (default, most actionable), age (most neglected first), dirty, name.",
    )
    p.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="Colorize output (default auto: on for a TTY unless NO_COLOR is set).",
    )
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repos: list[pathlib.Path] = []
    for root in args.roots:
        repos.extend(find_repos(pathlib.Path(root).expanduser(), max_depth=args.max_depth))

    # Dedup; preserve order
    seen: set[pathlib.Path] = set()
    deduped: list[pathlib.Path] = []
    for r in repos:
        rp = r.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        deduped.append(r)

    inspected = [inspect_repo(r) for r in deduped]
    return report(inspected, args)


if __name__ == "__main__":
    sys.exit(main())
