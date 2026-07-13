# Meld → PyQt6 Port: Execution Progress & Field Notes

Companion to [PYQT_PORT_PLAN.md](PYQT_PORT_PLAN.md) (the spec). This file tracks
**what is done**, the **environment**, **gotchas learned during execution**, and
**corrections to the plan** discovered while porting. Read this first when resuming;
it is the difference between re-discovering a day of pitfalls and not.

Branch: `pyqt-port`. New code lives in `meldq/`; the Python-2 tree in `meld/` is the
untouched behavioral spec.

---

## Status board

| WP | Scope | Status |
|---|---|---|
| WP0 | Scaffolding, pyproject, purity guard | ✅ done |
| WP1 | Gate spikes S1 (editor) / S2 (tree) | ✅ done — both PASS (verdicts in plan §WP1) |
| WP2 | Engine (matchers/diffutil/merge/undo/task) + pure util/misc | ✅ done |
| WP3 | App shell, prefs, CLI, dialogs (T3.1–T3.10) | ✅ done |
| WP4 | Shared widgets (treemodel/historycombo/msgarea/findbar) | ✅ done |
| WP5 | **Directory comparison (dirdiff)** | ⬜ **not started** |
| WP6 | File comparison (filediff/filemerge/linkmap/diffmap/editor) | ✅ done — all T6.1–T6.13 |
| WP7 | **Version control (vcview + vc/ plugins)** | 🟡 T7.1–T7.10 done (plugins + registry + VcView scan/actions/command pipeline); **resume at T7.11** (run_diff_iter/show_patch) |
| WP8 | i18n pipeline, packaging, desktop | ⬜ not started |
| WP9 | Hardening, parity audit, translation proof | ⬜ not started |

**376 tests pass, 4 skipped** as of WP7.10. Test count grows per task.

WP7 UI progress: T7.8 (`VcTreeModel`, `VcView` skeleton), T7.9 (scan/filters/
`next_diff`/selection) and T7.10 (10 command actions, `update_actions_sensitivity`,
doc/menu/toolbar contributions, context menu, **and the command-execution pipeline**
`_command_iter`/`_command`/`_command_on_selected` + `_surface_warnings`) are done in
`meldq/vcview.py`. **Re-slice vs plan:** T7.10 pulled in the command half of T7.11
(the buttons were otherwise dead), so **T7.11 is reduced to the diff/patch-viewing
half** — `run_diff_iter` + `show_patch` (replace the interim `run_diff` create_diff
stub). T7.12 CommitDialog is still pending (Commit button uses an interim
QInputDialog). Key trap honored: **zero modal dialogs inside generator frames** — the
command failure path uses a dismissable msgarea; a modal there would re-enter the
pump and re-enter the generator (ValueError: generator already executing).
Note the **git untracked-file quirk** surfaces in the UI: an untracked non-ignored
file shows as NORMAL (not Unversioned); Non-VC/Unversioned is tested via `_null`.

WP7 status: the entire **Qt-free vc/ layer is done** — `_vc` base (T7.2), the
five live plugins git/svn/mercurial/bzr/cvs (T7.3–T7.6), and the `_null`
backend + importlib registry (T7.7). Six dead 1.4 backends (cdv, darcs,
monotone, rcs, svk, tla) are descoped → fall through to `_null`. What remains
(T7.8–T7.13) is the **Qt UI**: `VcTreeModel`, `VcView` (combo/console/tree),
scan generator, VC actions (commit/add/remove/revert/update/diff), commit
dialog, and MeldWindow integration. All consume `DiffTreeModel` (WP4) + the
WP3 shell/scheduler contract. Adversarial verification of the plugins ran as
workflows (svn: 4 lenses; hg/bzr/cvs/null/registry: 7 lenses).

### Suggested next work
WP5 (dirdiff) or WP7 (vcview). Both consume `meldq/widgets/treemodel.py` (done, WP4) and
the WP3 shell contract (doc_actions/menu_contributions/toolbar_contributions,
SchedulerPump, MeldDoc). Neither unblocks new dependencies. WP8 needs all three views
present. Read the relevant WP section of the plan **and this file's "Plan corrections"**
before starting.

---

## Environment (reproduce exactly)

- Python **3.14.6** (plan floor is 3.11; `python3.12` also available via Homebrew as a
  fallback if PyQt6 wheels ever misbehave on 3.14).
- venv at **`.venv/`** (repo root). Activate implicitly by calling `.venv/bin/python`.
- **PyQt6 6.11 / Qt 6.11**. Installed: `PyQt6 pytest pytest-qt pytest-timeout pygments`.
- Recreate: `python3 -m venv .venv && .venv/bin/pip install -e ".[highlight,dev]"`.

### Running tests (READ THIS — headless Qt has traps)
```
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q
```
- **Always** set `QT_QPA_PLATFORM=offscreen` (conftest sets it too, but belt-and-suspenders
  for one-off `python -c`).
- **Gate commits on the real pytest exit code**, never on a piped `tail`. The Bash tool
  auto-backgrounds long/blocking runs; capture the exit code to a file:
  `... > /tmp/out.txt 2>&1; echo "EXIT=$?"` and check EXIT, not the tail.
- Use `--timeout=15` (pytest-timeout) so a hung modal dialog fails loudly instead of
  wedging the run. NB: the signal-based timeout **cannot** interrupt a C++ modal loop
  (`QDialog.exec`, native `QFileDialog`) — those still hang the whole process; the fix is
  to not trigger them in tests (see gotchas).
- `-p no:cacheprovider` avoids stale-cache surprises across rapid edits.

---

## Package layout (as built)

```
meldq/
  __init__.py (__version__="2.0.0a0")  __main__.py  main.py  conf.py
  app.py        MeldWindow, SchedulerPump, DocActionManager, NewComparisonDialog
  doc.py        MeldDoc(QObject), CloseResponse, Direction, RESULT_OK/ERROR
  prefsdialog.py  PreferencesDialog, FilterList  (built in CODE, not .ui)
  filediff.py   FileDiff + CachedSequenceMatcher/CursorDetails/MeldBufferData/
                CloseDialog/PatchDialog + module helpers position_at_line_or_eof/
                insert_text_at_line/text_between_lines/utf16_units/current_keymask,
                FakeText/FakeTextArray, MASK_SHIFT/MASK_CTRL
  filemerge.py  FileMerge(FileDiff)
  linkmap.py    LinkMap(QWidget)          diffmap.py  DiffMap(QWidget)
  engine/       matchers diffutil merge undo task   (undo/diffutil/merge use QtCore only)
  util/         misc.py (Qt-FORBIDDEN, test-enforced)  prefs.py (Preferences over QSettings)
  widgets/      editor.py historycombo.py msgarea.py findbar.py treemodel.py
  vc/           __init__.py only (empty) — WP7 fills it
  resources/icons/  tree-*.png (9), button_*.png (5), icon.png
  ui/           (empty — dialogs built in code; see deviation D7 note below)
tests/          per-WP test files; fixtures/ (lao tzu merge_* astral.txt encodings/ engine/)
```

Not yet created (WP5/WP7 will): `meldq/dirdiff.py`, `meldq/vcview.py`, `meldq/vc/*.py`
plugins. `meldq/vc/__init__.py` exists but is empty — `Preferences` filter default and
the shell's `append_vcview` lazy-import it and fall back gracefully (that fallback is
tested in `tests/test_action_manager.py::test_append_missing_module_warns`; WP7 should
retarget or update that test once vcview exists).

---

## Gotchas learned during execution (cost real debugging time)

1. **Modal dialogs hang headless tests.** `QDialog.exec()`, `QMessageBox.exec/question/
   warning`, native `QFileDialog.getSaveFileName` block forever offscreen. Symptoms:
   `timeout` kills pytest with EXIT=124, no per-test timeout message. Mitigations:
   monkeypatch the dialog (`monkeypatch.setattr(QMessageBox, "question", lambda *a,**k:
   QMessageBox.StandardButton.Yes)`), set `bufferdata.filename` before `save_file` so it
   doesn't prompt, and in **window fixtures clear every doc's `bufferdata[*].modified` and
   call `pump.stop()` before teardown** — otherwise qtbot's auto-`close()` runs
   `closeEvent` → the save-on-close `CloseDialog` → hang. (A modified `FileMerge` middle
   pane is the classic trigger.)
2. **Un-shown windows report nothing.** Qt does not deliver `resizeEvent` and returns
   `isVisible()==False` for widgets whose top-level window isn't shown. Tests must either
   `window.show(); qtbot.waitExposed(window)` or assert on `isVisibleTo(parent)` /
   `blockBoundingGeometry` rather than `isVisible()`.
3. **GC drops signal connections.** A `QObject` (e.g. a `MeldDoc`) whose only reference is
   a local variable gets garbage-collected and its `.connect()`s die silently. Hold a
   reference (assign to a var, add to a list, `qtbot.addWidget`).
4. **Protected methods on C++-created widgets.** `QScrollBar.initStyleOption` is protected;
   PyQt refuses it on the editor's built-in scrollbar ("no access to protected functions
   for objects not created from Python"). Build the `QStyleOptionSlider` manually via the
   public `opt.initFrom(sb)` + set `orientation/minimum/maximum/sliderPosition/sliderValue
   /singleStep/pageStep/rect`. (See `meldq/diffmap.py:_groove_rect_in_self`.)
5. **`QTextCursor.selectedText()` uses U+2029**, not `\n` and not a space. Every text
   extraction seam replaces `" "` → `"\n"` (module const `_PARAGRAPH` in filediff).
   The plan text literally shows `.replace(" ", "\n")` — that is a character-corruption of
   U+2029; use `" "`.
6. **QTextCursor positions are UTF-16 code units**, `str` indices are codepoints. They
   diverge at the first astral char (emoji, 𝕏). Bridge with `char_to_utf16_offset` /
   `utf16_to_char_offset` (util/misc) and `utf16_units` (filediff). Never index a Python
   `str` with a cursor position when astral chars are possible — test via
   `cursor.selectedText()` instead.
7. **`doc.blockCount()` counts a trailing newline as an empty final block.** Loading a
   file ending in `\n` yields `toPlainText()` ending in `\n` (blocks `[..., ""]`). Expected
   in tests; not a bug.
8. **`connect_after` has no Qt equivalent**, and re-declaring an inherited `pyqtSignal` on a
   subclass shadows it. `FileDiff` emits the MeldDoc-declared `current_diff_changed` /
   `next_diff_changed` / `file_changed` — it does NOT re-declare them.
9. **Stale `.pyc` after same-second reverts.** After a mutation-test that reverts a source
   file within the same second and at the same size, CPython may validate the old bytecode.
   `find meldq tests -name __pycache__ -type d -exec rm -rf {} +` if a revert "fails".
10. **`contentsChange` fires during `doc.undo()/redo()`** — re-diff must still run then;
    only undo *recording* is guarded (WP2). Never apply inline highlights via
    `mergeCharFormat` (mutates the doc → `contentsChange` → re-diff loop); use
    `setExtraSelections` (view-level, no signal).
11. **Fixtures must not clobber class/module state without restoring it.** The vc parser
    fixtures first did `git.Vc.check_repo_root = lambda ...` (a *class-level* rebind), which
    leaked into later files — by the time `test_vc_registry` ran, git/svn "matched" every
    directory and `get_vcs` returned extra plugins. It passed in isolation, failed in the full
    suite. Always use `monkeypatch.setattr(Cls, "attr", ...)` (auto-restored) for this, and
    sanity-check order-independence by running vc test files in a shuffled grouping.

---

## Plan corrections & deliberate deviations (a future executor MUST know)

These are places where the plan text was wrong, ambiguous, or where I deviated with reason.
None changed a §2 contract.

- **`text_between_lines` / selected-text:** plan shows `.replace(" ", "\n")`; correct is
  `.replace(" ", "\n")` (U+2029 corruption in the plan). Applied everywhere text is
  extracted (filediff `text_between_lines`, `get_selected_text`).
- **`DiffMap._groove_rect_in_self`:** plan calls `scrollbar.initStyleOption(opt)` — fails on
  C++ scrollbars. Build the option manually (gotcha #4).
- **`_update_highlighting` cache:** plan mandates an `_inline_ranges` replay for cached
  chunks. I simplified to **recompute selections every pass** (the expensive difflib call is
  still cached by `CachedSequenceMatcher`). Output is identical; ExtraSelections are rebuilt
  wholesale so there is nothing to "replay". `_inline_ranges` attr exists but is unused.
- **`_update_regexes`:** 1.4 appends `"(?m)"` to the pattern; trailing inline flags are an
  error on py3.11+. Use `re.compile(value, re.MULTILINE)` instead.
- **`save_file` when `bufferdata.encoding is None`** (never-loaded buffer): plan/1.4 fall
  through and would write a `str` to a `"wb"` handle (TypeError). Added an `else:
  data = text.encode("utf-8")` branch.
- **`make_patch`:** appends `"\n"` to each line before `difflib.unified_diff` so the patch is
  well-formed (1.4 passed newline-less lines).
- **Dialogs built in CODE, not `.ui`** (deviation from D7): `PreferencesDialog` (T3.10),
  `NewComparisonDialog` (T3.8), plus `CloseDialog`/`PatchDialog`. Rationale: hand-authoring
  Qt Designer XML without Designer is error-prone and the result is identical + more
  testable. `meldq/ui/` is empty. WP8 packaging should NOT expect `.ui` files.
- **Preferences dialog** gained an extra **Display tab** with colour pickers (the `color_*`
  prefs had no dialog UI in 1.4 because they were gconf-only; gconf is gone).
- **Task ordering nuance:** T3.8 (new-comparison dialog) was deferred until after WP4's
  `FileHistoryCombo` landed, then done between WP4 and WP6 (commit `6ed94e58`).
- **DiffMap/LinkMap were created minimally in WP6.2** (constructible stubs) and completed in
  T6.7/T6.8. WP5's dirdiff `DiffMap.setup(scrollbar, chunk_fn)` fraction path is implemented
  and tested (`test_diffmap.py::test_dirdiff_fraction_setup_still_paints`) — WP5 can rely on
  it.
- **`meldq/diffmap.py` already exists** (WP6 created it). The plan's T5.9 says "WP5 creates
  it" — instead, WP5 should EXTEND the existing file (it already has both the `setup()`
  fraction API for dirdiff and `setup_editor()` for filediff).

---

## Latent 1.4 bugs fixed + pinned (each has a regression test)

`merge.py:131` seq2 NameError · `undo.py:182` checkpoint IndexError · `task.py:87` no-op
`remove_scheduler` · `diffutil.py:311/316/332` `/2` float index · `historyentry.py:314`
dead `set_directory_entry` · `msgarea.py:72` `__actionarea` typo + `:242` mutable default ·
`findbar.py:88` replace-all infinite loop · `filediff.py:1032` save-as-UTF-8 fallback that
didn't re-encode · `filediff.py:1214/1219` map-for-side-effects pane show/hide ·
`filemerge.py:101/106` parenthesized-string membership · UTF-16 inline-offset drift ·
`git.py:85` pre-scan `update-index --refresh` via `popen` (no cwd, never awaited) → ran in
meld's own dir and read stale status; now `_vc.call([...], cwd=self.location)` (blocks, in
repo). **Quirk kept faithfully, NOT a bug:** the git scan surfaces *ignored* others only
(`ls-files --others --ignored`), so a plain untracked non-ignored file never enters the tree
cache and `tree.get(path, STATE_NORMAL)` shows it as NORMAL, not "unversioned" — pinned by
`test_vc_git.py::test_real_repo_states`.
`svn.py:112` dead dir-missing branch (a vanished path is never `isdir`, so svn's `!` surfaces
as a MISSING **File**) — kept verbatim, documented, pinned. `svn` property-only-mod lines and
CRLF `\r` are *shared quirks* with 1.4, pinned as parity by `test_secondary_column_lines_dropped_parity`.
`bzr.py:83` `cur_state` UnboundLocalError when the first status line is indented (orphan line
before any section header) → now `cur_state=None` guard skips it (`test_orphan_indented_line_before_header`).
`cvs.py` **cluster** (all pinned in `test_vc_cvs.py`): `(?m)` trailing flag = py3.11 re.error;
one-shot `map()` membership → silent misclassification (now a `set`); `open(...,'U')` removed in
3.11; stale `state` leak on unknown "dummy timestamp" rev → `STATE_ERROR`; unbound `ignore_re`
after a bad-`.cvsignore` re.error → `self.warnings` + `_DummyMatcher`. `_null.py:54` / `cvs.py:65`
`map()` concatenated into `dirs+files` = py3 TypeError → list comprehensions.

---

## Contract quick-reference (what WP5/WP7 code against)

- **Doc base:** subclass `meldq.doc.MeldDoc(QObject)`; set `self.widget` (composition, never
  multiple-inherit QWidget). Signals: `label_changed(str)`, `status_changed(str)`,
  `create_diff(list)`, `closed()`, `file_changed(str)`, `next_diff_changed(bool,bool)`,
  `current_diff_changed()`. Emit `self.label_changed.emit(self.label_text)`.
- **Action contract:** implement `doc_actions() -> list[QAction]`,
  `menu_contributions() -> {"file"|"edit"|"changes"|"view": [QAction|None]}` (`None`=sep),
  `toolbar_contributions() -> list[QAction]`. Actions parented to `self.widget`.
- **Scheduler:** `self.scheduler` (FifoScheduler). Add generator tasks as `gen.__next__`.
  Set `self.scheduler.paused = True/False` around any modal `exec()` raised from inside a
  scheduled generator (the pump skips paused schedulers).
- **Tree model:** `meldq.widgets.treemodel.DiffTreeModel(ntree=, extra_cols=)` with
  `STATE_*` constants, roles `ROLE_PATH/ROLE_STATE/ROLE_ISDIR`, `add_entries/add_empty/
  add_error/value_path(s)/set_state/get_state/rowpath/index_for_rowpath/inorder_search_
  down/up`, per-instance `text_styles`, `state_icons()`. Role-based styling in `data()`.
- **Widgets:** `FileHistoryCombo(history_id, directory_entry=, settings=)`,
  `MsgAreaController.new_from_text_and_icon(...)`, `FindBar.start_find/next/replace(editor)`.
- **Prefs:** `Preferences` attribute access + `changed(str)` signal; QSettings namespaces
  `prefs/`, `history/`, `migration/`. Colours are `#rrggbb` (feed straight to `QColor`).
- **i18n:** `from meldq.conf import _`; wrap every user string in `_()` with the EXACT 1.4
  msgid; convert GTK mnemonics with `misc.gtk_mnemonic_to_qt(_("_Label"))` (translate
  FIRST, then convert).
