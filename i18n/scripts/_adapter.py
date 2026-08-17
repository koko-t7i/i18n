"""Adapter layer for the i18n skill.

Repository-level policy, as opposed to the Markdown mechanics in ``_md`` and ``_job``:

* layout detection / target-path resolution
* internal-link rewriting for the resolved layout
* glossary matching and violation detection
* the structural inventories the verifier compares between source and target
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _md  # noqa: E402

# --------------------------------------------------------------------------------------
# language codes
# --------------------------------------------------------------------------------------

CJK_LANGS = {"zh", "ja", "ko"}

#: Extra tokens that may stand in for a language in a filename or directory name.
_LANG_ALIASES = {
    "zh-CN": ["zh-CN", "zh_CN", "zh-Hans", "zh-hans", "zh", "cn", "CN", "chs"],
    "zh-TW": ["zh-TW", "zh_TW", "zh-Hant", "zh-hant", "tw", "TW", "cht"],
    "ja": ["ja", "jp", "JP", "ja-JP", "ja_JP"],
    "ko": ["ko", "kr", "KR", "ko-KR", "ko_KR"],
}


def lang_aliases(lang: str) -> list[str]:
    """Return the plausible filename/directory tokens for ``lang``, most specific first."""
    if lang in _LANG_ALIASES:
        return list(_LANG_ALIASES[lang])
    out = [lang]
    base = lang.split("-")[0].split("_")[0]
    if base != lang:
        out.append(base)
        out.append(lang.replace("-", "_"))
    return out


def is_cjk(lang: str) -> bool:
    return lang.split("-")[0].split("_")[0].lower() in CJK_LANGS


# --------------------------------------------------------------------------------------
# code masking -- every text transform below must avoid touching code
# --------------------------------------------------------------------------------------

#: Delegated to _md so every consumer -- the verifier's inventory, glossary matching, link
#: rewriting -- gets CommonMark-accurate fence boundaries, including fences nested inside
#: blockquotes and list items, which the old regex sliced incorrectly.
mask_code = _md.mask_code
unmask_code = _md.unmask_code
slugify = _md.slugify


_QUOTE_PREFIX_RE = re.compile(r"^[ \t]*(?:>[ \t]?)+")
_FENCE_OPEN_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*(?P<info>.*?)[ \t]*$")


def _fence_parts(text: str) -> list[tuple[str, str]]:
    """``(info_string, body)`` per fenced block, in document order.

    The info string is read after stripping any blockquote prefix, so a fence inside a
    blockquote reports ``bash`` rather than ``> ```bash``. The body keeps its prefix, so a
    translation that drops the surrounding blockquote still shows up as a difference.
    """
    out = []
    for s, e in _md.fence_spans(text):
        lines = text[s:e].split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        opener = _QUOTE_PREFIX_RE.sub("", lines[0]) if lines else ""
        m = _FENCE_OPEN_RE.match(opener)
        info = m.group("info") if m else ""
        body_lines = lines[1:]
        if body_lines and _FENCE_OPEN_RE.match(_QUOTE_PREFIX_RE.sub("", body_lines[-1])):
            body_lines.pop()  # closing fence
        out.append((info, "\n".join(body_lines)))
    return out


# --------------------------------------------------------------------------------------
# layout detection
# --------------------------------------------------------------------------------------

#: Directory names that conventionally hold a per-language tree.
_PARALLEL_ROOTS = ["translations", "i18n", "docs", "content", "locales"]

#: Sibling-suffix shapes, ordered by how strongly they identify a translation.
_SIBLING_PATTERNS = [
    "{stem}.{lang}{ext}",  # README.zh-CN.md
    "{stem}_{lang}{ext}",  # README_CN.md
    "{stem}-{lang}{ext}",  # README-zh.md
]

_SKIP_DIRS = {
    ".git", ".claude", ".codex", ".i18n", "node_modules", "__pycache__", ".venv", "venv",
    "vendor", ".worktrees", "dist", "build", ".cache",
}


@dataclass
class Layout:
    """How translated files are laid out for one language."""

    style: str  # 'sibling' | 'parallel'
    pattern: str  # sibling: '{stem}.{lang}{ext}' | parallel: 'docs/{lang}/{relpath}'
    lang_token: str  # the exact token used in paths, e.g. 'zh-CN' or 'CN'
    confidence: float
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "style": self.style,
            "pattern": self.pattern,
            "lang_token": self.lang_token,
            "confidence": round(self.confidence, 2),
            "evidence": self.evidence[:10],
        }


def iter_markdown(root: Path, patterns: list[str] | None = None) -> list[Path]:
    """All Markdown files under ``root``, excluding vendored/build dirs."""
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        if p.suffix.lower() not in (".md", ".mdx", ".markdown"):
            continue
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        rel = p.relative_to(root).as_posix()
        if patterns and not any(fnmatch.fnmatch(rel, g) for g in patterns):
            continue
        out.append(p)
    return out


def detect_layout(root: Path, lang: str) -> Layout:
    """Infer where translations for ``lang`` should live by looking at what already exists.

    Falls back to sibling-suffix, which is what every repo in this collection uses today.
    """
    root = Path(root)
    tokens = lang_aliases(lang)
    files = iter_markdown(root)
    rels = [f.relative_to(root).as_posix() for f in files]

    # -- parallel-directory evidence -------------------------------------------------
    par_hits: dict[tuple[str, str], list[str]] = {}
    for rel in rels:
        parts = rel.split("/")
        for i, part in enumerate(parts[:-1]):
            if part not in tokens:
                continue
            prefix = "/".join(parts[:i]) if i else ""
            par_hits.setdefault((prefix, part), []).append(rel)

    # -- sibling-suffix evidence -----------------------------------------------------
    relset = set(rels)
    sib_hits: dict[tuple[str, str], list[str]] = {}
    for rel in rels:
        p = Path(rel)
        for tok in tokens:
            for pat in _SIBLING_PATTERNS:
                sep = pat.split("{stem}")[1].split("{lang}")[0]
                suffix = f"{sep}{tok}{p.suffix}"
                if not rel.endswith(suffix):
                    continue
                base = rel[: -len(suffix)] + p.suffix
                if base in relset:  # only counts if the source file is right there
                    sib_hits.setdefault((pat, tok), []).append(rel)

    best_par = max(par_hits.items(), key=lambda kv: len(kv[1]), default=None)
    best_sib = max(sib_hits.items(), key=lambda kv: len(kv[1]), default=None)
    n_par = len(best_par[1]) if best_par else 0
    n_sib = len(best_sib[1]) if best_sib else 0

    if n_par or n_sib:
        total = n_par + n_sib
        if n_par >= n_sib:
            (prefix, tok), ev = best_par
            pattern = f"{prefix}/{{lang}}/{{relpath}}" if prefix else "{lang}/{relpath}"
            return Layout("parallel", pattern, tok, n_par / total, sorted(ev))
        (pat, tok), ev = best_sib
        return Layout("sibling", pat, tok, n_sib / total, sorted(ev))

    # -- no evidence: default ---------------------------------------------------------
    return Layout("sibling", _SIBLING_PATTERNS[0], lang, 0.0, [])


def is_translation_artifact(rel: str, lang: str, layout: Layout) -> bool:
    """True if ``rel`` is itself a translated file (so it must not be a translation source)."""
    p = Path(rel)
    for tok in lang_aliases(lang) + [layout.lang_token]:
        for pat in _SIBLING_PATTERNS:
            sep = pat.split("{stem}")[1].split("{lang}")[0]
            if rel.endswith(f"{sep}{tok}{p.suffix}"):
                return True
        if tok in p.parts[:-1]:
            return True
    return False


def _sibling_target(src_rel: str, pattern: str, lang_token: str) -> str:
    p = Path(src_rel)
    stem = (p.parent / p.stem).as_posix() if p.parent.as_posix() != "." else p.stem
    return pattern.format(stem=stem, lang=lang_token, ext=p.suffix)


def resolve_target(src_rel: str, layout: Layout) -> str:
    """Map a source path to its translated counterpart under ``layout``.

    A parallel-directory layout only governs files that actually live under its prefix.
    Anything outside it (a root ``README.md`` next to a ``docs/<lang>/`` tree) falls back
    to a sibling suffix rather than being relocated into the docs tree.
    """
    if layout.style == "sibling":
        return _sibling_target(src_rel, layout.pattern, layout.lang_token)
    prefix = layout.pattern.split("{lang}")[0].rstrip("/")
    if prefix and not src_rel.startswith(prefix + "/"):
        return _sibling_target(src_rel, _SIBLING_PATTERNS[0], layout.lang_token)
    rel = src_rel[len(prefix) + 1:] if prefix else src_rel
    return layout.pattern.format(lang=layout.lang_token, relpath=rel)


# --------------------------------------------------------------------------------------
# link rewriting
# --------------------------------------------------------------------------------------

_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)(\s+\"[^\"]*\")?\)")
_REFDEF_RE = re.compile(r"^([ ]{0,3})\[([^\]]+)\]:[ \t]*(\S+)(.*)$", re.MULTILINE)
_EXTERNAL_RE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//|#|mailto:)")


def _rewrite_one(url: str, src_rel: str, tgt_rel: str, layout: Layout, root: Path) -> str:
    """Rewrite a single relative link so it still resolves from the translated file."""
    if _EXTERNAL_RE.match(url):
        return url
    frag = ""
    if "#" in url:
        url, frag = url.split("#", 1)
        frag = "#" + frag
    if not url:
        return frag
    if Path(url).suffix.lower() not in (".md", ".mdx", ".markdown"):
        # Non-Markdown asset: re-point at the same file from the new location.
        target_abs = (Path(src_rel).parent / url).as_posix()
        new = _relpath(target_abs, Path(tgt_rel).parent.as_posix())
        return new + frag
    # Markdown: prefer the translated counterpart when it is planned to exist.
    linked_src = _normpath((Path(src_rel).parent / url).as_posix())
    linked_tgt = resolve_target(linked_src, layout)
    if not (root / linked_src).exists():
        linked_tgt = linked_src  # unknown file, keep pointing at the original
    return _relpath(linked_tgt, Path(tgt_rel).parent.as_posix()) + frag


def _normpath(p: str) -> str:
    parts: list[str] = []
    for seg in p.split("/"):
        if seg in ("", "."):
            continue
        if seg == ".." and parts and parts[-1] != "..":
            parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


def _relpath(target: str, start: str) -> str:
    t = _normpath(target).split("/")
    s = [x for x in _normpath(start).split("/") if x]
    i = 0
    while i < len(s) and i < len(t) - 1 and s[i] == t[i]:
        i += 1
    up = [".."] * (len(s) - i)
    return "/".join(up + t[i:]) or "."


def rewrite_links(content: str, src_rel: str, tgt_rel: str, layout: Layout, root: Path) -> str:
    """Rewrite relative links in ``content`` for a file moving from ``src_rel`` to ``tgt_rel``."""
    if _normpath(str(Path(src_rel).parent)) == _normpath(str(Path(tgt_rel).parent)):
        return content  # same directory, every relative link still resolves
    masked, chunks = mask_code(content)

    def _link(m: re.Match) -> str:
        bang, text, url, title = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        return f"{bang}[{text}]({_rewrite_one(url, src_rel, tgt_rel, layout, root)}{title})"

    masked = _LINK_RE.sub(_link, masked)

    def _refdef(m: re.Match) -> str:
        indent, label, url, rest = m.groups()
        return f"{indent}[{label}]: {_rewrite_one(url, src_rel, tgt_rel, layout, root)}{rest}"

    masked = _REFDEF_RE.sub(_refdef, masked)
    return unmask_code(masked, chunks)




# --------------------------------------------------------------------------------------
# structural inventories (used by the verifier)
# --------------------------------------------------------------------------------------

COOP_PLACEHOLDER_RE = re.compile(r"@@(?:CODE_BLOCK|INLINE_CODE|LINE|COOP_CHUNK_START|COOP_CHUNK_END)[^@]*@@")
USER_TOKEN_RE = re.compile(
    r"\{\{[^{}\n]+\}\}"          # {{var}}
    r"|\{[A-Za-z_][\w.]*\}"      # {count}
    r"|\$\{[^}\n]+\}"            # ${VAR}
    r"|%\([^)\n]+\)[sdfr]"       # %(name)s
    r"|%[sdfr]"                  # %s
    r"|<\d+>|</\d+>"             # <0></0>
)
_HTML_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)\b[^>]*>")
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_CHATTER_RE = re.compile(
    r"^\s*(?:here(?:'s| is) the translat|below is the translat|translated (?:text|version|by)"
    r"|以下是翻译|以下为翻译|翻译如下|译文如下)",
    re.I,
)



def inventory(text: str) -> dict:
    """Structural fingerprint of a Markdown document, comparable between source and target."""
    masked, code_chunks = mask_code(text)
    fences = _fence_parts(text)
    headings = _HEADING_RE.findall(masked)
    links, images = [], []
    for m in _LINK_RE.finditer(masked):
        (images if m.group(1) else links).append(m.group(3))
    return {
        # Scanned on the masked text: a document that *documents* these tokens writes them
        # inside backticks, and that is not a failed restoration.
        "coop_placeholders": sorted(COOP_PLACEHOLDER_RE.findall(masked)),
        "tokens": sorted(USER_TOKEN_RE.findall(masked)),
        "html_tags": sorted(f"{'/' if c else ''}{n.lower()}" for c, n in _HTML_TAG_RE.findall(masked)),
        "fence_infos": [i for i, _ in fences],
        "fence_bodies": [b for _, b in fences],
        "fence_count": len(fences),
        # Inline code bodies are compared verbatim: a translator that renders `{count}` as
        # `{数量}`, or translates a flag name, is caught here and nowhere else.
        "inline_code": sorted(c for c in code_chunks if not _md.is_fence(c)),
        "inline_code_count": sum(1 for c in code_chunks if not _md.is_fence(c)),
        "links": sorted(links),
        "images": sorted(images),
        "heading_levels": [len(h) for h, _ in headings],
        "heading_slugs": [slugify(t) for _, t in headings],
        "anchors": sorted(
            u.split("#", 1)[1] for u in links + images if u.startswith("#")
        ),
        "chatter": bool(_CHATTER_RE.search(text)),
    }


def cjk_ratio(text: str) -> float:
    """Share of CJK ideographs/kana/hangul among the letters in ``text``."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    cjk = sum(1 for c in letters if "぀" <= c <= "ヿ" or "㐀" <= c <= "鿿" or "가" <= c <= "힯")
    return cjk / len(letters)


# --------------------------------------------------------------------------------------
# glossary
# --------------------------------------------------------------------------------------

@dataclass
class Term:
    id: str
    source: str
    policy: str = "translate"
    aliases: list[str] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)
    translations: dict = field(default_factory=dict)
    case_sensitive: bool = False
    severity: str = "error"
    notes: str = ""

    def surface_forms(self) -> list[str]:
        return sorted({self.source, *self.aliases}, key=len, reverse=True)

    def target_text(self, lang: str) -> str | None:
        return (self.translations.get(lang) or {}).get("text")

    def forbidden(self, lang: str) -> list[str]:
        return (self.translations.get(lang) or {}).get("forbid", [])


def load_glossary(path: Path | str | None) -> list[Term]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for t in data.get("terms", []):
        out.append(
            Term(
                id=t.get("id") or t["source"],
                source=t["source"],
                policy=t.get("policy", "translate"),
                aliases=t.get("aliases", []),
                scope=t.get("scope", []),
                translations=t.get("translations", {}),
                case_sensitive=t.get("case_sensitive", False),
                severity=t.get("severity", "error"),
                notes=t.get("notes", ""),
            )
        )
    return out


def _term_pattern(form: str, case_sensitive: bool) -> re.Pattern:
    esc = re.escape(form)
    # \b only means anything when the term starts/ends with a word character.
    left = r"\b" if form[:1].isalnum() else ""
    right = r"\b" if form[-1:].isalnum() else ""
    return re.compile(f"{left}{esc}{right}", 0 if case_sensitive else re.I)


def match_terms(text: str, terms: list[Term], lang: str, rel: str = "") -> list[Term]:
    """The subset of ``terms`` that actually occur in ``text`` (and are in scope for ``rel``)."""
    masked, _ = mask_code(text)
    hits = []
    for t in terms:
        if t.scope and rel and not any(fnmatch.fnmatch(rel, g) for g in t.scope):
            continue
        if t.policy == "translate" and not t.target_text(lang):
            continue
        if any(_term_pattern(f, t.case_sensitive).search(masked) for f in t.surface_forms()):
            hits.append(t)
    return hits


def glossary_prompt(terms: list[Term], lang: str) -> str:
    """Compact instruction block appended to a chunk prompt."""
    if not terms:
        return ""
    lines = ["", "TERMINOLOGY (must be respected exactly):"]
    for t in terms:
        if t.policy == "do_not_translate":
            lines.append(f"- {t.source} -> keep in English, do NOT translate")
        elif t.policy == "first_use_gloss":
            tgt = t.target_text(lang) or ""
            lines.append(f"- {t.source} -> {tgt} (first occurrence: `{tgt} ({t.source})`)")
        else:
            tgt = t.target_text(lang)
            bad = t.forbidden(lang)
            line = f"- {t.source} -> {tgt}"
            if bad:
                line += f"  (never use: {', '.join(bad)})"
            lines.append(line)
        if t.notes:
            lines[-1] += f"  // {t.notes}"
    return "\n".join(lines) + "\n"


def check_glossary(source: str, target: str, terms: list[Term], lang: str, rel: str = "") -> list[dict]:
    """Glossary violations for one translated document."""
    hits = match_terms(source, terms, lang, rel)
    tgt_masked, _ = mask_code(target)
    findings = []
    for t in hits:
        if t.policy == "do_not_translate":
            if not any(_term_pattern(f, t.case_sensitive).search(tgt_masked) for f in t.surface_forms()):
                findings.append({
                    "code": "X-GLOSSARY", "severity": t.severity, "term": t.source,
                    "message": f"do-not-translate term {t.source!r} is missing from the translation",
                })
            continue
        want = t.target_text(lang)
        if want and want not in tgt_masked:
            findings.append({
                "code": "X-GLOSSARY", "severity": t.severity, "term": t.source,
                "message": f"expected translation {want!r} for {t.source!r} not found",
            })
        for bad in t.forbidden(lang):
            if bad in tgt_masked:
                findings.append({
                    "code": "X-GLOSSARY", "severity": "warn", "term": t.source,
                    "message": f"forbidden rendering {bad!r} used for {t.source!r}",
                })
    return findings
