# Manual smoke tests

Checks that can't (or shouldn't) be automated headless — run before shipping a
work package. Automated coverage lives in `tests/`; this file is only for the
things a human needs to eyeball on a real desktop (Linux and macOS).

Setup:

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[highlight,dev]"
.venv/bin/meldq          # or: .venv/bin/python -m meldq
```

## WP7 — Version control view

Prep a repo with local changes:

```sh
git clone <any repo> /tmp/vc-smoke && cd /tmp/vc-smoke
echo change >> some-tracked-file
: > a-brand-new-file
```

Open it: `meldq /tmp/vc-smoke` (or File → New → Version Control).

Expected observable behavior:

1. **Scan + status.** The tree lists modified files, bold dark-red, with a
   "Modified" status column; the statusbar flashes `[repo] Scanning …` while it
   populates. Toggle **Show Ignored** / **Non VC** / **Normal** in the toolbar
   (or View → Version status) and confirm the visible set changes. Toggle
   **Flatten** off and confirm the Location column appears and the tree nests.
2. **Diff.** Double-click (or select + Compare) a modified file → a file
   comparison tab opens showing the committed version vs the working copy (fed
   from a temp patch checkout). "No differences found." appears as a
   non-modal message bar (not a dialog) for an unchanged file.
3. **Commit.** Select a file, click **Commit** → the VC Log dialog opens with a
   changed-files summary. Type a message; **Ctrl+Return** commits; the console
   pane echoes `git commit -m …` and its output. Re-open Commit and confirm the
   previous message is available in the **Previous Logs** picker and loads into
   the message box when selected.
4. **Console.** The arrow toggle at the bottom collapses/expands the console;
   right-click → **Clear** empties it. Quit and relaunch: the collapsed/expanded
   state persists (pref `vc_console_visible`).
5. **Multi-selection.** Select two rows, right-click on one of them → both stay
   selected and the popup's **Compare** diffs both.
6. **Error surfacing.** With a bad `.cvsignore` (CVS) or a missing VC binary,
   the error appears as a message bar / disabled combo entry, never a crash.

A run that requires no VCS binaries: `meldq <plain-dir>` falls back to the
"Null" backend — files show as Unversioned under the Non-VC filter and VC
actions are no-ops.
