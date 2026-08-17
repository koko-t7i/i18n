# Style guide

Optional, like the glossary. Without one, translation still works; the *style* drifts
between runs the way terminology drifts without a glossary.

Lives at `<state-dir>/style.json` and **should be committed**. Seed it by copying
`assets/style.example.json`.

The glossary fixes individual words. This fixes everything between them.

## Schema

Top level is one object per language tag. `schema` is the only reserved key.

```jsonc
{
  "schema": 1,
  "zh-CN": {
    "audience": "开发者，习惯阅读中文技术文档",
    "register": "简洁、技术、不用营销腔；祈使句直述，不加语气助词",
    "address": "你",
    "quotes": "「」",
    "dash": "——",
    "cjk_latin_space": true,
    "headings": "名词短语，不用动宾结构",
    "unknown_terms": "keep_english",
    "locale": {"numbers": "保持原文格式", "dates": "保持原文格式", "units": "不做换算"}
  }
}
```

| Field | Meaning |
|---|---|
| `audience` | who reads this; the single most useful line, because it settles a dozen smaller questions |
| `register` | tone and formality |
| `address` | how to address the reader — `你` / `您` / impersonal |
| `quotes` | `「」` or `“”`; **checked** |
| `dash` | the dash form to use |
| `cjk_latin_space` | space between CJK and Latin/digits; **checked** |
| `headings` | heading construction |
| `unknown_terms` | default for terms not in the glossary: `keep_english` · `translate` · `gloss_on_first_use` |
| `locale` | numbers, dates, units |

Unrecognised string fields are passed through to the prompt verbatim, so a repository can
state a convention this skill has never heard of and it still reaches the translator.

`zh-CN` falls back to `zh` when no exact match exists, so one entry can cover a family.

## How it reaches the translator

`style_prompt()` renders a compact block appended to every chunk prompt, right after the
terminology block:

```
STYLE (this repository's conventions for this language):
- Audience: 开发者，习惯阅读中文技术文档
- Address the reader as: 你
- Quotation marks: 「」
- Space between CJK and Latin/digits: yes
- Terms absent from the glossary: leave in English
Follow these even where the source does something different -- they are
target-language conventions, not properties of the source.
```

That last sentence matters. The source is English and uses `"`; the translation should not
inherit it. Without the instruction, translators reproduce source punctuation.

The same block is given to the reviewer and the proofreader, so all three passes are
judging against one definition rather than three private opinions.

## What is checked, and what is not

Three conventions can be asserted from the text alone. `verify` reports them as `X-STYLE`,
always as **warnings** — a style slip is worth surfacing, never worth refusing to write the
file over.

| Checked | How |
|---|---|
| quotation system | counts the other system's marks when `quotes` is set |
| CJK/Latin spacing | finds adjacencies when `cjk_latin_space` is true |
| half-width punctuation between CJK | `,;:!?` bounded by CJK on both sides |

All three run on code-masked text, so identifiers, fenced blocks and URLs are exempt —
`run.sh plan --root .` is full of unspaced punctuation and none of it is a style finding.

Everything else in the file — register, audience fit, heading construction — is
**unverifiable by a script**. It reaches the translator as an instruction and the
proofreader as a criterion, and that is the whole enforcement.

## Changing it later

Editing `style.json` does not mark documents stale, exactly like editing the glossary. The
chunk cache is keyed on `sha256(chunk.source)`, which does not include the prompt — so a new
style block costs nothing and invalidates nothing, and equally does not retroactively apply.

To propagate a changed convention, re-run the affected files with `--all`.
