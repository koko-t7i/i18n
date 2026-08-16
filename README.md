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

<details>
<summary>Previously built on Azure/co-op-translator</summary>

Chunking and reassembly used to come from
[Azure/co-op-translator](https://github.com/Azure/co-op-translator) (MIT), vendored as a
pinned submodule. To call three functions it cost **182 transitive packages** — the whole
Azure AI SDK, semantic-kernel, openai, numpy — plus a 20 MB font bundle used only for image
translation. It also silently rewrote `**加粗**` to `<strong>加粗</strong>` for CJK targets,
dropped code blocks without warning when a placeholder went missing, and destroyed
frontmatter comments through `yaml.dump`.

The replacement was validated by running both implementations over the same 16-document
corpus and diffing. Code-block extraction matched exactly on every document; the only
differences were the three behaviours dropped on purpose, plus one where upstream was
corrupting input outright — on a 4000-word paragraph it split mid-paragraph, joined the
pieces with a newline, and duplicated the heading.
</details>

## Limitations

- **Chunking is coarse for short documents.** A character budget with a preference for
  H1/H2 boundaries means a short document is one chunk — editing a word in it re-translates
  the whole body. The cache pays off on long documents and across many files.
- **Cross-file anchors are not repaired.** Translated headings get new slugs; in-document
  `[x](#frag)` links are repointed automatically, but a link from *another* file into a
  translated heading is not — that only warns.
- **mkdocs nav is not translated.** Edit it by hand.
- **YAML resources need `pyyaml`.** Without it that path refuses to run rather than
  hand-parsing — a wrong guess silently corrupts a config file.

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
