# Packaging meldq (M6)

Freezes the app into a self-contained bundle with [PyInstaller]. PyInstaller
does **not** cross-compile — build the macOS `.app` on macOS and the Windows
`.exe` on Windows.

> Status: scaffolding. The spec below is complete and reviewed, but the actual
> bundle must be built (and code-signed) on each target OS; that step has not
> been run in CI yet.

## Prerequisites

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[package]"
```

`PyQt6-QScintilla` is a hard runtime dependency (declared in `pyproject.toml`)
and `packaging/meldq.spec` force-includes `PyQt6.Qsci`, since QScintilla ships
no standard PyInstaller hook.

## macOS `.app`

```
pyinstaller packaging/meldq.spec        # -> dist/Meld.app
open dist/Meld.app
```

Signing + notarising (needs an Apple Developer ID):

```
codesign --deep --force --options runtime \
  --sign "Developer ID Application: <NAME> (<TEAMID>)" dist/Meld.app
ditto -c -k --keepParent dist/Meld.app Meld.zip
xcrun notarytool submit Meld.zip --keychain-profile <PROFILE> --wait
xcrun stapler staple dist/Meld.app
```

## Windows `.exe`

```
pyinstaller packaging/meldq.spec        # -> dist/Meld/Meld.exe  (one-folder)
```

For a single-file `Meld.exe`, change the spec's `EXE(...)` to
`exclude_binaries=False` and pass `a.binaries`/`a.datas` into `EXE`, then drop
`COLLECT`/`BUNDLE`. One-folder starts faster and is the recommended default.

## Linux

Native install stays the packaging path of record:

```
pip install .
meldq
```

(A PyInstaller one-folder build works too, but distro packages/`pip` are
preferred on Linux.)

[PyInstaller]: https://pyinstaller.org/

## Translations

Compile the 50 upstream catalogs before packaging (they load from
`meldq/resources/locale/`, domain "meld"; many msgids match the fresh UI):

```
python3 packaging/compile_translations.py    # needs gettext's msgfmt
```

## Build status

The macOS `.app` build was exercised successfully on 2026-07-18
(pyinstaller 6.x, 80 MB bundle): `--version` works and the full GUI boots
offscreen with a live comparison. Windows remains unexercised.
