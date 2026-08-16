# i18n

**Keep translated docs in sync with the originals, without them quietly rotting.**

[简体中文](README.zh-CN.md)

An agent skill for [Claude Code](https://claude.com/claude-code). Subagents write the prose;
scripts handle everything that must not be left to a model — chunking, incremental caching,
layout resolution, link rewriting, and a structural gate that blocks bad output before it
reaches your repo. No translation API, no API keys.

## Why not just ask the model to translate the file?

Because a one-shot translation is right once and wrong forever after. Three things go wrong,
and all three are silent:

| Failure | What actually happens |
|---|---|
| **Drift** | You fix a typo in `README.md`. `README.zh-CN.md` still describes last month's behaviour, and nothing tells you. |
| **Structure damage** | The model translates a flag name inside backticks, or renders `{count}` as `{数量}`. The doc still looks fine; the copy-pasted command no longer runs. |
| **Terminology drift** | "skill" is 技能 in one paragraph and 技巧 three paragraphs later. |

This skill makes each one mechanical: content hashes detect drift, a verifier fails the run
on structure damage, and a glossary with a `forbid` list pins terminology.

## Install

```bash
git clone git@github.com:koko-t7i/i18n.git ~/icode/skills/i18n
ln -s ~/icode/skills/i18n/i18n ~/.claude/skills/i18n
```

One dependency: `markdown-it-py`. [`uv`](https://docs.astral.sh/uv/) on `PATH` supplies it
per-run and installs nothing globally; a plain `python3` that already has it works too.
Translating `.yaml` resource files additionally needs `pyyaml` — without it that path stops
rather than hand-parsing, since a wrong guess silently corrupts a config file.

## Use

Just ask:

> 把 README 和 docs 翻译成中文

> sync the Japanese docs

> check the translations still match

> re-translate the installation guide from scratch

Ask again later and anything whose source has not changed is skipped. Translations you edited
by hand are detected and never overwritten without you saying so.

## What it handles

| | |
|---|---|
| **Documentation** | `.md`, `.mdx`, `.markdown` — README, `docs/**`, `SKILL.md` |
| **Resources** | `.json`, `.yaml`/`.yml`, `.properties`, `.po`/`.pot` |
| **Not handled** | source-code comments, user-facing strings inside source code, docs-site config (`mkdocs.yml` nav, `docusaurus.config.js`) |

For Docusaurus, translate `i18n/<locale>/**.json` instead — that is a resource file and fully
supported. See [`references/resources.md`](i18n/references/resources.md).

## What gets checked

Every translation is compared against its source before it is accepted. These fail the run:

| Check | Asserts |
|---|---|
| `X-INLINE` | inline code spans are byte-identical — `` `--retries` `` stayed `` `--retries` `` |
| `X-TOKEN` | placeholders match — `{count}`, `%s`, `${VAR}`, `{{var}}` |
| `X-FENCE` | code fence count, language tags and bodies are unchanged |
| `X-HTML` | HTML tag multiset matches the source |
| `X-LINK` | external URLs verbatim, internal link count preserved |
| `X-HEADING` | heading level sequence matches element-wise |
| `X-GLOSSARY` | required terms present, forbidden renderings absent |
| `X-CHATTER` | no "here is the translation" preamble |

These only warn: `X-DEADLINK` (a relative link that does not resolve), `X-ANCHOR` (a
fragment with no matching heading), `X-UNTRANSLATED`, `X-ORPHAN`.

`X-INLINE` is the one that earns its keep. A translated `` `{count}` `` → `` `{数量}` ``
passes every other check and breaks the command your reader copies.

When a check fails, the offending chunk is sent back with the specific finding attached
rather than the whole document being retried. After two failed repair rounds it stops and
tells you which file needs a human, and why.

> [!NOTE]
> **Anchors into another file are not rewritten.** Translating `## Getting Started` to
> `## 快速开始` moves its anchor from `#getting-started` to `#快速开始`. Links *within* that
> document are repointed automatically; a link from a different file
> (`[x](./guide.md#getting-started)`) is not, and lands at the top of the page instead of the
> section. `X-ANCHOR` warns when it can see the mismatch. Doing better needs a repo-wide
> anchor map built after every file is translated, which is not implemented — it matters for
> a docs site with heavy cross-linking and rarely for a README plus a few guides.

## Where state lives

| Path | Commit? | Purpose |
|---|---|---|
| `.claude/i18n/state.json` | **yes** | translation lockfile: source hashes and the chunk cache |
| `.claude/i18n/glossary.json` | **yes** | terminology, if you use one |
| `.claude/i18n/work/` | no | per-run scratch |

```gitignore
.claude/i18n/work/
```

> [!IMPORTANT]
> A common `.gitignore` recipe denies `.claude/` wholesale and allowlists individual files.
> In such a repo `state.json` is silently untracked, and the next fresh clone re-translates
> everything from scratch. The skill runs `git check-ignore` before doing any work and warns
> you. Either allowlist it:
>
> ```gitignore
> !.claude/i18n/
> .claude/i18n/work/
> ```
>
> or tell the skill to keep state outside `.claude/`, in `.i18n/`.

## How it works

**Code blocks become `@@CODE_BLOCK_n@@` tokens before any model sees the text**, and are
restored during reassembly. A subagent physically cannot corrupt a code block; it can only
corrupt the token, and that is checked.

The load-bearing invariant is that **feeding every chunk back unchanged reproduces the source
byte for byte.** The test suite asserts it on real documents, on fences nested inside
blockquotes and list items, and on a 4000-word single paragraph.

Reassembly refuses, rather than writing a damaged file, when a `@@CODE_BLOCK_n@@` token was
dropped, mangled or duplicated, when a chunk is missing, or when a chunk id appears twice.
Every one of those silently destroyed content in the implementation this replaced.

Frontmatter is **edited, not re-serialised**: the original block is kept verbatim and scalar
values are substituted line by line, so comments, key order and quoting style survive.
Multi-line values are never touched. Nothing round-trips through a YAML dumper.

Layout follows your repo's existing convention (`README.zh-CN.md`, `docs/zh-CN/`,
`README_CN.md`, …) rather than imposing one, and relative links are rewritten to match.

Documents are split on a character budget, preferring H1/H2 boundaries once a chunk has
bulk, and each chunk is cached under the hash of its source text. Files whose source has not
changed are skipped entirely. Within a file the cache is only as fine as the chunks: a
document short enough to be a single chunk is retranslated whole when one word changes,
while a long one reuses every section you did not touch.

## Development

```bash
python3 -m unittest discover tests -v            # bare stdlib, nothing to install
uv run --with markdown-it-py python -m unittest discover tests
```

Run it both ways. On a bare `python3`, `_md` falls back to a regex Markdown scanner and the
four tests that need container-nested fences skip themselves.

Changing chunk boundaries means bumping `CHUNKER_VERSION` in `i18n/scripts/_job.py`. That
invalidates every cached chunk translation, which is correct — cached text from an older
splitter may never be produced again — and shows up as stale on the next run.

## License

MIT.
