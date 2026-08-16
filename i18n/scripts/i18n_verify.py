#!/usr/bin/env python3
"""Verify translated documents against their sources. This is the blocking gate.

Runs the structural assertions co-op-translator does not make, and optionally its own
``run_review`` freshness/structure pass. Findings carry a severity; any ``error`` fails
the run.

Exit codes: 0 pass (warnings allowed) | 1 blocking findings | 2 error | 3 nothing to verify
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _adapter as A  # noqa: E402
from _state import State, file_sha  # noqa: E402

EXTERNAL = A._EXTERNAL_RE


def _split_links(urls: list[str]) -> tuple[list[str], int]:
    """External URLs (compared verbatim) and the count of internal ones (rewritten by us)."""
    ext = sorted(u for u in urls if EXTERNAL.match(u) and not u.startswith("#"))
    internal = sum(1 for u in urls if not EXTERNAL.match(u))
    return ext, internal


def verify_pair(src_text: str, tgt_text: str, lang: str, rel: str, terms: list) -> list[dict]:
    s = A.inventory(src_text)
    t = A.inventory(tgt_text)
    f: list[dict] = []

    def add(code, sev, msg, **kw):
        f.append({"code": code, "severity": sev, "file": rel, "message": msg, **kw})

    if t["coop_placeholders"]:
        add("X-PLACEHOLDER", "error",
            "co-op placeholder tokens were left unresolved in the output",
            actual=t["coop_placeholders"][:10])

    if s["tokens"] != t["tokens"]:
        add("X-TOKEN", "error", "user placeholder tokens differ",
            expected=s["tokens"], actual=t["tokens"])

    if s["html_tags"] != t["html_tags"]:
        add("X-HTML", "error", "HTML tags differ between source and translation",
            expected=s["html_tags"], actual=t["html_tags"],
            hint="CJK targets: co-op-translator rewrites **bold** to <strong>; "
                 "i18n_apply.py should have repaired this")

    if s["inline_code"] != t["inline_code"]:
        only_s = [c for c in s["inline_code"] if c not in t["inline_code"]]
        only_t = [c for c in t["inline_code"] if c not in s["inline_code"]]
        add("X-INLINE", "error", "inline code spans differ (they must be copied verbatim)",
            expected=only_s[:10], actual=only_t[:10])

    if s["fence_count"] != t["fence_count"]:
        add("X-FENCE", "error", "fenced code block count differs",
            expected=s["fence_count"], actual=t["fence_count"])
    elif s["fence_infos"] != t["fence_infos"]:
        add("X-FENCE", "error", "code fence language tags differ",
            expected=s["fence_infos"], actual=t["fence_infos"])
    elif s["fence_bodies"] != t["fence_bodies"]:
        add("X-FENCE", "error", "code block contents were modified")

    s_ext, s_int = _split_links(s["links"])
    t_ext, t_int = _split_links(t["links"])
    if s_ext != t_ext:
        add("X-LINK", "error", "external link URLs differ",
            expected=s_ext, actual=t_ext)
    if s_int != t_int:
        add("X-LINK", "error", "internal link count differs",
            expected=s_int, actual=t_int)

    if len(s["images"]) != len(t["images"]):
        add("X-IMAGE", "error", "image count differs",
            expected=len(s["images"]), actual=len(t["images"]))

    if s["heading_levels"] != t["heading_levels"]:
        add("X-HEADING", "error", "heading level sequence differs",
            expected=s["heading_levels"], actual=t["heading_levels"])

    slugs = set(t["heading_slugs"])
    for a in t["anchors"]:
        if a and a not in slugs and a in set(s["anchors"]):
            add("X-ANCHOR", "warn", f"internal anchor #{a} does not match any heading in the translation")

    if t["chatter"]:
        add("X-CHATTER", "error", "translation contains model preamble/chatter")

    if A.is_cjk(lang) and A.cjk_ratio(tgt_text) < 0.10:
        add("X-UNTRANSLATED", "warn",
            f"target looks untranslated (CJK ratio {A.cjk_ratio(tgt_text):.2f})")

    f.extend({**g, "file": rel} for g in A.check_glossary(src_text, tgt_text, terms, lang, rel))
    return f


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify translated documents.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--lang", required=True)
    ap.add_argument("--files", nargs="*", default=None, help="limit to these source paths")
    ap.add_argument("--glossary", default=None)
    ap.add_argument("--strict", action="store_true", help="treat warnings as blocking")
    ap.add_argument("--run-review", action="store_true",
                    help="also run co-op-translator's own deterministic review")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    state = State.load(root)
    gpath = Path(args.glossary) if args.glossary else root / ".i18n" / "glossary.json"
    terms = A.load_glossary(gpath)

    pairs = []
    for rel, langs in sorted(state.data.get("files", {}).items()):
        e = langs.get(args.lang)
        if not e:
            continue
        if args.files and rel not in args.files:
            continue
        pairs.append((rel, e["target"]))

    if not pairs:
        msg = "nothing to verify: no recorded translations for %s" % args.lang
        print(json.dumps({"status": "empty", "message": msg}) if args.json else msg)
        return 3

    findings: list[dict] = []
    checked = 0
    for rel, tgt_rel in pairs:
        src, tgt = root / rel, root / tgt_rel
        if not src.exists():
            findings.append({"code": "X-ORPHAN", "severity": "warn", "file": rel,
                             "message": "source file no longer exists; translation is orphaned"})
            continue
        if not tgt.exists():
            findings.append({"code": "X-MISSING", "severity": "error", "file": rel,
                             "message": f"translated file {tgt_rel} is missing"})
            continue
        findings.extend(verify_pair(
            src.read_text(encoding="utf-8"), tgt.read_text(encoding="utf-8"),
            args.lang, rel, terms,
        ))
        checked += 1

    review = None
    if args.run_review:
        try:
            from i18n_plan import load_coop
            coop = load_coop()
            review = coop.run_review(language_codes=args.lang, root_dir=str(root),
                                     markdown=True, notebook=False)
        except SystemExit:
            review = {"ok": None, "error": "co-op-translator unavailable"}
        except Exception as exc:  # pragma: no cover
            review = {"ok": None, "error": str(exc)}

    n_err = sum(1 for f in findings if f["severity"] == "error")
    n_warn = sum(1 for f in findings if f["severity"] == "warn")
    blocking = n_err or (args.strict and n_warn)

    out = {
        "status": "fail" if blocking else "pass",
        "lang": args.lang,
        "checked": checked,
        "counts": {"error": n_err, "warn": n_warn},
        "findings": findings,
        "retry_files": sorted({f["file"] for f in findings if f["severity"] == "error"}),
        "coop_review": review,
    }

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"checked {checked} file(s) for {args.lang}: {n_err} error(s), {n_warn} warning(s)")
        for f in findings:
            extra = ""
            if "expected" in f:
                extra = f"\n        expected={f['expected']!r}\n        actual  ={f['actual']!r}"
            print(f"  {f['severity'].upper():5s} {f['code']:16s} {f['file']}: {f['message']}{extra}")
        if review is not None:
            print(f"  co-op review ok={review.get('ok')}")
            if review.get("stdout"):
                for line in str(review["stdout"]).strip().splitlines():
                    print(f"      {line}")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
