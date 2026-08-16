# Glossary

Optional. Without one, translation still works; terminology just drifts between runs.

Lives at `<repo>/.claude/i18n/glossary.json` and **should be committed**. Seed it by copying
`assets/glossary.example.json`.

## Schema

```jsonc
{
  "schema": 1,
  "source_lang": "en",
  "terms": [
    {
      "id": "skill",
      "source": "skill",
      "aliases": ["skills", "Agent Skill"],
      "policy": "translate",
      "case_sensitive": false,
      "scope": ["**/*.md"],
      "translations": {
        "zh-CN": {"text": "技能", "forbid": ["技巧", "本领"]},
        "ja": {"text": "スキル"}
      },
      "notes": "A Claude Code Agent Skill, not a general ability.",
      "severity": "error"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `source` / `aliases` | surface forms to look for in the source text |
| `policy` | `translate` · `do_not_translate` · `first_use_gloss` |
| `translations.<lang>.text` | the required rendering |
| `translations.<lang>.forbid` | renderings that must never appear |
| `scope` | fnmatch globs limiting where the term applies; omit for everywhere |

| `case_sensitive` | default `false`; set `true` for product names |
| `severity` | `error` blocks the run, `warn` does not |
| `notes` | appended to the prompt line; use it to disambiguate |

## Policies

- **`translate`** — the target text must contain `translations.<lang>.text`. This is the
  default and needs a translation entry for the active language, or the term is skipped.
- **`do_not_translate`** — the source form must appear verbatim in the target. Use for
  product names, CLI names, protocol names.
- **`first_use_gloss`** — with `"keep_source": true`, the first occurrence renders as
  `幂等 (idempotent)` and later ones as `幂等`. Useful for jargon a reader may not know.

`scope` uses fnmatch against the repo-relative path, so `**/*.md` matches `docs/a.md` but
**not** a root-level `README.md` — `**/` requires a directory component. Write
`["*.md", "**/*.md"]` to cover both, or omit `scope` entirely.

`forbid` is what actually stops drift. Requiring "技能" does not stop a later run from
producing "技巧" somewhere else in the document; listing "技巧" under `forbid` does.

## How it reaches the translator

At plan time, only the terms **matched in that specific chunk** are appended to that chunk's
prompt as a compact block:

```
TERMINOLOGY (must be respected exactly):
- skill -> 技能  (never use: 技巧, 本领)  // A Claude Code Agent Skill, not a general ability.
- Claude Code -> keep in English, do NOT translate
```

Subagents never see the whole table, so a large glossary costs nothing per chunk.

Matching ignores code: a term appearing only inside backticks is not treated as a prose
occurrence and is not required in the translation. Word boundaries are applied only when the
term starts or ends with an alphanumeric character, so CJK and symbol-bounded terms match by
substring.

## Violations

Reported by `verify` as `X-GLOSSARY`:

- required translation absent → `severity` from the term (default `error`)
- `do_not_translate` term missing from the target → `severity` from the term
- a `forbid` rendering present → always `warn`

A document that *discusses* terminology will trip its own glossary — a translation guide
that writes "use 技能, never 技巧" contains 技巧 and gets a `GL-ALT` warning. That is why
`forbid` findings are always `warn` and never block. Leave them; do not contort the prose to
silence them.

Changing the glossary does not by itself mark documents stale. To propagate a new or changed
term, re-run the affected files with `--all`, or delete their entries from `.claude/i18n/state.json`.
