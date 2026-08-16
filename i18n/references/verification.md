# Verification and repair

Read this when `verify` exits 1 or `apply` rejects a file.

## Running it

```bash
run.sh verify --root . --lang zh-CN [--files README.md] [--strict] [--run-review] [--json]
```

Exit codes: **0** pass (warnings allowed) · **1** blocking findings · **2** usage/IO error ·
**3** nothing to verify (no recorded translations for that language).

`--run-review` additionally runs co-op-translator's own freshness/structure pass. It needs no
credentials. Its result appears under `coop_review` and does not by itself fail the run.

`--json` output carries `retry_files`, which feeds straight into the repair loop.

## Checks

| Code | Severity | Assertion |
|---|---|---|
| `X-PLACEHOLDER` | error | no `@@CODE_BLOCK_n@@`-style token survives in the output |
| `X-INLINE` | error | inline code spans are byte-identical multisets |
| `X-TOKEN` | error | prose placeholder tokens match (`{count}`, `{{v}}`, `${V}`, `%s`, `%(n)s`, `<0>`) |
| `X-HTML` | error | HTML tag multiset matches the source |
| `X-FENCE` | error | fence count, language tags, and code bodies all match |
| `X-LINK` | error | external URLs match verbatim; internal link count matches |
| `X-IMAGE` | error | image count matches |
| `X-HEADING` | error | heading level sequence matches element-wise |
| `X-CHATTER` | error | no model preamble ("here is the translation", "以下是翻译") |
| `X-MISSING` | error | the recorded translated file is gone |
| `X-ANCHOR` | warn | an internal anchor present in the source has no matching heading |
| `X-UNTRANSLATED` | warn | CJK target whose CJK character ratio is below 0.10 |
| `X-ORPHAN` | warn | translation exists but its source was deleted |
| `X-GLOSSARY` | error/warn | see `glossary.md` |

`X-INLINE` catches the failure mode nothing else does: `` `{count}` `` rendered as
`` `{数量}` ``, or a flag name like `` `--retries` `` translated. Inline code must be copied
character for character.

`X-HTML` is the safety net for the upstream CJK defect: co-op-translator rewrites `**bold**`
to `<strong>bold</strong>` for CJK targets and reports no warning. `i18n_apply.py` repairs
this automatically; if `X-HTML` still fires, the repair was skipped because the **source**
document already contained that tag, and a human should look at it.

## Repair loop

```bash
run.sh verify --root . --lang zh-CN --json > .claude/i18n/work/<run>/verify.json
run.sh plan   --root . --lang zh-CN --repair .claude/i18n/work/<run>/verify.json
# fan out the new tasks, then apply and verify again
```

`--repair` re-plans exactly the files with blocking findings, bypassing the chunk cache for
them so the bad translation is not reused.

When re-dispatching, put the specific finding in the subagent's prompt. "Placeholder
`{count}` was translated to `{数量}`; restore the literal token and translate only the
surrounding prose" fixes it; "try again" usually does not.

**Retry budget is 2.** After two failed repair rounds, stop. Report which files failed, which
check they failed, and what the expected/actual values were. Leave the last written version
in place rather than a half-repaired one, and tell the user it needs a human.

## Warnings you should usually not chase

- `X-UNTRANSLATED` on a file that is mostly code samples and API names is normal.
- `X-ANCHOR` fires whenever headings are translated, which is the point of translating them.
  Only act on it if the docs site actually relies on those anchors.
