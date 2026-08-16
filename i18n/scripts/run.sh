#!/usr/bin/env bash
# Wrapper that supplies markdown-it-py to the Python entry points.
#
#   ./run.sh plan   --root . --lang zh-CN --paths 'README.md'
#   ./run.sh apply  --root . --run 20260816-071500
#   ./run.sh verify --root . --lang zh-CN
#   ./run.sh resource plan --root . --lang zh-CN --file locales/en.json
#
# uv is the expected way to run this: it supplies every dependency per-run and installs
# nothing globally. Without uv we fall back to a bare python3, which works as far as the
# libraries it happens to have -- markdown-it-py for accurate fence detection, pyyaml for
# YAML resource files. Missing markdown-it-py degrades to a regex scanner with a warning;
# missing pyyaml stops the YAML resource path rather than guessing at the syntax.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

if [ $# -eq 0 ]; then
  echo "usage: run.sh <plan|apply|verify|resource> [args...]" >&2
  exit 2
fi
cmd="$1"
shift

if command -v uv >/dev/null 2>&1; then
  exec uv run --quiet --with markdown-it-py --with pyyaml python "$HERE/i18n_${cmd}.py" "$@"
fi

if python3 -c 'import markdown_it' >/dev/null 2>&1; then
  echo "note: uv not found; running on the system python3." >&2
  exec python3 "$HERE/i18n_${cmd}.py" "$@"
fi

echo "error: uv is not installed and the system python3 lacks markdown-it-py." >&2
echo "  install uv (recommended): https://docs.astral.sh/uv/" >&2
echo "  or:                       python3 -m pip install markdown-it-py pyyaml" >&2
exit 2
