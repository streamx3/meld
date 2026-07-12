"""Layering guard: engine and util modules must not depend on Qt widgets.

meldq.engine.matchers/merge/task and meldq.util.misc must import without
pulling in any part of PyQt6; meldq.engine.diffutil and meldq.engine.undo
may use QtCore (QObject/pyqtSignal) but never QtWidgets. The import probes
run in a subprocess because pytest-qt loads QtWidgets into this process.
"""

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

MELDQ_DIR = Path(__file__).resolve().parent.parent / "meldq"

NO_QT_MODULES = [
    "meldq.engine.matchers",
    "meldq.engine.merge",
    "meldq.engine.task",
    "meldq.util.misc",
]
QTCORE_ONLY_MODULES = [
    "meldq.engine.diffutil",
    "meldq.engine.undo",
]


def _skip_if_absent(module: str) -> None:
    if importlib.util.find_spec(module) is None:
        pytest.skip(f"{module} not yet ported")


def _probe(module: str, forbidden: str) -> int:
    code = (
        "import sys\n"
        f"import {module}\n"
        f"sys.exit(1 if any(m == {forbidden!r} or m.startswith({forbidden!r} + '.')"
        " for m in sys.modules) else 0)"
    )
    return subprocess.run([sys.executable, "-c", code]).returncode


@pytest.mark.parametrize("module", NO_QT_MODULES)
def test_no_qt_at_all(module):
    _skip_if_absent(module)
    assert _probe(module, "PyQt6") == 0, f"{module} imports PyQt6"


@pytest.mark.parametrize("module", QTCORE_ONLY_MODULES)
def test_no_qtwidgets(module):
    _skip_if_absent(module)
    assert _probe(module, "PyQt6.QtWidgets") == 0, f"{module} imports QtWidgets"


def test_util_misc_source_has_no_qt_import():
    src = MELDQ_DIR / "util" / "misc.py"
    if not src.exists():
        pytest.skip("meldq/util/misc.py not yet ported")
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".")[0] for alias in node.names]
            assert "PyQt6" not in names, "PyQt6 import in util/misc.py"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root != "PyQt6", "PyQt6 import in util/misc.py"
