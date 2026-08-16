"""Structural verification: one positive and one negative per check."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
import _adapter as A  # noqa: E402
from i18n_verify import verify_pair  # noqa: E402

SRC = """---
title: Demo
---

# Demo Project

A small **bold** demo with a [link](https://example.com) and `inline code`.

## Getting Started

See [the guide](./docs/guide.md).

```bash
npm install --save demo
```

| Option | Default |
|---|---|
| `retries` | 3 |

Use the `{count}` placeholder and %s formatting.

<!-- keep me -->
"""

GOOD = """---
title: 演示
---

# 演示项目

一个带 **加粗** 的小演示，含[链接](https://example.com)和 `inline code`。

## 快速开始

参见[使用指南](./docs/guide.md)。

```bash
npm install --save demo
```

| 选项 | 默认值 |
|---|---|
| `retries` | 3 |

使用 `{count}` 占位符和 %s 格式化。

<!-- keep me -->
"""


def codes(src, tgt, lang="zh-CN", terms=()):
    return {f["code"] for f in verify_pair(src, tgt, lang, "README.md", list(terms))
            if f["severity"] == "error"}


class TestVerifyPositive(unittest.TestCase):
    def test_a_good_translation_produces_no_errors(self):
        self.assertEqual(codes(SRC, GOOD), set())


class TestVerifyNegative(unittest.TestCase):
    def test_placeholder_inside_inline_code_translated(self):
        self.assertIn("X-INLINE", codes(SRC, GOOD.replace("`{count}`", "`{数量}`")))

    def test_flag_name_inside_inline_code_translated(self):
        self.assertIn("X-INLINE", codes(SRC, GOOD.replace("`retries`", "`重试次数`")))

    def test_bare_placeholder_in_prose_translated(self):
        self.assertIn("X-TOKEN", codes(SRC, GOOD.replace("%s", "%字符串")))

    def test_html_leaked_into_translation(self):
        self.assertIn("X-HTML", codes(SRC, GOOD.replace("**加粗**", "<strong>加粗</strong>")))

    def test_code_block_body_modified(self):
        self.assertIn("X-FENCE", codes(SRC, GOOD.replace("npm install", "npm 安装")))

    def test_code_fence_language_changed(self):
        self.assertIn("X-FENCE", codes(SRC, GOOD.replace("```bash", "```shell")))

    def test_code_block_dropped(self):
        broken = GOOD.replace("```bash\nnpm install --save demo\n```\n", "")
        self.assertIn("X-FENCE", codes(SRC, broken))

    def test_external_url_changed(self):
        self.assertIn("X-LINK", codes(SRC, GOOD.replace("https://example.com", "https://evil.com")))

    def test_internal_link_dropped(self):
        self.assertIn("X-LINK", codes(SRC, GOOD.replace("[使用指南](./docs/guide.md)", "使用指南")))

    def test_heading_demoted(self):
        self.assertIn("X-HEADING", codes(SRC, GOOD.replace("## 快速开始", "### 快速开始")))

    def test_model_chatter(self):
        self.assertIn("X-CHATTER", codes(SRC, "以下是翻译：\n\n" + GOOD))

    def test_unresolved_coop_placeholder(self):
        self.assertIn("X-PLACEHOLDER", codes(SRC, GOOD.replace("npm install --save demo",
                                                               "@@CODE_BLOCK_0@@")))

    def test_untranslated_document_warns(self):
        warns = {f["code"] for f in verify_pair(SRC, SRC, "zh-CN", "README.md", [])
                 if f["severity"] == "warn"}
        self.assertIn("X-UNTRANSLATED", warns)


class TestGlossary(unittest.TestCase):
    def terms(self):
        return [
            A.Term(id="skill", source="skill", policy="translate",
                   translations={"zh-CN": {"text": "技能", "forbid": ["技巧"]}}),
            A.Term(id="cc", source="Claude Code", policy="do_not_translate",
                   case_sensitive=True),
        ]

    def test_missing_required_translation_is_an_error(self):
        f = A.check_glossary("A skill here.", "这里有一个本领。", self.terms(), "zh-CN")
        self.assertTrue(any(x["severity"] == "error" for x in f))

    def test_correct_translation_passes(self):
        self.assertEqual(A.check_glossary("A skill here.", "这里有一个技能。", self.terms(), "zh-CN"), [])

    def test_forbidden_rendering_warns(self):
        f = A.check_glossary("A skill here.", "这里有一个技能，也叫技巧。", self.terms(), "zh-CN")
        self.assertTrue(any(x["severity"] == "warn" for x in f))

    def test_do_not_translate_term_must_survive(self):
        f = A.check_glossary("Use Claude Code.", "使用克劳德代码。", self.terms(), "zh-CN")
        self.assertTrue(any("do-not-translate" in x["message"] for x in f))

    def test_term_only_in_code_is_not_required(self):
        # `skill` appears only inside inline code, so it is not a prose occurrence.
        self.assertEqual(A.check_glossary("Run `skill` now.", "现在运行 `skill`。",
                                          self.terms(), "zh-CN"), [])


if __name__ == "__main__":
    unittest.main()
