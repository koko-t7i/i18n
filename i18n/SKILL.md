---
name: i18n
description: >-
  Translate and localize documentation and i18n resources: Markdown/MDX docs, README,
  SKILL.md, docs/** trees, JSON/YAML/PO/.properties message files. Use when the user says
  翻译文档, 翻译 README, 翻译成中文, 中文文档, 英文文档, 双语文档, 本地化, 国际化, i18n, l10n,
  多语言, 语言包, 术语表, 更新翻译, 补齐翻译, 同步翻译, 只翻译改动的部分, 检查翻译, 校对译文,
  translate docs, translate README, localize documentation, sync or refresh translations,
  add a Chinese/Japanese/Korean version, check translation consistency, or verify that a
  translated document still matches the original structure. Re-translates only what changed
  via content hashing, and verifies structural parity (code blocks, inline code, links,
  placeholders, headings, resource keys) before accepting output. Not for translating
  source-code comments or user-facing strings embedded in source code.
license: MIT
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Task
---

# i18n — documentation translation

Translation runs as a pipeline: a script plans the work and hands out chunks, **subagents do
the actual translating**, and a script reassembles and verifies. You orchestrate; you do not
translate whole documents yourself in the main thread.

Everything is this skill's own code. `run.sh` runs each script through `uv`, which supplies
its two dependencies (`markdown-it-py` for CommonMark-accurate fence detection, `pyyaml` for
YAML resource files) per-run. Always invoke the scripts through `run.sh`.

## Hard rules

- **Never** translate: fenced or inline code, URLs, placeholder tokens (`{count}`, `%s`,
  `${VAR}`), resource keys, frontmatter keys, `@@CODE_BLOCK_n@@`-style tokens.
- **Never** hand-write a translated file. Everything goes through `run.sh apply`.
- **Never** accept output that `run.sh verify` rejects. Fix it or report it.
- **Never** overwrite a translation a human edited. `plan` reports these as conflicts; ask
  the user before passing `--force`.
- Decline requests to translate source-code comments or in-code strings; say why and offer
  to translate the docs instead.
- No external translation API, ever. Subagents are the translator.

## Quick start

```bash
S=~/.claude/skills/i18n/scripts          # or the repo path
$S/run.sh plan  --root . --lang zh-CN --paths 'README.md' 'docs/**/*.md'
# ... fan out one Task subagent per file in .claude/i18n/work/<run>/tasks/ ...
$S/run.sh apply  --root . --run <run_id>
$S/run.sh verify --root . --lang zh-CN
```

## Workflow

1. **Confirm scope** — target language(s) and which paths. Nothing else needs asking.
2. **Detect layout** — `run.sh plan --detect-layout-only --root . --lang zh-CN`. If
   `confidence < 0.8`, read `references/layout.md`, show the user the two candidate layouts,
   and pass `--layout` / `--layout-pattern`.
3. **Glossary** *(optional)* — if `.claude/i18n/glossary.json` is absent, offer to seed it from
   `assets/glossary.example.json`. Running without one is fine.
4. **Plan** — `run.sh plan --root . --lang <lang> [--paths ...] --json`. Read the summary.
   - `conflicts` non-empty → surface each to the user and stop until they decide.
   - `task_count == 0` → everything is current; say so and stop.
   - `truncated_tasks > 0` → say so; a second run is needed after this batch.
5. **Read the reference the plan points at** — normally none. Only when routing says so.
6. **Fan out** — one `Task` subagent per file in `.claude/i18n/work/<run>/tasks/`, about 6 per
   message. See the subagent contract below.
7. **Apply** — `run.sh apply --root . --run <run_id>`. Rejected files are listed with a
   code; re-dispatch just those tasks.
8. **Verify** — `run.sh verify --root . --lang <lang> --json`.
9. **Repair on failure** — read `references/verification.md`, then
   `run.sh plan --repair .claude/i18n/work/<run>/verify.json` and return to step 6.
   **Retry budget: 2.** After that, report exactly which files need a human and why.
10. **Report** — files written, chunks fresh vs reused, verify verdict. Do not commit unless
    asked; if committing, stage the translated files and `.claude/i18n/state.json` together.

## Routing

Read at most what this table names. Do not preload references.

| Situation | Read |
|---|---|
| Layout confidence < 0.8, or the user asks where translations go | `references/layout.md` |
| `verify` exited 1, or `apply` rejected a file | `references/verification.md` |
| Translating JSON / YAML / PO / .properties | `references/resources.md` |
| A glossary finding appeared, or the user asks about terminology | `references/glossary.md` |
| Anything about job/chunk internals, caching, or a run that behaves oddly | `references/workflow.md` |

## Subagent contract

Each subagent gets exactly one task file. Its prompt must state:

1. Read `<task_file>`. Translate the `source` field following the embedded `prompt` field.
2. Write **only** `{"chunk_id": "<chunk_id>", "translated_text": "..."}` to `result_path`.
3. Keep every `@@CODE_BLOCK_n@@`, `@@INLINE_CODE_n@@`, `@@LINE_nnnn@@` token byte-identical.
4. Keep Markdown structure identical — same headings, same list nesting, same table shape.
5. Copy inline code spans verbatim; never translate what is inside backticks.
6. Return no commentary, no ```` ```markdown ```` wrapper, no "here is the translation".
7. Do not touch any file in the repository.

## Installation

```bash
ln -s <repo>/i18n ~/.claude/skills/i18n
```

`run.sh` runs each script through `uv`, which provides the dependencies per-run and installs
nothing globally. Without `uv` it falls back to the system `python3`, which works only as far
as that interpreter's libraries allow — see `references/workflow.md`.
