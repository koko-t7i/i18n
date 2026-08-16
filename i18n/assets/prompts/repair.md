# Repair prompt template

Use this when re-dispatching a chunk that failed verification. Substitute the bracketed
parts. The point is that the subagent is told **exactly what was wrong**, not just to retry.

---

You are repairing a translation that failed a structural check. Do not re-translate from
scratch; make the smallest change that fixes the listed problems.

**Task file:** `[.i18n/work/<run>/tasks/<task_id>.json]`
Read it. `source` is the original text, `prompt` is the original translation instruction.

**What was wrong with the previous attempt:**

```
[paste the relevant findings from verify.json --- code, message, expected, actual]
```

For example, a finding of

```
X-INLINE  expected=['`{count}`']  actual=['`{数量}`']
```

means the literal token inside backticks was translated. Restore `` `{count}` `` exactly and
translate only the prose around it.

**Rules (unchanged from the original task):**

1. Keep every `@@CODE_BLOCK_n@@`, `@@INLINE_CODE_n@@`, `@@LINE_nnnn@@` token byte-identical.
2. Copy every inline code span verbatim. Never translate anything between backticks.
3. Keep Markdown structure identical: same heading levels, same list nesting, same table
   shape, same number of links and images, same URLs.
4. Do not introduce HTML tags that are not in the source.
5. Return no commentary and no code-fence wrapper.

**Output:** write only this JSON to `[result_path]`:

```json
{"chunk_id": "[chunk_id]", "translated_text": "..."}
```

Do not modify any other file.
