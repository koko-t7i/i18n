# i18n

An agent skill for translating documentation and i18n resources, built for Claude Code.

Subagents do the translating; scripts do everything that must be deterministic — chunking,
incremental caching, layout resolution, link rewriting, and structural verification. No
translation API and no API keys are involved.

## What it handles

| Class | Formats |
|---|---|
| Documentation | `.md`, `.mdx`, `.markdown` — README, `docs/**`, `SKILL.md` |
| Resources | `.json`, `.yaml`/`.yml`, `.properties`, `.po`/`.pot` |

Not handled: source-code comments, user-facing strings embedded in source code, and
docs-site config (`mkdocs.yml` nav, `docusaurus.config.js`). See
`i18n/references/resources.md` for the Docusaurus workaround.

## Install

```bash
git clone <this repo> ~/icode/skills/i18n
cd ~/icode/skills/i18n
git submodule update --init --depth 1          # fetches the vendored translator
ln -s "$PWD/i18n" ~/.claude/skills/i18n
```

Requires [`uv`](https://docs.astral.sh/uv/) on `PATH`. Nothing is installed globally; `run.sh`
resolves dependencies into uv's cache on first use (a large download the first time).

## Use

Ask in plain language — "把 README 翻译成中文", "sync the Japanese docs", "check the
translations still match". Or drive the scripts directly:

```bash
S=~/.claude/skills/i18n/scripts

$S/run.sh plan  --root . --lang zh-CN --paths 'README.md' 'docs/**/*.md'
#   ... a subagent translates each file in .i18n/work/<run>/tasks/ ...
$S/run.sh apply  --root . --run <run_id>
$S/run.sh verify --root . --lang zh-CN
```

| Command | Purpose |
|---|---|
| `plan` | scan, detect layout, diff against state, emit subagent tasks |
| `apply` | reassemble results, repair CJK emphasis, rewrite links, write files |
| `verify` | structural gate; exit 1 on any blocking finding |
| `resource {plan,apply,verify}` | the key/value file path |

Useful flags: `--detect-layout-only`, `--all` (ignore cache), `--force` (overwrite
hand-edited translations), `--layout` / `--layout-pattern`, `--repair <verify.json>`,
`--json`, `--strict`, `--run-review`.

## Files it creates in your repo

| Path | Commit? | Purpose |
|---|---|---|
| `.i18n/state.json` | **yes** | translation lockfile: source hashes and the chunk cache |
| `.i18n/glossary.json` | **yes** | terminology, if you use one |
| `.i18n/work/` | no | per-run scratch; add to `.gitignore` |

## How it works

Markdown chunking, code-block protection and reassembly come from
[Azure/co-op-translator](https://github.com/Azure/co-op-translator) (MIT), vendored as a
submodule pinned at commit `f4f4b11` (v0.20.0). Its `start_markdown_agent_translation` /
`finish_markdown_agent_translation` pair is designed for exactly this shape: the host agent
supplies the translation, upstream handles the mechanics. Code blocks are swapped for
`@@CODE_BLOCK_n@@` tokens before any model sees the text, so they cannot be corrupted.

**The PyPI release cannot be used.** 0.18.2 does not ship that API — its entry points are
only `translate`, `evaluate`, `migrate-links`. Hence the pinned submodule.

This repo adds what upstream does not cover:

- **Layout** — upstream always writes to `translations/<lang>/`. This skill detects the
  repo's existing convention (`README.zh-CN.md`, `docs/zh-CN/`, `README_CN.md`, …) and
  follows it, rewriting relative links to match.
- **CJK emphasis repair** — upstream silently rewrites `**加粗**` to `<strong>加粗</strong>`
  for CJK targets (Latin targets are unaffected, and `warnings` comes back empty). `apply`
  converts it back, but only for tags the source document does not itself use.
- **Incremental caching** — keyed on each chunk's source hash, so unchanged chunks never
  reach a subagent and reuse survives re-chunking.
- **Verification** — inline-code identity, placeholder multisets, HTML tag parity, fence
  bodies, link URLs, heading sequence, glossary compliance.
- **Resource files** — JSON/YAML/properties/PO, with key-set identity enforced before write.

## Development

```bash
python3 -m unittest discover tests -v     # standard library only, no install needed
```

To move to a newer upstream:

```bash
git -C vendor/co-op-translator fetch --depth 1 origin main
git -C vendor/co-op-translator checkout <new-sha>
git add vendor/co-op-translator && python3 -m unittest discover tests
```

Re-run the end-to-end smoke test afterwards — the CJK repair and the chunk contract both
depend on upstream behaviour that is not covered by upstream's own API guarantees.

## License

MIT. `vendor/co-op-translator` is MIT and retains its own `LICENSE`.
