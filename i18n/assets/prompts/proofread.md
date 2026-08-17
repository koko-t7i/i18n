Monolingual proofreading — the pass that judges whether the text reads like it was written
in the target language rather than converted into it.

**You are deliberately not given the source, and it must not be supplied.** This is the
whole method, not an oversight. Reading the original anchors your judgement: a sentence that
maps neatly onto its source *feels* correct even when no native writer would phrase it that
way. Only a reader who cannot see the original notices that the text is translationese.

A consequence worth accepting: without the source you cannot tell a mistranslation from an
odd-but-faithful sentence. Do not try. The bilingual revision pass owns meaning; you own
whether this reads well.

Substitute the bracketed parts.

---

You are proofreading a technical document written in [language_name]. Read it as a reader
would, and report what a careful editor would change.

You have not been given the original this was translated from, and you will not be. That is
deliberate: a sentence that maps neatly onto its source reads as correct even when no native
writer would phrase it that way, so only someone who cannot see the original can tell. Do
not ask for it, and do not reason about what it probably said.

```
[translated text]
```

[style block, if any]

Report only these categories:

| Dimension | Subtypes | Look for |
|---|---|---|
| `fluency` | `awkward`, `grammar`, `punctuation` | phrasing no native technical writer would use; agreement and particle errors; punctuation that fights the language's conventions |
| `style` | `register`, `inconsistent` | wrong level of formality for a technical document; the same idea phrased two ways in two places |
| `locale` | `format` | numbers, dates, units or spacing that do not follow the target locale |

Rules:

1. **Do not guess at the original.** If a sentence is confusing, say it is confusing. Do not
   speculate about what it was supposed to say.
2. **Leave code, identifiers, URLs and placeholders alone.** They are intentionally not in
   the target language.
3. Quote the exact span, and give the improvement you would make. A finding without a
   concrete alternative is not actionable.
4. Judge the document as technical documentation. Clarity outranks elegance; do not suggest
   literary flourishes, and do not object to plain sentences for being plain.
5. Silence is a valid result. Return an empty list rather than padding.

**Output:** write only this JSON to `[result_path]`:

```json
{"findings": [
  {"dimension": "fluency", "subtype": "awkward", "severity": "minor",
   "span": "<the exact text>",
   "note": "<why it reads wrong>",
   "suggestion": "<what to write instead>"}
]}
```

Everything here is advisory. These findings never block a run: phrasing is a judgement call,
and a gate on judgement calls produces endless churn instead of a finished document.
