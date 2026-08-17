#!/usr/bin/env python3
"""Translate and verify key/value resource files: JSON, YAML, .properties, PO.

Unlike Markdown, these need no chunking and no upstream help -- the unit is a key, the
structural contract is "the key set never changes", and everything else is placeholder
preservation. So this path needs no Markdown parsing at all.

    i18n_resource.py plan   --root . --lang zh-CN --file locales/en.json
    i18n_resource.py apply  --root . --run <id>
    i18n_resource.py verify --root . --lang zh-CN --file locales/en.json

Exit codes: 0 ok | 1 blocking findings | 2 error
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
from _paths import (  # noqa: E402
    add_state_dir_arg, rel_state_dir, resolve_state_dir, run_main, warn_if_ignored,
)
from _state import State, sha  # noqa: E402

BATCH_KEYS = 60

# --------------------------------------------------------------------------------------
# format handling
# --------------------------------------------------------------------------------------

_PROP_RE = re.compile(r"^([^#!=:\s][^=:]*?)\s*[=:]\s*(.*)$")


def detect_format(path: Path) -> str:
    s = path.suffix.lower()
    return {
        ".json": "json", ".yaml": "yaml", ".yml": "yaml",
        ".properties": "properties", ".po": "po", ".pot": "po",
    }.get(s, "")


def flatten(obj, prefix: str = "") -> dict[str, str]:
    """Dotted-key view of a nested mapping; only string leaves are translatable."""
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    elif isinstance(obj, str):
        out[prefix] = obj
    return out


def unflatten_into(template, values: dict[str, str], prefix: str = ""):
    """Rebuild the original structure, substituting translated strings by dotted key."""
    if isinstance(template, dict):
        return {k: unflatten_into(v, values, f"{prefix}.{k}" if prefix else str(k))
                for k, v in template.items()}
    if isinstance(template, list):
        return [unflatten_into(v, values, f"{prefix}[{i}]") for i, v in enumerate(template)]
    if isinstance(template, str):
        return values.get(prefix, template)
    return template


def read_resource(path: Path) -> tuple[object, dict[str, str], str]:
    """Return ``(structure, {key: text}, fmt)``."""
    fmt = detect_format(path)
    raw = path.read_text(encoding="utf-8")
    if fmt == "json":
        data = json.loads(raw)
        return data, flatten(data), fmt
    if fmt == "properties":
        pairs = {}
        for line in raw.splitlines():
            m = _PROP_RE.match(line)
            if m:
                pairs[m.group(1).strip()] = m.group(2)
        return raw, pairs, fmt
    if fmt == "po":
        return raw, _po_entries(raw), fmt
    if fmt == "yaml":
        try:
            import yaml  # optional; degrade with a clear message rather than guessing
        except ImportError:
            raise SystemExit(
                "error: YAML support needs pyyaml, which run.sh supplies via uv. Install uv, "
                "or `pip install pyyaml`. Refusing to hand-parse YAML -- a wrong guess "
                "silently corrupts a config file."
            )
        data = yaml.safe_load(raw)
        return data, flatten(data), fmt
    raise SystemExit(f"error: unsupported resource format: {path.suffix}")


_PO_ENTRY_RE = re.compile(
    r'^msgid\s+"(?P<id>(?:[^"\\]|\\.)*)"\s*\n(?P<strs>(?:msgstr.*\n?)+)', re.MULTILINE
)


def _po_entries(raw: str) -> dict[str, str]:
    out = {}
    for m in _PO_ENTRY_RE.finditer(raw):
        mid = m.group("id")
        if mid:
            out[mid] = mid
    return out


def write_resource(path: Path, structure, values: dict[str, str], fmt: str) -> str:
    if fmt in ("json",):
        out = json.dumps(unflatten_into(structure, values), ensure_ascii=False, indent=2) + "\n"
    elif fmt == "yaml":
        import yaml
        out = yaml.safe_dump(unflatten_into(structure, values), allow_unicode=True, sort_keys=False)
    elif fmt == "properties":
        lines = []
        for line in str(structure).splitlines():
            m = _PROP_RE.match(line)
            if m and m.group(1).strip() in values:
                lines.append(f"{m.group(1)}={values[m.group(1).strip()]}")
            else:
                lines.append(line)
        out = "\n".join(lines) + "\n"
    elif fmt == "po":
        def _sub(m):
            mid = m.group("id")
            if mid and mid in values:
                esc = values[mid].replace("\\", "\\\\").replace('"', '\\"')
                return f'msgid "{mid}"\nmsgstr "{esc}"\n'
            return m.group(0)
        out = _PO_ENTRY_RE.sub(_sub, str(structure))
    else:
        raise SystemExit(f"error: cannot write format {fmt}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out, encoding="utf-8")
    return out


# --------------------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------------------

def verify_resource(src: dict[str, str], tgt: dict[str, str], rel: str) -> list[dict]:
    f: list[dict] = []

    def add(code, sev, msg, **kw):
        f.append({"code": code, "severity": sev, "file": rel, "message": msg, **kw})

    missing = sorted(set(src) - set(tgt))
    added = sorted(set(tgt) - set(src))
    if missing:
        add("RES-KEYSET", "error", f"{len(missing)} key(s) missing from the translation",
            keys=missing[:15])
    if added:
        add("RES-KEYSET", "error", f"{len(added)} key(s) added or renamed in the translation",
            keys=added[:15])

    for k in sorted(set(src) & set(tgt)):
        sv, tv = src[k], tgt[k]
        if sv.strip() and not tv.strip():
            add("RES-EMPTY", "error", f"key {k!r} is empty in the translation")
            continue
        want = sorted(A.USER_TOKEN_RE.findall(sv))
        got = sorted(A.USER_TOKEN_RE.findall(tv))
        if want != got:
            add("RES-PLACEHOLDER", "error", f"placeholders differ for key {k!r}",
                expected=want, actual=got)
        for esc in ("\\n", "\\t"):
            if sv.count(esc) != tv.count(esc):
                add("RES-ESCAPE", "error", f"{esc!r} count differs for key {k!r}",
                    expected=sv.count(esc), actual=tv.count(esc))
    return f


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def cmd_plan(args) -> int:
    root = Path(args.root).resolve()
    src_path = root / args.file
    if not src_path.exists():
        sys.stderr.write(f"error: no such file: {src_path}\n")
        return 2
    _, pairs, fmt = read_resource(src_path)
    layout = A.detect_layout(root, args.lang)
    tgt_rel = args.target or A.resolve_target(args.file, layout)

    state_dir = resolve_state_dir(root, args.state_dir)
    warn_if_ignored(root, state_dir)
    state = State.load(root, state_dir)
    cache = state.chunk_cache(args.file, args.lang) if not args.all else {}
    terms = A.load_glossary(state_dir / "glossary.json")

    todo = {k: v for k, v in pairs.items() if sha(v) not in cache}
    run_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    work = state_dir / "work" / run_id
    (work / "tasks").mkdir(parents=True, exist_ok=True)
    (work / "results").mkdir(parents=True, exist_ok=True)

    keys = sorted(todo)
    batches = [keys[i:i + BATCH_KEYS] for i in range(0, len(keys), BATCH_KEYS)] or []
    for i, batch in enumerate(batches):
        entries = {k: todo[k] for k in batch}
        hits = A.match_terms("\n".join(entries.values()), terms, args.lang, args.file)
        task_id = f"res-{i:03d}"
        (work / "tasks" / f"{task_id}.json").write_text(json.dumps({
            "task_id": task_id, "file": args.file, "target": tgt_rel, "lang": args.lang,
            "format": fmt, "entries": entries,
            "prompt": (
                f"Translate the VALUES of this key/value resource file into {args.lang}.\n"
                "STRICT RULES:\n"
                "- Return a JSON object with exactly the same keys.\n"
                "- Never translate, rename, add or remove a key.\n"
                "- Preserve every placeholder ({name}, {{name}}, %s, ${VAR}) exactly.\n"
                "- Preserve escape sequences (\\n, \\t) and their count.\n"
                "- Translate only human-readable text."
                + A.glossary_prompt(hits, args.lang)
            ),
            "result_path": f"{rel_state_dir(root, state_dir)}/work/{run_id}/results/{task_id}.json",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    plan = {"run_id": run_id, "kind": "resource", "file": args.file, "target": tgt_rel,
            "lang": args.lang, "format": fmt, "total_keys": len(pairs),
            "reused": len(pairs) - len(todo), "task_count": len(batches),
            "work_dir": f"{rel_state_dir(root, state_dir)}/work/{run_id}"}
    (work / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2) if args.json else
          f"run {run_id}  {args.file} -> {tgt_rel}  keys={len(pairs)} "
          f"reused={plan['reused']} tasks={len(batches)}")
    return 0


def cmd_apply(args) -> int:
    root = Path(args.root).resolve()
    state_dir = resolve_state_dir(root, args.state_dir)
    work = state_dir / "work" / args.run
    plan = json.loads((work / "plan.json").read_text(encoding="utf-8"))
    src_path = root / plan["file"]
    structure, pairs, fmt = read_resource(src_path)

    state = State.load(root, state_dir)
    cache = dict(state.chunk_cache(plan["file"], plan["lang"]))
    values = {k: cache[sha(v)] for k, v in pairs.items() if sha(v) in cache}

    for rf in sorted((work / "results").glob("*.json")):
        data = json.loads(rf.read_text(encoding="utf-8"))
        for k, v in (data.get("entries") or data).items():
            if k in pairs and isinstance(v, str):
                values[k] = v

    missing = sorted(set(pairs) - set(values))
    if missing:
        print(f"  REJECTED {plan['file']} [RES-MISSING] {len(missing)} key(s) untranslated: "
              f"{missing[:5]}")
        return 1

    findings = verify_resource(pairs, values, plan["file"])
    blocking = [f for f in findings if f["severity"] == "error"]
    if blocking and not args.force:
        for f in blocking[:10]:
            print(f"  ERROR {f['code']} {f['message']}")
        print("  nothing written; fix the results or re-run with --force")
        return 1

    tgt = root / plan["target"]
    out = write_resource(tgt, structure, values, fmt)
    state.record(plan["file"], plan["lang"], plan["target"], sha(src_path.read_text("utf-8")),
                 out, {sha(v): values[k] for k, v in pairs.items()})
    state.save()
    print(f"  wrote {plan['target']}  ({len(values)} keys)")
    return 0


def cmd_verify(args) -> int:
    root = Path(args.root).resolve()
    layout = A.detect_layout(root, args.lang)
    src_path = root / args.file
    tgt_rel = args.target or A.resolve_target(args.file, layout)
    tgt_path = root / tgt_rel
    if not tgt_path.exists():
        print(f"  ERROR RES-MISSING {tgt_rel} does not exist")
        return 1
    _, src_pairs, _ = read_resource(src_path)
    _, tgt_pairs, _ = read_resource(tgt_path)
    findings = verify_resource(src_pairs, tgt_pairs, args.file)
    n_err = sum(1 for f in findings if f["severity"] == "error")
    out = {"status": "fail" if n_err else "pass", "checked": len(src_pairs),
           "counts": {"error": n_err, "warn": len(findings) - n_err}, "findings": findings}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(f"checked {len(src_pairs)} key(s): {n_err} error(s)")
        for f in findings:
            print(f"  {f['severity'].upper():5s} {f['code']:16s} {f['message']}")
    return 1 if n_err else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Translate/verify key-value resource files.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "apply", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".")
        p.add_argument("--json", action="store_true")
        add_state_dir_arg(p)
        if name == "apply":
            p.add_argument("--run", required=True)
            p.add_argument("--force", action="store_true")
        else:
            p.add_argument("--lang", required=True)
            p.add_argument("--file", required=True)
            p.add_argument("--target", default=None)
            if name == "plan":
                p.add_argument("--all", action="store_true")
    args = ap.parse_args()
    return {"plan": cmd_plan, "apply": cmd_apply, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(run_main(main))
