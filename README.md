# i18n

**Keep translated docs in sync with the originals, without them quietly rotting.**

[![CI](https://github.com/koko-t7i/i18n/actions/workflows/ci.yml/badge.svg)](https://github.com/koko-t7i/i18n/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](pyproject.toml)

[简体中文](README.zh-CN.md)

An agent skill for [Claude Code](https://claude.com/claude-code) and
[Codex](https://developers.openai.com/codex). Subagents write the prose; scripts do
everything that must not be left to a model. No translation API, no API keys.

## Quickstart

```bash
git clone git@github.com:koko-t7i/i18n.git ~/icode/skills/i18n
ln -s ~/icode/skills/i18n/i18n ~/.claude/skills/i18n     # Claude Code
ln -s ~/icode/skills/i18n/i18n ~/.codex/skills/i18n      # Codex
```

One directory, both harnesses — link whichever you use, or both. Needs
[`uv`](https://docs.astral.sh/uv/) on `PATH`, which supplies Python 3.13 and the two
dependencies per-run and installs nothing globally.

Then just ask — *把 README 和 docs 翻译成中文*, *sync the Japanese docs*, *check the
translations still match*, *re-translate the installation guide from scratch*.

Ask again later and unchanged files are skipped. Translations you edited by hand are detected
and never overwritten without you saying so.

## Why not just ask the model to translate the file?

A one-shot translation is right once and wrong forever after. Three things go wrong, and all
three are silent:

| Failure | What happens | Caught by |
|---|---|---|
| **Drift** | You fix a typo in `README.md`; the translation still describes last month's behaviour | content hashes |
| **Structure damage** | A flag name inside backticks gets translated, or `{count}` becomes `{数量}` — the doc looks fine, the copied command breaks | the verifier |
| **Terminology drift** | "skill" is 技能 in one paragraph and 技巧 three paragraphs later | a glossary `forbid` list |

## What it handles

| | |
|---|---|
| **Documentation** | `.md`, `.mdx`, `.markdown` — README, `docs/**`, `SKILL.md` |
| **Resources** | `.json`, `.yaml`/`.yml`, `.properties`, `.po`/`.pot` |
| **Not handled** | source-code comments, strings inside source code, docs-site config (`mkdocs.yml` nav, `docusaurus.config.js`) |

For Docusaurus translate `i18n/<locale>/**.json` instead — a resource file, fully supported.

## What gets checked

Every translation is compared against its source before it is accepted. These fail the run:

| Check | Asserts |
|---|---|
| `X-INLINE` | inline code is byte-identical — the check that earns its keep, since `` `{数量}` `` passes every other one and breaks the copied command |
| `X-TOKEN` | placeholders match — `{count}`, `%s`, `${VAR}`, `{{var}}` |
| `X-FENCE` | code fence count, language tags and bodies unchanged |
| `X-HTML` | HTML tag multiset matches the source |
| `X-LINK` | external URLs verbatim, internal link count preserved |
| `X-HEADING` | heading level sequence matches element-wise |
| `X-GLOSSARY` | required terms present, forbidden renderings absent |
| `X-CHATTER` | no "here is the translation" preamble |

Warnings only: `X-DEADLINK`, `X-ANCHOR`, `X-UNTRANSLATED`, `X-ORPHAN`, `X-STYLE`.

On failure only the offending chunk is retried, with the finding attached. After two rounds
it stops and names the file that needs a human.

Every check above compares *structure*. None of them can tell you the translation is fluent
and wrong — for that there are two more passes, below.

## Revision and proofreading

Structure checks catch a mangled code fence. They cannot catch a paragraph that reads
perfectly and says the opposite of the source. Professional practice splits that into two
jobs, and this follows it:

| Pass | Sees | Judges | Blocks? |
|---|---|---|---|
| **revision** | source **and** translation | accuracy, terminology, audience fit | yes |
| **proofread** | **translation only** | fluency, style, locale | no |

The proofreader is not shown the source, and that is the method rather than an oversight: a
sentence that maps neatly onto its source reads as correct even when no native writer would
phrase it that way. Only someone who cannot see the original notices.

Each pass costs one extra model call per file, so it is a choice — translation memory and
the style guide below cost nothing and are always on.

```bash
run.sh review plan    --root . --lang zh-CN --mode revision
run.sh review collect --root . --run <run_id>
```

Findings come back in the localisation industry's MQM error typology and feed the existing
repair loop. See [`i18n/references/review.md`](i18n/references/review.md).

## Terminology and style

Two optional files, both committed, both living beside the state:

| File | Fixes |
|---|---|
| `<state-dir>/glossary.json` | individual words — required renderings, forbidden ones, terms to leave in English |
| `<state-dir>/style.json` | everything between them — register, audience, how the reader is addressed, quotation marks, CJK/Latin spacing, what to do with terms the glossary does not list |

Without a glossary, terminology drifts between runs. Without a style file, so does the
prose. Three of the style conventions are machine-checked as `X-STYLE`; the rest reach the
translator, the reviser and the proofreader as one shared definition.

> [!NOTE]
> **Anchors from another file are not rewritten.** Translating `## Getting Started` moves its
> anchor to `#快速开始`. Links within that document are repointed automatically; one from a
> different file is not, and lands at the top of the page. `X-ANCHOR` warns. Fixing it needs
> a repo-wide anchor map built after every file is translated — not implemented, and it
> matters for a cross-linked docs site far more than for a README plus a few guides.

## Where state lives

Under the directory your agent already owns: `.claude/i18n/` for Claude Code, `.codex/i18n/`
for Codex.

| Path | Commit? | Purpose |
|---|---|---|
| `<state-dir>/state.json` | **yes** | translation lockfile: source hashes, plus both sides of every chunk |
| `<state-dir>/glossary.json` | **yes** | terminology, if you use one |
| `<state-dir>/style.json` | **yes** | style conventions, if you use them |
| `<state-dir>/work/` | no | per-run scratch — gitignore it |

A repo that already has one keeps it, whichever agent you open it with — two lockfiles cannot
see each other's chunk cache, and a split would silently re-translate everything. `--state-dir`
overrides the choice.

> [!IMPORTANT]
> The common `.gitignore` recipe denies `.claude/` (or `.codex/`) wholesale. In such a repo
> `state.json` is silently untracked and the next fresh clone re-translates everything. The
> skill runs `git check-ignore` before doing any work and warns you. Either allowlist it —
> `!.claude/i18n/` then `.claude/i18n/work/` — or tell the skill to keep state in `.i18n/`.

## How it works

### A subagent cannot break a code block

**Code blocks become `@@CODE_BLOCK_n@@` tokens before any model sees the text** and are
restored on reassembly. What reaches the translator is the token, and the token is checked.

The invariant is that **feeding every chunk back unchanged reproduces the source byte for
byte**. The tests assert it on real documents, on fences nested in blockquotes and list
items, and on a 4000-word paragraph. Reassembly refuses to write a damaged file when a token
is dropped, mangled or duplicated, or when a chunk is missing or duplicated.

### Frontmatter is edited, not re-serialised

The original block is kept and scalar values substituted line by line, so comments, key order
and quoting survive. Round-tripping through a YAML dumper — the obvious implementation —
silently reformats all three.

### Layout follows your repo

`README.zh-CN.md`, `docs/zh-CN/`, `README_CN.md`, … — the convention already in the repo is
detected rather than imposed, and relative links are rewritten to match wherever the
translation lands.

### Chunking, the cache, and translation memory

Documents split on a character budget, preferring H1/H2 boundaries, and each chunk is cached
under the hash of its source. Unchanged files are skipped entirely.

Within a file the cache is only as fine as the chunks, so a single-chunk document has no
exact hit once one word changes. That is where the second tier comes in: the state file
stores each chunk's **source** next to its translation, so a changed chunk is matched
against the nearest previous one and handed to the translator as an **edit** — old
translation, old source, similarity ratio — rather than a blank page. Sentences whose source
did not change come through untouched.

Without it, a one-word fix re-words the entire page and every reviewer has to re-read a
translation that did not need to change. Measured on this repository's own README: 54
insertions and 44 deletions without the previous translation, 19 and 9 with it.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
uv run --with ruff ruff check .
python3 -m unittest discover tests -v
```

## License

MIT.
