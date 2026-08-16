"""Layout detection, path resolution and link rewriting."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
import _adapter as A  # noqa: E402


def build(tree: dict) -> Path:
    root = Path(tempfile.mkdtemp())
    for rel, body in tree.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


class TestLayoutDetection(unittest.TestCase):
    def tearDown(self):
        for d in getattr(self, "_dirs", []):
            shutil.rmtree(d, ignore_errors=True)

    def mk(self, tree):
        d = build(tree)
        self._dirs = getattr(self, "_dirs", []) + [d]
        return d

    def test_sibling_suffix_detected(self):
        root = self.mk({"README.md": "# a", "README.zh-CN.md": "# b", "CONTRIBUTING.md": "# c"})
        lay = A.detect_layout(root, "zh-CN")
        self.assertEqual(lay.style, "sibling")
        self.assertEqual(lay.pattern, "{stem}.{lang}{ext}")
        self.assertEqual(lay.lang_token, "zh-CN")
        self.assertEqual(A.resolve_target("CONTRIBUTING.md", lay), "CONTRIBUTING.zh-CN.md")

    def test_underscore_sibling_variant(self):
        root = self.mk({"README.md": "# a", "README_CN.md": "# b"})
        lay = A.detect_layout(root, "zh-CN")
        self.assertEqual(lay.style, "sibling")
        self.assertEqual(lay.lang_token, "CN")
        self.assertEqual(A.resolve_target("README.md", lay), "README_CN.md")

    def test_parallel_dir_detected(self):
        root = self.mk({"docs/guide.md": "# a", "docs/zh-CN/guide.md": "# b"})
        lay = A.detect_layout(root, "zh-CN")
        self.assertEqual(lay.style, "parallel")
        self.assertEqual(A.resolve_target("docs/sub/deep.md", lay), "docs/zh-CN/sub/deep.md")

    def test_file_outside_parallel_prefix_falls_back_to_sibling(self):
        # A root README next to a docs/<lang>/ tree must not be relocated into docs/.
        root = self.mk({"README.md": "# a", "docs/guide.md": "# b", "docs/zh-CN/guide.md": "# c"})
        lay = A.detect_layout(root, "zh-CN")
        self.assertEqual(lay.style, "parallel")
        self.assertEqual(A.resolve_target("README.md", lay), "README.zh-CN.md")

    def test_no_evidence_defaults_to_sibling_with_zero_confidence(self):
        root = self.mk({"README.md": "# a", "docs/a.md": "# b"})
        lay = A.detect_layout(root, "zh-CN")
        self.assertEqual(lay.style, "sibling")
        self.assertEqual(lay.confidence, 0.0)
        self.assertEqual(A.resolve_target("docs/a.md", lay), "docs/a.zh-CN.md")

    def test_sibling_needs_the_source_beside_it(self):
        # notes.zh-CN.md with no notes.md is not evidence of a sibling convention.
        root = self.mk({"notes.zh-CN.md": "# b"})
        self.assertEqual(A.detect_layout(root, "zh-CN").confidence, 0.0)

    def test_translation_artifacts_are_not_sources(self):
        root = self.mk({"README.md": "# a", "README.zh-CN.md": "# b",
                        "docs/guide.md": "# c", "docs/zh-CN/guide.md": "# d"})
        lay = A.detect_layout(root, "zh-CN")
        self.assertFalse(A.is_translation_artifact("README.md", "zh-CN", lay))
        self.assertTrue(A.is_translation_artifact("README.zh-CN.md", "zh-CN", lay))
        self.assertTrue(A.is_translation_artifact("docs/zh-CN/guide.md", "zh-CN", lay))


class TestLinkRewriting(unittest.TestCase):
    def setUp(self):
        self.root = build({"README.md": "# a", "docs/guide.md": "# g", "docs/other.md": "# o",
                           "docs/zh-CN/guide.md": "# gz", "imgs/a.png": "x"})
        self.lay = A.detect_layout(self.root, "zh-CN")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def rw(self, content):
        return A.rewrite_links(content, "docs/guide.md", "docs/zh-CN/guide.md", self.lay, self.root)

    def test_same_directory_is_a_noop(self):
        c = "[a](./b.md)"
        self.assertEqual(A.rewrite_links(c, "README.md", "README.zh-CN.md", self.lay, self.root), c)

    def test_sibling_markdown_points_at_translated_counterpart(self):
        # docs/other.md exists, so its translation lands at docs/zh-CN/other.md -- which is
        # the same directory as the rewritten file, hence a bare filename.
        self.assertEqual(self.rw("[o](./other.md)"), "[o](other.md)")

    def test_unknown_markdown_keeps_pointing_at_the_original(self):
        # No docs/nope.md on disk, so there will be no translation of it to point at.
        self.assertEqual(self.rw("[x](./nope.md)"), "[x](../nope.md)")

    def test_external_and_anchor_untouched(self):
        c = "[e](https://x.com/a.md) [a](#sec) [m](mailto:a@b.c)"
        self.assertEqual(self.rw(c), c)

    def test_asset_repointed_at_same_file(self):
        self.assertEqual(self.rw("![i](../imgs/a.png)"), "![i](../../imgs/a.png)")

    def test_anchor_survives_on_a_rewritten_path(self):
        self.assertEqual(self.rw("[o](./other.md#sec)"), "[o](other.md#sec)")

    def test_link_up_to_root_readme_gets_translated_counterpart(self):
        # docs/guide.md -> docs/zh-CN/guide.md, so ../README.md becomes ../../README.zh-CN.md
        self.assertEqual(self.rw("[r](../README.md)"), "[r](../../README.zh-CN.md)")

    def test_links_inside_code_are_untouched(self):
        c = "text\n\n```md\n[x](./other.md)\n```\n"
        self.assertIn("[x](./other.md)", self.rw(c))

    def test_reference_definitions_rewritten(self):
        self.assertEqual(self.rw("[r]: ../README.md"), "[r]: ../../README.zh-CN.md")


class TestCodeMasking(unittest.TestCase):
    def test_roundtrip(self):
        t = "a `x` b\n\n```bash\nnpm i\n```\n\nc `y`\n"
        m, ch = A.mask_code(t)
        self.assertNotIn("npm i", m)
        self.assertEqual(A.unmask_code(m, ch), t)

    def test_unclosed_fence_is_still_captured(self):
        t = "a\n\n```bash\nnpm i\n"
        m, ch = A.mask_code(t)
        self.assertNotIn("npm i", m)
        self.assertEqual(A.unmask_code(m, ch), t)


if __name__ == "__main__":
    unittest.main()
