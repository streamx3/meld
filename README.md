meldq — Meld, ported to PyQt6
=============================

**meldq** is a product-oriented port of [Meld](https://meldmerge.org/) — the
visual diff and merge tool — from GTK to **PyQt6 / QScintilla**. It compares
files, directories, and git working copies, and adds a headline feature neither
GTK Meld nor its 1.4 predecessor has: **importing and applying an external
`.patch`** as an interactive comparison.

This is a fork of GNOME Meld. The upstream GTK application lives in `meld/`
(kept as the behavioral reference); the PyQt6 application this repository builds
is the `meldq/` package. Licensed under the GPL v2 or later.

Requirements
------------

* Python 3.11+ (developed on 3.14)
* PyQt6 ≥ 6.8  (the shell drives light/dark theming via `QStyleHints`, added in
  Qt 6.8)
* PyQt6-QScintilla ≥ 2.14  (the editor component)

Install and run (from source)
-----------------------------

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/meldq                 # or: .venv/bin/python -m meldq
```

Usage:

```sh
meldq                           # empty window
meldq <file1> <file2> [<file3>] # 2- or 3-way file comparison
meldq <dir1> <dir2> [<dir3>]    # 2- or 3-way directory comparison
meldq <path>                    # version-control view of a git working copy
```

`File ▸ Import Patch…` applies a `.patch`/`.diff` against a chosen base
directory and opens each patched file as a comparison you can accept or reject
hunk by hunk. `File ▸ Create Patch…` exports a unified diff of the current
comparison.

What works
----------

* **FileDiff** — 2- and 3-way compare and merge, syntax highlighting, inline
  intra-line highlights, gutter click-merge, sync scroll, encoding- and
  EOL-preserving load/save (incl. UTF-8 BOM), atomic save, on-disk-change reload
  prompt, connector linkmaps.
* **DirDiff** — 2/3-way folder compare with a six-valued state model, compare /
  copy (symlink-preserving) / trash-delete with confirmation, VC-metadata dirs
  hidden by default.
* **VcView (git)** — status, working-vs-repository compare, commit, add / revert
  / remove (with confirmation for destructive actions), scoped to the opened
  directory.
* **Patch** — pure-Python unified-diff parse + apply (no GNU `patch`
  dependency), import and export.
* **Shell** — tabbed window, New-Comparison dialog, CLI dispatch, System /
  Light / Dark theming that follows the OS.

Testing
-------

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q
```

`QT_QPA_PLATFORM=offscreen` is required for headless runs. See `MANUAL_TESTS.md`
for the checks that need a real desktop.

Status and known limitations
-----------------------------

See `BUILD_PLAN_3.24.md` for the plan and progress, and
`REVIEW_FINDINGS_3.24.md` for the current review findings and their fixes.
Notably deferred: a name/text **filter UI** (a default `.git`/VC-dir filter is
applied), 3-way merge into a read-only patch-review pane, DirDiff size/mtime
columns, the chunkmap overview, and packaging (macOS `.app` / Windows `.exe`
scaffolding exists under `packaging/` but is not built in CI).
