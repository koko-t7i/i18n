# Workflow internals

Read this when a run behaves unexpectedly, or when you need to reason about caching.

## Why the invocation looks like that

`run.sh` always runs:

```bash
uv run --python 3.12 --prerelease=allow --with <repo>/vendor/co-op-translator python <script>.py
```

- `--python 3.12` — co-op-translator pins `>=3.10,<3.13`.
- `--prerelease=allow` — its `semantic-kernel` dependency requires `azure-ai-agents>=1.2.0b3`,
  a pre-release. Without this flag uv fails resolution outright.
- `--with <local path>` — the PyPI release (0.18.2) **does not ship the agent-assisted API**;
  its entry points are only `translate`, `evaluate`, `migrate-links`. The vendored submodule
  is pinned at commit `f4f4b11` (v0.20.0), which does.

We import `co_op_translator.mcp.server` and call its functions directly as a Python API. No
MCP server is started; that module is just where upstream put these entry points.

## The job / chunk model

`start_markdown_agent_translation(document, language_code, source_path)` returns:

```jsonc
{"job_type": "markdown_agent_translation", "chunk_count": 2, "state": {...},
 "chunks": [{"id": "frontmatter:1", "kind": "frontmatter", "source": "**title**: Demo",
             "prompt": "...", "instructions": "..."},
            {"id": "body:1", "kind": "body",
             "source": "# Demo\n\n@@CODE_BLOCK_0@@\n...", "prompt": "..."}]}
```

Two things matter:

- **Code is already gone from `source`.** Upstream replaces fenced code with
  `@@CODE_BLOCK_n@@` before the text ever reaches a translator, and restores it during
  reassembly. A subagent physically cannot corrupt a code block; it can only corrupt the
  token, which `i18n_apply.py` checks for before writing anything.
- **Frontmatter is split out and filtered.** Only translatable keys appear (`title`), rendered
  as `**title**: Demo`. Keys like `sidebar_position` never reach the translator and are
  reconstructed verbatim.

`finish_markdown_agent_translation(job, translated_chunks)` needs **every** chunk of the
document — you cannot reassemble half a file.

## Why the cache is keyed on chunk source hash

Because `finish` needs all chunks, incrementality cannot live at the file level. So
`.i18n/state.json` stores, per (file, language):

```jsonc
{"target": "README.zh-CN.md", "source_sha": "...", "target_sha": "...",
 "chunks": {"<sha256 of chunk source>": "<translated text>"}}
```

On re-plan, each chunk's source hash is looked up. Hits are copied into the job blob as
`reused_chunks` and never become tasks; misses become tasks. Keying on content rather than
chunk id means reuse survives re-chunking — a chunk that keeps its text but moves from
`body:2` to `body:3` still hits.

**Honest limitation:** upstream chunks by token budget, so a document under the budget is a
single `body:1` chunk. Editing one word in such a file re-translates the whole body. The
cache pays off on long documents and on repeated runs across many files, not on small edits
to short files.

## Staleness and human edits

`State.status()` returns one of:

| Status | Meaning | Plan behaviour |
|---|---|---|
| `missing` | no translated file on disk | translate |
| `ok` | source hash matches what we translated | skip (unless `--all`) |
| `stale` | source changed since translation | translate, reusing unchanged chunks |
| `edited` | translated file's hash differs from what we wrote | **conflict, skip** |
| `orphan` | translation exists but we have no record of it | translate |

`edited` is the important one: it means a human touched the translation. Never pass `--force`
without asking. Report the file, say the translation was hand-edited, and let the user choose.

## Work directory

`.i18n/work/<run_id>/` holds `plan.json`, `jobs/*.json`, `tasks/*.json`, `results/*.json`.
It is disposable and should be gitignored. `.i18n/state.json` and `.i18n/glossary.json` are
the durable files and **should** be committed — state is the translation lockfile, and a
translated file without its state entry looks `orphan` on the next run.

## Failure codes from `apply`

| Code | Cause | Action |
|---|---|---|
| `ASM-MISSING` | a chunk result file is absent or empty | re-dispatch those chunk tasks |
| `ASM-PLACEHOLDER` | `@@CODE_BLOCK_n@@` tokens altered | re-dispatch with the rule restated |
| `ASM-FINISH` | upstream reassembly raised | read the message; usually a malformed chunk |

A rejected file is **not written** — other files in the same run still are.
