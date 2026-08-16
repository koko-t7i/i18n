#!/usr/bin/env bash
# Wrapper that supplies markdown-it-py to the Python entry points.
#
#   ./run.sh plan   --root . --lang zh-CN --paths 'README.md'
#   ./run.sh apply  --root . --run 20260816-071500
#   ./run.sh verify --root . --lang zh-CN
#   ./run.sh resource plan --root . --lang zh-CN --file locales/en.json
#
# markdown-it-py is the only third-party dependency. Everything still imports without it --
# the scripts fall back to a regex Markdown scanner and warn -- but fences nested inside
# blockquotes or list items are only detected correctly with the real parser.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

if [ $# -eq 0 ]; then
  echo "usage: run.sh <plan|apply|verify|resource> [args...]" >&2
  exit 2
fi
cmd="$1"
shift

if command -v uv >/dev/null 2>&1; then
  exec uv run --quiet --with markdown-it-py python "$HERE/i18n_${cmd}.py" "$@"
fi

if python3 -c 'import markdown_it' >/dev/null 2>&1; then
  exec python3 "$HERE/i18n_${cmd}.py" "$@"
fi

echo "error: neither uv nor markdown-it-py is available." >&2
echo "  install uv:            https://docs.astral.sh/uv/" >&2
echo "  or install the parser: python3 -m pip install markdown-it-py" >&2
exit 2
