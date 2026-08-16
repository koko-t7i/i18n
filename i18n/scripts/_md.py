"""Markdown primitives: fences, inline code, headings, frontmatter.

This is the only module that touches ``markdown-it-py``. It is imported lazily so the test
suite still runs on a bare ``python3`` with nothing installed; when the import fails we fall
back to a regex scanner and warn once.

The fallback is genuinely worse and the difference is not academic: a fence nested inside a
blockquote (``> ```bash``) or inside a list item is a `fence` token to markdown-it, but the
regex sees the ``> `` prefix and mis-slices the block. Prefer the real parser.
"""

from __future__ import annotations

import re
import sys
import unicodedata

# --------------------------------------------------------------------------------------
# parser availability
# --------------------------------------------------------------------------------------

_MD = None
_MD_TRIED = False
_WARNED = False


def _parser():
    """Return a cached MarkdownIt instance, or None if markdown-it-py is unavailable."""
    global _MD, _MD_TRIED
    if not _MD_TRIED:
        _MD_TRIED = True
        try:
            from markdown_it import MarkdownIt  # type: ignore
            _MD = MarkdownIt("commonmark")
        except ImportError:
            _MD = None
    return _MD


def _warn_fallback() -> None:
    global _WARNED
    if _WARNED:
        return
    _WARNED = True
    sys.stderr.write(
        "warning: markdown-it-py is unavailable; falling back to a regex Markdown scanner.\n"
        "         Fences nested in blockquotes or list items may be detected incorrectly.\n"
        "         Run through run.sh, which supplies it via uv.\n"
    )


def using_parser() -> bool:
    """True when the real CommonMark parser is in use (tests branch on this)."""
    return _parser() is not None


# --------------------------------------------------------------------------------------
# line offsets
# --------------------------------------------------------------------------------------

def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


# --------------------------------------------------------------------------------------
# fenced code
# --------------------------------------------------------------------------------------

#: Fallback only. Closing fence must be at least as long as the opener, per CommonMark,
#: which a backreference cannot express -- hence `{n,}` built at match time is impossible
#: in one pass. This approximation requires an exact-length close.
#: The trailing ``\n?`` matters: markdown-it's token map covers the newline after the
#: closing fence, and both backends must produce identical spans or the two code paths
#: disagree about where a code block ends.
_FENCE_FALLBACK_RE = re.compile(
    r"^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)\n"
    r"(?P<body>.*?)(?:^(?P=indent)(?P=fence)[ \t]*$\n?|\Z)",
    re.DOTALL | re.MULTILINE,
)


def fence_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of fenced code blocks, in document order.

    Spans cover the opening fence line through the closing fence line inclusive, including
    any container prefix (``> ``) on those lines, so slicing and re-inserting round-trips
    byte for byte.
    """
    md = _parser()
    if md is None:
        _warn_fallback()
        return [(m.start(), m.end()) for m in _FENCE_FALLBACK_RE.finditer(text)]

    offsets = _line_offsets(text)
    spans: list[tuple[int, int]] = []
    for tok in md.parse(text):
        if tok.type == "fence" and tok.map:
            start_line, end_line = tok.map  # end is exclusive
            spans.append((offsets[start_line], offsets[min(end_line, len(offsets) - 1)]))
    spans.sort()
    return spans


# --------------------------------------------------------------------------------------
# inline code
# --------------------------------------------------------------------------------------

_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)


def inline_code_spans(text: str, skip: list[tuple[int, int]] | None = None) -> list[tuple[int, int]]:
    """Character spans of inline code, excluding anything inside ``skip`` (usually fences).

    Regex rather than AST on purpose: markdown-it's ``code_inline`` tokens carry no character
    offsets, so recovering them means re-scanning backtick runs anyway.
    """
    blocked = skip if skip is not None else fence_spans(text)
    out = []
    for m in _INLINE_CODE_RE.finditer(text):
        s, e = m.span()
        if any(bs <= s < be for bs, be in blocked):
            continue
        out.append((s, e))
    return out


# --------------------------------------------------------------------------------------
# masking (used by the verifier and the glossary matcher)
# --------------------------------------------------------------------------------------

_MASK = "\x00M{}\x00"


def mask_code(text: str) -> tuple[str, list[str]]:
    """Replace fenced and inline code with opaque sentinels.

    Returns ``(masked_text, chunks)``; feed both to :func:`unmask_code`. Sentinels use NUL so
    they can never collide with real Markdown. Fenced blocks come first in ``chunks``.
    """
    fences = fence_spans(text)
    spans = [(s, e, "fence") for s, e in fences]
    spans += [(s, e, "inline") for s, e in inline_code_spans(text, fences)]
    spans.sort()

    chunks: list[str] = []
    out: list[str] = []
    pos = 0
    for s, e, _kind in spans:
        if s < pos:  # overlapping match, already consumed
            continue
        out.append(text[pos:s])
        out.append(_MASK.format(len(chunks)))
        chunks.append(text[s:e])
        pos = e
    out.append(text[pos:])
    return "".join(out), chunks


def unmask_code(text: str, chunks: list[str]) -> str:
    for i, c in enumerate(chunks):
        text = text.replace(_MASK.format(i), c)
    return text


def is_fence(chunk: str) -> bool:
    return chunk.lstrip().startswith(("```", "~~~")) or chunk.lstrip().startswith(("> ```", ">```"))


# --------------------------------------------------------------------------------------
# headings
# --------------------------------------------------------------------------------------

_ATX_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_HEADING_LINE_RE = re.compile(r"^\s{0,3}#{1,6}\s")


def slugify(text: str) -> str:
    """GitHub-flavoured anchor slug (CJK survives; punctuation is dropped)."""
    t = re.sub(r"`([^`]*)`", r"\1", text)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[*_~]", "", t).strip().lower()
    t = "".join(c for c in t if unicodedata.category(c)[0] not in "PS" or c in "-_ ")
    return re.sub(r"[\s]+", "-", t).strip("-")


def headings(text: str) -> list[tuple[int, str, str]]:
    """``(level, raw_text, unique_slug)`` in document order, with GitHub ``-1``/``-2`` dedupe."""
    md = _parser()
    found: list[tuple[int, str]] = []
    if md is None:
        _warn_fallback()
        masked, chunks = mask_code(text)
        for m in _ATX_RE.finditer(masked):
            # Restore code spans before slugifying, or the sentinel leaks into the anchor.
            found.append((len(m.group(1)), unmask_code(m.group(2), chunks)))
    else:
        tokens = md.parse(text)
        for i, tok in enumerate(tokens):
            if tok.type == "heading_open":
                level = int(tok.tag[1:])
                content = tokens[i + 1].content if i + 1 < len(tokens) else ""
                found.append((level, content))

    seen: dict[str, int] = {}
    out = []
    for level, raw in found:
        base = slugify(raw)
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append((level, raw, base if n == 0 else f"{base}-{n}"))
    return out


# --------------------------------------------------------------------------------------
# frontmatter
# --------------------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?\n)---[ \t]*(?:\n|\Z)", re.DOTALL)


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """``(raw_block_including_fences, body)``; ``(None, text)`` when there is no frontmatter.

    The raw block is returned verbatim -- comments, quoting and key order intact -- because
    the round-trip substitutes values line by line rather than re-serialising YAML.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, text
    return text[: m.end()], text[m.end():]


#: Frontmatter keys whose values are prose. Everything else is preserved untranslated --
#: unknown keys default to preserve, which is the safe direction.
TRANSLATABLE_KEYS = frozenset({
    "title", "description", "excerpt", "summary", "abstract", "subtitle", "tagline",
    "caption", "alt", "label", "placeholder", "tooltip", "help_text",
    "error_message", "success_message", "warning_message", "info_message",
    "og_title", "og_description", "twitter_title", "twitter_description",
    "meta_title", "meta_description", "seo_title", "seo_description", "keywords",
})

#: A scalar ``key: value`` line at top level. Indented keys belong to nested structures and
#: are deliberately not matched -- translating half of a nested block is worse than skipping.
_FM_FIELD_RE = re.compile(r"^(?P<key>[A-Za-z_][\w.-]*)(?P<sep>:[ \t]*)(?P<val>\S.*?)[ \t]*$")


def frontmatter_fields(raw_block: str) -> dict[str, str]:
    """Translatable scalar fields of a raw frontmatter block, in document order.

    Multi-line values (block scalars, nested maps, lists) never match and are therefore
    preserved untouched.
    """
    out: dict[str, str] = {}
    for line in raw_block.splitlines():
        m = _FM_FIELD_RE.match(line)
        if not m:
            continue
        key = m.group("key")
        if key.lower() not in TRANSLATABLE_KEYS:
            continue
        val = m.group("val")
        if val in ("|", ">", "|-", ">-", "[", "{"):  # opens a multi-line value
            continue
        out[key] = _strip_quotes(val)
    return out


def _strip_quotes(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def apply_frontmatter_fields(raw_block: str, values: dict[str, str]) -> str:
    """Substitute translated values back into the raw block, preserving everything else.

    Quoting style is inherited from the original line, so a value that was quoted stays
    quoted. Comments, blank lines, key order and untranslated keys are untouched.

    Only keys on the translatable allowlist are ever rewritten, whatever the caller passes:
    a bug upstream of here must not be able to rewrite ``slug`` or ``sidebar_position``.
    """
    out = []
    for line in raw_block.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        m = _FM_FIELD_RE.match(stripped)
        if not m or m.group("key") not in values or m.group("key").lower() not in TRANSLATABLE_KEYS:
            out.append(line)
            continue
        new = values[m.group("key")]
        orig = m.group("val")
        if len(orig) >= 2 and orig[0] == orig[-1] and orig[0] in "\"'":
            q = orig[0]
            new = f"{q}{new.replace(q, chr(92) + q)}{q}"
        elif _needs_quoting(new):
            new = '"%s"' % new.replace('"', '\\"')
        nl = line[len(stripped):]
        out.append(f"{m.group('key')}{m.group('sep')}{new}{nl}")
    return "".join(out)


def _needs_quoting(v: str) -> bool:
    """True when a bare YAML scalar would be mis-parsed or would break the document."""
    return bool(v) and (v[0] in "#&*!|>%@`[{'\"" or ": " in v or v.endswith(":") or "\n" in v)


# --------------------------------------------------------------------------------------
# internal anchors
# --------------------------------------------------------------------------------------

_ANCHOR_LINK_RE = re.compile(r"(\]\(#)([^)\s]+)(\))")


def normalize_internal_anchors(source: str, translated: str) -> str:
    """Repoint in-document ``](#frag)`` links at the translated headings.

    Headings are matched by position: the Nth heading of the source maps to the Nth heading
    of the translation. A fragment that does not correspond to any source heading is left
    alone, so hand-written anchors and anchors into other files are never touched.
    """
    src_slugs = [s for _, _, s in headings(source)]
    tgt_slugs = [s for _, _, s in headings(translated)]
    mapping = {
        s: t for s, t in zip(src_slugs, tgt_slugs) if s != t
    }
    if not mapping:
        return translated

    fences = fence_spans(translated)

    def _sub(m: re.Match) -> str:
        if any(bs <= m.start() < be for bs, be in fences):
            return m.group(0)
        return f"{m.group(1)}{mapping.get(m.group(2), m.group(2))}{m.group(3)}"

    return _ANCHOR_LINK_RE.sub(_sub, translated)
