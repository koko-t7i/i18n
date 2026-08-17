"""The style guide: what reaches the translator, and the part that can be checked."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
import _adapter as A

STYLE = {
    "zh-CN": {
        "audience": "开发者",
        "register": "简洁、技术",
        "address": "你",
        "quotes": "「」",
        "cjk_latin_space": True,
        "unknown_terms": "keep_english",
        "locale": {"units": "保持原文"},
    },
    "ja": {"quotes": "「」"},
}


class TestLoadStyle(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(A.load_style(self.root / "nope.json"), {})
        self.assertEqual(A.load_style(None), {})

    def test_schema_key_is_not_a_language(self):
        p = self.root / "style.json"
        p.write_text(json.dumps({"schema": 1, "zh-CN": {"address": "你"}}), encoding="utf-8")
        self.assertEqual(sorted(A.load_style(p)), ["zh-CN"])

    def test_region_falls_back_to_base_subtag(self):
        self.assertEqual(A.style_for({"zh": {"address": "你"}}, "zh-TW"), {"address": "你"})

    def test_exact_language_wins_over_base(self):
        style = {"zh": {"address": "您"}, "zh-CN": {"address": "你"}}
        self.assertEqual(A.style_for(style, "zh-CN")["address"], "你")


class TestStylePrompt(unittest.TestCase):
    def test_empty_style_adds_nothing(self):
        self.assertEqual(A.style_prompt({}, "zh-CN"), "")
        self.assertEqual(A.style_prompt(STYLE, "de"), "")

    def test_known_fields_are_labelled(self):
        out = A.style_prompt(STYLE, "zh-CN")
        self.assertIn("Audience: 开发者", out)
        self.assertIn("Address the reader as: 你", out)
        self.assertIn("Quotation marks: 「」", out)

    def test_booleans_render_as_words(self):
        self.assertIn("Latin/digits: yes", A.style_prompt(STYLE, "zh-CN"))

    def test_enum_is_expanded_into_an_instruction(self):
        self.assertIn("leave in English", A.style_prompt(STYLE, "zh-CN"))

    def test_nested_locale_is_flattened(self):
        self.assertIn("units: 保持原文", A.style_prompt(STYLE, "zh-CN"))

    def test_unknown_string_fields_still_reach_the_translator(self):
        out = A.style_prompt({"zh-CN": {"emoji": "不要使用"}}, "zh-CN")
        self.assertIn("emoji: 不要使用", out)


class TestCheckStyle(unittest.TestCase):
    def test_no_style_means_no_findings(self):
        self.assertEqual(A.check_style("随便写的“文字”", {}, "zh-CN"), [])

    def test_wrong_quote_system_warns(self):
        f = A.check_style("这里有“引号”。", STYLE, "zh-CN")
        self.assertEqual([x["code"] for x in f], ["X-STYLE"])
        self.assertEqual(f[0]["severity"], "warn")
        self.assertIn("“”", f[0]["message"])

    def test_configured_quote_system_passes(self):
        self.assertEqual(A.check_style("这里有「引号」。", STYLE, "zh-CN"), [])

    def test_missing_cjk_latin_space_warns(self):
        f = A.check_style("使用uv运行。", STYLE, "zh-CN")
        self.assertTrue(any("without a space" in x["message"] for x in f))

    def test_spaced_cjk_latin_passes(self):
        self.assertEqual(A.check_style("使用 uv 运行。", STYLE, "zh-CN"), [])

    def test_code_is_not_inspected(self):
        """A fenced block is full of unspaced identifiers and half-width punctuation."""
        text = "正常的 CJK 文本。\n\n```bash\nrun.sh plan --root . --lang zh-CN\n```\n"
        self.assertEqual(A.check_style(text, STYLE, "zh-CN"), [])

    def test_halfwidth_punctuation_between_cjk_warns(self):
        f = A.check_style("第一句,第二句。", STYLE, "zh-CN")
        self.assertTrue(any("half-width" in x["message"] for x in f))

    def test_halfwidth_punctuation_around_latin_is_left_alone(self):
        self.assertEqual(A.check_style("支持 json, yaml 两种格式。", STYLE, "zh-CN"), [])

    def test_findings_are_never_blocking(self):
        f = A.check_style("这里有“引号”,还有半角。", STYLE, "zh-CN")
        self.assertTrue(f)
        self.assertTrue(all(x["severity"] == "warn" for x in f))

    def test_file_is_attached_to_findings(self):
        f = A.check_style("这里有“引号”。", STYLE, "zh-CN", "docs/a.md")
        self.assertEqual(f[0]["file"], "docs/a.md")


if __name__ == "__main__":
    unittest.main()
