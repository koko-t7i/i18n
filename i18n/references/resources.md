# Resource files (JSON / YAML / .properties / PO)

A separate path from Markdown. No chunking and no Markdown parsing — the unit is a key, and
the structural contract is that the key set never changes.

```bash
S=~/.claude/skills/i18n/scripts
$S/run.sh resource plan   --root . --lang zh-CN --file locales/en.json
# fan out subagents over .claude/i18n/work/<run>/tasks/
$S/run.sh resource apply  --root . --run <run_id>
$S/run.sh resource verify --root . --lang zh-CN --file locales/en.json
```

## Unit model

Nested structures are flattened to dotted keys; only **string leaves** are translatable.

```jsonc
{"app": {"title": "Hello", "greet": "Hi {name}"}, "retries": 3}
// -> {"app.title": "Hello", "app.greet": "Hi {name}"}     retries is not a string, so it is untouched
```

List items become `key[0]`, `key[1]`. On write, the original structure is rebuilt and
non-string values are copied through unchanged.

| Format | Read | Write |
|---|---|---|
| `.json` | `json` | re-serialised, 2-space indent, `ensure_ascii=false` |
| `.yaml` / `.yml` | `pyyaml` **required** | `safe_dump`, `allow_unicode`, key order preserved |
| `.properties` | line grammar | line-by-line substitution, comments and blank lines preserved |
| `.po` / `.pot` | `msgid`/`msgstr` pairs | `msgstr` substituted, `msgid` untouched |

`run.sh` supplies `pyyaml` through `uv`, so the YAML path works out of the box. On a system
`python3` without it, that path **refuses to run** rather than hand-parsing — a wrong guess
silently corrupts a config file, which is worse than stopping.

## Subagent contract

Tasks batch up to 60 keys. The subagent receives an `entries` object and must return a JSON
object with **exactly the same keys**:

```jsonc
{"entries": {"app.title": "你好", "app.greet": "你好 {name}"}}
```

Rules stated in the prompt: never translate, rename, add or remove a key; preserve every
placeholder exactly; preserve `\n` / `\t` and their counts; translate only human-readable
text.

## Checks

| Code | Severity | Assertion |
|---|---|---|
| `RES-KEYSET` | error | leaf key sets are identical — nothing added, removed or renamed |
| `RES-PLACEHOLDER` | error | placeholder multiset matches per value |
| `RES-ESCAPE` | error | `\n` and `\t` counts match per value |
| `RES-EMPTY` | error | no empty target where the source was non-empty |
| `RES-MISSING` | error | a key has no translation at all |

`apply` runs these **before writing** and refuses to write on any error, so a broken
translation never lands on disk. `--force` overrides, but there is rarely a good reason.

## Not covered

Docs-site config (`mkdocs.yml` nav, `docusaurus.config.js`) is not handled. For Docusaurus,
translate `i18n/<locale>/**.json` instead — that is a resource file and fully supported. For
mkdocs, nav titles must currently be edited by hand; treat a request to automate that as
out of scope and say so.

ICU plural forms (`{n, plural, one {...} other {...}}`) pass through as ordinary strings.
The placeholder check protects the outer braces, but the keyword arms are not validated —
review those by hand if the project uses them heavily.
