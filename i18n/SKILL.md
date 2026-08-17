---
name: i18n
description: >-
  Translate docs and i18n resource files, and keep translations in sync with their source.
  Use for 翻译文档, 本地化, 国际化, 多语言, 术语表, 同步翻译, 检查翻译, translate docs, localize,
  sync translations. Not for code comments or in-code strings.
license: MIT
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
S=~/.claude/skills/i18n/scripts          # Codex: ~/.codex/skills/i18n/scripts
$S/run.sh plan  --root . --lang zh-CN --paths 'README.md' 'docs/**/*.md'
# ... fan out one subagent per file in <state-dir>/work/<run>/tasks/ ...
$S/run.sh apply  --root . --run <run_id>
$S/run.sh verify --root . --lang zh-CN
```

`<state-dir>` is resolved for you: whichever state directory the repository already has,
otherwise `.claude/i18n` under Claude Code and `.codex/i18n` under Codex. The `work_dir` in
`plan --json` shows which one was picked. Override it with `--state-dir` — on every command
of a run, not just the first.

## Workflow

1. **Confirm scope** — target language(s) and which paths. Nothing else needs asking.
2. **Detect layout** — `run.sh plan --detect-layout-only --root . --lang zh-CN`. If
   `confidence < 0.8`, read `references/layout.md`, show the user the two candidate layouts,
   and pass `--layout` / `--layout-pattern`.
3. **Glossary and style** *(optional)* — if `<state-dir>/glossary.json` or `style.json` is
   absent, offer to seed them from `assets/glossary.example.json` and
   `assets/style.example.json`. Running without either is fine; the glossary holds
   terminology, the style file holds everything between the terms.
4. **Plan** — `run.sh plan --root . --lang <lang> [--paths ...] --json`. Read the summary.
   - `conflicts` non-empty → surface each to the user and stop until they decide.
   - `task_count == 0` → everything is current; say so and stop.
   - `truncated_tasks > 0` → say so; a second run is needed after this batch.
5. **Read the reference the plan points at** — normally none. Only when routing says so.
6. **Fan out** — one subagent per task file in `<state-dir>/work/<run>/tasks/`, about 6 in
   flight at a time. Claude Code: the `Task` tool. Codex: spawn that many subagents in
   parallel. If the harness you are running under has no subagent mechanism at all, work
   through the task files yourself one at a time — same contract, just serial.
   A task with `"mode": "revise"` carries `previous_translation`; use
   `assets/prompts/revise_markdown.md` for those. See the subagent contract below.
7. **Apply** — `run.sh apply --root . --run <run_id>`. Rejected files are listed with a
   code; re-dispatch just those tasks.
8. **Verify** — `run.sh verify --root . --lang <lang> --json`.
9. **Repair on failure** — read `references/verification.md`, then
   `run.sh plan --repair <state-dir>/work/<run>/verify.json` and return to step 6.
   **Retry budget: 2.** After that, report exactly which files need a human and why.
10. **Revise** *(default; skip only if the user asked for a draft)* — `run.sh review plan
    --root . --lang <lang> --mode revision`, fan out, `run.sh review collect --run <id>`.
    Blocking findings go back through `plan --repair` at step 6. This is the only pass that
    catches a translation that is fluent and wrong.
11. **Proofread** *(only when asked for publication quality)* — same shape with
    `--mode proofread`. Findings never block; surface them and let the user choose.
12. **Report** — files written, chunks fresh vs reused vs edited from a previous
    translation, verify verdict, and any review findings. Do not commit unless asked; if
    committing, stage the translated files and `<state-dir>/state.json` together.

## Routing

Read at most what this table names. Do not preload references.

| Situation | Read |
|---|---|
| Layout confidence < 0.8, or the user asks where translations go | `references/layout.md` |
| `verify` exited 1, or `apply` rejected a file | `references/verification.md` |
| Translating JSON / YAML / PO / .properties | `references/resources.md` |
| A glossary finding appeared, or the user asks about terminology | `references/glossary.md` |
| An `X-STYLE` finding appeared, or the user asks about tone, punctuation or how the reader is addressed | `references/style.md` |
| Running revision or proofreading, or the user asks how translation quality is judged | `references/review.md` |
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

Two additions when the file already has a translation:

- **`plan` attaches the previous translation itself** — a task with `"mode": "revise"`
  carries `previous_translation`, `previous_source` and `match_ratio`. Use
  `assets/prompts/revise_markdown.md`: edit that translation, leave every sentence whose
  source did not change byte-identical. A short document is one chunk, so without this one
  edited word re-words the whole page.
- A *switch-language* link at the top points the other way in the translated file:
  `[简体中文](README.zh-CN.md)` becomes `[English](README.md)`, never a link to itself.

## Installation

One directory serves both harnesses; link it wherever you need it.

```bash
ln -s <repo>/i18n ~/.claude/skills/i18n     # Claude Code
ln -s <repo>/i18n ~/.codex/skills/i18n      # Codex
```

`run.sh` runs each script through `uv`, which pins Python 3.13 and provides the dependencies
per-run, installing nothing globally. Without `uv` it falls back to the system `python3`,
refusing anything older than 3.13 and working only as far as that interpreter's libraries
allow — see `references/workflow.md`.
