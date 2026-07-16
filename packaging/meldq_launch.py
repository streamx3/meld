"""Frozen-app entry point for PyInstaller (macOS .app / Windows .exe).

Kept separate from meldq/__main__.py so the bundle has a stable, importable
launch script that PyInstaller can analyse.
"""

import sys

from meldq.main import main

if __name__ == "__main__":
    sys.exit(main())
