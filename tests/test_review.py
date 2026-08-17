"""Revision and proofreading: prompt rendering, source isolation, findings normalisation."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
import _adapter as A
import i18n_review as R

SOURCE = "The cache is cold on the first run.\n"
TARGET = "首次运行时缓存是冷的。\n"
STYLE = {"zh-CN": {"quotes": "「」", "address": "你"}}


class TestBuildPrompt(unittest.TestCase):
    def prompt(self, mode, style=None):
        return R.build_prompt(mode, "zh-CN", SOURCE, TARGET, [], style or {}, "r.json")

    def test_revision_carries_both_sides(self):
        out = self.prompt("revision")
        self.assertIn(SOURCE.strip(), out)
        self.assertIn(TARGET.strip(), out)

    def test_proofread_never_carries_the_source(self):
        """The whole point of the monolingual pass -- assert it, do not trust it."""
        out = self.prompt("proofread")
        self.assertIn(TARGET.strip(), out)
        self.assertNotIn(SOURCE.strip(), out)

    def test_proofread_tells_the_subagent_why(self):
        self.assertIn("have not been given the original", self.prompt("proofread"))

    def test_placeholders_are_all_substituted(self):
        for mode in R.MODES:
            out = self.prompt(mode, STYLE)
            for token in ("[source text]", "[translated text]", "[result_path]",
                          "[language_name]", "[style block, if any]",
                          "[terminology and style blocks, if any]"):
                self.assertNotIn(token, out, f"{token} survived in {mode}")

    def test_language_name_is_resolved(self):
        self.assertIn("Chinese (Simplified)", self.prompt("revision"))

    def test_style_block_reaches_both_modes(self):
        for mode in R.MODES:
            self.assertIn("Quotation marks: 「」", self.prompt(mode, STYLE))

    def test_intro_above_the_rule_is_not_sent(self):
        """Everything before the `---` is documentation for the operator, not the model."""
        self.assertNotIn("Substitute the bracketed parts", self.prompt("revision"))


class TestNormalise(unittest.TestCase):
    def one(self, mode, **over):
        item = {"dimension": "accuracy", "subtype": "mistranslation",
                "severity": "major", "span": "x", "note": "n"}
        item.update(over)
        return R.normalise({"findings": [item]}, mode, "README.md")

    def test_major_blocks_in_revision(self):
        out, bad = self.one("revision")
        self.assertEqual(out[0]["severity"], "error")
        self.assertEqual(out[0]["code"], "X-REVISION")
        self.assertEqual(bad, [])

    def test_minor_only_warns(self):
        out, _ = self.one("revision", severity="minor")
        self.assertEqual(out[0]["severity"], "warn")

    def test_critical_blocks(self):
        out, _ = self.one("revision", severity="critical")
        self.assertEqual(out[0]["severity"], "error")

    def test_proofreading_never_blocks(self):
        """Phrasing is a judgement call; gating on it never converges."""
        for sev in R.SEVERITIES:
            out, _ = self.one("proofread", dimension="fluency", severity=sev)
            self.assertEqual(out[0]["severity"], "warn")
            self.assertEqual(out[0]["code"], "X-PROOF")

    def test_mqm_severity_is_preserved_alongside(self):
        out, _ = self.one("proofread", dimension="style", severity="critical")
        self.assertEqual(out[0]["mqm_severity"], "critical")

    def test_cross_dimension_findings_are_discarded(self):
        out, bad = self.one("proofread")           # accuracy from a proofreader
        self.assertEqual(out, [])
        self.assertIn("may not report dimension", bad[0])

    def test_reviser_may_not_report_fluency(self):
        out, bad = self.one("revision", dimension="fluency")
        self.assertEqual(out, [])
        self.assertTrue(bad)

    def test_unknown_severity_is_discarded(self):
        out, bad = self.one("revision", severity="catastrophic")
        self.assertEqual(out, [])
        self.assertIn("unknown severity", bad[0])

    def test_empty_findings_are_fine(self):
        self.assertEqual(R.normalise({"findings": []}, "revision", "a.md"), ([], []))
        self.assertEqual(R.normalise({}, "revision", "a.md"), ([], []))

    def test_shape_matches_what_repair_consumes(self):
        """i18n_plan --repair reads `file` and `severity` off each finding."""
        out, _ = self.one("revision")
        self.assertEqual(out[0]["file"], "README.md")
        self.assertIn(out[0]["severity"], ("error", "warn"))

    def test_dimensions_are_disjoint_between_modes(self):
        self.assertFalse(R.DIMENSIONS["revision"] & R.DIMENSIONS["proofread"])


class TestStyleReachesReview(unittest.TestCase):
    def test_style_prompt_is_shared_with_translation(self):
        """One definition of the conventions, used by translator and reviewer alike."""
        self.assertEqual(
            A.style_prompt(STYLE, "zh-CN"),
            A.style_prompt(STYLE, "zh-CN"),
        )
        self.assertIn(A.style_prompt(STYLE, "zh-CN").strip(),
                      R.build_prompt("proofread", "zh-CN", "", TARGET, [], STYLE, "r.json"))


if __name__ == "__main__":
    unittest.main()
