"""State directory resolution and the git-ignore guard."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
import _paths as P  # noqa: E402
from _state import State  # noqa: E402

#: Everything resolve_state_dir consults. Cleared per-test, or the answers would depend on
#: which harness happens to be running the suite.
_HARNESS_ENV = ("I18N_STATE_DIR", "I18N_HARNESS", "CLAUDECODE", "CODEX_HOME")


class HarnessEnvCase(unittest.TestCase):
    """Base: a temp root and a neutral environment."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in _HARNESS_ENV:
            os.environ.pop(name, None)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def seed(self, rel, marker="state.json"):
        d = self.root / rel
        d.mkdir(parents=True, exist_ok=True)
        (d / marker).write_text("{}")
        return d


class TestResolveStateDir(HarnessEnvCase):
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


class TestHarnessDetection(HarnessEnvCase):
    """A fresh repo goes under the directory the running harness already owns."""

    def test_claude_code_env(self):
        os.environ["CLAUDECODE"] = "1"
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".claude" / "i18n")

    def test_codex_env(self):
        os.environ["CODEX_HOME"] = "/home/somebody/.codex"
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".codex" / "i18n")

    def test_explicit_harness_beats_env(self):
        """run.sh infers from its own invocation path, which is the better signal."""
        os.environ["CLAUDECODE"] = "1"
        os.environ["I18N_HARNESS"] = "codex"
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".codex" / "i18n")

    def test_unknown_harness_value_is_ignored(self):
        os.environ["I18N_HARNESS"] = "something-else"
        os.environ["CODEX_HOME"] = "/home/somebody/.codex"
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".codex" / "i18n")

    def test_no_signal_falls_back_to_claude(self):
        self.assertIsNone(P.detect_harness())
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".claude" / "i18n")


class TestExistingDirWins(HarnessEnvCase):
    """Two state.json files cannot share a chunk cache, so never start a second one."""

    def test_claude_dir_survives_a_codex_session(self):
        self.seed(".claude/i18n")
        os.environ["CODEX_HOME"] = "/home/somebody/.codex"
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".claude" / "i18n")

    def test_codex_dir_survives_a_claude_session(self):
        self.seed(".codex/i18n")
        os.environ["CLAUDECODE"] = "1"
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".codex" / "i18n")

    def test_neutral_dir_is_reused_but_never_chosen(self):
        self.seed(".i18n")
        os.environ["CODEX_HOME"] = "/home/somebody/.codex"
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".i18n")

    def test_glossary_alone_marks_the_directory_as_in_use(self):
        """The glossary can be seeded before the first plan run."""
        self.seed(".codex/i18n", marker="glossary.json")
        os.environ["CLAUDECODE"] = "1"
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".codex" / "i18n")

    def test_empty_directory_does_not_count(self):
        (self.root / ".codex" / "i18n").mkdir(parents=True)
        os.environ["CLAUDECODE"] = "1"
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".claude" / "i18n")

    def test_two_state_dirs_refuse_to_guess(self):
        self.seed(".claude/i18n")
        self.seed(".codex/i18n")
        with self.assertRaises(P.AmbiguousStateDir) as cm:
            P.resolve_state_dir(self.root)
        self.assertIn("--state-dir", str(cm.exception))

    def test_override_resolves_an_ambiguous_repo(self):
        self.seed(".claude/i18n")
        self.seed(".codex/i18n")
        self.assertEqual(
            P.resolve_state_dir(self.root, ".codex/i18n"), self.root / ".codex" / "i18n"
        )

    def test_run_main_reports_ambiguity_as_exit_2(self):
        def boom():
            raise P.AmbiguousStateDir("two of them")

        with mock.patch("sys.stderr"):
            self.assertEqual(P.run_main(boom), 2)


class TestStateDirEnvOverride(HarnessEnvCase):
    def test_env_override_is_honoured(self):
        os.environ["I18N_STATE_DIR"] = "somewhere/else"
        self.assertEqual(P.resolve_state_dir(self.root), self.root / "somewhere" / "else")

    def test_env_override_beats_an_existing_dir(self):
        self.seed(".claude/i18n")
        os.environ["I18N_STATE_DIR"] = ".i18n"
        self.assertEqual(P.resolve_state_dir(self.root), self.root / ".i18n")

    def test_flag_beats_env_override(self):
        os.environ["I18N_STATE_DIR"] = "from/env"
        self.assertEqual(
            P.resolve_state_dir(self.root, "from/flag"), self.root / "from" / "flag"
        )


class TestGitIgnoreGuard(unittest.TestCase):
    """.claude/ and .codex/ are gitignored wholesale in some repos; state.json must not be
    lost silently."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_no_warning_when_tracked(self):
        (self.root / ".gitignore").write_text(".claude/i18n/work/\n")
        d = self.root / P.CLAUDE_DIR
        self.assertIsNone(P.warn_if_ignored(self.root, d))

    def test_warns_when_dot_claude_is_ignored_wholesale(self):
        (self.root / ".gitignore").write_text(".claude/\n")
        msg = P.warn_if_ignored(self.root, self.root / P.CLAUDE_DIR)
        self.assertIsNotNone(msg)
        self.assertIn("state.json is git-ignored", msg)
        self.assertIn("--state-dir", msg)

    def test_warns_when_dot_codex_is_ignored_wholesale(self):
        (self.root / ".gitignore").write_text(".codex/\n")
        msg = P.warn_if_ignored(self.root, self.root / P.CODEX_DIR)
        self.assertIsNotNone(msg)
        self.assertIn(".codex/i18n/state.json is git-ignored", msg)

    def test_non_repo_does_not_crash(self):
        outside = Path(tempfile.mkdtemp())
        try:
            self.assertFalse(P.is_git_ignored(outside, outside / ".claude" / "i18n" / "state.json"))
        finally:
            shutil.rmtree(outside, ignore_errors=True)


class TestStateUsesGivenDir(HarnessEnvCase):
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
