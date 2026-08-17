"""State schema compatibility and the fuzzy translation-memory match."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
import _state as S

PARA = (
    "This paragraph explains the widget and how it behaves when the cache is cold.\n"
    "It has several sentences so that a one-word edit is a small fraction of it.\n"
)


class MemoryCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.dir = self.root / ".claude" / "i18n"
        self.dir.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write_state(self, chunks, schema):
        (self.dir / "state.json").write_text(json.dumps({
            "schema": schema,
            "files": {"README.md": {"zh-CN": {
                "target": "README.zh-CN.md", "chunker": 1,
                "source_sha": "s", "target_sha": "t", "chunks": chunks,
            }}},
        }), encoding="utf-8")
        return S.State.load(self.root, self.dir)


class TestSchemaCompatibility(MemoryCase):
    """A schema bump must never discard state -- that would re-translate every repo."""

    def test_schema_1_is_read_not_dropped(self):
        st = self.write_state({S.sha(PARA): "旧译文"}, schema=1)
        self.assertEqual(st.chunk_cache("README.md", "zh-CN", 1), {S.sha(PARA): "旧译文"})

    def test_schema_1_entries_have_no_fuzzy_capability(self):
        """Without the old source there is nothing to measure similarity against."""
        st = self.write_state({S.sha(PARA): "旧译文"}, schema=1)
        self.assertEqual(st.chunk_pairs("README.md", "zh-CN", 1), {})
        self.assertIsNone(st.fuzzy_match(PARA.replace("cold", "warm"), "README.md", "zh-CN", 1))

    def test_schema_2_round_trip(self):
        st = self.write_state({S.sha(PARA): {"src": PARA, "tgt": "旧译文"}}, schema=2)
        self.assertEqual(st.chunk_cache("README.md", "zh-CN", 1), {S.sha(PARA): "旧译文"})
        self.assertEqual(st.chunk_pairs("README.md", "zh-CN", 1)[S.sha(PARA)]["src"], PARA)

    def test_mixed_shapes_coexist(self):
        """Files translated before and after the bump share one state.json."""
        st = self.write_state({
            "a": "只有译文",
            "b": {"src": PARA, "tgt": "两侧都有"},
        }, schema=2)
        self.assertEqual(st.chunk_cache("README.md", "zh-CN", 1),
                         {"a": "只有译文", "b": "两侧都有"})
        self.assertEqual(sorted(st.chunk_pairs("README.md", "zh-CN", 1)), ["b"])

    def test_unreadable_future_schema_starts_clean(self):
        st = self.write_state({"a": "x"}, schema=99)
        self.assertEqual(st.data["files"], {})

    def test_loading_stamps_the_current_schema(self):
        st = self.write_state({S.sha(PARA): "旧译文"}, schema=1)
        self.assertEqual(st.data["schema"], S.SCHEMA)


class TestFuzzyMatch(MemoryCase):
    def state(self):
        return self.write_state({S.sha(PARA): {"src": PARA, "tgt": "旧译文"}}, schema=2)

    def test_small_edit_matches(self):
        st = self.state()
        match = st.fuzzy_match(PARA.replace("cold", "warm"), "README.md", "zh-CN", 1)
        self.assertIsNotNone(match)
        pair, ratio = match
        self.assertEqual(pair["tgt"], "旧译文")
        self.assertGreater(ratio, 0.95)

    def test_unrelated_text_does_not_match(self):
        st = self.state()
        other = "Something else entirely, about billing and invoices and nothing here.\n"
        self.assertIsNone(st.fuzzy_match(other, "README.md", "zh-CN", 1))

    def test_threshold_is_honoured(self):
        st = self.state()
        half = PARA[: len(PARA) // 3]
        self.assertIsNone(st.fuzzy_match(half, "README.md", "zh-CN", 1, threshold=0.99))
        self.assertIsNotNone(st.fuzzy_match(half, "README.md", "zh-CN", 1, threshold=0.1))

    def test_best_of_several_is_chosen(self):
        near = PARA.replace("cold", "warm")
        far = "A totally different paragraph about invoices.\n"
        st = self.write_state({
            "a": {"src": far, "tgt": "远"},
            "b": {"src": PARA, "tgt": "近"},
        }, schema=2)
        pair, _ = st.fuzzy_match(near, "README.md", "zh-CN", 1)
        self.assertEqual(pair["tgt"], "近")

    def test_a_different_chunker_yields_nothing(self):
        """Chunk text from another splitter may never be produced again."""
        st = self.state()
        self.assertIsNone(st.fuzzy_match(PARA, "README.md", "zh-CN", chunker=2))

    def test_no_state_yields_nothing(self):
        st = S.State.load(self.root, self.dir)
        self.assertIsNone(st.fuzzy_match(PARA, "README.md", "zh-CN", 1))


if __name__ == "__main__":
    unittest.main()
