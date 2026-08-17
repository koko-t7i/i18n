"""Make ``i18n/scripts/`` importable under pytest.

The suite is written for ``python -m unittest discover tests``, which does not load this
file -- that is why each test module still does the same ``sys.path`` insert itself. This
exists so ``pytest`` works too, without a second copy of the bootstrap in every module.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "i18n" / "scripts"))
