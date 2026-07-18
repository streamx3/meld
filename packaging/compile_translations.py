#!/usr/bin/env python3
"""Compile the po/ catalogs into meldq/resources/locale/ for runtime use.

meldq loads gettext catalogs from ``meldq/resources/locale/<lang>/LC_MESSAGES/
meld.mo`` (see meldq.conf.locale_dir). The 50 upstream po/ catalogs keep the
"meld" domain and many msgids still match the fresh UI's strings, so compiling
them buys real (partial) translations. Compiled .mo files are NOT committed —
run this before packaging, or any time you want a translated dev run:

    python3 packaging/compile_translations.py      # needs msgfmt (gettext)
"""

import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PO_DIR = ROOT / "po"
OUT = ROOT / "meldq" / "resources" / "locale"


def main():
    if shutil.which("msgfmt") is None:
        sys.exit("msgfmt not found — install gettext "
                 "(brew install gettext / apt install gettext)")
    count = 0
    for po in sorted(PO_DIR.glob("*.po")):
        lang = po.stem
        dest = OUT / lang / "LC_MESSAGES"
        dest.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["msgfmt", "--output-file", str(dest / "meld.mo"), str(po)],
            capture_output=True, text=True)
        if result.returncode != 0:
            print(f"SKIP {lang}: {result.stderr.strip()}", file=sys.stderr)
            continue
        count += 1
    print(f"compiled {count} catalogs into {OUT}")


if __name__ == "__main__":
    main()
