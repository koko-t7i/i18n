"""Where this skill keeps its per-repository state.

State is grouped under the directory the agent harness already owns -- ``.claude/i18n/``
under Claude Code, ``.codex/i18n/`` under Codex -- rather than adding another top-level
dotdir. Which one applies is worked out by :func:`resolve_state_dir`.

Two caveats are handled here rather than left to chance:

*Splitting.* A repository translated under one harness and then opened under the other must
keep using the state directory it already has. Two ``state.json`` files cannot see each
other's chunk cache, so a split silently re-translates everything. An existing directory
therefore outranks the harness.

*Ignoring.* Some repos gitignore ``.claude/`` (or ``.codex/``) wholesale. ``state.json``
*must* be committed -- an ignored one silently makes every translated file look untranslated
on the next clone. So :func:`warn_if_ignored` checks and says so, and ``--state-dir`` exists
as the escape hatch.
"""

import os
import subprocess
import sys
from pathlib import Path

CLAUDE_DIR = ".claude/i18n"
CODEX_DIR = ".codex/i18n"
NEUTRAL_DIR = ".i18n"

#: Recognised on sight, in this order. ``.i18n`` is never chosen on its own -- it is the
#: documented ``--state-dir`` escape hatch, and repos that took it keep working untouched.
KNOWN_DIRS = (CLAUDE_DIR, CODEX_DIR, NEUTRAL_DIR)

#: Last resort, when nothing identifies the harness. Same directory this skill has always
#: used, so a repo that predates harness detection is unaffected.
DEFAULT_DIR = CLAUDE_DIR

_HARNESS_DIRS = {"claude": CLAUDE_DIR, "codex": CODEX_DIR}

#: A directory counts as "already in use" if either durable file is there. The glossary can
#: be seeded before the first ``plan`` run, so state.json alone is not enough to go on.
_MARKERS = ("state.json", "glossary.json")


class AmbiguousStateDir(ValueError):
    """Two or more known state directories exist and neither can be assumed to win."""


def detect_harness() -> str | None:
    """``"claude"``, ``"codex"``, or None when nothing says.

    ``I18N_HARNESS`` is set by ``run.sh`` from the path it was invoked through, which is the
    one signal that survives both harnesses symlinking this skill to the same repository.
    The environment variables are the fallback: Claude Code exports ``CLAUDECODE``, and
    ``CODEX_HOME`` is set in a configured Codex install.
    """
    declared = os.environ.get("I18N_HARNESS", "").strip().lower()
    if declared in _HARNESS_DIRS:
        return declared
    if os.environ.get("CLAUDECODE"):
        return "claude"
    if os.environ.get("CODEX_HOME"):
        return "codex"
    return None


def existing_state_dirs(root: Path) -> list[str]:
    """Known state directories under ``root`` that already hold state or a glossary."""
    root = Path(root)
    return [d for d in KNOWN_DIRS if any((root / d / m).is_file() for m in _MARKERS)]


def resolve_state_dir(root: Path, override: str | None = None) -> Path:
    """Absolute path to the state directory for ``root``.

    In order: an explicit ``--state-dir``; ``I18N_STATE_DIR``; the directory this repository
    already uses; the one belonging to the current harness; :data:`DEFAULT_DIR`.

    Raises :class:`AmbiguousStateDir` when the repository has more than one.
    """
    root = Path(root)
    override = override or os.environ.get("I18N_STATE_DIR") or None
    if override:
        p = Path(override)
        return p if p.is_absolute() else root / p

    found = existing_state_dirs(root)
    if len(found) > 1:
        raise AmbiguousStateDir(
            "more than one state directory exists in this repository: "
            + ", ".join(found)
            + "\n  they cannot share a chunk cache, so pick one explicitly: --state-dir <dir>"
        )
    if found:
        return root / found[0]

    return root / _HARNESS_DIRS.get(detect_harness() or "", DEFAULT_DIR)


def rel_state_dir(root: Path, state_dir: Path) -> str:
    try:
        return state_dir.relative_to(Path(root)).as_posix()
    except ValueError:
        return str(state_dir)


def is_git_ignored(root: Path, path: Path) -> bool:
    """True if git would ignore ``path``. False when git is unavailable or root is not a repo."""
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", str(path)],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def warn_if_ignored(root: Path, state_dir: Path) -> str | None:
    """Warn when the durable state files would be silently untracked.

    Returns the warning text (also written to stderr), or None.
    """
    if not is_git_ignored(root, state_dir / "state.json"):
        return None
    rel = rel_state_dir(root, state_dir)
    msg = (
        f"warning: {rel}/state.json is git-ignored.\n"
        f"         state.json is the translation lockfile and must be committed, or the next\n"
        f"         run in a fresh clone will treat every translated file as untranslated.\n"
        f"         Either un-ignore it in .gitignore:\n"
        f"             !{rel}/\n"
        f"             {rel}/work/\n"
        f"         or keep state elsewhere:  --state-dir .i18n"
    )
    sys.stderr.write(msg + "\n")
    return msg


def run_main(main) -> int:
    """Entry-point wrapper turning a state-directory clash into a plain exit-2 error."""
    try:
        return main()
    except AmbiguousStateDir as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2


def add_state_dir_arg(ap) -> None:
    ap.add_argument(
        "--state-dir",
        default=None,
        help=(
            "where to keep state.json/glossary.json/work "
            f"(default: the directory this repo already uses, else {CLAUDE_DIR} "
            f"under Claude Code and {CODEX_DIR} under Codex)"
        ),
    )
