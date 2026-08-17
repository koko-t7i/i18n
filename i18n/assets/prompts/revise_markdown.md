Use this prompt instead of `translate_markdown.md` when the task file carries a
`previous_translation`. `plan` attaches one whenever a near-identical chunk was translated
before, so the work is an edit, not a translation.

The point is that settled prose stays settled. A short document is one chunk, so without
this a single changed word re-words the whole page — every reviewer then has to re-read a
translation that did not need to change.

---

You are updating an existing translation, not writing a new one.

**The previous source** is in `previous_source`. **Its approved translation** is in
`previous_translation`. **The new source** is in `source`. They differ by
`match_ratio` — close to 1.0 means very little changed.

1. Diff `previous_source` against `source`. Only those differences may change.
2. Start from `previous_translation` and edit it. Every sentence whose source did not
   change must come through **byte-identical**. Do not re-word it, do not improve it, do
   not "modernise" it. It was approved.
3. Write new target-language prose only for what genuinely changed, matching the
   surrounding register, punctuation and terminology of the text you are editing.
4. If the source removed something, remove its translation. If the source added something,
   add a translation in the right position.

Everything in the original translation prompt still applies — placeholders byte-identical,
Markdown structure unchanged, inline code verbatim, no commentary. The `prompt` field of
the task file carries it, including any terminology and style blocks.

Output is unchanged: write only

```json
{"chunk_id": "<chunk_id>", "translated_text": "..."}
```

to `result_path`, and touch nothing else.

> A caveat worth stating: `match_ratio` is measured on the *source* text. A high ratio
> means little changed, not that the old translation was good. If the previous translation
> is plainly wrong, fix it and say so in your report — but do not use "I would have phrased
> it differently" as a reason to rewrite.
