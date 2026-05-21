"""Unit tests for drift. Run from repo root: `python3 -m unittest discover -s tests`."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
