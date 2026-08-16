"""CJK emphasis repair.

co-op-translator rewrites ``**x**`` to ``<strong>x</strong>`` for CJK targets, silently
(``warnings`` comes back empty). These tests pin both the repair and, more importantly,
the cases where the repair must NOT fire.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
import _adapter as A  # noqa: E402


class TestPostfixCJK(unittest.TestCase):
    def test_strong_and_em_converted_back(self):
        src = "# T\n\nSome **bold** and *em* text.\n"
        tgt = "# T\n\n一些<strong>加粗</strong>和<em>斜体</em>文本。\n"
        out, notes = A.postfix_cjk_emphasis(src, tgt, "zh-CN")
        self.assertIn("**加粗**", out)
        self.assertIn("*斜体*", out)
        self.assertNotIn("<strong>", out)
        self.assertEqual(len(notes), 2)

    def test_b_and_i_aliases(self):
        out, _ = A.postfix_cjk_emphasis("**x**", "<b>粗</b><i>斜</i>", "zh-CN")
        self.assertEqual(out, "**粗***斜*")

    def test_non_cjk_target_untouched(self):
        tgt = "Algo <strong>negrita</strong>."
        self.assertEqual(A.postfix_cjk_emphasis("**bold**", tgt, "es")[0], tgt)

    # -- the negative cases that matter --------------------------------------------
    def test_source_already_uses_strong_so_it_is_left_alone(self):
        src = "Some <strong>bold</strong> text."
        tgt = "一些<strong>加粗</strong>文本。"
        out, notes = A.postfix_cjk_emphasis(src, tgt, "zh-CN")
        self.assertEqual(out, tgt)
        self.assertIn("left untouched", notes[0])

    def test_per_tag_granularity(self):
        # <strong> is in the source so it stays; <em> is not, so it is repaired.
        src = "Some <strong>bold</strong> and *em*."
        tgt = "一些<strong>加粗</strong>和<em>斜体</em>。"
        out, _ = A.postfix_cjk_emphasis(src, tgt, "zh-CN")
        self.assertIn("<strong>加粗</strong>", out)
        self.assertIn("*斜体*", out)

    def test_html_inside_code_blocks_is_never_rewritten(self):
        tgt = "文本 <strong>粗</strong>\n\n```html\n<strong>keep me</strong>\n```\n"
        out, _ = A.postfix_cjk_emphasis("x **b**", tgt, "zh-CN")
        self.assertIn("**粗**", out)
        self.assertIn("<strong>keep me</strong>", out)

    def test_html_inside_inline_code_is_never_rewritten(self):
        tgt = "用 `<strong>` 标签，以及<strong>粗</strong>。"
        out, _ = A.postfix_cjk_emphasis("use `<strong>` and **b**", tgt, "zh-CN")
        self.assertIn("`<strong>`", out)
        self.assertIn("**粗**", out)


class TestCJKRatio(unittest.TestCase):
    def test_detects_untranslated_text(self):
        self.assertLess(A.cjk_ratio("This is entirely English prose."), 0.1)
        self.assertGreater(A.cjk_ratio("这是完全的中文散文。"), 0.9)

    def test_empty_is_zero(self):
        self.assertEqual(A.cjk_ratio("123 !!!"), 0.0)


if __name__ == "__main__":
    unittest.main()
