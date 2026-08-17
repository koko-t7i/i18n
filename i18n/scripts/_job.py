"""Translation jobs: split a document into chunks, then put the translation back together.

Replaces co-op-translator's ``start_markdown_agent_translation`` /
``finish_markdown_agent_translation`` with an implementation that needs only
``markdown-it-py``.

Three deliberate departures from the code this replaces:

* **No CJK emphasis rewriting.** Upstream silently converted ``**加粗**`` to
  ``<strong>加粗</strong>`` for ja/ko/zh targets and reported nothing. We simply never do it.
* **Placeholder restoration is checked.** Upstream restored with a ``str.replace`` loop and
  validated nothing, so a dropped ``@@CODE_BLOCK_n@@`` silently deleted a code block while
  ``warnings`` stayed empty. Here a mismatch raises.
* **Frontmatter is edited, not re-serialised.** Upstream round-tripped through
  ``yaml.dump``, destroying comments and reformatting values. We substitute scalar values
  line by line and leave every other byte alone.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _md

#: Bump when chunk boundaries change. Cached chunk translations from an older chunker are
#: keyed on source text that this one may no longer produce, so they must be discarded.
CHUNKER_VERSION = 1

JOB_TYPE = "markdown_translation"
JOB_VERSION = 1

DEFAULT_BUDGET = 8000  # characters; English prose runs ~4 chars/token

PLACEHOLDER_RE = re.compile(r"@@CODE_BLOCK_(\d+)@@")

RTL_LANGS = ("ar", "fa", "ur", "he")

_LANG_NAMES = {
    "zh-CN": "Chinese (Simplified)", "zh-TW": "Chinese (Traditional)",
    "zh-HK": "Chinese (Hong Kong)", "ja": "Japanese", "ko": "Korean",
    "es": "Spanish", "fr": "French", "de": "German", "it": "Italian",
    "pt-BR": "Portuguese (Brazil)", "pt-PT": "Portuguese (Portugal)",
    "ru": "Russian", "ar": "Arabic", "fa": "Persian", "he": "Hebrew",
    "ur": "Urdu", "hi": "Hindi", "th": "Thai", "vi": "Vietnamese",
    "id": "Indonesian", "tr": "Turkish", "pl": "Polish", "nl": "Dutch",
    "sv": "Swedish", "da": "Danish", "fi": "Finnish", "no": "Norwegian",
    "cs": "Czech", "el": "Greek", "uk": "Ukrainian", "hu": "Hungarian",
    "ro": "Romanian", "en": "English",
}

_ALIASES = {"cn": "zh-CN", "tw": "zh-TW", "hk": "zh-HK", "zh": "zh-CN",
            "jp": "ja", "kr": "ko", "br": "pt-BR", "pt": "pt-PT"}

_INSTRUCTIONS = (
    "Translate this chunk by following the prompt. Return only the translated content "
    "for this chunk, preserving placeholders and Markdown structure exactly."
)

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "prompts" / "translate_markdown.md"
)


# --------------------------------------------------------------------------------------
# language
# --------------------------------------------------------------------------------------

def normalize_lang(code: str) -> str:
    """``cn`` -> ``zh-CN``, ``ZH_cn`` -> ``zh-CN``. Unknown codes keep canonical casing."""
    c = (code or "").strip()
    if not c:
        return c
    if c.lower() in _ALIASES:
        return _ALIASES[c.lower()]
    parts = re.split(r"[-_]", c)
    out = [parts[0].lower()]
    for p in parts[1:]:
        out.append(p.upper() if len(p) == 2 else (p.title() if len(p) == 4 else p))
    return "-".join(out)


def language_name(code: str) -> str:
    norm = normalize_lang(code)
    return _LANG_NAMES.get(norm) or _LANG_NAMES.get(norm.split("-")[0]) or norm


def is_rtl(code: str) -> bool:
    return normalize_lang(code).split("-")[0].lower() in RTL_LANGS


# --------------------------------------------------------------------------------------
# code-block placeholders
# --------------------------------------------------------------------------------------

def replace_code_blocks(body: str) -> tuple[str, dict[str, str]]:
    """Swap fenced code for ``@@CODE_BLOCK_n@@`` tokens so no model can corrupt it."""
    spans = _md.fence_spans(body)
    out, mapping = [], {}
    pos = 0
    for i, (s, e) in enumerate(spans):
        token = f"@@CODE_BLOCK_{i}@@"
        out.append(body[pos:s])
        out.append(token)
        mapping[token] = body[s:e]
        pos = e
    out.append(body[pos:])
    return "".join(out), mapping


def restore_code_blocks(text: str, mapping: dict[str, str]) -> str:
    """Restore code in a single regex pass.

    A ``str.replace`` loop (what upstream did) can substitute into code that an earlier
    iteration already restored, if that code happens to contain placeholder-looking text.
    One pass with a callback cannot.
    """
    return PLACEHOLDER_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)


# --------------------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------------------

_LIST_RE = re.compile(r"^\s*(?:[*+-]|\d+[.)])\s+")


def _blocks(text: str) -> list[str]:
    """Split into atomic units: a heading, a whole list, or a paragraph-ish run.

    A list is never split -- that is the most common way to break nesting -- and neither is
    a line carrying a code placeholder.
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    buf: list[str] = []
    i = 0

    def flush():
        if buf:
            out.append("".join(buf))
            buf.clear()

    while i < len(lines):
        line = lines[i]
        if _md._HEADING_LINE_RE.match(line):
            flush()
            out.append(line)
            i += 1
            continue
        if _LIST_RE.match(line):
            flush()
            block = [line]
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    block.append(nxt)
                    i += 1
                    continue
                if _LIST_RE.match(nxt) or nxt[:1] in (" ", "\t"):
                    block.append(nxt)
                    i += 1
                    continue
                break
            out.append("".join(block))
            continue
        buf.append(line)
        i += 1
    flush()
    return out


#: A section boundary is only worth breaking on once the chunk has some bulk. Breaking at
#: every H2 regardless shatters a short document into one chunk per section -- eleven
#: subagent calls for a 5 KB README -- with no gain.
SECTION_BREAK_RATIO = 0.5


def chunk_body(text: str, budget: int = DEFAULT_BUDGET) -> list[str]:
    """Greedy accumulation of blocks, preferring H1/H2 boundaries once a chunk has bulk."""
    chunks: list[str] = []
    cur: list[str] = []
    size = 0
    for block in _blocks(text):
        starts_section = bool(re.match(r"^\s{0,3}#{1,2}\s", block))
        # Only break on a section boundary if the current chunk has real content --
        # otherwise leading blank lines become an empty chunk that costs a subagent call.
        has_content = any(p.strip() for p in cur)
        section_break = starts_section and has_content and size >= budget * SECTION_BREAK_RATIO
        if cur and (size + len(block) > budget or section_break):
            chunks.append("".join(cur))
            cur, size = [], 0
        cur.append(block)
        size += len(block)
    if cur:
        chunks.append("".join(cur))
    return chunks or [text]


# --------------------------------------------------------------------------------------
# prompt
# --------------------------------------------------------------------------------------

def build_prompt(lang: str, kind: str) -> str:
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.format(language_name=language_name(lang), language_code=normalize_lang(lang))
    prompt += (
        "\nWrite the output in right-to-left direction.\n" if is_rtl(lang)
        else "\nWrite the output in left-to-right direction.\n"
    )
    if kind == "frontmatter":
        prompt += (
            "\nThis chunk is YAML frontmatter rendered as `**key**: value` lines. "
            "Translate only the values. Keep every `**key**:` exactly as written, "
            "one field per line, same order, same count.\n"
        )
    return prompt


# --------------------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------------------

def start_job(document: str, lang: str, source_path: str | None = None,
              budget: int = DEFAULT_BUDGET) -> dict:
    """Split ``document`` into translatable chunks and return a job for :func:`finish_job`."""
    norm = normalize_lang(lang)
    fm_raw, body = _md.split_frontmatter(document)
    fm_fields = _md.frontmatter_fields(fm_raw) if fm_raw else {}

    masked_body, placeholder_map = replace_code_blocks(body)
    body_chunks = chunk_body(masked_body, budget)

    chunks = []
    if fm_fields:
        chunks.append({
            "id": "frontmatter:1", "kind": "frontmatter", "index": 1, "total": 1,
            "source": "\n".join(f"**{k}**: {v}" for k, v in fm_fields.items()),
            "prompt": build_prompt(norm, "frontmatter"),
            "instructions": _INSTRUCTIONS,
        })
    body_prompt = build_prompt(norm, "body")
    for i, src in enumerate(body_chunks, start=1):
        chunks.append({
            "id": f"body:{i}", "kind": "body", "index": i, "total": len(body_chunks),
            "source": src, "prompt": body_prompt, "instructions": _INSTRUCTIONS,
        })

    return {
        "job_type": JOB_TYPE,
        "version": JOB_VERSION,
        "chunker": CHUNKER_VERSION,
        "language_code": norm,
        "language_name": language_name(norm),
        "is_rtl": is_rtl(norm),
        "source_path": source_path,
        "chunk_count": len(chunks),
        "chunks": chunks,
        "state": {
            "original_document": document,
            "placeholder_map": placeholder_map,
            "frontmatter_raw": fm_raw,
            "frontmatter_fields": fm_fields,
        },
    }


# --------------------------------------------------------------------------------------
# finish
# --------------------------------------------------------------------------------------

_FM_LINE_RE = re.compile(r"^\*\*(?P<key>[^*]+)\*\*:[ \t]*(?P<val>.*)$")


def _coerce(translated_chunks) -> dict[str, str]:
    if isinstance(translated_chunks, dict):
        return {str(k): str(v) for k, v in translated_chunks.items()}
    out: dict[str, str] = {}
    for item in translated_chunks:
        cid = item.get("chunk_id") or item.get("id")
        if cid is None:
            raise ValueError("translated chunk is missing chunk_id")
        cid = str(cid)
        if cid in out:
            raise ValueError(f"duplicate chunk_id: {cid}")
        for key in ("translated_text", "translation", "content", "text"):
            if key in item:
                out[cid] = str(item[key])
                break
        else:
            raise ValueError(f"chunk {cid} has no translated text")
    return out


def finish_job(job: dict, translated_chunks) -> dict:
    """Reassemble a translated document. Raises on any contract violation."""
    if job.get("job_type") != JOB_TYPE or job.get("version") != JOB_VERSION:
        raise ValueError("unrecognised job payload")

    translations = _coerce(translated_chunks)
    chunks = list(job.get("chunks", []))
    expected = [str(c["id"]) for c in chunks]
    missing = [c for c in expected if c not in translations]
    if missing:
        raise ValueError(f"missing translated chunks: {', '.join(missing)}")
    extra = sorted(set(translations) - set(expected))

    state = job.get("state", {})
    mapping = state.get("placeholder_map", {})

    body_parts, fm_text = [], ""
    for c in chunks:
        text = translations[str(c["id"])]
        if c.get("kind") == "frontmatter":
            fm_text = text
        else:
            body_parts.append(text)
    content = "".join(body_parts)

    # -- placeholders must survive exactly once each -------------------------------------
    # Multiset, not set: a duplicated placeholder emits the same code block twice, which is
    # just as wrong as losing one and is what a set comparison would wave through.
    from collections import Counter
    want = Counter(mapping.keys())
    got = Counter(f"@@CODE_BLOCK_{n}@@" for n in PLACEHOLDER_RE.findall(content))
    if want != got:
        lost = sorted((want - got).elements())
        added = sorted((got - want).elements())
        raise ValueError(
            "code placeholders were altered by the translation; "
            f"lost={lost} unexpected={added}"
        )

    content = _md.normalize_internal_anchors(state.get("original_document", ""), content)
    content = restore_code_blocks(content, mapping)

    fm_raw = state.get("frontmatter_raw")
    if fm_raw:
        fields = dict(state.get("frontmatter_fields", {}))
        if fm_text and fields:
            for line in fm_text.splitlines():
                m = _FM_LINE_RE.match(line.strip())
                if m and m.group("key") in fields:
                    fields[m.group("key")] = m.group("val").strip()
        content = _md.apply_frontmatter_fields(fm_raw, fields) + content

    return {
        "language_code": job.get("language_code"),
        "source_path": job.get("source_path"),
        "content": content,
        "warnings": [f"ignored extra translated chunks: {', '.join(extra)}"] if extra else [],
    }
