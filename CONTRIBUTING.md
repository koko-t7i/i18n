# Contributing

```bash
git clone git@github.com:koko-t7i/i18n.git && cd i18n
uv run --with ruff ruff check .
python3 -m unittest discover tests -v
```

Needs [`uv`](https://docs.astral.sh/uv/) and Python 3.13. `uv` fetches its own interpreter,
so the system one does not have to be current.

## Run the tests both ways

```bash
uv run --python 3.13 --with markdown-it-py --with pyyaml python -m unittest discover tests
uv run --python 3.13 --no-project python -m unittest discover tests   # bare interpreter
```

`markdown-it-py` gives CommonMark-accurate fence detection; without it `_md.py` falls back to
a regex scanner and four tests — the ones covering fences nested in blockquotes and list
items — skip themselves. Both paths ship to users, so both have to pass. CI runs both.

`pytest` works too (`uv run --with pytest pytest`), via `tests/conftest.py`. The suite itself
is plain `unittest` with no third-party dependencies, and should stay that way.

## Four things that will bite you

**`state.json` is a lockfile and must be committed.** `.claude/i18n/state.json` records the
source hash of every translated file. If it is missing or ignored, the next run in a fresh
clone sees every translation as `orphan` and re-translates the whole repo. The skill runs
`git check-ignore` and warns, but only if you read the warning.

**Never hand-edit a translated file.** `README.zh-CN.md` is generated. Editing it makes the
next `plan` report it as an `edited` conflict, which then needs `--force` to resolve, which
throws away your edit anyway. Change `README.md`, then re-run the skill:

```bash
./i18n/scripts/run.sh plan  --root . --lang zh-CN --paths 'README.md' --json
# dispatch the tasks in .claude/i18n/work/<run>/tasks/ to subagents
./i18n/scripts/run.sh apply  --root . --run <run_id>
./i18n/scripts/run.sh verify --root . --lang zh-CN
```

Commit the translation and `state.json` together. `plan` attaches the previous translation
itself when a chunk is a close enough match, so a task carrying `"mode": "revise"` should be
dispatched with `assets/prompts/revise_markdown.md` — a one-word source change must not
re-word the entire page. `i18n/SKILL.md` has the full subagent contract.

**Never let a state schema bump discard state.** `_state.SCHEMA` is 2; `READABLE_SCHEMAS`
lists every version still readable, and `load()` keeps anything on that list. Dropping an
old schema instead would make every repository that has ever used this skill re-translate
from scratch on the next run — silently, because the files still exist. Schema 1 chunk
values are bare strings and schema 2 values are `{"src", "tgt"}` pairs; both shapes coexist
in one file while a repo migrates. Add a compatibility test before you touch this.

**Changing chunk boundaries means bumping `CHUNKER_VERSION`.** It lives in
`i18n/scripts/_job.py`. Cached chunk translations are keyed on source text a different
chunker may never produce again, so an unbumped version serves stale chunks that no longer
line up. Bumping invalidates every cached translation in every repo using the skill — which
is the point, and the reason not to change chunking casually.

## Style

`ruff check .` must pass; the configuration is in `pyproject.toml` (line length 100, rules
`E,F,I,UP,B`). There is deliberately no formatter — the code aligns some things by hand.

Python 3.13 is the floor. No `from __future__ import annotations`, no compatibility shims.

The scripts are the part that must not be left to a model: they are where correctness is
enforced. Prefer failing loudly over guessing. Every check that can reject output has a code
(`X-*` for documents, `RES-*` for resources, `ASM-*` for reassembly) — new ones follow that
pattern and get a row in the README table.

Subjective checks are advisory, full stop. `X-STYLE` and everything from proofreading is
`warn` and stays `warn`: gating on a judgement call produces churn, not a finished
document. If a check cannot be stated as an assertion about the text, it does not block.
