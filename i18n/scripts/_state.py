"""Incremental translation state.

``_job.finish_job`` needs *every* chunk of a document to reassemble it, so incrementality
cannot live at the document level -- it has to live at the chunk level. This module caches
``sha256(chunk.source) -> translated_text`` per
(file, language). On a re-run, any chunk whose source text is unchanged is served from the
cache and never reaches a subagent; only cache misses become tasks.

Keying on the source hash rather than the chunk id also makes reuse survive re-chunking:
if a chunk keeps its text but moves from ``body:2`` to ``body:3``, it still hits.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = 1


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
    def load(cls, root: Path, state_dir: Path) -> "State":
        root, state_dir = Path(root), Path(state_dir)
        p = state_dir / "state.json"
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
            if data.get("schema") == SCHEMA:
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

    def chunk_cache(self, rel: str, lang: str, chunker: int | None = None) -> dict[str, str]:
        """Cached chunk translations, empty when they came from a different chunker.

        Chunk boundaries are part of the cache key by implication: text cached under an
        older splitter may never be produced again, so keeping it would silently mix
        translations from two different segmentations.
        """
        e = self.entry(rel, lang)
        if chunker is not None and e.get("chunker") != chunker:
            return {}
        return e.get("chunks", {})

    def record(
        self,
        rel: str,
        lang: str,
        target_rel: str,
        source_sha: str,
        target_text: str,
        chunks: dict[str, str],
        chunker: int | None = None,
    ) -> None:
        self.data.setdefault("files", {}).setdefault(rel, {})[lang] = {
            "target": target_rel,
            "chunker": chunker,
            "source_sha": source_sha,
            "target_sha": sha(target_text),
            "translated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "chunks": chunks,
        }

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
