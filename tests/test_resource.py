"""Key/value resource files: key-set identity and placeholder preservation."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
from i18n_resource import (
    flatten,
    read_resource,
    unflatten_into,
    verify_resource,
    write_resource,
)

SRC = {
    "app": {"title": "Hello", "greet": "Hi {name}, you have {count} messages"},
    "errors": {"notFound": "Not found", "retry": "Retry in %d seconds"},
    "lines": "first\\nsecond",
}


def errs(src, tgt):
    return {f["code"] for f in verify_resource(src, tgt, "en.json") if f["severity"] == "error"}


class TestFlatten(unittest.TestCase):
    def test_dotted_keys(self):
        f = flatten(SRC)
        self.assertIn("app.greet", f)
        self.assertIn("errors.notFound", f)
        self.assertEqual(f["lines"], "first\\nsecond")

    def test_lists_are_indexed(self):
        self.assertEqual(flatten({"a": ["x", "y"]}), {"a[0]": "x", "a[1]": "y"})

    def test_non_string_leaves_are_not_translatable(self):
        self.assertEqual(flatten({"n": 3, "b": True, "s": "x"}), {"s": "x"})

    def test_roundtrip_preserves_non_strings(self):
        tpl = {"n": 3, "b": True, "s": "x"}
        self.assertEqual(unflatten_into(tpl, {"s": "y"}), {"n": 3, "b": True, "s": "y"})


class TestVerifyResource(unittest.TestCase):
    def setUp(self):
        self.src = flatten(SRC)

    def test_good_translation_passes(self):
        tgt = dict(self.src)
        tgt["app.title"] = "你好"
        tgt["app.greet"] = "你好 {name}，你有 {count} 条消息"
        tgt["errors.notFound"] = "未找到"
        tgt["errors.retry"] = "%d 秒后重试"
        tgt["lines"] = "第一\\n第二"
        self.assertEqual(errs(self.src, tgt), set())

    def test_missing_key(self):
        tgt = dict(self.src)
        del tgt["app.title"]
        self.assertIn("RES-KEYSET", errs(self.src, tgt))

    def test_renamed_key(self):
        tgt = dict(self.src)
        tgt["app.标题"] = tgt.pop("app.title")
        self.assertIn("RES-KEYSET", errs(self.src, tgt))

    def test_translated_placeholder(self):
        tgt = dict(self.src)
        tgt["app.greet"] = "你好 {名字}，你有 {count} 条消息"
        self.assertIn("RES-PLACEHOLDER", errs(self.src, tgt))

    def test_dropped_printf_placeholder(self):
        tgt = dict(self.src)
        tgt["errors.retry"] = "稍后重试"
        self.assertIn("RES-PLACEHOLDER", errs(self.src, tgt))

    def test_empty_value(self):
        tgt = dict(self.src)
        tgt["app.title"] = ""
        self.assertIn("RES-EMPTY", errs(self.src, tgt))

    def test_escape_count_changed(self):
        tgt = dict(self.src)
        tgt["lines"] = "第一第二"
        self.assertIn("RES-ESCAPE", errs(self.src, tgt))


class TestJsonRoundTrip(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_write_preserves_shape_and_non_strings(self):
        src = self.d / "en.json"
        src.write_text(json.dumps({"a": {"t": "Hello"}, "n": 3, "l": ["x"]}), encoding="utf-8")
        structure, pairs, fmt = read_resource(src)
        self.assertEqual(fmt, "json")
        out = self.d / "zh.json"
        write_resource(out, structure, {"a.t": "你好", "l[0]": "叉"}, fmt)
        got = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(got, {"a": {"t": "你好"}, "n": 3, "l": ["叉"]})

    def test_properties_roundtrip_keeps_comments(self):
        src = self.d / "m.properties"
        src.write_text("# a comment\nkey.one=Hello\nkey.two=World\n", encoding="utf-8")
        structure, pairs, fmt = read_resource(src)
        self.assertEqual(pairs, {"key.one": "Hello", "key.two": "World"})
        out = self.d / "m_zh.properties"
        write_resource(out, structure, {"key.one": "你好", "key.two": "世界"}, fmt)
        text = out.read_text(encoding="utf-8")
        self.assertIn("# a comment", text)
        self.assertIn("key.one=你好", text)


if __name__ == "__main__":
    unittest.main()
