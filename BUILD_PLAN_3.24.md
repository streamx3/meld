# Meld-Qt fresh build plan (targets Meld 3.24 behavior)

Supersedes the 1.4-targeted `PYQT_PORT_PLAN.md`. Basis: `DIVERGENCE_MAP_3.24.md`
(re-porting the 1.4 code costs 103–148 pd — *more* than a fresh build; the 1.4
`meldq/` tree taught us the Qt patterns, so we reuse the **patterns + harness + pure
utils** and design clean against the 3.24 spec). Reference trees on this branch:
`meld/` = Meld 3.24.0 (behavioral spec), `meldq/` = the 1.4 port (reference only).

## Locked decisions (owner-approved 2026-07-14)

- **Editor = QScintilla.** Gate spike PASSED on PyQt6 6.11 / Qt 6.11 / py3.14
  (`PyQt6-QScintilla 2.14.1`): lexer syntax highlighting, inline-diff **indicators**,
  and full-line chunk **background markers** all work headless. Diff overlays: inline =
  indicators, chunk backgrounds = line markers. This replaces the 1.4 QPlainTextEdit
  editor; the old chunk-paint overlay code does NOT carry over.
- **Theming (v1, minimal — not a time sink).** One built-in light + one dark palette
  feeding the diff overlays and Scintilla lexer styles. NO user color-picker UI. Full
  GtkSourceView style-scheme mapping deferred.
- **VC = git only for v1.** hg/svn/darcs/cvs/bzr deferred; the plugin contract is
  designed extensible so they slot in later (see backlog).

## v1 scope

| In v1 (the usable core) | Deferred (documented backlog) |
|---|---|
| Shell: window, tabs, New-Comparison, CLI open | single-instance/remote-CLI, recent-comparisons, shortcuts overlay |
| FileDiff: 2/3-way compare + merge (action-gutter), sync scroll, inline highlights, encoding load/save, **syntax highlighting**, on-disk-change reload | sync points, image diff, overview-map style variants |
| DirDiff: 2/3-way, 6-valued state, name+text filters, compare/copy/**trash-delete**, size/time cols | comparison markers, shallow-compare tuning |
| VcView: git — status, **compare-vs-repo**, commit, add/remove/revert/resolve, conflict 3-way | hg/svn/darcs/cvs/bzr, VC push/unstage niceties |
| Prefs: GSettings-aligned keys, minimal light/dark theme | user color pickers, full style-scheme system, meldrc/GSettings migration |
| Engine: 3.24-aligned | — |
| **Patch: export (3.24-style) + import/apply external `.patch` (headline, net-new)** | — |

## Reused as-is (proven by the green test suite)

Test harness (pytest-qt/offscreen/fixtures/workflow verification); the Qt **patterns**
(scheduler pump, no-modal-inside-a-generator → `QTimer.singleShot`, model lifetime /
widget-parenting); pure utils (`shell_to_regex` byte-identical, `gtk_mnemonic_to_qt`,
UTF-16 offset bridges, the QSettings `Value`/`Preferences` descriptor).

## Clean-build contracts (per subsystem, against 3.24)

- **Engine** — align to 3.24: `Differ` + `MyersSequenceMatcher` **with `postprocess()`**
  (adjacent-match coalescing → chunk counts match 3.24); `DiffChunk` namedtuple;
  `conflicts` list; `has_chunk`/`get_chunk_starts`/`paired_all_single_changes`;
  `diffs-changed(chunk_changes)`; empty-sequence guards; undo returns affected actions.
- **Editor** — `MeldSciView(QsciScintilla)`: chunk-bg markers, inline indicators, line
  numbers, read-only, per-buffer lexer, minimal theme; expose a line/offset API the
  differ + linkmap consume.
- **FileDiff** — 2/3-way; **ActionGutter** merge (hover copy/copy-up/copy-down, no
  linkmap icons); sync scroll (reuse the influence-map algorithm); go-to-chunk centers
  all panes; on-disk monitor + reload prompt; refuse blind overwrite.
- **LinkMap / ChunkMap** — connectors-only linkmap (curves, no icons); chunkmap overview
  with a you-are-here handle + drag scrub.
- **DirDiff** — 6-valued content state (+ FileError→STATE_ERROR); name filters + **byte**
  text filters (apply-text-filters toggle); size/mtime columns; trash-delete; scanning
  spinner; msgarea info/error bars; retain NORMAL folders (fix the 1.4 visibility bug).
- **VcView (git)** — plugin API: `get_valid_actions`, `refresh_vc_state`,
  `get_path_for_repo_file` (working-vs-repo compare, **replaces the GNU-patch trick**),
  `get_path_for_conflict` (3-way), a runner returning exit codes; commit dialog; move to
  trash. Contract shaped so hg/svn/… are drop-in.
- **Prefs** — keys aligned to `org.gnome.Meld` gschema (QSettings-backed); minimal theme
  keys; no color pickers.
- **Shell** — QActions (GAction-equivalent), tabs; **all-tabs scheduler** (fixes the 1.4
  bug where background scans stall on tab switch); New-Comparison; CLI dispatch.
- **Patch (headline)** — export dialog (3-pane side-select + reverse + diff highlight)
  AND **import/apply an external `.patch`** (net-new; neither 1.4 nor 3.24 has it).

## Build order — milestone-driven (working app early)

- **M0 — Foundation** (done/in-progress): plan + QScintilla spike ✓; add QScintilla dep;
  strip/park 1.4-only modules; re-point contracts.
- **M0.5 — Patch-import feasibility proof (FRONT-LOADED, owner priority)**: pure-Python
  unified-diff **parse + apply** core (no GNU `patch` dependency — key for Windows),
  with tests, proving the differentiator is feasible *before* the full app. The model:
  apply patch to source → present source-vs-patched in a normal FileDiff, so interactive
  hunk accept/reject reuses the merge UI. Core lands now; UI wiring in M5.
- **M1 — Walking skeleton**: Engine(min, 3.24-aligned) → `MeldSciView` → FileDiff **2-way
  view-only** → minimal Shell (open two files via CLI). *Milestone: "it opens and shows a
  syntax-highlighted diff."*
- **M2 — FileDiff complete**: 3-way, action-gutter merge, sync scroll, chunk ops, encoding
  load/save, reload-on-change, linkmap/chunkmap.
- **M3 — DirDiff**.
- **M4 — VcView (git)** incl. compare-vs-repo + conflict 3-way.
- **M5 — Patch** (export + import/apply) — the differentiator.
- **M6 — Prefs + theming polish; packaging (macOS `.app`, Windows) + hardening.**

Rough effort (from the map, scoped to v1, git-only): ~50–80 pd.

## Deferred backlog (post-v1, documented now)

hg/svn/darcs/cvs/bzr VC backends · ImageDiff · sync points · overview-map style variants ·
recent-comparisons manager · single-instance/remote-CLI · keyboard-shortcuts overlay ·
comparison markers · shallow-compare tuning · full style-scheme + dark-theme system ·
user color pickers · prefs migration from meldrc/GSettings · VC push/unstage.

## Non-goals
Not feature-for-feature 3.24 parity. Not GTK look-alike. No DE/OS coupling (no KDE libs).

---

## Progress log

**Branch `release-3_24_0_qt`, ~574 tests green, all pushed to fork
`git@github.com:streamx3/meld.git`.** Fresh code lives in `meldq/views/` +
`meldq/widgets/` + a few top-level `meldq/*.py` cores; the 1.4 `meldq/*.py`
(filediff/dirdiff/vcview/vc/) and the 3.24 `meld/` tree are REFERENCE only.

### Done
- **M0/M0.5/M1** — QScintilla editor spike; `meldq/patch.py` (pure-Python
  unified-diff parse+apply, no GNU patch; the headline differentiator's core);
  `meldq/widgets/sciview.py` `MeldSciView`; engine aligned to 3.24
  (`meldq/engine/matchers.py` postprocess+DiffChunk+guards, verified byte-
  identical to `meld/matchers/myers.py` in `tests/engine/test_matcher_vs_324.py`).
- **M2 (FileDiff) COMPLETE** — `meldq/views/filediff.py` `FileDiffView` (2- and
  3-way). Editable + live re-diff; undoable copy/delete merge; encoding-aware
  load/save; `meldq/views/linkmap.py` connectors; joined-region inline;
  ActionGutter click-merge; next/prev nav; **3-way via `Differ` with conflict
  detection**; on-disk reload via `meldq/widgets/infobar.py`. 2-way uses the raw
  Myers matcher; 3-way uses the Differ (pane 1 = base).
- **M3 (DirDiff) FUNCTIONAL** — `meldq/dircompare.py` (Qt-free `walk()` +
  tri-state `files_same` + per-pane states); `meldq/views/dirdiff.py`
  `DirDiffView` (tree, state colours, compare/copy/trash-delete, state filters,
  expansion preserved across refresh, opens FileDiff on a file).
- **M4 (VcView, git) FUNCTIONAL** — `meldq/gitvc.py` (Qt-free: find_repo_root,
  status, repo_file_content=HEAD bytes); `meldq/views/vcview.py` `VcView`
  (lists changes, opens working-vs-repository FileDiff).

Standalone runners exist per view (`python -m meldq.views.{filediff|dirdiff|vcview}`);
**there is no unifying app shell yet.**

### Remaining (rough order)
1. **M4 VC actions** — commit dialog, add/remove/revert/resolve, conflict 3-way.
2. **M5 Patch dialog** — a small UI over `meldq/patch.py`; import = open
   FileDiff(source, apply(source, patch)); export = the 3-pane side-select dialog.
3. **M6 the shell** — a real MeldWindow: tabs hosting the three views,
   New-Comparison dialog, CLI dispatch, prefs (GSettings-aligned keys), minimal
   light/dark theming, then **packaging (macOS .app, Windows)**. This is what
   makes it a shippable app.
4. **M3 polish** — scheduler-driven incremental scan (currently synchronous full
   walk + full-tree refresh, ok for normal trees), size/mtime columns, folder
   picker + filter UI.

### Known deferred refinements
- FileDiff: incremental re-diff (`Differ.change_sequence`) for large files
  (currently synchronous full re-diff per edit); inline offsets are char-based
  (non-ASCII needs UTF-16/byte mapping); inline chaff-reduction / InlineMyers;
  3-way merge is outer→base only (no base→side); theme-adaptive gutter arrows.
- No i18n yet in the fresh views (plain strings; gettext wiring is M6).
- Colours are hardcoded in `sciview.LIGHT/DARK`; no user pickers (per plan).
