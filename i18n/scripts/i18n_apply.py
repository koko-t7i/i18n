#!/usr/bin/env python3
"""Assemble subagent results into translated files.

For each planned job: merge cache-hit chunks with fresh subagent results, assert the code
placeholders survived, reassemble via ``_job.finish_job``, rewrite relative links for the
target location, and write the file.

This is the only script that writes into the repository.

Exit codes: 0 all files written | 1 one or more files rejected | 2 error
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _adapter as A
import _job
from _paths import add_state_dir_arg, resolve_state_dir, run_main
from _state import State, sha


def collect_chunks(job_blob: dict, results_dir: Path) -> tuple[dict[str, str], list[str]]:
    """Return ``({chunk_id: text}, missing_ids)`` merging reuse cache and subagent results."""
    out = dict(job_blob.get("reused_chunks", {}))
    missing = []
    for ch in job_blob["job"].get("chunks", []):
        cid = ch["id"]
        if cid in out:
            continue
        slug = job_blob["slug"]
        path = results_dir / f"{slug}.{cid.replace(':', '-')}.json"
        if not path.exists():
            missing.append(cid)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        text = data.get("translated_text")
        if not isinstance(text, str) or not text.strip():
            missing.append(cid)
            continue
        out[cid] = text
    return out, missing


def check_placeholders(job_blob: dict, chunks: dict[str, str]) -> list[dict]:
    """Every ``@@CODE_BLOCK_n@@`` token in a chunk's source must survive translation."""
    problems = []
    for ch in job_blob["job"].get("chunks", []):
        cid = ch["id"]
        if cid not in chunks:
            continue
        want = sorted(A.COOP_PLACEHOLDER_RE.findall(ch["source"]))
        got = sorted(A.COOP_PLACEHOLDER_RE.findall(chunks[cid]))
        if want != got:
            problems.append({
                "chunk_id": cid,
                "expected": want,
                "actual": got,
                "message": "code placeholders were altered; the chunk must be retranslated",
            })
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply translated chunks to the repository.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--run", required=True, help="run id from i18n_plan.py")
    ap.add_argument("--dry-run", action="store_true")
    add_state_dir_arg(ap)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    state_dir = resolve_state_dir(root, args.state_dir)
    work = state_dir / "work" / args.run
    if not work.is_dir():
        sys.stderr.write(f"error: no such run: {work}\n")
        return 2

    plan = json.loads((work / "plan.json").read_text(encoding="utf-8"))
    lang = plan["lang"]
    layout = A.Layout(**{k: v for k, v in plan["layout"].items() if k != "confidence"},
                      confidence=plan["layout"]["confidence"])
    state = State.load(root, state_dir)

    written, rejected = [], []

    for job_file in sorted((work / "jobs").glob("*.json")):
        blob = json.loads(job_file.read_text(encoding="utf-8"))
        rel, tgt_rel = blob["file"], blob["target"]

        chunks, missing = collect_chunks(blob, work / "results")
        if missing:
            rejected.append({
                "file": rel, "code": "ASM-MISSING",
                "chunk_ids": missing,
                "message": f"{len(missing)} chunk result(s) missing or empty",
            })
            continue

        problems = check_placeholders(blob, chunks)
        if problems:
            rejected.append({
                "file": rel, "code": "ASM-PLACEHOLDER",
                "chunks": problems,
                "message": "placeholder tokens were altered by the translator",
            })
            continue

        try:
            result = _job.finish_job(
                blob["job"],
                [{"chunk_id": c, "translated_text": t} for c, t in chunks.items()],
            )
        except Exception as exc:  # pragma: no cover - upstream guard
            rejected.append({"file": rel, "code": "ASM-FINISH", "message": str(exc)})
            continue

        content = A.rewrite_links(result["content"], rel, tgt_rel, layout, root)

        rec = {
            "file": rel, "target": tgt_rel,
            "reused": len(blob.get("reused_chunks", {})),
            "fresh": len(chunks) - len(blob.get("reused_chunks", {})),
            "upstream_warnings": result.get("warnings") or [],
        }

        if not args.dry_run:
            out_path = root / tgt_rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            # Both sides are stored: the translation for exact reuse, the source so a
            # later run can fuzzy-match a chunk that changed by a few words.
            cache = {
                sha(ch["source"]): {"src": ch["source"], "tgt": chunks[ch["id"]]}
                for ch in blob["job"]["chunks"]
            }
            state.record(rel, lang, tgt_rel, blob["source_sha"], content, cache,
                         chunker=_job.CHUNKER_VERSION)
        written.append(rec)

    if not args.dry_run and written:
        state.save()

    out = {
        "run_id": args.run,
        "lang": lang,
        "dry_run": args.dry_run,
        "written": written,
        "rejected": rejected,
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for w in written:
            verb = "would write" if args.dry_run else "wrote"
            print(f"  {verb} {w['target']}  (fresh={w['fresh']} reused={w['reused']})")
            for n in w["upstream_warnings"]:
                print(f"      upstream warning: {n}")
        for r in rejected:
            print(f"  REJECTED {r['file']} [{r['code']}] {r['message']}")
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(run_main(main))
