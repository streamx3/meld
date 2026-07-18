# Manual smoke tests

Checks that can't (or shouldn't) be automated headless — run before shipping.
Automated coverage lives in `tests/`; this file is only for the things a human
needs to eyeball on a real desktop (Linux and macOS).

Setup:

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/meldq          # or: .venv/bin/python -m meldq
```

## FileDiff

1. `meldq a.txt b.txt` — the two files open side by side, differences coloured,
   syntax highlighted. Click a gutter arrow: the chunk merges into the other
   pane and the view **stays put** (no jump to end of file). `Ctrl+Z` undoes the
   merge. `Ctrl+D` / `Ctrl+E` move to the next / previous change (Ctrl+D must
   navigate, not duplicate a line).
2. Edit a pane, `Ctrl+S`. Confirm a latin-1 or CRLF file is written back in its
   original encoding / line endings, and a UTF-8-BOM file keeps its BOM.
3. Change a file on disk in another editor: a reload bar appears. Then modify
   the file externally and try to save — Meld should refuse to blindly
   overwrite and offer Overwrite / Reload.

## DirDiff

1. `meldq dir1 dir2` — the tree lists differing / new / missing files, coloured;
   `.git` and other VC-metadata directories are **not** shown. Activating a file
   present on only one side opens it against an empty pane.
2. Right-click a row: Copy and Delete. A delete goes to Trash; on a volume with
   no trash, it asks before deleting permanently. Copying a symlink keeps it a
   symlink.

## VcView (git)

Prep a repo with local changes:

```sh
git clone <any repo> /tmp/vc-smoke && cd /tmp/vc-smoke
echo change >> some-tracked-file
: > a-brand-new-file
```

Open it: `meldq /tmp/vc-smoke` (or File → New → Version Control).

1. **Scan + status.** The tree lists changed / new files, coloured by state,
   with a Status column. Opening a subdirectory lists only that subtree.
2. **Diff.** Double-click a modified file → a comparison opens showing the
   committed (HEAD) version on the left (read-only) vs the working copy on the
   right. A renamed file shows its old committed content, not an empty pane.
3. **Commit.** Select files, click **Commit…**, type a message, OK. The commit
   lands; a rename commits wholly (the old name is gone from HEAD). A commit
   error (e.g. no `user.email`) appears in the message bar, not as a crash.
4. **Add / Revert / Remove.** Revert of an untracked file and Remove both ask
   for confirmation before destroying anything. The selection survives the
   refresh that follows each action.
5. **Error surfacing.** With `git` missing (empty `PATH`) or the repo directory
   deleted while the tab is open, an action shows a message bar, never a crash.

A run that requires no git: `meldq <plain-dir>` shows "Not a git repository."

## Patch (the differentiator)

1. `File ▸ Import Patch…`, pick a `.patch` and a base directory. Each file opens
   as source-vs-patched. Accept as-is and `Ctrl+S` — the patched result is
   written to disk. Try a CRLF patch and a patch with a rename.
2. `File ▸ Create Patch…` on a comparison — Copy / Save the unified diff and
   confirm `git apply` accepts it.

## Theming

View ▸ Theme ▸ System / Light / Dark. In System mode, flip the OS appearance and
confirm the editors, trees, and chrome follow live.
