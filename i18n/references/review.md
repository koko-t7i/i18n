# Revision and proofreading

`verify` asserts the translation is *shaped* like its source. Nothing in it asserts the
translation **means** what the source means, or that it **reads** like the target language.
Those are two different jobs, and professional practice keeps them apart.

ISO 17100 makes bilingual revision by a second person mandatory, and lists monolingual
proofreading separately. This skill mirrors that split:

| Pass | Sees | Judges | Blocking? |
|---|---|---|---|
| `revision` | source **and** translation | accuracy, terminology, audience fit | yes, on `major`/`critical` |
| `proofread` | **translation only** | fluency, style, locale conventions | never |

## Why the proofreader is not shown the source

This is the method, not an oversight. A sentence that maps neatly onto its source reads as
correct even when no native writer would phrase it that way — the source primes you to
accept it. Only a reader who cannot see the original notices that the text is translationese.

So `i18n_review.py` puts no `source` key in a proofreading task, and the prompt tells the
subagent it will not get one and must not reason about what it said.

The cost of that is real and accepted: a proofreader cannot tell a mistranslation from an
odd-but-faithful sentence. That is revision's job, which is why both exist.

## Commands

```bash
S=~/.claude/skills/i18n/scripts          # Codex: ~/.codex/skills/i18n/scripts

$S/run.sh review plan    --root . --lang zh-CN --mode revision --json
# ... fan out one subagent per file in <state-dir>/work/<run>/review/ ...
$S/run.sh review collect --root . --run <run_id> --json
```

`plan` reviews every file with a recorded translation for that language; `--files` limits
it. Pass `--run <id>` to attach the review to an existing translation run rather than
opening a new work directory.

`collect` normalises the results into the same shape `verify --json` emits, so repair is
the existing loop:

```bash
$S/run.sh plan --root . --lang zh-CN --repair <state-dir>/work/<run>/review.json
```

Exit codes: `0` clean · `1` blocking findings · `2` error or a missing result · `3` nothing
to review.

## Quality tiers

Revision and proofreading each cost one extra model call per file. That is the only part of
this skill that scales cost with quality, so it is a decision, not a default:

| Tier | Passes | Relative cost |
|---|---|---|
| draft | translate | 1x |
| standard | translate + revision | ~2x |
| publication | translate + revision + proofread | ~3x |

Translation memory and the style guide are not part of this trade — they cost nothing extra
and are always on.

Pick `draft` for a first pass at a large docs tree, `standard` when the translation will be
read by users, `publication` for a page that represents the project.

## The findings format

Subagents return MQM-style findings — the localisation industry's error typology:

```json
{"findings": [
  {"dimension": "accuracy", "subtype": "mistranslation", "severity": "major",
   "span": "<the exact translated text at fault>",
   "note": "<what the source says, and what the translation says instead>"}
]}
```

`collect` maps MQM severity onto this skill's two levels: `critical`/`major` become `error`,
`minor` becomes `warn`. The original is kept as `mqm_severity`.

**Proofreading findings are forced to `warn` regardless of severity.** Phrasing is a
judgement call, and a gate on judgement calls produces endless churn rather than a finished
document. They are for a human to act on, or not.

### Dimensions are enforced, not trusted

`revision` may only report `accuracy`, `terminology`, `audience`. `proofread` may only
report `fluency`, `style`, `locale`. A finding outside its pass's set is **discarded** and
listed under `rejected`.

The sets are disjoint on purpose. A reviser reporting fluency is duplicating the proofreader
with the source in view — which is exactly the anchored judgement the split exists to avoid.
Seeing rejections in the output usually means a pass was given the wrong prompt.

## What this does not do

**Back-translation** — translating the target back and comparing — is the recognised method
for verifying meaning without a bilingual reviewer, and it is standard in clinical and
regulatory work. It is not here: it roughly doubles cost again for a fraction of what a
bilingual reviser already catches, and technical documentation does not carry that risk.

**MQM scoring** — weighted penalties per thousand words, a quality score out of 100 — is
built for grading vendors and comparing suppliers. This skill borrows the typology and
leaves the arithmetic; a gate wants to know *which* sentence is wrong, not that the document
scored 94.
