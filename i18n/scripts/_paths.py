"""Where this skill keeps its per-repository state.

State lives in ``.claude/i18n/`` -- grouped under the directory that already exists for
agent config, rather than adding another top-level dotdir.

One caveat is handled here rather than left to chance: some repos gitignore ``.claude/``
wholesale. ``state.json`` *must* be committed -- an ignored one silently makes every
translated file look untranslated on the next clone. So :func:`warn_if_ignored` checks and
says so, and ``--state-dir`` exists as the escape hatch.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DEFAULT_DIR = ".claude/i18n"


def resolve_state_dir(root: Path, override: str | None = None) -> Path:
    """Absolute path to the state directory for ``root``."""
    root = Path(root)
    if override:
        p = Path(override)
        return p if p.is_absolute() else root / p
    return root / DEFAULT_DIR


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


def add_state_dir_arg(ap) -> None:
    ap.add_argument(
        "--state-dir",
        default=None,
        help=f"where to keep state.json/glossary.json/work (default: {DEFAULT_DIR})",
    )
