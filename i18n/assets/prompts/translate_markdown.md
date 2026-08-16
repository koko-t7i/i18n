Translate the following Markdown into {language_name} ({language_code}).

STRICT RULES (NO EXCEPTIONS):

1. STRUCTURE
   - Preserve the exact Markdown syntax of the input.
   - Do NOT reformat, canonicalize, or "improve" the Markdown.
   - Same heading levels, same list nesting, same table shape, same blank lines.
   - Do NOT reorder lines, merge paragraphs, or split paragraphs.
   - Do NOT introduce HTML tags. If the source has HTML, keep it byte-for-byte and
     translate only the visible text inside it.

2. DO NOT TRANSLATE
   - Anything inside backticks. Inline code is copied character for character:
     a flag name, an identifier, a path, or a token like `{{count}}` stays exactly as-is.
   - URLs and file paths.
   - Placeholder tokens: `@@CODE_BLOCK_0@@` and similar. Reproduce every one of them
     exactly once, unchanged, in its original position.
   - Alert markers such as [!NOTE], [!TIP], [!IMPORTANT], [!WARNING], [!CAUTION].
   - Variable, function and class names.

3. OUTPUT
   - Return ONLY the translated content.
   - No ```markdown wrapper, no preamble, no "here is the translation", no commentary.

4. LINKS
   - Keep the link target unchanged; translate only the link text.
   - `[text](url)` stays `[translated text](url)`.
