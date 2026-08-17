#!/usr/bin/env python3
"""Revision and proofreading -- the two passes that judge what structure cannot.

``verify`` asserts that the translation is shaped like its source. Nothing in it asserts
that the translation *means* what the source means, or that it reads like the target
language. ISO 17100 splits exactly those into two steps, and keeps them apart on purpose:

    revision    bilingual, source beside translation -- accuracy, terminology, audience
    proofread   monolingual, translation alone       -- fluency, style, locale

The separation is the method. A reviser holding the source accepts translationese because
it corresponds; a proofreader who cannot see the source notices. So the proofreading task
files carry no source text, and this script will not put one there.

    i18n_review.py plan    --root . --lang zh-CN --mode revision
    i18n_review.py collect --root . --run <id>

``collect`` emits findings in the same shape ``verify --json`` produces, so the existing
``i18n_plan.py --repair`` consumes them unchanged.

Exit codes: 0 ok | 1 blocking findings | 2 error | 3 nothing to review
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _adapter as A
import _job
from _paths import add_state_dir_arg, rel_state_dir, resolve_state_dir, run_main
from _state import State

MODES = ("revision", "proofread")

#: MQM dimensions this skill accepts, split by which pass may report them. A reviser
#: reporting fluency and a proofreader reporting accuracy both mean the pass was given the
#: wrong prompt, so the split is enforced rather than trusted.
DIMENSIONS = {
    "revision": {"accuracy", "terminology", "audience"},
    "proofread": {"fluency", "style", "locale"},
}

SEVERITIES = ("minor", "major", "critical")

#: MQM severity -> this skill's two-level scheme. Proofreading overrides all of it to warn:
#: phrasing is a judgement call, and gating on judgement calls never converges.
_BLOCKING = {"critical": "error", "major": "error", "minor": "warn"}

_PROMPTS = Path(__file__).resolve().parent.parent / "assets" / "prompts"


def slug_for(rel: str, lang: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]+", "-", f"{rel}-{lang}").strip("-").lower()


def build_prompt(mode: str, lang: str, source: str, translation: str,
                 terms: list, style: dict, result_path: str) -> str:
    """Render the mode's prompt template. Revision sees both sides; proofreading does not."""
    template = (_PROMPTS / f"{mode}.md").read_text(encoding="utf-8")
    body = template.split("---", 1)[1].strip() if "---" in template else template
    out = (body
           .replace("[language_name]", _job.language_name(lang))
           .replace("[translated text]", translation)
           .replace("[result_path]", result_path))
    if mode == "revision":
        out = out.replace("[source text]", source)
        blocks = A.glossary_prompt(terms, lang) + A.style_prompt(style, lang)
        out = out.replace("[terminology and style blocks, if any]", blocks.strip())
    else:
        out = out.replace("[style block, if any]", A.style_prompt(style, lang).strip())
    return out


def cmd_plan(args) -> int:
    root = Path(args.root).resolve()
    state_dir = resolve_state_dir(root, args.state_dir)
    state = State.load(root, state_dir)
    terms = A.load_glossary(state_dir / "glossary.json")
    style = A.load_style(state_dir / "style.json")

    pairs = []
    for rel, langs in sorted(state.data.get("files", {}).items()):
        e = langs.get(args.lang)
        if not e:
            continue
        if args.files and rel not in args.files:
            continue
        pairs.append((rel, e["target"]))

    if not pairs:
        msg = f"nothing to review: no recorded translations for {args.lang}"
        print(json.dumps({"status": "empty", "message": msg}) if args.json else msg)
        return 3

    run_id = args.run or time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    work = state_dir / "work" / run_id
    (work / "review").mkdir(parents=True, exist_ok=True)
    (work / "review-results").mkdir(parents=True, exist_ok=True)

    tasks = []
    for rel, tgt_rel in pairs:
        src, tgt = root / rel, root / tgt_rel
        if not src.exists() or not tgt.exists():
            continue
        translation = tgt.read_text(encoding="utf-8")
        source = src.read_text(encoding="utf-8") if args.mode == "revision" else ""
        task_id = f"{slug_for(rel, args.lang)}.{args.mode}"
        result_path = (f"{rel_state_dir(root, state_dir)}/work/{run_id}"
                       f"/review-results/{task_id}.json")

        payload = {
            "task_id": task_id,
            "mode": args.mode,
            "file": rel,
            "target": tgt_rel,
            "lang": args.lang,
            "translation": translation,
            "prompt": build_prompt(args.mode, args.lang, source, translation,
                                   A.match_terms(source or translation, terms, args.lang, rel),
                                   style, result_path),
            "result_path": result_path,
        }
        # Revision alone gets the source. Withholding it is what makes the monolingual
        # pass able to see translationese, so it is a property of the file, not the prompt.
        if args.mode == "revision":
            payload["source"] = source

        (work / "review" / f"{task_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tasks.append({"task_id": task_id, "file": rel, "target": tgt_rel})

    out = {
        "run_id": run_id,
        "mode": args.mode,
        "lang": args.lang,
        "work_dir": f"{rel_state_dir(root, state_dir)}/work/{run_id}",
        "tasks": tasks,
        "task_count": len(tasks),
    }
    (work / f"review-plan-{args.mode}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"run {run_id}  mode={args.mode}")
        for t in tasks:
            print(f"  {t['file']} -> {t['target']}")
        print(f"  {len(tasks)} review task(s) in {out['work_dir']}/review/")
    return 0


def normalise(raw: dict, mode: str, rel: str) -> tuple[list[dict], list[str]]:
    """Findings in ``verify``'s shape, plus complaints about ones that were discarded."""
    out, rejected = [], []
    for item in raw.get("findings", []) or []:
        dim = str(item.get("dimension", "")).lower()
        sev = str(item.get("severity", "")).lower()
        if dim not in DIMENSIONS[mode]:
            rejected.append(f"{rel}: {mode} may not report dimension {dim!r}")
            continue
        if sev not in SEVERITIES:
            rejected.append(f"{rel}: unknown severity {sev!r}")
            continue
        # Proofreading is advisory in full: see the note on _BLOCKING.
        severity = "warn" if mode == "proofread" else _BLOCKING[sev]
        out.append({
            "code": "X-REVISION" if mode == "revision" else "X-PROOF",
            "severity": severity,
            "file": rel,
            "message": f"{dim}/{item.get('subtype', '?')}: {item.get('note', '')}".strip(),
            "dimension": dim,
            "subtype": item.get("subtype"),
            "mqm_severity": sev,
            "span": item.get("span"),
            "suggestion": item.get("suggestion"),
        })
    return out, rejected


def cmd_collect(args) -> int:
    root = Path(args.root).resolve()
    state_dir = resolve_state_dir(root, args.state_dir)
    work = state_dir / "work" / args.run
    if not work.is_dir():
        sys.stderr.write(f"error: no such run: {work}\n")
        return 2

    tasks = {}
    for p in sorted((work / "review").glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        tasks[t["task_id"]] = t
    if not tasks:
        sys.stderr.write(f"error: no review tasks in {work}/review/\n")
        return 2

    findings, rejected, missing = [], [], []
    for task_id, t in sorted(tasks.items()):
        rf = work / "review-results" / f"{task_id}.json"
        if not rf.exists():
            missing.append(task_id)
            continue
        try:
            raw = json.loads(rf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            rejected.append(f"{task_id}: result is not valid JSON ({exc})")
            continue
        got, bad = normalise(raw, t["mode"], t["file"])
        findings.extend(got)
        rejected.extend(bad)

    n_err = sum(1 for f in findings if f["severity"] == "error")
    n_warn = sum(1 for f in findings if f["severity"] == "warn")
    out = {
        "status": "fail" if n_err else "pass",
        "run_id": args.run,
        "reviewed": len(tasks) - len(missing),
        "missing_results": missing,
        "rejected": rejected,
        "counts": {"error": n_err, "warn": n_warn},
        "findings": findings,
    }
    (work / "review.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"  {f['severity'].upper():5s} {f['code']:11s} {f['file']}: {f['message']}")
        for r in rejected:
            print(f"  discarded  {r}")
        for m in missing:
            print(f"  no result  {m}")
        print(f"  {n_err} blocking, {n_warn} advisory -> "
              f"{rel_state_dir(root, state_dir)}/work/{args.run}/review.json")
    if missing:
        return 2
    return 1 if n_err else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Revise and proofread translations.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="emit review tasks for subagents")
    p.add_argument("--root", default=".")
    p.add_argument("--lang", required=True)
    p.add_argument("--mode", choices=MODES, default="revision")
    p.add_argument("--files", nargs="*", default=None, help="limit to these source paths")
    p.add_argument("--run", default=None, help="reuse an existing run id")
    add_state_dir_arg(p)
    p.add_argument("--json", action="store_true")

    c = sub.add_parser("collect", help="turn review results into verify-shaped findings")
    c.add_argument("--root", default=".")
    c.add_argument("--run", required=True)
    add_state_dir_arg(c)
    c.add_argument("--json", action="store_true")

    args = ap.parse_args()
    return {"plan": cmd_plan, "collect": cmd_collect}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(run_main(main))
