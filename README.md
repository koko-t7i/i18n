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

## Quick start

```bash
git clone --recurse-submodules git@github.com:koko-t7i/i18n.git ~/icode/skills/i18n
ln -s ~/icode/skills/i18n/i18n ~/.claude/skills/i18n
```

Requires [`uv`](https://docs.astral.sh/uv/) on `PATH`. Nothing is installed globally; the
first run resolves dependencies into uv's cache (a large download once).

Then just ask:

> 把 README 和 docs 翻译成中文

or drive the scripts yourself:

```bash
S=~/.claude/skills/i18n/scripts

$S/run.sh plan  --root . --lang zh-CN --paths 'README.md' 'docs/**/*.md'
#   ... a subagent translates each task in .claude/i18n/work/<run>/tasks/ ...
$S/run.sh apply  --root . --run <run_id>
$S/run.sh verify --root . --lang zh-CN
```

Re-run `plan` later and it reports `up-to-date` for anything whose source has not changed.

## What it handles

| | |
|---|---|
| **Documentation** | `.md`, `.mdx`, `.markdown` — README, `docs/**`, `SKILL.md` |
| **Resources** | `.json`, `.yaml`/`.yml`, `.properties`, `.po`/`.pot` |
| **Not handled** | source-code comments, user-facing strings inside source code, docs-site config (`mkdocs.yml` nav, `docusaurus.config.js`) |

For Docusaurus, translate `i18n/<locale>/**.json` instead — that is a resource file and fully
supported. See [`references/resources.md`](i18n/references/resources.md).

## What "structural parity" means

The verifier compares source and translation and fails the run on any of these:

```
X-INLINE       inline code spans must be byte-identical      `--retries` stayed `--retries`
X-TOKEN        placeholders must match                       {count}, %s, ${VAR}, {{var}}
X-FENCE        fence count, language tags, and bodies        ```bash blocks unchanged
X-HTML         HTML tag multiset must match the source
X-LINK         external URLs verbatim; internal link count
X-HEADING      heading level sequence, element-wise
X-GLOSSARY     required terms present, forbidden ones absent
X-CHATTER      no "here is the translation" preamble
```

`X-INLINE` is the one that earns its keep. A translated `` `{count}` `` → `` `{数量}` `` passes
every other check and breaks the command your reader copies.

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
> everything from scratch. `plan` runs `git check-ignore` and warns you. Either allowlist it:
>
> ```gitignore
> !.claude/i18n/
> .claude/i18n/work/
> ```
>
> or keep state outside `.claude/` with `--state-dir .i18n`.

## Commands

| Command | Purpose |
|---|---|
| `plan` | scan, detect layout, diff against state, emit subagent tasks |
| `apply` | reassemble results, repair CJK emphasis, rewrite links, write files |
| `verify` | structural gate; exit 1 on any blocking finding |
| `resource {plan,apply,verify}` | the key/value file path |

Useful flags: `--detect-layout-only`, `--all` (ignore cache), `--force` (overwrite
hand-edited translations), `--layout` / `--layout-pattern`, `--state-dir`,
`--repair <verify.json>`, `--json`, `--strict`, `--run-review`.

## How it works

Markdown chunking, code-block protection and reassembly come from
[Azure/co-op-translator](https://github.com/Azure/co-op-translator) (MIT), vendored as a
submodule pinned at commit `f4f4b11` (v0.20.0). Its agent-assisted API is built for exactly
this shape — the host agent supplies the translation, upstream handles the mechanics. Code
blocks become `@@CODE_BLOCK_n@@` tokens *before any model sees the text*, so they cannot be
corrupted.

> **The PyPI release will not work.** 0.18.2 does not ship that API — its entry points are
> only `translate`, `evaluate`, `migrate-links`. Hence the pinned submodule.

This repo adds what upstream does not cover:

- **Layout detection** — upstream always writes to `translations/<lang>/`. This follows your
  repo's existing convention instead (`README.zh-CN.md`, `docs/zh-CN/`, `README_CN.md`, …)
  and rewrites relative links to match.
- **CJK emphasis repair** — upstream silently rewrites `**加粗**` to `<strong>加粗</strong>`
  for CJK targets, with `warnings` coming back empty. Latin targets are unaffected. `apply`
  converts it back, but only for tags the source document does not itself use.
- **Incremental caching** — keyed on each chunk's source hash, so reuse survives re-chunking.
- **Verification** — the checks above.
- **Resource files** — key-set identity enforced *before* anything is written.

## Limitations

- **Chunk granularity is upstream's.** It chunks by token budget, so a short document is one
  chunk — editing a word in it re-translates the whole body. The cache pays off on long
  documents and across many files, not on small edits to short ones.
- **Translated headings change anchors.** `verify` warns when a document links to an anchor
  that no longer exists in it, but cross-file anchors are not repaired automatically.
- **mkdocs nav is not translated.** Edit it by hand.
- **YAML needs `pyyaml`.** Without it the resource path refuses to run rather than
  hand-parsing — a wrong guess silently corrupts a config file.

## Development

```bash
python3 -m unittest discover tests -v     # standard library only, nothing to install
```

Upgrading the vendored translator:

```bash
git -C vendor/co-op-translator fetch --depth 1 origin main
git -C vendor/co-op-translator checkout <new-sha>
git add vendor/co-op-translator && python3 -m unittest discover tests
```

Re-run the end-to-end smoke test afterwards. The CJK repair and the chunk contract both
depend on upstream behaviour that its own API guarantees do not cover.

## License

MIT. `vendor/co-op-translator` is MIT and retains its own `LICENSE`.
