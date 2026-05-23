"""Unit tests for drift. Run from repo root: `python3 -m unittest discover -s tests`."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import drift


def _init_repo(path: pathlib.Path) -> None:
    """Initialize a minimal git repo at path with one commit."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)
    (path / "README.md").write_text("hi")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def _init_unborn(path: pathlib.Path) -> None:
    """git init with no commit yet (unborn branch)."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True)


def _detach(path: pathlib.Path) -> None:
    """Add a second commit, then check out the first (detached HEAD)."""
    (path / "second.txt").write_text("two")
    subprocess.run(["git", "add", "second.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=path, check=True)
    subprocess.run(["git", "checkout", "-q", "HEAD~1"], cwd=path, check=True)


class TestIsRepo(unittest.TestCase):
    def test_empty_git_dir_is_not_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / ".git").mkdir()
            self.assertFalse(drift._is_repo(root))

    def test_real_repo_is_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            _init_repo(root)
            self.assertTrue(drift._is_repo(root))

    def test_no_git_anywhere(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(drift._is_repo(pathlib.Path(td)))


class TestFindRepos(unittest.TestCase):
    def test_walks_depth_and_skips_node_modules(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            # Repo at depth 1
            (root / "a").mkdir()
            _init_repo(root / "a")
            # Repo inside node_modules at depth 2 — should be skipped
            (root / "b" / "node_modules" / "c").mkdir(parents=True)
            _init_repo(root / "b" / "node_modules" / "c")
            # Repo at depth 2
            (root / "d" / "e").mkdir(parents=True)
            _init_repo(root / "d" / "e")
            found = drift.find_repos(root, max_depth=2)
            names = {p.name for p in found}
            self.assertIn("a", names)
            self.assertIn("e", names)
            self.assertNotIn("c", names)

    def test_stops_descending_into_repos(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            _init_repo(root)
            inner = root / "inner"
            inner.mkdir()
            _init_repo(inner)
            found = drift.find_repos(root, max_depth=4)
            # outer should be found; inner should NOT (descent stops at a repo)
            paths = {str(p) for p in found}
            self.assertIn(str(root), paths)
            self.assertNotIn(str(inner), paths)


class TestInspectRepo(unittest.TestCase):
    def test_basic_repo_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            _init_repo(root)
            r = drift.inspect_repo(root)
            self.assertEqual(r.branch, "master")  # git's modern default may differ; both ok
            self.assertEqual(r.dirty, 0)
            self.assertGreater(r.last_commit_ts, 0)
            self.assertEqual(r.upstream, "")

    def test_dirty_files_counted(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            _init_repo(root)
            (root / "new_file.txt").write_text("x")
            (root / "README.md").write_text("modified")
            r = drift.inspect_repo(root)
            self.assertEqual(r.dirty, 2)

    def test_unborn_repo_keeps_branch_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            _init_unborn(root)
            r = drift.inspect_repo(root)
            # branch is the real (unborn) branch name, never the literal "HEAD"
            self.assertNotEqual(r.branch, "HEAD")
            self.assertIn(r.branch, {"main", "master"})
            self.assertFalse(r.has_commits)
            self.assertFalse(r.detached)
            self.assertEqual(r.last_commit_age_days, float("inf"))

    def test_detached_head_labeled(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            _init_repo(root)
            _detach(root)
            r = drift.inspect_repo(root)
            self.assertTrue(r.detached)
            self.assertTrue(r.branch.startswith("detached@"))
            self.assertTrue(r.has_commits)

    def test_dirty_mtime_only_on_dirty_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            _init_repo(root)
            clean = drift.inspect_repo(root)
            self.assertEqual(clean.last_working_change_ts, 0.0)
            (root / "edit.txt").write_text("dirty")
            dirty = drift.inspect_repo(root)
            self.assertGreater(dirty.last_working_change_ts, 0.0)


class TestAgeStr(unittest.TestCase):
    def test_inf(self):
        self.assertIn("∞", drift._age_str(float("inf")))

    def test_days(self):
        self.assertEqual(drift._age_str(2).strip(), "2d")

    def test_months(self):
        self.assertIn("mo", drift._age_str(60))


class TestBadgeFlags(unittest.TestCase):
    def test_dirty_and_ahead(self):
        class A:
            dirty_warn = 1
            stale_days = 14
        r = drift.Repo(path=pathlib.Path("/tmp/x"), branch="m", upstream="origin/m", ahead=3, behind=0, dirty=5)
        b = drift._badge(r, A())
        self.assertIn("D5", b)
        self.assertIn("↑3", b)

    def test_no_upstream(self):
        class A:
            dirty_warn = 1
            stale_days = 14
        r = drift.Repo(path=pathlib.Path("/tmp/x"), branch="m", upstream="", ahead=0, behind=0, dirty=0)
        b = drift._badge(r, A())
        self.assertIn("no-upstream", b)

    def test_no_commits_takes_precedence_over_no_upstream(self):
        class A:
            dirty_warn = 1
            stale_days = 14
        r = drift.Repo(path=pathlib.Path("/tmp/x"), branch="main", upstream="", has_commits=False)
        b = drift._badge(r, A())
        self.assertIn("no-commits", b)
        self.assertNotIn("no-upstream", b)


class TestStalled(unittest.TestCase):
    """stalled keys off last *touch* (commit or edit), not commit age alone."""

    class _Args:
        dirty_warn = 1
        stale_days = 14

    def _repo(self, commit_age_days, touch_age_days, dirty):
        now = time.time()
        return drift.Repo(
            path=pathlib.Path("/tmp/x"),
            dirty=dirty,
            last_commit_ts=now - commit_age_days * 86400,
            last_working_change_ts=now - touch_age_days * 86400,
        )

    def test_old_commit_recent_edit_is_not_stalled(self):
        # Committed 60d ago but edited today -> active, not abandoned.
        r = self._repo(commit_age_days=60, touch_age_days=0, dirty=3)
        self.assertFalse(drift._is_stalled(r, self._Args()))
        self.assertNotIn("stalled", drift._badge(r, self._Args()))

    def test_old_commit_old_edit_is_stalled(self):
        r = self._repo(commit_age_days=60, touch_age_days=40, dirty=3)
        self.assertTrue(drift._is_stalled(r, self._Args()))
        self.assertIn("stalled", drift._badge(r, self._Args()))

    def test_clean_repo_never_stalled(self):
        r = self._repo(commit_age_days=400, touch_age_days=400, dirty=0)
        self.assertFalse(drift._is_stalled(r, self._Args()))


class TestExitCode(unittest.TestCase):
    class _Args:
        dirty_warn = 1
        stale_days = 14

    def test_clean_old_repo_exits_zero(self):
        # A finished, shipped, clean project must not fail scripts just for age.
        now = time.time()
        r = drift.Repo(path=pathlib.Path("/tmp/x"), dirty=0,
                       last_commit_ts=now - 400 * 86400)
        self.assertEqual(drift._exit_code([r], self._Args()), 0)

    def test_dirty_repo_exits_one(self):
        now = time.time()
        r = drift.Repo(path=pathlib.Path("/tmp/x"), dirty=2,
                       last_commit_ts=now - 1 * 86400,
                       last_working_change_ts=now - 1 * 86400)
        self.assertEqual(drift._exit_code([r], self._Args()), 1)

    def test_stalled_repo_exits_one(self):
        now = time.time()
        r = drift.Repo(path=pathlib.Path("/tmp/x"), dirty=1,
                       last_commit_ts=now - 60 * 86400,
                       last_working_change_ts=now - 60 * 86400)
        self.assertEqual(drift._exit_code([r], self._Args()), 1)


class TestSortKey(unittest.TestCase):
    def _repos(self):
        now = time.time()
        a = drift.Repo(path=pathlib.Path("/tmp/alpha"), dirty=0,
                       last_commit_ts=now - 1 * 86400)        # recent, clean
        b = drift.Repo(path=pathlib.Path("/tmp/zeta"), dirty=5,
                       last_commit_ts=now - 1 * 86400,
                       last_working_change_ts=now - 1 * 86400)  # dirty, recent
        c = drift.Repo(path=pathlib.Path("/tmp/mid"), dirty=1,
                       last_commit_ts=now - 90 * 86400,
                       last_working_change_ts=now - 90 * 86400)  # neglected
        return [a, b, c]

    def test_age_puts_most_neglected_first(self):
        ordered = sorted(self._repos(), key=drift._sort_key("age"))
        self.assertEqual(ordered[0].path.name, "mid")

    def test_dirty_puts_most_dirty_first(self):
        ordered = sorted(self._repos(), key=drift._sort_key("dirty"))
        self.assertEqual(ordered[0].path.name, "zeta")

    def test_name_is_alphabetical(self):
        ordered = sorted(self._repos(), key=drift._sort_key("name"))
        self.assertEqual([r.path.name for r in ordered], ["alpha", "mid", "zeta"])


class TestColor(unittest.TestCase):
    class _Args:
        dirty_warn = 1
        stale_days = 14
        color = "auto"

    def test_paint_off_returns_plain(self):
        self.assertEqual(drift._paint("x", drift._C.RED, on=False), "x")

    def test_paint_on_wraps(self):
        out = drift._paint("x", drift._C.RED, on=True)
        self.assertTrue(out.startswith(drift._C.RED))
        self.assertTrue(out.endswith(drift._C.RESET))

    def test_paint_empty_never_wrapped(self):
        self.assertEqual(drift._paint("", drift._C.RED, on=True), "")

    def test_color_always_and_never(self):
        a = self._Args(); a.color = "always"
        self.assertTrue(drift._want_color(a))
        a.color = "never"
        self.assertFalse(drift._want_color(a))

    def test_no_color_env_disables_auto(self):
        a = self._Args(); a.color = "auto"
        with unittest.mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertFalse(drift._want_color(a))

    def test_badge_plain_and_colored_agree_on_flags(self):
        a = self._Args()
        r = drift.Repo(path=pathlib.Path("/tmp/x"), dirty=3, upstream="origin/m", ahead=2)
        plain = drift._badge(r, a)
        colored = drift._badge_colored(r, a, on=True)
        for tok in ("D3", "↑2"):
            self.assertIn(tok, plain)
            self.assertIn(tok, colored)  # token text survives the color wrapping


class TestExclude(unittest.TestCase):
    def test_exclude_by_exact_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "keep").mkdir()
            _init_repo(root / "keep")
            (root / "backup-old").mkdir()
            _init_repo(root / "backup-old")
            found = drift.find_repos(root, max_depth=1)
            self.assertEqual({p.name for p in found}, {"keep", "backup-old"})
            # simulate --exclude 'backup-*'
            import fnmatch
            filtered = [r for r in found if not fnmatch.fnmatch(r.name, "backup-*")]
            self.assertEqual([p.name for p in filtered], ["keep"])

    def test_exclude_via_main_argv(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "active").mkdir()
            _init_repo(root / "active")
            (root / "archive-2024").mkdir()
            _init_repo(root / "archive-2024")
            import io
            with unittest.mock.patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                drift.main([str(root), "--max-depth", "1", "--exclude", "archive-*"])
                out = mock_out.getvalue()
            self.assertIn("active", out)
            self.assertNotIn("archive-2024", out)


if __name__ == "__main__":
    unittest.main()
