"""Incremental translation state.

``_job.finish_job`` needs *every* chunk of a document to reassemble it, so incrementality
cannot live at the document level -- it has to live at the chunk level. This module caches
``sha256(chunk.source) -> translated_text`` per
(file, language). On a re-run, any chunk whose source text is unchanged is served from the
cache and never reaches a subagent; only cache misses become tasks.

Keying on the source hash rather than the chunk id also makes reuse survive re-chunking:
if a chunk keeps its text but moves from ``body:2`` to ``body:3``, it still hits.

Schema 2 also stores each chunk's *source* next to its translation, which turns the cache
into a small translation memory: a chunk that changed by a few words can be matched against
the nearest old one and translated as an edit rather than from scratch. That costs file
size -- state.json now holds both sides of every chunk -- and it is the only way to offer a
fuzzy match at all.

Schema 1 files stay readable and are never discarded: their chunk values are bare strings
instead of ``{"src": ..., "tgt": ...}``. They simply have no fuzzy-match capability until
each file is next translated. Dropping them instead would re-translate every repository
that has ever used this skill.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Self

SCHEMA = 2

#: Schemas whose contents this version can still use. Reading one does not rewrite it;
#: entries are upgraded in place the next time their file is translated.
READABLE_SCHEMAS = (1, 2)

#: Below this similarity, editing the old translation is more work than translating afresh
#: and risks anchoring the result to prose that no longer applies. CAT tools put the
#: useful-fuzzy floor around 70-75%; this is deliberately a little lower because chunks
#: here are whole sections rather than sentences, so the same edit moves the ratio less.
FUZZY_THRESHOLD = 0.6


def sha(text: str) -> str:
    """Hash of ``text`` after newline/trailing-whitespace normalisation."""
    norm = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_text(encoding="utf-8"))


@dataclass
class State:
    root: Path
    data: dict
    state_dir: Path

    # ---------------------------------------------------------------- construction
    @classmethod
    def load(cls, root: Path, state_dir: Path) -> Self:
        root, state_dir = Path(root), Path(state_dir)
        p = state_dir / "state.json"
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            if data.get("schema") in READABLE_SCHEMAS:
                data["schema"] = SCHEMA
                return cls(root, data, state_dir)
        return cls(root, {"schema": SCHEMA, "files": {}}, state_dir)

    def save(self) -> Path:
        p = self.state_dir / "state.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(p)
        return p

    # ---------------------------------------------------------------- accessors
    def entry(self, rel: str, lang: str) -> dict:
        return self.data.setdefault("files", {}).setdefault(rel, {}).get(lang, {})

    def _chunks(self, rel: str, lang: str, chunker: int | None) -> dict:
        """Raw chunk store, empty when it came from a different chunker.

        Chunk boundaries are part of the cache key by implication: text cached under an
        older splitter may never be produced again, so keeping it would silently mix
        translations from two different segmentations.
        """
        e = self.entry(rel, lang)
        if chunker is not None and e.get("chunker") != chunker:
            return {}
        return e.get("chunks", {})

    def chunk_cache(self, rel: str, lang: str, chunker: int | None = None) -> dict[str, str]:
        """``{source_sha: translated_text}`` -- the exact-match cache.

        Reads both schemas: a schema-1 value is the translation itself, a schema-2 value is
        a ``{"src", "tgt"}`` pair.
        """
        return {
            k: (v["tgt"] if isinstance(v, dict) else v)
            for k, v in self._chunks(rel, lang, chunker).items()
        }

    def chunk_pairs(self, rel: str, lang: str, chunker: int | None = None) -> dict[str, dict]:
        """``{source_sha: {"src", "tgt"}}`` -- only entries that carry their source.

        This is what fuzzy matching needs. Schema-1 entries are omitted rather than faked:
        without the original source text there is nothing to measure similarity against.
        """
        return {
            k: v
            for k, v in self._chunks(rel, lang, chunker).items()
            if isinstance(v, dict) and v.get("src") and v.get("tgt")
        }

    def record(
        self,
        rel: str,
        lang: str,
        target_rel: str,
        source_sha: str,
        target_text: str,
        chunks: dict[str, dict],
        chunker: int | None = None,
    ) -> None:
        """``chunks`` maps a source hash to ``{"src": ..., "tgt": ...}`` (schema 2)."""
        self.data.setdefault("files", {}).setdefault(rel, {})[lang] = {
            "target": target_rel,
            "chunker": chunker,
            "source_sha": source_sha,
            "target_sha": sha(target_text),
            "translated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "chunks": chunks,
        }

    def fuzzy_match(self, source: str, rel: str, lang: str, chunker: int | None = None,
                    threshold: float = FUZZY_THRESHOLD) -> tuple[dict, float] | None:
        """Nearest previously translated chunk of the same file, or None.

        A translation memory in miniature. Without it a chunk that changed by one word is
        translated from scratch, and the subagent rewrites settled prose that nobody asked
        it to touch -- which is a real cost on a document translated fifty times, not a
        theoretical one.

        Returns ``({"src", "tgt"}, ratio)``. Exact matches are the caller's job; this is
        only consulted after :meth:`chunk_cache` misses.
        """
        pairs = self.chunk_pairs(rel, lang, chunker)
        if not pairs:
            return None

        best, best_ratio = None, 0.0
        matcher = SequenceMatcher(autojunk=False)
        matcher.set_seq2(source)
        for pair in pairs.values():
            # real_quick_ratio/quick_ratio are cheap upper bounds; skip anything that
            # cannot beat the incumbent before paying for the full comparison.
            matcher.set_seq1(pair["src"])
            if matcher.real_quick_ratio() <= best_ratio or matcher.quick_ratio() <= best_ratio:
                continue
            ratio = matcher.ratio()
            if ratio > best_ratio:
                best, best_ratio = pair, ratio

        if best is None or best_ratio < threshold:
            return None
        return best, best_ratio

    # ---------------------------------------------------------------- staleness
    def status(self, rel: str, lang: str, source_sha: str, target_abs: Path,
               chunker: int | None = None) -> str:
        """One of ``missing`` | ``ok`` | ``stale`` | ``edited`` | ``orphan``.

        ``edited`` means a human changed the translated file after we wrote it; the caller
        must not overwrite it without an explicit ``--force``. A chunker change also reads
        as ``stale`` -- the translation is still valid text, but it can no longer be
        extended incrementally, so it has to be redone once.
        """
        e = self.entry(rel, lang)
        if not target_abs.exists():
            return "missing"
        if not e:
            return "orphan"
        if e.get("target_sha") and file_sha(target_abs) != e["target_sha"]:
            return "edited"
        if chunker is not None and e.get("chunker") != chunker:
            return "stale"
        return "ok" if e.get("source_sha") == source_sha else "stale"
