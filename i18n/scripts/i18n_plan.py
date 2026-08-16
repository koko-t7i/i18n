#!/usr/bin/env python3
"""Plan a translation run: scan, detect layout, diff against state, emit subagent tasks.

Writes ``.i18n/work/<run_id>/`` containing:

    jobs/<slug>.json      the co-op-translator job object, plus any cache-hit chunks
    tasks/<task_id>.json  one file per chunk that actually needs a subagent
    plan.json             the summary this script prints

This script never writes into the repository itself -- that is ``i18n_apply.py``'s job.

Exit codes: 0 planned (possibly zero tasks) | 1 conflicts need a decision | 2 error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _adapter as A  # noqa: E402
from _state import State, sha  # noqa: E402


def load_coop():
    """Import co-op-translator's agent-assisted API, with an actionable error if absent."""
    try:
        from co_op_translator.mcp import server  # type: ignore
        return server
    except ImportError as exc:  # pragma: no cover - environment guard
        sys.stderr.write(
            "error: co-op-translator is not importable (%s).\n"
            "Run this script through the wrapper, which supplies the vendored copy:\n"
            "  uv run --python 3.12 --prerelease=allow \\\n"
            "      --with <skill>/../vendor/co-op-translator python %s ...\n"
            "Or ensure the submodule is checked out: git submodule update --init --depth 1\n"
            % (exc, Path(__file__).name)
        )
        raise SystemExit(2)


def slugify_path(rel: str, lang: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", f"{rel}-{lang}").strip("-").lower()


def main() -> int:
    ap = argparse.ArgumentParser(description="Plan an i18n translation run.")
    ap.add_argument("--root", default=".", help="repository root")
    ap.add_argument("--lang", required=False, help="target language, e.g. zh-CN")
    ap.add_argument("--paths", nargs="*", default=None, help="glob(s) limiting the sources")
    ap.add_argument("--exclude", nargs="*", default=[], help="glob(s) to skip")
    ap.add_argument("--layout", choices=["auto", "sibling", "parallel"], default="auto")
    ap.add_argument("--layout-pattern", default=None, help="override the layout pattern")
    ap.add_argument("--detect-layout-only", action="store_true")
    ap.add_argument("--all", action="store_true", help="ignore the cache; re-translate everything")
    ap.add_argument("--force", action="store_true", help="overwrite human-edited translations")
    ap.add_argument("--glossary", default=None, help="path to glossary.json (default .i18n/glossary.json)")
    ap.add_argument("--max-tasks", type=int, default=40)
    ap.add_argument("--repair", default=None, help="verify.json whose failures should be re-planned")
    ap.add_argument("--json", action="store_true", help="emit plan.json on stdout")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.stderr.write(f"error: {root} is not a directory\n")
        return 2

    # ---- layout -------------------------------------------------------------------
    if not args.lang:
        sys.stderr.write("error: --lang is required\n")
        return 2
    layout = A.detect_layout(root, args.lang)
    if args.layout != "auto":
        layout = A.Layout(
            style=args.layout,
            pattern=args.layout_pattern
            or ("{stem}.{lang}{ext}" if args.layout == "sibling" else "docs/{lang}/{relpath}"),
            lang_token=layout.lang_token if layout.confidence else args.lang,
            confidence=1.0,
            evidence=["explicit --layout"],
        )
    elif args.layout_pattern:
        layout.pattern = args.layout_pattern
        layout.confidence = 1.0

    if args.detect_layout_only:
        out = {"layout": layout.to_dict(), "root": str(root), "lang": args.lang}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    # ---- sources ------------------------------------------------------------------
    repair_files: set[str] | None = None
    if args.repair:
        rep = json.loads(Path(args.repair).read_text(encoding="utf-8"))
        repair_files = {f["file"] for f in rep.get("findings", []) if f.get("severity") == "error"}
        if not repair_files:
            sys.stderr.write("nothing to repair: no blocking findings in %s\n" % args.repair)
            return 0

    sources: list[str] = []
    for p in A.iter_markdown(root, args.paths):
        rel = p.relative_to(root).as_posix()
        if any(re.fullmatch(g.replace("*", ".*"), rel) for g in args.exclude):
            continue
        if A.is_translation_artifact(rel, args.lang, layout):
            continue
        if repair_files is not None and rel not in repair_files:
            continue
        sources.append(rel)

    state = State.load(root)
    glossary_path = Path(args.glossary) if args.glossary else root / ".i18n" / "glossary.json"
    terms = A.load_glossary(glossary_path)

    run_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    work = root / ".i18n" / "work" / run_id
    (work / "jobs").mkdir(parents=True, exist_ok=True)
    (work / "tasks").mkdir(parents=True, exist_ok=True)
    (work / "results").mkdir(parents=True, exist_ok=True)

    coop = load_coop()

    files_out, conflicts, tasks_written = [], [], 0
    skipped_by_cap = 0

    for rel in sources:
        abs_src = root / rel
        text = abs_src.read_text(encoding="utf-8")
        src_sha = sha(text)
        tgt_rel = A.resolve_target(rel, layout)
        status = state.status(rel, args.lang, src_sha, root / tgt_rel)

        if status == "edited" and not args.force:
            conflicts.append({
                "file": rel, "target": tgt_rel, "reason": "translation was edited by hand",
                "hint": "re-run with --force to overwrite, or leave it and translate other files",
            })
            continue
        if status == "ok" and not args.all and repair_files is None:
            files_out.append({"file": rel, "target": tgt_rel, "status": "up-to-date", "tasks": 0})
            continue

        job = coop.start_markdown_agent_translation(
            document=text, language_code=args.lang, source_path=rel
        )
        cache = {} if (args.all or repair_files is not None) else dict(state.chunk_cache(rel, args.lang))

        slug = slugify_path(rel, args.lang)
        reused, todo = {}, []
        for ch in job.get("chunks", []):
            csha = sha(ch["source"])
            if csha in cache:
                reused[ch["id"]] = cache[csha]
                continue
            todo.append((ch, csha))

        for ch, csha in todo:
            if tasks_written >= args.max_tasks:
                skipped_by_cap += 1
                continue
            hits = A.match_terms(ch["source"], terms, args.lang, rel)
            task_id = f"{slug}.{ch['id'].replace(':', '-')}"
            payload = {
                "task_id": task_id,
                "job_ref": slug,
                "file": rel,
                "target": tgt_rel,
                "lang": args.lang,
                "chunk_id": ch["id"],
                "kind": ch.get("kind"),
                "source_sha": csha,
                "source": ch["source"],
                "prompt": ch["prompt"] + A.glossary_prompt(hits, args.lang),
                "instructions": ch.get("instructions", ""),
                "result_path": f".i18n/work/{run_id}/results/{task_id}.json",
            }
            (work / "tasks" / f"{task_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            tasks_written += 1

        (work / "jobs" / f"{slug}.json").write_text(
            json.dumps(
                {
                    "slug": slug, "file": rel, "target": tgt_rel, "lang": args.lang,
                    "source_sha": src_sha, "layout": layout.to_dict(),
                    "reused_chunks": reused, "job": job,
                },
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
        files_out.append({
            "file": rel, "target": tgt_rel, "status": status,
            "chunks": len(job.get("chunks", [])), "reused": len(reused),
            "tasks": len(todo), "slug": slug,
        })

    plan = {
        "run_id": run_id,
        "root": str(root),
        "lang": args.lang,
        "layout": layout.to_dict(),
        "glossary": str(glossary_path) if terms else None,
        "glossary_terms": len(terms),
        "work_dir": f".i18n/work/{run_id}",
        "files": files_out,
        "task_count": tasks_written,
        "conflicts": conflicts,
        "truncated_tasks": skipped_by_cap,
    }
    (work / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(f"run {run_id}  layout={layout.style}:{layout.pattern} (conf {layout.confidence:.2f})")
        for f in files_out:
            print(f"  {f['status']:11s} {f['file']} -> {f['target']}"
                  f"  tasks={f.get('tasks', 0)} reused={f.get('reused', 0)}")
        print(f"  {tasks_written} task(s) in {plan['work_dir']}/tasks/")
        if skipped_by_cap:
            print(f"  WARNING: {skipped_by_cap} chunk(s) dropped by --max-tasks {args.max_tasks}")
        for c in conflicts:
            print(f"  CONFLICT {c['file']}: {c['reason']}")

    if skipped_by_cap:
        sys.stderr.write(
            f"warning: {skipped_by_cap} chunk(s) exceeded --max-tasks and were not planned; "
            f"re-run after applying this batch\n"
        )
    return 1 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
