"""Markdown primitives.

Fence detection is tested against both backends. The regex fallback is deliberately allowed
to fail on container-nested fences -- that is exactly why markdown-it-py is preferred -- so
those cases are marked as requiring the real parser.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
import _md  # noqa: E402

needs_parser = unittest.skipUnless(
    _md.using_parser(), "markdown-it-py not installed; run through run.sh"
)


def fenced(text):
    return [text[s:e] for s, e in _md.fence_spans(text)]


class TestFences(unittest.TestCase):
    def test_backtick_fence(self):
        self.assertEqual(fenced("a\n\n```py\nx=1\n```\n\nb\n"), ["```py\nx=1\n```\n"])

    def test_tilde_fence(self):
        self.assertEqual(fenced("~~~js\nlet a=1;\n~~~\n"), ["~~~js\nlet a=1;\n~~~\n"])

    def test_info_string_with_attributes(self):
        t = "```python title=\"x.py\"\nx=1\n```\n"
        self.assertEqual(fenced(t), [t])

    def test_unclosed_fence_still_captured(self):
        t = "# T\n\n```bash\nnpm i\n\nstill going\n"
        self.assertEqual(len(fenced(t)), 1)

    def test_no_fence(self):
        self.assertEqual(fenced("just prose with `inline` code\n"), [])

    @needs_parser
    def test_fence_inside_blockquote(self):
        # The regex fallback mis-slices this; it is the main reason to prefer the parser.
        got = fenced("> note\n> ```bash\n> npm i\n> ```\n\ndone\n")
        self.assertEqual(len(got), 1)
        self.assertIn("> npm i", got[0])

    @needs_parser
    def test_fence_inside_list_item(self):
        got = fenced("- item\n  ```py\n  x=1\n  ```\n- two\n")
        self.assertEqual(len(got), 1)
        self.assertIn("x=1", got[0])

    @needs_parser
    def test_two_fences_are_separate(self):
        self.assertEqual(len(fenced("```a\n1\n```\n\ntext\n\n```b\n2\n```\n")), 2)


class TestInlineCode(unittest.TestCase):
    def test_inline_outside_fences(self):
        t = "use `--flag` here\n"
        self.assertEqual([t[s:e] for s, e in _md.inline_code_spans(t)], ["`--flag`"])

    def test_inline_inside_fence_is_not_reported(self):
        t = "```py\nx = `not inline`\n```\n"
        self.assertEqual(_md.inline_code_spans(t), [])

    def test_double_backtick_span(self):
        t = "a ``code with ` tick`` b\n"
        self.assertEqual([t[s:e] for s, e in _md.inline_code_spans(t)], ["``code with ` tick``"])


class TestMasking(unittest.TestCase):
    def test_roundtrip_is_lossless(self):
        t = "a `x` b\n\n```bash\nnpm i\n```\n\nc `y`\n"
        m, ch = _md.mask_code(t)
        self.assertNotIn("npm i", m)
        self.assertNotIn("`x`", m)
        self.assertEqual(_md.unmask_code(m, ch), t)

    def test_roundtrip_with_nested_fence(self):
        t = "> ```sh\n> ls\n> ```\n\ntail `z`\n"
        m, ch = _md.mask_code(t)
        self.assertEqual(_md.unmask_code(m, ch), t)


class TestHeadings(unittest.TestCase):
    def test_levels_and_slugs(self):
        got = _md.headings("# Title\n\n## Getting Started\n\n### `code` bit\n")
        self.assertEqual([lv for lv, _, _ in got], [1, 2, 3])
        self.assertEqual([s for _, _, s in got], ["title", "getting-started", "code-bit"])

    def test_cjk_slug_survives(self):
        self.assertEqual([s for _, _, s in _md.headings("## 快速开始\n")], ["快速开始"])

    def test_duplicate_headings_get_suffixes(self):
        got = [s for _, _, s in _md.headings("## Dup\n\n## Dup\n\n## Dup\n")]
        self.assertEqual(got, ["dup", "dup-1", "dup-2"])

    def test_headings_inside_code_are_not_headings(self):
        self.assertEqual(_md.headings("```md\n# not a heading\n```\n"), [])


class TestFrontmatter(unittest.TestCase):
    RAW = ('---\ntitle: "Hello"\n# a comment\ndate: 2026-01-01\n'
           "description: Plain value\ntags:\n  - a\nbody: |\n  block\n"
           "sidebar_position: 3\n---\n")

    def test_absent(self):
        self.assertEqual(_md.split_frontmatter("# Body\n"), (None, "# Body\n"))

    def test_split(self):
        raw, body = _md.split_frontmatter(self.RAW + "\n# Body\n")
        self.assertEqual(raw, self.RAW)
        self.assertEqual(body, "\n# Body\n")

    def test_malformed_is_not_frontmatter(self):
        self.assertEqual(_md.split_frontmatter("---\ntitle: x\n")[0], None)

    def test_only_translatable_scalars_extracted(self):
        f = _md.frontmatter_fields(self.RAW)
        self.assertEqual(f, {"title": "Hello", "description": "Plain value"})

    def test_multiline_and_unknown_keys_skipped(self):
        f = _md.frontmatter_fields(self.RAW)
        for k in ("date", "tags", "body", "sidebar_position"):
            self.assertNotIn(k, f)

    def test_substitution_preserves_everything_else(self):
        out = _md.apply_frontmatter_fields(self.RAW, {"title": "你好", "description": "普通值"})
        self.assertIn("# a comment", out)
        self.assertIn("date: 2026-01-01", out)
        self.assertIn("  - a", out)
        self.assertIn("body: |", out)
        self.assertIn("sidebar_position: 3", out)

    def test_quoting_style_is_inherited(self):
        out = _md.apply_frontmatter_fields(self.RAW, {"title": "你好", "description": "普通值"})
        self.assertIn('title: "你好"', out)      # was quoted
        self.assertIn("description: 普通值", out)  # was bare

    def test_value_needing_quotes_gets_them(self):
        out = _md.apply_frontmatter_fields("---\ntitle: x\n---\n", {"title": "a: b"})
        self.assertIn('title: "a: b"', out)

    def test_unknown_key_is_never_substituted(self):
        out = _md.apply_frontmatter_fields(self.RAW, {"sidebar_position": "99"})
        self.assertIn("sidebar_position: 3", out)


class TestAnchors(unittest.TestCase):
    def test_fragment_repointed_at_translated_heading(self):
        src = "# A\n\n## Getting Started\n\nsee [x](#getting-started)\n"
        tgt = "# A\n\n## 快速开始\n\nsee [x](#getting-started)\n"
        self.assertIn("(#快速开始)", _md.normalize_internal_anchors(src, tgt))

    def test_unknown_fragment_untouched(self):
        src = "# A\n\n## B\n\ntext\n"
        tgt = "# A\n\n## 乙\n\nsee [x](#hand-written)\n"
        self.assertIn("(#hand-written)", _md.normalize_internal_anchors(src, tgt))

    def test_untranslated_headings_are_a_noop(self):
        doc = "# A\n\n## B\n\nsee [x](#b)\n"
        self.assertEqual(_md.normalize_internal_anchors(doc, doc), doc)

    def test_anchors_inside_code_untouched(self):
        src = "# A\n\n## Getting Started\n\ntext\n"
        tgt = "# A\n\n## 快速开始\n\n```md\n[x](#getting-started)\n```\n"
        self.assertIn("[x](#getting-started)", _md.normalize_internal_anchors(src, tgt))


if __name__ == "__main__":
    unittest.main()
