#!/usr/bin/env bash
# Wrapper that supplies markdown-it-py to the Python entry points.
#
#   ./run.sh plan   --root . --lang zh-CN --paths 'README.md'
#   ./run.sh apply  --root . --run 20260816-071500
#   ./run.sh verify --root . --lang zh-CN
#   ./run.sh resource plan --root . --lang zh-CN --file locales/en.json
#
# uv is the expected way to run this: it pins the interpreter and supplies every dependency
# per-run, installing nothing globally. Without uv we fall back to a bare python3, which
# works as far as the libraries it happens to have -- markdown-it-py for accurate fence
# detection, pyyaml for YAML resource files. Missing markdown-it-py degrades to a regex
# scanner with a warning; missing pyyaml stops the YAML resource path rather than guessing
# at the syntax.
#
# The scripts need Python 3.13. uv fetches it if the system does not have it; the bare
# fallback checks, because a too-old interpreter otherwise fails somewhere in the middle of
# a run rather than before it starts.
set -euo pipefail

# Both harnesses symlink this skill to the same repository, so the resolved path cannot say
# which one is running. The path we were *invoked* through can: read it before resolving.
RAW="$(dirname "${BASH_SOURCE[0]}")"
HERE="$(cd "$RAW" && pwd -P)"

if [ -z "${I18N_HARNESS:-}" ]; then
  case "$RAW" in
    */.codex/*)  export I18N_HARNESS=codex ;;
    */.claude/*) export I18N_HARNESS=claude ;;
  esac
fi

if [ $# -eq 0 ]; then
  echo "usage: run.sh <plan|apply|verify|resource> [args...]" >&2
  exit 2
fi
cmd="$1"
shift

if command -v uv >/dev/null 2>&1; then
  exec uv run --quiet --python 3.13 --with markdown-it-py --with pyyaml \
    python "$HERE/i18n_${cmd}.py" "$@"
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)'; then
  echo "error: uv is not installed and the system python3 is older than 3.13." >&2
  echo "  install uv, which fetches its own interpreter: https://docs.astral.sh/uv/" >&2
  exit 2
fi

if python3 -c 'import markdown_it' >/dev/null 2>&1; then
  echo "note: uv not found; running on the system python3." >&2
  exec python3 "$HERE/i18n_${cmd}.py" "$@"
fi

echo "error: uv is not installed and the system python3 lacks markdown-it-py." >&2
echo "  install uv (recommended): https://docs.astral.sh/uv/" >&2
echo "  or:                       python3 -m pip install markdown-it-py pyyaml" >&2
exit 2
