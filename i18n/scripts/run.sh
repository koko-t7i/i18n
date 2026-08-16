#!/usr/bin/env bash
# Wrapper that supplies the vendored co-op-translator to the Python entry points.
#
#   ./run.sh plan   --root . --lang zh-CN --paths 'README.md'
#   ./run.sh apply  --root . --run 20260816-071500
#   ./run.sh verify --root . --lang zh-CN --json
#
# --prerelease=allow is REQUIRED: semantic-kernel pulls azure-ai-agents>=1.2.0b3, which uv
# refuses to resolve otherwise. --python 3.12 is REQUIRED: upstream pins >=3.10,<3.13.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
VENDOR="$(cd "$HERE/../.." && pwd -P)/vendor/co-op-translator"

if [ ! -f "$VENDOR/pyproject.toml" ]; then
  echo "error: vendored co-op-translator missing at $VENDOR" >&2
  echo "run: git -C \"$(cd "$HERE/../.." && pwd -P)\" submodule update --init --depth 1" >&2
  exit 2
fi

if [ $# -eq 0 ]; then
  echo "usage: run.sh <plan|apply|verify|resource> [args...]" >&2
  exit 2
fi
cmd="$1"
shift
exec uv run --quiet --python 3.12 --prerelease=allow --with "$VENDOR" \
  python "$HERE/i18n_${cmd}.py" "$@"
