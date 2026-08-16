"""Translation jobs: split, reassemble, and refuse anything that would lose content.

The load-bearing property is the identity round-trip: feeding each chunk back unchanged
must reproduce the source document byte for byte. If that holds, splitting and reassembly
cannot be silently losing anything.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
import _job  # noqa: E402
import _md  # noqa: E402

needs_parser = unittest.skipUnless(
    _md.using_parser(), "markdown-it-py not installed; run through run.sh"
)

DOC = '''---
title: "Demo Project"
# keep this comment
sidebar_position: 3
description: A demo
---

# Demo Project

Some **bold** text, a [link](https://example.com) and `inline code`.

See [install](#getting-started).

## Getting Started

```python
x = {"a": 1}
```

| Option | Default |
|---|---|
| `retries` | 3 |

Use `{count}` and %s.
'''


def echo(job):
    """The identity 'translation': every chunk comes back exactly as it went out."""
    return [{"chunk_id": c["id"], "translated_text": c["source"]} for c in job["chunks"]]


class TestIdentityRoundTrip(unittest.TestCase):
    def rt(self, doc, lang="zh"):
        job = _job.start_job(doc, lang, "README.md")
        return _job.finish_job(job, echo(job))["content"]

    def test_full_document(self):
        self.assertEqual(self.rt(DOC), DOC)

    def test_without_frontmatter(self):
        d = "# T\n\ntext\n\n```sh\nls\n```\n"
        self.assertEqual(self.rt(d), d)

    def test_long_paragraph_is_not_shattered(self):
        # Upstream split mid-paragraph and joined with "\n", turning one paragraph into
        # several and duplicating the heading. This must not.
        d = "# T\n\n" + ("word " * 4000) + "\n"
        out = self.rt(d)
        self.assertEqual(out, d)
        self.assertEqual(out.count("# T"), 1)

    @needs_parser
    def test_nested_fences(self):
        d = "# T\n\n> note\n> ```bash\n> npm i\n> ```\n\n- item\n  ```py\n  x=1\n  ```\n"
        self.assertEqual(self.rt(d), d)

    def test_no_empty_chunks(self):
        job = _job.start_job(DOC, "zh", "README.md")
        for c in job["chunks"]:
            self.assertTrue(c["source"].strip(), f"chunk {c['id']} is blank")


class TestStartJob(unittest.TestCase):
    def setUp(self):
        self.job = _job.start_job(DOC, "zh", "README.md")

    def test_language_normalised(self):
        self.assertEqual(self.job["language_code"], "zh-CN")
        self.assertEqual(self.job["language_name"], "Chinese (Simplified)")
        self.assertFalse(self.job["is_rtl"])

    def test_rtl_languages(self):
        for code in ("ar", "fa", "ur", "he"):
            self.assertTrue(_job.is_rtl(code), code)
        self.assertFalse(_job.is_rtl("zh-CN"))

    def test_code_is_placeholdered_before_any_model_sees_it(self):
        for c in self.job["chunks"]:
            self.assertNotIn("x = {\"a\": 1}", c["source"])
        self.assertEqual(len(self.job["state"]["placeholder_map"]), 1)

    def test_frontmatter_chunk_only_has_translatable_scalars(self):
        fm = [c for c in self.job["chunks"] if c["kind"] == "frontmatter"][0]
        self.assertIn("**title**: Demo Project", fm["source"])
        self.assertIn("**description**: A demo", fm["source"])
        self.assertNotIn("sidebar_position", fm["source"])

    def test_prompt_is_rendered_from_the_template(self):
        p = self.job["chunks"][-1]["prompt"]
        self.assertIn("Chinese (Simplified)", p)
        self.assertIn("left-to-right", p)
        self.assertNotIn("{language_name}", p)

    def test_chunker_version_recorded(self):
        self.assertEqual(self.job["chunker"], _job.CHUNKER_VERSION)


class TestFinishRefusesLoss(unittest.TestCase):
    """Every one of these was silent data loss upstream."""

    def setUp(self):
        self.job = _job.start_job(DOC, "zh", "README.md")

    def mutate(self, old, new):
        return [{"chunk_id": c["id"], "translated_text": c["source"].replace(old, new)}
                for c in self.job["chunks"]]

    def test_dropped_placeholder(self):
        with self.assertRaises(ValueError):
            _job.finish_job(self.job, self.mutate("@@CODE_BLOCK_0@@", ""))

    def test_mangled_placeholder(self):
        with self.assertRaises(ValueError):
            _job.finish_job(self.job, self.mutate("@@CODE_BLOCK_0@@", "@@ CODE_BLOCK_0 @@"))

    def test_duplicated_placeholder(self):
        with self.assertRaises(ValueError):
            _job.finish_job(self.job, self.mutate(
                "@@CODE_BLOCK_0@@", "@@CODE_BLOCK_0@@ @@CODE_BLOCK_0@@"))

    def test_missing_chunk(self):
        with self.assertRaises(ValueError):
            _job.finish_job(self.job, echo(self.job)[:-1])

    def test_duplicate_chunk_id(self):
        c = echo(self.job)
        with self.assertRaises(ValueError):
            _job.finish_job(self.job, c + [c[0]])

    def test_chunk_without_text(self):
        with self.assertRaises(ValueError):
            _job.finish_job(self.job, [{"chunk_id": c["id"]} for c in self.job["chunks"]])

    def test_wrong_job_type(self):
        bad = dict(self.job, job_type="something-else")
        with self.assertRaises(ValueError):
            _job.finish_job(bad, echo(self.job))

    def test_extra_chunk_is_only_a_warning(self):
        r = _job.finish_job(self.job, echo(self.job) + [{"chunk_id": "body:99",
                                                         "translated_text": "x"}])
        self.assertTrue(r["warnings"])


class TestFrontmatterRoundTrip(unittest.TestCase):
    def test_translated_values_applied_others_preserved(self):
        job = _job.start_job(DOC, "zh", "README.md")
        chunks = []
        for c in job["chunks"]:
            if c["kind"] == "frontmatter":
                chunks.append({"chunk_id": c["id"],
                               "translated_text": "**title**: 演示项目\n**description**: 一个演示"})
            else:
                chunks.append({"chunk_id": c["id"], "translated_text": c["source"]})
        out = _job.finish_job(job, chunks)["content"]
        self.assertIn('title: "演示项目"', out)
        self.assertIn("description: 一个演示", out)
        self.assertIn("# keep this comment", out)
        self.assertIn("sidebar_position: 3", out)

    def test_field_the_model_omitted_keeps_its_original_value(self):
        job = _job.start_job(DOC, "zh", "README.md")
        chunks = [{"chunk_id": c["id"],
                   "translated_text": ("**title**: 演示项目" if c["kind"] == "frontmatter"
                                       else c["source"])}
                  for c in job["chunks"]]
        out = _job.finish_job(job, chunks)["content"]
        self.assertIn("description: A demo", out)


class TestNormalizeLang(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(_job.normalize_lang("cn"), "zh-CN")
        self.assertEqual(_job.normalize_lang("jp"), "ja")
        self.assertEqual(_job.normalize_lang("kr"), "ko")

    def test_canonical_casing(self):
        self.assertEqual(_job.normalize_lang("ZH_cn"), "zh-CN")
        self.assertEqual(_job.normalize_lang("pt-br"), "pt-BR")

    def test_unknown_code_passes_through(self):
        self.assertEqual(_job.normalize_lang("xx-YY"), "xx-YY")


if __name__ == "__main__":
    unittest.main()
