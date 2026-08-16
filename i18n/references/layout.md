# Where translations go

Read this when layout confidence is below 0.8, when the repo mixes conventions, or when the
user asks where translated files will land.

## Detection

`detect_layout(root, lang)` scans existing Markdown for evidence and returns the winner:

**Sibling-suffix** — a translated file sitting next to its source. Recognised shapes:

| Pattern | Example |
|---|---|
| `{stem}.{lang}{ext}` | `README.zh-CN.md` |
| `{stem}_{lang}{ext}` | `README_CN.md` |
| `{stem}-{lang}{ext}` | `README-zh.md` |

A candidate only counts if the **source file is right beside it**. A lone `notes.zh-CN.md`
with no `notes.md` is not evidence of a convention.

**Parallel-directory** — a per-language subtree, e.g. `docs/zh-CN/guide.md`,
`translations/ja/...`, `i18n/ko/...`.

The language token is matched loosely, so `zh-CN` also recognises `zh`, `zh_CN`, `zh-Hans`,
`CN`, `cn`. Whatever token the repo already uses is the token that gets reused.

`confidence` is the winning style's share of all evidence. `0.0` means no evidence at all.

## Resolution

With a **sibling** layout, every file maps to the same pattern.

With a **parallel** layout, only files under the detected prefix are relocated. A root
`README.md` next to a `docs/zh-CN/` tree resolves to `README.zh-CN.md`, not
`docs/zh-CN/README.md` — a doc tree's language convention does not own the repository root.

## Overriding

```bash
run.sh plan --root . --lang zh-CN --layout sibling  --layout-pattern '{stem}_{lang}{ext}'
run.sh plan --root . --lang zh-CN --layout parallel --layout-pattern 'docs/{lang}/{relpath}'
```

Placeholders: `{stem}` (path without extension), `{lang}`, `{ext}` (with dot), `{relpath}`
(path relative to the pattern's prefix).

When confidence is low, do not guess. Show the user both resolutions for a concrete file:

```
README.md -> README.zh-CN.md        (sibling)
README.md -> docs/zh-CN/README.md   (parallel)
```

## Link rewriting

Applied only when the source and target directories differ.

- **External URLs, `mailto:`, bare `#anchors`** — untouched.
- **Relative Markdown links** — repointed at the linked file's *translated* counterpart, if
  that source file exists in the repo. If it does not, the link keeps pointing at the
  original, since no translation of it will be produced.
- **Relative asset links** (images, etc.) — repointed at the same file from the new location.
- **Reference definitions** (`[label]: url`) — rewritten the same way.
- **Links inside code** — never touched.

Anchor fragments are carried through unchanged. Note that translated headings produce
different anchors; `verify` warns (`X-ANCHOR`) when a translated document links to an anchor
that no longer exists in it, but it cannot repair cross-file anchors automatically.

## Excluded from source scanning

Translation artifacts are never treated as sources, so a second run does not translate
`README.zh-CN.md` into `README.zh-CN.zh-CN.md`. Also skipped:
`.git`, `.claude`, `.i18n`, `node_modules`, `__pycache__`, `.venv`, `venv`, `vendor`, `.worktrees`,
`dist`, `build`, `.cache`.
