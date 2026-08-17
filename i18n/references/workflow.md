# Workflow internals

Read this when a run behaves unexpectedly, or when you need to reason about caching.

## Dependencies

`uv` is the expected environment. `run.sh` runs:

```bash
uv run --with markdown-it-py --with pyyaml python <script>.py
```

Two dependencies, supplied per-run, nothing installed globally.

| Library | Used for | Missing |
|---|---|---|
| `markdown-it-py` | CommonMark-accurate fence detection | `_md` falls back to a regex scanner and warns once |
| `pyyaml` | `.yaml` resource files | that path stops rather than hand-parsing |

The scripts need Python 3.13. `uv` fetches it, so the system interpreter does not have to be
current; without `uv`, `run.sh` checks the system `python3` and refuses an older one rather
than failing partway through a run.

That fallback path also works only as far as the interpreter's own libraries go, and prints a
note saying so. The regex fallback mis-slices fences
nested inside blockquotes (`> ```bash`) or list items, so the unit tests skip the
container-nesting cases when the parser is absent.

## The job / chunk model

`_job.start_job(document, lang, source_path)` returns:

```jsonc
{"job_type": "markdown_translation", "version": 1, "chunker": 1,
 "language_code": "zh-CN", "language_name": "Chinese (Simplified)", "is_rtl": false,
 "chunk_count": 2,
 "chunks": [{"id": "frontmatter:1", "kind": "frontmatter", "source": "**title**: Demo", ...},
            {"id": "body:1", "kind": "body", "source": "# Demo\n\n@@CODE_BLOCK_0@@\n...", ...}],
 "state": {"original_document": "...", "placeholder_map": {...},
           "frontmatter_raw": "---\ntitle: Demo\n---\n", "frontmatter_fields": {"title": "Demo"}}}
```

Three things matter:

- **Code is gone from `source` before any model sees it.** Fenced blocks are replaced by
  `@@CODE_BLOCK_n@@` and restored during reassembly. A subagent physically cannot corrupt a
  code block; it can only corrupt the token, and that is checked.
- **Frontmatter is split out and filtered.** Only keys on the translatable allowlist appear,
  rendered as `**title**: Demo`. Keys like `sidebar_position` never reach the translator.
  Multi-line values (block scalars, nested maps, lists) are never translated.
- **Frontmatter is edited, not re-serialised.** The original block is kept verbatim and
  scalar values are substituted line by line, so comments, key order and quoting style all
  survive. Nothing round-trips through a YAML dumper.

`_job.finish_job(job, translated_chunks)` needs **every** chunk of the document — you cannot
reassemble half a file.

## What finish_job refuses

All of these were silent data loss in the implementation this replaced. Each now raises,
and `i18n_apply.py` turns it into an `ASM-*` rejection without writing the file:

| Situation | Result |
|---|---|
| a `@@CODE_BLOCK_n@@` token was dropped | `ValueError`, names the lost tokens |
| a token was mangled (`@@ CODE_BLOCK_0 @@`) | `ValueError` |
| a token was duplicated | `ValueError` — the check is a multiset, not a set |
| a chunk is missing | `ValueError`, names the chunk ids |
| a chunk id appears twice | `ValueError` |
| an extra chunk id was returned | accepted, reported in `warnings` |

The invariant worth remembering: **feeding every chunk back unchanged must reproduce the
source byte for byte.** The test suite asserts exactly that, including on documents with
nested fences and a 4000-word single paragraph.

## Why the cache is keyed on chunk source hash

Because `finish_job` needs all chunks, incrementality cannot live at the file level. So
`state.json` stores, per (file, language):

```jsonc
{"target": "README.zh-CN.md", "chunker": 1, "source_sha": "...", "target_sha": "...",
 "chunks": {"<sha256 of chunk source>": "<translated text>"}}
```

On re-plan, each chunk's source hash is looked up. Hits are copied into the job blob as
`reused_chunks` and never become tasks; misses become tasks. Keying on content rather than
chunk id means reuse survives re-chunking — a chunk that keeps its text but moves from
`body:2` to `body:3` still hits.

`chunker` is the segmentation version. When `_job.CHUNKER_VERSION` changes, cached chunks
were produced by a splitter that may never emit that text again, so the whole file is
re-translated once. That is deliberate and visible in the plan output as `stale`.

## The fuzzy tier

An exact hash miss is not the end. `State.fuzzy_match` compares the new chunk against every
previously translated chunk of the same file with `difflib.SequenceMatcher`, and above
`FUZZY_THRESHOLD` (0.6) the task file gains `previous_translation`, `previous_source` and
`match_ratio`, plus `"mode": "revise"`. The subagent then edits rather than retranslates —
see `assets/prompts/revise_markdown.md`.

This is what a CAT tool calls a fuzzy match, and it exists for one reason: chunks here are
whole sections, so a one-word source change otherwise re-words a whole page of settled
prose. The threshold sits below the 70–75% CAT convention because a section-sized chunk
moves its ratio less than a sentence does for the same edit.

`plan --json` reports `fuzzy_matched`. `--all` and `--repair` suppress it: both mean
"ignore what we had", so anchoring to the old translation would defeat them.

### Schema 2

Fuzzy matching needs the old *source*, so `chunks` maps a hash to `{"src", "tgt"}` rather
than to a bare string. Schema 1 files are still read — their entries simply have no fuzzy
capability until each file is next translated. **Nothing is discarded on upgrade**; doing so
would re-translate every repository that has ever used this skill. Both shapes coexist in
one `state.json` while a repo migrates file by file.

The cost is file size: `state.json` now holds both sides of every chunk. That is what a
translation memory is.

**Honest limitation:** chunking uses a character budget with a preference for breaking at
H1/H2, so a document under the budget is a single `body:1` chunk. Editing one word in such a
file re-translates the whole body. The cache pays off on long documents and on repeated runs
across many files, not on small edits to short files.

## Staleness and human edits

`State.status()` returns one of:

| Status | Meaning | Plan behaviour |
|---|---|---|
| `missing` | no translated file on disk | translate |
| `ok` | source hash matches what we translated | skip (unless `--all`) |
| `stale` | source changed, or the chunker version did | translate, reusing unchanged chunks |
| `edited` | translated file's hash differs from what we wrote | **conflict, skip** |
| `orphan` | translation exists but we have no record of it | translate |

`edited` is the important one: it means a human touched the translation. Never pass `--force`
without asking. Report the file, say the translation was hand-edited, and let the user choose.

## State directory

State is grouped under the directory the harness already owns, so nothing new appears at the
top level. Three contents, whichever directory is picked:

| Path | Committed? | Purpose |
|---|---|---|
| `<state-dir>/state.json` | **yes** | translation lockfile: source hashes + chunk cache |
| `<state-dir>/glossary.json` | **yes** | terminology, if used |
| `<state-dir>/style.json` | **yes** | style conventions, if used — see `style.md` |
| `<state-dir>/work/<run_id>/` | no | `plan.json`, `jobs/`, `tasks/`, `results/`, `review/` — disposable |

`resolve_state_dir` in `_paths.py` picks it, in this order:

| | Condition | Result |
|---|---|---|
| 1 | `--state-dir` given | that path (relative ones resolve against `--root`) |
| 2 | `I18N_STATE_DIR` set | same treatment |
| 3 | `.claude/i18n`, `.codex/i18n` or `.i18n` already holds `state.json` or `glossary.json` | that one |
| 4 | harness identified — `I18N_HARNESS` (set by `run.sh` from the path it was invoked through), else `CLAUDECODE`, else `CODEX_HOME` | `.claude/i18n` or `.codex/i18n` |
| 5 | nothing identified it | `.claude/i18n` |

Step 3 outranks the harness on purpose. A repo translated under Claude Code and later opened
under Codex keeps its `.claude/i18n` rather than starting a second one — two `state.json`
files cannot see each other's chunk cache, so a split re-translates the whole repo and then
leaves two lockfiles disagreeing about it. When two of them somehow do exist, every command
stops with exit 2 and asks for an explicit `--state-dir` instead of guessing.

`.i18n` is recognised but never chosen on its own; it is the escape hatch below, and repos
that took it keep working.

A translated file whose state entry is missing looks `orphan` on the next run and gets
re-translated from scratch, so `state.json` genuinely has to be committed.

**This is the one thing that bites.** The common community `.gitignore` recipes deny the
whole agent directory and allowlist individual files:

```gitignore
.claude/
!.claude/settings.json
.claude/settings.local.json
```

In a repo like that, `state.json` is silently untracked. `plan` therefore runs
`git check-ignore` on it and prints a warning naming the fix. If you see that warning, either
allowlist the directory —

```gitignore
!.claude/i18n/
.claude/i18n/work/
```

or, under Codex:

```gitignore
!.codex/i18n/
.codex/i18n/work/
```

— or move state out from under the agent directory entirely with `--state-dir .i18n`. Do not
ignore the warning: the failure is silent and only shows up as a full re-translation in a
fresh clone.

## Failure codes from `apply`

| Code | Cause | Action |
|---|---|---|
| `ASM-MISSING` | a chunk result file is absent or empty | re-dispatch those chunk tasks |
| `ASM-PLACEHOLDER` | `@@CODE_BLOCK_n@@` tokens altered | re-dispatch with the rule restated |
| `ASM-FINISH` | reassembly raised | read the message; usually a malformed chunk |

A rejected file is **not written** — other files in the same run still are.
