"""State directory resolution and the git-ignore guard."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
import _paths as P  # noqa: E402
from _state import State  # noqa: E402


class TestResolveStateDir(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_default_is_under_dot_claude(self):
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".claude" / "i18n")

    def test_relative_override(self):
        self.assertEqual(P.resolve_state_dir(self.root, ".i18n"), self.root / ".i18n")

    def test_absolute_override(self):
        self.assertEqual(P.resolve_state_dir(self.root, "/tmp/elsewhere"), Path("/tmp/elsewhere"))

    def test_override_wins_over_default(self):
        (self.root / ".claude" / "i18n").mkdir(parents=True)
        self.assertEqual(P.resolve_state_dir(self.root, "custom/dir"), self.root / "custom" / "dir")

    def test_rel_state_dir(self):
        d = P.resolve_state_dir(self.root)
        self.assertEqual(P.rel_state_dir(self.root, d), ".claude/i18n")

    def test_rel_state_dir_outside_root(self):
        self.assertEqual(P.rel_state_dir(self.root, Path("/tmp/x")), "/tmp/x")


class TestGitIgnoreGuard(unittest.TestCase):
    """.claude/ is gitignored wholesale in some repos; state.json must not be lost silently."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_no_warning_when_tracked(self):
        (self.root / ".gitignore").write_text(".claude/i18n/work/\n")
        d = P.resolve_state_dir(self.root)
        self.assertIsNone(P.warn_if_ignored(self.root, d))

    def test_warns_when_dot_claude_is_ignored_wholesale(self):
        (self.root / ".gitignore").write_text(".claude/\n")
        d = P.resolve_state_dir(self.root)
        msg = P.warn_if_ignored(self.root, d)
        self.assertIsNotNone(msg)
        self.assertIn("state.json is git-ignored", msg)
        self.assertIn("--state-dir", msg)

    def test_non_repo_does_not_crash(self):
        outside = Path(tempfile.mkdtemp())
        try:
            self.assertFalse(P.is_git_ignored(outside, outside / ".claude" / "i18n" / "state.json"))
        finally:
            shutil.rmtree(outside, ignore_errors=True)


class TestStateUsesGivenDir(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_save_and_reload_roundtrip(self):
        d = P.resolve_state_dir(self.root)
        s = State.load(self.root, d)
        s.record("README.md", "zh-CN", "README.zh-CN.md", "srcsha", "译文", {"c1": "块"})
        path = s.save()
        self.assertEqual(path, self.root / ".claude" / "i18n" / "state.json")
        again = State.load(self.root, d)
        self.assertEqual(again.entry("README.md", "zh-CN")["target"], "README.zh-CN.md")
        self.assertEqual(again.chunk_cache("README.md", "zh-CN"), {"c1": "块"})

    def test_two_state_dirs_are_independent(self):
        a, b = self.root / "a", self.root / "b"
        State.load(self.root, a).save()
        s = State.load(self.root, b)
        s.record("x.md", "ja", "x.ja.md", "sha", "text", {})
        s.save()
        self.assertEqual(State.load(self.root, a).data["files"], {})
        self.assertIn("x.md", State.load(self.root, b).data["files"])


if __name__ == "__main__":
    unittest.main()
