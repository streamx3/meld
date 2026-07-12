# Meld → PyQt6 Port: Execution Playbook

**Target executor: Claude Opus 4.8 (or equivalent agent), working in this repository.**
**Decision record and survey background: [PYQT_MIGRATION_PLAN.md](PYQT_MIGRATION_PLAN.md) — read it first, once, in full.**

## 0. Read this first (operating instructions for the executing agent)

You are porting Meld 1.4.0 — a Python 2 + PyGTK/GTK2 visual diff/merge tool — to
Python 3.11+ and PyQt6. This document is the complete work breakdown. The strategic
rationale, GTK→Qt mapping tables, and risk register live in PYQT_MIGRATION_PLAN.md;
this document is the *how*, in commit-sized tasks.

Rules of engagement:

1. **The old tree is the spec.** `meld/`, `bin/`, `data/` stay untouched; new code goes in
   `meldq/` + `tests/` as laid out in §2. When in doubt about behavior, read the 1.4
   source — every task cites the old code by `file:line`.
2. **Work in task order within a WP; respect the WP dependency graph (§3).** Each task
   T*n.m* is one commit: `WP<n>.<m>: <imperative summary>`. Do not batch tasks into one
   commit; do not start a WP whose dependencies haven't landed.
3. **Every task ends green.** Run `python -m pytest tests/ -x -q` before each commit; a
   task is not done until its acceptance criteria pass plus the whole existing suite.
   For UI tasks, also do the manual launch check the task specifies (`python -m meldq ...`).
4. **Traps are mandatory reading.** Each task's TRAPS list cites known silent-breakage
   sites (`map()` laziness, `/` vs `//`, PEP 479, bytes/str). When you port a cited line,
   verify the trap is addressed; several of them import fine and fail only at runtime,
   far from the cause.
5. **Latent 1.4 bugs listed in tasks are fixed, not preserved** — each fix gets a
   regression test in the same commit.
6. **Do not redesign the contracts (§2).** Signal names, class names, module layout, and
   the doc/shell action interface are settled. If a contract turns out to be genuinely
   unimplementable, stop and report — don't improvise a replacement.
7. **String discipline for i18n:** every user-visible string is `_( "..." )` with the
   *exact* English wording from the 1.4 sources/glade files (task instructions quote
   them). This preserves 34 existing translation catalogs. Do not "improve" wording.
8. **No porting commentary in code.** No comments like "was gtk.TextView" or "ported
   from filediff.py". Write idiomatic PyQt6 as if greenfield; git history carries the
   provenance.
9. **When a spike (WP1) fails its pass criteria, stop.** S1/S2 exist to invalidate
   assumptions cheaply; escalate to the user with findings rather than pushing through.
10. **Scope guard:** Linux + macOS; Windows deferred. Descoped VCS plugins (tla,
    monotone, cdv, svk, darcs, rcs), help/ subsystem, and gconf desktop integration are
    *decisions*, not oversights — do not resurrect them.

Definition of done for the whole port (checked in WP9): `python -m meldq <two files>`,
`<three files>`, `<two dirs>`, and `<a git checkout>` each open the correct comparison
view; edits re-diff live; chunk merge/undo/save round-trip correctly; the engine test
corpus and all widget tests pass; the msgmerge check reports zero orphaned msgids.

---
## 1. Background and current state

The repo is checked out at tag `release-1_4_0`: Meld 1.4.0, ~9,900 LOC of Python 2 +
PyGTK/GTK2, six glade-2 UI files, four GtkUIManager XML files, a hand-written Makefile,
gettext/intltool i18n with 34 catalogs. A full-source survey (per-file GTK touchpoints,
190 GTK→Qt mappings, risk register, decisions D1–D12) lives in
[PYQT_MIGRATION_PLAN.md](PYQT_MIGRATION_PLAN.md). The port target is **Python 3.11+ and
PyQt6 ≥ 6.6** on Linux + macOS. Total estimated effort: **~66–99 person-days** (§3).

Two facts shape everything below. First, the codebase is cleanly layered: the diff/merge
engine and VC plugins are nearly toolkit-free and port almost verbatim; the cost is in
views and infrastructure. Second, this is a cutover, not an in-place migration — PyGTK
does not exist on Python 3, so new code goes to a parallel package (`meldq/`) and the old
tree remains in-repo, untouched, as the behavioral spec.

## 2. Target architecture and normative contracts

These contracts are **settled design** — every work package codes against them exactly.
If one proves genuinely unimplementable, stop and escalate (operating rule 6).

### 2.1 Package layout

```
meldq/__init__.py            __version__ = "2.0.0a0" (single source of version truth)
meldq/conf.py                gettext init (exposes _, ngettext), resource paths via importlib.resources
                             (WP0 ships a stub; WP3 completes locale binding)
meldq/main.py                QApplication entry point (console_script "meldq"); replaces bin/meld
meldq/app.py                 MeldWindow(QMainWindow): QTabWidget of docs, menus/toolbar,
                             statusbar+progress, DocActionManager, SchedulerPump, dialogs
meldq/prefsdialog.py         PreferencesDialog (T3.10)
meldq/doc.py                 MeldDoc(QObject) base (+ Direction enum)
meldq/filediff.py            FileDiff (1/2/3-pane text comparison)
meldq/filemerge.py           FileMerge(FileDiff)
meldq/dirdiff.py             DirDiff
meldq/vcview.py              VcView
meldq/linkmap.py             LinkMap(QWidget): bezier chunk connectors + clickable action icons
meldq/diffmap.py             DiffMap(QWidget): overview bar (created in WP5, extended in WP6)
meldq/engine/{matchers,diffutil,merge,undo,task}.py
meldq/vc/{__init__,_vc,_null,git,svn,mercurial,bzr,cvs}.py   (tla/monotone/cdv/svk/darcs/rcs descoped)
meldq/widgets/editor.py      DiffTextEdit(QPlainTextEdit)
meldq/widgets/historycombo.py HistoryCombo, FileHistoryCombo
meldq/widgets/msgarea.py     MsgArea + MsgAreaController
meldq/widgets/findbar.py     FindBar(QWidget)
meldq/widgets/treemodel.py   DiffTreeModel + traversal helpers (shared dirdiff/vcview)
meldq/util/misc.py           pure helpers — Qt imports FORBIDDEN (created WP2; WP4/WP7 append idempotently)
meldq/util/prefs.py          Preferences(QObject) over QSettings
meldq/resources/icons/       PNG icons (XPMs converted)
meldq/locale/<lang>/LC_MESSAGES/meld.mo   compiled catalogs (gitignored build artifact; WP8 T8.5)
meldq/ui/*.ui                Qt Designer files for STATIC dialogs only; dynamic views are code-built
spikes/                      WP1 spike scripts (never imported by meldq/)
tests/                       pytest + pytest-qt; tests/fixtures/ golden corpus
pyproject.toml               PEP 621; requires-python ">=3.11"; deps PyQt6>=6.6; extra "highlight": pygments
```

### 2.2 Classes and signals (exact names)

| Class | Signals / key API |
|---|---|
| `engine.diffutil.Differ(QObject)` | `diffs_changed = pyqtSignal()` |
| `engine.undo.UndoSequence(QObject)` | `can_undo_changed(bool)`, `can_redo_changed(bool)`, `checkpointed(object, bool)` (object = QTextDocument); `register_document`, `begin_group`/`end_group`, `undo`/`redo`, `checkpoint(doc)`, `clear()` |
| `doc.MeldDoc(QObject)` | `label_changed(str)`, `status_changed(str)`, `create_diff(list)`, `closed()`; owns `scheduler`, `prefs`, `undosequence`, `num_panes`, `label_text`; `Direction` enum lives in `meldq/doc.py` |
| `util.prefs.Preferences(QObject)` | `changed = pyqtSignal(str)` (pref name); typed accessors; QSettings("meldq","meldq"), IniFormat |

### 2.3 Undo redesign (normative — replaces GTK before-delete capture)

QTextDocument-native undo is adopted. `UndoSequence` keeps its public API but is rebuilt
as a cross-pane coordinator: it listens to `QTextDocument.undoCommandAdded` on every
registered document (fires exactly once per undo step) and appends that document to its
ordered stack; `undo()` pops and calls `document.undo()` (redo symmetric), with a guard
flag suppressing re-recording during its own undo/redo. `begin_group`/`end_group` map to
`beginEditBlock`/`endEditBlock` on the single document being edited (multi-document
groups are asserted out — 1.4 never needed them). Checkpoints record per-document stack
height; the modified flag is height-vs-checkpoint, emitted via `checkpointed(doc, bool)`.
Consequence: the old `BufferAction`/insert-text/delete-range machinery is **not ported**;
re-diffing on edit uses `contentsChange(position, removed, added)` plus tracked per-pane
`blockCount()` deltas to compute `(startline, sizechange)` for `Differ.change_sequence`.

### 2.4 Doc/shell action contract (replaces gtk.UIManager merging)

Each doc implements `doc_actions() -> list[QAction]`,
`menu_contributions() -> dict[str, list[QAction]]` (keys `"file"|"edit"|"changes"|"view"`,
`None` entries = separators), and `toolbar_contributions() -> list[QAction]`. MeldWindow
owns fixed menus (File, Edit, Changes, View, Help), each with a placeholder section
bounded by named separators; `DocActionManager` clears and repopulates the placeholder
sections and the doc segment of the toolbar on `QTabWidget.currentChanged`. Shortcuts on
doc actions are active window-wide while their doc is current.

### 2.5 Scheduler contract

`engine/task.py` stays pure Python (no Qt import). The 1.4 `runnable` callback list
becomes a plain `runnable_cb` attribute. `app.SchedulerPump(QObject)` owns a
`QTimer(interval 0)`; it pumps only the **current tab's** scheduler, one
`scheduler.iteration()` per tick, stops when `tasks_pending()` is false, restarts from
`runnable_cb`. Docs raising modal dialogs from inside scheduled generators set
`scheduler.paused` around `exec()` (the pump skips paused schedulers).

### 2.6 Tree model contract (shared dirdiff + vcview)

`widgets.treemodel.DiffTreeModel(QStandardItemModel)`, **one column per pane**. Roles:
`ROLE_PATH = Qt.ItemDataRole.UserRole + 1` (str | None), `ROLE_STATE = UserRole + 2`
(int, `STATE_*` constants carried over verbatim from `meld/tree.py`),
`ROLE_ISDIR = UserRole + 3` (bool); WP5 adds `ROLE_NEWER` additively.
Foreground/Font/Decoration are computed from `ROLE_STATE` inside `data()` (a state →
QColor/QFont table replacing Pango markup). No markup strings in the model, no HTML
delegates. Row addressing: `rowpath(index) -> tuple` and `index_for_rowpath(tuple)`;
`QPersistentModelIndex` wherever rows are mutated while iterating.

### 2.7 Editor contract

`widgets.editor.DiffTextEdit(QPlainTextEdit)`: geometry helpers `line_ypos(line)` and
`lines_visible()` built on `firstVisibleBlock`/`blockBoundingGeometry`/`contentOffset`;
chunk backgrounds painted in `paintEvent` on the viewport **before** `super()`; inline
char-level highlights via ExtraSelections; `keyPressEvent` swallows
Ctrl+Z/Ctrl+Shift+Z/Ctrl+Y (undo is window-level through `UndoSequence`); overwrite mode
via native `overwriteMode()`. Word wrap is OFF in the initial port (recorded deviation).

### 2.8 i18n

`from meldq.conf import _` everywhere; every user-visible string uses the **exact**
English wording from the 1.4 sources/glade so the existing 34 catalogs keep matching
(verified by WP8's msgid check, gated in T9.5).

### 2.9 Global rules

Python 3.11+, PyQt6 only. No threads — engine and scheduler live on the GUI thread.
Preserve the cooperative generator protocol (`yield None …` final value; consume with
`next()`; PEP 479 — never let StopIteration escape). The old code is the behavioral
spec; deviate only where a task explicitly says redesign/delete/fix. Latent 1.4 bugs
listed in tasks are fixed with regression tests. Linux + macOS; Windows deferred.

## 3. Dependency graph, execution order, effort

```
WP0 scaffolding
 └─ WP1 spikes (S1 editor, S2 tree)          ← hard gate: stop on FAIL
     └─ WP2 engine (+ util/misc)
         └─ WP3 shell (window, actions, prefs, launcher, prefs dialog)
             └─ WP4 shared widgets (historycombo, msgarea, treemodel, findbar)
                 ├─ WP5 dirdiff        (creates diffmap.py)
                 ├─ WP6 filediff       (extends diffmap.py; largest WP)
                 └─ WP7 vcview + vc/   (consumes treemodel, msgarea)
                     └─ WP8 i18n + packaging + desktop
                         └─ WP9 hardening + parity audit
```

Execute strictly in order WP0 → WP9 (WP5/WP6/WP7 may interleave at task level but land
WP5's T5.1–T5.2 treemodel extensions before WP7's tree work). One task = one commit
(`WP<n>.<m>: <summary>`), suite green before every commit. Exception: WP3's T3.8
(new-comparison dialog) and the WP3 acceptance items that exercise it (AC3's
`tests/test_newcomparison.py`, AC6) are deferred until WP4's T4.5 lands; WP3 closes with
the Ctrl+N `QMessageBox` stub and T3.8 executes as the first task after T4.5.

| WP | Scope | Effort (pd) |
|---|---|---|
| WP0 | Scaffolding, pyproject, purity guard | 0.5 |
| WP1 | Gate spikes S1 + S2 | 2–3 |
| WP2 | Engine + undo rebuild + golden corpus | 6–7 |
| WP3 | Shell, DocActionManager, prefs store + dialog, CLI | 10–15 |
| WP4 | Shared widgets + tree model | 5–7 |
| WP5 | Directory comparison | 9–14 |
| WP6 | File comparison (crux) | 18–24 |
| WP7 | VC view + plugins | 6–10 |
| WP8 | i18n pipeline, packaging, desktop | 4–6 |
| WP9 | Hardening, parity, translation proof | 5–8 |
| **Total** | | **≈ 66–99** |

### Cross-WP reconciliation notes (read before starting any WP)

- **`meldq/diffmap.py`**: created by WP5 (T5.9) since dirdiff lands first; WP6 (T6.7)
  extends the landed class and must adapt to its API, not replace it.
- **`meldq/util/misc.py`**: created by WP2; WP4 and WP7 append idempotently (verify a
  helper's absence before adding; keep the no-Qt rule — `tests/test_purity.py` enforces).
- **`meldq/conf.py`**: WP0 ships the gettext stub; WP3 completes locale binding. Import
  order matters: `meldq.conf` must initialize before `meldq.vc._vc` (module-level `_()`).
- **`Direction` enum**: defined once in `meldq/doc.py`; WP6 and WP7 both reference it —
  whichever lands first creates it, the other reuses.
- **Editor stub**: if WP4 leaves a `widgets/editor.py` stub, WP6 completes it in place,
  keeping any landed API.
- **Where drafts disagree with landed code**: the WP texts specify consumed APIs by exact
  name; if a provider WP landed something slightly different, grep the landed code and
  adapt the consumer to reality — do not silently fork a second implementation.

## 4. Work packages

## WP0 — Scaffolding

### Goal
Create the new package skeleton, build metadata, and test harness so every later WP has
a place to land and a green baseline to keep.

### Dependencies
None.

### Tasks

**T0.1 — Package skeleton + pyproject.**
Create `meldq/__init__.py` (`__version__ = "2.0.0a0"`), a minimal `meldq/conf.py` stub
(`import gettext; _ = gettext.gettext; ngettext = gettext.ngettext` — WP2 imports `_`
from it; WP3 replaces the stub with real locale binding), empty subpackages
(`engine/`, `vc/`, `widgets/`, `util/`, `resources/icons/.gitkeep`, `ui/.gitkeep`),
`tests/__init__.py`, and `pyproject.toml`:
- `[project]` name `meldq`, `dynamic = ["version"]` with `[tool.setuptools.dynamic] version = {attr = "meldq.__version__"}` (WP8 T8.1 finalizes the rest of the file), `requires-python = ">=3.11"`,
  `dependencies = ["PyQt6>=6.6"]`, `[project.optional-dependencies] highlight = ["pygments"]`,
  dev extra: `pytest`, `pytest-qt`.
- `[project.scripts] meldq = "meldq.main:main"` (main.py arrives in WP3; ship a stub
  `main()` that prints version and exits 0 so the entry point imports).
- setuptools backend; `[tool.setuptools.package-data]` for `resources/*`, `ui/*`.
- `[tool.pytest.ini_options] qt_api = "pyqt6"`.
Acceptance: `pip install -e ".[highlight]" --dry-run` resolves; `python -c "import meldq; print(meldq.__version__)"` prints `2.0.0a0`.

**T0.2 — Purity guard test.**
`tests/test_purity.py`: imports `meldq.engine.matchers/diffutil/merge/task` (skip while
absent via `pytest.importorskip`) and `meldq.util.misc`, then asserts
`"PyQt6.QtWidgets" not in sys.modules` and that `meldq.util.misc` has no `PyQt6`
top-level import (AST scan of the source file). `diffutil`/`undo` are allowed QtCore
only. This test encodes the layering rule for the whole port.
Acceptance: test passes (skipping absent modules today, failing loudly the day someone
imports QtWidgets from the engine).

**T0.3 — Golden-corpus directory layout.**
Create `tests/fixtures/README.md` documenting the corpus format defined in WP2 (pairs/
triples of input files + expected chunk JSON), and `tests/fixtures/engine/opcodes/`,
`tests/fixtures/engine/merge3/`, `tests/fixtures/encodings/` placeholders (the paths WP2's
T2.2/T2.4 and WP6's T6.3 actually populate). No test logic yet —
WP2 owns generation; this task exists so fixture paths are stable from the start.

### Acceptance criteria
1. `python -m pytest tests/ -q` green.
2. `pip install -e .` then `meldq` prints the version.
3. Repo layout matches §2 exactly.

### Estimated effort
0.5 pd.

---

## WP1 — Gate spikes (S1: editor rendering; S2: shared tree model)

### Goal
Cheaply validate the two riskiest architecture bets **before** any dependent WP starts.
Spike code lives in `spikes/` (committed for reference, never imported by `meldq/`), and
each spike ends in a written PASS/FAIL verdict appended to this file.

### Dependencies
WP0.

### Tasks

**T1.1 — S1: two-pane editor + chunk painting + sync scroll + linkmap.**
Build `spikes/s1_editor.py`, a standalone QApplication showing two `QPlainTextEdit`
subclasses loaded with ~2,000-line lorem files differing in ~30 scattered chunks
(hardcode a fake chunk list — no engine needed):
- Chunk backgrounds: full-width fills painted in `paintEvent` on the viewport *before*
  `super().paintEvent()`, plus 1-px darker top/bottom boundary lines per chunk, computed
  from `firstVisibleBlock()`/`blockBoundingGeometry(...).translated(contentOffset())`.
- Proportional sync scroll: dragging either scrollbar scrolls the other pane so that
  chunk midpoints align (linear interpolation between chunk boundaries — the same math
  as `meld/filediff.py:1142-1241`), with a reentrancy guard flag.
- A 40-px `LinkMap` QWidget between panes drawing cubic-bezier polygons connecting
  corresponding chunk edges, repainted on either pane's scroll signal.
- A resize + `setFont` (monospace, 3 sizes) torture toggle.

PASS criteria (all must hold):
(a) chunk fills and boundary lines visually glued to their text lines during fast
    scrolling (no lag/ghosting) with both panes at 2,000 lines;
(b) linkmap curves stay attached to chunk edges during scroll and window resize;
(c) no per-frame full-document iteration — painting cost is O(visible blocks), verified
    by logging block-iteration counts per paint (< 200 per frame);
(d) font size change re-aligns everything without restart.
FAIL → stop; the fallback ladder is: QScintilla evaluation, then custom text widget —
user decision required either way.

**T1.2 — S2: three QTreeViews on one QStandardItemModel.**
Build `spikes/s2_tree.py`: one `QStandardItemModel`, 3 columns × ~500 rows nested 3
deep; three `QTreeView`s side by side, view *i* shows only column *i*
(`setTreePosition(i)` + `setColumnHidden` for the others); per-view expansion mirrored
across panes by connecting `expanded`/`collapsed` to a sync handler; row recolored via
`Qt.ForegroundRole`.
PASS: branch indicators render correctly in all three views (including view 0 whose
tree column is not column 0); expansion sync has no recursion; selection can be
mirrored by row. FAIL → fallback is three mirrored models with a sync layer (WP4's
model API absorbs this; flag it before WP4 starts).

**T1.3 — Verdict commit.** Append `S1: PASS/FAIL — <two-line evidence>` and same for S2
to this section; if either failed, stop per operating rule 9.

### Verdicts (recorded 2026-07: PyQt 6.11 / Qt 6.11 / Python 3.14, macOS)

**S1: PASS** — auto-harness: max 34 block iterations per paint over a full scroll
sweep of 2,000 lines (bound 200 → painting is O(visible)); anchor alignment error
0.0 lines across all 30 chunks; reentrancy stable; font 14→18pt re-derives chunk
fills, boundary lines, and linkmap attachment correctly (verified in renders).
Caveat: "no ghosting during fast scrolling" was verified by proxy (bounded paint
cost + correct renders at sampled positions) on the offscreen platform — do a
2-minute interactive eyeball run (`python spikes/s1_editor.py`) before WP6 starts.

**S2: PASS** — expansion and collapse mirrored across all three views from any
view; row selection mirrored; 50 rapid expand/collapse cycles without recursion;
branch indicators render correctly in every view including panes whose tree
column is not column 0; per-state ForegroundRole colors render. `setTreePosition`
+ hidden sibling columns confirmed viable — WP4's single-shared-model design
stands; no mirrored-model fallback needed.

### Acceptance criteria
1. `python spikes/s1_editor.py` and `python spikes/s2_tree.py` run standalone.
2. Verdicts recorded in this document.

### Estimated effort
2–3 pd.

---

---

## WP2 — Engine port (`meldq/engine/*` + pure `meldq/util/misc.py`)

### Goal

Port Meld's toolkit-free diff/merge/scheduling core — `matchers.py`, `diffutil.py`, `merge.py`, `task.py` — to Python 3.11 under `meldq/engine/`, convert `Differ` to a `QObject` with a `diffs_changed` signal, and REBUILD `UndoSequence` as a QTextDocument-native cross-pane undo coordinator per the undo contract. Split old `meld/misc.py` into a pure `meldq/util/misc.py` (Qt import forbidden, test-enforced), keeping the `select()`-based `read_pipe_iter` generator. Everything lands with a golden-fixture pytest corpus that validates behavior without ever running the Python 2 original, and with regression tests for the two latent bugs being fixed (`merge.py:131`, `undo.py:182`).

### Dependencies

- **WP0** (scaffolding): must provide an importable `meldq/` package with `meldq/__init__.py` (`__version__ = "2.0.0a0"`), `meldq/conf.py` exposing `_` and `ngettext`, a `pyproject.toml` installing `PyQt6>=6.6` plus dev deps `pytest` and `pytest-qt`, and an empty `tests/` scaffold. Run `python -c "from meldq.conf import _"` first; if it fails, WP0 has not landed — stop.
- No other WP is required. WP3 (app shell), WP5 (dirdiff), WP6 (filediff), WP7 (vcview) all build on this WP.

### Old-code map

| Old code (path:lines) | What it does | New home |
|---|---|---|
| `meld/matchers.py:20-47` | `find_common_prefix` / `find_common_suffix` binary-search helpers | `meldq/engine/matchers.py` — verbatim |
| `meld/matchers.py:50-262` | `MyersSequenceMatcher` (O(NP) diff, incremental `initialise()` generator, preprocess/discard optimizations) | `meldq/engine/matchers.py` — verbatim + py3 fixes |
| `meld/diffutil.py:27-51` | `IncrementalSequenceMatcher` (generator-driven difflib wrapper) | `meldq/engine/diffutil.py` — verbatim + py3 fixes |
| `meld/diffutil.py:54-63` | `opcode_reverse` table + `reverse_chunk` | `meldq/engine/diffutil.py` — verbatim |
| `meld/diffutil.py:70-443` | `Differ`: 2/3-way chunk model, merge cache, line cache, incremental re-diff | `meldq/engine/diffutil.py` — `Differ(QObject)` with `diffs_changed = pyqtSignal()` |
| `meld/merge.py:22-161` | `AutoMergeDiffer` (auto-resolving 3-way differ + unresolved-conflict tracking) | `meldq/engine/merge.py` — verbatim + fix `:131` |
| `meld/merge.py:163-257` | `Merger` (drives `merge_3_files`/`merge_2_files` generators) | `meldq/engine/merge.py` — base class `diffutil.Differ` DROPPED (never initialized, no state used — verified against `meld/filediff.py:337-356` and `meld/filemerge.py:74-81`) |
| `meld/undo.py:36-49` | `GroupAction` (nested-sequence group wrapper) | NOT PORTED (undo redesign) |
| `meld/undo.py:51-247` | `UndoSequence` (action stack, groups, per-buffer checkpoints) | `meldq/engine/undo.py` — REBUILT as QTextDocument coordinator (T2.7) |
| `meld/task.py:22-139` | `SchedulerBase` (task list, `runnable` callbacks, iteration) | `meldq/engine/task.py` — verbatim + `runnable_cb` attribute + `SchedulerEmpty` |
| `meld/task.py:142-176` | `LifoScheduler` / `FifoScheduler` / `RoundRobinScheduler` | `meldq/engine/task.py` — verbatim, sentinel exception swapped |
| `meld/task.py:180-222` | `__main__` demo block (py2 prints, `gen.next`) | DELETED — replaced by `tests/engine/test_task.py` |
| `meld/misc.py:32-53` | `whitespace_re`, `NULL`, `cmdout`, `shelljoin` | `meldq/util/misc.py` (`NULL` deleted → `subprocess.DEVNULL`) |
| `meld/misc.py:55-78` | `run_dialog` (gtk.MessageDialog wrapper) | WP3 (app shell): rebuilt as a `QMessageBox` helper in `meldq/app.py`. NOT ported here. |
| `meld/misc.py:80-89` | `open_uri` (gtk.show_uri / gnome fallback) | WP3 (app shell): `QDesktopServices.openUrl` one-liner in `meldq/app.py`. NOT ported here. |
| `meld/misc.py:92-123` | `position_menu_under_widget` | DELETED — Qt positions menus natively |
| `meld/misc.py:125-133` | `make_tool_button_widget` | DELETED — `QToolButton` draws its own arrow |
| `meld/misc.py:135-163` | `struct` record class, `all_equal` | `meldq/util/misc.py` (`__cmp__` → `__eq__`) |
| `meld/misc.py:165-189` | `shorten_names` | `meldq/util/misc.py` (lazy-map fixes) |
| `meld/misc.py:191-244` | `read_pipe_iter`, `write_pipe` | `meldq/util/misc.py` (bytes discipline, try/finally kill) |
| `meld/misc.py:246-297` | `commonprefix`, `copy2`, `copytree`, `shell_escape` | `meldq/util/misc.py` — verbatim + py3 fixes |
| `meld/misc.py:299-356` | `shell_to_regex`, `ListItem` | `meldq/util/misc.py` — verbatim |

### Tasks

Each task is one commit. Copy the GPL header block (with original copyright lines) from each old file into its new counterpart. Create `meldq/engine/__init__.py` (empty) in T2.1 and `meldq/util/__init__.py` (empty) in T2.6 if WP0 did not.

---

#### T2.1 — Port `meldq/engine/matchers.py` (verbatim + py3 mechanics)

**Old source:** `meld/matchers.py` (263 lines, zero toolkit imports).

**Build:** Copy the file to `meldq/engine/matchers.py`. Only these changes:

1. `meld/matchers.py:71` — `get_difference_opcodes` returns a lazy `filter(...)`. Replace with:
   ```python
   def get_difference_opcodes(self):
       return [c for c in self.get_opcodes() if c[0] != "equal"]
   ```
   The result is stored in `Differ.diffs` (`meld/diffutil.py:432`) and later `len()`'d (`diffutil.py:203`), indexed/sliced (`diffutil.py:254,260,273-278`), and `==`-compared (`diffutil.py:342`) — a lazy iterator breaks all of these *at a distance*, not at the call site.
2. `meld/matchers.py:145` — `while lastsnake != None:` → `while lastsnake is not None:`.
3. Keep everything else byte-identical, including the generator protocol of `initialise()` (`meld/matchers.py:202-203` yields `None` every 100 outer iterations, `:262` yields `1` when done). Do NOT convert the trailing `yield 1` to a `return` — the scheduler consumes `yield None ... yield <final>`.

**TRAPS:**
- `meld/matchers.py:52-62` — `__init__` deliberately does NOT chain to `difflib.SequenceMatcher.__init__`. Do not "fix" this: py3.11 `difflib.get_opcodes()` only needs `self.opcodes` and `get_matching_blocks()`, both of which this class provides. Adding the super call changes junk/autojunk state for no benefit.
- `meld/matchers.py:30,45` — divisions already wrapped in `int(...)`; safe under true division. Verify, don't touch.
- `meld/matchers.py:20-21,35-36` — `a[0]`/`a[-1]` raise `IndexError` on empty sequences. This is 1.4 behavior; callers always pass at least `[""]` (a `"".split("\n")` result). Preserve — do not add guards.
- `meld/matchers.py:66-67` — `get_matching_blocks` drains `initialise()` with a `for` loop: fine in py3. The *external* consumer `meld/diffutil.py:430` uses `.next()` — handled in T2.3, not here.
- PEP 479: `initialise()` contains no internal `next()`/`raise StopIteration` — verified safe. Never add one.

**Tests (minimal smoke; the corpus lands in T2.2):** `tests/engine/test_matchers.py` with: identical inputs → single terminator block `(len(a), len(b), 0)`; `get_difference_opcodes` returns a `list` (regression for the filter trap: `assert isinstance(result, list)`); `initialise()` yields `None` before `1` for inputs > 100 iterations.

---

#### T2.2 — Golden-test corpus + invariant harness for opcode-level behavior

**Purpose:** validate the engine WITHOUT running Python 2. Three sources of expected values, in trust order: (1) hand-constructed expectations for small cases, (2) GNU `diff`/`diff3` cross-checks of aggregate properties, (3) invariant checks + frozen characterization for large cases.

**Build:**

1. `tests/engine/util.py`:
   - `apply_opcodes(a: list[str], opcodes) -> list[str]` — reconstructs `b` from `a` given full opcodes (equal chunks included): walk opcodes, copy `a[i1:i2]` for `equal`, emit `b`-side content for others; used as the universal correctness oracle (needs `b` for non-equal chunks: signature `apply_opcodes(a, b, opcodes)` copying `b[j1:j2]` for insert/replace).
   - `validate_opcodes(opcodes, len_a, len_b)` — asserts: 5-tuples; tags in `{"equal","replace","insert","delete"}`; `i1<=i2`, `j1<=j2`; contiguous coverage `0..len_a` / `0..len_b`; `insert` has `i1==i2`, `delete` has `j1==j2`.
   - `gnu_diff_counts(a, b) -> tuple[int, int]` — writes both to temp files (`"\n".join(lines) + "\n"`), runs `["diff", fa, fb]`, counts output lines starting `"< "` and `"> "`. Both Linux and macOS ship a minimal-edit `diff`; fixtures are tiny so heuristics never kick in.
2. `tests/fixtures/engine/opcodes/*.json`, one case per file:
   ```json
   {"description": "insert two lines mid-file",
    "a": ["one", "two", "five"],
    "b": ["one", "two", "three", "four", "five"],
    "expected": [["insert", 2, 2, 2, 4]]}
   ```
   `"expected"` is the `get_difference_opcodes()` list, or `null` for invariant-only cases. Required hand-built cases: identical; pure insert (top/middle/bottom); pure delete; single replace; common prefix+suffix stripping exercised (`common_prefix > 0` and `common_suffix > 0` paths of `meld/matchers.py:86-100`); a discard-path case with >10 lines unique to one side (triggers `lines_discarded` at `meld/matchers.py:126` and the snake-splitting at `:147-168`) with `"expected": null`; single-line files; files that are `[""]` (empty text).
3. `tests/engine/test_opcodes_corpus.py`, parametrized over fixture files, running **each** of `MyersSequenceMatcher`, `IncrementalSequenceMatcher` (from T2.3 — mark those parametrizations `pytest.importorskip` until T2.3 lands, or land this test file in T2.3), and stdlib `difflib.SequenceMatcher`:
   - reconstruction oracle passes for all three matchers;
   - `validate_opcodes` passes;
   - where `"expected"` is non-null: Myers output equals it exactly;
   - GNU cross-check (`@pytest.mark.skipif(shutil.which("diff") is None, ...)`): Myers total removed/added line counts equal GNU `diff`'s (both are minimal edit scripts; the discard heuristic only removes lines with zero matches on the other side, which any diff must count as edits). `difflib` counts are asserted `>=` Myers (difflib is not minimal). If a fixture ever fails the equality, verify by hand before touching the assertion — do not silently weaken it.

**TRAPS:**
- Do not generate expected values by running the new code and pasting output ("self-fulfilling golden"). Only invariant-`null` fixtures may be characterization-frozen, and only AFTER reconstruction + GNU checks pass.
- `difflib.SequenceMatcher` in 3.11 has `autojunk=True` by default — construct it as `difflib.SequenceMatcher(None, a, b, autojunk=False)` in the harness or popular-line junking skews comparisons on repetitive fixtures.

---

#### T2.3 — Port `meldq/engine/diffutil.py`: `Differ(QObject)` + `diffs_changed`

**Old source:** `meld/diffutil.py` (443 lines).

**Build:** Copy, then apply exactly:

1. `meld/diffutil.py:20` — delete `import gobject`; add `from PyQt6.QtCore import QObject, pyqtSignal`.
2. `meld/diffutil.py:70-75` — 
   ```python
   class Differ(QObject):
       """Utility class to hold diff2 or diff3 chunks"""
       diffs_changed = pyqtSignal()
   ```
3. `meld/diffutil.py:81` — `gobject.GObject.__init__(self)` → `super().__init__()`. It must remain the FIRST statement of `__init__` (PyQt requires QObject init before any attribute/signal use).
4. `meld/diffutil.py:114` — `self.emit("diffs-changed")` → `self.diffs_changed.emit()`.
5. `meld/diffutil.py:51` — `IncrementalSequenceMatcher.get_difference_opcodes`: same list-comprehension rewrite as T2.1 item 1.
6. `meld/diffutil.py:311` `seq = toindex/2`, `:316` `seq = fromindex/2`, `:332` `seq = textindex/2` — all three become `// 2`. Under py3, `/` yields a float that is then used as `c[seq]` / `cs[seq]` list index → `TypeError`, but ONLY when pane 0 or pane 2 changes are queried — a smoke test on a 2-pane diff of pane 1 will not catch it.
7. `meld/diffutil.py:430` — `while work.next() is None:` → `while next(work) is None:`.
8. `meld/diffutil.py:134` — local list named `next` shadows the builtin. Rename to `next_chunks` (and its uses at `:148,:154,:155,:161`); `prev` may stay.
9. `meld/diffutil.py:263,266,270` — delete the commented-out py2 `print` lines.

Everything else — `_update_merge_cache`, `_update_line_cache`, `_consume_blank_lines`, `_find_blank_lines`, `change_sequence`/`_change_sequence`, `_locate_chunk`, `get_chunk`, `locate_chunk`, `diff_count`, `has_mergeable_changes`, `_range_from_lines`, `all_changes`, `pair_changes`, `single_changes`, `sequences_identical`, `_merge_blocks`, `_auto_merge`, `_merge_diffs`, `set_sequences_iter`, `clear` — ports byte-identical.

**PyQt6 guidance:** zero-arg `pyqtSignal()`; connections are direct (synchronous) in a single thread, so consumers connected before `set_sequences_iter` runs observe the same mid-update timing GTK's `SIGNAL_RUN_FIRST` gave. Never move diffing to a thread.

**TRAPS:**
- `meld/diffutil.py:432` — `self.diffs[i] = matcher.get_difference_opcodes()`: the stored value MUST be a list (guaranteed by the T2.1 item 1 and T2.3 item 5 rewrites). Add an assert-style regression test, not a runtime assert.
- `meld/diffutil.py:197-203` `_locate_chunk` does `len(self.diffs[whichdiffs])` and enumerates it — second place lazy filters explode.
- `meld/diffutil.py:342` `sequences_identical` compares `self.diffs == [[], []]` — filter objects never equal `[]`; with lists it's correct.
- `meld/diffutil.py:421-435` `set_sequences_iter` is itself a generator calling `next(work)`. PEP 479: if `work` were exhausted, the escaping `StopIteration` becomes `RuntimeError`. The matcher protocol (final `yield 1` breaks the loop first) prevents this — preserve the protocol on both sides, and never wrap `next(work)` in a bare `except StopIteration: pass`.
- `meld/diffutil.py:45-46` — `done.sort()` sorts `(int, tuple)` pairs; first elements are unique (match starts < the `(la, ...)` terminator), so py3's no-heterogeneous-comparison rule is never hit. Verified — do not "fix" with a key function that changes tie behavior.
- Signal-handler arity: GTK handlers received the emitter (`meld/filediff.py:840` `def on_diffs_changed(self, linediffer)`). `pyqtSignal()` passes nothing — consumer WPs adapt their slots; do NOT add an argument to the signal.
- `clear()` (`meld/diffutil.py:437-442`) emits `diffs_changed` via `_update_merge_cache` — preserve; filediff relies on the redraw.

**Tests:** `tests/engine/test_diffutil.py` (use `qapp` fixture from pytest-qt; add `tests/conftest.py` with a session-scoped QApplication if WP0 didn't):
- Exhaust `set_sequences_iter` on a 2-way case; count `diffs_changed` emissions (== 1); assert `isinstance(d.diffs[0], list)`.
- **Float-index regression:** 3-way texts where pane 0 and pane 2 each differ from base; assert `list(d.single_changes(0))` and `list(d.single_changes(2))` yield reversed chunks and `list(d.pair_changes(1, 2))` / `(2, 1)` work — these four calls all crash with `TypeError` if `/2` survives.
- `locate_chunk` line-cache behavior incl. one-past-last-line query (`meld/diffutil.py:119` allocates `l + 1`).
- `change_sequence`: 2-way case, then simulate an edit (insert 2 lines in pane 0 at a known line), pass updated texts, assert new chunk list equals a from-scratch `Differ` on the edited texts (self-consistency oracle).
- 3-way merge cache: identical change in panes 0 and 2 → tag is `replace`/`insert`/`delete`, not `conflict` (`meld/diffutil.py:357-371`); divergent change → `conflict`.
- `ignore_blanks = True`: replace-that-is-only-blank-lines becomes `insert`/`delete`/dropped per `meld/diffutil.py:163-175`.
- `sequences_identical()` True for identical inputs after init, False before init.

---

#### T2.4 — Port `meldq/engine/merge.py` + fix the `seq2` NameError

**Old source:** `meld/merge.py` (257 lines).

**Build:**

1. `meld/merge.py:17-18` — `import diffutil` / `import matchers` (py2 implicit-relative) → `from . import diffutil, matchers`.
2. `meld/merge.py:27-28` — `AutoMergeDiffer.__init__`: `diffutil.Differ.__init__(self)` → `super().__init__()` (QObject chain now runs through it).
3. **BUG FIX** `meld/merge.py:131` — in the delete+delete split tail:
   ```python
   out0 = ('conflict', i0, i0 + seq1[2] - i1, end0, end0 + seq2[2] - i1)
   ```
   `seq2` is undefined → `NameError`. Fix to `seq1[2]`, mirroring the symmetric `seq0` branch at `:128`.
4. `meld/merge.py:163-169` — `class Merger(diffutil.Differ)` → `class Merger:` (drop the base). `__init__` never chained to `Differ.__init__`, so under Qt the first inherited-QObject touch would crash; consumers (`meld/filediff.py:337-356`, `meld/filemerge.py:74-81`) only use `.differ`, `.texts`, `.unresolved`, `initialize`, `merge_2_files`, `merge_3_files` — verified. Note: old `Merger` never defines `self.unresolved` in `__init__`; `merge_3_files`/`merge_2_files` set it (`:193`, `:238`). Preserve exactly.
5. `meld/merge.py:173` — `while step.next() == None:` → `while next(step) is None:`.
6. `meld/merge.py:95` `while 1:` → `while True:`; `== None`/`!= None` at `:96, :103, :200, :202-203, :209, :224` → `is None`/`is not None`.
7. Delete the commented-out alternative-merge block `meld/merge.py:60-79` and the commented `PatienceSequenceMatcher` lines `:19, :25`.
8. Everything else verbatim: `_auto_merge` override (`:32-135`), unresolved bookkeeping in `change_sequence` (`:137-158`), `get_unresolved_count`, `_apply_change`, `merge_3_files`, `merge_2_files`.

**TRAPS:**
- `meld/merge.py:36` — the unpack `l0, h0, l1, h1, l2, h2 = out0[3], out0[4], out0[1], out0[2], out1[3], out1[4]` has non-obvious ordering (pane0, base, pane2). Transcribe exactly; a swapped pair produces plausible-but-wrong merges that only the 3-way corpus catches.
- `meld/merge.py:94-124` — `i0/i1/end0/end1` look possibly-unbound to linters; they are bounded by the invariant that both `using` lists are non-empty on entry (guaranteed by `meld/diffutil.py:411-419`). Add a comment, do NOT restructure the loop.
- `meld/merge.py:173` PEP 479: `initialize` is a generator driving another generator with `next()`; the `yield 1` terminator protocol prevents exhaustion (same as T2.3).
- `meld/merge.py:234,256` — final `yield "\n".join(mergedtext)` returns a `str` as the generator's last value; consumers loop `for x in gen` and keep the final truthy value. Preserve; don't `return` it.
- `meld/merge.py:151` — the `sizechange == 0 and startidx == self.unresolved[lo]` edge (replace-at-conflict-line) is deliberate; port verbatim.

**Tests:** `tests/engine/test_merge.py`:
- **Regression `merge.py:131`** — `test_delete_delete_split_tail_seq1`:
  ```python
  base  = ["a", "b", "c", "d", "e"]
  text0 = ["a", "d", "e"]        # deletes b,c
  text2 = ["a", "e"]             # deletes b,c,d  (seq1 outlives seq0)
  d = AutoMergeDiffer(); d.auto_merge = True
  for _ in d.set_sequences_iter([text0, base, text2]): pass
  changes = list(d.all_changes())
  ```
  On unfixed code this raises `NameError: seq2`. After the fix assert the cache contains the shared-delete pair `(('delete',1,3,1,1), ('delete',1,3,1,1))` followed by the tail conflict pair `(('conflict',3,4,1,2), ('conflict',3,4,1,1))`.
- `test_merge3_marks_tail_conflict`: same inputs through `Merger` (`initialize([text0, base, text2], [text0, base, text2])`, drain, then drain `merge_3_files()`); expect merged text `"a\n(??)d\ne"` and `merger.unresolved == [1]`.
- 3-way fixtures in `tests/fixtures/engine/merge3/*.json` with keys `{"description", "base", "local", "remote", "merged_lines", "unresolved", "diff3_check"}`; cases: non-overlapping edits (clean merge), identical edits both sides (applied once, no conflict), overlapping divergent edit (conflict marker `"(??)"` lines + unresolved indices), delete-vs-edit conflict. Where `diff3_check` is true and the expected merge is conflict-free, cross-check against `subprocess.run(["diff3", "-m", local, base, remote])` output (skipif `shutil.which("diff3") is None`). Meld's auto-merge is more aggressive than diff3 — set `diff3_check` only on the clean non-overlapping cases.
- `merge_2_files` both directions on a 3-way differ; conflict chunks skipped (`meld/merge.py:250`).
- `AutoMergeDiffer.change_sequence` unresolved-shift: seed `unresolved=[2,5,9]`, apply `change_sequence(1, 4, -2, texts)`-shaped calls, assert list shifts/drops per `:137-158` semantics (compute expectations by hand-walking the loop).

---

#### T2.5 — Port `meldq/engine/task.py`: schedulers, `runnable_cb`, `SchedulerEmpty`

**Old source:** `meld/task.py` (223 lines, pure Python — must stay Qt-free).

**Build:** Copy `:22-177`, then:

1. Add at module top:
   ```python
   class SchedulerEmpty(Exception):
       """Raised by get_current_task when the scheduler has no tasks."""
   ```
   Replace `raise StopIteration` at `meld/task.py:151, :163, :176` with `raise SchedulerEmpty` and the `except StopIteration: return 0` at `:126-128` with `except SchedulerEmpty: return 0`. Rationale: `StopIteration` as a control-flow sentinel is a PEP 479 landmine the moment any caller is a generator.
2. Replace the GObject-mimicking callback list (`meld/task.py:32, :37-42, :61-62`) with a plain attribute per the normative contract:
   ```python
   self.runnable_cb = None   # callable(scheduler) | None; set by owner
   self.paused = False       # §2.5: docs set this around modal exec(); the pump skips paused schedulers
   ```
   `add_task` (`:44-62`) ends with `if self.runnable_cb is not None: self.runnable_cb(self)`. Delete `connect()`.
3. `add_scheduler` (`:77-80`) → `sched.runnable_cb = self.add_task` (child scheduler passed as the task — same effect as the old lambda).
4. **BUG FIX (latent, 1.4)** `remove_scheduler` (`:82-89`): the old `self.callbacks.remove(sched)` could never succeed — `callbacks` held lambdas, not schedulers, so the disconnect was a silent no-op and a closed document's scheduler kept re-adding itself to the app pump (`meld/meldapp.py:468, :628` call this). New body:
   ```python
   def remove_scheduler(self, sched):
       self.remove_task(sched)
       sched.runnable_cb = None
   ```
5. Make `iteration()` (`:119-139`) generator-aware so callers pass generator objects instead of the py2 `gen.next` bound method (32 call sites across later WPs die here instead of one-by-one):
   ```python
   import types
   ...
   try:
       if isinstance(task, types.GeneratorType):
           ret = next(task)
       else:
           ret = task()
   except StopIteration:
       pass
   ```
   `except StopIteration: pass` (old `:131-132`) is legal — `iteration()` is not a generator — and still handles exhausted generators AND plain callables that finish. Everything else in `iteration` verbatim (bare `except Exception: traceback.print_exc()` at `:133-134` included; it is what keeps one broken task from killing the pump).
6. `add_task(self, task, atfront=0)` (`:44`) → `atfront=False`. Docstring: task may be a callable, a generator object, or a scheduler.
7. `__repr__` (`:34-35`) → `return repr(self.tasks)`.
8. Delete the entire `__main__` demo block (`meld/task.py:180-222`).
9. `SchedulerBase(object)` → `SchedulerBase:`; subclass `__init__`s may keep explicit `super().__init__()`.

**TRAPS:**
- `meld/task.py:99-106` `__call__` returns the task's own return value if truthy else `tasks_pending()` — WP3's `SchedulerPump` depends on this exact convention; do not normalize to bool.
- `meld/task.py:130-137` — tasks legitimately return **strings** (status text) and **floats** (progress fraction); `meld/meldapp.py:262-270` dispatches on the type of `iteration()`'s return. Never coerce.
- `meld/task.py:138` `self.tasks.remove(task)` is unguarded — if a task removed itself mid-run this raises. 1.4 behavior; preserve (no try/except).
- Schedulers nested as tasks are *callables* (they define `__call__`), so the `GeneratorType` branch must be an `isinstance` check, not a `callable()` check.
- This module must import NOTHING from Qt — enforced by the purity test in T2.6.

**Tests:** `tests/engine/test_task.py` (no Qt): FIFO/LIFO/RoundRobin ordering with 3 interleaved generators; falsy-return removes callable task; exhausted generator removed via `StopIteration`; a task raising `ValueError` is removed, traceback printed (capsys), other tasks survive; `runnable_cb` fires on `add_task` with the scheduler as arg; `add_scheduler` propagation (child task → child appears in parent.tasks); **regression** `test_remove_scheduler_disconnects`: after `parent.remove_scheduler(child)`, `child.add_task(...)` must NOT re-add `child` to `parent.tasks` (fails on a faithful port of the 1.4 code); string/float passthrough from `iteration()`; `complete_tasks()` drains; `SchedulerEmpty` raised by `get_current_task()` on empty schedulers and `iteration()` returns 0.

---

#### T2.6 — Split `meld/misc.py`: pure half → `meldq/util/misc.py` + purity enforcement

**Old source:** `meld/misc.py` (357 lines). Port ONLY the pure half; see Old-code map for the four GTK functions' fates (two → WP3 `meldq/app.py`, two deleted).

**Build** `meldq/util/misc.py` with module imports `copy, errno, os, re, select, shutil, subprocess, codecs` and `from meldq.conf import _` (replaces `meld/misc.py:23`; needed only by `shorten_names`). Importing PyQt6 anywhere in this module is FORBIDDEN.

Function-by-function:

1. `whitespace_re` (`:32`) — verbatim.
2. `cmdout` (`:35-48`) — delete the module-level `NULL` fd (`:33`); use `subprocess.DEVNULL` for the default `stdin`/`stderr`. Add `text=True` to the `Popen` defaults so `communicate(text)` (`:46`) and the returned output are `str`. Sole 1.4 caller was the descoped svk plugin, but the helper is kept for VC WP use.
3. `shelljoin` (`:50-53`) — replace the py2 and-or ternary at `:52`. **TRAP:** `(cond) and s or default` quotes FALSY strings too: for `s == ""` it returns `'""'`. A naive `s if cond else default` silently changes that. Correct translation:
   ```python
   def quote(s):
       return s if s and whitespace_re.search(s) is None else '"%s"' % s
   ```
4. `struct` (`:135-151`) — keep the class; replace `__cmp__`/`cmp` (`:150-151`, both removed in py3) with:
   ```python
   def __eq__(self, other):
       return self.__dict__ == other.__dict__
   ```
   Consumers compare with `==`/`!=` only (`meld/dirdiff.py:60-61, :79`); py3 derives `!=` from `__eq__`. Defining `__eq__` makes the class unhashable — acceptable, no consumer hashes it (verified: `dirdiff.py:57,:99`, `filediff.py:731`). Update the py2 `print` in the docstring (`:140`).
5. `all_equal` (`:153-163`) — return `True`/`False` instead of `1`/`0`; body otherwise verbatim.
6. `shorten_names` (`:165-189`) — **the lazy-map fixes.** Wrap every `map()` in `list()`: `:171` (`names = list(map(...))`), `:172` (`paths`), `:175` (`basenames`), `:185` (`roots`), `:189` (return value). Callers index (`basenames[0]` at `:186`), `len()` (via `all_equal` at `:179`), and iterate the return value multiple times (`meld/filediff.py:664`, `meld/dirdiff.py:882`) — one-shot iterators break every one of these away from the call site. Keep the `try/except IndexError` shape at `:174-177` (defensive; a `str.split("/")` result is never empty). `_("[None]")` at `:189` via `meldq.conf`.
7. `read_pipe_iter` (`:191-237`) — **DECISION (per plan): keep the POSIX `select()`-based generator; a QProcess rewrite is deferred until a Windows WP exists (Windows is a deferred platform).** Rework internals for py3:
   - Replace the `sentinel` class with `__del__` (`:199-206`) — `__del__`-based cleanup is unreliable in py3 — with a plain generator function using `try/finally`. `generator.close()`/GC raises `GeneratorExit` at the yield point; the `finally` block performs the old `__del__` behavior: if the process is still alive (`proc.poll() is None`), write `"killing '%s'\n" % command[0]` to `errorstream`, `proc.terminate()`, then `"killed (status was '%i')\n" % proc.wait()`. (These two strings were untranslated in 1.4; keep them untranslated.)
   - Bytes discipline: pipes stay binary. `bits` accumulates `bytes`; loop sentinel `:212` becomes `bits[-1] != b""`; final value `:234` becomes `b"".join(bits).decode("utf-8", errors="replace")` — the generator's contract is: yields `None` on every `yield_interval` timeout, then yields exactly one **str** and ends.
   - **TRAP** `:221` — `childout.read(4096)` on a `BufferedReader` blocks until 4096 bytes or EOF, defeating the `select()`. Use `childout.read1(4096)` (returns whatever is available; returns `b""` only at EOF, preserving the sentinel).
   - **TRAP** `:226` — `childerr.read(1)` then `errorstream.write(...)`: single bytes can split multibyte UTF-8. Use `childerr.read1(4096)` and feed it through `codecs.getincrementaldecoder("utf-8")(errors="replace")`, writing the decoded `str` to `errorstream`; after the loop (`:230`) flush with `decoder.decode(childerr.read(), final=True)`.
   - Keep: signature `read_pipe_iter(command, errorstream, yield_interval=0.1, workdir=None)`; `workdir == "" → None` (`:235-236`); `select.select([childout, childerr], [], [childout, childerr], yield_interval)` (`:213`); the `Exception("Error reading pipe")` on error-state (`:218`); `except IOError` → `except OSError` (py3 alias) with the same `break`s (`:222-223, :227-228`); exit-status message `"Exit code: %i\n"` (`:233`).
   - `errorstream` receives only `str` — this is the contract vcview's console (`meld/vcview.py:440-445`) codes against.
8. `write_pipe` (`:239-244`) — add `text=True` to `Popen` so `communicate(text)` accepts `str`. Caller: `meld/vcview.py:525`.
9. `commonprefix` (`:246-261`) — verbatim (`copy.copy` is fine in py3).
10. `copy2` (`:263-274`) — `except OSError, e:` at `:272` → `except OSError as e:`. Keep the EPERM-tolerant `copystat` (NTFS bug workaround); do NOT replace with `shutil.copy2`.
11. `copytree` (`:276-292`) — `except OSError, e:` at `:279` → `as e`; `symlinks=1` → `symlinks=True`. Keep hand-rolled (tolerates existing destination dirs, unlike `shutil.copytree`).
12. `shell_escape` (`:294-297`), `shell_to_regex` (`:299-346`), `ListItem` (`:348-356`) — verbatim. `:339`'s `'\\{'` is a valid escaped backslash; leave as-is (or normalize to `r'\{'`, no behavior change).

**Purity enforcement** — `tests/engine/test_purity.py`:
```python
import subprocess, sys
def test_engine_and_util_misc_do_not_import_qt():
    code = ("import sys; import meldq.util.misc, meldq.engine.task, "
            "meldq.engine.matchers; "
            "bad = [m for m in sys.modules if m.startswith('PyQt6')]; "
            "sys.exit(1 if bad else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
```
(`meldq.engine.diffutil/merge/undo` legitimately import Qt and are excluded.)

**Tests:** `tests/engine/test_misc.py` — `shorten_names` cases: `("/tmp/foo1","/tmp/foo2") → ["foo1","foo2"]`; `("/a/x/file.c","/a/y/file.c") → ["[x] file.c","[y] file.c"]`; single arg → `["foo"]`; `("/a/b","/a/") → ["b","[None]"]`; **lazy-map regression**: result is a `list` and iterating it twice gives the same output. `struct` equality/inequality. `all_equal([]) is True`. `shelljoin(["a b",""," c"])` — asserts the empty-string element is quoted (`'""'`, the ternary trap). `shell_to_regex`: `"*.py"`, `"{a,b}c"`, `"[!x]"`, escaped `\*`. `commonprefix` incl. `[] → ''`. `copy2`/`copytree` on `tmp_path` incl. symlink preservation. `cmdout(["echo","hi"]) == ("hi\n", 0)`. `write_pipe(["cat"], "x") == 0`. `read_pipe_iter`: (a) run `[sys.executable, "-c", "import sys,time; print('out'); sys.stderr.write('err'); sys.stderr.flush(); time.sleep(0.3); print('done')"]` with an `io.StringIO` errorstream and `yield_interval=0.05`; collect until a `str` arrives; assert ≥1 `None` was yielded, final value contains `"out"` and `"done"`, errorstream value contains `"err"`; (b) kill-on-close: start `[sys.executable, "-c", "import time; time.sleep(30)"]`, pull one `None`, call `gen.close()`, assert errorstream contains `"killing"` and the call returned promptly (`< 5 s`).

---

#### T2.7 — REBUILD `meldq/engine/undo.py`: QTextDocument-native `UndoSequence`

**Old source:** `meld/undo.py` (behavioral reference only — the action-object machinery is NOT ported). This is the WP's one redesign, executing decision D2 of `PYQT_MIGRATION_PLAN.md` and the normative undo contract. Do NOT use `QUndoStack`.

**Old behavior being preserved (the spec):** one window-level undo stack spanning all panes (`meld/undo.py:65-66` `actions`/`next_redo`); undo/redo hit the buffer the *most recent step* belongs to (`:141, :162`); user actions group into one step (`:197-232`, driven by `meld/filediff.py:566-570`); per-buffer save-point checkpoints drive the modified flag via the `checkpointed` signal (`:177-195`, consumed at `meld/filediff.py:206, :584-585`); editing after undoing past a checkpoint destroys the checkpoint (`:117-121`); `can-undo`/`can-redo` emitted only on transitions (`:127-130, :148-151, :170-173`); a busy guard prevents undo/redo from re-recording (`:69, :109-110, :140, :161`).

**Build** `meldq/engine/undo.py`:

```python
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QTextCursor, QTextDocument

class UndoSequence(QObject):
    can_undo_changed = pyqtSignal(bool)
    can_redo_changed = pyqtSignal(bool)
    checkpointed = pyqtSignal(object, bool)   # (QTextDocument, is_at_checkpoint)
```

State in `__init__(self, parent=None)` (call `super().__init__(parent)` first): `self._docs: list[QTextDocument] = []`; `self._stack: list[QTextDocument] = []` (one entry per undo step, ordered oldest→newest); `self._next_redo: int = 0` (index into `_stack`, same role as old `next_redo`); `self._checkpoint_heights: dict[QTextDocument, int | None] = {}` (`None` = checkpoint destroyed/absent); `self._checkpoint_state: dict[QTextDocument, bool] = {}` (last emitted flag); `self._group_doc: QTextDocument | None = None`; `self._group_cursor: QTextCursor | None = None`; `self._group_depth: int = 0`; `self._busy: bool = False`; `self._can_undo = False`; `self._can_redo = False`.

Method-by-method:

- `register_document(self, doc)` — no-op if already registered. `doc.setUndoRedoEnabled(True)`; connect `doc.undoCommandAdded` to `functools.partial(self._on_undo_command_added, doc)` (`undoCommandAdded` fires **exactly once per new undo step** — merged keystrokes and whole edit blocks produce one emission, which is why the coordinator's stack stays in lock-step with the document's internal stack); append to `_docs`; `_checkpoint_heights[doc] = 0`; `_checkpoint_state[doc] = True` (a fresh document is at its checkpoint / unmodified).
- `_height(self, doc) -> int` — `sum(1 for d in self._stack[:self._next_redo] if d is doc)`: the document's current undo depth as the coordinator sees it.
- `_on_undo_command_added(self, doc)` — the automatic add-tracking (replaces old `add_action`, `meld/undo.py:101-132`):
  1. `if self._busy: return` (guard against re-recording during our own undo/redo).
  2. Truncate the redo tail: `del self._stack[self._next_redo:]`. (The other documents' internal redo stacks are NOT cleared by Qt, but the coordinator is the sole caller of `doc.redo()`, so orphaned internal redo entries are unreachable — document this in a comment.)
  3. Checkpoint-destruction rule (generalizes old `:117-121`): for every `d` in `_checkpoint_heights`, if the recorded height is not `None` and exceeds `_height(d)` *now* (post-truncation, pre-append), set it to `None` — the checkpointed state can no longer be reached.
  4. `self._stack.append(doc)`; `self._next_redo = len(self._stack)`.
  5. `self._refresh_can_flags()`; `self._refresh_checkpoint(doc)`.
- `can_undo(self)` → `self._next_redo > 0`; `can_redo(self)` → `self._next_redo < len(self._stack)` (old `:91-99`).
- `undo(self)` — `assert self._next_redo > 0` (old `:139`); `doc = self._stack[self._next_redo - 1]`; `self._next_redo -= 1`; `self._busy = True; doc.undo(); self._busy = False`; `self._refresh_can_flags(); self._refresh_checkpoint(doc)`.
- `redo(self)` — symmetric: `assert self._next_redo < len(self._stack)`; `doc = self._stack[self._next_redo]`; `self._next_redo += 1`; busy-guarded `doc.redo()`; refresh both.
- `begin_group(self, doc)` — **signature change: takes the document being edited** (the 1.4 caller `meld/filediff.py:566-567` has the buffer in hand). `if self._busy: return` (old `:206-207`). If `self._group_depth == 0`: `self._group_doc = doc; self._group_cursor = QTextCursor(doc); self._group_cursor.beginEditBlock()`. Else: `assert doc is self._group_doc, "multi-document undo groups are not supported"` (normative) and `self._group_cursor.beginEditBlock()` (Qt edit blocks nest natively — the edit-block depth lives on the document, so *all* edits on `doc` between the outermost begin/end collapse into one undo command regardless of which cursor performs them). `self._group_depth += 1`.
- `end_group(self)` — `if self._busy: return`; `assert self._group_depth > 0` (old `:223`); `self._group_cursor.endEditBlock(); self._group_depth -= 1`; at depth 0 clear `_group_doc`/`_group_cursor`. Old single-action collapse (`:229-230`) and empty-group discard are free: one revision = one `undoCommandAdded`; zero edits = no signal.
- `checkpoint(self, doc)` — `self._checkpoint_heights[doc] = self._height(doc)`; `self._checkpoint_state[doc] = True`; emit `checkpointed(doc, True)` **unconditionally** (old `:187` emitted unconditionally; save/load flows at `meld/filediff.py:796, :1042` rely on the emission).
- `is_at_checkpoint(self, doc) -> bool` — `cp = self._checkpoint_heights.get(doc); return cp is not None and cp == self._height(doc)`. **RENAMED from the old `checkpointed()` method (`meld/undo.py:189-195`) — the name now belongs to the signal and PyQt forbids a method shadowing a class-level `pyqtSignal`.** Consumer WPs must use `is_at_checkpoint`.
- `clear(self)` — `assert self._group_depth == 0` (old `:80-81`); for each registered doc call `doc.clearUndoRedoStacks(QTextDocument.Stacks.UndoAndRedoStacks)`; `self._stack.clear(); self._next_redo = 0`; set every `_checkpoint_heights[d] = None` (old clear dropped all checkpoints, `:88`; the caller re-checkpoints right after reload — `meld/filediff.py:707` then `:796`); emit `can_undo_changed(False)`/`can_redo_changed(False)` only if previously true (old `:82-85`), updating `_can_undo`/`_can_redo`. No `checkpointed` emission (old clear emitted none).
- `_refresh_can_flags(self)` — compute `can_undo()`/`can_redo()`; emit `can_undo_changed`/`can_redo_changed` only on change; store.
- `_refresh_checkpoint(self, doc)` — `new = self.is_at_checkpoint(doc)`; if `new != self._checkpoint_state.get(doc, True)`: store and emit `checkpointed(doc, new)`.

**What replaces the old delete-capture re-diff path:** none of `BufferInsertionAction`/`BufferDeletionAction` (`meld/filediff.py:571-582`) is ported; WP6 re-diffs from `QTextDocument.contentsChange(position, charsRemoved, charsAdded)` + per-pane blockCount deltas. State this in a module docstring so WP4's agent doesn't go hunting for `add_action`.

**TRAPS:**
- Only `UndoSequence` may ever call `doc.undo()`/`doc.redo()` — the editor contract has `DiffTextEdit.keyPressEvent` swallow Ctrl+Z/Ctrl+Shift+Z/Ctrl+Y precisely so the widget's built-in undo never desynchronizes the coordinator stack. Put this invariant in the class docstring.
- Loading file content into a registered document fires `undoCommandAdded` once; the 1.4 flow (load → `clear()` → `checkpoint(doc)`, `meld/filediff.py:707, :796`) already handles it — WP6 must either follow that flow or wrap loads in `setUndoRedoEnabled(False)`. Docstring note.
- `checkpointed = pyqtSignal(object, bool)` — the first arg must be `object`, not `QTextDocument`: PyQt would otherwise refuse `None`-ish edge values and the doc contract fixes `object`.
- QTextDocument is used as a dict key — safe (sip wrappers hash by identity), but use `is` comparisons in `_height` (as specced) to avoid `__eq__` surprises.
- Do not connect `undoCommandAdded` with a plain lambda inside a `for` loop over docs (late-binding bug); use `functools.partial` or a default-arg lambda.

**Tests:** `tests/engine/test_undo.py` (all take pytest-qt's `qapp`; edit documents via `QTextCursor(doc).insertText(...)`; force distinct undo steps by inserting at document start vs end or by interleaving documents):
- `test_cross_pane_undo_order` — insert into A, into B, into A again → 3 stack entries; `undo()` ×3 restores both initial texts in reverse order; `redo()` ×3 restores final texts; `can_undo()`/`can_redo()` correct at every step.
- `test_signal_transitions` — record `can_undo_changed`/`can_redo_changed` emissions in lists; assert emitted only on transitions (True once on first command, False once when fully undone, etc.).
- `test_group_is_single_undo_step` — `begin_group(A)`, two inserts at different positions, `end_group()` → exactly one `undoCommandAdded` (count via a signal spy), stack height 1, one `undo()` reverts both edits. Also: nested begin/begin/end/end is one step; a group with zero edits adds nothing.
- `test_group_multi_doc_asserts` — `begin_group(A)` then `begin_group(B)` raises `AssertionError`.
- **Regression (undo.py:182 shape)** `test_checkpoint_with_mixed_docs_at_stack_top` — insert into A, insert into B (stack `[A, B]`), `undo()` once (`_next_redo == 1`), then `checkpoint(A)`: must not raise (the 1.4 code IndexErrors in exactly this stack-top configuration at `meld/undo.py:182`) and `is_at_checkpoint(A)` is True.
- `test_modified_flag_roundtrip` — checkpoint(A); edit A → `checkpointed(A, False)` emitted once; `undo()` → `checkpointed(A, True)`; `redo()` → False again.
- `test_checkpoint_destroyed_by_divergent_edit` (old `:117-121` semantics) — edit A, `checkpoint(A)` (height 1), `undo()`, edit A anew → checkpoint destroyed: `is_at_checkpoint(A)` False, and undoing back to height 1... asserts still False (height matches but checkpoint is `None`).
- `test_cross_doc_checkpoint_destroyed_by_truncation` — edit A, edit B, `checkpoint(B)` (B-height 1), `undo()` ×2, edit A → B's checkpoint destroyed (its height-1 state was in the truncated tail).
- `test_busy_guard` — set `seq._busy = True`, edit a registered doc, assert stack unchanged; and a normal `undo()` leaves stack length unchanged (only `_next_redo` moves).
- `test_clear` — after edits, `clear()`: `can_undo()` False, both docs' `documentAvailableUndoSteps`-equivalent behavior (a subsequent `undo()` assert-fails), checkpoints gone until re-checkpointed.

---

### Contracts consumed / provided

**Consumed (from WP0):** `meldq` package importable; `meldq/conf.py` exposing `_`; `pyproject.toml` with `PyQt6>=6.6`, dev deps `pytest`, `pytest-qt`; `tests/` directory (this WP adds `tests/conftest.py` with a session QApplication fixture if absent).

**Provided (later WPs code against these):**
- `meldq.engine.diffutil.Differ(QObject)` — `diffs_changed = pyqtSignal()` (zero args: slots must not expect the emitter — affects ports of `meld/filediff.py:205,:840` and any `connect("diffs-changed", ...)` site); full 1.4 chunk API: `set_sequences_iter` (generator: `yield None...yield 1`), `change_sequence`, `get_chunk`, `locate_chunk`, `pair_changes`, `single_changes`, `all_changes`, `diff_count`, `has_mergeable_changes`, `sequences_identical`, `clear`, `ignore_blanks` attribute.
- `meldq.engine.merge.AutoMergeDiffer`, `merge.Merger` — `Merger` is a plain class (no Differ base); consumers set `merger.differ`/`merger.texts` directly exactly as `meld/filediff.py:337-356` did.
- `meldq.engine.undo.UndoSequence(QObject)` — signals `can_undo_changed(bool)`, `can_redo_changed(bool)`, `checkpointed(object, bool)`; API: `register_document(doc)`, `begin_group(doc)` (**note: now takes the document**), `end_group()`, `undo()`, `redo()`, `can_undo()`, `can_redo()`, `checkpoint(doc)`, `is_at_checkpoint(doc)` (**renamed from `checkpointed()`**), `clear()`. There is NO `add_action` — recording is automatic via `undoCommandAdded`. WP4 must route Ctrl+Z through this class only and re-diff from `contentsChange`.
- `meldq.engine.task` — `SchedulerBase.runnable_cb` (single callable attribute, called with the scheduler; WP3's `SchedulerPump` sets it on the app-level `LifoScheduler`), `SchedulerEmpty`, generator-or-callable `add_task`, `iteration()` returning str/float/truthy for the statusbar convention (`meld/meldapp.py:262-270`).
- `meldq.util.misc` — pure helpers; `read_pipe_iter` yields `None` then exactly one `str` (utf-8, `errors="replace"`) and writes only `str` to `errorstream` (contract for the vcview WP re `meld/vcview.py:440-445`); `shorten_names` returns a `list[str]`.
- `run_dialog`/`open_uri` intentionally absent — WP3 provides Qt equivalents in `meldq/app.py`; grep hits for `misc.run_dialog` in later ports must be redirected there.

### Deleted (do-not-port)

- `meld/misc.py:33` `NULL` module fd — `subprocess.DEVNULL` exists.
- `meld/misc.py:92-123` `position_menu_under_widget` — QMenu clamps to monitors and handles RTL natively.
- `meld/misc.py:125-133` `make_tool_button_widget` — QToolButton draws its own dropdown indicator.
- `meld/undo.py:36-49` `GroupAction`, `:101-132` `add_action`, `:234-246` `abort_group` — replaced by QTextDocument-native recording; `abort_group` additionally has zero callers in 1.4 (verified by grep).
- `meld/task.py:37-42` `connect("runnable", ...)` callback list — replaced by `runnable_cb` per contract.
- `meld/task.py:180-222` `__main__` demo — replaced by `tests/engine/test_task.py`.
- `meld/merge.py:19,:25,:60-79` commented-out PatienceSequenceMatcher / alternative-merge experiments — dead weight.
- `meld/diffutil.py:263,:266,:270` commented py2 `print` debugging.
- `Merger(diffutil.Differ)` inheritance (`meld/merge.py:163`) — never initialized, no state used; lethal under QObject.

### Acceptance criteria

1. `python -m pytest tests/engine -q` exits 0 (expect ≥ 55 tests; none skipped except the GNU `diff`/`diff3` cross-checks on machines lacking the tools).
2. Purity: `python -c "import sys; import meldq.util.misc, meldq.engine.task, meldq.engine.matchers; sys.exit(1 if [m for m in sys.modules if m.startswith('PyQt6')] else 0)"` exits 0.
3. Regression tests exist and pass under these exact node IDs: `tests/engine/test_merge.py::test_delete_delete_split_tail_seq1` (fix for `meld/merge.py:131`), `tests/engine/test_undo.py::test_checkpoint_with_mixed_docs_at_stack_top` (fix for `meld/undo.py:182`), `tests/engine/test_task.py::test_remove_scheduler_disconnects` (fix for `meld/task.py:87-89`), plus the float-index test in `tests/engine/test_diffutil.py` exercising `single_changes(0)`/`single_changes(2)`/`pair_changes` on a 3-way diff (fix for `meld/diffutil.py:311/316/332`).
4. Verify test sensitivity by mutation: temporarily reintroduce `seq2` at the merge tail, `/2` at `diffutil` `:311`, and a lazy `filter` in `get_difference_opcodes` — each mutation must make at least one test fail; revert.
5. Signal smoke: `python -c "from PyQt6.QtWidgets import QApplication; import sys; app=QApplication(sys.argv); from meldq.engine.diffutil import Differ; d=Differ(); hits=[]; d.diffs_changed.connect(lambda: hits.append(1)); [None for _ in d.set_sequences_iter([['a','x'],['a','b']])]; assert hits == [1]; print('ok')"` prints `ok`.
6. Hygiene greps are clean: `grep -rn "gobject\|import gtk\|pygtk" meldq/` → no matches; `grep -rn "\.next()" meldq/` → no matches; `grep -rn "PyQt6" meldq/util/misc.py meldq/engine/task.py meldq/engine/matchers.py` → no matches.
7. GNU cross-check tests pass on a machine with `diff`/`diff3` on PATH (`python -m pytest tests/engine/test_opcodes_corpus.py tests/engine/test_merge.py -q` with zero skips there).
8. Undo end-to-end check (covers the rebuilt coordinator against real Qt documents): `python -m pytest tests/engine/test_undo.py -q` exits 0 and includes ≥ 10 test functions.
9. The old tree is untouched: `git status --porcelain meld/ bin/` shows no modifications.

### Estimated effort

**6–7 person-days** (T2.1: 0.5, T2.2: 1, T2.3: 1, T2.4: 1, T2.5: 0.5, T2.6: 1, T2.7: 1.5–2, plus 0.5 slack for corpus iteration). Consistent with the strategy doc's Phase-1 band (3–6 pd) plus the golden-corpus work it assigned to Phase 0.

---

## WP3 — Application shell (`meldq/app.py`, `doc.py`, `conf.py`, `main.py`, `util/prefs.py`)

### Goal

Build the PyQt6 application shell that every document type plugs into: `MeldWindow` (QMainWindow with a QTabWidget of comparisons, fixed menus/toolbar with named placeholder sections, statusbar + progress), the `DocActionManager` that replaces gtk.UIManager per-tab merging, the `SchedulerPump` that replaces the `gobject.idle_add` pump, the `MeldDoc(QObject)` base class, the new-comparison and about dialogs, a QSettings-backed `Preferences(QObject)` with one-time migration from `~/.meld/meldrc.ini`, and the `meldq` console entry point with 1.4-compatible CLI semantics. The old files `meld/meldapp.py`, `meld/melddoc.py`, `meld/preferences.py` (store half only), `meld/util/prefs.py`, `meld/paths.py`, and `bin/meld` are the behavioral spec; deviations are only those listed in **Deleted** and in the normative contracts below.

### Dependencies

- **WP0 (scaffolding)** — `meldq/` package exists with `meldq/__init__.py` containing `__version__ = "2.0.0a0"`; `pyproject.toml` with PyQt6>=6.6 and pytest + pytest-qt dev deps; `tests/` runnable. If WP0 has not landed, create the minimal skeleton as part of T3.1 (it is idempotent).
- **WP2 (engine port)** — consumed APIs: `meldq/engine/task.py` (`FifoScheduler`/`LifoScheduler`, pure Python, `runnable_cb` callback attribute, `iteration()`, `tasks_pending()`, `add_task()`, `remove_task()`, `remove_scheduler()`) and `meldq/engine/undo.py` (`UndoSequence(QObject)` with `can_undo_changed(bool)`, `can_redo_changed(bool)` signals and `can_undo()`, `can_redo()`, `clear()` methods).
- **Widgets WP (assumed WP4)** — `meldq/widgets/historycombo.py:FileHistoryCombo` blocks **T3.8 only** (exact consumed API listed there). All other tasks of WP3 have no widget dependencies; execute T3.8 last and skip it if the widget has not landed, leaving the `Ctrl+N` action wired to a `QMessageBox` stub. Under the strict §3 order this is always the case: T3.8 — together with AC3's `tests/test_newcomparison.py` and AC6 — is executed as the first task after WP4's T4.5 lands.

No doc WP (filediff/dirdiff/vcview) is a dependency: **all imports of doc modules in `app.py` must be lazy** (inside the `append_*` methods) so the shell runs and is testable before any view is ported (see T3.7).

### Old-code map

| Old code | What it does | New home |
|---|---|---|
| `bin/meld:22-31` | Unbuffered stdout wrapper | delete (py3 line-buffering suffices) |
| `bin/meld:34-38` | `--pychecker` hook | delete |
| `bin/meld:41-46` | `--sm-config-prefix`/`--sm-client-id` stripping | delete (Qt handles `-session`) |
| `bin/meld:48-53, 119-123` | `--profile` flag + `profile.run` | `meldq/main.py` (cProfile) |
| `bin/meld:56-61` | `meld.doap` sentinel → sys.path bootstrap, `#LIBDIR#` token | `meldq/conf.py:running_from_source()`; sys.path hack deleted (entry point) |
| `bin/meld:63-69` | gettext bind/textdomain "meld" | `meldq/conf.py:init_i18n()` |
| `bin/meld:71-102` | version gates; **latent bug at :77** (leaked `except` var `e`) | `meldq/main.py:_missing_reqs()` — bug fixed + regression test |
| `bin/meld:109-111` | `gtk.glade.bindtextdomain`, icon-theme search path | deleted (strings set from Python via `_()`; window icon in `main.py`) |
| `meld/paths.py:19-48` | `#TOKEN#` resource dirs, `ui_dir`/`icon_dir`/`locale_dir` | `meldq/conf.py` resource helpers over `importlib.resources` |
| `meld/meldapp.py:58-94` | `NewDocDialog` (new comparison) | `meldq/app.py:NewComparisonDialog` + `meldq/ui/newcomparison.ui` |
| `meld/meldapp.py:103-116` | `MeldStatusBar` push/pop wrapper | `MeldWindow.set_task_status()/set_doc_status()` (last-message-wins QLabels) |
| `meld/meldapp.py:130-218` | `MeldApp.__init__`: window, actions, UIManager, DnD, prefs hooks, scheduler | `meldq/app.py:MeldWindow.__init__` (code-built menus/toolbar) |
| `meld/meldapp.py:138-178` | 38 actions + 3 toggle actions (labels, accels, tooltips) | `MeldWindow._build_actions()` QAction table (T3.6) |
| `meld/meldapp.py:187-260` | connect-proxy → statusbar tooltip machinery | deleted → `QAction.setStatusTip` |
| `meld/meldapp.py:200-205, 228-232` | drag-dest + gnomevfs URI drop | `MeldWindow.dragEnterEvent/dropEvent` via `QMimeData.urls()` |
| `meld/meldapp.py:210-212, 262-285` | idle pump (`on_idle`, `on_scheduler_runnable`, `idle_hooked`) | `meldq/app.py:SchedulerPump` (T3.5) |
| `meld/meldapp.py:213, 335-337` | default size from prefs; **size written on every `size_allocate`** | restore at init; debounced save in `resizeEvent` (T3.6) |
| `meld/meldapp.py:217-226` | window focus in/out → docs' `on_focus_change` | `MeldWindow.changeEvent` (ActivationChange) |
| `meld/meldapp.py:287-293` | pref-change → toolbar/statusbar visibility | `MeldWindow._on_pref_changed` (toolbar_style branch deleted) |
| `meld/meldapp.py:298-317` | delete_event; `on_switch_page` UIManager merge, undo sensitivity, title | `closeEvent`; `MeldWindow._on_current_tab_changed` + `DocActionManager.set_doc` (T3.7) |
| `meld/meldapp.py:319-333` | tab-label/title updates, can-undo/redo, next-diff sensitivity | same-named slots on `MeldWindow` (T3.7) |
| `meld/meldapp.py:342-414` | File/Edit menu dispatch incl. clipboard isinstance dispatch | `MeldWindow.on_menu_*` slots; clipboard via `focusWidget()` duck-typing |
| `meld/meldapp.py:419-433` | preferences dialog launch, fullscreen, toggles | slots (prefs *dialog* itself is another WP; keep a stub slot) |
| `meld/meldapp.py:438-450` | help/bug/about | `QDesktopServices.openUrl`; `MeldWindow.show_about()` |
| `meld/meldapp.py:455-462` | next/prev diff via `gtk.gdk.SCROLL_*`; stop | `doc.py:Direction` enum; `current_doc().next_diff(...)`/`.stop()` |
| `meld/meldapp.py:464-493` | `try_remove_page`, `on_file_changed` broadcast, `_append_page` | same-named methods on `MeldWindow` (T3.7) |
| `meld/meldapp.py:495-554` | `append_dirdiff/filediff/diff/vcview` factories | same names, **lazy imports** (T3.7) |
| `meld/meldapp.py:559-566` | `current_doc()` + DummyDoc null object | `MeldWindow.current_doc()` + module-level `_DummyDoc` |
| `meld/meldapp.py:571-623` | optparse CLI (`--diff` greedy callback, usage text) | `meldq/main.py:parse_args()` (argparse) (T3.9) |
| `meld/meldapp.py:625-646` | `_single_file_open`, `open_paths` | `MeldWindow._single_file_open` (transient `SchedulerPump`), `open_paths` |
| `meld/melddoc.py:29` | `RESULT_OK/RESULT_ERROR` | `meldq/doc.py` module constants (verbatim) |
| `meld/melddoc.py:31-51` | GObject signals + init (undosequence, scheduler, prefs, label) | `meldq/doc.py:MeldDoc(QObject)` (T3.4) |
| `meld/melddoc.py:63-79` | `_open_files` external editor (`os.spawnvp`) | `MeldDoc._open_files` via `subprocess.Popen`/`QDesktopServices` |
| `meld/melddoc.py:112-124` | `on_container_switch_in/out_event` UIManager merge | **deleted** → doc-actions contract + `DocActionManager` |
| `meld/melddoc.py:126-141` | `on_delete_event` RESPONSE protocol, `on_quit_event` | `doc.py:CloseResponse(IntEnum)` + same-named methods |
| `meld/preferences.py:237-286` | `MeldPreferences.defaults` schema (colors, filters, regexes) | `meldq/util/prefs.py:DEFAULTS` (converted colors/fonts) (T3.2) |
| `meld/preferences.py:291-297` | `get_current_font` (gconf desktop font) | `Preferences.get_current_font() -> QFont` via `QFontDatabase.systemFont(FixedFont)` |
| `meld/preferences.py:299-308` | `get_toolbar_style` (gconf) | deleted → fixed `Qt.ToolButtonStyle.ToolButtonTextUnderIcon` |
| `meld/preferences.py:310-325` | `get_gnome_editor_command` | deleted; `edit_command_type` collapses to `internal`/`custom` |
| `meld/preferences.py:327-328` | `get_custom_editor_command` | `Preferences.get_custom_editor_command()` (verbatim) |
| `meld/preferences.py:31-233` | `ListWidget` + `PreferencesDialog` | **T3.10 below** — the preferences dialog IS part of this WP; it consumes this WP's store |
| `meld/util/prefs.py:39-59` | `Value` class + type constants | `meldq/util/prefs.py` (kept) |
| `meld/util/prefs.py:65-143` | `GConfPreferences` | deleted wholesale |
| `meld/util/prefs.py:145-235` | `ConfigParserPreferences` (INI write-through) | deleted; INI kept **read-only** for migration (T3.3) |
| `data/ui/meldapp.glade:5-70` | main window markup | code-built `MeldWindow` |
| `data/ui/meldapp.glade:71-97` | about dialog | `MeldWindow.show_about()` (QMessageBox.about) |
| `data/ui/meldapp.glade:98-491` | newdialog (3 tabs, 7 history entries, 2 checkboxes) | `meldq/ui/newcomparison.ui` + `NewComparisonDialog` (T3.8) |
| `data/ui/meldapp.glade:492-561` | `popup_new` menu (dead handlers) | **do not port** |
| `data/ui/meldapp-ui.xml:1-68` | menubar/toolbar/placeholder merge spec | `MeldWindow._build_menus()` ordered tables + `DocActionManager` (T3.6/T3.7) |

### Tasks

---

#### T3.1 — `meldq/conf.py`: late-bound gettext, resource paths, running-from-source (commit: "conf: i18n + resource resolution")

Old refs: `bin/meld:56-69`, `meld/paths.py:19-48`, trap `meld/preferences.py:262-282`.

Create `meldq/conf.py`. **Importing PyQt6 in this module is forbidden** (engine/tests must be able to import `_` headlessly). Contents:

```python
"""gettext init (exposes _, ngettext) and resource paths for meldq."""
import gettext as _gettext_module
from importlib import resources
from pathlib import Path

APPLICATION_NAME = "Meld"
GETTEXT_DOMAIN = "meld"          # MUST stay "meld": the 34 po/ catalogs use this domain
HELP_URL = "https://meldmerge.org/help/"
BUG_REPORT_URL = "http://bugzilla.gnome.org/buglist.cgi?query=product%3Ameld"  # verbatim from meldapp.py:442

_translation = _gettext_module.NullTranslations()

def _(message: str) -> str:
    return _translation.gettext(message)

def ngettext(singular: str, plural: str, n: int) -> str:
    return _translation.ngettext(singular, plural, n)

def mnemonic(label: str) -> str:
    """Convert a GTK '_x' mnemonic label (the msgid form) to Qt '&x'."""
    # escape literal '&' first, then replace only the FIRST '_'
    return label.replace("&", "&&").replace("_", "&", 1)

def package_dir() -> Path: ...          # Path(resources.files("meldq"))
def ui_file(name: str) -> Path: ...     # package_dir()/"ui"/name
def icon_path(name: str) -> Path: ...   # package_dir()/"resources"/"icons"/name
def locale_dir() -> Path: ...           # see below
def running_from_source() -> bool: ...  # see below
def init_i18n() -> None: ...            # see below
```

- `running_from_source()`: True iff `package_dir().parent / "pyproject.toml"` exists (replaces the `meld.doap` sentinel at `bin/meld:57`; sys.path patching is gone — the console script imports an installed/`pip install -e` package).
- `locale_dir()`: if `package_dir()/"resources"/"locale"` exists return it; else if `running_from_source()` return `<repo_root>/build/locale` (where the packaging WP's msgfmt step will put `<lang>/LC_MESSAGES/meld.mo` during dev). Missing dirs are fine — see fallback.
- `init_i18n()`: `global _translation; _translation = gettext.translation(GETTEXT_DOMAIN, localedir=str(locale_dir()), fallback=True)`. **Late binding is the point**: modules do `from meldq.conf import _` and call `_()` at import time (the `preferences.py:262-282` pattern survives in the prefs defaults); because `_` delegates to the module-global translation, calling `init_i18n()` before those modules are imported makes their import-time strings translate, and forgetting to call it degrades to English instead of crashing.
- Copy `data/icons/icon.png` → `meldq/resources/icons/icon.png` (app/window icon; XPM conversion of other icons belongs to the icon/packaging WP).

Also create `tests/conftest.py` (if absent) with `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` at module top, before any Qt import.

Tests — `tests/test_conf.py`:
1. Subprocess check that conf is Qt-free: `python -c "import meldq.conf, sys; sys.exit(1 if 'PyQt6' in sys.modules else 0)"`.
2. `mnemonic("_File") == "&File"`, `mnemonic("Find Ne_xt") == "Find Ne&xt"`, `mnemonic("A & B_x") == "A && B&x"`.
3. `_("anything")` returns its argument before `init_i18n()` (NullTranslations) and does not raise after `init_i18n()` with no catalogs present (`fallback=True`).
4. `ui_file("newcomparison.ui")`, `icon_path("icon.png")` return paths inside the package; `icon_path("icon.png").exists()`.

TRAPS:
- `bin/meld:77` — `print _("Cannot import: ") + mod + "\n" + str(e)` references `e` leaked from an enclosing `except` clause; in py3 except-vars don't leak → NameError. The launcher error path is rewritten in T3.9, not translated.
- `bin/meld:90,96,101` — `except (ImportError, AssertionError), e` is a py2 SyntaxError in py3; do not copy any launcher code verbatim.
- `meld/paths.py:19-24` — the `( #LOCALEDIR# )` empty-tuple sed-token trick must NOT be reproduced; `importlib.resources` replaces it.
- gettext domain: using `"meldq"` instead of `"meld"` silently orphans all 34 catalogs — keep `"meld"`.
- GTK mnemonics: msgids contain `_` (`_File`, `Prefere_nces`, `Find Ne_xt` at `meldapp.py:139-172`; `_Three Way Compare` at `meldapp.glade:131`). Qt uses `&`. Always call `conf.mnemonic(_(msgid))` — translating first, then converting — otherwise translated strings lose their (translated) mnemonics or show literal underscores.

---

#### T3.2 — `meldq/util/prefs.py`: `Preferences(QObject)` over QSettings (commit: "prefs: QSettings store")

Old refs: `meld/util/prefs.py:39-59` (Value), `:145-235` (ConfigParser backend semantics), `meld/preferences.py:237-286` (schema), `:288-289` (rootkey), `:291-328` (helpers).

Create `meldq/util/prefs.py`:

```python
from PyQt6.QtCore import QObject, QSettings, pyqtSignal
from PyQt6.QtGui import QFont, QFontDatabase
from meldq.conf import _

BOOL, INT, STRING, FLOAT = "bool", "int", "string", "float"   # keep old type tags (util/prefs.py:56-59)

class Value:                       # verbatim from util/prefs.py:39-53
    __slots__ = ("type", "default", "current")

def make_settings() -> QSettings:
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "meldq", "meldq")

class Preferences(QObject):
    changed = pyqtSignal(str)      # pref name; receivers read the new value off the object

    def __init__(self, settings: QSettings | None = None, parent: QObject | None = None): ...
    def __getattr__(self, name): ...     # returns self._values[name].current, AttributeError otherwise
    def __setattr__(self, name, value): ...
    def get_default(self, name): ...     # util/prefs.py:102-103 verbatim
    def get_current_font(self) -> QFont: ...
    def get_custom_editor_command(self, files: list[str]) -> list[str]: ...
```

**Key naming (normative for every WP):** all schema values under group `prefs/` → `prefs/<name>` (e.g. `prefs/tab_size`); `history/<history_id>` is reserved for `HistoryCombo` persistence (`history/file_comparison`, `history/dir_comparison`, `history/vc_directory` — the glade `string1` ids at `meldapp.glade:146,284,408`); `migration/meldrc_done` (bool) for T3.3. `QSettings.Format.IniFormat` is forced so storage is a plain INI on all platforms (deterministic tests, greppable user config).

**Attribute plumbing** — QObject makes this a trap (see TRAPS): `__setattr__` must be `if "_values" in self.__dict__ and name in self._values: <write path> else: super().__setattr__(name, value)`. Write path: coerce nothing, compare `value.current != val` (keep the short-circuit from `util/prefs.py:105-107`), then `self._settings.setValue(f"prefs/{name}", val)` and `self.changed.emit(name)`. Load path in `__init__`: for each schema key with `settings.contains(f"prefs/{name}")`, set `value.current = _coerce(settings.value(f"prefs/{name}"), value.type)`.

`_coerce(raw, type_tag)`: BOOL — pass through real bools; strings `"true"/"1"` → True, `"false"/"0"` → False (case-insensitive; the old backend stored `str(True)` = `"True"`, `util/prefs.py:206`); INT/FLOAT — `int()`/`float()` of the string; STRING — `str(raw)`. On coercion error, fall back to the default (do not crash on a hand-edited ini).

**Schema** — `DEFAULTS: dict[str, Value]` module-level, carried from `preferences.py:237-286` with these conversions (all other keys/defaults verbatim, including `window_size_x/y` 600, `tab_size` 4, `text_codecs` "utf8 latin1", `edit_wrap_lines` int 0, `toolbar_visible`/`statusbar_visible` True, `vc_console_visible` False):

| key | old default | new default |
|---|---|---|
| `custom_font` | `"monospace, 14"` (Pango, `preferences.py:241`) | `"monospace,14"` (parsed by `QFont.fromString`) |
| `color_delete_bg` | `"DarkSeaGreen1"` | `"#c1ffc1"` |
| `color_delete_fg` | `"Red"` | `"#ff0000"` |
| `color_replace_bg` | `"#ddeeff"` | unchanged |
| `color_replace_fg` / `color_conflict_fg` / `color_edited_fg` | `"Black"` | `"#000000"` |
| `color_conflict_bg` | `"Pink"` | `"#ffc0cb"` |
| `color_inline_bg` | `"LightSteelBlue2"` | `"#bcd2ee"` |
| `color_inline_fg` | `"Red"` | `"#ff0000"` |
| `color_edited_bg` | `"gray90"` | `"#e5e5e5"` |
| `edit_command_type` | `"gnome"` | `"internal"` (allowed values now `internal`/`custom`) |

The `filters` and `regexes` defaults keep their **exact** `_()`-wrapped msgids from `preferences.py:262-282`, including the `#TRANSLATORS:` comments (xgettext will need them), but with escape fixes (see TRAPS). The `Version Control` filter line is built via `_( "Version Control\t1\t%s\n") % _vc_filter_pattern()` where `_vc_filter_pattern()` lazily does `from meldq.vc import get_plugins_metadata; from meldq.util.misc import shell_escape` and falls back to the literal `"CVS .svn .hg .bzr .git"` on ImportError (the descoped plugin set — `vc/__init__.py:38-46`, `misc.py:294-297`; the brace-escaping in `shell_escape` only mattered for the descoped tla `{arch}`).

`get_current_font()`: if `self.use_custom_font`: `f = QFont(); f.fromString(self.custom_font); return f`; else `return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)` (replaces the gconf desktop key at `preferences.py:295-297`; the `"Monospace 10"` string fallback disappears).

Tests — `tests/test_prefs.py` (pytest-qt; construct with `QSettings(str(tmp_path/"t.ini"), QSettings.Format.IniFormat)` injected):
1. Defaults readable as attributes; `get_default("tab_size") == 4`.
2. Set → persisted: `p.tab_size = 8`; new `Preferences` over the same file reads 8 (typed int, not `"8"`).
3. `changed` signal: `qtbot.waitSignal(p.changed)` fires with `"tab_size"` exactly once per change; assigning an equal value emits nothing (short-circuit).
4. Bool round-trip through INI strings (`"true"`, and legacy `"True"`).
5. `AttributeError` on unknown key; plain instance attributes (e.g. `p._settings`) still work.
6. **Escape-regression** (survey trap `preferences.py:272,276`): assert the runtime default strings equal the py2-evaluated literals, e.g. `regexes` line 1 == `"CVS keywords\t0\t\\$\\w+(:[^\\n$]+)?\\$\n"` evaluated (`\$` … a literal backslash-dollar) and the C-comment line contains `/\*.*?\*/` — i.e. the new **source** doubles the invalid escapes (`\\$`, `\\*`) so the runtime string (and therefore the gettext msgid lookup) is unchanged while py3 stops warning.
7. `python -W error -c "import meldq.util.prefs"` exits 0 (no SyntaxWarning from invalid escapes).

TRAPS:
- `preferences.py:262-282` — module-import-time `_()` calls: with T3.1's late-bound `_` this is safe, but `main()` must call `conf.init_i18n()` **before** importing `meldq.app`/`meldq.util.prefs`, else defaults freeze as English for the process. Enforced in T3.9.
- `preferences.py:272` `"\$\\w+..."` and `:276` `"/\*.*?\*/"` — invalid escape sequences: py2 silently kept the backslash; py3.12 warns, future py3 errors. Fix by doubling backslashes, NOT by `r""`-prefixing blindly — `\t`, `\n` in the same literals must keep their meaning, and the runtime value must be byte-identical or 34 catalogs orphan these entries (test 6 pins it).
- QObject + `__setattr__`: `QObject.__init__` and pyqtSignal machinery set instance attributes; routing every setattr through the schema dict breaks construction. The `"_values" in self.__dict__` guard pattern above is mandatory; set `self.__dict__["_values"]`/`self.__dict__["_settings"]` directly before calling anything else.
- `util/prefs.py:206` `self._parser.set(None, attr, str(val))` — py3 configparser rejects a `None` section; irrelevant here only because the write path is deleted, but the migration reader (T3.3) must use `parser.defaults()`, not `parser.get(None, ...)`.
- `util/prefs.py:163` `SafeConfigParser` removed in py3.12; `:186` `readfp` removed in py3.11 — use `RawConfigParser` + `read()` in T3.3.
- `util/prefs.py:111-115, 217-221` — `try/except StopIteration` around plain listener for-loops is a dead py2 idiom; do not reproduce; the signal replaces the listener list.
- `util/prefs.py:142, 235` — `print k, v.type, v.current` py2 print statements; drop `dump()` or make it `print(...)`.
- Old `notify_add(cb)` delivered `(attr, val)` (`util/prefs.py:130-136`); the contract signal is `changed(str)` **name only** — every consumer (e.g. `melddoc.py:49`, `meldapp.py:209`) must re-read the value from the prefs object. Document in the class docstring.
- QSettings returns strings for everything under IniFormat — never compare `settings.value(k) == True`.
- gconf desktop keys (`preferences.py:295-325`) are gone: no system-monospace-font key (→ `QFontDatabase`), no toolbar style, no gnome editor command. `edit_command_type == "gnome"` must never be produced or consumed again.

---

#### T3.3 — One-time migration from `~/.meld/meldrc.ini` (commit: "prefs: legacy meldrc.ini migration")

Old refs: `meld/util/prefs.py:173-194` (path + read), `meld/preferences.py:241` (Pango font), `:252-261` (X11 colors), `:247` (edit_command_type).

Add to `meldq/util/prefs.py`:

```python
def legacy_ini_path() -> pathlib.Path: ...
    # util/prefs.py:173-181: win32 → %APPDATA%/Meld/meldrc.ini (Windows deferred, keep the branch), else ~/.meld/meldrc.ini

def migrate_legacy_prefs(settings: QSettings, ini_path: pathlib.Path | None = None) -> bool:
    """Copy 1.4 meldrc.ini values into QSettings once. Returns True if a migration ran."""

X11_COLORS: dict[str, str]                      # lowercase name -> "#rrggbb"
def x11_color_to_hex(name: str) -> str | None: ...
def pango_font_to_qfont_string(pango: str) -> str: ...
```

`Preferences.__init__` calls `migrate_legacy_prefs(self._settings)` **before** loading values, guarded by: skip if `settings.value("migration/meldrc_done")` is truthy; skip (but still set the flag) if the ini does not exist. Migration algorithm:

1. `parser = configparser.RawConfigParser()` (**Raw**: stored regex/filter values contain `%` and `$` — interpolation would raise `InterpolationSyntaxError`); `parser.read(ini_path, encoding="utf-8")`; values are in `parser.defaults()` (the 1.4 backend wrote everything into `[DEFAULT]`, `util/prefs.py:193,206`).
2. For each `(key, raw)` in `defaults()` with `key in DEFAULTS`: coerce with `_coerce(raw, DEFAULTS[key].type)`; then per-key conversions:
   - `color_*`: `raw` may be an X11 name — if it starts with `#` keep it; else `x11_color_to_hex(raw)`; if unknown, drop the key (falls back to new default). Never write an unconverted name: `QColor("DarkSeaGreen1")` is invalid.
   - `custom_font`: `pango_font_to_qfont_string(raw)`.
   - `edit_command_type`: `"gnome"` → `"internal"`.
3. Write converted values to `prefs/<key>`; finally `settings.setValue("migration/meldrc_done", True)` and `settings.sync()`.

`X11_COLORS` must contain at least the 1.4 default palette (`darkseagreen1 #c1ffc1`, `lightsteelblue2 #bcd2ee`, `pink #ffc0cb`, `red #ff0000`, `black #000000`) plus the ~30 most common X11 tint names (`*1`-`*4` variants of seagreen/steelblue/etc. are cheap to include). `x11_color_to_hex`: lowercase, strip spaces; handle `gray<N>`/`grey<N>` programmatically (`v = round(N * 255 / 100)`, so `gray90` → `#e5e5e5`); else table lookup; else `QColor(name)` validity check (SVG names like `pink` are valid) returning `QColor(name).name()`; else None.

`pango_font_to_qfont_string("Monospace 12")`/`("monospace, 14")`: split on whitespace after replacing `,` with ` `; if the last token is an int, it is the point size (default 10); among the remaining trailing tokens, consume case-insensitive `Bold`/`Italic` style words; the rest joined is the family. Build `QFont(family, size)`, apply `setBold/setItalic`, return `.toString()`.

Tests — `tests/test_prefs_migration.py`: write a fixture ini
```
[DEFAULT]
window_size_x = 1000
use_custom_font = True
custom_font = Monospace 12
color_delete_bg = DarkSeaGreen1
color_edited_bg = gray90
edit_command_type = gnome
tab_size = 8
regexes = CVS keywords	0	\$\w+(:[^\n$]+)?\$
```
1. After constructing `Preferences` over fresh QSettings + this ini: `window_size_x == 1000` (int), `use_custom_font is True`, `custom_font` round-trips via `QFont.fromString` to family "Monospace" pointSize 12, `color_delete_bg == "#c1ffc1"`, `color_edited_bg == "#e5e5e5"`, `edit_command_type == "internal"`, `regexes` preserved verbatim (RawConfigParser did not eat `%`/`$`).
2. Idempotence: constructing a second `Preferences` after deleting the ini does not lose migrated values (`migration/meldrc_done` short-circuits).
3. No ini present → flag set, defaults intact, no exception.
4. `x11_color_to_hex`: `("grey42")` → `#6b6b6b`, unknown junk → None; `("Pink")` → `#ffc0cb`.

TRAPS:
- `util/prefs.py:242` `import ConfigParser` → `configparser` (renamed).
- `util/prefs.py:163/186` `SafeConfigParser`/`readfp` — removed; and **interpolation**: 1.4 wrote raw user regexes; `ConfigParser` (non-Raw) chokes on `%` (`InterpolationSyntaxError`) — `RawConfigParser` is mandatory.
- `util/prefs.py:184-188` opened the ini with no encoding; py3 must pass `encoding="utf-8"` (user filter names may be non-ASCII).
- Booleans were stored as `str(True)` = `"True"` (`util/prefs.py:206`) — `_coerce` must accept `"True"/"False"` capitalized.
- `preferences.py:252-261` — five of ten color defaults are X11-only names; migrating them un-converted makes every chunk background invisible (QColor invalid → black/transparent), a **silent** failure. The conversion table is not optional.
- Old `window_size_x/y` may be absurd (the 1.4 bug wrote every intermediate resize); clamp migrated values to `>= 100` to be safe.

---

#### T3.4 — `meldq/doc.py`: `MeldDoc(QObject)` base + close protocol (commit: "doc: MeldDoc base class")

Old refs: `meld/melddoc.py:29-141` (whole file).

```python
import enum, os, subprocess, sys
from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from meldq.conf import _
from meldq.engine import task, undo

RESULT_OK, RESULT_ERROR = (0, 1)                      # melddoc.py:29

class CloseResponse(enum.IntEnum):                    # replaces gtk.RESPONSE_* (melddoc.py:126-135)
    OK = 0        # doc agrees to close
    CANCEL = 1    # doc vetoes close (and app quit)
    CLOSE = 2     # close without further callbacks (app-quit special case)

class Direction(enum.IntEnum):                        # replaces gtk.gdk.SCROLL_DOWN/UP (meldapp.py:456-459)
    DOWN = 1                                          # §2.2: THE app-wide direction enum; WP5/WP6/WP7 import it
    UP = -1

class MeldDoc(QObject):
    # contract signals — EXACT names
    label_changed = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    create_diff = pyqtSignal(list)
    closed = pyqtSignal()
    # 1.4-behavior extensions (melddoc.py:36-41), consumed by the shell
    file_changed = pyqtSignal(str)
    next_diff_changed = pyqtSignal(bool, bool)        # (have_prev, have_next)
    current_diff_changed = pyqtSignal()

    def __init__(self, prefs, parent: QObject | None = None): ...
    # attributes set in __init__ (melddoc.py:44-51):
    #   self.undosequence = undo.UndoSequence(self)
    #   self.scheduler = task.FifoScheduler()
    #   self.prefs = prefs; self.prefs.changed.connect(self.on_preference_changed)
    #   self.num_panes = 0
    #   self.label_text = _("untitled")
    #   self.widget: QWidget | None = None   # the tab page; set by subclasses before _append_page

    # doc/shell action contract (normative) — base returns empty
    def doc_actions(self) -> list["QAction"]: return []
    def menu_contributions(self) -> dict[str, list["QAction"]]: return {}
    def toolbar_contributions(self) -> list["QAction"]: return []

    # verbatim ports (melddoc.py:53-110)
    def save(self): pass
    def save_as(self): pass
    def stop(self): ...                                # melddoc.py:59-61
    def _open_files(self, selected: list[str]): ...    # see below
    def on_undo_activate(self): ...                    # melddoc.py:81-83
    def on_redo_activate(self): ...
    def on_refresh_activate(self, *extra): self.on_reload_activate(*extra)
    def on_reload_activate(self, *extra): pass
    def on_find_activate(self, *extra): pass
    def on_find_next_activate(self, *extra): pass
    def on_replace_activate(self, *extra): pass
    def on_preference_changed(self, key: str): pass    # NOTE: 1-arg now (prefs.changed carries name only)
    def on_file_changed(self, filename: str): pass
    def set_labels(self, lst: list[str]): pass
    def next_diff(self, direction: Direction): pass
    def on_focus_change(self): pass                    # called from MeldWindow.changeEvent
    def on_container_switch_in_event(self): pass       # NO-ARG activation hook; T3.7 calls it on tab switch-in
    def on_container_switch_out_event(self): pass      # counterpart, called on the outgoing doc
    def on_delete_event(self, appquit: bool = False) -> CloseResponse: return CloseResponse.OK
    def on_quit_event(self): pass                      # melddoc.py:137-141; vcview.py:357 overrides it
```

`_open_files` (from `melddoc.py:63-79`): files — if `self.prefs.edit_command_type == "custom"`: `cmd = self.prefs.get_custom_editor_command(files); subprocess.Popen(cmd)`; else (`"internal"`): `QDesktopServices.openUrl(QUrl.fromLocalFile(f))` per file. Dirs — `QDesktopServices.openUrl(QUrl.fromLocalFile(d))` (replaces the win32/darwin/xdg-open triple at `melddoc.py:74-79`).

Tests — `tests/test_doc.py`:
1. Signal signatures: `MeldDoc(prefs).label_changed` connect/emit with str; `create_diff` with list; `next_diff_changed` with (bool, bool).
2. `on_delete_event()` returns `CloseResponse.OK`; `CloseResponse.CANCEL != CloseResponse.OK`.
3. `stop()` removes the current task: add a generator task to `doc.scheduler`, call `stop()`, assert `not doc.scheduler.tasks_pending()`.
4. `prefs.changed` → `on_preference_changed` receives the key name (subclass records calls).
5. `_open_files` with `edit_command_type="custom"` and `edit_command_custom="echo"` spawns without raising (monkeypatch `subprocess.Popen` to record argv `["echo", <file>]`).

TRAPS:
- `melddoc.py:106-107` — old code has a **method** `label_changed()` that emits the signal of the same name; in the new class the pyqtSignal owns that name. Delete the method; all call sites in doc WPs must use `self.label_changed.emit(self.label_text)`. Any subclass defining `def label_changed` will shadow the signal and break the shell silently.
- `melddoc.py:36-41` — hyphenated signal names (`"label-changed"`) must not survive anywhere; grep for quotes-with-hyphen connect strings when porting call sites.
- `melddoc.py:69,72` — `os.spawnvp(os.P_NOWAIT, ...)`: absent on Windows, discouraged everywhere; `subprocess.Popen` (no `shell=True`).
- `melddoc.py:112-124` — the UIManager-arg `on_container_switch_in/out_event(uimanager)` and `self.ui_file`/`self.actiongroup`/`self.popup_menu` do **not** exist anymore; the doc-actions contract replaces the merge protocol. NO-ARG activation hooks of the same names remain on `MeldDoc` (see the listing) purely for focus/status refresh on tab switch. Doc WPs own their context menus as plain `QMenu`s.
- PyQt single-QObject-base rule: `MeldDoc` is plain `QObject`; subclasses must use **composition** for their widget (`self.widget`), never multiple inheritance from `QWidget` + `MeldDoc` (D6).
- `melddoc.py:90` calls `self.on_reload_activate(self, *extra)` — passes `self` twice (harmless py2 sloppiness); fix to `self.on_reload_activate(*extra)`.
- Emitting `status_changed` with non-str payloads: old `'status-changed'` was PYOBJECT (`melddoc.py:39`); the contract narrows it to `str` — doc WPs must stringify.

---

#### T3.5 — `meldq/app.py`: `SchedulerPump` (commit: "app: scheduler pump")

Old refs: `meld/meldapp.py:210-212` (hook), `:262-280` (`on_idle`), `:282-285` (`on_scheduler_runnable`), `meld/task.py:37-42,99-139` (scheduler protocol).

```python
class SchedulerPump(QObject):
    status_message = pyqtSignal(str)      # on_idle str branch  (meldapp.py:265-266)
    progress_fraction = pyqtSignal(float) # float branch        (meldapp.py:267-268)
    progress_pulse = pyqtSignal()         # other-truthy branch (meldapp.py:269-270)
    idle_changed = pyqtSignal(bool)       # True = no tasks pending (drives Stop sensitivity + status clear)

    def __init__(self, parent: QObject | None = None):
        # self._timer = QTimer(self); self._timer.setInterval(0)
        # self._timer.timeout.connect(self._tick)
        # self._scheduler = None; self._paused = False
    def set_scheduler(self, scheduler | None) -> None: ...
    def pause(self) -> None: ...    # modal-dialog guard: stop timer, remember state
    def resume(self) -> None: ...   # restart timer iff scheduler has pending tasks
    def stop(self) -> None: ...     # detach completely (used on window close)
    def _on_runnable(self, sched) -> None: ...
    def _tick(self) -> None: ...
```

Semantics (normative, per contract):
- `set_scheduler(s)`: on the old scheduler set `runnable_cb = None`; on the new set `s.runnable_cb = self._on_runnable`; start the timer iff `s.tasks_pending()` (emit `idle_changed(False)` on start).
- `_tick()` — **one scheduler iteration per timer tick** (translation of `on_idle`, `meldapp.py:262-280`): first `if getattr(self._scheduler, "paused", False): self._timer.stop(); return` (§2.5 — the pump skips paused schedulers; `resume()`/`_on_runnable` restart it); then `ret = self._scheduler.iteration()`; if `isinstance(ret, str)` → `status_message.emit(ret)`; elif `type(ret) is float` → `progress_fraction.emit(ret)`; elif `ret` → `progress_pulse.emit()`; then if `not self._scheduler.tasks_pending()`: `self._timer.stop()`; `status_message.emit("")`; `progress_fraction.emit(0.0)`; `idle_changed.emit(True)`.
- `_on_runnable`: if not paused and timer inactive → `self._timer.start()`; `idle_changed.emit(False)`.
- `pause()/resume()`: pump-internal helpers (stop timer / restart iff pending). Docs that raise modal dialogs from inside scheduled generators set `self.scheduler.paused = True/False` around `exec()` per §2.5 — `_tick` honors the flag (above), so no pump handle is needed inside docs; the pump stays exposed as `MeldWindow.pump` for the shell's own use.

**Design change vs 1.4 (contract-mandated):** 1.4 kept one global `LifoScheduler` into which every doc's `FifoScheduler` was chained (`meldapp.py:211, 317, 489`), so background tabs kept working. The new pump drives **only the current tab's scheduler**; background tabs' tasks freeze until re-selected. `MeldWindow._on_current_tab_changed` calls `pump.set_scheduler(doc.scheduler)`. The one 1.4 code path that ran a scheduler with no tab — `_single_file_open`, `meldapp.py:625-633` — gets a **transient private `SchedulerPump`** created in that method and torn down via its `idle_changed(True)`.

Tests — `tests/test_scheduler_pump.py` (pytest-qt; use the real `meldq.engine.task.FifoScheduler`):
1. Generator task yielding `0.25`, `"working"`, `1` then ending: with `qtbot.waitSignal(pump.idle_changed, timeout=2000)`, assert received: one `progress_fraction(0.25)`, one `status_message("working")`, one `progress_pulse`, final `status_message("")`+`progress_fraction(0.0)`+`idle_changed(True)`, and `pump._timer.isActive() is False` afterwards (no busy-spin at idle).
2. Adding a task to the attached scheduler restarts the timer via `runnable_cb` without any manual poke.
3. `pause()` during a running task stops ticks; `resume()` finishes it.
4. `set_scheduler(other)` detaches: tasks added to the old scheduler no longer tick, `old.runnable_cb is None`.

TRAPS:
- `meldapp.py:265` `type(ret) in (type(""), type(u""))` — py2 str/unicode dance → `isinstance(ret, str)`.
- `meldapp.py:267` `type(ret) == type(0.0)` — this is an **exact float** check; `isinstance(ret, float)` is fine but `isinstance(ret, (int, float))` is NOT: generators yield int `1` to mean "pulse", and `bool` must not be treated as a fraction. Keep `type(ret) is float`.
- `meldapp.py:283-285` idle_add returns 1/0 to stay/leave idle — the QTimer start/stop replaces the return-value protocol; an always-running 0 ms QTimer busy-spins a core (D4) — the stop-on-empty is mandatory, test 1 pins it.
- `task.py:127` — `get_current_task` raising `StopIteration` is caught inside `iteration()`; under PEP 479 that raise must not live inside a generator (engine WP's problem, but do not "simplify" the pump to call `get_current_task` directly).
- Scheduler generators must be consumed with `next()`/callables per the generator-protocol contract; the pump only ever calls `scheduler.iteration()`.
- `runnable_cb` may be `None` while a background tab adds tasks — the engine tolerates it; the pump must re-check `tasks_pending()` in `set_scheduler` to pick up work queued while detached (test 4's inverse).

---

#### T3.6 — `meldq/app.py`: `MeldWindow` — window, actions, menus, toolbar, statusbar, dialogs (commit: "app: MeldWindow shell")

Old refs: `meld/meldapp.py:125-260, 287-299, 335-477`, `data/ui/meldapp.glade:5-97`, `data/ui/meldapp-ui.xml:1-68`.

`class MeldWindow(QMainWindow)` — `__init__(self, prefs: Preferences)`:

1. **Window**: title `"Meld"`; `self.resize(prefs.window_size_x, prefs.window_size_y)` (`meldapp.py:213`); central widget `self.tabs = QTabWidget()` with `setTabsClosable(True)`, `setDocumentMode(True)`; `tabCloseRequested.connect(self._on_tab_close_requested)`; `currentChanged.connect(self._on_current_tab_changed)`.
2. **Actions** — `_build_actions()`: create every QAction as `self.action_<name>` with `conf.mnemonic(_(msgid))` texts, `QKeySequence` shortcuts, `QIcon.fromTheme` icons, and `setStatusTip(_(tooltip_msgid))`. The table is the 1.4 table at `meldapp.py:138-178`, verbatim msgids:

   | attr | text msgid | shortcut | theme icon | statusTip msgid |
   |---|---|---|---|---|
   | action_new | `_("_New...")` | Ctrl+N | document-new | `_("Start a new comparison")` |
   | action_save | "Save" | Ctrl+S | document-save | `_("Save the current file")` |
   | action_save_as | "Save As..." | Ctrl+Shift+S | document-save-as | `_("Save the current file with a different name")` (1.4 forgot `_()` at `meldapp.py:142` — fix) |
   | action_close | "Close" | Ctrl+W | window-close | `_("Close the current file")` |
   | action_quit | "Quit" | Ctrl+Q | application-exit | `_("Quit the program")` |
   | action_undo | "Undo" | Ctrl+Z | edit-undo | `_("Undo the last action")` |
   | action_redo | "Redo" | Ctrl+Shift+Z | edit-redo | `_("Redo the last undone action")` |
   | action_cut / copy / paste | "Cut"/"Copy"/"Paste" | Ctrl+X/C/V | edit-cut/copy/paste | `_("Cut the selection")` / `_("Copy the selection")` / `_("Paste the clipboard")` |
   | action_find | "Find..." | Ctrl+F | edit-find | `_("Search for text")` |
   | action_find_next | `_("Find Ne_xt")` | Ctrl+G | — | `_("Search forwards for the same text")` |
   | action_replace | `_("_Replace")` | Ctrl+H | edit-find-replace | `_("Find and replace text")` |
   | action_preferences | `_("Prefere_nces")` | — | preferences-system | `_("Configure the application")` |
   | action_prev_change | `_("Previous change")` | Ctrl+E | go-up | `_("Go to the previous change")` |
   | action_next_change | `_("Next change")` | Ctrl+D | go-down | `_("Go to the next change")` |
   | action_stop | "Stop" | Escape | process-stop | `_("Stop the current action")` |
   | action_refresh | "Refresh" | Ctrl+R | view-refresh | `_("Refresh the view")` |
   | action_reload | `_("Reload")` | Ctrl+Shift+R | view-refresh | `_("Reload the comparison")` |
   | action_help | `_("_Contents")` | F1 | help-contents | `_("Open the Meld manual")` |
   | action_bug | `_("Report _Bug")` | — | — | `_("Report a bug in Meld")` |
   | action_about | "About" | — | help-about | `_("About this program")` |
   | action_fullscreen (checkable) | `_("Full Screen")` | F11 | — | `_("View the comparison in full screen")` |
   | action_toolbar_visible (checkable, init `prefs.toolbar_visible`) | `_("_Toolbar")` | — | — | `_("Show or hide the toolbar")` |
   | action_statusbar_visible (checkable, init `prefs.statusbar_visible`) | `_("_Statusbar")` | — | — | `_("Show or hide the statusbar")` |

   Where 1.4 used a stock label (`None` action label, `meldapp.py:141-155`) the English word above is a **new** msgid (GTK translated stock labels itself); flag them with a `# new msgid vs 1.4` comment for the i18n WP.
3. **Menus** — `_build_menus()`: `self.menus: dict[str, QMenu]` with keys `"file","edit","changes","view","help"`, titles `conf.mnemonic(_("_File"))` etc. (`meldapp.py:139,146,157,161,169`). Ordering reproduces `meldapp-ui.xml:2-52`, with one **named placeholder section per menu** (two separator QActions, `objectName` `f"doc_section_start_{key}"` / `f"doc_section_end_{key}"`, both initially `setVisible(False)`):
   - File: New, Save, SaveAs, [placeholder], sep, Close, Quit (1.4 had no File placeholder — the contract adds one).
   - Edit: Undo, Redo, sep, Cut, Copy, Paste, [placeholder ⇔ `EditActionsPlaceholder`, meldapp-ui.xml:19], Find, FindNext, Replace, sep, Preferences.
   - Changes: PrevChange, NextChange, [placeholder ⇔ `ChangesActions`, meldapp-ui.xml:31].
   - View: ToolbarVisible, StatusbarVisible, Fullscreen, [placeholder ⇔ `ViewPlaceholder` **plus** the FileStatus/VcStatus/FileFilters submenu mounts, meldapp-ui.xml:38-41 — docs contribute submenus as `QMenu.menuAction()` entries in their `"view"` list], sep, Stop, Refresh, Reload.
   - Help: Help, BugReport, About, [placeholder — present for uniformity, never populated].
4. **Toolbar** — `self.toolbar = self.addToolBar("Toolbar")`, `setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)` (mimics `gtk.TOOLBAR_BOTH`, the `preferences.py:301` fallback), `setObjectName("main_toolbar")`. Contents per `meldapp-ui.xml:54-64` collapsed to one doc segment: New, [sep `doc_toolbar_start` hidden], [sep `doc_toolbar_end` hidden], PrevChange, NextChange, Stop. Visibility from `prefs.toolbar_visible` (`meldapp.py:207`).
5. **Statusbar** (`meldapp.glade:31-59`, `meldapp.py:103-116,198-199`): `self.progress = QProgressBar()` (fixed width 150, `setTextVisible(False)`), `self.task_status_label = QLabel()`, `self.doc_status_label = QLabel()`; all via `statusBar().addPermanentWidget(...)` in that order. Methods `set_task_status(str)` / `set_doc_status(str)` do `setText` (push/pop stack semantics deleted — last message wins). Action statusTips display in the statusbar's temporary area automatically (this **replaces** `meldapp.py:187-260` entirely). Visibility of `statusBar()` from `prefs.statusbar_visible`.
6. **Pump wiring**: `self.pump = SchedulerPump(self)`; connect `status_message→set_task_status`, `progress_fraction→self.progress.setValue` (scale 0-100: `int(f*100)`), `progress_pulse→` set `self.progress.setRange(0,0)` while pulsing and restore `(0,100)` on fraction/idle, `idle_changed→` `action_stop.setEnabled(not idle)` (+ initial `action_stop.setEnabled(False)`, mirroring `meldapp.py:274-279`).
7. **Prefs wiring**: `prefs.changed.connect(self._on_pref_changed)` handling `"toolbar_visible"`/`"statusbar_visible"` (`meldapp.py:287-293` minus the gconf `toolbar_style` branch).
8. **Geometry debounce** (fixes `meldapp.py:335-337` writing prefs on every `size_allocate`): `self._geometry_save_timer = QTimer(self)` single-shot, 500 ms, timeout → `prefs.window_size_x = self.width(); prefs.window_size_y = self.height()`. Override `resizeEvent` to call `super()` then `self._geometry_save_timer.start()` (restart-on-each-event = trailing-edge debounce).
9. **DnD** (`meldapp.py:200-205,228-232`): `setAcceptDrops(True)`; `dragEnterEvent`: `acceptProposedAction()` iff `mimeData().hasUrls()`; `dropEvent`: `paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]`; `self.open_paths(paths)`.
10. **Focus forwarding** (`meldapp.py:217-226`): override `changeEvent`; on `QEvent.Type.ActivationChange` call `doc.on_focus_change()` for every open doc.
11. **Slots** (translate `meldapp.py:342-462` one-to-one; every `current_doc().x()` dispatch keeps its name): `on_menu_file_new_activate` (opens `NewComparisonDialog` — stub `QMessageBox.information` until T3.8), save/save_as/close/quit, undo/redo/refresh/reload/find/find_next/replace, cut/copy/paste (clipboard dispatch: `w = self.focusWidget()`; call `w.cut()/copy()/paste()` if the attribute exists and is callable — covers QLineEdit, QPlainTextEdit, QComboBox.lineEdit; `meldapp.py:395-414`), preferences (stub until the prefs-dialog WP: open a `QMessageBox.information(self, "Meld", "Preferences dialog not ported yet")`), fullscreen (`isFullScreen()` ? `showNormal()` : `showFullScreen()`; `meldapp.py:422-427`), toolbar/statusbar toggles writing prefs (`meldapp.py:429-433`), help → `QDesktopServices.openUrl(QUrl(conf.HELP_URL))`, bug → `conf.BUG_REPORT_URL`, `on_menu_edit_down_activate`/`up` → `current_doc().next_diff(Direction.DOWN/UP)`, stop → `current_doc().stop()`.
12. **About** (`meldapp.py:444-450`, `meldapp.glade:71-97`): `show_about()` uses `QMessageBox.about(self, _("About Meld"), html)` with program name Meld, `meldq.__version__`, `_("Copyright © 2002-2009 Stephen Kennedy")`, and an `<a href="http://meld.sourceforge.net/">` link (QMessageBox labels open external links natively — the `gtk.about_dialog_set_url_hook` machinery dies).
13. **Quit protocol** (`meldapp.py:298-299,357-369,464-477`): `closeEvent(event)` runs the right-to-left loop: `for i in range(self.tabs.count()-1, -1, -1)` (comment from `meldapp.py:358-359`: a VC page in the far-left tab must close last), `self.tabs.setCurrentIndex(i)`, `resp = self.try_remove_page(doc, appquit=True)`; on `CloseResponse.CANCEL` → `event.ignore(); return`. Then `on_quit_event()` on any remaining docs, flush the geometry timer (write immediately if active), `event.accept()`.
14. **current_doc** (`meldapp.py:559-566`): returns the mapped doc for `tabs.currentWidget()` or the module-level `_DummyDoc` instance (`__getattr__` returning `lambda *a, **k: None` — keeps every menu handler safe with zero tabs, exactly like 1.4).

Tests — `tests/test_app_shell.py` (pytest-qt):
1. Window constructs offscreen; 5 menus titled `&File/&Edit/&Changes/&View/&Help`; toolbar and statusbar visible; progressbar present.
2. Each menu contains its two placeholder separators (find by objectName), initially invisible.
3. `action_stop` disabled at start; shortcuts: `action_new.shortcut() == QKeySequence("Ctrl+N")`, `action_next_change` Ctrl+D, `action_prev_change` Ctrl+E, `action_reload` Ctrl+Shift+R.
4. Geometry debounce: call `window.resize(700, 500)` then `qtbot.wait` past 500 ms → prefs updated once; three rapid resizes produce exactly one `changed("window_size_x")`/`("window_size_y")` burst (count signal emissions).
5. Toggling `action_statusbar_visible` hides `statusBar()` and writes `prefs.statusbar_visible == False`; flipping the pref externally (`prefs.statusbar_visible = True`) re-shows it.
6. `current_doc()` with no tabs returns an object whose arbitrary method calls are no-ops (DummyDoc).
7. closeEvent with zero tabs accepts (window closes).

TRAPS:
- `meldapp.py:335-337` — the size is persisted on EVERY resize event; a literal port hammers QSettings and emits a `changed` storm re-entering every doc's `on_preference_changed`. Debounce is mandatory (test 4).
- `meldapp.py:298` GTK `delete_event` truthiness is **inverted** vs Qt: GTK returns non-False to VETO the close; Qt vetoes with `event.ignore()`. Do not translate return values.
- `meldapp.py:132` `gtk.window_set_default_icon_name("icon")` vs `.desktop Icon=meld` — the D11 mismatch; the window icon is set once in `main.py` from the bundled `icon.png`, not by name lookup.
- `meldapp.py:133-134` `pygobject_version` guard and `:142` untranslated tooltip — delete guard, fix tooltip (wrap in `_()`).
- `meldapp.py:190-191` `props.is_important` has no Qt equivalent (it forced text-beside-icon for Save/Undo) — drop.
- `meldapp.py:396` `self.widget.get_focus()` is per-window; use `self.focusWidget()`, NOT `QApplication.focusWidget()` (which may point into a modeless dialog).
- Escape-as-shortcut for Stop (`meldapp.py:165`): give `action_stop` `Qt.ShortcutContext.WindowShortcut` (default) — it must not fire when a dialog is active; do not use ApplicationShortcut.
- The editor WP swallows Ctrl+Z/Ctrl+Shift+Z/Ctrl+Y in `keyPressEvent` (editor contract) so the window-level `action_undo/redo` are the single undo entry points — do not also install QShortcuts.
- `QProgressBar` pulse: GTK `pulse()` (`meldapp.py:270`) maps to `setRange(0,0)` (busy indicator); remember to restore `setRange(0,100)` before `setValue` or fractions render as busy.
- Statusbar `push/pop` with context ids (`meldapp.py:103-116,257-260`): Qt has no message stack; last-writer-wins labels are the agreed simplification — do not build a stack wrapper.
- `gnomevfs` availability gating (`meldapp.py:29-33,204`) disappears: `QMimeData.urls()` is unconditional.

---

#### T3.7 — `meldq/app.py`: `DocActionManager` + tab lifecycle (commit: "app: doc action manager and tab plumbing")

Old refs: `meld/meldapp.py:301-333` (switch_page), `:464-493` (`try_remove_page`, `_append_page`), `:479-483` (file-changed broadcast), `:495-554` (factories), `:625-646` (`_single_file_open`, `open_paths`), `meld/melddoc.py:112-124` (the replaced merge protocol), `data/ui/meldapp-ui.xml:19,31,38-41,54-64` (placeholder spec).

**DocActionManager** (normative — every doc WP codes against this):

```python
class DocActionManager(QObject):
    MENU_KEYS = ("file", "edit", "changes", "view")

    def __init__(self, window: "MeldWindow"): ...
    def set_doc(self, doc: MeldDoc | None) -> None:
        """Clear all placeholder sections and the toolbar doc segment,
        then repopulate from doc.menu_contributions()/doc.toolbar_contributions()."""
```

- Clearing: for each menu key, walk `menu.actions()` from the action after `doc_section_start_<key>` up to (exclusive) `doc_section_end_<key>` and `menu.removeAction(a)` each. `removeAction` does not destroy the QAction — actions stay parented to the doc's widget (`doc_actions()` contract) and simply become inert (their shortcuts stop firing), which implements "shortcuts active window-wide while the doc is current" with zero extra code. Same walk for the toolbar between `doc_toolbar_start`/`doc_toolbar_end`.
- Populating: `section = contributions.get(key, [])`; first map each `None` entry to a fresh `QAction` with `setSeparator(True)` (parented to the menu) — §2.4's `None`-=-separator convention (`insertActions` would crash on a raw `None`); then `menu.insertActions(end_separator, section)`; both boundary separators `setVisible(bool(section))`. Toolbar: `toolbar.insertActions(end_sep, doc.toolbar_contributions())` (same `None` mapping), separators likewise.
- `set_doc(None)` = clear only.
- Debug guard: assert no contributed action's `shortcut()` collides with a shell action's shortcut (catches a doc re-binding Ctrl+Z etc. at develop time).

**MeldWindow tab plumbing** (all on MeldWindow):

- `self._doc_for_widget: dict[QWidget, MeldDoc]` and `self._current_doc: MeldDoc | None` (Qt's `currentChanged(int)` gives no old index — track it; replaces `notebook.get_current_page()` juggling at `meldapp.py:304-307`).
- `_append_page(doc, icon_name)` (`meldapp.py:485-493`): register `self._doc_for_widget[doc.widget] = doc` **before** `self.tabs.addTab(doc.widget, QIcon.fromTheme(icon_name), doc.label_text)`; `setCurrentWidget`; connect `doc.label_changed → self.on_label_changed` (partial-bound with doc), `doc.file_changed → self.on_file_changed_broadcast`, `doc.create_diff → self.append_diff`, `doc.status_changed → self.set_doc_status`.
- `_on_current_tab_changed(index)` (translation of `on_switch_page`, `meldapp.py:301-317`): if there was a previous doc, disconnect its `next_diff_changed`, `undosequence.can_undo_changed/can_redo_changed` (wrap disconnects in `try/except TypeError`); if `index < 0`: `dam.set_doc(None)`, `pump.set_scheduler(None)`, title `"Meld"`, disable undo/redo/prev/next, return. Else resolve `doc`; `action_undo.setEnabled(doc.undosequence.can_undo())`, same for redo (`meldapp.py:309-310`); connect `doc.undosequence.can_undo_changed → action_undo.setEnabled` (and redo; `meldapp.py:325-329, 513-514`); connect `doc.next_diff_changed → self._on_next_diff_changed` (`meldapp.py:315-316, 331-333` — sets prev/next enabled); `setWindowTitle(f"{tab_text} - Meld")` (`meldapp.py:311-312`); `set_doc_status("")`; `dam.set_doc(doc)`; `pump.set_scheduler(doc.scheduler)`. Finally call `doc.on_container_switch_in_event()`; on the previous doc (if any) call `on_container_switch_out_event()` before its disconnects — both are the no-arg activation hooks T3.4 adds (default `pass`; WP5/WP6 override them for focus/status refresh).
- `on_label_changed(doc, text)` (`meldapp.py:319-323`): `tabs.setTabText(index_of(doc), text)`; if current, retitle window. (`child_set_property "menu-label"` at `:323` has no QTabWidget equivalent — use `setTabToolTip` instead.)
- `try_remove_page(doc, appquit=False) -> CloseResponse` (`meldapp.py:464-477`): `resp = doc.on_delete_event(appquit)`; if `resp != CloseResponse.CANCEL`: if doc is current → `dam.set_doc(None)`, `pump.set_scheduler(None)`; `tabs.removeTab(idx)`; `del self._doc_for_widget[doc.widget]`; `doc.closed.emit()`; if `tabs.count() == 0`: title `"Meld"`. Return resp.
- `_on_tab_close_requested(index)` → `try_remove_page(doc_at(index))`.
- `on_file_changed_broadcast(filename)` (`meldapp.py:479-483`): forward `on_file_changed(filename)` to every doc except the sender (`self.sender()` or partial-bind the source doc).
- Factories (`meldapp.py:495-554`) — same names/signatures, **lazy imports**:
  ```python
  def append_filediff(self, files):        # meldapp.py:505-517
      from meldq import filediff, filemerge   # inside the method
  ```
  On `ImportError` (module not yet ported) show `QMessageBox.warning(self, "Meld", f"This comparison type is not available yet: {exc}")` and return None. `append_filediff` keeps the len==4 → FileMerge branch and `seq.clear()` (`meldapp.py:511-512`; the can-undo wiring moved to `_on_current_tab_changed`). `append_dirdiff` keeps the `auto_compare` FIXME comment verbatim (`meldapp.py:500-502` — a known 1.4 wart, preserve behavior). `append_diff` ports the file/dir mixing heuristic verbatim (`meldapp.py:519-544`), with the error dialog `misc.run_dialog(_("Cannot compare a mixture of files and directories.\n"), ...)` becoming `QMessageBox.warning(self, "Meld", _("Cannot compare a mixture of files and directories.\n"))` — same msgid.
- `open_paths(paths, auto_compare=False)` (`meldapp.py:635-646`) verbatim; `_single_file_open(path)` (`meldapp.py:625-633`): lazy-import vcview, create doc, private `SchedulerPump`, `pump.set_scheduler(doc.scheduler)`, connect `doc.create_diff → self.append_diff`, `doc.run_diff([path])`, and on `idle_changed(True)` dispose pump and doc.

Tests — `tests/test_action_manager.py`: define `FakeDoc(MeldDoc)` whose widget is a `QLabel`, contributing `QAction("DocA-Edit")` to `"edit"`, a submenu menuAction to `"view"`, and one toolbar action.
1. `_append_page(fake_a); _append_page(fake_b)` → two tabs; current is B; Edit menu placeholder section contains exactly B's action; separators visible.
2. `tabs.setCurrentIndex(0)` → section now holds A's action, B's gone; B's action `shortcut()` no longer triggers (send key via `qtbot.keyClick(window, ...)`, assert not fired).
3. `try_remove_page(fake_a)` with `on_delete_event → CANCEL` leaves the tab; with OK removes it and emits `closed` (qtbot.waitSignal).
4. Undo sensitivity: fake doc's `undosequence.can_undo_changed.emit(True)` enables `action_undo` only while that doc is current.
5. `label_changed.emit("newname")` updates tab text and window title `"newname - Meld"`.
6. Close-all order: three tabs, each recording `on_delete_event` call order — asserts right-to-left (`meldapp.py:357-360` behavior) when `close()` is invoked.
7. `append_filediff(["a","b"])` with no `meldq.filediff` module present → warning box (monkeypatch `QMessageBox.warning` to record) and returns None.

TRAPS:
- `meldapp.py:307` `olddoc.disconnect(self.diff_handler)` — GTK handler-id disconnect; in PyQt store the slot and `signal.disconnect(slot)`, guarded by `try/except TypeError` (disconnecting a never-connected pyqtSignal raises).
- `QTabWidget.currentChanged` fires **during** `addTab` of the first tab and during `removeTab` of the current tab — `_doc_for_widget` must be populated before `addTab` and the handler must tolerate `index == -1` and unknown widgets (return early), or you get KeyErrors on startup/close.
- `meldapp.py:302,363` `get_data("pyobject")` — dead pattern; `tabs.widget(i)` returns the page and the dict resolves the doc. Never store back-pointers with `setProperty` (loses the Python identity).
- `meldapp.py:360` `reversed(self.notebook.get_children())` — keep the right-to-left semantics AND the `setCurrentIndex(i)` before each `try_remove_page` (docs may show save dialogs and expect to be visible).
- 1.4 kept background tabs' schedulers running (`meldapp.py:489`); the contract pump freezes them — dirdiff/vcview WPs must not assume scans progress while hidden (documented behavior change; the scan resumes on tab activation because `set_scheduler` checks `tasks_pending()`).
- Lazy factory imports are load-bearing for WP ordering: a top-level `from meldq import filediff` in `app.py` makes the shell untestable until Phase-4 lands.
- Duplicated shortcut = Qt silently fires `QAction.ambiguous` and **neither** action runs — the DocActionManager debug assert exists because this manifests as "menu item randomly stopped working".
- `insertActions` before a hidden separator still works, but forgetting to re-show boundary separators makes doc sections visually fuse with fixed items — set visibility from section emptiness every `set_doc`.

---

#### T3.8 — New-comparison dialog (commit: "app: new comparison dialog") — requires widgets WP

Old refs: `meld/meldapp.py:58-94`, `data/ui/meldapp.glade:98-491`.

Consumed widget API (`meldq/widgets/historycombo.py:FileHistoryCombo`): constructor `FileHistoryCombo(parent=None)`; `set_history_id(str)` (QSettings key `history/<id>`), `set_directory_entry(bool)`, `get_full_path() -> str`, `prepend_history(str)`, `focus_entry()`, and an `activated` submit signal (Enter in the line edit).

Create `meldq/ui/newcomparison.ui` (Qt Designer XML, loaded with `PyQt6.uic.loadUi`): QDialog `newdialog`, windowTitle `Choose Files` (set again from code as `_("Choose Files")` — `meldapp.glade:100`); QTabWidget `notebook` with three tabs; QDialogButtonBox `buttonbox` (Cancel + Ok, Ok default — `meldapp.glade:459-482`). Widget objectNames preserved from glade for mechanical porting: tab 1 (`_File Comparison`, `meldapp.glade:243`): `three_way_compare0` checkbox (`_Three Way Compare`, glade:128-135), rows `fileentry0` (label `Other`, glade:229, initially disabled — glade:177), `fileentry1` (`Original`, glade:212), `fileentry2` (`Mine`, glade:195); tab 2 (`_Directory Comparison`, glade:387): `three_way_compare1`, `direntry0/1/2` (labels Other/Original/Mine, glade:336-370, directory mode — `int1=1` at glade:286,303,321); tab 3 (`_Version Control Browser`, glade:440): `vcentry0` (label `Directory`, glade:425, directory mode). All seven entries are `FileHistoryCombo` via Designer **widget promotion** (promoted class `FileHistoryCombo`, header `meldq.widgets.historycombo`). Tab titles and labels set from code with `conf.mnemonic(_(msgid))` so the exact glade msgids hit the catalogs.

`class NewComparisonDialog(QDialog)` in `meldq/app.py`:

```python
def __init__(self, parent: MeldWindow):
    # uic.loadUi(conf.ui_file("newcomparison.ui"), self)
    # history ids: file entries "file_comparison", dir entries "dir_comparison", vc "vc_directory"
    #   (glade string1 values at meldapp.glade:146,284,408)
    # self.entrylists = ([fileentry0,1,2], [direntry0,1,2], [vcentry0])   # meldapp.py:62
    # self.diff_methods = (parent.append_filediff, parent.append_dirdiff, parent.append_vcview)
    # three_way_compare0/1.toggled -> _on_three_way_toggled  (meldapp.py:80-83:
    #   entrylists[page][0].setEnabled(checked); focus entry[0] if checked else entry[1])
    # initial: fileentry0/direntry0 enabled iff their checkbox is checked (meldapp.py:64-65)
    # each entry's activated -> _on_entry_activate (meldapp.py:71-78: focus next entry in its
    #   list, or the Ok button if last)
    # setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose); non-modal: caller uses .show()
def accept(self):   # meldapp.py:85-94
    # page = notebook.currentIndex()
    # paths = [e.get_full_path() or "" for e in self.entrylists[page]]
    # if page < 2 and not three_way[page].isChecked(): paths.pop(0)    # drop the "Other" slot
    # for p in paths: self.entrylists[page][0].prepend_history(p)
    # self.diff_methods[page](paths); super().accept()
```

`MeldWindow.on_menu_file_new_activate` replaces its T3.6 stub with `NewComparisonDialog(self).show()`.

Tests — `tests/test_newcomparison.py` (pytest-qt, monkeypatch the three `append_*` on a real MeldWindow to record calls):
1. Dialog loads; three tabs with the exact titles `&File Comparison` / `&Directory Comparison` / `&Version Control Browser`.
2. File tab: entry0 disabled until `three_way_compare0` checked; checking enables and focuses it.
3. Set texts `a`,`b` in entries 1,2 (2-way), accept → `append_filediff(["<a>","<b>"])` (two paths — the pop(0) branch).
4. 3-way: check, fill all three, accept → three paths, order `[other, original, mine]` (glade row order).
5. VC tab: accept → `append_vcview(["<dir>"])`.
6. Histories: after accept, a fresh `FileHistoryCombo` with id `file_comparison` sees the prepended entries (QSettings-backed).

TRAPS:
- Glade `Custom` widgets with `creation_function=meld.ui.historyentry.create_fileentry` (`meldapp.glade:143-187,405-417`; dispatcher `historyentry.py:431-436`) have NO .ui analogue — widget promotion is the replacement; do not try to port `gnomeglade`'s `set_custom_handler`.
- Entry index 0 is the **"Other"** (third) file — the visually FIRST row (glade packs rows top-to-bottom as fileentry0/1/2 = Other/Original/Mine, labels at glade:229/212/195). Getting the pop(0) slot wrong swaps merge ancestor/mine in every 3-way launch.
- `meldapp.py:83` `self.entrylists[page][not button.get_active()]` — py2 `not True == 0` indexing trick: focus entry **0** when checked, entry **1** when unchecked. Translate to an explicit index, don't index with a bool.
- 1.4's dialog is modeless (`show_all` at `meldapp.py:69`, destroyed in `on_response`); keep `.show()` + `WA_DeleteOnClose`, not `exec()` — tests and muscle memory rely on the main window staying interactive.
- `get_full_path() or ""` (`meldapp.py:88`): empty entries must yield `""`, not None — `append_filediff` asserts on list length, and a None path crashes later in doc code.
- QDialogButtonBox emits `accepted` for Ok — override `accept()` rather than connecting to `clicked` so Enter-in-last-entry → default button works (glade `has_default` on button_ok, glade:474).

---

#### T3.9 — `meldq/main.py`: entry point + CLI (commit: "main: entry point and CLI")

Old refs: `bin/meld:1-123`, `meld/meldapp.py:571-623` (parse_args), `:50` (version).

```python
"""Console entry point: [project.scripts] meldq = "meldq.main:main"."""
import argparse, sys
from meldq import __version__
from meldq import conf
from meldq.conf import _

def _missing_reqs(mod: str, exc: BaseException | None = None) -> "NoReturn":
    # fixed version of bin/meld:75-81: message uses str(exc) from the PARAMETER, not a leaked global
    ...print + sys.exit(1)

def parse_args(argv: list[str]) -> argparse.Namespace: ...
def main(argv: list[str] | None = None) -> int: ...
```

`parse_args` (pure, Qt-free, unit-testable) reproduces `meldapp.py:590-623`:
- prog `meldq`; `description=_("Meld is a file and directory comparison tool.")`; usage epilog built from the 5 usage lines with the exact msgids (`meldapp.py:591-595`): `_("Start with an empty window")`, `_("Start a version control comparison")`, `_("Start a 2- or 3-way file comparison")`, `_("Start a 2- or 3-way directory comparison")`, `_("Start a comparison between file and dir/file")`, plus `_("file")`/`_("dir")` placeholders.
- `--version` → `f"%(prog)s {__version__}"`.
- `-L/--label`, action `append`, default `[]`, help `_("Set label to use instead of file name")`.
- `-a/--auto-compare`, store_true, help `_("Automatically compare all differing files on startup")`.
- `-u/--unified`, `-c/--context`, `-e/--ed`, `-r/--recursive` — store_true, help `_("Ignored for compatibility")`.
- `--diff`, `action="append"`, `nargs="+"`, `dest="diff"`, `default=[]`, `metavar="PATH"`, help `_("Creates a diff tab for up to 3 supplied files or directories.")`. Post-parse validation: every group length in (1,2,3,4) else `parser.error(_("wrong number of arguments supplied to --diff"))` (`meldapp.py:585-588`).
- positional `paths`, `nargs="*"`; if `len > 4`: `parser.error(_("too many arguments (wanted 0-4, got %d)") % len(args.paths))` (`meldapp.py:615-616`).

`main()`:
1. `argv = list(sys.argv[1:] if argv is None else argv)`; extract `--profile` (pop it, remember flag — `bin/meld:48-53`).
2. `conf.init_i18n()` **before any meldq.app / meldq.util.prefs import** (import-time `_()` in prefs defaults).
3. Guarded Qt import: `try: from PyQt6.QtWidgets import QApplication ... except ImportError as exc: _missing_reqs("PyQt6 >= 6.6", exc)`.
4. `app = QApplication(sys.argv)`; `app.setApplicationName("Meld")`; `app.setApplicationVersion(__version__)`; `app.setOrganizationName("meldq")`; `app.setWindowIcon(QIcon(str(conf.icon_path("icon.png"))))`.
5. `args = parse_args(argv)`; construct `Preferences()` and `MeldWindow(prefs)`; `window.show()`.
6. `for files in args.diff: window.append_diff(files)`; `tab = window.open_paths(args.paths, args.auto_compare)`; `if tab: tab.set_labels(args.label)` (`meldapp.py:618-623`).
7. `rc = app.exec()` (wrapped in `cProfile.run` when profiling); `return rc`; module footer `if __name__ == "__main__": sys.exit(main())` so `python -m meldq.main` works. Also add `meldq/__main__.py` with the same two lines so `python -m meldq` works.

Tests — `tests/test_cli.py` (no QApplication needed):
1. `parse_args(["--diff","a","b","--diff","x","y","z"]).diff == [["a","b"],["x","y","z"]]`.
2. `parse_args(["--diff"])` and `["--diff","a","b","c","d","e"]` → SystemExit 2 with the exact error msgid text on stderr (capsys).
3. `parse_args(["p1","p2","p3","p4","p5"])` → SystemExit ("too many arguments (wanted 0-4, got 5)").
4. `-L` accumulates; ignored flags parse without effect; `parse_args([]).paths == []`.
5. `--version` → SystemExit 0, stdout `meldq 2.0.0a0`.
6. Regression for `bin/meld:77`: `_missing_reqs("PyQt6", ImportError("nope"))` raises SystemExit(1) and prints a message containing both "PyQt6" and "nope" (capsys) — the leaked-`e` NameError path is structurally impossible and pinned.

TRAPS:
- `bin/meld:77` — see above; the whole launcher error path is rewritten.
- `meldapp.py:571-588` — the optparse greedy callback stops at any token beginning `-` (`arg[:2]=="--" or (arg[:1]=="-" and len(arg)>1)`), i.e. it cannot take dash-prefixed filenames; argparse `nargs="+"` has the same option-lookalike boundary — behavior preserved, but note negative-number-looking paths were broken in 1.4 too (comment at `meldapp.py:577`). Do not "fix" by consuming past options.
- optparse allowed `--diff` groups of length 4 (`meldapp.py:585`) because filemerge takes 4 paths — keep (1,2,3,4), not (1,2,3) as the help text implies.
- `bin/meld:1` shebang + `#LIBDIR#` sys.path splice (`:60-61`) — do not reproduce; the console script and installed package make both obsolete; `conf.running_from_source()` covers the dev-tree case for locale only.
- `bin/meld:120-121` `import profile` — py3 prefers `cProfile`.
- i18n ordering: importing `meldq.app` (→ `meldq.util.prefs` → filter defaults with `_()`) before `conf.init_i18n()` ships English defaults for the session; step 2 before step 5 is load-bearing.
- QApplication must exist before `MeldWindow` and before any `QIcon` use; keep `Preferences` constructible without it (QSettings needs no QApplication) so tests stay cheap.


#### T3.10 — Preferences dialog (commit: "app: preferences dialog")

**Old refs:** `meld/preferences.py:31-233` (`ListWidget`, `PreferencesDialog`), `data/ui/preferences.glade` (832 lines — read it for tab layout, widget types, and every translatable string).

**Build** `meldq/prefsdialog.py` with `class PreferencesDialog(QDialog)`, launched from the shell's Settings→Preferences action (add the action in T3.6's menu table under "edit"). Static dialog → Qt Designer file `meldq/ui/preferences.ui` per D7, loaded with `uic.loadUi`. Reproduce the 1.4 tab set from preferences.glade: **Editor** (font: system-default checkbox + font picker storing `QFont.toString()`-compatible pref; tab width spinbox; spaces-instead-of-tabs; show line numbers; use syntax highlighting; wrap mode radio group), **Display** (color pickers for the `color_*_bg/fg` keys — `QPushButton` swatches opening `QColorDialog`, storing `#rrggbb`), **File Filters** (a `ListWidget`-equivalent: editable `QTreeView` + `QStandardItemModel` with columns Name/Active/Pattern over the `misc.ListItem` tab-separated pref format — port `meld/preferences.py:31-97` list-editing behavior: add/remove rows, checkbox toggles, live write-through to prefs on `itemChanged`), **Text Filters** (same widget class, regex patterns), **Encoding** (text_codecs entry), and the load-save behaviors of `meld/preferences.py:99-233`. Every label/tooltip string `_()`-wrapped with the exact glade wording.

**TRAPS:**
- `meld/preferences.py:262-282` — module-level `_()` calls in the defaults table run at import time; in the port, defaults live in `util/prefs.py` (T3.2) and must NOT be translated at module import (store untranslated, translate at display) or i18n init order becomes load-bearing.
- The 1.4 dialog writes through on every toggle (no OK/Cancel model) — preserve that (it is why `Preferences.changed(str)` exists); do not add an Apply button.
- Filter default strings contain regex escapes that are invalid string escapes in py3 (`preferences.py:262-282`) — use raw strings.

**Acceptance:** dialog opens from the menu; toggling a checkbox emits `Preferences.changed` and the value survives restart (`QSettings` written); filter list add/edit/delete round-trips; `msgfmt`-extracted strings match glade wording (spot-check 5 msgids against `po/uk.po`).

**Effort:** ~1.5 pd.

### Contracts consumed / provided

**Consumed** (must exist, from other WPs):
- `meldq.engine.task`: `FifoScheduler`/`LifoScheduler` — pure Python, `runnable_cb` attribute (callable | None, invoked as `runnable_cb(scheduler)` from `add_task`), `iteration()`, `tasks_pending()`, `add_task()`, `remove_task()`; generator tasks follow the yield-None protocol.
- `meldq.engine.undo.UndoSequence(QObject)`: `can_undo_changed(bool)`, `can_redo_changed(bool)` signals; `can_undo()`, `can_redo()`, `clear()`.
- `meldq.widgets.historycombo.FileHistoryCombo` (T3.8 only): `set_history_id`, `set_directory_entry`, `get_full_path`, `prepend_history`, `focus_entry`, `activated` signal; persists under `history/<id>`.
- `meldq.util.misc.shell_escape` (lazy, with fallback) and `meldq.vc.get_plugins_metadata` (lazy, with fallback) for the filters default.
- Editor WP: `DiffTextEdit.keyPressEvent` swallows Ctrl+Z/Ctrl+Shift+Z/Ctrl+Y (window-level undo routing).

**Provided** (every doc WP codes against these):
- `meldq.doc`: `MeldDoc(QObject)` with contract signals `label_changed(str)`, `status_changed(str)`, `create_diff(list)`, `closed()` plus extensions `file_changed(str)`, `next_diff_changed(bool,bool)`, `current_diff_changed()`; `CloseResponse` IntEnum; `Direction`; `RESULT_OK/RESULT_ERROR`; `doc_actions()/menu_contributions()/toolbar_contributions()` defaulting to empty; `self.widget`, `self.scheduler`, `self.undosequence`, `self.prefs`, `self.label_text`, `self.num_panes`; overridables `save/save_as/stop/next_diff/on_find_activate/.../on_delete_event/on_quit_event/on_focus_change/on_preference_changed(key)/on_container_switch_in_event/on_container_switch_out_event` (the last two are no-arg tab-activation hooks called by `_on_current_tab_changed`).
- `meldq.app.DocActionManager` placeholder semantics (menu keys `"file","edit","changes","view"`; submenus contributed as `QMenu.menuAction()`; actions parented to doc widget; shortcuts live only while current).
- `meldq.app.SchedulerPump` honoring the §2.5 `scheduler.paused` flag (docs set it around modal `exec()` from generator frames; `pause()/resume()` are pump-internal helpers); `MeldWindow.pump` exposed.
- `meldq.app.MeldWindow`: `append_filediff/append_dirdiff/append_vcview/append_diff/open_paths/try_remove_page/current_doc/set_doc_status/set_task_status`; window-quit right-to-left close protocol via `on_delete_event(appquit)`.
- `meldq.util.prefs.Preferences`: attribute access, `changed(str)` signal, `get_default`, `get_current_font() -> QFont`, `get_custom_editor_command`, full schema incl. hex `color_*` values (doc WPs feed them straight to `QColor`); QSettings key namespace `prefs/`, `history/`, `migration/`.
- `meldq.conf`: `_`, `ngettext`, `mnemonic`, `init_i18n`, `ui_file`, `icon_path`, `locale_dir`, `running_from_source`, `HELP_URL`, `BUG_REPORT_URL`.

### Deleted (do-not-port)

- `meldapp.py:187-260` — UIManager connect-proxy/menu-select statusbar-tooltip machinery: `QAction.setStatusTip` is native.
- `meldapp.py:103-116` — statusbar push/pop context stacks: last-message-wins labels.
- `meldapp.py:29-33, 204-205, 228-232` — gnomevfs DnD gating: `QMimeData.urls()` is unconditional.
- `meldapp.py:132-134` — default-icon-name + `pygobject_version` guard: `QApplication.setWindowIcon`.
- `meldapp.py:190-191` — `props.is_important`: no Qt equivalent, cosmetic.
- `meldapp.py:323` — notebook `menu-label` property: QTabWidget has no tab-list popup.
- `meldapp.py:486` + `meld/ui/notebooklabel.py` — custom close-button tab widget: `setTabsClosable(True)`.
- `data/ui/meldapp.glade:492-561` — `popup_new` menu + 5 handlers: dead code already in 1.4.0.
- `data/ui/meldapp-ui.xml` as a runtime artifact: its structure is compiled into `_build_menus()` tables.
- `melddoc.py:112-124` — UIManager merge/unmerge protocol: replaced by the doc-actions contract.
- `meld/util/prefs.py:65-143` (`GConfPreferences`) and the gconf desktop getters `preferences.py:291-325` (system monospace font → QFontDatabase; toolbar style → fixed; gnome editor command → QDesktopServices): gconf is dead; cross-process pref change notification is an accepted casualty (the 1.4 INI fallback never had it either).
- `meld/util/prefs.py:145-235` write path (whole-file INI rewrite per assignment): QSettings + read-only migration.
- `bin/meld:22-31` (Unbuffered stdout), `:34-38` (pychecker), `:41-46` (`--sm-*` args; Qt handles `-session`), `:56-61` (`meld.doap` sentinel + `#LIBDIR#`), `:87-111` (pygtk/glade gates, glade textdomain, icon-theme path).
- `meld/paths.py:19-24` `#TOKEN#` substitution contract (and `tools/install_paths` from this subsystem's perspective): `importlib.resources`.
- `meldapp.py:20,571-623` optparse: argparse.

### Acceptance criteria

1. `python -c "import meldq.conf, sys; sys.exit(1 if 'PyQt6' in sys.modules else 0)"` exits 0 (conf is Qt-free).
2. `python -W error -c "import meldq.util.prefs, meldq.doc, meldq.app, meldq.main"` exits 0 under Python 3.11 (no invalid-escape or deprecation warnings at import; app imports without any doc module present).
3. `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_conf.py tests/test_prefs.py tests/test_prefs_migration.py tests/test_doc.py tests/test_scheduler_pump.py tests/test_app_shell.py tests/test_action_manager.py tests/test_newcomparison.py tests/test_cli.py -q` — all green.
4. `meldq --version` prints `meldq 2.0.0a0` and exits 0; `meldq --diff` (empty group) and `meldq --diff a b c d e` (5-path group) exit 2 printing the 1.4 error string; `meldq --diff a` (1-path group) is accepted per T3.9's `(1,2,3,4)` validation.
5. Manual launch `meldq` (Linux/macOS): window titled "Meld" appears sized 600×600 on first run; menubar shows File/Edit/Changes/View/Help; toolbar shows New/Prev/Next/Stop; statusbar with progressbar; hovering "New..." shows "Start a new comparison" in the statusbar; Stop is greyed out; F11 toggles fullscreen; View→Statusbar hides the statusbar and the setting survives restart.
6. Manual: Ctrl+N opens the modeless "Choose Files" dialog with tabs File Comparison / Directory Comparison / Version Control Browser; the first file entry is disabled until "Three Way Compare" is checked; Cancel closes; with doc WPs absent, OK produces the "not available yet" warning instead of crashing.
7. Migration: with a `~/.meld/meldrc.ini` fixture containing `color_delete_bg = DarkSeaGreen1`, `custom_font = Monospace 12`, `edit_command_type = gnome`, first launch writes `prefs/color_delete_bg=#c1ffc1`, a `QFont.fromString`-parsable `custom_font`, `edit_command_type=internal`, and `migration/meldrc_done=true` into `~/.config/meldq/meldq.ini`; second launch does not re-run migration (verified by test 3's migration suite; manually by deleting the old ini between runs).
8. Debounce regression: resizing the window continuously for 2 s produces at most a handful of `prefs` writes, not one per resize event (pinned by `tests/test_app_shell.py` test 4).
9. Latent-bug regressions green: `tests/test_cli.py` test 6 (`bin/meld:77` leaked-except fix) and `tests/test_prefs.py` test 6 (`preferences.py:272/276` escape/msgid preservation).
10. Scheduler pump: `tests/test_scheduler_pump.py` asserts the timer is inactive when no tasks are pending (no idle busy-spin) and that a newly added task restarts pumping without user interaction.
11. i18n wiring: running with `LANG=fr_FR.UTF-8` and a compiled `fr` catalog under `build/locale` shows translated menu titles (manual spot check; automated msgmerge verification belongs to the packaging WP).

### Estimated effort

**11 person-days** (range 9–13): T3.1 conf 0.5 · T3.2 prefs store 1.0 · T3.3 migration 1.5 · T3.4 MeldDoc 0.5 · T3.5 pump 1.0 · T3.6 MeldWindow 2.5 · T3.7 DocActionManager + tab plumbing 2.0 · T3.8 new-comparison dialog 1.0 · T3.9 main/CLI 1.0. Consistent with the plan's shell estimate (10–18 pd) minus the editor-widget decision and preferences dialog, which are owned by other WPs.

---

## WP4 — Shared widgets (`meldq/widgets/`: historycombo, msgarea, treemodel, findbar)

### Goal

Build the four shared widgets in `meldq/widgets/` — `HistoryCombo`/`FileHistoryCombo` (replacing `meld/ui/historyentry.py`, 439 LOC), `MsgArea`+`MsgAreaController` (replacing `meld/ui/msgarea.py`), `DiffTreeModel` (replacing `meld/tree.py`'s `DiffTreeStore`, shared by dirdiff and vcview), and `FindBar` (replacing `meld/ui/findbar.py`) — plus the pure helpers they need in `meldq/util/misc.py`. These are the reusable building blocks that WP5 (dirdiff), WP6 (filediff), and WP7 (vcview) consume; roughly half of the old `meld/ui/` subsystem (`wraplabel.py`, `notebooklabel.py`, `gnomeglade.py`, most of `historyentry.py`) is deleted outright because Qt6 has the features built in.

### Dependencies

- **WP0** (package skeleton: `meldq/` package with `conf.py` exposing `_`, `meldq/util/misc.py` stub + its no-Qt-import purity test, `pyproject.toml` with PyQt6 dep, `tests/` with pytest + pytest-qt configured). WP4 cannot start before WP0.
- **No dependency** on WP2 (engine) or WP3 (shell) — WP4 can run in parallel with them. WP3's deferred T3.8 (new-comparison dialog) consumes `FileHistoryCombo` and runs immediately after this WP's T4.5 — land T4.4/T4.5 early.
- Consumed by: WP3 (app shell: `FileHistoryCombo` in new-comparison dialog), WP5 (dirdiff: `DiffTreeModel`, `FileHistoryCombo`), WP6 (filediff: `MsgArea*`, `FindBar`, `FileHistoryCombo`, utf-16 helpers), WP7 (vcview: `DiffTreeModel`, `FileHistoryCombo`, `HistoryCombo`).

### Old-code map

| Old file:lines | What it does | New home |
|---|---|---|
| `meld/ui/historyentry.py:32-33` | `MIN_ITEM_LEN=3`, default history length 10 | `meldq/widgets/historycombo.py` module constants |
| `meld/ui/historyentry.py:35-57` | ListStore dedup/clamp/escape helpers | policy re-implemented on QComboBox item API (helpers die) |
| `meld/ui/historyentry.py:60-180` | `HistoryEntry(gtk.ComboBoxEntry)`: gconf-persisted history + inline completion | `HistoryCombo(QComboBox)` |
| `meld/ui/historyentry.py:182-187` | gconf ImportError monkey-patching | DELETED (QSettings is unconditional) |
| `meld/ui/historyentry.py:191-202` | `_expand_filename` (pure) | `historycombo._expand_filename` verbatim |
| `meld/ui/historyentry.py:205-423` | `HistoryFileEntry(gtk.HBox, gtk.Editable)`: entry+Browse, file dialog, URI DnD | `FileHistoryCombo(QWidget)` |
| `meld/ui/historyentry.py:425-429` | gnomevfs ImportError monkey-patching | DELETED (`QUrl.toLocalFile`) |
| `meld/ui/historyentry.py:431-438` | glade `create_fileentry`/`create_entry` factories | DELETED (direct construction in consumer WPs) |
| `meld/ui/msgarea.py:30-217` | `MsgArea(gtk.HBox)`: banner w/ icon, labels, response buttons | `meldq/widgets/msgarea.py` `MsgArea(QFrame)` |
| `meld/ui/msgarea.py:52-114` | expose-event paint + tooltip-style-stealing hack | DELETED (QPalette ToolTip roles) |
| `meld/ui/msgarea.py:219-247` | `MsgAreaController(gtk.HBox)` one-slot banner host | `msgarea.MsgAreaController(QWidget)` |
| `meld/ui/msgarea.py:249-250` | glade `msgarea_mgr_create` factory | DELETED |
| `meld/tree.py:23` | `COL_PATH/STATE/TEXT/ICON` interleaved column scheme | DELETED (Qt item roles) |
| `meld/tree.py:25-28` (values defined `meld/vc/_vc.py:33-36`) | `STATE_IGNORED..STATE_MAX = range(12)` | `meldq/widgets/treemodel.py` module constants (canonical for UI layer) |
| `meld/tree.py:30-38` | 8 state pixbufs loaded at import time | lazy `_state_icons()` cache in `treemodel.py`; PNGs copied to `meldq/resources/icons/` |
| `meld/tree.py:40-118` | `DiffTreeStore(gtk.TreeStore)`: add/set/get/value_path helpers | `treemodel.DiffTreeModel(QStandardItemModel)` |
| `meld/tree.py:48-76` | Pango markup `textstyle` + `pixstyle` tables | `TextStyle` dataclass table + icon table, served from `data()` |
| `meld/tree.py:120-159` | `inorder_search_down/up` generators (PEP 479 bug at 138/158) | `DiffTreeModel.inorder_search_down/up` over QModelIndex, fixed |
| `meld/ui/findbar.py:24-141` | `FindBar(gnomeglade.Component)`: find/replace over GtkTextBuffer | `meldq/widgets/findbar.py` `FindBar(QWidget)` |
| `meld/ui/findbar.py:143-144` | glade `findbar_create` factory | DELETED |
| `data/ui/findbar.glade` | findbar layout + widget ids + labels | code-built QGridLayout, same objectNames, labels via `_()` with identical msgids |
| `meld/ui/wraplabel.py` (all 68 LOC) | wrap-to-allocation GtkLabel | DELETED |
| `meld/ui/notebooklabel.py` (all 96 LOC) | closable/ellipsized notebook tab label | DELETED (QTabBar built-ins; WP3 handles middle-click close) |
| `meld/ui/gnomeglade.py` (all 130 LOC) | glade load/autoconnect/`load_pixbuf` foundation | DELETED (`load_pixbuf` → inline `QPixmap.scaledToWidth`) |

### Tasks

---

**T4.1 — Pure helpers in `meldq/util/misc.py` (mnemonics + UTF-16 offsets)**

Old refs: GTK mnemonic labels throughout glade (`data/ui/findbar.glade:25,36,64,75,115,143,178,192,207`), `historyentry.py:248` `_("_Browse...")`, `filediff.py:720` `_("Hi_de")`; the char-offset arithmetic in `findbar.py:122-135` that becomes offset-unit-sensitive under Qt.

Build (append to `meldq/util/misc.py`; create the file if WP2 left it absent — it must import NO Qt module, that is enforced by test):

```python
def gtk_mnemonic_to_qt(label: str) -> str:
    """'_Match Case' -> '&Match Case'. Escape literal '&' first, convert
    only the FIRST underscore (GTK mnemonic marker) to '&'."""
    return label.replace("&", "&&").replace("_", "&", 1)

def char_to_utf16_offset(text: str, char_offset: int) -> int:
    """Python-str codepoint offset -> QTextDocument UTF-16 code-unit offset."""
    return char_offset + sum(1 for c in text[:char_offset] if ord(c) > 0xFFFF)

def utf16_to_char_offset(text: str, utf16_offset: int) -> int:
    """Inverse of char_to_utf16_offset (walk codepoints, count 2 for astral)."""
```

Rationale for the offset pair: Python `re` runs over `QPlainTextEdit.toPlainText()` (codepoint-indexed `str`), but `QTextCursor.setPosition()` takes UTF-16 code units — they diverge as soon as the document contains an astral-plane character (emoji). WP6's inline-highlight code needs the same conversion; this is the shared home.

Tests in `tests/test_util_misc.py`:
- `test_mnemonic_conversion`: `gtk_mnemonic_to_qt("_Match Case") == "&Match Case"`, `gtk_mnemonic_to_qt("Who_le word") == "Who&le word"`, `gtk_mnemonic_to_qt("A & B_x") == "A && B&x"`.
- `test_utf16_offsets_roundtrip`: for `text = "ab\U0001F600cd"` assert `char_to_utf16_offset(text, 3) == 4`, `utf16_to_char_offset(text, 4) == 3`, and roundtrip identity for every valid offset.
- `test_misc_imports_no_qt`: `import sys, meldq.util.misc; assert not any(m.split('.')[0] == 'PyQt6' for m in sys.modules)` (run in a subprocess so other tests don't pollute `sys.modules`).

TRAPS:
- The i18n rule (D8) requires msgids to keep the GTK underscore form (the 34 `po/` catalogs contain `_Browse...`, `_Match Case`, …). Therefore ALWAYS call `_()` on the underscored string first and `gtk_mnemonic_to_qt` on the *translated result*: `gtk_mnemonic_to_qt(_("_Browse..."))`. Converting before translation orphans every catalog entry silently.
- Do not import Qt in `util/misc.py` — WP0's purity test fails the whole suite if you do.

---

**T4.2 — `meldq/widgets/treemodel.py`: STATE constants, style tables, `DiffTreeModel` core**

Old refs: `meld/tree.py:23` (COL constants), `meld/tree.py:25-28` + `meld/vc/_vc.py:33-36` (STATE constants), `tree.py:30-38` (pixbuf loading via `gnomeglade.load_pixbuf`, `gnomeglade.py:120-129` — scaled to *width* with aspect preserved), `tree.py:40-118` (`DiffTreeStore`), consumers `dirdiff.py:348,374,395,403,457,497,503,524,548-552,581,617,648,707,784,812-827,876-901,995-1034` and `vcview.py:87-92,168-176,285-288,304-305,326,340,346,375,417,560-578,588-605,642-644`.

Build:

1. Copy icons: `cp data/icons/tree-file-changed.png data/icons/tree-file-missing.png data/icons/tree-file-new.png data/icons/tree-file-newer.png data/icons/tree-file-normal.png data/icons/tree-folder-changed.png data/icons/tree-folder-missing.png data/icons/tree-folder-new.png data/icons/tree-folder-normal.png meldq/resources/icons/` (9 files; `tree-file-newer.png` is the emblem WP5 composites — ship it now so WP5 has no data dependency). Verify WP0's `pyproject.toml` includes `meldq/resources/**` as package data; add the include if missing.

2. Module constants (canonical for the UI layer; the vc WP must import these or keep values identical — they are frozen at `range(12)`):
```python
STATE_IGNORED, STATE_NONE, STATE_NORMAL, STATE_NOCHANGE, \
STATE_ERROR, STATE_EMPTY, STATE_NEW, \
STATE_MODIFIED, STATE_CONFLICT, STATE_REMOVED, \
STATE_MISSING, STATE_MAX = range(12)

ROLE_PATH  = Qt.ItemDataRole.UserRole + 1   # str | None
ROLE_STATE = Qt.ItemDataRole.UserRole + 2   # int STATE_*
ROLE_ISDIR = Qt.ItemDataRole.UserRole + 3   # bool
```

3. Style table replacing Pango markup (`tree.py:49-61`, transcribe colors exactly):
```python
@dataclass(frozen=True)
class TextStyle:
    fg: str | None = None; bg: str | None = None
    bold: bool = False; italic: bool = False; strikethrough: bool = False

DEFAULT_TEXT_STYLES = [
    TextStyle(fg="#888888"),                                  # IGNORED
    TextStyle(fg="#888888"),                                  # NONE
    TextStyle(fg="black"),                                    # NORMAL
    TextStyle(fg="black", italic=True),                       # NOCHANGE
    TextStyle(fg="#ff0000", bg="yellow", bold=True),          # ERROR
    TextStyle(fg="#999999", italic=True),                     # EMPTY
    TextStyle(fg="#008800", bold=True),                       # NEW
    TextStyle(fg="#880000", bold=True),                       # MODIFIED
    TextStyle(fg="#ff0000", bg="#ffeeee", bold=True),         # CONFLICT
    TextStyle(fg="#880000", bold=True, strikethrough=True),   # REMOVED
    TextStyle(fg="#888888", strikethrough=True),              # MISSING
]
assert len(DEFAULT_TEXT_STYLES) == STATE_MAX
```
`DiffTreeModel.__init__` copies this into `self.text_styles = list(DEFAULT_TEXT_STYLES)` — an *instance* attribute, because vcview overrides one entry per instance (`vcview.py:92` sets MISSING to `fg="#000088", bold, strikethrough`).

4. Lazy icon cache (module function, NOT import-time — `tree.py:30-38` loads at import, Qt cannot):
```python
_icon_cache: list[tuple[QIcon | None, QIcon | None]] | None = None
def state_icons() -> list[tuple[QIcon | None, QIcon | None]]:
```
On first call, load each PNG via `importlib.resources.files("meldq") / "resources" / "icons"` into `QPixmap(str(path)).scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)` — width 14 for `tree-file-*`, 20 for `tree-folder-*` (matches `tree.py:30-34` / `gnomeglade.py:126-128` width-based scaling). Table per `tree.py:63-76`: `(file, folder)` pairs; IGNORED/NONE/NORMAL/NOCHANGE → normal; ERROR/EMPTY → `(None, None)`; NEW → new; MODIFIED/CONFLICT/REMOVED → changed; MISSING → missing.

5. The model:
```python
class DiffTreeModel(QStandardItemModel):
    def __init__(self, ntree: int = 3, extra_cols: int = 0, parent: QObject | None = None):
        # columnCount = ntree + extra_cols; extra columns are plain
        # DisplayRole text columns for vcview (Location/Status/Rev/Tag/Options,
        # vcview.py:87,172-178); pane columns are 0..ntree-1.
    def add_entries(self, parent: QModelIndex | None, names: Sequence[str | None]) -> QModelIndex
    def add_empty(self, parent: QModelIndex | None, text: str = "empty folder") -> QModelIndex
    def add_error(self, parent: QModelIndex | None, msg: str, pane: int) -> None
    def value_path(self, index: QModelIndex, pane: int) -> str | None
    def value_paths(self, index: QModelIndex) -> list[str | None]
    def set_state(self, index: QModelIndex, pane: int, state: int, isdir: bool = False) -> None
    def get_state(self, index: QModelIndex, pane: int) -> int
    def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```
Semantics (spec is `tree.py:78-118`):
- All helpers accept an index in ANY column of the row and use `index.siblingAtColumn(pane)` internally; `add_*` return the column-0 index of the new row.
- `add_entries` appends a row of `ntree + extra_cols` `QStandardItem`s under `parent` (invisible root if `parent` is None/invalid) and sets `ROLE_PATH` per pane item from `names` (`tree.py:78-82`). Text/state are set later via `set_state`, exactly like the old flow.
- `add_empty`: every pane gets `ROLE_STATE = STATE_EMPTY`, `ROLE_PATH = None`, DisplayRole = `text` (fixes the `tree.py:88` quirk that stored the *pixstyle tuple* into COL_PATH — new code must never store non-`str|None` in ROLE_PATH). Default text stays the untranslated literal `"empty folder"` (`tree.py:84` has no `_()`; the catalogs have no such msgid — do not "helpfully" translate it).
- `add_error`: every pane `ROLE_STATE = STATE_ERROR`; only column `pane` gets DisplayRole = `msg` (`tree.py:92-97`; the old per-pane icon write at :96 is moot — ERROR has no icon).
- `set_state(index, pane, state, isdir)`: write `ROLE_STATE`, `ROLE_ISDIR`; recompute DisplayRole = `os.path.basename(path)` from `ROLE_PATH` (`tree.py:107-113`) — if `ROLE_PATH` is None, leave DisplayRole untouched.
- `data()` override — this is where markup dies. For pane columns (col < ntree) with a non-None `ROLE_STATE`:
  - `ForegroundRole` → `QBrush(QColor(style.fg))` when fg set
  - `BackgroundRole` → `QBrush(QColor(style.bg))` when bg set
  - `FontRole` → `QFont()` with `setBold/setItalic/setStrikeOut` per style
  - `DecorationRole` → `state_icons()[state][1 if isdir else 0]` (may be None)
  - everything else → `super().data(index, role)`.
  Store PLAIN text in DisplayRole — `gobject.markup_escape_text` (`tree.py:89,97,108`) is deleted, nothing is escaped, no HTML delegate exists.

Tests in `tests/test_treemodel.py` (pytest-qt, `QT_QPA_PLATFORM=offscreen`):
- `test_state_constants_verbatim`: assert the 12-tuple ordering matches `meld/vc/_vc.py:33-36` (hardcode expected ints in the test).
- `test_add_entries_and_paths`: 3-pane model, `add_entries(None, ["/a/x", None, "/c/x"])`; `value_paths` returns exactly that list.
- `test_set_state_styles`: after `set_state(idx, 1, STATE_MODIFIED, isdir=False)`: `get_state(idx,1) == STATE_MODIFIED`; `data(sib1, ForegroundRole).color().name() == "#880000"`; `data(sib1, FontRole).bold() is True`; DisplayRole == basename; DecorationRole is a non-null QIcon; for `STATE_ERROR` DecorationRole is None.
- `test_add_empty_path_is_none`: regression for `tree.py:88` — `value_path` of an empty row is `None`, not a tuple.
- `test_instance_style_override`: mutate `model.text_styles[STATE_MISSING]`, verify only that instance's ForegroundRole changes (vcview requirement).

TRAPS:
- `tree.py:30-38` loads pixbufs at module import time. `QPixmap` before `QGuiApplication` exists produces null pixmaps and console warnings — the icon cache must be lazy and only invoked from `data()`/tests that have a running app (pytest-qt's `qapp` fixture).
- `tree.py:42-43` uses `type("")`/`type(pixbuf_file)` as TreeStore column-type tokens — a GTK-ism with no Qt analog; roles are dynamically typed, do not port any type-declaration machinery.
- `tree.py:106` `isdir=0` uses bool-as-int tuple indexing — new signature takes `bool`; keep an explicit `1 if isdir else 0` at the icon lookup (a raw `pixstyle[state][isdir]` transliteration with a bool works but hides intent).
- Porting `textstyle` as HTML strings into an HTML-rendering delegate is explicitly forbidden (contract + D5): it regresses selection highlight, eliding, and row heights. Role-based styling only.
- `gobject.markup_escape_text` deletions must be TOTAL — if any consumer WP later escapes text before `DisplayRole`, filenames render as `&amp;`-garbage. Store raw strings.
- vcview subclasses the store and re-runs `__init__` with extra columns (`vcview.py:89-92`, `dirdiff.py:111-118` adds an emblem column block) — the `extra_cols` ctor arg covers vcview; dirdiff's emblem column DIES (WP5 composites `tree-file-newer.png` onto the base icon and serves it via DecorationRole), so do not add an emblem column here.

---

**T4.3 — `DiffTreeModel` row addressing + inorder traversal (PEP 479 fix)**

Old refs: `tree.py:120-139` (`inorder_search_down`), `tree.py:141-159` (`inorder_search_up`), GTK path-tuple arithmetic `tree.py:143-145`; consumers `dirdiff.py:1030-1038`, `vcview.py:642-644`.

Build — add to `DiffTreeModel`:
```python
def rowpath(self, index: QModelIndex) -> tuple[int, ...]
    # () for invalid/root; walk index.parent() chain collecting .row()
def index_for_rowpath(self, path: tuple[int, ...]) -> QModelIndex
    # fold: idx = self.index(r, 0, idx); returns invalid index if any step invalid
def inorder_search_down(self, it: QModelIndex) -> Iterator[QModelIndex]
def inorder_search_up(self, it: QModelIndex) -> Iterator[QModelIndex]
```
Traversal is a line-for-line port of the `tree.py` algorithms over QModelIndex: child = `self.index(0, 0, it)`, next-sibling = `self.index(it.row()+1, 0, it.parent())`, parent = `it.parent()`, last-descendant descent via `self.rowCount(it)` and `self.index(nc-1, 0, it)`; validity via `.isValid()`. All yielded indexes are column 0. **Both `raise StopIteration()` statements (`tree.py:138` and `tree.py:158`) become plain `return`** — under PEP 479 (py3.7+) the raise form escapes the generator as `RuntimeError`, crashing next-diff navigation exactly at the first/last row.

Document (docstring) the mutation rule for consumers: indexes yielded by the generators and tuples from `rowpath` are only stable while the model is unmodified; any consumer mutating rows mid-iteration must convert to `QPersistentModelIndex` first (WP5's copy/delete paths).

Tests in `tests/test_treemodel.py`:
- Build fixture tree: top-level `A(A0, A1(A1a)), B, C(C0)`.
- `test_search_down_terminates`: `[rowpath(i) for i in model.inorder_search_down(idx_A)] == [(0,0),(0,1),(0,1,0),(1,),(2,),(2,0)]` — i.e. A0, A1, A1a, B, C, C0, then clean termination (this is the PEP 479 regression: the old code would raise RuntimeError instead of ending).
- `test_search_up_terminates`: from C0 → `[C, B, A1a, A1, A0, A]` as rowpaths `[(2,),(1,),(0,1,0),(0,1),(0,0),(0,)]`, clean termination.
- `test_rowpath_roundtrip`: `index_for_rowpath(rowpath(i)) == i` for every index in the fixture; `index_for_rowpath((9,9))` returns an invalid index.

TRAPS:
- `tree.py:138/158` `raise StopIteration()` — THE trap this task exists for; a mechanical 2to3 pass does not touch it and the failure only manifests when navigation walks off either end of the tree.
- `tree.py:144` `if path[-1]:` means "previous sibling exists" — port as `if it.row() > 0:`, not a truthiness check on a tuple.
- QModelIndex vs iter lifetime: GTK iters were re-fetched from stored tuples after edits (`dirdiff.py:504-515`); plain QModelIndex goes stale on row removal. The helpers must not cache indexes internally; statelessness is the contract.
- `sibling()` on a top-level index: prefer `self.index(row+1, 0, it.parent())` uniformly — `it.parent()` is the invalid root index for top-level rows and `QStandardItemModel.index` handles that; mixing `sibling()` and `index()` idioms invites off-by-one bugs at the root level.

---

**T4.4 — `meldq/widgets/historycombo.py`: `HistoryCombo`**

Old refs: `historyentry.py:32-33` (constants), `:35-52` (dedup/clamp), `:60-180` (`HistoryEntry`), `:94-106` (insert policy), `:118-128` (load), `:130-133` (clear), `:135-143` (length), `:145-163` (completion); consumers `vcview.py:81` (`prepend_text`), `vcview.py:85` (`child.get_text()` → `currentText()`), glade history ids listed below.

Build:
```python
MIN_ITEM_LEN = 3                        # historyentry.py:32
DEFAULT_HISTORY_LENGTH = 10             # historyentry.py:33

class HistoryCombo(QComboBox):
    def __init__(self, history_id: str | None = None,
                 settings: QSettings | None = None,
                 parent: QWidget | None = None):
        # setEditable(True); setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # completer().setCompletionMode(QCompleter.CompletionMode.InlineCompletion)
        # completer().setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)
        # self._settings = settings or QSettings()
        # self._history_id = history_id; self._history_length = DEFAULT_HISTORY_LENGTH
        # self._load_history()
    def prepend_text(self, text: str) -> None      # historyentry.py:108-111
    def set_history_length(self, n: int) -> None   # :135-140 (ignore n <= 0)
    def get_history_length(self) -> int
    def clear_history(self) -> None                # :130-133 (clear items + save)
    def set_history_id(self, history_id: str) -> None  # re-key + _load_history(); Designer-promotion support (T3.8/T7.12 construct with the default ctor)
    def _settings_key(self) -> str | None          # f"history/{self._history_id}" or None
    def _save_history(self) -> None
    def _load_history(self) -> None
```
Insert policy, ported exactly from `historyentry.py:94-106`: reject `len(text) <= MIN_ITEM_LEN` (strictly-greater-than-3 rule, `:95`); if an identical item exists remove it (dedup, `:99` via `findText(text, Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchCaseSensitive)` + `removeItem`); otherwise trim the item list to `history_length - 1` from the bottom (`:100`, so the insert lands at exactly `history_length`); `insertItem(0, text)`; `_save_history()`. `prepend_text` ignores empty text (`:108-110`). `_load_history` clears items and loads up to `history_length` entries (deliberate normalization of the `:127` off-by-one that loaded only `length-1`; document in docstring). Persist as a string list under key `history/<history_id>`; `history_id=None` disables persistence entirely (`:80-85,89,120` behavior). Reading must normalize QSettings' polymorphic return:
```python
def _as_str_list(value) -> list[str]:
    if value is None: return []
    if isinstance(value, str): return [value] if value else []
    return [str(v) for v in value]
```
Which 1.4 behaviors survive: prepend history w/ dedup+clamp+min-length, history-length get/set, inline completion, clear, persistence under stable per-id keys. Which die: gconf storage and its ImportError monkey-patching (`:182-187`), `set_escape_func` (`:171-180`, zero callers), `append_text` (`:113-116`, zero callers — grep-verified), `get_entry/self.child` indirection (`:155-169`, Qt exposes `lineEdit()`), EntryCompletion minimum-key-length 3 (`:152`, no QCompleter equivalent — accepted deviation), old gconf-stored user history (not migrated here; the prefs/D9 WP owns any one-time import).

Stable settings keys (documented in the module docstring for consumer WPs): `history/file_comparison`, `history/dir_comparison`, `history/vc_directory` (meldapp.glade:145-179, 283-321, 407-410), `history/direntry` (dirdiff.glade:114-150, vcview.glade:36-38), `history/fileentry` (filediff.glade:23-52), `history/previousentry` (vcview.glade:454-455).

Tests in `tests/test_historycombo.py` (inject `QSettings(str(tmp_path/"h.ini"), QSettings.Format.IniFormat)`):
- `test_min_item_len`: `prepend_text("abc")` (len 3) stores nothing; `"abcd"` stores.
- `test_dedup_moves_to_top`: prepend a, b, a → items `["aaaa","bbbb"]`-style order with the duplicate moved to index 0, count unchanged.
- `test_clamp_at_history_length`: prepend 12 distinct items → `count() == 10`, newest first.
- `test_persistence_roundtrip`: prepend items, create a NEW `HistoryCombo` with a fresh `QSettings` on the same file → identical item list/order.
- `test_single_item_roundtrip`: exactly one stored item survives a reload as a 1-element list (QSettings str-vs-list normalization regression).
- `test_no_history_id_no_write`: `history_id=None` writes no keys.

TRAPS:
- `historyentry.py:95` is `<=` — "must be LONGER than 3 chars". Porting as `<` silently admits 3-char paths and diverges from saved-history parity.
- `historyentry.py:100`: the clamp happens ONLY when no duplicate was removed, and clamps to `length-1` BEFORE the insert. Reordering these operations changes the maximum size by one.
- QSettings INI backend returns a bare `str` for single-element lists and `None` for missing keys — without `_as_str_list` the combo silently loads one character... per item or crashes on iteration. This is the QSettings equivalent of the py2 bytes/str trap.
- An editable QComboBox default-inserts the entry text on Enter (`InsertPolicy.InsertAtBottom`) — without `NoInsert`, every Enter press pollutes the history model bypassing the min-length/dedup policy.
- `insertItem(0, ...)` shifts `currentIndex` and can rewrite the line-edit text mid-typing. Save `lineEdit().text()` before mutating items and restore it after (the old ListStore never touched the entry).
- `QComboBox.findText` default match flags are NOT plain string equality — pass `MatchFixedString | MatchCaseSensitive` explicitly, or dedup becomes case-insensitive (GTK `row[0] == text` at `:40` was exact).
- Do not name the history-clear method `clear()` — `QComboBox.clear()` already exists and overriding it changes base-class semantics for every caller.

---

**T4.5 — `meldq/widgets/historycombo.py`: `FileHistoryCombo`**

Old refs: `historyentry.py:191-202` (`_expand_filename`), `:205-260` (class, signals, layout, a11y), `:289-297,406-423` (DnD), `:299-331` (history/path API), `:333-404` (browse dialog); consumers `dirdiff.py:363-373`, `filediff.py:694-695,1010-1011,1103-1105`, `vcview.py:283-284,353-354,652`, `meldapp.py:61-92` (incl. `focus_entry` at `:78,83`, `set_sensitive` at `:64` → inherited `setEnabled`).

Build (same module as T4.4):
```python
def _expand_filename(filename: str, default_dir: str | None) -> str:
    # VERBATIM port of historyentry.py:191-202 (pure; no gobject calls)

class FileHistoryCombo(QWidget):
    activated = pyqtSignal()   # replaces the glade 'activate' autoconnect

    def __init__(self, history_id: str | None = None,
                 browse_dialog_title: str | None = None,
                 directory_entry: bool = False,
                 default_path: str = "~",
                 settings: QSettings | None = None,
                 parent: QWidget | None = None):
        # QHBoxLayout, margins 0, spacing 3 (historyentry.py:237)
        # self.combo = HistoryCombo(history_id, settings) — PUBLIC attribute
        # browse = QPushButton(gtk_mnemonic_to_qt(_("_Browse...")))
        # self.combo.lineEdit().returnPressed.connect(self.activated)
        # browse.clicked.connect(self._browse_clicked)
        # DnD: self.setAcceptDrops(True); self.combo.lineEdit().setAcceptDrops(False)
        # a11y: combo.setAccessibleName(_("Path"));
        #       combo.setAccessibleDescription(_("Path to file"));
        #       browse.setAccessibleDescription(_("Pop up a file selector to choose a file"))
    def get_full_path(self) -> str | None          # :320-328 minus filename_from_utf8
    def set_filename(self, filename: str) -> None  # :330-331 (text only, NO history write)
    def prepend_history(self, text: str) -> None   # :302-303 → combo.prepend_text
    def focus_entry(self) -> None                  # :305-306 → combo.lineEdit().setFocus()
    def set_default_path(self, path: str | None)   # :308-312 (abspath or None)
    def set_history_id(self, history_id: str)      # forwards to self.combo.set_history_id (promotion support)
    def set_directory_entry(self, is_dir: bool)    # fixed: writes THE attribute the
    def get_directory_entry(self) -> bool          #   browse handler reads (see TRAPS)
    def _browse_clicked(self) -> None
    def dragEnterEvent(self, event) / dropEvent(self, event)
```
`get_full_path`: empty text → `None`; else `_expand_filename(text, self._default_path)` (absolute passthrough / `~` expansion / join with default dir or cwd — semantics frozen by `:191-202`).
`_browse_clicked`: start location = `self.get_full_path() or os.path.expanduser(self._default_path or "~")` (collapses `__build_filename`, `:351-366`). Directory mode → `QFileDialog.getExistingDirectory(self, self._title or _("Select directory"), start)`; file mode → `QFileDialog.getOpenFileName(self, self._title or _("Select file"), start)[0]`. On a non-empty result: `set_filename(path)` then `self.activated.emit()` — the emit is load-bearing parity with `:341-343` (`entry.set_text` + `entry.activate()`): choosing a file must trigger the same handler as pressing Enter, or dirdiff/filediff never reload after Browse.
`dropEvent` (`:406-423`): first `url.toLocalFile()` that is non-empty among `event.mimeData().urls()` → `set_filename`, `event.acceptProposedAction()`, `self.activated.emit()` (parity with `:423`).

Which 1.4 behaviors survive: `prepend_history`, `get_full_path`, `set_filename` (text-only), activate-on-Enter, activate-after-Browse, activate-after-drop, `focus_entry`, default-path expansion, directory-vs-file chooser mode, accessible names/descriptions. Which die: gconf (T4.4), gnomevfs URI decoding (`:413,425-429` → `QUrl.toLocalFile`), the `gtk.Editable` interface registration + undeclared `'changed'` re-emission (`:205,242` — grep confirms NO consumer connects to it in 1.4; consumers needing text-change notification connect `combo.lineEdit().textChanged` directly), `browse_clicked` gsignal (`:207`, declared but never emitted), `__gproperties__`/`do_get_property`/`do_set_property` (`:211-287` → ctor kwargs + methods), the cached non-modal dialog + `window.raise_()` dance (`:369-373,390-404` → static modal QFileDialog), `gtk.FILE_CHOOSER_ACTION_SAVE` branch (`:385-386`, unreachable — `__filechooser_action` is always OPEN), ATK relation pair (`:259-260`), `append_history` (`:299-300`, zero callers).

Tests in `tests/test_historycombo.py`:
- `test_expand_filename`: absolute passthrough; `~x` expansion; relative joins default dir; relative joins cwd when default None (all four branches of `:191-202`).
- `test_get_full_path_empty_is_none`.
- `test_enter_emits_activated`: `qtbot.keyClick(combo.lineEdit(), Qt.Key.Key_Return)` + `qtbot.waitSignal(fhc.activated)`.
- `test_browse_dir_mode_regression`: monkeypatch `QFileDialog.getExistingDirectory`/`getOpenFileName` to record invocation; construct with `directory_entry=False`, call `set_directory_entry(True)`, click Browse → `getExistingDirectory` used and `activated` emitted (regression for the `:314-318` dead setter).
- `test_drop_local_file`: synthesize a `QDropEvent` with a `file://` QMimeData → text set, `activated` emitted.
- `test_set_filename_no_history`: `set_filename` leaves `combo.count()` unchanged.

TRAPS:
- `historyentry.py:314-318` LATENT BUG: `set_directory_entry` assigns `self.directory_entry` while the browse handler reads the name-mangled `self.__directory_entry` (`:375`) — the setter never worked in 1.4. Fix by design (one attribute) + the regression test above.
- `historyentry.py:324,356` `gobject.filename_from_utf8` and `:340` `unicode(filename, encoding)` are py2 encoding round-trips — DELETE, do not transliterate; py3 paths are `str` (use `os.fsdecode` only if raw bytes ever appear, they don't here).
- `historyentry.py:407` `selection_data.data.split()` treats DnD payload as a whitespace-separated byte-string of URIs — in py3/Qt this becomes `QMimeData.urls()`; any attempt to parse `mimeData().text()` instead re-introduces the bytes/str encoding lottery.
- `historyentry.py:291` `drag_dest_unset()` on the inner entry exists because the entry's own drop site would swallow drops. Qt equivalent: `lineEdit().setAcceptDrops(False)` — omit it and QLineEdit inserts the literal `file:///...` URL text before your `dropEvent` ever runs (silent double-handling).
- `pyqtSignal` must be a class attribute; creating it in `__init__` fails at runtime with a generic AttributeError far from the cause.
- Signal emission from a lambda captured in a loop is not an issue here, but connecting `returnPressed` to `self.activated` (signal-to-signal) is the correct idiom — do not wrap in a lambda that would keep the widget alive.
- Button label: `gtk_mnemonic_to_qt(_("_Browse..."))` — msgid keeps the underscore (T4.1 trap).

---

**T4.6 — `meldq/widgets/msgarea.py`: `MsgArea` + `MsgAreaController`**

Old refs: `msgarea.py:30-34` (signals), `:36-62` (construction), `:64-82` (response data + `__close`), `:84-114` (paint/style hacks), `:116-180` (buttons/response), `:182-217` (`set_text_and_icon`), `:219-247` (`MsgAreaController`), `:242` (mutable default); consumer API surface `filediff.py:700,717-725,843-864` (`clear`, `new_from_text_and_icon`, `add_stock_button_with_text`, `connect("response")`, `has_message`, `set_msg_id`/`get_msg_id`, post-hoc `button.props.label = ...` → `setText`).

Build:
```python
class ResponseId(enum.IntEnum):   # exact GTK values — filediff compares these ints
    NONE = -1; OK = -5; CANCEL = -6; CLOSE = -7; HELP = -11

_ICON_FALLBACKS: dict[str, QStyle.StandardPixmap] = {
    "dialog-information": QStyle.StandardPixmap.SP_MessageBoxInformation,
    "dialog-warning":     QStyle.StandardPixmap.SP_MessageBoxWarning,
    "dialog-error":       QStyle.StandardPixmap.SP_MessageBoxCritical,
    "window-close":       QStyle.StandardPixmap.SP_DialogCloseButton,
}
def _themed_icon(widget: QWidget, name: str) -> QIcon:
    # QIcon.fromTheme(name); if .isNull() → widget.style().standardIcon(fallback)

class MsgArea(QFrame):
    response = pyqtSignal(int)

    def __init__(self, buttons: Sequence[tuple[str, int]] | None = None,
                 parent: QWidget | None = None):
        # setAutoFillBackground(True); palette Window←ToolTipBase,
        # WindowText/Text←ToolTipText (replaces msgarea.py:52-114 wholesale);
        # setFrameShape(QFrame.Shape.StyledPanel)
        # QHBoxLayout margins 8 (:44), spacing 16 (:42); content slot stretch=1;
        # trailing QVBoxLayout action area spacing 4 (:46)
        # self._buttons: dict[int, QPushButton] = {}
    def add_button(self, text: str, respid: int) -> QPushButton
    def add_stock_button_with_text(self, text: str, icon_name: str, respid: int) -> QPushButton
    def set_text_and_icon(self, icon_name: str, primary: str,
                          secondary: str | None = None) -> None
    def set_response_sensitive(self, respid: int, sensitive: bool) -> None   # :155-160
    def set_default_response(self, respid: int) -> None                      # :162-167
    def button_for_response(self, respid: int) -> QPushButton | None         # fixes :71-76

class MsgAreaController(QWidget):
    def __init__(self, parent=None)                 # QHBoxLayout margins 0
    def has_message(self) -> bool                   # :226-227
    def get_msg_id(self): / def set_msg_id(self, msgid)   # :229-233
    def clear(self) -> None                         # :235-240 (removeWidget + deleteLater)
    def new_from_text_and_icon(self, icon_name: str, primary: str,
                               secondary: str | None = None,
                               buttons: Sequence[tuple[str, int]] | None = None) -> MsgArea
```
Details:
- `add_button` (`:142-148`): `QPushButton(gtk_mnemonic_to_qt(text))` if text contains a mnemonic (caller decides; the method takes the final display text), `setFocusPolicy(Qt.FocusPolicy.NoFocus)` (`:144` `set_focus_on_click(False)`), record `self._buttons[respid] = button`, connect `clicked` → `functools.partial(self.response.emit, respid)`, add to the action layout (HELP appends last, matching the `:132-135` pack_end intent).
- `add_stock_button_with_text` (`:172-180`): `add_button(text, respid)` then `button.setIcon(_themed_icon(self, icon_name))`.
- `set_text_and_icon` (`:182-217`): icon `QLabel` with `_themed_icon(...).pixmap(20, 20)` (GTK `ICON_SIZE_BUTTON` = 20px), centered; a `QVBoxLayout` (spacing 6, `:192`) of primary label `"<b>%s</b>" % html.escape(primary)` and optional secondary `"<small>%s</small>" % html.escape(secondary)`; both labels: `setTextFormat(Qt.TextFormat.RichText)`, `setWordWrap(True)` (replaces `WrapLabel` entirely), `setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)` (`:204,214` selectable), left-aligned.
- `set_default_response` → `button.setDefault(True)` (`:166` `grab_default`).
- `MsgAreaController.new_from_text_and_icon` (`:242-247`): `clear()` first; **`buttons: ... = None`, normalized with `buttons or ()`** — the `buttons=[]` mutable default at `:242` is one of the survey's named latent bugs.
- Animated show/hide (KMessageWidget-style `QPropertyAnimation` on `maximumHeight`) is OPTIONAL — implement plain `show()`; do not gate acceptance on animation.

Tests in `tests/test_msgarea.py`:
- `test_response_signal`: controller → `new_from_text_and_icon("dialog-information", "Files are identical")`; `add_stock_button_with_text(gtk_mnemonic_to_qt(_("Hi_de")), "window-close", ResponseId.CLOSE)`; `button.click()` inside `qtbot.waitSignal(area.response)` → payload `== -7`.
- `test_button_for_response_regression`: after adding CANCEL + CLOSE buttons, `button_for_response(ResponseId.CANCEL)` returns the right widget and `button_for_response(999)` returns None — the old `__find_button` (`msgarea.py:72`) raised `AttributeError: _MsgArea__actionarea` on ANY invocation; assert no exception.
- `test_controller_lifecycle`: `has_message()` False→True→False across `new_from_text_and_icon`/`clear`; `set_msg_id`/`get_msg_id` round-trip; `clear()` resets msg id to None (`:240`).
- `test_no_shared_buttons_default`: two `new_from_text_and_icon` calls without buttons → second MsgArea has zero buttons (mutable-default regression).
- `test_markup_escaped`: primary text `"a <b> & c"` → the label's `text()` contains `&lt;b&gt;` and `&amp;` (escaping regression for `:196,207` — the old code injected raw text into Pango markup and broke on filenames containing `<`/`&`).
- `test_response_sensitive`: `set_response_sensitive(ResponseId.CLOSE, False)` disables exactly that button; unknown respid is a silent no-op (`:155-160` loop semantics).

TRAPS:
- `msgarea.py:72` LATENT BUG (survey-listed): `self.__actionarea` vs `self.__action_area` — unreachable in 1.4 only because `__close` (`:78-82`) was never called. The dict-of-buttons design makes the bug structurally impossible; the regression test above pins it.
- `msgarea.py:242` mutable default argument `buttons=[]` (survey-listed) — any code path that ever appended to it would leak buttons across ALL future banners. Use `None`.
- `msgarea.py:52-114` (expose-event `paint_flat_box`, `set_app_paintable`, the popup-window-named-`gtk-tooltip` style theft with reentrancy guard): DO NOT PORT ANY OF IT. Qt exposes tooltip colors as first-class `QPalette.ColorRole.ToolTipBase/ToolTipText`. Porting the paint handler is the single biggest waste-of-effort risk in this WP.
- `msgarea.py:31-34` declares a `'close'` gsignal that is never emitted and `__close` is never invoked — do not port a `closed` signal "for completeness"; WP6's callers only use `response`.
- `:64-69` per-button `set_data('hotwire-msg-area-data')` → a plain dict; do NOT use `QObject.setProperty` (stringly-typed, survives nothing).
- Connecting `clicked` in a loop with `lambda: self.response.emit(respid)` captures `respid` by reference — late-binding gives every button the LAST respid. Use `functools.partial` (or a default-arg lambda) — this is the exact Qt analog of the old per-widget response data.
- Response ids must keep GTK's negative integer values (`ResponseId.CLOSE == -7`): filediff (WP6) connects handlers that receive and may compare the raw int.
- `QIcon.fromTheme` returns a null icon on macOS (no freedesktop theme) — the `_ICON_FALLBACKS` table is mandatory, not defensive garnish (D11).

---

**T4.7 — `meldq/widgets/findbar.py`: widget shell + visibility state machine**

Old refs: `findbar.py:24-29` (ctor: glade load, `orig_base_color` save at `:29`), `:31-54` (hide/start_find/start_find_next/start_replace), `:56-69` (button/entry handlers), `:96-97` (changed → reset tint); `data/ui/findbar.glade` widget ids (`find_label:113`, `find_entry:128`, `replace_label:141`, `replace_entry:158`, `replace_button:21`, `replace_all_button:32`, `find_previous_button:60`, `find_next_button:71`, `findbar_close:93`, `match_case:176`, `whole_word:189`, `regex:204`) and labels (`_Search for:115`, `Replace _With:143`, `_Replace:25`, `Replace _All:36`, `_Previous:64`, `_Next:75`, `_Match Case:178`, `Who_le word:192`, `Regular E_xpression:207`).

Build — code-built layout (findbar is NOT in the contract's static-dialog `.ui` list):
```python
class FindBar(QWidget):
    def __init__(self, parent: QWidget | None = None):
        self.text_edit: QPlainTextEdit | None = None
```
Widgets, with `setObjectName` matching the old glade ids exactly (grep-ability across the port): `find_label`/`replace_label` (`QLabel`, `setBuddy` to their entries — replaces glade `mnemonic_widget:117,145`), `find_entry`/`replace_entry` (`QLineEdit`), `find_next_button`/`find_previous_button`/`replace_button`/`replace_all_button` (`QPushButton`), `findbar_close` (`QToolButton` with `_themed_icon(self,"window-close")`), `match_case`/`whole_word`/`regex` (`QCheckBox`). All texts: `gtk_mnemonic_to_qt(_("<exact glade msgid>"))`. Layout: `QGridLayout` — row 0: `find_label | find_entry | find_previous_button | find_next_button | findbar_close`; row 1: `replace_label | replace_entry | replace_button | replace_all_button`; row 2 spanning: the three checkboxes in an HBox (`find_options` equivalent).

State machine (spec `findbar.py:31-54`):
- `hide(self)`: `self.text_edit = None; super().hide()` (`:31-33`).
- `start_find(self, text_edit)`: store target; hide the 4 replace widgets (`:37-40`); `show()`; `find_entry.setFocus()` + `find_entry.selectAll()`.
- `start_find_next(self, text_edit)`: store target; if `find_entry.text()`: `find_next_button.click()` else `start_find(text_edit)` (`:44-49`).
- `start_replace(self, text_edit)`: store target; show everything (`:51-54`); focus find entry.
- Connections: `findbar_close.clicked → self.hide` (`:56-57`); `find_entry.returnPressed → find_next_button.click` (`:59-60`); `replace_entry.returnPressed → replace_button.click` (`:62-63`); `find_entry.textChanged → self._clear_tint` (`:96-97`, implemented as `find_entry.setStyleSheet("")`).

WP6 boundary (explicit): WP4 delivers a self-sufficient widget operating on ANY `QPlainTextEdit` handed to `start_*`. WP6 owns: constructing/embedding the bar under the filediff panes, the Ctrl+F/Ctrl+H/F3 QActions that call `start_find/start_replace/start_find_next`, retargeting `findbar.text_edit` when pane focus changes (`filediff.py:376`), Escape-in-textview → `findbar.hide()` (`filediff.py:518`), and hiding on file reload (`filediff.py:624`). WP4's tests use a bare `QPlainTextEdit` — no FileDiff involvement.

TRAPS:
- `QWidget.hide()` is not virtual on the C++ side: our Python override runs only for Python-level calls. All 1.4 call sites are Python (`filediff.py:518,624` and the close button), so this is safe — but document it in the docstring so WP6 doesn't call `setVisible(False)` and skip the `text_edit = None` reset.
- `findbar.py:47,60,63` `button.activate()` — there is NO `QAbstractButton.activate()`; the equivalent is `.click()` (fires `clicked` respecting enabled state).
- `findbar.py:29` saves `get_style().base[0]` to restore later — do not port; toggling `setStyleSheet("#ffdddd")`/`setStyleSheet("")` needs no saved color. (Setting a QSS background wins over QPalette in both directions, which is exactly why it's the safe mechanism.)
- The old `show_all()` at `:53` vs `show()` at `:41` distinction is GTK-specific (recursive show); in Qt, child visibility follows the parent — re-showing previously-hidden replace widgets requires explicit `.show()` on each of the 4 widgets in `start_replace`.
- Checkbox/label msgids must be the exact glade strings incl. underscore position (`Who_le word`, `Regular E_xpression`) or all 34 catalogs miss them (D8).

---

**T4.8 — `FindBar` find/replace engine + tests**

Old refs: `findbar.py:71-82` (replace), `:84-94` (replace-all), `:102-141` (`_find_text`), `:110-111` (py2 decode), `:117` (flags idiom), `:118` (py2 except), `:121` (`backwards == False`), `:133-137` (selection placement), `:140-141` (no-match: collapse selection + tint).

Build:

`_find_text(self, start_offset: int = 1, backwards: bool = False, wrap: bool = True) -> bool` — pure-Python `re` search (keep the Python regex dialect; do NOT switch to `QTextDocument.find`/`QRegularExpression`, the filter regex dialect must stay consistent app-wide):
1. `text = self.text_edit.toPlainText()`; `insert_char = utf16_to_char_offset(text, self.text_edit.textCursor().position())` — the cursor `position()` is UTF-16 units; the regex works in codepoints (T4.1 helpers).
2. Pattern build (`:103-115`): `tofind = self.find_entry.text()`; if not `regex.isChecked()`: `re.escape(tofind)`; if `whole_word.isChecked()`: `r'\b' + tofind + r'\b'` (this order — escape first, wrap second); flags `re.M | (0 if match_case.isChecked() else re.I)` (rewrite of the `:117` and-or idiom).
3. `except re.error as e:` → `QMessageBox.critical(self, "Meld", _("Regular expression error\n'%s'") % e)` (msgid verbatim from `:119`) and return False.
4. Forward (`:121-124`): `match = pattern.search(text, insert_char + start_offset)`; if None and `wrap`: `pattern.search(text, 0)`. Backward (`:125-131`): last match of `pattern.finditer(text, 0, insert_char)`; if None and `wrap`: last match of `pattern.finditer(text, insert_char)`.
5. On match (`:132-138`): `start16 = char_to_utf16_offset(text, match.start())`, `end16 = char_to_utf16_offset(text, match.end())`; cursor = `textCursor()`; `setPosition(end16)`; `setPosition(start16, QTextCursor.MoveMode.KeepAnchor)`; `setTextCursor(cursor)`; `ensureCursorVisible()`; return True. **Anchor at END, position at START** — this reproduces GTK's insert-mark-at-match-start (`:134`), which the `insert_char + start_offset` arithmetic in step 1/4 depends on for find-next stepping.
6. On no match (`:140-141`): `cursor = textCursor(); cursor.setPosition(cursor.position())` (collapses any selection at the insert position, mirroring `place_cursor(get_insert)`); `setTextCursor(cursor)`; `find_entry.setStyleSheet("QLineEdit { background: #ffdddd; }")`; return False.

`_replace_clicked(self)` (spec `:71-82`, re-expressed per contract): capture `old = (c.selectionStart(), c.selectionEnd()) if c.hasSelection() else None` from `textCursor()`; `match = self._find_text(0)`; capture `new` the same way from the fresh `textCursor()`; **replace only if `match and old is not None and old == new`** — the `(selectionStart, selectionEnd)` tuple comparison replaces GTK's dual-mark `iter.equal` checks at `:77`. Then: `cursor = self.text_edit.textCursor(); cursor.beginEditBlock(); cursor.insertText(self.replace_entry.text()); self.text_edit.setTextCursor(cursor); self._find_text(0); cursor.endEditBlock()` — `insertText` on a cursor with a selection performs the delete+insert of `:79-80` in one step and leaves the cursor after the inserted text, exactly like GTK's `insert_at_cursor`.

`_replace_all_clicked(self)` (spec `:84-94`, REDESIGNED — see TRAPS): 
```
saved = self.text_edit.textCursor()          # QTextCursor auto-adjusts like the :86 mark
work = self.text_edit.textCursor(); work.movePosition(QTextCursor.MoveOperation.Start)
self.text_edit.setTextCursor(work)
work.beginEditBlock()                        # single undo step, replaces :87-91 user action
prev_end = -1
while self._find_text(0, wrap=False):
    cur = self.text_edit.textCursor()
    if cur.selectionEnd() == cur.selectionStart() and cur.selectionEnd() == prev_end:
        break                                # zero-length match, no progress
    cur.insertText(self.replace_entry.text())
    self.text_edit.setTextCursor(cur)
    prev_end = cur.position()
work.endEditBlock()
self.text_edit.setTextCursor(saved)          # :92-93 restore
self.text_edit.ensureCursorVisible()         # :94
```

Tests in `tests/test_findbar.py` (fixture: `FindBar` + bare `QPlainTextEdit` with known text, drive via `start_find`/`start_replace` + direct slot calls):
- `test_find_wraps`: cursor after last match, find-next selects the first match.
- `test_find_backwards`: `_find_text(backwards=True)` selects the previous match; wraps to the last.
- `test_whole_word`: pattern `word` does not match inside `words`.
- `test_regex_error_dialog`: monkeypatch `QMessageBox.critical` to record; enter `(` with regex checked → recorded once, no exception, returns False.
- `test_no_match_tints_entry`: styleSheet contains `#ffdddd`; typing in the entry clears it.
- `test_replace_only_if_selected`: with the cursor placed but nothing selected, replace performs a find (selection appears) but does NOT modify the document; a second replace (selection == match) replaces exactly once.
- `test_replace_all_single_undo`: text `"a b a b a"`, find `a`, replace `X` → `"X b X b X"`; ONE `edit.undo()` restores the original text (edit-block grouping regression; also validates the WP-undo contract, since one edit block == one `undoCommandAdded`).
- `test_replace_all_terminates_when_replacement_contains_pattern`: text `"aaa"`, find `a`, replace `aa` → result `"aaaaaa"` and the call RETURNS (guarded by a 5-second pytest timeout marker) — regression for the 1.4 infinite loop.
- `test_replace_all_zero_length_pattern_terminates`: regex `x*` on `"ab"` terminates.
- `test_astral_offsets`: text `"😀😀 target"`, find `target` → the SELECTED text (`textCursor().selectedText()`) equals `"target"` (fails without the UTF-16 conversion because each emoji shifts positions by one).

TRAPS:
- `findbar.py:110-111` `.decode("utf-8")` on entry/buffer text: in py3 this is `AttributeError: 'str' object has no attribute 'decode'` — DELETE both, do not "port" to `.encode().decode()`.
- `findbar.py:118` `except re.error, e` — py2 syntax, SyntaxError in py3.
- `findbar.py:117` `match_case and re.M or (re.M|re.I)` — the and-or ternary idiom; correct here by luck (re.M is truthy) but rewrite as a real conditional. Keep `re.M` in BOTH branches (it affects `^`/`$` in user regexes).
- Codepoint-vs-UTF-16 offsets: `match.start()` indexes the Python `str`; `QTextCursor.setPosition` counts UTF-16 units. Any document containing a non-BMP character silently shifts every subsequent selection by one unit per astral char — this is the port's premier silent breakage; the helpers from T4.1 are mandatory in BOTH directions (`:108` insert offset in, `:133-136` selection out).
- `findbar.py:77` `oldsel[0].equal(newsel[0])`: GTK compares two independent marks (insert + selection_bound); a naive port comparing `cursor.position()` only replaces on backwards-selected matches or misses the check entirely. The `(selectionStart(), selectionEnd())` tuple comparison is order-normalized (Qt returns min/max) and is the contract-mandated re-expression.
- `findbar.py:88` LATENT BUG (fixed by design here): replace-all calls `_find_text(0)` with `wrap=True` — if the replacement contains the pattern (`a`→`aa`) or the regex matches empty (`x*`), 1.4 loops forever while growing the buffer. The redesign (start from document start, `wrap=False`, zero-progress guard) preserves "replace every match in the document" (the observable 1.4 behavior for sane inputs) while terminating on the pathological ones. This deviation is intentional and covered by two regression tests.
- `findbar.py:86,92-93` saved left-gravity mark → a spare `QTextCursor` (cursors auto-adjust across edits exactly like marks); an `int` position does NOT auto-adjust — do not store one.
- Edit blocks are DOCUMENT-level state: `beginEditBlock` on cursor A groups edits made through cursor B into the same undo command. That's why the replace-all loop can set fresh cursors per iteration; but it also means an unbalanced `endEditBlock` (e.g. early `return` on exception) corrupts undo grouping for the whole document — use try/finally around the loop.
- `textview.scroll_to_mark(insert, 0.25)` (`:94,137`): Qt has no within-margin parameter; `ensureCursorVisible()` is the accepted equivalent (deviation noted, invisible to tests).
- `findbar.py:121` `backwards == False` — cosmetic py2-ism; write `not backwards`.

### Contracts consumed / provided

**Consumed:**
- `meldq.conf._` (WP0) — every user-visible string.
- WP0 test harness: pytest + pytest-qt (`qtbot`, `qapp`), `QT_QPA_PLATFORM=offscreen` in CI.
- `meldq/util/misc.py` purity rule (no Qt imports; WP0's enforcement test).
- Global rules: PyQt6 only, no threads, old code is the behavioral spec.

**Provided (frozen for WP3/WP5/WP6/WP7):**
- `meldq.widgets.treemodel`: `STATE_IGNORED..STATE_MAX` (= `range(12)`, canonical for the UI layer — the vc WP must import or match), `ROLE_PATH/ROLE_STATE/ROLE_ISDIR` (`UserRole+1/2/3`), `TextStyle`, `DEFAULT_TEXT_STYLES`, `state_icons()`, `DiffTreeModel(ntree=3, extra_cols=0)` with `add_entries/add_empty/add_error/value_path/value_paths/set_state/get_state/rowpath/index_for_rowpath/inorder_search_down/inorder_search_up` and role-computed Foreground/Background/Font/Decoration in `data()`. `self.text_styles` is per-instance and override-safe (vcview). Extra columns are plain DisplayRole text columns after the pane columns (vcview's Location/Status/Rev/Tag/Options).
- `meldq.widgets.historycombo`: `HistoryCombo(history_id, settings=None)` (`prepend_text`, `set_history_id`, `set_history_length/get_history_length`, `clear_history`, `currentText()` inherited), `FileHistoryCombo(history_id, browse_dialog_title=None, directory_entry=False, default_path="~", settings=None)` (`activated = pyqtSignal()`, `get_full_path`, `set_filename`, `prepend_history`, `focus_entry`, `set_default_path`, `set_history_id`, `set/get_directory_entry`, public `.combo`), `_expand_filename`. Stable QSettings keys `history/<id>` for ids: `file_comparison`, `dir_comparison`, `vc_directory`, `direntry`, `fileentry`, `previousentry`.
- `meldq.widgets.msgarea`: `ResponseId` IntEnum (GTK values), `MsgArea` (`response = pyqtSignal(int)`, `add_button`, `add_stock_button_with_text`, `set_text_and_icon`, `set_response_sensitive`, `set_default_response`, `button_for_response`), `MsgAreaController` (`has_message`, `get_msg_id/set_msg_id`, `clear`, `new_from_text_and_icon`), `_themed_icon` helper.
- `meldq.widgets.findbar`: `FindBar` (`text_edit` attr, `hide`, `start_find`, `start_find_next`, `start_replace`, `_find_text`) operating on any `QPlainTextEdit`. WP6 owns embedding, shortcuts, focus retargeting, Escape handling.
- `meldq.util.misc`: `gtk_mnemonic_to_qt`, `char_to_utf16_offset`, `utf16_to_char_offset` (WP6 reuses the offset pair for inline highlights).

### Deleted (do-not-port)

- `meld/ui/wraplabel.py` (entire file, 68 LOC) — `QLabel.setWordWrap(True)` IS this widget; its only consumer was msgarea.
- `meld/ui/notebooklabel.py` (entire file, 96 LOC) — `QTabWidget.setTabsClosable/tabCloseRequested`, `tabBar().setElideMode(Qt.ElideMiddle)`, `setTabIcon/setTabToolTip` are built in; the ~10-line middle-click-close QTabBar subclass belongs to WP3 (app shell), not here.
- `meld/ui/gnomeglade.py` (entire file, 130 LOC) — glade loading/autoconnect/`set_data("pyobject")`/`load_pixbuf`; new views are code-built, `load_pixbuf` collapses to `QPixmap(...).scaledToWidth(...)` inline.
- `historyentry.py:182-187, 425-429` — gconf/gnomevfs ImportError monkey-patching of name-mangled methods; both technologies are dead.
- `historyentry.py:35-57` — ListStore row helpers + `set_escape_func` cell-data hook (zero callers for the escape hook).
- `historyentry.py:113-116, 299-300` — `append_text`/`append_history`: zero call sites in 1.4 (grep-verified).
- `historyentry.py:205-209` — `browse_clicked` gsignal (declared, never emitted) and the `gtk.Editable` interface registration + `'changed'` re-emission (`:242`; zero consumers connect to it).
- `historyentry.py:211-287` — `__gproperties__`/`do_get_property`/`do_set_property`: ctor kwargs + plain methods replace GObject property plumbing.
- `historyentry.py:333-404` — FileChooserDialog construction, stock buttons, transient/modal dance, cached non-modal dialog + `raise_()`, `x-directory/normal` mime filter, the unreachable SAVE branch: one static `QFileDialog` call replaces ~70 lines.
- `historyentry.py:259-260` — ATK `RELATION_CONTROLLER_FOR/CONTROLLED_BY` pair (no practical PyQt6 API; names/descriptions kept).
- `msgarea.py:52-114` — `set_app_paintable`/expose-event `paint_flat_box`/`style-set` tooltip-window style theft: replaced by two QPalette role assignments.
- `msgarea.py:31-34 ('close'), 78-82 (__close)` — dead signal + unreachable method.
- `msgarea.py:249-250`, `findbar.py:143-144`, `historyentry.py:431-438` — glade `Custom` creation-function factories; consumer WPs construct widgets directly.
- `meld/tree.py:23` COL_* interleaved-column scheme + `column_index` (`:103-104`) — roles make columns-per-attribute obsolete.
- `meld/tree.py:48-61` Pango markup table + `gobject.markup_escape_text` calls (`:89,97,108`) — role-based styling, plain text in the model.
- `data/ui/findbar.glade` — layout rebuilt in code (not in the contract's static-`.ui` whitelist).
- gconf-stored user history content — not readable from Qt; any one-time migration is the prefs WP's (D9) concern, WP4 ships empty history.

### Acceptance criteria

All commands run from the repo root with the WP0 venv active; prefix GUI-touching commands with `QT_QPA_PLATFORM=offscreen`.

1. **Imports are clean and app-free**: `QT_QPA_PLATFORM=offscreen python -c "import meldq.widgets.treemodel, meldq.widgets.historycombo, meldq.widgets.msgarea, meldq.widgets.findbar; print('ok')"` prints `ok` — in particular `treemodel` must import without a `QApplication` (lazy icon cache; the old `tree.py:30-38` pattern would fail this).
2. **Purity guard**: `python -c "import sys, meldq.util.misc; assert not any(m.split('.')[0]=='PyQt6' for m in sys.modules); print('pure')"` prints `pure`.
3. **Full suite green**: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_util_misc.py tests/test_treemodel.py tests/test_historycombo.py tests/test_msgarea.py tests/test_findbar.py -v` — zero failures; the run includes, by name: `test_search_down_terminates`, `test_search_up_terminates` (PEP 479 regression, tree.py:138/158), `test_add_empty_path_is_none` (tree.py:88 quirk), `test_button_for_response_regression` (msgarea.py:72), `test_no_shared_buttons_default` (msgarea.py:242), `test_browse_dir_mode_regression` (historyentry.py:314-318), `test_replace_all_terminates_when_replacement_contains_pattern` + `test_replace_all_zero_length_pattern_terminates` (findbar.py:88), `test_replace_all_single_undo`, `test_astral_offsets` (UTF-16), `test_single_item_roundtrip` (QSettings list normalization).
4. **Traversal parity**: the golden orders in `test_search_down_terminates`/`test_search_up_terminates` match the hand-traced GTK algorithm output documented in the test (down from A: A0,A1,A1a,B,C,C0; up from C0: C,B,A1a,A1,A0,A).
5. **No zombie GTK-isms in new code**: `grep -rn "raise StopIteration" meldq/` → no output; `grep -rnE "^import (gtk|gobject|atk|gconf|gnomevfs)|^from (gtk|gobject)" meldq/` → no output; `ls meldq/widgets/` contains `historycombo.py msgarea.py treemodel.py findbar.py` and does NOT contain `wraplabel*`, `notebooklabel*`, `gnomeglade*`.
6. **i18n msgid fidelity**: `grep -Fn '_("_Search for")' meldq/widgets/findbar.py && grep -Fn '_("Replace _With")' meldq/widgets/findbar.py && grep -Fn '_("_Match Case")' meldq/widgets/findbar.py && grep -Fn '_("Who_le word")' meldq/widgets/findbar.py && grep -Fn '_("Regular E_xpression")' meldq/widgets/findbar.py && grep -Fn '_("_Browse...")' meldq/widgets/historycombo.py && grep -Fn '_("Select directory")' meldq/widgets/historycombo.py && grep -Fn '_("Select file")' meldq/widgets/historycombo.py` all succeed (msgids identical to the 1.4 glade/py sources so the 34 catalogs keep matching), and `grep -rn '"&' meldq/widgets/ | grep '_('` finds nothing (no pre-converted mnemonics inside `_()`).
7. **Icons shipped**: `ls meldq/resources/icons/ | grep -c '^tree-'` prints `9`; `QT_QPA_PLATFORM=offscreen python -c "from PyQt6.QtWidgets import QApplication; a=QApplication([]); from meldq.widgets.treemodel import state_icons, STATE_NEW; ic=state_icons(); assert ic[STATE_NEW][0] is not None and not ic[STATE_NEW][0].isNull(); print('icons ok')"` prints `icons ok`.
8. **Manual smoke** (Linux or macOS, real display): run
   `python -c "from PyQt6.QtWidgets import *; import sys; from meldq.widgets.findbar import FindBar; from meldq.widgets.msgarea import MsgAreaController, ResponseId; from meldq.util.misc import gtk_mnemonic_to_qt as m; from meldq.conf import _; app=QApplication(sys.argv); w=QMainWindow(); c=QWidget(); v=QVBoxLayout(c); mc=MsgAreaController(); a=mc.new_from_text_and_icon('dialog-information', _('Files are identical')); a.add_stock_button_with_text(m(_('Hi_de')),'window-close',ResponseId.CLOSE); a.response.connect(lambda r: mc.clear()); e=QPlainTextEdit('one two one two one'); f=FindBar(); v.addWidget(mc); v.addWidget(e); v.addWidget(f); f.start_replace(e); w.setCentralWidget(c); w.show(); sys.exit(app.exec())"`
   Expected observable behavior: a tooltip-tinted banner with bold "Files are identical" and a "Hide" button that dismisses it on click; the find bar shows find+replace rows; typing `one` and pressing Enter selects successive occurrences, wrapping past the end; typing `[` with "Regular E&xpression" checked and pressing Enter shows an error dialog; a non-matching term tints the find field pink and editing the term clears the tint; Replace All with `one`→`ONE` changes all three occurrences and a single Ctrl+Z in the editor... (note: Ctrl+Z here exercises the raw QPlainTextEdit stack — one undo restores the pre-replace-all text, proving the single edit block).

### Estimated effort

**6 person-days** (range 5–7): T4.1 ≈ 0.25 pd; T4.2 ≈ 1.25 pd; T4.3 ≈ 0.5 pd; T4.4 ≈ 0.5 pd; T4.5 ≈ 1 pd; T4.6 ≈ 1 pd; T4.7 ≈ 0.5 pd; T4.8 ≈ 1 pd. This is consistent with the survey's 3–6 pd for `meld/ui/` (roughly half of which is deletion) plus the `tree.py` share (~1.5 pd) of dirdiff's 8–14 pd. The riskiest items are the UTF-16 offset semantics in T4.8 and role-styling fidelity in T4.2 — both are fenced by dedicated regression tests.

---

## WP5 — Directory comparison (`meldq/dirdiff.py`)

### Goal

Port Meld 1.4.0's directory comparison — `meld/dirdiff.py` (1043 LOC) plus the shared tree-store layer `meld/tree.py` (160 LOC) — to `meldq/dirdiff.py` and `meldq/widgets/treemodel.py`, replacing three GtkTreeViews on an interleaved-column `gtk.TreeStore` with three `QTreeView`s sharing one role-based `DiffTreeModel` (the S2 spike has already validated `setTreePosition` + hidden sibling columns). The filesystem-scan generator, state computation, filters, copy/delete operations, cross-pane sync, and per-pane diffmap overview are ported behaviorally 1:1, with the survey-listed latent bugs fixed under regression tests.

### Dependencies

- **WP2** (engine port): `meldq/engine/task.py` (`FifoScheduler` with `add_task(task, atfront=False)`, `tasks_pending()`, `iteration()`, `remove_all_tasks()`, and the `runnable_cb` callback attribute), `meldq/util/misc.py` (pure helpers: `shorten_names`, `shell_to_regex`, `copy2`, `copytree`, `all_equal`); `meldq/conf.py` (`_`, `ngettext`, resource paths — provided by WP0/WP3, not WP2).
- **WP3** (shell & infrastructure): `meldq/doc.py` `MeldDoc(QObject)` with the four normative signals; `meldq/app.py` `MeldWindow` + `DocActionManager` + `SchedulerPump`; `meldq/util/prefs.py` `Preferences(QObject)` with `changed = pyqtSignal(str)` and keys `regexes`, `filters`, `ignore_symlinks`, `color_delete_bg`, `color_replace_bg`; `meldq/widgets/historycombo.py` `FileHistoryCombo` (provided by WP4).
- Does **NOT** depend on the filediff WPs. `meldq/diffmap.py` is created here if the filediff WP has not landed it yet (see T5.9 and Contracts provided).
- Phase-0 spike S2 (3 views × 1 model × `setTreePosition`) must have passed — it did, per the plan; if you find no spike artifact, re-verify with a 20-line scratch script before T5.3.

### Old-code map

| Old file:lines | What it does | New home |
|---|---|---|
| `meld/tree.py:23` | `COL_PATH..COL_END` column constants | deleted — replaced by roles in `meldq/widgets/treemodel.py` |
| `meld/tree.py:25-28` | STATE_* constants re-export from `vc/_vc.py:33-36` | STATE_* module constants in `meldq/widgets/treemodel.py` (WP4 T4.2, canonical for the UI layer; `meldq/vc/_vc.py` imports or matches them in WP7 T7.2) |
| `meld/tree.py:30-38` | module-import-time pixbuf loading of 8 tree icons | lazy `_icon_cache` in `meldq/widgets/treemodel.py` |
| `meld/tree.py:40-46` | `DiffTreeStore(gtk.TreeStore)`, interleaved ntree×4 columns | `DiffTreeModel(QStandardItemModel)`, one column per pane |
| `meld/tree.py:48-76` | Pango markup textstyle + pixstyle tables | `STATE_STYLE` dict → `data()` Foreground/Background/Font/Decoration |
| `meld/tree.py:78-97` | `add_entries` / `add_empty` / `add_error` | `DiffTreeModel` methods, same names (fix `:88` bug) |
| `meld/tree.py:99-118` | `value_paths`/`value_path`/`column_index`/`set_state`/`get_state` | `DiffTreeModel` methods (drop `column_index`) |
| `meld/tree.py:120-159` | `inorder_search_down`/`_up` iter-walk generators | `DiffTreeModel` methods over `QModelIndex` (PEP 479 fix) |
| `meld/dirdiff.py:43-100` | `_files_same` + `_cache` tri-state content comparison | module functions in `meldq/dirdiff.py`, bytes semantics |
| `meld/dirdiff.py:102-118` | `COL_EMBLEM`, `pixbuf_newer`, `DirDiffTreeStore` | deleted — `ROLE_NEWER` role + composited icons in treemodel |
| `meld/dirdiff.py:125-155` | `EmblemCellRenderer` custom GObject renderer | deleted — pre-composited cached `QPixmap` via DecorationRole |
| `meld/dirdiff.py:163-168` | `TypeFilter` | `meldq/dirdiff.py`, unchanged (add `__slots__`-friendly dataclass ok) |
| `meld/dirdiff.py:179-242` | `DirDiff.__init__`: glade load, actions, widget lists, view setup | `DirDiff(MeldDoc)` + code-built `QGridLayout` in `meldq/dirdiff.py` |
| `meld/dirdiff.py:244-252` | `update_regexes` (text-filter compilation) | `DirDiff.update_regexes` (fix `(?m)` suffix — py3.11 `re.error`) |
| `meld/dirdiff.py:254-283` | custom-filter popup dance + UIManager switch-in/out | deleted — doc/shell contract + `QToolButton` InstantPopup |
| `meld/dirdiff.py:285-314` | `create_name_filters` + dynamic filter-action UI defs | `DirDiff.create_name_filters` building checkable QActions |
| `meld/dirdiff.py:316-318` | `on_preference_changed` | slot on `Preferences.changed` |
| `meld/dirdiff.py:320-336` | `_do_to_others` + `_sync_vscroll/_sync_hscroll` | guarded-bool sync helpers on scrollbar `valueChanged` |
| `meld/dirdiff.py:338-343` | `_get_focused_pane` | sticky `self.focus_pane` tracking via focus events |
| `meld/dirdiff.py:345-361` | `file_deleted` / `file_created` | same names, `QPersistentModelIndex` args |
| `meld/dirdiff.py:363-379` | `on_fileentry_activate` / `set_locations` | same names over `FileHistoryCombo` |
| `meld/dirdiff.py:381-390` | `recursively_update` (child purge + task scheduling) | same name; `gen.__next__` to scheduler |
| `meld/dirdiff.py:392-517` | `_search_recursively_iter` scan generator + accum classes | same name, generator preserved; fixes at :427-436, :439, :442-443, :456/:467/:477, :468/:478, :500-501 |
| `meld/dirdiff.py:519-535` | `launch_comparison(s_on_selected)` | same names; `create_diff.emit(list(...))` |
| `meld/dirdiff.py:537-594` | `copy_selected` / `delete_selected` | same names; sorted `QPersistentModelIndex` discipline |
| `meld/dirdiff.py:596-623` | cursor-changed status line (`rwx`, `nice`) | `on_treeview_cursor_changed` slot; `status_changed.emit` |
| `meld/dirdiff.py:625-644` | Left/Right cross-pane hop key handling | `DirTreeView.keyPressEvent` + direct slot call (`:643` fix) |
| `meld/dirdiff.py:646-670` | row activation, expand/collapse mirroring | `on_treeview_row_activated`, `expanded`/`collapsed` slots |
| `meld/dirdiff.py:672-688` | popup handler-block dance + focus in/out sensitivity | focus eventFilter + `PopupFocusReason` guard (`:683` fix) |
| `meld/dirdiff.py:694-744` | toolbar handlers, state/name filter toggles, hide-selected | QAction `triggered`/`toggled` slots |
| `meld/dirdiff.py:749-751` | `_get_selected_paths` | returns sorted `list[QPersistentModelIndex]` |
| `meld/dirdiff.py:757-828` | `_filter_on_state` / `_update_item_state` | same names, verbatim logic over model facade |
| `meld/dirdiff.py:830-854` | `popup_in_pane` / button-press context menu | `customContextMenuRequested` + `DirTreeView.mousePressEvent` |
| `meld/dirdiff.py:856-871` | `set_num_panes` (model rebuild, show/hide) | same name; fix map no-ops `:863/:866`; rewire after `setModel` |
| `meld/dirdiff.py:873-888` | `refresh` / `recompute_label` / `_update_diffmaps` | same names |
| `meld/dirdiff.py:890-984` | diffmap expose drawing + click-to-scroll | `DiffMap(QWidget)` in `meldq/diffmap.py` + `DirDiff._diffmap_chunks` |
| `meld/dirdiff.py:986-1023` | `on_file_changed` external-change tree search | same name, verbatim over indexes |
| `meld/dirdiff.py:1025-1042` | `next_diff` / `on_reload_activate` | same names; neutral direction enum |
| `data/ui/dirdiff.glade` | 2×7 GtkTable layout, autoconnect handlers | code-built `QGridLayout` in `DirDiff._build_ui` |
| `data/ui/dirdiff-ui.xml` | UIManager menu/toolbar/popup merge spec | ordering spec for `menu_contributions`/`toolbar_contributions`/popup QMenu |

### Tasks

---

#### T5.1 — `meldq/widgets/treemodel.py`: DiffTreeModel + traversal helpers (shared with vcview)

**Old refs:** `meld/tree.py:23-159`, `meld/dirdiff.py:102-104` (emblem), `meld/vc/_vc.py:33-36` (STATE constants).

**Build:**

1. Copy the 9 icons `data/icons/tree-{file,folder}-{normal,new,changed,missing}.png` + `data/icons/tree-file-newer.png` into `meldq/resources/icons/` (plain `git add` of copies; do not modify the old tree).
2. EXTEND the WP4-landed `meldq/widgets/treemodel.py` (T4.2/T4.3) — **do not recreate it**. WP4's
   signatures are normative: `DiffTreeModel(ntree=3, extra_cols=0, parent=None)`, model-METHOD
   `rowpath(index)`/`index_for_rowpath(path)`, `DEFAULT_TEXT_STYLES` + per-instance `text_styles`,
   lazy `state_icons()`, and the STATE_* module constants (defined THERE — do NOT import them from
   `meldq.vc._vc`, which only lands in WP7). Items 3–5 below re-state the landed design for
   context: where they differ from WP4's landed code (free-function `rowpath`, `STATE_STYLE` dict,
   `_icon(state, isdir, newer)` loader), adapt to WP4's API instead of recreating it; the genuine
   additions of this task are `ROLE_NEWER`, `set_newer()`, and newer-emblem compositing in the
   icon cache. Add new tests to the existing `tests/test_treemodel.py`.

```python
ROLE_NEWER = Qt.ItemDataRole.UserRole + 4   # bool, dirdiff "newer" emblem; default False
# ROLE_PATH/ROLE_STATE/ROLE_ISDIR (UserRole + 1/2/3) already landed in WP4 T4.2.
# Where this WP's text writes rowpath(idx) / index_for_rowpath(self.model, p), read the
# WP4 model methods self.model.rowpath(idx) / self.model.index_for_rowpath(p).
```

`rowpath` climbs `index.row()`/`index.parent()` producing e.g. `(0, 2, 1)`; `index_for_rowpath` walks `model.index(r, 0, parent)`. These are the *only* row-addressing currency — they replace GTK tree-path tuples verbatim, so `todo.sort()` (dirdiff.py:400) and the expansion-propagation prefix slicing (dirdiff.py:504-515) keep working unchanged.

3. `STATE_STYLE`: a module-level dict `state -> (fg: str|None, bg: str|None, bold: bool, italic: bool, strikethrough: bool)` transliterating `tree.py:48-61` exactly: IGNORED/NONE `#888888`; NORMAL black; NOCHANGE black italic; ERROR `#ff0000` on `yellow` bold; EMPTY `#999999` italic; NEW `#008800` bold; MODIFIED `#880000` bold; CONFLICT `#ff0000` on `#ffeeee` bold; REMOVED `#880000` bold strikethrough; MISSING `#888888` strikethrough. Assert `len(STATE_STYLE) == STATE_MAX` minus... no: cover all 11 states 0..STATE_MISSING (tree.py:62 asserts length == STATE_MAX == 11).
4. Lazy icon cache: `_icon(state: int, isdir: bool, newer: bool) -> QIcon | None`, module function with a dict cache keyed `(state, isdir, newer)`. Loads `QPixmap` from `meldq/resources/icons/` via the `meldq.conf` resource-path helper, scaled `scaledToHeight(20 if isdir else 14, Qt.TransformationMode.SmoothTransformation)`; when `newer`, composite `tree-file-newer.png` (14px) over the base with `QPainter` at the right edge. The pixstyle table (tree.py:63-75): NORMAL-family states → normal icons; NEW → `-new`; MODIFIED/CONFLICT/REMOVED → `-changed`; MISSING → `-missing`; ERROR/EMPTY → `None`. **Nothing loads at import time** (tree.py:30-38 loaded at import; Qt requires a live QGuiApplication — enforce with the import-purity test in AC1).
5. `class DiffTreeModel(QStandardItemModel)`:

```python
def __init__(self, ntree: int = 3, parent=None):      # setColumnCount(ntree); self.ntree = ntree
def add_entries(self, parent: QModelIndex | None, names: list) -> QModelIndex   # appendRow of ntree QStandardItems; ROLE_PATH per pane; DisplayRole = os.path.basename(name)
def add_empty(self, parent: QModelIndex, text: str = "empty folder") -> QModelIndex
def add_error(self, parent: QModelIndex, msg: str, pane: int) -> None
def value_path(self, index: QModelIndex, pane: int) -> str | None
def value_paths(self, index: QModelIndex) -> list
def set_state(self, index: QModelIndex, pane: int, state: int, isdir: bool = False) -> None
def get_state(self, index: QModelIndex, pane: int) -> int
def set_newer(self, index: QModelIndex, pane: int, newer: bool) -> None
def inorder_search_down(self, index: QModelIndex):    # generator of QModelIndex
def inorder_search_up(self, index: QModelIndex):      # generator of QModelIndex
def data(self, index, role=Qt.ItemDataRole.DisplayRole)
```

Per-pane values live as roles on the item at `(row, pane)`; all methods accept an index of any column and normalize (`index.sibling(index.row(), pane)`). `set_state` stores ROLE_STATE + ROLE_ISDIR and sets DisplayRole to `os.path.basename(value_path(...))` — **plain text, no markup, no escaping** (kills `gobject.markup_escape_text`, tree.py:89/97/108). `add_empty` sets `STATE_EMPTY` on every pane, DisplayRole = the text, and **ROLE_PATH = None** — this FIXES the upstream bug at tree.py:88 where the pixstyle *tuple* was stored into COL_PATH (regression test required: `value_path()` on an empty row returns `None`, not a tuple). `add_error` sets STATE_ERROR on all panes but message text only on `pane` (tree.py:92-97).

`data()` override: for roles Foreground/Background/Font/Decoration, read the item's own ROLE_STATE/ROLE_ISDIR/ROLE_NEWER and return `QColor(fg)` / `QColor(bg)` / a `QFont` with bold/italic/strikeout flags / `_icon(...)`; else `super().data(...)`. This is the normative replacement for Pango-markup-in-model.

`inorder_search_down` transliterates tree.py:120-139 (children first, then next sibling, then climb until a parent has a next sibling); `inorder_search_up` transliterates tree.py:141-159 (previous sibling then descend to deepest last child, else parent) — implement the previous-sibling step with `rowpath` tuple arithmetic exactly as `path[:-1] + (path[-1]-1,)` to stay faithful.

**TRAPS:**
- `tree.py:138` and `tree.py:158` — `raise StopIteration()` inside a generator is a **RuntimeError under PEP 479** (py3.7+). Must become bare `return`. Only triggers at the first/last row of the tree, i.e. exactly where next-diff navigation lands; write the boundary test (AC2).
- `tree.py:88` — `add_empty` stores `self.pixstyle[STATE_EMPTY]` (a tuple) into the COL_PATH column. Any code calling `value_path` on an empty row got a tuple back. Fix (store None); do not replicate.
- `tree.py:30-38` — icons loaded at module import. In Qt, creating QPixmap before QApplication warns/fails; keep loading lazy.
- `tree.py:42-43` — `type("")`/`type(pixbuf)` column-type tokens: GTK-ism, disappears entirely; don't look for an equivalent.
- `tree.py:106` — `isdir` used as int index into a tuple (`pixstyle[state][isdir]`); the new signature takes a real `bool`.
- vcview (WP7) shares this file — do not bake dirdiff-only assumptions into method signatures; `ROLE_NEWER` defaults to unset/False so vcview never touches it.
- `QStandardItemModel.appendRow` with fewer items than columns leaves null items — always append exactly `ntree` `QStandardItem()`s.

**Tests:** `tests/test_treemodel.py` (pytest-qt for the `data()` role checks; traversal/rowpath tests need only QModelIndex, still require a `QApplication` fixture from pytest-qt).

---

#### T5.2 — `_files_same` with explicit bytes semantics + text-filter regexes

**Old refs:** `meld/dirdiff.py:43-100` (function + `_cache`), `:244-252` (`update_regexes`), `:285-302` (name-filter regex building), `:163-168` (`TypeFilter`), `misc.py:135-151` (`struct` with `__cmp__`), `misc.py:299` (`shell_to_regex`).

**Build:** In `meldq/dirdiff.py` (top of file, before the DirDiff class):

```python
import collections
StatSig = collections.namedtuple("StatSig", "mode size mtime")
_cache: dict = {}

def _files_same(lof, regexes) -> int:
    """0 = differ, 1 = identical, 2 = identical after regex filtering."""
```

Normative semantics (this is the WP-mandated redesign of dirdiff.py:83-98):
1. Signatures: `StatSig(stat.S_IFMT(s.st_mode), s.st_size, s.st_mtime)` — a namedtuple, **not** `misc.struct` (whose py2 `__cmp__` at misc.py:150 dies in py3: `==` on struct instances falls back to identity, so the cache-validity check at dirdiff.py:79 would *never* hit and every rescan would re-read every file — a silent performance regression, not a crash).
2. All-dirs → 1; mixed file/dir → 0; no regexes and sizes differ → 0; cache hit with equal sigs → cached result (verbatim from :64-80).
3. **Read bytes**: `contents = [open(f, "rb").read() for f in lof]` (fixes the text-mode read of arbitrary binary at dirdiff.py:83, which in py3 raises `UnicodeDecodeError` on any non-UTF-8 file and returns wrong results on `\r\n` translation).
4. If all byte-strings equal → 1.
5. Else, if `regexes` non-empty: decode each with `bytes.decode("utf-8", errors="replace")`, apply `re.sub(r, "", text)` for each compiled pattern, result = 2 if all filtered texts equal else 0. If `regexes` empty → 0. Keep the tri-state ints (callers at :771 and :797-820 compare `== 1` / `== 2` truthily).
6. **Documented divergence** (put this in the docstring): py2 compared raw bytes-as-str and ran str regexes directly over raw file bytes; py3 applies the user's text filters to a UTF-8/`replace`-decoded view. Files that differ only inside byte sequences that are invalid UTF-8 *and* matched by a filter may now be classified differently. This is accepted (D-level decision); the parity test pins the new behavior.
7. Keep the `except (MemoryError, OverflowError)` huge-file fallback to pairwise `filecmp.cmp(..., shallow=False)` (:84-91) including its known limitation (filters not applied — keep the FIXME comment).
8. Cache write: `_cache[lof] = (sigs, result)` (plain tuple, no struct).

`update_regexes` (from :244-252): iterate `misc.ListItem` lines of `self.prefs.regexes`; **compile as `re.compile("(?m)" + r.value)`** — the original appends `"(?m)"` at the END of the pattern (dirdiff.py:249), which Python 3.11 rejects outright with `re.error: global flags not at the start of the expression`. This is a hard crash on first preference load, not a silent bug. On `re.error`, show the exact 1.4 message `_("Error converting pattern '%s' to regular expression") % r.value` via `QMessageBox.warning`.

`create_name_filters` regex core (from :285-302): port verbatim (multi-glob `"(%s)$" % "|".join(shell_to_regex(b)[:-1] ...)`, single glob, empty-skip, `TypeFilter(f.name, f.active, func)` with the `lambda x, r=cregex: r.match(x) is None` default-arg binding). The dynamic QAction part of `create_name_filters` is T5.4; keep the pure part testable without Qt.

**TRAPS:**
- `dirdiff.py:249` — `r.value+"(?m)"`: **`re.error` on Python 3.11**. Highest-priority fix in this task.
- `dirdiff.py:83` — `open(f, "r")` on binary files: py3 `UnicodeDecodeError` → scan generator dies mid-scan. Bytes read is mandatory.
- `misc.py:150` — `struct.__cmp__` unused in py3 → cache never validates (silent). Replaced by namedtuple.
- `dirdiff.py:98` — `result = all_same(contents) and 2`: `all_same` returns 0/1; keep tri-state semantics but write it as an explicit `if`.
- `dirdiff.py:96-97` — the loop reassigns `contents` (list) from `re.sub` results; fine in py3, but do not "optimize" into a generator — the list is compared twice.
- `misc.ListItem` (misc.py:348-356) splits on tabs and does `int(a.pop(0))` — pref strings must keep the `name\tactive\tvalue` format; coordinate with WP3's prefs defaults, don't invent a new format here.
- Do not import Qt into any helper that the pure tests touch except the QMessageBox in `update_regexes` (keep the dialog call at the caller level so `_files_same`/filter-building stay Qt-free).

**Tests:** `tests/test_files_same.py` — pure pytest (no Qt): binary-identical → 1; binary-different → 0; text files differing only in a `$Id:.*$`-matched line with that filter → 2; same but filters empty → 0; invalid-UTF-8 binary with filters present → no exception; cache: monkeypatch `builtins.open` with a counter — second call with unchanged mtime reads 0 files, after `os.utime` re-reads; `MemoryError` fallback via monkeypatched read.

---

#### T5.3 — DirDiff skeleton: class, layout, views, model wiring, pane switching

**Old refs:** `meld/dirdiff.py:176-242` (init), `:856-871` (`set_num_panes`), `:363-379` (`set_locations`/fileentries), `:873-884` (`refresh`/`recompute_label`), `data/ui/dirdiff.glade` (geometry).

**Build:**

1. `class DirTreeView(QTreeView)` (private to `meldq/dirdiff.py`): constructor takes the owning DirDiff; overrides `keyPressEvent` (T5.7 fills it) and `mousePressEvent` (calls `self._dirdiff.on_pane_pressed(self)` before `super()` — this is the "unselect other panes on any click" behavior from dirdiff.py:838-841, which must fire for clicks on empty space too, so the `pressed` signal is NOT sufficient).
2. `class DirDiff(MeldDoc)` in `meldq/dirdiff.py`. Follow the widget-exposure convention already established by `meldq/doc.py` (grep it first); default assumption: the doc owns `self.widget = QWidget()` which MeldWindow inserts into the QTabWidget. Constructor signature: `def __init__(self, prefs, num_panes: int)` matching dirdiff.py:179.
3. `_build_ui()` — code-built `QGridLayout` on `self.widget` replacing `dirdiff.glade` (glade-2 format, unconvertible; per D7 dynamic views are code-built). Grid columns `[0..6]` = `diffmap0 | pane0 | spacer0 | pane1 | spacer1 | pane2 | diffmap1`; row 0 = `FileHistoryCombo` per pane at columns 1/3/5; row 1 = everything else. Column stretch 1 on pane columns, 0 elsewhere. Build the widget lists in loops (`self.treeview = [DirTreeView(self) for _ in range(3)]`, `self.fileentry = [...]`, `self.diffmap = [DiffMap(), DiffMap()]`, `self.linkmap = [QWidget(), QWidget()]`), killing `map_widgets_into_lists` (dirdiff.py:211). The two `linkmap` entries are **plain spacer QWidgets** with `setFixedWidth(50)` (glade width_request=50) — do NOT instantiate `meldq.linkmap.LinkMap`; in 1.4 dirdiff they are blank, and the glade wires their `scroll_event` to a handler that does not exist (`on_linkmap_scroll_event` — dead wiring, drop). DiffMaps: `setFixedWidth(20)` (glade width_request=20).
4. View configuration per view: `setHeaderHidden(True)`, `setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)`, `setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)`, `setUniformRowHeights(True)`, `setExpandsOnDoubleClick(False)` (see TRAPS), `setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)`, both scrollbar policies `ScrollBarAlwaysOn` (glade GTK_POLICY_ALWAYS). Per D12 the GTK left-side-scrollbar asymmetry on pane 0 (glade `GTK_CORNER_TOP_RIGHT`, dirdiff.glade:42-43) is **dropped** — all scrollbars on the right.
5. `_set_model(model)` helper — the single place that attaches a model (needed because `set_num_panes`, like dirdiff.py:858, creates a **fresh** `DiffTreeModel(n)` on every pane-count change): for each of the first n views: `view.setModel(model)`; `view.setTreePosition(i)`; `for c in range(model.columnCount()): view.setColumnHidden(c, c != i)`; then **reconnect** `view.selectionModel().currentRowChanged` → `self.on_treeview_cursor_changed` (see TRAPS).
6. `set_num_panes(n)` transliterating dirdiff.py:856-871: guard `n != self.num_panes and n in (1,2,3)`; new model; `_set_model`; then show/hide with **explicit loops** — the originals are `map(lambda x: x.show(), toshow)` / `map(... hide ...)` at dirdiff.py:863 and :866, which are **silent no-ops in py3** (map is lazy): a missed fix ships a dirdiff that never switches pane counts. Show `scrolledwindow`-equivalents (the views), `fileentry[:n]`, `linkmap[:n-1]`, `diffmap[:2 if n>1 else ...]` — follow the original slicing exactly: `toshow = views[:n] + fileentry[:n] + linkmap[:n-1] + diffmap[:n]`, `tohide = views[n:] + fileentry[n:] + linkmap[n-1:] + diffmap[n:]` (note `diffmap[:n]` — with n=1 only the left diffmap shows; preserve). Preserve the first-time-through branch (:867-871): only re-trigger `on_fileentry_activate(None)` when `num_panes` was already nonzero.
7. `set_locations(locations)` (dirdiff.py:367-379): `set_num_panes(len(locations))`; `os.path.abspath(l or ".")`; model cleared implicitly by the fresh model or `model.removeRows`; `fileentry[pane].set_filename(loc)` + `prepend_history(loc)` (the WP4 T4.5 API); `child = model.add_entries(None, locations)`; `self.treeview[0].setFocus()`; `self._update_item_state(child)`; `recompute_label()`; `self.scheduler.remove_all_tasks()`; `self.recursively_update((0,))`.
8. `on_fileentry_activate(self, *_)` — must accept zero meaningful args because `set_num_panes` calls it with `None` (dirdiff.py:869). Reads all pane paths, calls `set_locations`.
9. `refresh()` (dirdiff.py:873-877) and `recompute_label()` (:879-884, `misc.shorten_names`, `" : ".join`, `self.label_changed.emit(self.label_text)` — MeldDoc signal, not the old method-emit combo at melddoc.py:106-107).

**TRAPS:**
- `dirdiff.py:863/:866` — map-for-side-effect no-op (see above). One of the two highest-value silent breaks in this file.
- After **every** `QTreeView.setModel()` the view creates a new `QItemSelectionModel` and resets header sections: `currentRowChanged`/`selectionChanged` connections die silently and hidden columns un-hide. `set_num_panes` recreates the model (dirdiff.py:858) on every comparison start — if you wire selection signals only in `__init__`, the status bar and diffmaps go stale after the *second* comparison and nothing crashes. All wiring lives in `_set_model`.
- `setExpandsOnDoubleClick(False)` is required: the row-activation handler (dirdiff.py:658-662, ported in T5.7) itself toggles expansion for directories; with Qt's default double-click-expands the two would cancel out (toggle twice) — the GTK code owned the toggle exclusively.
- `dirdiff.py:375` — `self.treeview0` is gnomeglade `__getattr__` magic; the new code has only the list `self.treeview[0]`.
- `dirdiff.py:236` — `self.linediffs = [[], []]` is dead (assigned once, never read anywhere in dirdiff.py). Do not port.
- MeldDoc init (melddoc.py:44-51) sets `self.num_panes = 0` — `set_num_panes` relies on that sentinel; confirm `meldq/doc.py` does the same or set it explicitly in DirDiff.
- `QTreeView.setTreePosition(pane)` must be called **after** `setModel`, and column hiding after both (S2 spike order).
- Don't connect `Preferences.changed` more than once across model rebuilds — connect in `__init__`, not `_set_model`.

---

#### T5.4 — Actions and the doc/shell contract

**Old refs:** `meld/dirdiff.py:183-210` (action tables), `:201` + `:263-283` (UIManager merge — deleted), `:254-261` (filter popup), `:304-314` (dynamic filter actions), `data/ui/dirdiff-ui.xml` (ordering), `meldapp.py:162-164` (submenu labels).

**Build:**

1. Create all QActions in `_make_actions()`, parented to `self.widget`, stored in `self.actions: dict[str, QAction]` keyed by the old names (`DirCompare`, `DirCopyLeft`, `DirCopyRight`, `DirDelete`, `Hide`, `DirOpen`, `IgnoreCase`, `ShowSame`, `ShowNew`, `ShowModified`). Labels/tooltips reuse the **exact** 1.4 strings through `_()` (i18n rule): `_("_Compare")`→strip the mnemonic underscore to `Qt` convention `_("_Compare").replace("_","&")` — no: keep msgid identical for catalog matching; set the QAction text to the translated string with `_` swapped for `&` *after* translation (`_( "_Compare" ).replace("_", "&", 1)`). Tooltips: `_("Compare selected")`, `_("Copy To Left")`, `_("Copy To Right")`, `_("Delete selected")`, `_("Hide selected")`, `_("Open selected")`, `_("Ignore case of entries")`, `_("Show identical")`, `_("Show new")`, `_("Show modified")`, `_("Set active filters")`. Labels `_("Left")`, `_("Right")`, `_("Hide")`, `_("Case")`, `_("Same")`, `_("New")`, `_("Modified")`, `_("Filters")`. Icons via `QIcon.fromTheme` with the D11 fallback set: DirCompare→`dialog-information`, DirCopyLeft→`go-previous`, DirCopyRight→`go-next`, DirDelete→`edit-delete`, Hide→`window-close`, DirOpen→`document-open`, IgnoreCase→`format-text-italic`, ShowSame→`emblem-default`/apply-like, ShowNew→`list-add`, ShowModified→`list-remove`.
2. Toggles: `setCheckable(True)`; defaults from dirdiff.py:193-198: IgnoreCase False, ShowSame/ShowNew/ShowModified True. Connect `toggled(bool)` to the T5.7/T5.6 slots. Keep a plain attribute `self.ignore_case: bool` mirrored from the IgnoreCase action — the scan generator reads this attribute, not the action (the original reads action state mid-generator at dirdiff.py:406; decoupling keeps the generator testable headless).
3. Filters button: `self.filter_button = QToolButton()` with `setText(_("Filters"))`, `setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)`, `setMenu(self.filter_menu)`. This replaces the whole CustomFilterMenu toggle + `_custom_popup_deactivated` + `position_menu_under_widget` machinery (dirdiff.py:199, :254-261, :270-273) — InstantPopup makes the un-toggle bookkeeping structurally impossible to need. Expose it on the toolbar via a container `QWidgetAction` appended to `toolbar_contributions()`.
4. `create_name_filters()` dynamic part (from :304-314): for each `TypeFilter`, a checkable QAction labeled `f.label`, tooltip `_("Hide %s") % f.label`, checked=`f.active`, `toggled` → `lambda checked, i=i: self._update_name_filter(checked, i)` (**keep the default-arg binding** — `i=i` — exactly as at :308; a bare closure captures the loop variable and every filter toggles the last one). Each action is added to BOTH `self.filter_menu` (the Filters button popup, replacing `/CustomPopup`) and the View-menu `FileFilters` submenu (replacing the `/Menubar/ViewMenu/FileFilters` merge at :311).
5. Doc/shell contract methods, per the normative contract:
   - `doc_actions(self) -> list[QAction]`: everything in `self.actions.values()` + the name-filter actions.
   - `menu_contributions(self) -> dict[str, list[QAction]]`: `{"view": [IgnoreCase, file_status_menu.menuAction(), file_filters_menu.menuAction()], "changes": []...}` where `file_status_menu = QMenu(_("File status"))` containing ShowSame/ShowNew/ShowModified and `file_filters_menu = QMenu(_("File filters"))` containing the name-filter actions (labels from meldapp.py:162/164; structure from dirdiff-ui.xml:3-12).
   - `toolbar_contributions(self) -> list[QAction]` in dirdiff-ui.xml:15-35 order: `[DirCompare, sep, DirCopyLeft, DirCopyRight, DirDelete, sep, Hide, IgnoreCase, sep, ShowSame, ShowNew, ShowModified, sep, filters_widget_action]` where `sep` = a QAction with `setSeparator(True)`.
6. Context popup: `self.popup_menu = QMenu(self.widget)` built ONCE in dirdiff-ui.xml:37-46 order: DirCompare | sep | DirCopyLeft, DirCopyRight | sep | DirOpen | sep | DirDelete.
7. Initial enabled state: DirCopyLeft/DirCopyRight/DirDelete disabled (the ctor calls the focus-out path at dirdiff.py:220 → :685-688 before any pane is focused).
8. Slot wiring for the six plain actions → the T5.8 operations (`launch_comparisons_on_selected`, `copy_selected(-1)`, `copy_selected(1)`, `delete_selected`, `on_filter_hide_current_clicked`, DirOpen → `_open_files` of selected, dirdiff.py:703-708).

**TRAPS:**
- The whole `on_container_switch_in_event`/`out_event` pair (dirdiff.py:263-283) and `ui_file` (:201) do **not** get ported — `DocActionManager` (WP3) repopulates placeholder sections on tab switch from the three contract methods. The one behavioral remnant to keep: on switch-in the old code re-grabbed focus and refreshed the status line via scheduled tasks (:275-277); reproduce by overriding the no-arg doc-activation hook WP3 provides (`MeldDoc.on_container_switch_in_event`, called by `MeldWindow._on_current_tab_changed` — T3.4/T3.7; schedule `self.treeview_focussed.setFocus` and `self.on_treeview_cursor_changed` in it).
- `action.props.is_important` loop (:207-210) and `misc.make_tool_button_widget` (:272-273) → nothing per-action; the shell sets `QToolBar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)` — do not try to port these.
- Mnemonic conversion: msgids must stay byte-identical to 1.4 (`"_Compare"`); convert `_`→`&` only on the *translated* result, and only the first underscore.
- Lambdas with loop variables at :300 and :308 — default-arg binding is load-bearing twice.
- `set_translation_domain("meld")` (:203) — gettext domain is handled globally by `meldq/conf.py`; nothing to port.

---

#### T5.5 — State computation and filtering

**Old refs:** `meld/dirdiff.py:757-779` (`_filter_on_state`), `:781-828` (`_update_item_state`), `:713-727` (state-filter toggles), `:729-736` (`_update_name_filter`), `:345-361` (`file_deleted`/`file_created`), `:986-1023` (`on_file_changed`).

**Build:**

1. `self.state_filters = [STATE_NORMAL, STATE_MODIFIED, STATE_NEW]` (from :237-241).
2. `_filter_on_state(roots, fileslist)` — verbatim transliteration of :757-779 over `_files_same`. Keep the `assert len(roots) == self.model.ntree`.
3. `_update_item_state(it: QModelIndex) -> int` — verbatim logic of :781-828:
   - `mtime(f)` returning 0 on OSError; newest_index = argmax, `-1` when all mtimes equal (:791-794).
   - `all_present = 0 not in mod_times` — **preserve the quirk** that a genuine epoch-0 mtime classifies as missing (document with a comment).
   - tri-state dispatch: `all_same == 1` → STATE_NORMAL; `== 2` → STATE_NOCHANGE; `all_present_same` truthy → STATE_NEW; else STATE_MODIFIED (:811-820).
   - Emblem: `self.model.set_newer(it, j, j == newest_index)` replacing the `j == newest_index and pixbuf_newer or None` and/or idiom + `set_value(COL_EMBLEM)` (:821-823).
   - Missing panes: `set_state(it, j, STATE_MISSING, True in one_isdir)` (:825-827) — `one_isdir` holds `None`/bool; `True in one_isdir` semantics preserved (missing entry shows a folder icon if any present sibling is a dir).
   - Return `different` (int 0/1) — the scan generator does `differences[0] |= ...` (:498).
4. State-filter toggles: `_update_state_filter(state, active)` verbatim (:713-721, keep the assert); three `toggled` slots (:722-727). `on_button_ignore_case_toggled` → sets `self.ignore_case` then `self.refresh()` (:710-711).
5. `_update_name_filter(active, idx)` verbatim (:729-736) → `refresh()`.
6. `file_deleted(pidx: QPersistentModelIndex, pane)` (:345-354): `files = model.value_paths(QModelIndex(pidx))`; if `any(os.path.exists(f) for f in files)` → `_update_item_state`; else `model.removeRow(idx.row(), idx.parent())`. Then `_update_diffmaps()`.
7. `file_created(pidx, pane)` (:356-361): walk `while it.isValid() and rowpath(it) != (0,): self._update_item_state(it); it = it.parent()` — note the original stops **before** updating the root row `(0,)`; preserve. Then `_update_diffmaps()`.
8. `on_file_changed(changed_filename)` (:986-1023): verbatim component-walk over `model.index(...)`/`iter_next`-equivalents (`child.sibling(child.row()+1, 0)`); collect found rows as `rowpath` tuples for the dedupe (`if path not in changed_paths`, :1019); update each.
9. `on_preference_changed`: slot on `Preferences.changed(str)` — `if key == "regexes": self.update_regexes()` (:316-318).

**TRAPS:**
- `dirdiff.py:350` — `if 1 in is_present` over a list of bools: works in py3 (`True == 1`) but write `any(...)` and add a comment; don't let a linter "fix" it to `if is_present`.
- `dirdiff.py:806/:828` — `different` is an int used with `|=`; the scan generator's `differences[0]` depends on it. Keep int (or bool — `|=` works — but be consistent).
- `dirdiff.py:823` — `x and y or z` idiom: if a future refactor moves this, remember `pixbuf_newer and ... or None` style breaks when the middle operand is falsy; the role-based `set_newer(bool)` sidesteps it.
- `dirdiff.py:795` — mtime-0 = missing quirk; also `mod_times` compares floats with `==` via `.count(max(...))` — port exactly, mtimes from the same stat calls are bit-identical.
- `on_file_changed` (:995) does `model.value_path(it, pane).split(os.sep)` — with ROLE_PATH now possibly `None` (empty rows), guard `value_path` results before `.split` only if the root row could be empty (it can't — preserve the original's lack of guard but note the empty-row `None` fix from T5.1 means child rows CAN return None: the component-walk at :1008 calls `os.path.basename(model.value_path(child, pane))` on every child, including EMPTY placeholder rows where the old code got the buggy tuple and the new code gets `None` → `TypeError`. Add `if name is None: child = next-sibling; continue` — this is a consequence of fixing tree.py:88 and needs a test: `on_file_changed` on a tree containing an empty-folder placeholder must not raise.)

---

#### T5.6 — Scan generator on the scheduler

**Old refs:** `meld/dirdiff.py:381-390` (`recursively_update`), `:392-517` (`_search_recursively_iter`), scheduler protocol `task.py:44/116/119`.

**Build:**

1. `recursively_update(path: tuple)` (:381-390): `it = index_for_rowpath(self.model, path)`; purge children with `self.model.removeRows(0, self.model.rowCount(it), it)`; `self._update_item_state(it)`; `self.scheduler.add_task(self._search_recursively_iter(path).__next__)` — the scheduler consumes a callable exactly as 1.4 passed `gen.next` (:390); `.next` does not exist in py3.
2. `_search_recursively_iter(rootpath)` — port :392-517 preserving the generator protocol (`yield` status strings; scheduler detects completion via StopIteration from `__next__`; PEP 479 only concerns raising StopIteration *inside* the body — never do that, always `return`):
   - Disable Hide action at start, re-enable at end (:393, :517).
   - `prefixlen`, `symlinks_followed`, `todo = [rootpath]`, `expanded = {}` — rowpath tuples throughout; `todo.sort()` each loop iteration then `pop(0)` (:399-401) — tuple ordering gives depth-first exactly as GTK paths did.
   - The two `accum` classes verbatim, EXCEPT the case-insensitive `add()` (:424-436) is refactored from AssertionError-as-control-flow to explicit checks — under `python -O` asserts vanish and the original silently corrupts the collision map:
     ```python
     def add(self, pane, items):
         for i in items:
             ci = i.lower()
             existing = self.items.get(ci)
             if existing is None:
                 self.items[ci] = self.default[:]
                 self.items[ci][pane] = i
             elif existing[pane] is not None:
                 self.bad.append(_("'%s' hidden by '%s'") %
                     (os.path.join(self.roots[pane], i), existing[pane]))
             else:
                 existing[pane] = i
     ```
     (preserve the exact message construction from :433-434, including that the second operand is the bare name, not joined — string parity for the catalogs).
   - `get()` case-insensitive branch: `keys = sorted(self.items)` (the original `keys = self.items.keys(); keys.sort()` at :442-443 is an AttributeError on a py3 view); keep `fixup`/`first_nonempty` verbatim (:444-449).
   - **Case-collision modal with pump pause** (:438-441): when `self.bad` is non-empty, the dialog fires from *inside the running generator*, and `QMessageBox.exec()` re-enters the event loop — the SchedulerPump timer fires, calls `scheduler.iteration()`, which calls `__next__` on the **already-executing** generator → `ValueError: generator already executing` → the scan dies. Wrap the dialog per §2.5: `self.scheduler.paused = True` / `try/finally: self.scheduler.paused = False` around `QMessageBox.warning(self.widget, "Meld", msg)`, using the exact 1.4 text `_("You are running a case insensitive comparison on a case sensitive filesystem. Some files are not visible:\n%s") % "\n".join(self.bad)`. WP3's `SchedulerPump._tick` skips paused schedulers (headless tests need nothing extra); a small `pump_paused()` contextmanager on `MeldDoc` doing exactly that flag-flip is an acceptable convenience wrapper.
   - Directory listing loop (:452-489): `except OSError as err` (the `except OSError, err` comma syntax at :456/:467/:477 is a py3 SyntaxError — loud, but listed for completeness); `print("Ignoring OS error: %s" % err)` and `print("ignoring dangling symlink", e)` as py3 calls (:468/:478 are py2 print statements); name filters applied with a list comprehension per filter — `entries = [e for e in entries if f.filter(e)]` — the original `entries = filter(f.filter, entries)` reassigned in a loop (:460-461) stacks lazy filter objects in py3; it happens to still work (nested lazy filters) but breaks the `len()`-free contract subtly on re-iteration — make it a list. Symlink-once logic via `(st_dev, st_ino)` dict verbatim (:470-483).
   - **THE map-for-side-effect fix** (:500-501): `map(lambda x: todo.append(self.model.get_path(add_entry(x))), alldirs)` and `map(add_entry, allfiles)` are silent no-ops in py3 — **the scan would add zero rows to the model and the app would look "done" instantly with an empty tree**. Replace:
     ```python
     for names in alldirs:
         child = add_entry(names)
         todo.append(rowpath(child))
     for names in allfiles:
         add_entry(names)
     ```
     where `add_entry` is the closure at :496-499 (`add_entries` + `differences[0] |= self._update_item_state(child)`).
   - Empty dir → `self.model.add_empty(it)` (:503).
   - Expansion propagation (:504-515): port the tuple algorithm **verbatim** (`expanded[path] = False` on differences; then for each sorted key, walk prefixes and `self.treeview[0].expand(index_for_rowpath(self.model, cur))`). `QTreeView.expand()` emits `expanded`, so the T5.7 mirror handler propagates to the other panes — same causality as GTK's `expand_row` → `on_treeview_row_expanded` → `_do_to_others` (:515 → :664-665).
   - Status yields: exact strings `_("[%s] Scanning %s")` (:394/:404) and `_("[%s] Done")` (:516), routed by the scheduler consumer to `self.status_changed.emit(...)` (check how WP3's pump forwards yielded strings; if it doesn't, emit directly before each yield).
3. `stop()` behavior comes from MeldDoc (melddoc.py:59-61) — verify WP3 ported it; the Stop toolbar action must be able to kill a running scan.

**TRAPS:**
- `dirdiff.py:500-501` — map no-op: the single most dangerous silent break in the whole subsystem. Regression test AC4 exists specifically for it.
- `dirdiff.py:390` — `.next` attribute: py3 `AttributeError` at first scan.
- `dirdiff.py:427-436` — AssertionError-as-control-flow: breaks under `python -O` (asserts stripped → `existing[pane]` silently overwritten, collisions unreported). AC10 runs the scan suite under `-O`.
- `dirdiff.py:439` — modal inside generator: generator-reentrancy `ValueError` under the Qt pump (GTK's recursive main loop tolerated it). Mandatory `scheduler.paused` bracketing (§2.5).
- `dirdiff.py:442-443` — `keys()` view has no `.sort()` in py3.
- `dirdiff.py:406` — the generator reads `IgnoreCase` action state mid-flight; new code reads `self.ignore_case` captured at class-selection time (the `accum` class is chosen once per outer loop iteration — actually per `while todo` iteration at :406; preserve per-iteration read of the attribute).
- `dirdiff.py:398 vs :504-515` — `expanded` dict keys are tuples; if you "modernize" rowpath to QModelIndex here the prefix-slicing propagation breaks. Tuples are load-bearing.
- Yield strings before slow work, exactly as the original (status appears while scanning, not after).

---

#### T5.7 — Cross-pane sync: selection, expansion, scroll, focus, keyboard, activation, status

**Old refs:** `meld/dirdiff.py:320-343`, `:596-644`, `:646-670`, `:672-688`, `:749-751`, `:830-854`.

**Build:**

1. Reentrancy guard: `self._syncing = False`; every mirror handler starts `if self._syncing: return`, sets it True in a `try/finally`. Replaces the `hasattr` lock at :320-328 (which in py3 also collides with the lazy-`map` bug: `adjs = map(...)` at :331/:335 produces a map object that `objects[:self.num_panes]` at :324 would `TypeError` on — moot once redesigned, but do not transliterate).
2. Scroll sync: for each view, `view.verticalScrollBar().valueChanged.connect(self._sync_vscroll)` and horizontal likewise (:234-235, :330-336). Handler copies the raw value to the other visible panes' bars under the guard. Ranges are identical across panes (same model, mirrored expansion) so raw copy matches GTK's `set_value(adjustment.value)`.
3. Expansion sync: `view.expanded.connect(self._on_expanded)` / `collapsed` (:664-670): mirror `other.expand(index)` / `collapse(index)` under the guard (indexes are shared — one model), then `_update_diffmaps()`.
4. Focus tracking (:213-221, :677-688): install `self.widget` as eventFilter on each view AND its viewport for `QEvent.Type.FocusIn`/`FocusOut` — or override in `DirTreeView`. On FocusIn of pane i: `self.treeview_focussed = view; self.focus_pane = i`; enable DirCopyLeft iff `i > 0`, DirCopyRight iff `i+1 < num_panes`, DirDelete True (:680-682); then **call `self.on_treeview_cursor_changed()` directly** — the original emits the built-in `cursor-changed` signal on the widget as control flow (`tree.emit("cursor-changed")` at :683); Qt cannot emit built-in signals from outside, and a missed call means a stale status bar that only manual testing catches. On FocusOut: disable the three actions (:685-688) **unless** the focus is leaving because a popup opened — check `QFocusEvent.reason() == Qt.FocusReason.PopupFocusReason` (this single check replaces the whole handler_block/unblock ceremony at :672-675/:831-833, which existed because GTK menus steal focus).
5. `_get_focused_pane()` returns `self.focus_pane` (sticky, updated on FocusIn, set to None only on non-popup FocusOut) — replaces the `is_focus()` scan at :338-343. Rationale: in Qt, by the time a context-menu QAction slot runs, the view may not report `hasFocus()`; the sticky value reproduces GTK's effective semantics (actions disabled whenever no pane owns focus, so slots never see a stale pane).
6. `_get_selected_paths(pane) -> list[QPersistentModelIndex]` (:749-751): `sorted((QPersistentModelIndex(i) for i in self.treeview[pane].selectionModel().selectedRows(0)), key=lambda p: rowpath(QModelIndex(p)))` — GTK's `get_selected_rows` returned paths **sorted**; Qt's `selectedRows()` order is arbitrary, and copy/delete/hide reverse-iterate assuming sorted order (:544, :578, :742). Sorting here is correctness, not cosmetics.
7. Left/Right pane hop in `DirTreeView.keyPressEvent` (:625-644): on `Qt.Key.Key_Right`/`Key_Left`, compute target pane; if a target view exists: take `paths = dirdiff._get_selected_paths(pane)`; `view.selectionModel().clearSelection()`; `target.setFocus()`; `target.selectionModel().clearSelection()`; if paths: `target.setCurrentIndex(QModelIndex(paths[0]))` then `select(QItemSelection(...), SelectionFlags.Select | Rows)` for each path (:640-642); **then call `dirdiff.on_treeview_cursor_changed()` directly** (the second `tree.emit("cursor-changed")` control-flow site, :643). `event.accept(); return` for BOTH keys **even when no hop happened** (pane 0 + Left) — matching the unconditional `return event.keyval in (Left, Right)` at :644. Note this deliberately suppresses QTreeView's native Left/Right collapse/expand, exactly as GTK's handler suppressed the native bindings. The migration plan's §8 lists these bindings as droppable; this WP overrides that: the pane-hop is user-visible functionality and is ported. All other keys → `super().keyPressEvent(event)`.
8. Row activation (:646-662): connect `view.activated(QModelIndex)`. Transliterate: `allrows = model.value_paths(index)`; `pane_ordering = ((0,1,2),(1,2,0),(2,1,0))`; first existing path wins; file → `self.create_diff.emit([r for r in allrows if r and os.path.isfile(r)])` (:657 — note `r and`: empty-row None paths after the T5.1 fix); dir → toggle `view.setExpanded(index, not view.isExpanded(index))` (:658-662; setExpanded routes through expand/collapse so the mirror fires).
9. Status line `on_treeview_cursor_changed(*args)` (:596-623): also connected to each `selectionModel().currentRowChanged` (in `_set_model`, per T5.3). Port `rwx` as a ternary comprehension (the `and/or` at :603 works but rewrite) and `nice()` verbatim including the `ngettext` table (:604-616; `deltat /= units` is float division on a float — identical in py3). **Rename the local `stat = os.stat(fname)` at :619** — it shadows the `stat` module (works in the original only because the module isn't used below; a landmine). Emit `self.status_changed.emit("")` on OSError, else the `"%s : %s"` format (:621-623). Preserve `nice()` returning None for absurd deltas (>~500 years) — do not "fix".
10. Context menu (:830-854): connect `customContextMenuRequested(point)` per view. Handler: `index = view.indexAt(point)`; if invalid → return (GTK's `except TypeError: pass` at :843-846 — no menu outside rows); `view.setFocus()`; if `len(selected) <= 1 and QApplication.keyboardModifiers() == Qt.KeyboardModifier.NoModifier`: `view.setCurrentIndex(index)` (the `event.state == 0` guard at :850); set DirCopyLeft/Right enabled per pane (:834-835); `self.popup_menu.exec(view.viewport().mapToGlobal(point))`. Unselect-other-panes on ANY press lives in `DirTreeView.mousePressEvent` → `on_pane_pressed(view)`: `for t in others_visible: t.selectionModel().clearSelection()` (:838-841 fires on every button, including clicks on empty space — `pressed` signal would miss those).

**TRAPS:**
- `dirdiff.py:643` and `:683` — `tree.emit("cursor-changed")` as control flow: MUST become direct calls to `on_treeview_cursor_changed()`; a missed one produces a stale status bar/toolbar with zero errors (explicitly flagged by the survey as manual-testing-only breakage).
- `dirdiff.py:544/:578/:742` — reverse-iteration over selections assumes GTK's sorted order; Qt does not sort. `_get_selected_paths` MUST sort by rowpath.
- `dirdiff.py:324/:331/:335` — `map()` result sliced (`objects[:self.num_panes]`): `TypeError: 'map' object is not subscriptable` on first scroll if transliterated.
- `dirdiff.py:644` — the handler swallows Left/Right unconditionally; forgetting this re-enables Qt's native collapse-on-Left and makes the hop unreachable at pane boundaries.
- `dirdiff.py:850/:853` — `event.state == 0` is a GTK modifier mask; the Qt analog is `keyboardModifiers() == NoModifier`, and the GTK return-value semantics (consume click only when unmodified) are handled for free by `customContextMenuRequested`.
- Focus-out during popup: without the `PopupFocusReason` guard, opening the context menu disables DirCopyLeft/Right/Delete before their `triggered` slots run → every popup action silently no-ops. This is the Qt re-expression of the handler_block dance (:672-675/:831-833).
- `selectionModel()` objects are replaced on `setModel` — all connections in this task that touch selection models must live in `_set_model` (T5.3), not `__init__`.

---

#### T5.8 — Operations: compare, open, copy, delete, hide, next_diff

**Old refs:** `meld/dirdiff.py:519-594`, `:703-708`, `:738-744`, `:1025-1042`.

**Build:**

1. `launch_comparison(it, pane, force=1)` (:519-525): `paths = [p for p in self.model.value_paths(it) if p and os.path.exists(p)]; self.create_diff.emit(paths)` — the original passes a lazy `filter` object to `emit` (:524); py3 would emit a one-shot iterator into the signal payload — **materialize the list**.
2. `launch_comparisons_on_selected()` (:527-535) over `_get_selected_paths`.
3. `copy_selected(direction)` (:537-569): assert direction in (-1, 1); pane from `_get_focused_pane()`; `sel = self._get_selected_paths(src_pane)` (already sorted); iterate `reversed(sel)`; for each `QPersistentModelIndex` p: `if not p.isValid(): continue`; `it = QModelIndex(p)`; `src/dst = model.value_path(it, src/dst_pane)`; keep the `if name is None: continue` guard (:549); file branch: `os.makedirs(dstdir, exist_ok=True)` + `misc.copy2` + `self.file_created(p, dst_pane)`; dir branch: overwrite confirm via `QMessageBox.question(self.widget, "Meld", _("'%s' exists.\nOverwrite?") % os.path.basename(dst), StandardButton.Ok | StandardButton.Cancel)` — Ok proceeds (`misc.copytree`) then `self.recursively_update(rowpath(QModelIndex(p)))`; `except (OSError, IOError) as e` → `QMessageBox.warning` with `_("Error copying '%s' to '%s'\n\n%s.") % (src, dst, e)` (:568-569).
4. `delete_selected()` (:571-594): same persistent-index reverse-iteration; file → `os.remove` + `file_deleted(p, pane)`; dir → confirm `_("'%s' is a directory.\nRemove recursively?") % basename`; on Ok `shutil.rmtree` + `recursively_update(rowpath(...))`; **`file_deleted(p, pane)` is called even when the user cancels** (:592 sits outside the Ok-branch) — preserve this quirk (it harmlessly re-checks existence and refreshes state); `except OSError as e` → `_("Error removing %s\n\n%s.") % (name, e)`.
5. `on_filter_hide_current_clicked` (:738-744): selected persistent indexes, iterate `reversed(sorted-by-rowpath)`, `self.model.removeRow(QModelIndex(p).row(), QModelIndex(p).parent())`. QPersistentModelIndex keeps later entries valid as earlier siblings vanish — this plus reverse order is the double protection replacing GTK's reverse-tuple discipline (:742-744).
6. DirOpen (:703-708): paths of selection → `self._open_files(files)` — MeldDoc method (melddoc.py:63-79); verify WP3 ported it (xdg-open/open dispatch); if the custom/gnome editor-command pref branch was descoped by WP3, fall back to `QDesktopServices.openUrl`.
7. `next_diff(direction)` (:1025-1039): `direction` is the app-wide neutral enum replacing `gtk.gdk.SCROLL_UP` (:1032) — import `Direction` from `meldq.doc` (created in WP3 T3.4; do not redefine). Start index: last of `_get_selected_paths(pane)` or the root row `(0,)` (:1030). Walk `model.inorder_search_up/down`; first row whose `get_state(it, pane)` not in `(STATE_NORMAL, STATE_EMPTY)` (:1034-1035): expand ancestors (`while parent valid: view.expand(parent)` — the `expand_to_path` replacement, :1037), `view.setCurrentIndex(cur)`, `view.scrollTo(cur)`.
8. `on_reload_activate` → `on_fileentry_activate(None)` (:1041-1042); wire to the shell's refresh action per the doc contract.

**TRAPS:**
- `dirdiff.py:524` — `filter(...)` object emitted through a signal: downstream `len()`/indexing in the shell's create-diff handler fails or (worse) the iterator is consumed once and re-read empty. Materialize.
- `dirdiff.py:537-594` + `:738-744` — mutation-while-iterating: rows are removed/`recursively_update`d (which deletes ALL children) while stored row addresses are held. GTK tuples survived only due to reverse ordering; a Qt port holding plain `QModelIndex` crashes or deletes the wrong rows the moment `recursively_update` fires mid-loop. `QPersistentModelIndex` + validity checks + reverse-sorted order, all three.
- `dirdiff.py:568/:593` — `except X, e` comma syntax (SyntaxError, loud); `IOError` is an alias of `OSError` in py3 — a single `except OSError` suffices.
- `dirdiff.py:592` — cancel-still-calls-`file_deleted` quirk: preserve; "fixing" it changes observable refresh behavior.
- `dirdiff.py:1030` — `(0,)` literal root path: goes through `index_for_rowpath`; the root row exists only after `set_locations` — guard `isValid()`.
- PEP 479 boundary: `next_diff` at the first/last non-normal row relies on the T5.1 generators returning cleanly; the old code crashed here in py3 (tree.py:138/:158) — AC2's boundary test covers it end-to-end.

---

#### T5.9 — Per-pane DiffMap overview

**Old refs:** `meld/dirdiff.py:886-984`, glade diffmap0/1 (width 20, button-press mask).

**Build:**

1. Check whether `meldq/diffmap.py` exists (a filediff WP may have landed it). If yes, adapt to its API; if not, create the generic contract widget:
   ```python
   class DiffMap(QWidget):
       def setup(self, scrollbar: QScrollBar,
                 chunk_fn: Callable[[], list[tuple[float, float, QColor]]]) -> None
       def paintEvent(self, event)   # fillRect per chunk + black outline drawRect
       def mousePressEvent(self, event)  # left button: click-to-scroll
   ```
   Chunks are `(start_fraction, end_fraction, color)` with fractions in [0,1] of widget height. Painting: `QPainter(self)`, background from palette, for each chunk `p.fillRect(x0, floor(h*f0), w-2*x0, ceil(h*f1)-floor(h*f0), color)` + `p.setPen(Qt.black); p.drawRect(...)` (x0=4 from :955). No GC cache — `area.meldgc` (:925-949) has no Qt equivalent or need. `update()` replaces `queue_draw` (:886-888).
2. Click-to-scroll (from :971-984): `fraction = event.position().y() / self.height()`; `sb = self._scrollbar`; `val = fraction * (sb.maximum() + sb.pageStep()) - sb.pageStep() / 2`; `sb.setValue(int(max(0, min(sb.maximum(), val))))`. This is the GTK math (`val = fraction*upper - page_size/2`, `upper = max + page`) with the hardcoded `size_of_arrow = 14` offsets (:952, :974, :978) **dropped** — Qt scrollbars (esp. macOS) have no steppers; fractions map to the full widget height. The 3.75-arrow fudge factor (:978) dies with it.
3. `DirDiff._diffmap_chunks(diffmapindex)` — transliterate :890-923: `treeindex = (0, self.num_panes-1)[diffmapindex]`; `traverse_states` generator over the model honoring `self.treeview[treeindex].isExpanded(index)` (replacing `treeview.row_expanded(path)` at :903), children queued depth-first exactly as :895-910 (yield state, then if expanded prepend children; final `yield None` end marker); chunk accumulation verbatim (:912-923, including `numlines = -1` start and skipping `chunks[0]`); state→color map from the meldgc table (:937-948): STATE_ERROR→`QColor("yellow")`, STATE_NEW→`QColor(prefs.color_delete_bg)`, STATE_MODIFIED/CONFLICT/REMOVED→`QColor(prefs.color_replace_bg)`, STATE_MISSING→`QColor("white")`, everything else → no chunk. Convert `(lastlines, state)` runs into `(start/numlines, end/numlines, color)` fractions.
4. Wire in `_set_model`/`set_num_panes`: `self.diffmap[0].setup(self.treeview[0].verticalScrollBar(), lambda: self._diffmap_chunks(0))`, `self.diffmap[1].setup(self.treeview[self.num_panes-1].verticalScrollBar(), ...)` — note diffmap 1 tracks the **last visible** pane (:892, :976), so re-setup on every pane-count change. `_update_diffmaps()` → `self.diffmap[0].update(); self.diffmap[1].update()` (:886-888) — called from expansion changes, `file_created/deleted`, and scan completion.

**TRAPS:**
- `dirdiff.py:928/:930` — `gdk.color_parse(self.prefs.color_delete_bg)`: 1.4 prefs store X11 color names (D9 flags e.g. `DarkSeaGreen1`) that `QColor(name)` does NOT parse — check `QColor.isValid()` and fall back to a hardcoded equivalent (`#c8e6c8`-ish for delete-bg, per WP3's prefs conversion table (T3.3); grep `meldq/util/prefs.py` first).
- `dirdiff.py:952-978` — the arrow-offset geometry: transliterating the `14`s misplaces every chunk and click on Qt; deleting them is the fix, not translating (`QStyle.pixelMetric(PM_ScrollBarExtent)` is only needed if pixel-parity with a stepper theme is demanded — it is not).
- `numlines` can be 0 for a root-only tree → division by zero in the fraction conversion; the original divides by `numlines` at :953 with the same latent risk (single-row tree) — guard `numlines <= 0` → empty chunk list.
- Chunk traversal must use `isExpanded` on the SAME view the diffmap mirrors; expansion is synced, but during the sync window they can differ for one event — harmless, but always read one view, never mix.
- `event.position()` (Qt6) not `event.pos()` for float precision; `event.button() == Qt.MouseButton.LeftButton` gate (:973).

---

#### T5.10 — Integration, doc lifecycle, smoke pass

**Old refs:** `meld/dirdiff.py:263-283` (activation refresh), melddoc.py:112-135 (lifecycle), the shell's new-comparison flow.

**Build:**

1. Register DirDiff with the shell's new-comparison dialog / CLI path: `meldq` invoked with two or three directory arguments must construct `DirDiff(prefs, n)` and call `set_locations(list_of_dirs)` (grep `meldq/main.py`/`meldq/app.py` for how FileDiff docs are constructed and mirror it).
2. Doc-activation hook (replacing :275-277): override `MeldDoc.on_container_switch_in_event` (WP3 T3.4, called from `_on_current_tab_changed`) to schedule `treeview_focussed.setFocus` and `on_treeview_cursor_changed` on the doc's scheduler so toolbar/status state is fresh.
3. `closed` signal / delete-event: DirDiff has no dirty state; closing needs no confirmation (melddoc.py:126-135 returned RESPONSE_OK unconditionally for dirdiff).
4. Connect `Preferences.changed` → `on_preference_changed`; verify `filters` (name filters) changes take effect on next refresh (1.4 only live-reloaded `regexes`, :316-318 — preserve exactly: name-filter pref changes require reopening the tab; do not add live reload).
5. Run the full manual smoke script (AC12) on Linux and macOS; fix paint/geometry fallout.
6. Ensure `tests/fixtures/dirdiff/` golden corpus committed: `same/` (identical pair), `basic/` (left/right with same.txt, mod.txt, only-left.txt, only-right.txt, subdir/nested.txt, emptydir/), `case/` (a.txt + A.txt on one side), `binary/` (PNG-ish bytes pair), `filtered/` (pair differing only in `$Id$` lines).

**TRAPS:**
- Tab-switch stale state is the classic silent failure mode of this port (survey risk list + plan §9.5): after T5.10, switching dirdiff→filediff→dirdiff must show correct toolbar enablement and status text — walk it manually, it cannot crash, only lie.
- Scheduler starvation: a dirdiff scan on a huge tree must keep the UI responsive (pump runs one `iteration()` per timer tick — verify no local loop drains the generator synchronously except in tests).

### Contracts consumed / provided

**Consumed (from WP2/WP3 — verify by grep before coding, adapt names only if the landed code differs):**
- `meldq.doc.MeldDoc(QObject)`: signals `label_changed(str)`, `status_changed(str)`, `create_diff(list)`, `closed()`; attributes `scheduler` (FifoScheduler), `prefs`, `num_panes`, `label_text`; methods `stop()`, `_open_files(list)`; the §2.5 `scheduler.paused` modal-pause convention (see T5.6).
- Doc/shell action contract: `doc_actions()`, `menu_contributions()`, `toolbar_contributions()` consumed by `DocActionManager` on `QTabWidget.currentChanged`.
- `meldq.engine.task.FifoScheduler`: `add_task(task, atfront=False)`, `tasks_pending()`, `iteration()`, `remove_all_tasks()`, `runnable_cb`; `app.SchedulerPump` timer semantics.
- `meldq.util.prefs.Preferences`: `changed(str)` signal; keys `regexes`, `filters`, `ignore_symlinks`, `color_delete_bg`, `color_replace_bg`.
- `meldq.widgets.historycombo.FileHistoryCombo`: path get/set, history prepend, Enter-activation signal.
- `meldq.util.misc`: `shorten_names`, `shell_to_regex`, `copy2`, `copytree`, `ListItem`, `all_equal` (Qt-free, enforced by test).
- `meldq.conf`: `_`, `ngettext`, resource path helper.
- Neutral `next_diff` direction enum: `meldq.doc.Direction` (provided by WP3 T3.4).

**Provided (other WPs code against these):**
- `meldq.widgets.treemodel`: `DiffTreeModel(QStandardItemModel)` with `ROLE_PATH/ROLE_STATE/ROLE_ISDIR` (normative) + `ROLE_NEWER` (additive, defaults False), methods `add_entries/add_empty/add_error/value_path/value_paths/set_state/get_state/set_newer/inorder_search_down/inorder_search_up` plus the WP4 T4.3 model methods `rowpath`/`index_for_rowpath`; STATE_* constants (canonical in this file per WP4 T4.2). **WP7 (vcview) builds on this file — no dirdiff-private behavior.**
- `meldq.diffmap.DiffMap` with the `setup(scrollbar, chunk_fn)` API (if this WP creates it; the filediff WP extends or replaces internals but keeps `setup`).
- `DirDiff.set_locations(list[str])`, `DirDiff.next_diff(direction)`, `DirDiff.on_reload_activate()` for the shell.

### Deleted (do-not-port)

- `EmblemCellRenderer` (dirdiff.py:125-155) — GObject custom renderer; replaced by pre-composited cached QPixmaps served via DecorationRole.
- `DirDiffTreeStore` + `COL_EMBLEM` + `TYPE_PIXBUF` (dirdiff.py:102-118) — interleaved-column machinery is a GTK artifact; roles replace it.
- All Pango markup + `gobject.markup_escape_text` (tree.py:48-62, :89/:97/:108) — role-based styling; no escaping needed for plain text.
- `on_container_switch_in/out_event`, `ui_file`, `custom_merge_id`, `filter_ui` merge lists (dirdiff.py:201, :263-283, :305-311) — replaced by the doc/shell contract.
- `_custom_popup_deactivated` + CustomFilterMenu toggle + `misc.position_menu_under_widget` + `make_tool_button_widget` (dirdiff.py:199, :254-261, :270-273) — `QToolButton` InstantPopup.
- Focus `handler_block/unblock` bookkeeping (`focus_in_events`/`focus_out_events`, dirdiff.py:213-219, :672-675, :831-833) — one `PopupFocusReason` check.
- `data/ui/dirdiff.glade` — glade-2 markup, unconvertible; layout rebuilt in code.
- `data/ui/dirdiff-ui.xml` — UIManager XML; survives only as the ordering spec quoted in T5.4.
- Linkmap drawing areas' dead `on_linkmap_scroll_event` wiring (dirdiff.glade:209-223/:280-294) — handler never existed; plain spacers.
- `GTK_CORNER_TOP_RIGHT` left-side scrollbar on pane 0 (dirdiff.glade:42-43) — D12 scope cut.
- `self.linediffs = [[], []]` (dirdiff.py:236) — dead; assigned once, never read.
- GC cache `area.meldgc` + `size_of_arrow = 14` stepper math (dirdiff.py:925-952, :974-978) — QPainter needs no GC; Qt scrollbars have no steppers.
- `action.props.is_important` loop (dirdiff.py:207-210) — toolbar-wide `ToolButtonTextBesideIcon`.
- `misc.struct` for stat signatures (misc.py:135-151) — namedtuple; py2 `__cmp__` is dead weight.
- `gtk.get_current_event_time()` plumbing (dirdiff.py:261, :836) — no Qt concept.

### Acceptance criteria

1. **Import purity:** `python -c "import meldq.dirdiff, meldq.widgets.treemodel"` succeeds in a process with no QApplication and creates no QPixmap/QIcon at import (assert via `QPixmap` monkeypatch in `tests/test_import_purity.py` or simply that the import does not warn/crash headless: run with `QT_QPA_PLATFORM=offscreen` unset).
2. **Tree model + traversal:** `python -m pytest tests/test_treemodel.py -q` green. Must include: rowpath/index_for_rowpath round-trip on a 3-level tree; `inorder_search_down` from root visits all rows in documented order and **terminates without RuntimeError at the last row** (PEP 479 regression, tree.py:138/:158 — same for `_up` at the first row); `value_path` on an `add_empty` row returns `None` (tree.py:88 regression); `data()` returns bold+`#008800` foreground for STATE_NEW and strikethrough font for STATE_MISSING.
3. **_files_same:** `python -m pytest tests/test_files_same.py -q` green (cases enumerated in T5.2, including the invalid-UTF-8 no-exception case — dirdiff.py:83 regression — and the filter-equal → 2 case).
4. **Scan populates the model** (dirdiff.py:500-501 regression): `python -m pytest tests/test_dirdiff_scan.py -q` green. With the `basic/` fixture and the scheduler drained via `while doc.scheduler.tasks_pending(): doc.scheduler.iteration()`, the model contains rows for every fixture entry with states: same.txt→STATE_NORMAL, mod.txt→STATE_MODIFIED, only-left.txt→STATE_NEW+STATE_MISSING pair, emptydir child→STATE_EMPTY placeholder; parent dir rows with differences are expanded in all visible views.
5. **`python -O -m pytest tests/test_dirdiff_scan.py -q`** also green, and the case-collision test (files `a.txt`+`A.txt`, `ignore_case=True`, `QMessageBox.warning` monkeypatched to record) reports exactly one collision message containing `hidden by` under both `-O` and normal runs (dirdiff.py:427-436 regression), and `scheduler.paused` is set around it (assert via a monkeypatched QMessageBox that checks the flag; dirdiff.py:439 / §2.5 contract).
6. **Text-filter compilation on py3.11** (dirdiff.py:249 regression): a test sets `prefs.regexes` to an active filter line and asserts `update_regexes` produces a pattern with MULTILINE flag active and raises no `re.error`.
7. **Operations:** `python -m pytest tests/test_dirdiff_ops.py -q` green: copy-right creates the file on disk and flips the row to STATE_NORMAL; delete with two selected sibling rows (dialogs monkeypatched to Ok) removes both correct rows from disk AND model (mutation-while-iterating regression, dirdiff.py:578/:744); hide-selected removes rows from the model only and `refresh()` restores them; `next_diff(Direction.DOWN)` from the root lands the cursor on the first non-NORMAL row and at the tree end returns without exception; `create_diff` emission payload is a `list`, not a filter object (dirdiff.py:524 regression).
8. **Sync:** `python -m pytest tests/test_dirdiff_sync.py -q` green: expanding a row in view 0 expands it in views 1/2; setting view0's vertical scrollbar propagates the value; `qtbot.keyClick(view0, Qt.Key.Key_Right)` moves focus to view 1, transfers the selection, and `status_changed` fires with a non-empty `rwx :` string (dirdiff.py:643 direct-call regression); focus on pane 0 leaves DirCopyLeft disabled and DirCopyRight enabled.
9. **DiffMap:** test builds a model with a MODIFIED run, asserts `_diffmap_chunks(0)` yields one chunk with `color_replace_bg`-derived color and correct fractions; `qtbot.mouseClick` at 50% height sets the scrollbar to approximately mid-range (±pageStep/2).
10. **Pane-count switching** (dirdiff.py:863/:866 regression): a test calls `set_num_panes(2)` then `set_num_panes(3)` and asserts widget visibility flags for views/fileentries/diffmaps/spacers match the slicing spec in T5.3, and that after each switch the new model's `selectionModel().currentRowChanged` is connected (spy on `on_treeview_cursor_changed` after programmatic `setCurrentIndex`).
11. **Qt-free util check:** the WP0-provided purity test that `meldq/util/misc.py` imports no Qt still passes: `python -m pytest tests/test_purity.py -q`.
12. **Manual smoke (Linux and macOS):** `meldq <fixture>/basic/left <fixture>/basic/right` — observe: three… two synced trees with colored/bold state text and file/folder icons, newer-emblem on the newer mod.txt, status bar shows `rwx` string when a row is selected, toolbar shows Compare/Left/Right/Delete/Hide/Case/Same/New/Modified/Filters in order, unchecking Same hides same.txt after refresh, right-click shows Compare/Left/Right/Open/Delete popup and its actions work, double-clicking mod.txt emits create_diff (opens a filediff tab if WP6 landed, else logged by the shell), Left/Right arrows hop panes, clicking the overview strip scrolls, and switching tabs away and back preserves toolbar enablement and status.

### Estimated effort

**11 person-days** (range 9–14): T5.1 ≈ 2 pd, T5.2 ≈ 1 pd, T5.3 ≈ 1.5 pd, T5.4 ≈ 1 pd, T5.5 ≈ 1 pd, T5.6 ≈ 1.5 pd, T5.7 ≈ 1.5 pd, T5.8 ≈ 1 pd, T5.9 ≈ 1 pd, T5.10 ≈ 0.5 pd — consistent with the survey's 8–14 pd band; T5.1's cost is shared with WP7 (vcview).

---

## WP6 — File comparison (meldq/filediff.py, filemerge.py, linkmap.py, diffmap.py + editor completion)

### Goal

Port Meld's 1/2/3-pane text comparison — the most GTK-entangled subsystem — to PyQt6: complete `DiffTextEdit` (chunk-background painting, geometry layer, inline ExtraSelections), build `FileDiff` with the full load/diff/edit/merge/save pipeline, the `LinkMap` bezier connector widget, the `DiffMap` overview bar, and `FileMerge` on top. The old `meld/filediff.py` (1502 loc), `meld/filemerge.py` (136 loc) and `meld/diffmap.py` (151 loc) are the behavioral spec; every deviation is called out explicitly below.

### Dependencies

- **WP0** (scaffolding: `meldq/__init__.py`, `meldq/conf.py` with `_`, `pyproject.toml`, `meldq/resources/`).
- **WP2** (engine: `meldq/engine/{matchers,diffutil,merge,undo,task}.py` — `Differ` with `diffs_changed`, `AutoMergeDiffer`, `Merger`, the REBUILT `UndoSequence` listening to `QTextDocument.undoCommandAdded`, `FifoScheduler` with `runnable_cb`).
- **WP3** (shell + doc base: `meldq/app.py` `MeldWindow`/`DocActionManager`/`SchedulerPump`, `meldq/doc.py` `MeldDoc(QObject)` with the 4 contract signals, tab lifecycle hooks, scheduler-pause convention).
- **WP3 + WP2** (util: `meldq/util/prefs.py` `Preferences(QObject)` with `changed = pyqtSignal(str)` and 1.4 key names; `meldq/util/misc.py` pure helpers incl. `shorten_names`, `ListItem`).
- **WP4** (shared widgets: `meldq/widgets/msgarea.py` `MsgArea`/`MsgAreaController`, `meldq/widgets/historycombo.py` `FileHistoryCombo`, `meldq/widgets/findbar.py` `FindBar`, and the *stub* of `meldq/widgets/editor.py` if WP4 created one — this WP completes it).

### Old-code map

| Old file:lines | What it does | New home |
|---|---|---|
| filediff.py:41-72 | `CachedSequenceMatcher` LRU diff cache | `meldq/filediff.py` `CachedSequenceMatcher` (py3 sort fix) |
| filediff.py:80 | `MASK_SHIFT, MASK_CTRL` | `meldq/filediff.py` module constants (values kept: 1, 2) |
| filediff.py:82-90 | `get_iter_at_line_or_eof`, `insert_with_tags_by_name` | `meldq/filediff.py` `position_at_line_or_eof(doc, line)`, `insert_text_at_line(doc, line, text)` |
| filediff.py:92-97 | `CursorDetails` | `meldq/filediff.py` verbatim (rename slot `next` → `next_chunk`, `prev` → `prev_chunk`) |
| filediff.py:100-206 | `FileDiff.__init__`: glade load, widget lists, tags, colors, actions | `meldq/filediff.py` `FileDiff(MeldDoc)` — code-built `QGridLayout`, QActions |
| filediff.py:208-215, 374-378 | focus/tab-switch handling | `FileDiff.on_container_switch_in_event()`, editor `focus_changed` wiring |
| filediff.py:217-224, 419-438 | regex text filters | `_update_regexes`, `_filter_text` near-verbatim |
| filediff.py:226-244 | buffer handler connect/disconnect | `_connect_buffer_handlers`/`_disconnect_buffer_handlers` over `contentsChange` |
| filediff.py:246-312 | cursor status, chunk sensitivity | `on_cursor_position_changed`, `_on_current_diff_changed` |
| filediff.py:314-372 | push/pull/delete/merge-all commands | same method names, QTextCursor edits |
| filediff.py:380-449 | re-diff on edit (`_after_text_modified`, after-insert/delete) | `_after_text_modified` + `_on_contents_change` blockCount-delta algorithm |
| filediff.py:392-417 | `FakeText`/`FakeTextArray` lazy buffer-line views | `FakeText.__getitem__` with slice support |
| filediff.py:451-471 | `load_font`, pixels_per_line, action pixbufs | `load_font` on `QFontMetricsF` + PNG pixmaps |
| filediff.py:473-503 | preference change dispatch | `on_preference_changed(key)` on `Preferences.changed` |
| filediff.py:505-528 | keymask press/release tracking | **DELETED** — `QApplication.keyboardModifiers()` polling |
| filediff.py:530-561 + filediff.glade:305-473 | close/save-selected dialog | `meldq/filediff.py` `CloseDialog(QDialog)` |
| filediff.py:566-582, 1477-1502 | undo capture, `BufferAction`s | **DELETED** — WP2 `UndoSequence` on `undoCommandAdded`; only `begin_group`/`end_group`/`checkpoint` calls remain here |
| filediff.py:584-585 | checkpointed → modified flag | `on_undo_checkpointed` |
| filediff.py:591-624 | open-selected, selected text, find activations | same names; findbar wiring |
| filediff.py:626-648 | size-allocate redraw, button-3 popup, toggle-overwrite | resize hook → `LinkMap.update()`; `customContextMenuRequested`; `Qt.Key_Insert` handling |
| filediff.py:655-704 | labels, `set_files` | `set_labels`, `recompute_label`, `set_files` |
| filediff.py:706-796 | `_load_files` encoding cascade | rewritten on `io` + `codecs.getincrementaldecoder` |
| filediff.py:798-826 | `_diff_files`, `_set_files_internal` | same names (map/`.next` fixes) |
| filediff.py:828-864 | merge sensitivity, "Files are identical" banners | `_set_merge_action_sensitivity`, `on_diffs_changed` |
| filediff.py:866-927 | `_update_highlighting` tags/marks | ExtraSelections rebuild generator |
| filediff.py:929-969 | textview expose chunk painting | `meldq/widgets/editor.py` `DiffTextEdit.paintEvent` |
| filediff.py:971-1045 | save-as chooser, `_save_text_to_filename`, `save_file` | `QFileDialog` + newline/encoding port (+ UTF-8 fallback bugfix) |
| filediff.py:1047-1076 + glade:474-586 | patch dialog | `PatchDialog(QDialog)` |
| filediff.py:1078-1129 | modified/writable flags, save-all, reload/refresh | same names |
| filediff.py:1131-1137 | `queue_draw` fan-out | `_queue_draw` |
| filediff.py:1142-1206 | `_sync_hscroll`, `_sync_vscroll` | same names, line-unit math |
| filediff.py:1208-1231 | `set_num_panes` show/hide + diffmap setup | same name, for-loops |
| filediff.py:1233-1241 | `_line_to_pixel`/`_pixel_to_line` | `DiffTextEdit.line_ypos`/`line_at_ypos`/`lines_visible` |
| filediff.py:1243-1267 | `_find_next_chunk`, `next_diff` | same names + `Direction` enum |
| filediff.py:1269-1291 | `paint_pixbuf_at`, `_linkmap_draw_icon` | `FileDiff._linkmap_draw_icon(painter, ...)` (called by LinkMap) |
| filediff.py:1296-1348 | linkmap expose beziers | `meldq/linkmap.py` `LinkMap.paintEvent` |
| filediff.py:1350-1426 | linkmap scroll/press/release, `_linkmap_process_event` | `LinkMap.wheelEvent/mousePressEvent/mouseReleaseEvent` + `FileDiff._linkmap_process_event` |
| filediff.py:1428-1458 | `copy_chunk`/`replace_chunk`/`delete_chunk` | same names, QTextCursor |
| filediff.py:1466-1474 | `MeldBufferData` | verbatim |
| filemerge.py:25-136 | `FileMerge` | `meldq/filemerge.py` |
| diffmap.py:22-151 | `DiffMap` DrawingArea | `meldq/diffmap.py` `DiffMap(QWidget)` |
| data/ui/filediff.glade:13-301 | 2×7 table layout, per-widget signals | code-built `QGridLayout` in `FileDiff.__init__` |
| data/ui/filediff-ui.xml | Changes-menu / popup layout | `menu_contributions()` / context-menu builder |
| data/icons/button_{apply0,apply1,copy0,copy1,delete}.xpm | linkmap action icons | `meldq/resources/icons/button_*.png` |

### Tasks

---

#### T6.1 — Complete `DiffTextEdit` (`meldq/widgets/editor.py`): geometry layer, chunk painting, key policy

**Old refs:** filediff.py:929-969 (expose painting), :1233-1241 (`_line_to_pixel`/`_pixel_to_line`), :123-126 (undo binding removal), :127-132 (view setup), :451-463 (font/tabs), :641-648 (overwrite).

Build `class DiffTextEdit(QPlainTextEdit)` (create the file if WP4 left only a stub; keep any WP4 API intact):

```python
class DiffTextEdit(QPlainTextEdit):
    focus_changed = pyqtSignal(bool)          # emitted from focusInEvent/focusOutEvent

    def __init__(self, parent: QWidget | None = None) -> None: ...
    # --- geometry layer (replaces filediff.py:1233-1241 and get_line_yrange/get_line_at_y uses) ---
    def line_height(self) -> float: ...
    def line_ypos(self, line: int) -> float: ...
    def line_at_ypos(self, y: int) -> int: ...
    def first_visible_line_fraction(self) -> float: ...
    def lines_visible(self) -> tuple[int, int]: ...
    # --- painting hooks, set by FileDiff ---
    chunk_fn: Callable[[tuple[int, int]], Iterable] | None          # bounds -> Differ.single_changes(pane, bounds)
    is_current_chunk_fn: Callable[[int], bool] | None               # first line of chunk -> is it the cursor chunk
    focus_line_fn: Callable[[], int | None] | None                  # cursor line for the yellow bar
    fill_colors: dict[str, QColor]; line_colors: dict[str, QColor]
```

Setup in `__init__`: `self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)` — **deliberate deviation**: `prefs.edit_wrap_lines` (filediff.py:131, :495-497) is ignored in the first Qt version; all geometry below assumes uniform block height. Record the deviation in a module docstring. `setMouseTracking` not needed here; `setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)` (popup built by FileDiff, T6.11).

**Geometry formulas (exact):**

```python
def line_height(self) -> float:
    return self.blockBoundingRect(self.document().firstBlock()).height()

def line_ypos(self, line: int) -> float:
    """Viewport y of the top edge of `line` (0-based); line >= blockCount()
    (the EOF sentinel) returns bottom of last block minus 1, mirroring
    filediff.py:1236-1237 (`return y + h - 1`)."""
    doc = self.document()
    if line >= doc.blockCount():
        g = self.blockBoundingGeometry(doc.lastBlock()).translated(self.contentOffset())
        return g.bottom() - 1.0
    block = doc.findBlockByNumber(line)
    return self.blockBoundingGeometry(block).translated(self.contentOffset()).top()

def line_at_ypos(self, y: int) -> int:            # replaces _pixel_to_line (filediff.py:1240-1241)
    return self.cursorForPosition(QPoint(0, y)).blockNumber()

def first_visible_line_fraction(self) -> float:   # feeds sync-scroll (T6.5)
    block = self.firstVisibleBlock()
    g = self.blockBoundingGeometry(block).translated(self.contentOffset())
    h = self.blockBoundingRect(block).height()
    return block.blockNumber() + (-g.top() / h if h > 0 else 0.0)

def lines_visible(self) -> tuple[int, int]:
    first = self.firstVisibleBlock().blockNumber()
    last = self.cursorForPosition(QPoint(0, self.viewport().height() - 1)).blockNumber()
    return first, last + 1
```

Note: `blockBoundingGeometry(...).translated(contentOffset())` is the canonical QPlainTextEdit recipe (used by Qt's line-number example); it is valid for any block but costs a walk from the visible block — only call it for lines at or near the viewport (all call sites in this WP are viewport-bounded, matching the GTK code's clipping to `visible`).

**paintEvent** (port of filediff.py:929-969; painting happens on the viewport BEFORE `super().paintEvent()` per editor contract):

```python
def paintEvent(self, event: QPaintEvent) -> None:
    if self.chunk_fn is not None:
        painter = QPainter(self.viewport())
        painter.setClipRect(event.rect())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        bounds = (self.line_at_ypos(event.rect().top()),
                  self.line_at_ypos(event.rect().bottom() + 1))          # :940-941
        width = self.viewport().width()
        for change in self.chunk_fn(bounds):
            ypos0 = self.line_ypos(change[1])                            # :950
            ypos1 = self.line_ypos(change[2])                            # :951
            rect = QRectF(-0.5, ypos0 - 0.5, width + 1, ypos1 - ypos0)   # :953
            if change[1] != change[2]:                                    # :954
                painter.fillRect(rect, self.fill_colors[change[0]])
                if self.is_current_chunk_fn(change[1]):                   # :957
                    painter.fillRect(rect, QColor(255, 255, 255, 128))    # :958 rgba(1,1,1,0.5)
            pen = QPen(self.line_colors[change[0]]); pen.setWidthF(1.0)
            painter.setPen(pen)
            if ypos1 == ypos0:
                painter.drawLine(QPointF(-0.5, ypos0 - 0.5), QPointF(width + 0.5, ypos0 - 0.5))
            else:
                painter.drawRect(rect)                                    # :961-962 stroke
        if self.hasFocus() and self.focus_line_fn is not None:            # :964-969
            line = self.focus_line_fn()
            if line is not None:
                y = self.line_ypos(min(line, self.document().blockCount() - 1))
                painter.fillRect(QRectF(0, y, width, self.line_height()),
                                 QColor(255, 255, 0, 64))                 # rgba(1,1,0,.25)
        painter.end()
    super().paintEvent(event)
```

FileDiff sets `chunk_fn = None` when `num_panes == 1` (mirrors :930-931).

**Key policy** (replaces `gtk.binding_entry_remove` at :123-126): undo is window-level through `UndoSequence`, so the editor must both (a) not run its own document undo and (b) not block the window-level `QAction` shortcut. QPlainTextEdit *accepts* `ShortcutOverride` for editing keys, which would starve the window shortcut — override `event()`:

```python
def event(self, e: QEvent) -> bool:
    if e.type() == QEvent.Type.ShortcutOverride and (
            e.matches(QKeySequence.StandardKey.Undo) or
            e.matches(QKeySequence.StandardKey.Redo) or
            (e.modifiers() & Qt.KeyboardModifier.ControlModifier and e.key() == Qt.Key.Key_Y)):
        e.ignore(); return False
    return super().event(e)

def keyPressEvent(self, e: QKeyEvent) -> None:
    if e.matches(QKeySequence.StandardKey.Undo) or e.matches(QKeySequence.StandardKey.Redo) \
            or (e.modifiers() & Qt.KeyboardModifier.ControlModifier and e.key() == Qt.Key.Key_Y):
        e.ignore(); return                                   # swallowed; window QAction fires
    if e.key() == Qt.Key.Key_Insert and self.insert_toggle_cb:
        self.insert_toggle_cb(); return                      # replaces toggle-overwrite dance :641-648
    if e.key() == Qt.Key.Key_Tab and self.spaces_instead_of_tabs:
        col = self.textCursor().positionInBlock()
        self.insertPlainText(" " * (self.tab_size - col % self.tab_size)); return
    super().keyPressEvent(e)
```

`insert_toggle_cb` is set by FileDiff to a method that flips `overwriteMode()` on ALL panes and refreshes the status text. Do NOT call `document().setUndoRedoEnabled(False)` — the WP2 UndoSequence *requires* the native undo stack.

**Font/tabs API** (port of :451-463, :473-481): `def set_font_and_tabs(self, font: QFont, tab_size: int) -> None` — `setFont(font)`; `self.setTabStopDistance(tab_size * QFontMetricsF(font).horizontalAdvance(' '))`.

**Tests** (`tests/test_editor_geometry.py`, pytest-qt): with 200 lines of text and a fixed 400×300 widget: `line_ypos(0) == 0` after scroll-to-top; `line_ypos(n+1) - line_ypos(n) == line_height()` for visible n; `line_at_ypos(int(line_ypos(k)) + 1) == k`; `lines_visible()` spans exactly the shown lines; `line_ypos(blockCount())` equals bottom of last block − 1; Ctrl+Z with `qtbot.keyClick` does NOT modify the document after typing.

**TRAPS:**
- filediff.py:1236-1237 — the EOF branch of `_line_to_pixel` returns `y + h - 1`; chunk math depends on EOF-line sentinels (chunks routinely carry `end == line_count`). Reproduce exactly or linkmap/chunk rects at file end are off by one line.
- filediff.py:940-941 — bounds use `y + area.height + 1`; keep the `+1` or the last partially-visible chunk row loses its bottom border.
- filediff.py:953 — rectangle x starts at −0.5 and width+1 so vertical borders are off-canvas; only horizontal boundary lines show. Keep coordinates and antialiasing OFF, else 1-px lines blur.
- filediff.py:123-126 — the GTK code *removed key bindings*; the Qt equivalent must handle BOTH `ShortcutOverride` and `keyPressEvent` — handling only `keyPressEvent` silently leaves window Ctrl+Z dead (shortcut never fires because the editor accepts the override).
- filediff.py:455 — `(ascent+descent)/1024`: py2 floor-div int; irrelevant now (use `QFontMetricsF.height()`), but do NOT port the `/1024` Pango scaling.
- filediff.glade:88/164/202 — `move_cursor` → `on_textview_move_cursor` is a DEAD handler (no such method in filediff.py) — do not port anything for it.

---

#### T6.2 — `FileDiff` skeleton: class, layout grid, pane lists, labels, prefs dispatch (`meldq/filediff.py`)

**Old refs:** filediff.py:100-206 (`__init__`), :114-119 (glade + `map_widgets_into_lists`), :151-176 (tags + color tables), :208-215, :530-532 (`_get_pane_label`), :655-682 (`set_labels`/`recompute_label`), :473-503 (`on_preference_changed`), :1131-1137 (`queue_draw`), :1208-1231 (`set_num_panes`), :106-112 (constants), glade table attachments (filediff.glade:13-301).

```python
class FileDiff(MeldDoc):
    differ = diffutil.Differ                      # class attr, overridden by FileMerge (filediff.py:104)
    # current_diff_changed() and next_diff_changed(bool, bool) are INHERITED from MeldDoc
    # (WP3 T3.4) — do NOT re-declare them here (subclass pyqtSignal shadowing hazard);
    # emit via self.current_diff_changed.emit() etc. (replaces emit(...) at :268/:270)
    MSG_SAME = 0                                  # :112 — (MSG_SAME,) = range(1)

    def __init__(self, prefs: Preferences, num_panes: int) -> None: ...
```

`MeldDoc.__init__` (WP3) provides `self.undosequence`, `self.scheduler`, `self.prefs`, `self.num_panes = 0`, `self.label_text`. FileDiff builds `self.widget = QWidget()` with a `QVBoxLayout` containing a `QGridLayout` plus the `FindBar` at the bottom (non-expanding), mirroring filediff.glade:

- Grid columns (glade attach coords): **col0** diffmap0, **col1** pane0, **col2** linkmap0, **col3** pane1, **col4** linkmap1, **col5** pane2, **col6** diffmap1. Column stretch 1 for panes, 0 for the rest.
- **Row 0**: `statusimage0` (QLabel, col0), `fileentry0` (`FileHistoryCombo`, col1), `statusimage1` (col2), `fileentry1` (col3), `statusimage2` (col4), `fileentry2` (col5).
- **Row 1**: per-pane `QVBoxLayout` in cols 1/3/5: `MsgAreaController` (`msgarea_mgr[i]`) above `DiffTextEdit` (`textview[i]`); `LinkMap` in cols 2/4 (`setFixedWidth(50)`, glade width_request filediff.glade:236); `DiffMap` in cols 0/6.

Build explicit Python lists replacing `map_widgets_into_lists` (:119): `self.textview: list[DiffTextEdit]` (3), `self.textbuffer = [tv.document() for tv in self.textview]`, `self.fileentry` (3), `self.diffmap` (2), `self.linkmap` (2), `self.statusimage` (3), `self.msgarea_mgr` (3), `self.vbox` (3 QWidget containers). `self.bufferdata = [MeldBufferData() for _ in self.textbuffer]` (:140).

Port `MeldBufferData` verbatim (:1466-1474; keep `__slots__`, use `False`/`True` for the 0/1 flags).

Colors (:151-176): build `self.fill_colors`/`self.line_colors` as `dict[str, QColor]` from prefs (`color_delete_bg` for both "insert" and "delete" — yes, both, see :167-168; "conflict" from `color_conflict_bg`, "replace" from `color_replace_bg`); `line_colors = {k: v.darker(125) for ...}` replaces the ×0.8 multiply (:172). Inline format: `self.inline_format = QTextCharFormat()` with `color_inline_bg`/`color_inline_fg` (replaces the "inline line" tag :160-161). The other four tags (:152-159) are NOT ported — chunk coloring is painted from the differ (see Deleted).

Register documents with undo (WP2 contract): `for doc in self.textbuffer: self.undosequence.register_document(doc)` (or the WP2-provided registration call — adapt to its exact name; it must be called once per pane document). Connect `self.undosequence.checkpointed.connect(self.on_undo_checkpointed)` (:206) and `self.linediffer = self.differ()`; `self.linediffer.ignore_blanks = self.prefs.ignore_blank_lines`; `self.linediffer.diffs_changed.connect(self.on_diffs_changed)` (:205).

Wire per-editor: `cursorPositionChanged` → `self.on_cursor_position_changed` (pane-index via `functools.partial`), `focus_changed` → focus bookkeeping + `self.on_current_diff_changed()` (:202-204) + `self.findbar.set_text_edit(view)` equivalent (:376), scrollbars (T6.5). Set editor paint hooks: `chunk_fn = partial(self._chunk_fn_for_pane, i)` (returns `self.linediffer.single_changes(i, bounds)` when `num_panes > 1` else `()`), `is_current_chunk_fn`, `focus_line_fn = lambda: self.cursor.line`.

`load_font()` (:451-471): `font = self.prefs.get_current_font()` — already a `QFont` (WP3 T3.2); no Pango-string parsing and no `get_current_font_qt` variant. `self.pixels_per_line = round(QFontMetricsF(font).height())`; apply `set_font_and_tabs(font, self.prefs.tab_size)` per pane; load the five action pixmaps: `self.pixmap_apply0/apply1/delete/copy0/copy1 = QPixmap(icon_path).scaledToHeight(self.pixels_per_line, Qt.TransformationMode.SmoothTransformation)`; `for lm in self.linkmap: lm.update()`. The `gobject.idle_add(load_font)` hack (:197) is dropped (GTK Bug 316730 workaround).

One-off conversion (commit the PNGs, not the script): for each of `data/icons/button_{apply0,apply1,copy0,copy1,delete}.xpm`, run `QPixmap(xpm).save("meldq/resources/icons/button_<name>.png")` (Qt6 still reads XPM) — icon set: **apply0** (apply left→right), **apply1** (apply right→left), **copy0** (copy-up variant left), **copy1** (copy-up variant right), **delete**.

`on_preference_changed(self, key: str)` connected to `prefs.changed` — dispatch table from :473-503: `tab_size` → re-apply tabs; `use_custom_font`/`custom_font` → `load_font()`; `regexes` → `_update_regexes()`; `spaces_instead_of_tabs` → set editor flag; `ignore_blank_lines` → set differ flag + `self.set_files([None] * self.num_panes)` refresh (:501-503). `show_line_numbers`, `edit_wrap_lines`, `use_syntax_highlighting` are accepted but no-ops (see Deleted).

`set_num_panes(self, n)` (:1208-1231): plain `for` loops over show/hide lists (`setVisible`); QGridLayout collapses hidden columns automatically. Then re-`setup_editor` both diffmaps with `(w, i) in zip(self.diffmap, (0, self.num_panes - 1))` and `chunk_change_fn(i)` closures (:1221-1225 — note the closure-over-loop-variable bug the old code already avoided with `chunk_change_fn`; keep that pattern), re-show statusimages for modified panes, `self._queue_draw()`, `self.recompute_label()`.

`recompute_label()` (:660-682): `shortnames = misc.shorten_names(*filenames)`; append `"*"` for modified; statusimage icons: modified+writable → `QIcon.fromTheme("document-save", style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))`; modified+not-writable → `"document-save-as"` (same fallback); not-writable → `"emblem-readonly"` (fallback `SP_MessageBoxWarning`); as 16-px pixmap on the QLabel; `self.label_text = " : ".join(shortnames)`; `self.label_changed()` → emits `label_changed(str)`. Pane label helper `_get_pane_label` (:530-532) uses `_("<unnamed>")` — exact msgid.

`_queue_draw()` (:1131-1137): `viewport().update()` on each textview, `update()` on linkmaps `[:num_panes-1]` and both diffmaps.

All user-visible strings via `from meldq.conf import _` with the EXACT 1.4 msgids (e.g. `_("<unnamed>")`, `_("untitled")` comes from doc base). GTK mnemonics: add helper `gtk_mnemonic_to_qt(s: str) -> str` in `meldq/util/misc.py` (if absent): `s.replace('&', '&&').replace('_', '&', 1)` — always translate FIRST, then convert: `gtk_mnemonic_to_qt(_("Hi_de"))`.

**Tests** (`tests/test_filediff_widget.py`): construct `FileDiff(prefs, 2)` under pytest-qt; assert `widget` hierarchy contains 3 DiffTextEdit / 2 LinkMap / 2 DiffMap; `set_num_panes(3)` shows pane 2/linkmap1, `set_num_panes(2)` hides them (`isVisibleTo(doc.widget)`); `label_changed` emitted with `"a : b"` after `set_labels(["a","b"])` + `recompute_label()`.

**TRAPS:**
- filediff.py:1214/:1219 — `map(lambda x: x.show(), toshow)` / `.hide()` are py2 side-effect maps: in py3 the lazy map object is discarded and **panes silently never show/hide** (no exception). Must be `for` loops. This is the highest-value silent breakage in the file.
- filediff.py:100 — `FileDiff(melddoc.MeldDoc, gnomeglade.Component)` double inheritance is ILLEGAL in PyQt (single QObject base) — the new class is `FileDiff(MeldDoc)` with `self.widget` composition; never subclass QWidget here.
- filediff.py:167-168 — "insert" and "delete" both use `color_delete_bg`; do not "fix" this to `color_edited_bg`.
- filediff.py:172 — `darken = x*0.8` ↔ `QColor.darker(125)` (125 = 1/0.8 · 100).
- filediff.py:139 — `textbuffer[i]` must be `textview[i].document()` — do not create standalone QTextDocuments and `setDocument` later without re-registering undo and contentsChange handlers.
- filediff.py:119 — glade name-coupling is gone; any typo in list construction fails silently at attribute-use distance — build all seven lists in one place and assert lengths in `__init__`.
- preferences.py:242+ — pref color values may be X11 names (e.g. `DarkSeaGreen1`) that `QColor(name)` cannot parse; WP3 guarantees `#rrggbb` after migration — assert `QColor(...).isValid()` at load and fall back to sane defaults rather than painting black.

---

#### T6.3 — File loading: encoding cascade, binary sniff, newline detection (`_load_files`, `set_files`)

**Old refs:** filediff.py:684-704 (`set_files`), :706-796 (`_load_files`), :717-725 (dismissable msgarea helper), :788-793 (writable/encoding/newlines capture).

`set_files(self, files)` ports near-verbatim (:684-704): clear buffers (`doc.clear()` — but see undo note below), `fileentry[i].set_filename(absfile)` + `prepend_history(absfile)` (WP4 API), fresh `MeldBufferData(absfile)` preserving label when filename unchanged (:696-698), `msgarea_mgr[i].clear()`, `recompute_label()`, focus pane `int(len(files) >= 2)` (:702 — py2 bool-as-index; make the `int()` explicit), `_connect_buffer_handlers()`, then `self.scheduler.add_task(self._set_files_internal(files).__next__)` (:704 — `.next` → `.__next__`).

Rewrite `_load_files(self, files, textbuffers, panetext)` as a generator with identical yield strings (exact msgids: `_("[%s] Set num panes")`, `_("[%s] Opening files")`, `_("[%s] Reading files")`):

```python
try_codecs = self.prefs.text_codecs.split() or ['utf_8', 'utf_16']   # :713
```

Per file, a task struct (`types.SimpleNamespace`) holding: `filename`, `pane`, `buf` (QTextDocument), `codecs_left: list[str]`, `fileobj` (binary, `open(f, 'rb')`), `decoder = codecs.getincrementaldecoder(codecs_left[0])()`, `text: list[str]`, `was_cr: bool`, `newline_kinds: set[str]`. The read loop (replaces :746-794):

1. `raw = t.fileobj.read(4096)`; decode with `t.decoder.decode(raw, final=(len(raw) == 0))` — the incremental decoder holds split multibyte sequences across chunks (this replaces `codecs.open(f, "rU", ...)`, removed-in-3.11 `'U'` mode, :732/:759).
2. On `UnicodeDecodeError` (was `ValueError`, :756): pop codec; if any left, reopen the file from byte 0 with a fresh decoder, clear `t.buf` and `t.text` (:757-761); else log via `logging` (not `print`, :763) and show the msgarea error `_("Could not read file")` / `_("%s is not in encodings: %s") % (t.filename, try_codecs)` (:766-768).
3. Binary sniff on the DECODED text: `if "\x00" in nextbit:` → msgarea `_("%s appears to be a binary file.") % t.filename`, remove task (:750-755). Decoded-text sniff (not raw bytes) is deliberate: raw NULs are normal in UTF-16.
4. Newlines (replaces `'rU'` + `file.newlines`, :775-791): rejoin held CR (`if t.was_cr: nextbit = "\r" + nextbit`); if chunk ends with `"\r"`, hold it (`t.was_cr = True; nextbit = nextbit[:-1]`); then count BEFORE normalizing: `crlf = nextbit.count("\r\n")`, `lone_cr = nextbit.count("\r") - crlf`, `lone_lf = nextbit.count("\n") - crlf`; add `"\r\n"`/`"\r"`/`"\n"` to `t.newline_kinds` for nonzero counts; normalize `nextbit = nextbit.replace("\r\n", "\n").replace("\r", "\n")`.
5. Append to document: `cur = QTextCursor(t.buf); cur.movePosition(QTextCursor.MoveOperation.End); cur.insertText(nextbit)`; `t.text.append(nextbit)`.
6. On EOF (empty raw, after final-decode flush; flush the held `was_cr` as a trailing `"\r"` newline_kind + normalized `"\n"` first): `self.set_buffer_writable(t.buf, os.access(t.filename, os.W_OK))` (:788); `self.bufferdata[t.pane].encoding = t.codecs_left[0]` (:789); `bufdata.newlines = k if len(t.newline_kinds) == 1 else tuple(sorted(t.newline_kinds))` where single kind is the plain string (:790-791 — GTK `file.newlines` semantics: str when uniform, tuple when mixed, None when no newlines); `panetext[t.pane] = "".join(t.text)`.
7. `yield 1` per outer loop pass (:794); after all tasks: `for b in self.textbuffer: self.undosequence.checkpoint(b)` (:795-796).

`IOError` handling (:739, :770): catch `OSError` (+ `LookupError` for unknown codec names, :739) — the py2 `except IOError, e` comma forms are SyntaxErrors in py3.

The dismissable-msg helper (:717-725) becomes `add_dismissable_msg(pane, icon, primary, secondary)` using WP4 `MsgAreaController.new_from_text_and_icon(...)` + a close button labelled `gtk_mnemonic_to_qt(_("Hi_de"))`; its response signal clears the controller.

Buffer handler discipline: `_disconnect_buffer_handlers`/`_connect_buffer_handlers` (:226-244) become flag+connection management: set `textview.setReadOnly(True/False)` and connect/disconnect `doc.contentsChange` → `self._on_contents_change` (T6.4) plus reset `self._prev_blockcount[pane] = doc.blockCount()` on reconnect. During load, handlers are disconnected exactly as in GTK (:710, :814 reconnect in `_diff_files`).

**Tests** (`tests/test_filediff_load.py`, fixtures in `tests/fixtures/encodings/`): utf8 file loads; latin-1 file with bytes invalid in utf-8 falls through the cascade to `iso8859_1` when `text_codecs = "utf_8 iso8859_1"`; utf_16 file (with BOM) loads under default cascade; file containing `b"\x00"` raw NUL → binary msgarea shown, buffer empty; CRLF file → `bufferdata.newlines == "\r\n"` and document text has no `"\r"`; mixed LF+CRLF → `newlines == ("\n", "\r\n")`; a CRLF split across the 4096 boundary (construct a file where byte 4095 is `\r`) does not produce a phantom blank line; a 3-byte UTF-8 char split across the boundary decodes correctly; after load `undosequence.checkpoint` called (documents report unmodified).

**TRAPS:**
- filediff.py:732/:759 — `codecs.open(f, "rU", codec)`: `'U'` mode raises `ValueError` on Python 3.11. Full rewrite required; do not try `newline=''` text-io shortcuts — the codec cascade needs re-open-from-zero semantics.
- filediff.py:750 — the NUL sniff runs on DECODED text; sniffing raw bytes false-positives every UTF-16 file.
- filediff.py:756 — the old code catches `ValueError`; incremental decoders raise `UnicodeDecodeError` (a subclass) — catch that, and remember the *final* flush can also raise (truncated multibyte at EOF): wrap both read-decode and final-flush.
- filediff.py:778-784 — the was_cr held-back CR must ALSO be flushed at EOF or a file ending in `"\r"` silently loses its last newline.
- filediff.py:791 — `hasattr(t.file, "newlines")` — the attribute is gone with the rewrite; forgetting manual tracking silently disables the mixed-newline save dialog (T6.10) and CRLF write-back.
- filediff.py:739/:756/:770 — `except X, e` comma syntax (SyntaxError — loud, but listed for completeness); :763 `print` statement.
- filediff.py:702 — `self.textview[len(files) >= 2]` indexes by bool; works in py3 but write `int(...)` for clarity.
- QTextDocument: clearing via `doc.clear()` resets the undo stack and fires `contentsChange` — do it only while handlers are disconnected and re-register with WP2's UndoSequence if its registration is per-connect (check WP2 API).

---

#### T6.4 — Diff pipeline: `FakeText`, `_filter_text`, `_diff_files`, re-diff-on-edit via `contentsChange`

**Old refs:** filediff.py:392-417 (`FakeText`/`FakeTextArray`), :419-438 (`_filter_text`), :798-826 (`_diff_files`, `_set_files_internal`), :380-390 (`_after_text_modified`), :440-449 (after-insert/after-delete), :217-224 (`_update_regexes`).

**Module helpers** (top of `meldq/filediff.py`):

```python
def position_at_line_or_eof(doc: QTextDocument, line: int) -> int:
    """Port of get_iter_at_line_or_eof (filediff.py:82-85)."""
    if line >= doc.blockCount():
        return doc.characterCount() - 1        # last valid cursor position
    return doc.findBlockByNumber(line).position()

def insert_text_at_line(doc: QTextDocument, line: int, text: str) -> None:
    """Port of insert_with_tags_by_name (filediff.py:87-90), minus the tag."""
    if line >= doc.blockCount():
        text = "\n" + text
    cur = QTextCursor(doc)
    cur.setPosition(position_at_line_or_eof(doc, line))
    cur.insertText(text)

def text_between_lines(doc: QTextDocument, lo: int, hi: int) -> str:
    cur = QTextCursor(doc)
    cur.setPosition(position_at_line_or_eof(doc, lo))
    cur.setPosition(position_at_line_or_eof(doc, hi), QTextCursor.MoveMode.KeepAnchor)
    return cur.selectedText().replace(" ", "\n")
```

**FakeText** (port of :392-417 — `__getslice__` MUST become `__getitem__` slice handling):

```python
class FakeText:
    def __init__(self, doc: QTextDocument, textfilter): ...
    def __getitem__(self, key):
        if isinstance(key, slice):
            lo = key.start or 0
            hi = len(self) if key.stop is None else key.stop
            txt = self.textfilter(text_between_lines(self.doc, lo, hi))
            if hi >= self.doc.blockCount():        # :399-402 EOF keeps last split element
                return txt.split("\n")
            return txt.split("\n")[:-1]
        block = self.doc.findBlockByNumber(min(key, self.doc.blockCount() - 1))
        return block.text()                        # :403-408 single line, UNFILTERED (matches old __getitem__)
    def __len__(self):
        return self.doc.blockCount()               # :409-410
```

`FakeTextArray` and `_get_texts(raw=0)` port verbatim (:412-417) — `[self._filter_text, lambda x: x][raw]` selection included.

`_filter_text` (:419-438) ports as-is (regex `killit` with the AssertionError guard). The warning dialog (:435-437) fires from inside scheduled generators — wrap the `QMessageBox.warning(...)` in the scheduler-pause convention: `self.scheduler.paused = True` / `finally: self.scheduler.paused = False` (WP3's SchedulerPump skips paused schedulers). Exact msgid: `_("Regular expression '%s' changed the number of lines in the file. Comparison will be incorrect. See the user manual for more details.")`.

`_diff_files(self, files, panetext)` (:798-819): `lines = [p.split("\n") for p in panetext]` (**not** `map`); `step = self.linediffer.set_sequences_iter(lines)`; `while next(step) is None: yield 1` (:803). Then locate chunk 0 (:806-809), `place cursor` → `cur = QTextCursor(self.textbuffer[1]); self.textview[1].setTextCursor(cur)` (:810), `self.scheduler.add_task(lambda: self.next_diff(Direction.DOWN), True)` (:811 — atfront flag kept), `self._queue_draw()`, `self.scheduler.add_task(self._update_highlighting().__next__)` (:813), `_connect_buffer_handlers()`, `_set_merge_action_sensitivity()`; the srcviewer highlighting calls (:816-818) are dropped (descoped, D10). `yield 0` last. `_set_files_internal` (:821-826) ports verbatim.

**Re-diff on edit** (replaces :440-449 + `deleted_lines_pending` at :135/:447-449/:576-580):

```python
def _on_contents_change(self, pane: int, position: int, removed: int, added: int) -> None:
    doc = self.textbuffer[pane]
    new_count = doc.blockCount()
    sizechange = new_count - self._prev_blockcount[pane]
    self._prev_blockcount[pane] = new_count
    startline = doc.findBlock(position).blockNumber()
    self._after_text_modified(pane, startline, sizechange)
```

Wire with `functools.partial(self._on_contents_change, i)` on `doc.contentsChange`. Equivalence proof vs GTK: insert of N newlines at line L → GTK computed `it.get_line() - lines_added == L` (:441-442) = `findBlock(position).blockNumber()`; delete from line L → GTK `it0.get_line() == L` (:446) = same. Blockcount delta equals `±lines` in both cases. `_after_text_modified(pane, startline, sizechange)` ports :380-390 with `self.linediffer.change_sequence(pane, startline, sizechange, self._get_texts())`, cursor refresh for the focused pane, `self.scheduler.add_task(self._update_highlighting().__next__)` (:389), `self._queue_draw()`.

Note: `contentsChange` fires during UndoSequence's own `doc.undo()`/`redo()` — re-diff MUST still run then (GTK behaved the same); only undo *recording* is suppressed (WP2's guard). Also: `setExtraSelections` does NOT fire `contentsChange` (view-level) — this is why inline highlights must never be applied via `QTextCursor.mergeCharFormat` (which does fire it and would loop).

**Tests** (`tests/test_faketext.py`, `tests/test_rediff.py`): FakeText slice vs `str.split` oracle on a 5-line doc incl. `hi >= blockCount` EOF case and empty last line; single-index returns unfiltered line even with an active filter; no `" "` in any output; typing a new line into pane 0 of a 2-pane FileDiff (qtbot.keyClicks) calls `change_sequence` with the right `(pane, startline, sizechange)` (monkeypatch-spy on the Differ) and updates `linediffer.diff_count()`; deleting a 3-line selection produces `sizechange == -3`.

**TRAPS:**
- filediff.py:396-402 — `FakeText.__getslice__` is NEVER called on py3; a mechanical port leaves slicing to fall into the single-index branch (or raise) and diff input becomes silently wrong. The slice logic (filter + drop-last-element unless EOF) must live in `__getitem__`.
- filediff.py:801 — `map(lambda x: x.split("\n"), panetext)` is lazy in py3; `Differ.set_sequences_iter` indexes its argument → `TypeError` far from the cause. Use a list comprehension.
- filediff.py:803/:389/:813/:704 — `.next` → `next()`/`.__next__`; the scheduler receives *callables*, so pass `gen.__next__` (bound method), never `gen.next`.
- filediff.py:339/:355/:867 — `[t for t in self._get_texts(raw=1)]` iterates `FakeTextArray` via the legacy `__getitem__`-until-IndexError protocol; py3 still supports it, but add `__len__` to `FakeTextArray` for sanity.
- QTextCursor.selectedText() returns U+2029 (paragraph separator) instead of `\n` — every extraction seam must go through `text_between_lines`; a missed site corrupts diffs *and* saved files.
- filediff.py:446-449/:576-580 — `deleted_lines_pending` pre-capture is impossible in Qt (no before-delete signal) and is fully replaced by the blockCount-delta; do not port the asserts.

---

#### T6.5 — Synchronized scrolling (`_sync_vscroll`, `_sync_hscroll`)

**Old refs:** filediff.py:141-146 (wiring + locks), :1142-1152 (`_sync_hscroll`), :1154-1206 (`_sync_vscroll`), :626-631 (size-allocate redraw).

Wiring in `__init__`: for each pane `i`: `tv.verticalScrollBar().valueChanged.connect(lambda _v, i=i: self._sync_vscroll(i))` (the signal's `int` value arg must be swallowed — a bare `partial(self._sync_vscroll, i)` would receive it as a second positional and TypeError), `tv.horizontalScrollBar().valueChanged.connect(self._sync_hscroll)`. Keep `self._sync_vscroll_lock` / `self._sync_hscroll_lock` booleans (:145-146).

`_sync_hscroll(self, value: int)` (:1142-1152): under lock, `setValue(value)` on the other visible panes' horizontal scrollbars.

`_sync_vscroll(self, master: int)` — the interpolation math ports verbatim but in **line units** (QPlainTextEdit's vertical scrollbar is block-indexed with wrap off: `value()` == first visible line, `pageStep()` == visible line count):

```python
def _sync_vscroll(self, master: int) -> None:
    if self._sync_vscroll_lock:
        return
    if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier):  # :1159 keymask & MASK_SHIFT
        self._sync_vscroll_lock = True
        syncpoint = 0.5                                                              # :1161
        line = (self.textview[master].first_visible_line_fraction()
                + self.textview[master].verticalScrollBar().pageStep() * syncpoint)  # :1164-1167 collapsed
        scrollbar_influence = ((1, 2), (0, 2), (1, 0))                               # :1170
        for i in scrollbar_influence[master][:self.num_panes - 1]:
            sb = self.textview[i].verticalScrollBar()
            mbegin, mend = 0, self.textbuffer[master].blockCount()                   # :1174
            obegin, oend = 0, self.textbuffer[i].blockCount()                        # :1175
            for c in self.linediffer.pair_changes(master, i):                        # :1177-1188 verbatim
                if c[1] >= line:
                    mend, oend = c[1], c[3]; break
                elif c[2] >= line:
                    mbegin, mend = c[1], c[2]; obegin, oend = c[3], c[4]; break
                else:
                    mbegin, obegin = c[2], c[4]
            fraction = (line - mbegin) / ((mend - mbegin) or 1)                      # :1189
            other_line = obegin + fraction * (oend - obegin)                         # :1190
            val = other_line - sb.pageStep() * syncpoint                             # :1193
            sb.setValue(round(min(max(val, sb.minimum()), sb.maximum())))            # :1195 (see note)
            if i == 1:
                master, line = 1, other_line                                         # :1198-1200
        self._sync_vscroll_lock = False
    for lm in self.linkmap[:self.num_panes - 1]:
        lm.update()                                                                  # :1203-1206
    for dm in self.diffmap:
        dm.update()
```

Notes to encode as comments: (a) GTK clamped to `upper - page_size`; `QScrollBar.maximum()` already excludes `pageStep()`, so clamp to `maximum()` directly; (b) `setValue` is integer → sub-line precision is lost (QPlainTextEdit scrolls whole lines anyway) — accepted deviation vs GTK's pixel adjustments; (c) the GTK `get_line_at_y`/`get_line_yrange` fractional-line computation (:1165-1167, :1191-1194) collapses entirely because line height is uniform with wrap off; (d) the forced synchronous `process_updates(True)` (:1204-1206) becomes plain `update()` — if visible lag appears on X11, switch to `repaint()` with a re-entrancy comment.

Also port `resync()` tasks in `pull_all_non_conflicting_changes`/`merge_all_non_conflicting_changes` (:342-349, :358-365) which flip the lock, replace text, then re-sync from the source pane's scrollbar.

**Tests** (`tests/test_sync_scroll.py`): build a 2-pane FileDiff from fixtures with one 20-line insertion in pane 1 around line 50 of 200; set pane-0 scrollbar to various values, `qtbot.waitUntil` sync; assert pane-1 scrollbar equals the hand-computed interpolation for at least 3 positions (before/inside/after the chunk); assert no recursion (lock) by counting valueChanged emissions; Shift+drag (simulate by setting modifiers via `qtbot.keyPress(widget, Qt.Key_Shift)` then scrolling) leaves the other pane untouched.

**TRAPS:**
- filediff.py:1164 — `adjustment.value` was PIXELS; a mechanical port that mixes pixels and Qt's line-indexed scrollbar values scrolls to garbage. Everything in this method is line-units now.
- filediff.py:1189 — `(mend - mbegin) or 1` guards division by zero for empty chunks — keep it; py3 true division is wanted here (it was float math already).
- filediff.py:1195 — dropping the `- page_size` when clamping is REQUIRED (`maximum()` semantics differ from GtkAdjustment `upper`), else the last page over-scrolls.
- filediff.py:1159 — the Shift-disables-sync behavior came from the keymask machinery; poll `QApplication.keyboardModifiers()` — do NOT port keymask state.
- Feedback loops: `setValue` on pane B fires `valueChanged` → `_sync_vscroll(B)`; the lock flag must be set BEFORE the first `setValue` (as in :1160) — reordering deadlocks or ping-pongs.

---

#### T6.6 — Inline character-level highlighting (`_update_highlighting` → ExtraSelections)

**Old refs:** filediff.py:41-72 (cache), :866-927 (generator), :895-898 (UTF-16 hack), :888-905 (cache/bail-out), :149-150 (`_inline_cache`, `_cached_match`).

Rebuild `_update_highlighting()` as a generator that recomputes per-pane ExtraSelection lists wholesale (the GTK progress-marks incremental cleaning at :869-893/:922-925 exists only because tags persist in the buffer; ExtraSelections are replaced atomically, so it is unnecessary):

```python
def _update_highlighting(self):
    alltexts = [t for t in self._get_texts(raw=1)]                 # :867
    newcache = set()
    sels: list[list[QTextEdit.ExtraSelection]] = [[] for _ in self.textbuffer]

    def add_sel(pane: int, start_pos: int, end_pos: int) -> None:
        sel = QTextEdit.ExtraSelection()
        sel.format = self.inline_format
        cur = QTextCursor(self.textbuffer[pane])
        cur.setPosition(start_pos); cur.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
        sel.cursor = cur
        sels[pane].append(sel)

    for chunk in self.linediffer.all_changes():                    # :871
        for i, c in enumerate(chunk):
            if c and c[0] == "replace":                            # :873
                pane1, panen = 1, i * 2
                cacheitem = (i, c, tuple(alltexts[1][c[1]:c[2]]), tuple(alltexts[i*2][c[3]:c[4]]))  # :876
                newcache.add(cacheitem)
                # base offsets: document position of chunk start, per pane
                base1 = position_at_line_or_eof(self.textbuffer[pane1], c[1])
                basen = position_at_line_or_eof(self.textbuffer[panen], c[3])
                text1 = utf16_units("\n".join(alltexts[1][c[1]:c[2]]))      # replaces :895-896
                textn = utf16_units("\n".join(alltexts[i*2][c[3]:c[4]]))    # replaces :897-898
                if len(text1) > 8000 and len(textn) > 8000:                 # :900-905
                    add_sel(pane1, base1, position_at_line_or_eof(self.textbuffer[pane1], c[2]))
                    add_sel(panen, basen, position_at_line_or_eof(self.textbuffer[panen], c[4]))
                    continue
                back = (0, 0)                                               # :908-919 verbatim
                for o in self._cached_match(text1, textn):
                    if o[0] == "equal":
                        if (o[2] - o[1] < 3) or (o[4] - o[3] < 3):
                            back = o[4] - o[3], o[2] - o[1]
                        continue
                    for j, (pane, base) in enumerate(((pane1, base1), (panen, basen))):
                        add_sel(pane, base + o[1 + 2*j] - back[j], base + o[2 + 2*j])
                    back = (0, 0)
                yield 1                                                     # :920
    for pane, s in enumerate(sels):
        self.textview[pane].setExtraSelections(s)
    self._inline_cache = newcache                                           # :926
    self._cached_match.clean(len(self._inline_cache))                       # :927
```

with:

```python
def utf16_units(s: str) -> tuple[int, ...]:
    b = s.encode("utf-16-le")
    return struct.unpack("%dH" % (len(b) // 2), b)
```

**Why this is now CORRECT where GTK was subtly wrong:** the offsets `o[...]` are UTF-16 code-unit counts; QTextCursor positions ARE UTF-16 code units, so `base + offset` is exact — whereas GTK's `iter.forward_chars(utf16_count)` (:915-917) over-advanced past astral-plane characters. Add a comment citing filediff.py:895-898.

Cache-consistency subtlety: the `cacheitem in self._inline_cache: continue` short-circuit (:888-889) skipped *recomputation* but the tags persisted in the buffer. With wholesale ExtraSelections rebuild we must still EMIT selections for cached chunks — therefore also cache the computed relative ranges: store `self._inline_ranges[cacheitem] = [(j, rel_start, rel_end), ...]` on compute; on cache hit, replay them against fresh `base1/basen` (line numbers move, relative offsets within an unchanged chunk do not). Evict `_inline_ranges` entries together with `_inline_cache`.

`CachedSequenceMatcher.clean` (:62-72): replace `items = self.cache.items(); items.sort(...)` with `items = sorted(self.cache.items(), key=lambda it: it[1][1])`.

**Tests** (`tests/test_inline_highlight.py`): 2-pane doc with lines `"abcdef"` vs `"abcXef"` in a replace chunk — after pumping the generator to exhaustion, exactly one ExtraSelection per pane covering the differing span (assert `selectionStart()/selectionEnd()` positions); astral-plane case: `"a𝕏b"` vs `"aYb"` — selection boundaries land on the right characters (𝕏 occupies 2 UTF-16 units); the >8000-unit bail-out highlights the whole chunk; editing the buffer reschedules highlighting (spy on `add_task`).

**TRAPS:**
- filediff.py:895-898 — the original encodes with `"utf16"` (BOM included) and strips the BOM via `[1:]` after unpack; with `utf-16-le` there is NO BOM — porting the `[1:]` strip drops the first real character of every chunk (silently misaligned highlights).
- filediff.py:896/:898 — `len(text1)/2` true division: `"%iH" % 4.0` still formats (`'4'`) so py3 hides the bug — write `// 2` deliberately.
- filediff.py:902-904, :914 — the inner `for i in range(2)` SHADOWS the outer `for i, c in enumerate(chunk)`; a careless port that keeps using `i` after the inner loop indexes the wrong pane. Rename the inner variable to `j` (as above).
- filediff.py:874 — `bufs = self.textbuffer[1], self.textbuffer[i*2]` — pane order is (middle, outer); the `o[1+2*j]` index arithmetic depends on that order; do not "clean it up".
- filediff.py:911-912 — the `back` heuristic (merge nearly-adjacent inline spans across sub-3-unit equal runs) is behavior, not noise; port verbatim.
- Do NOT use `QTextCursor.mergeCharFormat` — it modifies the document (fires `contentsChange` → re-diff → infinite loop) and pollutes undo.
- filediff.py:869 — `create_mark("progress", ...)` with the same name each pass would error in GTK if not cleaned; irrelevant now, but do not port marks at all.

---

#### T6.7 — `DiffMap` overview bar (`meldq/diffmap.py`)

> **Reconciliation:** WP5 (T5.9) already created `meldq/diffmap.py` for dirdiff. Extend the landed `DiffMap` class — keep its public API and add the filediff-specific behavior; do not replace the file. Concretely: WP5's `setup(scrollbar, chunk_fn)` fraction-based API must keep working unchanged (dirdiff calls it live) — the filediff entry point below is a NEW method `setup_editor(...)`; add a regression test that dirdiff's diffmap still paints after this task.

**Old refs:** diffmap.py:22-151 (whole file), filediff.py:1221-1225 (setup coupling), :678 (statusimage width coupling).

```python
class DiffMap(QWidget):
    WIDTH = 20          # was style property 'width', diffmap.py:135-140
    X_PADDING = 2.5     # was 'x-padding', diffmap.py:141-147

    def setup_editor(self, scrollbar: QScrollBar, editor: DiffTextEdit,
                     change_chunk_fn: Callable[[], Iterable],
                     fill_colors: dict[str, QColor], line_colors: dict[str, QColor]) -> None: ...
    # setup(scrollbar, chunk_fn) — WP5 T5.9's fraction-based API — is kept verbatim for dirdiff
    def paintEvent(self, event) -> None: ...          # replaces do_expose_event :93-117
    def mousePressEvent(self, event) -> None: ...     # replaces do_button_press_event :119-130
    def sizeHint(self) -> QSize: ...                  # replaces do_size_request :132-133 → QSize(self.WIDTH, 0)
```

`setup_editor` (replaces :44-62): disconnect previous connections (keep a handler list); store scrollbar/editor/difffunc/colors; connect `editor.document().blockCountChanged.connect(self._on_blockcount_changed)` (replaces buffer "changed" :56 + :87-91 line-count filter — `blockCountChanged` already fires only on line-count changes, so the `_num_lines` comparison collapses); `scrollbar.installEventFilter(self)` and in `eventFilter` trigger `update()` on `QEvent.Type.Resize`, `QEvent.Type.Move`, `QEvent.Type.StyleChange` (replaces "size-allocate"/"style-set" :52-54). `self.update()`.

Groove geometry (replaces the ENTIRE stepper computation :64-79):

```python
def _groove_rect_in_self(self) -> QRect:
    opt = QStyleOptionSlider(); self._scrollbar.initStyleOption(opt)
    groove = self._scrollbar.style().subControlRect(
        QStyle.ComplexControl.CC_ScrollBar, opt,
        QStyle.SubControl.SC_ScrollBarGroove, self._scrollbar)
    top_left = self.mapFromGlobal(self._scrollbar.mapToGlobal(groove.topLeft()))
    return QRect(QPoint(0, top_left.y()), QSize(self.width(), groove.height()))
```

`paintEvent` (port of :93-117): `num_lines = editor.document().blockCount()`; `scale = groove.height() / num_lines`; `painter.translate(0, groove.y())`; colors come from the passed prefs-derived dicts, NOT the hardcoded table at :100-103 (deliberate fix — the literals duplicated `color_*_bg` defaults); per chunk `c`: `y0 = round(scale * c[1]) - 0.5; y1 = round(scale * c[2]) - 0.5`; `rect = QRectF(X_PADDING, y0, width - 2*X_PADDING, int(y1 - y0))`; `painter.fillRect(rect, fill)`; `painter.setPen(line_color); painter.drawRect(rect)` (fill_preserve+stroke pair :115-117). Antialiasing OFF.

`mousePressEvent` (port of :119-130): left button only; `fraction = (event.position().y() - groove.y()) / groove.height()`; GTK `adj.upper` includes the page → `upper_gtk = sb.maximum() + sb.pageStep()`; `val = fraction * upper_gtk - sb.pageStep() / 2` (:126); clamp `sb.setValue(round(min(max(val, sb.minimum()), sb.maximum())))` — the GTK `upper - page_size` clamp (:127) is already `maximum()`.

`create_diffmap` glade factory (:150-151) is not ported.

**Tests** (`tests/test_diffmap.py`): with a 100-line doc and a chunk at lines 20-30, `widget.grab()` renders non-background pixels in the expected y-band (compute from groove rect); clicking at fraction 0.5 sets the scrollbar to `0.5*(max+page) - page/2` clamped; `blockCountChanged` triggers a repaint (spy via `update` monkeypatch).

**TRAPS:**
- diffmap.py:94 — `float(...) / self._num_lines` divides by zero when the buffer is empty (GTK got 1 line minimum from GtkTextBuffer; QTextDocument's `blockCount()` is also ≥1 — but assert it).
- diffmap.py:126 — `adj.upper` vs `QScrollBar.maximum()` semantics: porting `val = fraction * sb.maximum() - ...` verbatim mis-scales clicks near the bottom by one page. Use `maximum() + pageStep()`.
- diffmap.py:64-79 — do NOT port the stepper arithmetic; Qt6 styles have no steppers and `SC_ScrollBarGroove` is authoritative (macOS overlay scrollbars return a full-length groove — fine).
- filediff.py:1223 — `zip(self.diffmap, (0, self.num_panes - 1))`: diffmap1 tracks the LAST visible pane, which changes with `set_num_panes` — `setup_editor` must be re-callable (hence the disconnect bookkeeping).

---

#### T6.8 — `LinkMap` widget: beziers, action icons, hit-testing (`meldq/linkmap.py`)

**Old refs:** filediff.py:1269-1291 (`paint_pixbuf_at`, `_linkmap_draw_icon`), :1296-1348 (expose), :1350-1426 (scroll/press/release + `_linkmap_process_event`), :505-528 (keymask — replaced), :1384-1385 (CTRL double-height hack), filemerge.py:87-136 (overrides).

```python
class LinkMap(QWidget):
    def setup(self, doc: "FileDiff", which: int) -> None: ...
    def paintEvent(self, event) -> None: ...
    def mousePressEvent(self, event) -> None: ...
    def mouseReleaseEvent(self, event) -> None: ...
    def mouseMoveEvent(self, event) -> None: ...       # repaint → modifier poll
    def wheelEvent(self, event) -> None: ...           # port of on_linkmap_scroll_event :1350-1351 (alive, glade:244)
```

Construction: `setFocusPolicy(Qt.FocusPolicy.NoFocus)` (kills the focus save/restore dance :1374-1379/:1405-1407 — see Deleted), `setMouseTracking(True)`, `setFixedWidth(50)`.

Keymask replacement — module function in `meldq/filediff.py`:

```python
def current_keymask() -> int:
    mods = QApplication.keyboardModifiers()
    return ((MASK_SHIFT if mods & Qt.KeyboardModifier.ShiftModifier else 0)
          | (MASK_CTRL if mods & Qt.KeyboardModifier.ControlModifier else 0))
```

Polled at every paint / press / release / `_linkmap_draw_icon` call — **NOT** key-grab plumbing (:505-528 deleted; includes the ISO_Prev_Group X11 workaround :526). Known accepted deviation: pressing/releasing Shift or Ctrl while hovering motionless does not repaint until the next mouse move or scroll (mouseMoveEvent + paintEvent polling per contract).

`paintEvent` (port of :1296-1348):

```python
wtotal, htotal = self.width(), self.height()
painter = QPainter(self); painter.setClipRect(event.rect())
painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
doc, which = self._doc, self._which
tv_src, tv_dst = doc.textview[which], doc.textview[which + 1]
# rel_offset (:1306): vertical offset of each editor's viewport in linkmap coords
off_src = self.mapFromGlobal(tv_src.viewport().mapToGlobal(QPoint(0, 0))).y()
off_dst = self.mapFromGlobal(tv_dst.viewport().mapToGlobal(QPoint(0, 0))).y()
visible = [None, *tv_src.lines_visible(), *tv_dst.lines_visible()]        # :1308-1310
x_steps = [-0.5, wtotal / 3.0, 2.0 * wtotal / 3.0, wtotal + 0.5]          # :1313
pix_x = wtotal - doc.pixmap_apply0.width()                                 # :1340
for c in doc.linediffer.pair_changes(which, which + 1, visible[1:5]):     # :1315
    f0 = tv_src.line_ypos(c[1]) + off_src; f1 = tv_src.line_ypos(c[2]) + off_src   # :1317
    t0 = tv_dst.line_ypos(c[3]) + off_dst; t1 = tv_dst.line_ypos(c[4]) + off_dst   # :1318
    path = QPainterPath()
    path.moveTo(x_steps[0], f0 - 0.5)
    path.cubicTo(x_steps[1], f0 - 0.5, x_steps[2], t0 - 0.5, x_steps[3], t0 - 0.5)  # :1321-1323
    path.lineTo(x_steps[3], t1 - 0.5)
    path.cubicTo(x_steps[2], t1 - 0.5, x_steps[1], f1 - 0.5, x_steps[0], f1 - 0.5)  # :1325-1327
    path.closeSubpath()
    painter.fillPath(path, doc.fill_colors[c[0]])                          # :1330-1331
    if doc.linediffer.locate_chunk(which, c[1])[0] == doc.cursor.chunk:    # :1333
        painter.fillPath(path, QColor(255, 255, 255, 128))
    painter.strokePath(path, QPen(doc.line_colors[c[0]], 1.0))             # :1337-1338
    doc._linkmap_draw_icon(painter, which, c, pix_x, f0, t0)               # :1341
mid = int(0.5 * tv_src.height()) + 0.5                                     # :1344
painter.setPen(QPen(QColor(0, 0, 0, 128), 1.0))
painter.drawLine(QPointF(0.35 * wtotal, mid), QPointF(0.65 * wtotal, mid)) # :1345-1348
```

`FileDiff.paint_pixmap_at(painter, pixmap, x, y)` replaces :1269-1273 with `painter.drawPixmap(int(x), int(y), pixmap)`. `FileDiff._linkmap_draw_icon(painter, which, change, x, f0, t0)` ports :1275-1291 verbatim with `keymask = current_keymask()` replacing `self.keymask` — Shift → both icons `pixmap_delete`; Ctrl (and change not insert/delete) → `pixmap_copy0/copy1`; default → `pixmap_apply0/apply1`; the insert/replace/conflict draw predicates (:1286-1291) unchanged. **This method stays on FileDiff (not LinkMap)** so `FileMerge` overrides it 1:1 (filemerge.py:87-109).

`mousePressEvent` (port of :1372-1401): left button; `self._doc.mouse_chunk = None`; `pix_width/pix_height` from `pixmap_apply0`; `if current_keymask() == MASK_CTRL: pix_height *= 2` (:1384-1385 — the copy-up/copy-down half-zone hack); gutter quick-reject on `event.position().x()` (:1390-1397); then `doc._linkmap_process_event(event, which, side, htotal, rect_x, pix_width, pix_height)`.

`FileDiff._linkmap_process_event` (port of :1353-1370, stays on FileDiff for the FileMerge override): `src = which + side; dst = which + 1 - side`; per `pair_changes(src, dst)` skip pure inserts (:1361), compute `h = doc.textview[src].line_ypos(c[1]) + off_src` where `off_src` is the same mapFromGlobal offset as in paint — NOTE: `line_ypos` is already viewport-relative, so the GTK `- adj.value` (:1363) is already applied; first `h < 0` continue, `h > htotal` break, hit when `h < event.y < h + pix_height` → `self.mouse_chunk = ((src, dst), (rect_x, h, pix_width, pix_height), c)`.

`mouseReleaseEvent` (port of :1403-1426): if `doc.mouse_chunk` and release point still inside the stored rect (`inrect` lambda :1412): dispatch on `current_keymask()`: Shift → `doc.delete_chunk(src, chunk)`; Ctrl → `copy_up = event.position().y() - rect[1] < 0.5 * rect[3]`, `doc.copy_chunk(src, dst, chunk, copy_up)`; default → `doc.replace_chunk(src, dst, chunk)`. The `place_cursor_onscreen()` calls (:1415-1416) are dropped (GTK anti-scroll-jump hack; Qt cursor does not auto-scroll on programmatic edits).

`wheelEvent`: `self._doc.next_diff(Direction.DOWN if event.angleDelta().y() < 0 else Direction.UP)`.

**Tests** (`tests/test_linkmap.py`): 2-pane fixture with one replace chunk; `widget.grab()` → chunk fill color present between the panes' y-bands; simulated `qtbot.mouseClick` on the left gutter at the chunk's y (with no modifiers) calls `replace_chunk` (spy) with the right chunk; with `Qt.KeyboardModifier.ShiftModifier` passed to mouseClick, calls `delete_chunk`; wheel down triggers `next_diff(Direction.DOWN)`.

**TRAPS:**
- filediff.py:1306/:1356-1357 — `allocation.y` offsets: in Qt the equivalent is `mapFromGlobal(viewport().mapToGlobal(QPoint(0,0))).y()`; using widget (not viewport) coordinates misaligns every curve by the frame width; using `mapTo` fails because linkmap and editors are not ancestor/descendant.
- filediff.py:1363 — `- adj.value` is PIXELS in GTK; `line_ypos()` is already scroll-adjusted — subtracting a Qt scrollbar value (in lines!) here is the classic unit-mixing bug of this port.
- filediff.py:1384-1385 — the `pix_height *= 2` Ctrl hack enlarges the hit rect so the release-time `copy_up` half-test works; dropping it silently makes copy-down unreachable.
- filediff.py:1315 — `pair_changes(which, which+1, visible[1:5])` — the visible-bounds slicing (`[None] + ... ` then `[1:5]`) is an artifact; pass the 4-tuple directly but keep argument ORDER (from-lo, from-hi, to-lo, to-hi).
- filediff.py:1350-1351 — `on_linkmap_scroll_event` IS live (wired at filediff.glade:244/278) even though the plan's D7 note lists it as dead — port the wheel handler.
- filediff.py:1333 — `locate_chunk` per painted chunk is O(chunks) each; acceptable (GTK did the same) but bound the loop with the visible slice as GTK did or large files crawl.
- gtk.gdk.SCROLL_UP/DOWN tokens (:811, :1244-1246, :1350) must not leak into the new API — import `Direction` from `meldq.doc` (created in WP3 T3.4; do not redefine); `next_diff(direction: Direction)`.

---

#### T6.9 — Chunk navigation and merge actions; doc action contract

**Old refs:** filediff.py:178-195 (action table + ui_file), :275-312 (`on_current_diff_changed` sensitivity), :306-310 (set_sensitive), :314-372 (commands), :828-838 (`_set_merge_action_sensitivity`), :1243-1267 (`_find_next_chunk`, `next_diff`), :1428-1458 (chunk ops), :566-570 (user-action group hooks), filediff-ui.xml (menu/toolbar/popup layout).

**QActions** (port of :178-190; parent every action to `self.widget`; exact msgid text/tooltips; GTK accelerators → `QKeySequence`):

| name | icon (theme, fallback) | text | shortcut | statusTip | slot |
|---|---|---|---|---|---|
| `action_file_open` | "document-open" | `_("Open selected")` | — | `_("Open selected")` | `on_open_activate` |
| `action_create_patch` | — | `_("Create Patch")` | — | `_("Create a patch")` | `make_patch` |
| `action_push_left` | "go-previous" | `_("Push to left")` | `Alt+Left` | `_("Push current change to the left")` | `lambda: self.push_change(-1)` |
| `action_push_right` | "go-next" | `_("Push to right")` | `Alt+Right` | `_("Push current change to the right")` | `lambda: self.push_change(1)` |
| `action_pull_left` | "go-last" | `_("Pull from left")` | `Alt+Shift+Right` | `_("Pull change from the left")` | `lambda: self.pull_change(-1)` |
| `action_pull_right` | "go-first" | `_("Pull from right")` | `Alt+Shift+Left` | `_("Pull change from the right")` | `lambda: self.pull_change(1)` |
| `action_delete` | "edit-delete" | `_("Delete")` | `Alt+Delete` | `_("Delete change")` | `delete_change` |
| `action_merge_left` | — | `_("Merge all changes from left")` | — | `_("Merge all non-conflicting changes from the left")` | `lambda: self.pull_all_non_conflicting_changes(-1)` |
| `action_merge_right` | — | `_("Merge all changes from right")` | — | `_("Merge all non-conflicting changes from the right")` | `lambda: self.pull_all_non_conflicting_changes(1)` |
| `action_merge_all` | — | `_("Merge all non-conflicting")` | — | `_("Merge all non-conflicting changes from left and right panes")` | `merge_all_non_conflicting_changes` |

Doc/shell contract methods:

```python
def doc_actions(self) -> list[QAction]: ...   # all of the above
def menu_contributions(self) -> dict[str, list[QAction]]:
    # per filediff-ui.xml ChangesActions placeholder; a None entry = separator
    return {"changes": [push_left, push_right, pull_left, pull_right, delete_,
                        None, merge_left, merge_right, merge_all],
            "file": [create_patch]}
def toolbar_contributions(self) -> list[QAction]:
    return [push_left, push_right, pull_left, pull_right, delete_]
```

(Deviation note in code: 1.4's filediff-ui.xml toolbar placeholder held shell actions Save/Undo/Redo — those live permanently in the WP3 shell toolbar now; the doc segment carries the chunk actions instead.)

**Sensitivity** (`_on_current_diff_changed`, port of :275-312): connect `self.current_diff_changed.connect(self._on_current_diff_changed)` (:201). The chunk-capability logic (:279-305) ports verbatim with `self.textview[pane].isReadOnly()` inverted for `get_editable()`; `setEnabled` replaces `set_sensitive` (:306-310). End with `self._queue_draw()` (:312). `_set_merge_action_sensitivity` (:828-838) ports directly — note :830 indexes `self.textview[pane]` where `pane` may be `-1` (Python negative indexing made this "work" in 1.4 by using the LAST pane); preserve behavior but add a comment; guard `mergeable` when `pane == -1` the same way the old code accidentally did.

**Commands** (:314-372): `push_change`/`pull_change`/`delete_change` port verbatim (assertions included). `pull_all_non_conflicting_changes` (:332-349) and `merge_all_non_conflicting_changes` (:351-365): run `merge.Merger()` over `self._get_texts(raw=1)`; the buffer replacement `self.textbuffer[dst].set_text(mergedfile)` (:344, :360) must NOT use `setPlainText` (it clears the undo stack) — instead:

```python
self.undosequence.begin_group(self.textbuffer[dst])  # :343 on_textbuffer__begin_user_action
cur = QTextCursor(self.textbuffer[dst])
cur.select(QTextCursor.SelectionType.Document)
cur.insertText(mergedfile)
self.undosequence.end_group()                        # :345
```

Keep the `_sync_vscroll_lock` + `resync()` scheduler task pattern (:342-349).

**Chunk ops** (:1428-1458), all edits through QTextCursor so they land on the native undo stack:

```python
def copy_chunk(self, src: int, dst: int, chunk, copy_up: bool) -> None:      # :1428-1439
    b0, b1 = self.textbuffer[src], self.textbuffer[dst]
    t0 = text_between_lines(b0, chunk[1], chunk[2])
    if copy_up:
        if chunk[2] >= b0.blockCount() and chunk[3] < b1.blockCount():
            t0 = t0 + "\n"                                                    # :1434-1436
        insert_text_at_line(b1, chunk[3], t0)
    else:
        insert_text_at_line(b1, chunk[4], t0)

def replace_chunk(self, src: int, dst: int, chunk) -> None:                  # :1441-1451
    b0, b1 = self.textbuffer[src], self.textbuffer[dst]
    t0 = text_between_lines(b0, chunk[1], chunk[2])
    self.undosequence.begin_group(b1)                                         # :1448
    cur = QTextCursor(b1)
    cur.setPosition(position_at_line_or_eof(b1, chunk[3]))
    cur.setPosition(position_at_line_or_eof(b1, chunk[4]), QTextCursor.MoveMode.KeepAnchor)
    cur.removeSelectedText()                                                  # :1449
    insert_text_at_line(b1, chunk[3], t0)                                     # :1450
    self.undosequence.end_group()                                             # :1451

def delete_chunk(self, src: int, chunk) -> None:                              # :1453-1458
    b0 = self.textbuffer[src]
    start = position_at_line_or_eof(b0, chunk[1])
    if chunk[2] >= b0.blockCount():
        start = max(0, start - 1)                                             # :1456-1457 it.backward_char()
    cur = QTextCursor(b0)
    cur.setPosition(start)
    cur.setPosition(position_at_line_or_eof(b0, chunk[2]), QTextCursor.MoveMode.KeepAnchor)
    cur.removeSelectedText()
```

The `"edited line"` tag argument of the old `insert_with_tags_by_name` is intentionally not reproduced (see Deleted).

**Navigation** (:1243-1267): `_find_next_chunk(direction, pane)` with `Direction` tokens; `next_diff(direction)` — default pane selection (:1254-1259), `place cursor` via `QTextCursor` at `findBlockByNumber(c[1]).position()` + `setTextCursor`, then `ensureCursorVisible()` (deviation: GTK `scroll_to_mark(..., 0.1)` margin has no Qt knob; acceptable).

**Tests** (`tests/test_chunk_ops.py`): golden fixtures (`tests/fixtures/lao`, `tzu` — the classic GNU diff pair, plus a 3-way triple); after load+diff settle: `replace_chunk` makes both panes' chunk text equal and diff count drops; `delete_chunk` on an EOF-touching chunk removes the preceding newline (byte-exact oracle); `copy_chunk` up/down insert at chunk[3]/chunk[4]; each op is a SINGLE undo step: one `undosequence.undo()` restores the pre-op text exactly; `push_change`/`pull_change` route src/dst correctly; sensitivity: cursor inside a chunk in pane 0 of a 2-pane diff enables push-right and disables push-left.

**TRAPS:**
- filediff.py:344/:360 — `setPlainText` (the obvious `set_text` translation) CLEARS the QTextDocument undo stack and breaks the checkpoint model — the select-all-insert idiom is mandatory.
- filediff.py:1434-1436 — the copy-up EOF `"\n"` append fires only when src chunk touches EOF and dst does not; easy to invert; the regression test above pins it.
- filediff.py:1456-1457 — `it.backward_char()` before an EOF delete removes the newline BEFORE the chunk; off-by-one leaves a trailing blank line (silent — diff shows equal but files differ on disk).
- filediff.py:830 — `self.textview[pane]` with `pane == -1` relies on Python negative indexing; blindly adding a bounds-assert changes behavior — replicate, comment.
- filediff.py:287-291 — chunk tuple index semantics (`chunk[1] == chunk[2]` means empty on the from-side) come straight from Differ; do not reorder conditions.
- Group discipline: `begin_group`/`end_group` map to `beginEditBlock`/`endEditBlock` (WP2) — nesting across DIFFERENT documents in one group is asserted-out by WP2; `replace_chunk` edits only `b1`, fine; do not wrap `copy_chunk`'s single insert in a group (1.4 didn't: :1428-1439 has no user-action wrap).

---

#### T6.10 — Saving, close dialog, patch dialog, reload/refresh

**Old refs:** filediff.py:971-991 (`_get_filename_for_saving`), :993-1001 (`_save_text_to_filename`), :1003-1045 (`save_file`), :1088-1101 (save/save_as/save_all), :534-561 + glade:305-473 (closedialog), :1047-1076 + glade:474-586 (patchdialog), :1103-1107 (`on_fileentry_activate`), :1118-1129 (reload/refresh), :591-605 (open-selected, selected text).

`_get_filename_for_saving(self, title) -> str | None`: `QFileDialog.getSaveFileName(self.widget, title)[0] or None` — the manual overwrite prompt (:983-989) is DELETED (native dialog asks).

`_save_text_to_filename(self, filename: str, text: bytes) -> bool` (:993-1001): `open(filename, "wb").write(text)` in try/`except OSError as e` → `QMessageBox.critical` with exact msgid `_("Error writing to %s\n\n%s.") % (filename, e)`.

`save_file(self, pane, saveas=False)` (:1003-1045):
1. Filename via saveas branch with msgid `_("Choose a name for buffer %i.") % (pane+1)`; update `bufdata`, fileentry, history (:1008-1011).
2. `text = doc.toPlainText()` (paragraph separators already `\n`).
3. Newline write-back (:1015-1031): `isinstance(bufdata.newlines, str)` → `text = text.replace("\n", bufdata.newlines)` if not `"\n"`; `isinstance(..., tuple)` → `QMessageBox` with msgid `_("This file '%s' contains a mixture of line endings.\n\nWhich format would you like to use?") % bufdata.label`, buttons added via `addButton("UNIX (LF)" / "DOS (CR-LF)" / "MAC (CR)", QMessageBox.ButtonRole.ActionRole)` for the kinds present + Cancel; on choice store `bufdata.newlines = k` and convert (:1026-1031); Cancel → return (no result, matches :1024-1025).
4. Encoding (:1032-1039): `try: data = text.encode(bufdata.encoding)` — on `UnicodeEncodeError`, ask msgid `_("'%s' contains characters not encodable with '%s'\nWould you like to save as UTF-8?")` (Yes/No); **LATENT BUG FIX** (survey): 1.4 falls through WITHOUT re-encoding (py2 would then crash in the ascii write path) — on Yes, `data = text.encode("utf-8"); bufdata.encoding = "utf-8"`, on No return `RESULT_ERROR`. Regression test required.
5. On success: 1.4 emitted `"file-changed"` (:1041) consumed by vcview refresh; `MeldDoc` (WP3 T3.4) already provides `file_changed = pyqtSignal(str)` and the shell broadcasts it (T3.7) — emit the INHERITED signal, do NOT re-declare it on FileDiff; then `self.undosequence.checkpoint(doc)` (:1042); return `RESULT_OK`.

`save()`/`save_as()`/`save_all()` (:1088-1101) port directly. `set_buffer_writable`/`set_buffer_modified` (:1078-1086) port (index via `self.textbuffer.index(buf)` still works — QTextDocument identity).

**CloseDialog** (port of :534-561 + glade:305-473): `class CloseDialog(QDialog)` — title `_("Save modified files?")`, warning icon, bold label with exact glade wording `_("Some files have been modified.\nWhich ones would you like to save?")` (strip the Pango `<span>` markup, use `QFont.setBold`/rich text `<b>`), a QVBoxLayout of per-pane `QCheckBox(self._get_pane_label(i))` (checked iff modified, disabled iff not — :546-549), `QDialogButtonBox` with `gtk_mnemonic_to_qt(_("_Save Selected"))` (AcceptRole), Cancel (RejectRole), `gtk_mnemonic_to_qt(_("_Discard Changes"))` (DestructiveRole). `FileDiff.on_delete_event(self, appquit: bool = False) -> CloseResponse` returns `meldq.doc.CloseResponse.OK` / `CloseResponse.CANCEL` (imported from `meldq.doc` — WP3 T3.4; do NOT add a `RESULT_CANCEL` constant): Save-Selected → save each checked pane, any failure → CANCEL (:554-558); window-close (rejected) → CANCEL (:559-560); Discard → OK.

**PatchDialog** (port of :1047-1076 + glade:474-586): `QDialog` 600×400, read-only `QPlainTextEdit` with the current font, filled from `difflib.unified_diff(texts[0], texts[1], names[0], names[1])` with the `commonprefix` label shortening (:1054-1056); buttons: `_("Copy to Clipboard")` (ActionRole), Save As (`QDialogButtonBox.StandardButton.Save` with text via theme), Cancel. Copy → `QApplication.clipboard().setText(txt)` (no `.store()`); Save As → `_get_filename_for_saving(_("Save patch as..."))` + `_save_text_to_filename(filename, txt.encode("utf-8"))`. Escape rejects natively (glade's explicit accelerator :583 disappears). Optional 20-line `QSyntaxHighlighter` for `+/-/@@` prefixes — mark TODO, not required.

Reload/refresh (:1118-1129): `on_reload_activate` confirm dialog msgid `_("Reloading will discard changes in:\n%s\n\nYou cannot undo this operation.")` (OK/Cancel) then `set_files([b.filename for ...])`; `on_refresh_activate` → `set_files([None] * self.num_panes)`. `on_fileentry_activate` (:1103-1107): connect FileHistoryCombo activation → if `on_delete_event() != CloseResponse.CANCEL: set_files([e.get_full_path() ...])`. `on_open_activate`/`get_selected_text` (:591-605): selected text via `textCursor().selectedText().replace(" ", "\n")`; `_open_files` comes from MeldDoc (WP3).

**Tests** (`tests/test_filediff_save.py`): load CRLF fixture, edit, save → file on disk is CRLF everywhere; mixed-newline fixture + monkeypatched QMessageBox returning the DOS button → all-CRLF file and `bufdata.newlines == "\r\n"`; latin-1 buffer given a `€` char + monkeypatched Yes → file is valid UTF-8 containing `€` and `bufdata.encoding == "utf-8"` (**latent-bug regression**); save clears the modified star in `label_text` (checkpoint round-trip); CloseDialog: modified pane 0 only → checkbox 1 disabled; Discard returns OK without writing.

**TRAPS:**
- filediff.py:1016/:1019 — `type(x) == type("")` / `type(())` → `isinstance(str/tuple)`; with py3 the str-vs-unicode distinction is gone (a py2 unicode newlines value would have FAILED the `type("")` test — behavior is actually *fixed* in py3; note in comment).
- filediff.py:1032-1039 — the UTF-8 fallback bug described above; silent in a naive port (py3 would write the unencoded str? no — `'wb'.write(str)` raises TypeError at a distance).
- filediff.py:995 — write happens with `'wb'` + pre-encoded bytes; do NOT switch to text mode or newline conversion happens twice.
- filediff.py:537 — `if 1 in modified:` — port as `if any(modified):` (modified are now bools).
- filediff.py:559 — `RESPONSE_DELETE_EVENT` → CANCEL mapping equals QDialog `rejected`; do not treat Discard (DestructiveRole) as rejected.
- glade:389/:447 — `_Discard Changes`/`_Save Selected` msgids contain the underscore — translate the underscored string, then mnemonic-convert.

---

#### T6.11 — Cursor/status, overwrite mode, findbar wiring, context menu, banners

**Old refs:** filediff.py:246-273 (cursor status), :92-97 (CursorDetails), :641-648 (overwrite), :607-624 + :199 (findbar), :633-639 (popup), :840-864 (identical-files banners), :512-528 (Escape), :208-215 (switch-in focus), filemerge.py:58-59 (custom status).

`on_cursor_position_changed(self, pane: int, force: bool = False)` (port of :246-273): from `self.textview[pane].textCursor()` take `pos = cursor.position()`, `line = cursor.blockNumber()`, `offset = cursor.positionInBlock()`; early-out on same pane+pos unless force (:249-250); status text `"%s : %s" % ((_("INS"), _("OVR"))[int(self.textview_overwrite)], _("Ln %i, Col %i") % (line + 1, offset + 1))` + `self._get_custom_status_text()`; `self.status_changed.emit(status)`. Chunk tracking (:264-273): `locate_chunk` → update `self.cursor.chunk/prev_chunk/next_chunk`, emit `current_diff_changed` and `next_diff_changed(prev is not None, next is not None)`. Add `def _get_custom_status_text(self) -> str: return ""` — **deliberate fix**: filemerge.py:58-59 defines the conflicts counter but 1.4 never displays it; wiring it into the status string makes FileMerge's `"   Conflicts: %i"` visible.

Overwrite (replaces :641-648): `FileDiff._toggle_overwrite()` flips `self.textview_overwrite`, calls `setOverwriteMode` on ALL panes, refreshes status via `on_cursor_position_changed(focused_pane, force=True)`; registered as `insert_toggle_cb` on each editor (T6.1).

Findbar (consumes WP4 `FindBar`): instance placed at the bottom of the doc layout, hidden by default. `on_find_activate` → `self.findbar.start_find(self.textview_focussed)`; `on_find_next_activate` → `start_find_next(...)`; `on_replace_activate` → `start_replace(...)` (:607-620 — the `self.keymask = 0` resets are obsolete). Focus-in per pane updates `self.findbar.textview`-equivalent (:376). Escape anywhere in the doc hides it: `QShortcut(QKeySequence(Qt.Key.Key_Escape), self.widget, self.findbar.hide, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)` (replaces :517-518 and :622-624). FindBar is provided by WP4 (T4.7/T4.8): `start_find`/`start_find_next`/`start_replace`/`hide` operating on any `QPlainTextEdit` via Python `re` (NOT `QTextDocument.find` — WP4's explicit design rule); adapt call sites to those names.

Context menu (replaces :633-639 + filediff-ui.xml Popup): connect each editor's `customContextMenuRequested`; handler focuses the pane (GTK :635 `grab_focus`) and builds a `QMenu` in filediff-ui.xml Popup order: doc-local Save/Save As (no shortcuts — the shell owns Ctrl+S; text `_("Save")`? use theme-standard text via `QKeySequence.StandardKey` naming — set plain `_("Save")`/`_("Save As...")` if those msgids exist in the shell; otherwise reuse shell-provided actions if DocActionManager exposes them), separator, `action_create_patch`, separator, Cut/Copy/Paste bound to the focused editor's `cut()/copy()/paste()`, separator, `action_file_open`; `menu.exec(editor.viewport().mapToGlobal(pos))`.

Identical-files banners (`on_diffs_changed`, :840-864): on `sequences_identical()` and no error banner present, add per-pane MsgArea `_("Files are identical")` info banner with Hide button (index-0 pane uses `gtk_mnemonic_to_qt(_("Hi_de"))`, others `_("Hide")` — :850-854), `set_msg_id(FileDiff.MSG_SAME)`; clear all MSG_SAME banners when diffs reappear (:857-860); response → clear all (:862-864).

Tab-switch focus restore: `on_container_switch_in_event(self)` (WP3 hook) → `self.scheduler.add_task(self.textview_focussed.setFocus)` when set (:212-215).

**Tests** (`tests/test_filediff_status.py`): moving the cursor emits `status_changed` with `"INS : Ln 2, Col 3"` for a known position; `Qt.Key_Insert` flips all panes' `overwriteMode()` and status shows `OVR`; identical fixtures produce the `Files are identical` banner in every visible pane; pressing Escape hides a visible findbar.

**TRAPS:**
- filediff.py:258 — `(_("INS"), _("OVR"))[self.textview_overwrite]` indexes by int flag; keep `int()` around a bool.
- filediff.py:246-247 — GTK passed the buffer; Qt's `cursorPositionChanged` carries no args — bind the pane index via `partial` at connect time; deriving it from `QObject.sender()` breaks under queued signals and in tests.
- filediff.py:264/:269-272 — emit `next_diff_changed` only when prev/next EXISTENCE changes; emitting every move makes the shell rebuild widgets constantly.
- filediff.py:643-647 — the GTK disconnect/emit/reconnect dance must NOT be imitated; Qt has no `toggle-overwrite` signal, the Key_Insert interception is the whole mechanism.
- Dead glade handler `on_textview_move_cursor` (glade:88/164/202) — skip; also do not port `on_filediff__key_press_event` (:622-624) as a widget event filter — the QShortcut covers it.

---

#### T6.12 — `FileMerge` (`meldq/filemerge.py`)

**Old refs:** filemerge.py:25-136 entire file; filediff.py hooks it overrides.

```python
class FileMerge(FileDiff):
    differ = merge.AutoMergeDiffer                       # :27

    def __init__(self, prefs, num_panes):
        super().__init__(prefs, num_panes)
        self.hidden_textbuffer = QTextDocument(self)     # :31 gtk.TextBuffer()
```

- `_connect_buffer_handlers` (:33-36): call super, then `self.textview[0].setReadOnly(True); self.textview[2].setReadOnly(True)`.
- `set_files` (:38-44): 4-file remapping verbatim (`ancestor_file`, `merge_file` bookkeeping).
- `_set_files_internal` (:46-56): `textbuffers = self.textbuffer[:]; textbuffers[1] = self.hidden_textbuffer; files[1] = self.ancestor_file`; chain `_load_files` → `_merge_files` → `_diff_files` generators unchanged.
- `_get_custom_status_text` (:58-59): `return "   Conflicts: %i" % self.linediffer.get_unresolved_count()` — now visible via T6.11.
- `set_buffer_writable` (:61-67): hidden-buffer redirect verbatim.
- `_merge_files` (:69-85): `yield _("[%s] Computing differences")`; `lines = [p.split("\n") for p in panetext]` and `filteredlines = [...]` (**not** `map`, :71/:73); `step = merger.initialize(filteredlines, lines)`; `while next(step) is None: yield 1` (:76); `yield _("[%s] Merging files")`; `for panetext[1] in merger.merge_3_files(): yield 1` (:79-80 — yes, the loop target is a list element; keep it); `self.linediffer.unresolved = merger.unresolved`; insert result at END of visible middle doc via QTextCursor (:82); `self.bufferdata[1].modified = True` (:83); `recompute_label()`.
- `_linkmap_draw_icon` override (:87-109): ports 1:1 because T6.8 kept the hook on the doc class — replace `self.keymask & MASK_CTRL` with `current_keymask() & MASK_CTRL`; **fix the tuple bug**: `change[0] in ("delete",)` / `("insert",)` (:101/:106 — `in ("delete")` is a SUBSTRING test on py2 and py3; it worked by accident since no state name is a substring of another; write real tuples).
- `_linkmap_process_event` override (:111-136): `src = 2 * which; dst = 1`; per chunk choose the y-source pane: inserts hit-test against the DST pane (`h = self.textview[dst].line_ypos(c[3]) + off_dst`), others against SRC (:122-129) — offsets via the same `mapFromGlobal` recipe as T6.8; the `- dstadj.value`/`- srcadj.value` pixel subtractions (:125/:129) are already inside `line_ypos`.

**Tests** (`tests/test_filemerge.py`): 3 fixtures (base/local/remote with one clean change each side + one conflict): after load, middle pane contains the auto-merged text with conflict markers per `merge.Merger` semantics; `status_changed` text contains `"Conflicts: 1"`; panes 0/2 `isReadOnly()` is True and typing into them does nothing; `bufferdata[1].modified` is True and the tab label carries `*`.

**TRAPS:**
- filemerge.py:71/:73 — `map(lambda x: x.split("\n"), panetext)`: `merger.initialize` INDEXES its sequences → py3 `TypeError: 'map' object is not subscriptable` at a distance. Listify.
- filemerge.py:76 — `step.next() == None` → `next(step) is None`.
- filemerge.py:101/:106 — `change[0] in ("delete")` parenthesized-string membership (see above).
- filemerge.py:31 — the hidden ancestor document is loaded through `_load_files` but is NOT in `self.textbuffer`; the checkpoint loop (filediff.py:795-796) iterates `self.textbuffer`, so the hidden doc is never checkpointed — keep it out of UndoSequence registration entirely.
- filemerge.py:50 — `files[1] = self.ancestor_file` MUTATES the caller's list; `_set_files_internal` receives the list `set_files` scheduled — keep the mutation order (remap in `set_files` happens first).
- The `differ` class attribute swap (:27) means `AutoMergeDiffer.change_sequence` runs on every edit — WP2 must have ported `merge.py:137-160`; do not instantiate `diffutil.Differ` directly anywhere in FileDiff (always `self.differ()`, filediff.py:147).

---

#### T6.13 — Fixture corpus, integration smoke, launcher hookup

1. `tests/fixtures/`: `lao`/`tzu` (classic GNU diff texts), `mixed_newlines.txt` (LF+CRLF), `crlf.txt`, `latin1.txt`, `utf16.txt` (with BOM), `binary.bin` (contains NUL), `astral.txt` (contains `𝕏`), 3-way merge triple (`merge_base`, `merge_local`, `merge_remote`), and a `boundary_crlf.txt` generated so byte 4095 is `\r`.
2. Register comparison creation with the shell (WP3's new-comparison dialog / CLI): 2-3 files → `FileDiff`, 4 files (`--auto-merge` style) → `FileMerge`. Verify `meldq f1 f2` end-to-end.
3. Integration test `tests/test_filediff_integration.py`: full FileDiff over `lao`/`tzu` inside a real `MeldWindow` tab; pump the scheduler until idle (`qtbot.waitUntil(lambda: not doc.scheduler.tasks_pending())`); assert diff count > 0, linkmap/diffmap `grab()` non-empty, `next_diff(Direction.DOWN)` moves the cursor to the first chunk's start line, one edit + Ctrl+Z (window shortcut) round-trips the text.
4. Import-hygiene test (extend the WP0 purity test): `meldq/filediff.py`, `filemerge.py`, `linkmap.py`, `diffmap.py` import cleanly; `meldq/util/misc.py` still imports without Qt.

### Contracts consumed / provided

**Consumed:**
- WP2 `engine.diffutil.Differ(QObject)`: `diffs_changed` signal; `set_sequences_iter(list)`, `change_sequence(pane, startline, sizechange, texts)`, `locate_chunk(pane, line) -> (chunk, prev, next)`, `get_chunk(index, from_pane, to_pane=None)`, `pair_changes(from, to, lines)`, `single_changes(pane, lines)`, `all_changes()`, `has_mergeable_changes(pane)`, `sequences_identical()`, `clear()`, `ignore_blanks`; `engine.merge.Merger` (`initialize`, `merge_2_files`, `merge_3_files`, `unresolved`), `AutoMergeDiffer` (+ `get_unresolved_count`, `unresolved` set-attr).
- WP2 `engine.undo.UndoSequence`: per-document registration on `undoCommandAdded`, `begin_group(doc)`/`end_group()` (→ edit blocks; `begin_group` takes the target document), `undo`/`redo`, `checkpoint(doc)`, `clear()`, signals `can_undo_changed(bool)`, `can_redo_changed(bool)`, `checkpointed(object, bool)`.
- WP2 `engine.task.FifoScheduler`: `add_task(task, atfront=False)`, `tasks_pending()`, `runnable_cb`; generator protocol (yield None…final; never leak StopIteration — PEP 479).
- WP3 `doc.MeldDoc(QObject)`: signals `label_changed(str)`, `status_changed(str)`, `create_diff(list)`, `closed()`; `self.undosequence/scheduler/prefs/num_panes/label_text`; `_open_files`; tab hooks `on_container_switch_in_event`/`..._out_event`; `RESULT_OK/RESULT_ERROR` constants; `CloseResponse` and `Direction` enums (both provided by WP3 T3.4 — this WP adds nothing to `meldq/doc.py`).
- WP3 `app.SchedulerPump` pause convention: pump skips a scheduler while `scheduler.paused` is truthy (docs set/reset it around modal `exec()`).
- WP3 `DocActionManager`: consumes `doc_actions()`, `menu_contributions()` (keys "file"/"edit"/"changes"/"view", `None` = separator), `toolbar_contributions()` on tab switch.
- WP3 `util.prefs.Preferences`: `changed(str)` signal; keys `color_{delete,edited,replace,conflict,inline}_{bg,fg}` (QColor-parseable), `text_codecs`, `tab_size`, `spaces_instead_of_tabs`, `ignore_blank_lines`, `regexes`, `get_current_font()`; `util.misc.shorten_names`, `ListItem`, and (added here if missing) `gtk_mnemonic_to_qt`.
- WP4 `widgets.msgarea.MsgAreaController` (`new_from_text_and_icon`, `clear`, `set_msg_id`/`get_msg_id`, `has_message`, response signal), `widgets.historycombo.FileHistoryCombo` (`set_filename`, `prepend_history`, `get_full_path`, activation signal), `widgets.findbar.FindBar` (`start_find(editor)`, `start_find_next(editor)`, `start_replace(editor)`, `hide()`).

**Provided:**
- `meldq/widgets/editor.py` `DiffTextEdit(QPlainTextEdit)`: `focus_changed(bool)`; geometry API `line_height()`, `line_ypos(line)`, `line_at_ypos(y)`, `first_visible_line_fraction()`, `lines_visible()`; paint hooks `chunk_fn`/`is_current_chunk_fn`/`focus_line_fn`/`fill_colors`/`line_colors`; `set_font_and_tabs(font, tab_size)`; undo-key swallowing; `insert_toggle_cb`. (Also consumed by WP-dirdiff? No — dirdiff uses trees; consumed by vcview console only if that WP opts in.)
- `meldq/filediff.py` `FileDiff(MeldDoc)`: emits the inherited MeldDoc signals `current_diff_changed()`, `next_diff_changed(bool, bool)`, `file_changed(str)` (declared in WP3 T3.4 — not re-declared here); API `set_files(list)`, `set_labels(list)`, `save/save_as/save_all`, `next_diff(Direction)`, `on_delete_event(appquit=False) -> CloseResponse`, `set_num_panes(n)`, the doc-action contract trio; module helpers `position_at_line_or_eof`, `insert_text_at_line`, `text_between_lines`, `current_keymask`, `utf16_units`.
- `meldq/filemerge.py` `FileMerge(FileDiff)`; `meldq/linkmap.py` `LinkMap(QWidget).setup(doc, which)`; `meldq/diffmap.py` `DiffMap(QWidget).setup_editor(scrollbar, editor, change_chunk_fn, fill_colors, line_colors)` (WP5's `setup(scrollbar, chunk_fn)` fraction API kept intact).
- `meldq/resources/icons/button_{apply0,apply1,copy0,copy1,delete}.png`.

### Deleted (do-not-port)

- filediff.py:106-109, :505-528 — keymask press/release tracking incl. ISO_Prev_Group X11 workaround: replaced by `QApplication.keyboardModifiers()` polling.
- filediff.py:123-126 — `gtk.binding_entry_remove`: replaced by ShortcutOverride/keyPressEvent policy.
- filediff.py:151-161 — named buffer tags ("edited line" etc.): chunk coloring is painted from the differ; inline uses one QTextCharFormat. The "edited line" marker on pasted chunks (:87-90, :1437, :1450) is dropped — re-diff repaints correct chunk state immediately.
- filediff.py:197 — `gobject.idle_add(load_font)` GTK Bug 316730 hack.
- filediff.py:226-244 handler-id bookkeeping arrays — Qt connections managed via connect/disconnect of one `contentsChange` handler per pane.
- filediff.py:566-582 + :1477-1502 — `on_text_insert_text`/`on_text_delete_range`, `deleted_lines_pending`, `BufferAction`/`BufferInsertionAction`/`BufferDeletionAction`: WP2's QTextDocument-native undo makes before-delete capture unnecessary.
- filediff.py:816-818, :487-492, :1064 — GtkSourceView syntax highlighting, `show_line_numbers`, `spaces→` sourceview knobs: descoped to the Pygments follow-up (D10); `spaces_instead_of_tabs` is kept (reimplemented in keyPressEvent).
- filediff.py:983-989 — manual overwrite confirmation: QFileDialog asks natively.
- filediff.py:1072 — `clipboard.store()`: no Qt equivalent needed.
- filediff.py:1203-1206 — `invalidate_rect` + `process_updates(True)` forced sync repaint: `update()` suffices.
- filediff.py:1374-1379, :1405-1407, :1415-1416 — linkmap focus save/restore and `place_cursor_onscreen` anti-jump hacks: `NoFocus` policy + Qt edit semantics make them moot.
- filediff.glade:88/164/202 — dead `on_textview_move_cursor` handler.
- filediff.glade whole file — no conversion; layout is code-built (D7); `create_diffmap`/`findbar_create` glade factories (diffmap.py:150-151).
- diffmap.py:64-79, :135-147 — stepper style-property math and `install_style_property` knobs: `SC_ScrollBarGroove` + class constants.
- gtk.gdk.SCROLL_UP/DOWN as direction tokens (:811, :1244-1246, :1350) — `Direction` enum.

### Acceptance criteria

1. `python -c "from meldq.filediff import FileDiff; from meldq.filemerge import FileMerge; from meldq.linkmap import LinkMap; from meldq.diffmap import DiffMap; from meldq.widgets.editor import DiffTextEdit"` exits 0 on Python 3.11 with PyQt6 only.
2. `python -m pytest tests/test_editor_geometry.py tests/test_filediff_widget.py tests/test_filediff_load.py tests/test_faketext.py tests/test_rediff.py tests/test_sync_scroll.py tests/test_inline_highlight.py tests/test_diffmap.py tests/test_linkmap.py tests/test_chunk_ops.py tests/test_filediff_save.py tests/test_filediff_status.py tests/test_filemerge.py tests/test_filediff_integration.py -q` — all green under pytest-qt (offscreen: `QT_QPA_PLATFORM=offscreen`).
3. `grep -rn "import gtk\|import gobject\|import pango\|gtk\." meldq/ --include='*.py'` returns nothing; `grep -n "PyQt6" meldq/util/misc.py` returns nothing (pure-util rule).
4. Latent-bug regressions pass: (a) save-as-UTF-8 fallback actually writes UTF-8 (filediff.py:1032-1039); (b) `set_num_panes` show/hide works (map-for-side-effect :1214/:1219) — asserted by the pane-visibility test; (c) FakeText slicing equals the split-lines oracle (`__getslice__` :396-402); (d) inline offsets with astral chars land on character boundaries (:895-898).
5. Manual launch `meldq tests/fixtures/lao tests/fixtures/tzu`: two panes with colored chunk backgrounds and boundary lines; scrolling either pane proportionally scrolls the other with the linkmap curves tracking; clicking a linkmap arrow replaces the chunk; holding Shift over the linkmap and moving the mouse morphs icons to delete (click deletes); Ctrl shows copy icons (upper/lower half = copy up/down); diffmap click scrolls; typing in a pane updates chunks live; Ctrl+Z (window level) undoes exactly one chunk op or typing burst; status bar shows `INS : Ln x, Col y`; Alt+Left/Alt+Right push chunks when the Changes menu shows the merge actions.
6. Manual launch `meldq base local other merged` (4 files, FileMerge path): outer panes read-only, middle pane auto-merged with `Conflicts: N` in the status text, all linkmap actions target the middle pane.
7. i18n wording sanity at WP-close: spot-check the five msgids `"Ln %i, Col %i"`, `"Hi_de"`, `"[%s] Reading files"`, `"Files are identical"`, `"_Save Selected"` with `grep -F` against the 1.4 sources (wordings must match exactly); the full orphan gate runs in WP8 T8.4 (`tools/i18n_check_orphans.py` against `po/meld-1.4-reference.pot`) and is re-verified in T9.5.
8. Signals exist with exact names/signatures: `python -c "from meldq.filediff import FileDiff; assert hasattr(FileDiff, 'current_diff_changed') and hasattr(FileDiff, 'next_diff_changed') and hasattr(FileDiff, 'file_changed')"`.

### Estimated effort

**18–24 person-days.** Breakdown: T6.1 editor 2.5; T6.2 skeleton/layout 3; T6.3 loading 2.5; T6.4 diff pipeline 2.5; T6.5 sync scroll 1.5; T6.6 inline 2; T6.7 diffmap 1; T6.8 linkmap 2.5; T6.9 actions/chunk ops 2; T6.10 save/dialogs 2; T6.11 status/findbar 1.5; T6.12 filemerge 1.5; T6.13 integration 1.5 (≈ 21 PD midpoint, women within the plan's 18–30 PD filediff band since the undo redesign itself is WP2 scope). Highest-risk items to front-load: T6.1 geometry (validates the whole approach) and T6.5 unit-conversion.

---

## WP7 — Version control (meldq/vcview.py + meldq/vc/)

### Goal

Port Meld's version-control browser to PyQt6: the five kept VC plugin backends (git, svn, mercurial, bzr, cvs) plus the `_vc` base/registry as a **strictly Qt-free** package `meldq/vc/`, and the `VcView` document (status tree on `DiffTreeModel`, VC-selector combo, console pane, commit dialog, toolbar/menu actions) in `meldq/vcview.py`. All py2 bytes/str subprocess breakage is centralized and fixed in `_vc.popen/call`, the two GTK leaks (`cvs.py` → `misc.run_dialog`, transitive `gtk` import) are removed, and each tool's output parser gets fixture-based regression tests.

### Dependencies

Must land first (numbers per playbook; the parenthesised deliverable is what this WP actually needs, so remap by deliverable if numbering differs):

- **WP0** — scaffolding: `meldq/__init__.py` (`__version__`), `meldq/conf.py` (`_`, gettext init at import), `meldq/util/misc.py` (created in WP2), `meldq/resources/icons/`, pyproject/pytest scaffolding.
- **WP2** — engine: `meldq/engine/task.py` (`FifoScheduler` with `add_task(task, atfront=False)`, `remove_all_tasks()`, `tasks_pending()`, `iteration()`, `runnable_cb`).
- **WP3** — shell: `meldq/doc.py` (`MeldDoc(QObject)` with `label_changed/status_changed/create_diff/closed` signals, `self.scheduler`, `self.prefs`, `_open_files`), `meldq/app.py` (`MeldWindow`, `DocActionManager`, `SchedulerPump`), `meldq/util/prefs.py` (`Preferences`).
- **WP4** — shared widgets: `meldq/widgets/historycombo.py` (`HistoryCombo`, `FileHistoryCombo`), `meldq/widgets/msgarea.py` (`MsgArea`, `MsgAreaController`).
- **WP4 (shared widgets, extended by WP5 dirdiff)** — `meldq/widgets/treemodel.py`: `DiffTreeModel(QStandardItemModel)` with `ROLE_PATH/ROLE_STATE/ROLE_ISDIR`, the state→QColor/QFont style table in `data()`, `rowpath()`/`index_for_rowpath()`, and the `inorder_search_up/down` traversal helpers (PEP 479-safe — the old `raise StopIteration` at `meld/tree.py:138` and `meld/tree.py:158` must have become plain `return`).

### Old-code map

| Old file:lines | What it does | New home |
|---|---|---|
| `meld/vc/_vc.py:33-36` | `STATE_*` constants via `range(12)` | `meldq/vc/_vc.py` verbatim values (canonical origin is `widgets/treemodel.py` per WP4 T4.2; `_vc` imports or matches them — see T7.2) |
| `meld/vc/_vc.py:38-68` | `Entry`/`Dir`/`File` value objects; Pango `<b>Conflict</b>` in `states` (`:40`) | `meldq/vc/_vc.py` — same msgid, markup stripped post-translation; consumed via `ROLE_STATE`, not markup |
| `meld/vc/_vc.py:70-205` | `Vc`/`CachedVc` command interface, repo-root discovery, `listdir`/`lookup_files` | `meldq/vc/_vc.py` near-verbatim + new `self.warnings: list[str]` channel |
| `meld/vc/_vc.py:208-214` | `popen`/`call` subprocess helpers (bytes streams) | `meldq/vc/_vc.py` — text-mode, `encoding="utf-8"`, `errors="replace"` (T7.2) |
| `meld/vc/__init__.py:28-78` | glob+`__import__` plugin registry, deepest-root `get_vcs`, `_null` fallback | `meldq/vc/__init__.py` — explicit module list + `importlib` |
| `meld/vc/_null.py` | fallback plugin, `CMD="true"` | `meldq/vc/_null.py` (map→list fix at `:54-55`) |
| `meld/vc/git.py` | git backend (CachedVc, 3 subcommands) | `meldq/vc/git.py` (+cwd fix `:85`) |
| `meld/vc/svn.py` | svn backend, 4 status regexes | `meldq/vc/svn.py` |
| `meld/vc/mercurial.py` | hg backend, per-dir `hg status -A .` | `meldq/vc/mercurial.py` |
| `meld/vc/bzr.py` | bzr backend, `bzr status` section parser | `meldq/vc/bzr.py` (+UnboundLocalError fix `:83-86`) |
| `meld/vc/cvs.py` | CVS backend, parses `CVS/Entries` directly | `meldq/vc/cvs.py` (GTK leak removed, map/regex fixes) |
| `meld/vc/COPYING` | separate BSD license for the vc package | copy to `meldq/vc/COPYING` |
| `meld/vcview.py:36-51` | `_expand_to_root`, `_commonprefix` | `meldq/vcview.py` module functions |
| `meld/vcview.py:58-85` | `CommitDialog` (glade, TextBuffer mark dance, history entry) | `meldq/vcview.py:CommitDialog(QDialog)` + `meldq/ui/vccommit.ui` |
| `meld/vcview.py:87-92` | `COL_*` extra columns; `VcTreeStore` w/ STATE_MISSING markup override | `meldq/vcview.py:VcTreeModel(DiffTreeModel)` (1 pane + 5 plain columns; style-table override) |
| `meld/vcview.py:97-100` | filter lambdas (`entry_modified` …) | `meldq/vcview.py` verbatim |
| `meld/vcview.py:109-118` | `action_vc_cmds_map` NotImplementedError probing | `meldq/vcview.py:VcView.action_vc_cmds_map` verbatim |
| `meld/vcview.py:124-157` | `gtk.ActionGroup`, stock icons, `is_important` | QActions built in `VcView._make_actions()`; doc/shell contract methods |
| `meld/vcview.py:159-184` | TreeView + pixbuf/markup columns | `VcTreeView(QTreeView)` + role-styled `VcTreeModel` |
| `meld/vcview.py:186-196` | `ConsoleStream` TextBuffer end-mark appender | `_ConsoleStream` over read-only `QPlainTextEdit` |
| `meld/vcview.py:198-214` | location column visibility, console pref, VC ComboBox + `lock` hack | Qt equivalents; `blockSignals()` replaces `lock` |
| `meld/vcview.py:216-269` | `update_actions_sensitivity`, `choose_vc` (`["which", CMD]` at `:242`) | ported; `shutil.which` |
| `meld/vcview.py:271-299` | `on_vc_change`, `set_location`, `_set_location`, `recompute_label` | ported; `label_changed.emit(str)` |
| `meld/vcview.py:301-351` | `_search_recursively_iter` scan generator | ported onto `DiffTreeModel` + scheduler |
| `meld/vcview.py:353-421` | fileentry activate, quit/delete, row-activated, right-click, selection helpers | ported (T7.9/T7.10) |
| `meld/vcview.py:423-464` | `_command_iter`/`_command`/`_command_on_selected` console-streaming command runner | ported over `util.misc.read_pipe_iter` (T7.11) |
| `meld/vcview.py:466-504` | toolbar button handlers incl. delete-locally dialogs | QAction slots + `QMessageBox` (T7.10) |
| `meld/vcview.py:378-397, 506-557` | `run_diff_iter`, `show_patch` temp-checkout + `patch` pipe | ported; dialogs→MsgArea (T7.11) |
| `meld/vcview.py:559-615` | `refresh`, `refresh_partial`, `_update_item_state`, `find_iter_by_name`, `on_file_changed` | ported with `QPersistentModelIndex` |
| `meld/vcview.py:617-652` | console toggle/populate-popup, `next_diff` (`gtk.gdk.SCROLL_UP` at `:642`), reload | QToolButton toggle, context-menu Clear, `Direction` enum |
| `meld/misc.py:50-53,191-237,239-244,246-261,294-346` | `shelljoin`, `read_pipe_iter`, `write_pipe`, `commonprefix`, `shell_escape`/`shell_to_regex` | `meldq/util/misc.py` (Qt-free) (T7.1) |
| `data/ui/vcview.glade:22-235` | vcview layout (fileentry row, VPaned pos 250, console h=70, arrows) | code-built layout in `VcView.__init__` (dynamic view ⇒ no .ui per D7) |
| `data/ui/vcview.glade:237-511` | commitdialog (Ctrl+Return accel `:289-290`; labels `:340,428,477`; title `:240`) | `meldq/ui/vccommit.ui` + `QShortcut` |
| `data/ui/vcview-ui.xml:1-53` | UIManager merge: View menu, toolbar placeholders, Popup | `menu_contributions()`/`toolbar_contributions()`/`_make_context_menu()` |
| `meld/meldapp.py:163` | `("VcStatus", None, _("Version status"))` submenu action | `QMenu(_("Version status"))` owned by VcView, contributed to "view" |
| `meld/meldapp.py:456,459` | `current_doc().next_diff(gtk.gdk.SCROLL_DOWN/UP)` | `VcView.next_diff(Direction.DOWN/UP)` |
| `meld/preferences.py:251` | `vc_console_visible` BOOL default 0 | `Preferences` key `"vc_console_visible"`, default `False` |
| `meld/melddoc.py:112-124` | UIManager merge on tab switch | replaced by doc/shell action contract (consumed) |

### Tasks

#### T7.1 — Qt-free subprocess & path helpers in `meldq/util/misc.py`

Old refs: `meld/misc.py:50-53` (`shelljoin`), `:191-237` (`read_pipe_iter`), `:239-244` (`write_pipe`), `:246-261` (`commonprefix`), `:294-297` (`shell_escape`), `:299-346` (`shell_to_regex`).

Add to `meldq/util/misc.py` (idempotent — if the engine WP already ported any of these, verify signature and skip). **No Qt imports** (the repo-wide purity test enforces this).

- `def shelljoin(command: list[str]) -> str` — verbatim from `misc.py:50-53` (display-only quoting; do NOT swap in `shlex.join`, output feeds the console log and i18n'd status strings and old behavior quotes only whitespace).
- `def commonprefix(dirs: list[str]) -> str` — verbatim path-component-wise prefix from `misc.py:246-261` (do NOT use `os.path.commonprefix`, it is character-wise).
- `def shell_escape(glob_pat: str) -> str` and `def shell_to_regex(pat: str) -> str` — verbatim from `misc.py:294-346`; make pattern literals raw strings (`r'\['`, `r'\\{'`). Note `shell_to_regex` returns the regex **with a trailing `"$"`** — cvs.py slices it off with `[:-1]` (`meld/vc/cvs.py:153`); keep that contract.
- `def read_pipe_iter(command: list[str], errorstream, yield_interval: float = 0.1, workdir: str | None = None)` — generator: yields `None` while the child runs, then yields the **entire decoded stdout as one `str`** (this is the patch text consumed by `VcView.show_patch`). Rewrite the body of `misc.py:191-237` for py3:
  - `subprocess.Popen(command, cwd=workdir, stdin=DEVNULL, stdout=PIPE, stderr=PIPE)` in **binary** mode; `select.select` on `proc.stdout`/`proc.stderr` (POSIX-only is acceptable — Linux/macOS targets, Windows deferred); read with `os.read(fd, 4096)`.
  - Accumulate stdout bytes; on completion yield `b"".join(chunks).decode("utf-8", errors="replace")`. Decode each stderr chunk the same way and pass to `errorstream.write(...)` (replaces the byte-at-a-time `childerr.read(1)` at `misc.py:226`).
  - On nonzero exit write `"Exit code: %i\n" % status` to `errorstream` (keep `misc.py:233` wording).
  - Replace the `sentinel.__del__` kill-on-abandon hack (`misc.py:199-206`) with `try/finally` around the yield loop: on `GeneratorExit` (task removed via `scheduler.remove_all_tasks()`), `proc.terminate()`; write the old `"killing '%s'\n"` / `"killed (status was '%i')\n"` messages. Preserve `if workdir == "": workdir = None` (`misc.py:235-236`) — git's `get_working_directory` returns `''` (`meld/vc/git.py:78`).
- `def write_pipe(command: list[str], text: str) -> int` — `subprocess.run(command, input=text, text=True, stdout=subprocess.DEVNULL).returncode` (replaces `misc.py:239-244`).
- `def gtk_mnemonic_to_qt(label: str) -> str` — `label.replace("&", "&&").replace("_", "&", 1)`; reuse the shell WP's helper instead if one landed.

Tests `tests/test_util_misc_vc.py`: `shell_to_regex("{a,b}*.py")` matches `a1.py`; `commonprefix(["/a/b/c","/a/b/d"]) == "/a/b"`; `read_pipe_iter(["sh","-c","echo out; echo err >&2"], stream)` yields `None`s then `"out\n"` and stream received `"err\n"`; abandoning the generator of `["sleep","30"]` terminates the child (poll `proc` liveness via the `killing` message on the stream).

**TRAPS**
- `misc.py:212` loop condition `bits[-1] != ""` compares to **str** sentinel; a naive port reads bytes and never terminates — restructure, don't transliterate.
- `misc.py:221/226` `.read()` on buffered pipe objects mixed with `select` can block; the rewrite must select+`os.read` on raw fds.
- `misc.py:191-237` uses `select` on pipes — fine for POSIX; do not "modernize" to threads (global no-threads rule).
- Decoding chunk-wise can split multibyte sequences — that is why stdout must be decoded **once at the end**, not per chunk (stderr chunk-wise replace-decode is acceptable for a console).

#### T7.2 — `meldq/vc/_vc.py`: base classes, states, centralized text-mode subprocess

Old ref: `meld/vc/_vc.py` (whole file, 214 lines). Create `meldq/vc/_vc.py`; copy `meld/vc/COPYING` to `meldq/vc/COPYING`.

- Keep `STATE_IGNORED … STATE_MAX = range(12)` (`_vc.py:33-36`) exactly — these ints are the `ROLE_STATE` values of the shared `DiffTreeModel`. `meldq/widgets/treemodel.py` (WP4 T4.2) is the canonical origin for the UI layer: `meldq/vc/_vc.py` imports STATE_* from `meldq.widgets.treemodel` (or redefines the identical `range(12)`, asserted equal in `tests/test_vc_base.py`); do NOT change treemodel to import from `_vc` — that inverts the WP4→WP7 landing order.
- `Entry` (`_vc.py:38-51`): keep the **exact msgid** so the 34 catalogs still match, then strip markup after translation:
  ```python
  from meldq.conf import _
  states = [re.sub(r"</?b>", "", s) for s in
            _("Ignored:Unversioned:::Error::Newly added:Modified:<b>Conflict</b>:Removed:Missing").split(":")]
  assert len(states) == STATE_MAX
  ```
  `get_status()` now returns plain text; Conflict bolding comes from the model's ROLE_STATE→QFont table, not the string.
- `Dir`/`File` (`_vc.py:53-68`) verbatim (`isdir = True/False`). Keep `assert path[-1] != "/"` (`_vc.py:63`).
- `Vc`/`CachedVc` (`_vc.py:70-205`) verbatim, plus:
  - `Vc.__init__` gains `self.warnings: list[str] = []` — the plugin→view error channel that replaces the cvs.py GTK dialog (consumed in T7.11).
  - Keep the `NotImplementedError`-raising command methods (`_vc.py:94-107`) — `VcView.update_actions_sensitivity` probes them with dummy args (`meld/vcview.py:216-225`).
  - Keep `listdir` returning `dirs + files` **list concatenation** (`_vc.py:164-165`) — every `lookup_files/_get_dirsandfiles` override must return real lists (py3 `map` objects break `+`).
  - Keep the swapped-looking parameter naming of `_get_directoryname` (`_vc.py:169` passes `(files, dirs)` into a `(dirs, files)` signature) — behaviorally harmless (both are `(name, path)` tuples in one directory); do not "fix", just add a one-line comment.
- Centralized subprocess helpers — **exact signatures** (this is the single fix inherited by all plugins):
  ```python
  def popen(cmd: list[str], cwd: str | None = None) -> typing.IO[str]:
      """Return the child's stdout as a *text* stream (utf-8, errors='replace')."""
      return subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace").stdout

  def call(cmd: list[str], cwd: str | None = None) -> int:
      return subprocess.call(cmd, cwd=cwd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.STDOUT)
  ```
  Rationale to encode in comments: utf-8+replace (not locale) so undecodable filename bytes degrade to U+FFFD instead of crashing scans; `call` switches `stdout=PIPE` (`_vc.py:212-214`) to `DEVNULL` — the old PIPE was never drained, a 64 KiB+ output (`bzr check`, `svn info` on big trees) deadlocks `subprocess.call`.

Tests `tests/test_vc_base.py`: `_vc`'s STATE_* values equal `meldq.widgets.treemodel`'s; `Entry.states[STATE_CONFLICT] == "Conflict"` (markup stripped) and the source literal still contains `<b>Conflict</b>` (read `meldq/vc/_vc.py` text and assert the msgid substring — guards D8 catalog compatibility); `popen(["printf", "héllo"]).read() == "héllo"`; `popen` on a command emitting invalid utf-8 (`printf '\xff'`) yields `"�"` not an exception; `call(["true"]) == 0`, `call(["false"]) == 1`; `find_repo_root` walks up to a marker dir and raises `ValueError` past the fs root; `get_patch_files` extracts names from a sample git patch given `PATCH_INDEX_RE = "^diff --git a/(.*) b/.*$"`.

**TRAPS**
- `_vc.py:208-209` — bytes stdout was read by *every* plugin (`git.py:91/97/101`, `svn.py:85`, `mercurial.py:74`, `bzr.py:69/73`); without `text=True` svn/bzr line-iteration matches **str regexes against bytes → TypeError**, and git/hg `.split("\n")` gets `TypeError: a bytes-like object is required`. This is a hard, immediate break — fix here once, never per-plugin.
- `_vc.py:40` — markup inside a translated string: stripping it from the *msgid* would orphan the translation in all 34 po files; strip from the *translated result* only.
- `_vc.py:63` — `assert path[-1] != "/"` raises `IndexError` (not AssertionError) on `""`; callers never pass empty paths, keep as-is.
- Import-time `_()` call in `states`: `meldq.conf` gettext init must run before `meldq.vc` import (it does, per the WP0 conf.py stub contract) — do not move `_vc` import above `conf` init in any entry point.

#### T7.3 — `meldq/vc/git.py`

Old ref: `meld/vc/git.py` (140 lines). Port class `Vc(_vc.CachedVc)` with `CMD/NAME/VC_DIR/PATCH_STRIP_NUM/PATCH_INDEX_RE/state_map` verbatim (`git.py:36-49`), `check_repo_root` (`:51-55`, keeps the `.git`-file `os.path.exists` check), command methods (`:57-68`), `valid_repo` via `_vc.call([self.CMD, "branch"])` (`:69-73`), `get_working_directory` (`:74-78`; the `startswith("/")` POSIX test is fine for Linux/macOS).

`_lookup_tree_cache` (`git.py:80-120`):
- **FIX (survey latent bug)** `git.py:85`: `_vc.popen(["git", "update-index", "--refresh"])` runs in *meld's* cwd and never waits. Replace with `_vc.call([self.CMD, "update-index", "--refresh"], cwd=self.location)` — `call` blocks until done (popen didn't, so stale-status races were possible) and ignore the return value (`--refresh` exits nonzero when files need update; that's expected).
- `except OSError, e` → `except OSError as e` (`:110`); `iteritems()` → `items()` (`:134`); the three `proc.read().split("\n")[:-1]` sites (`:91/97/101`) now work because popen is text-mode.
- Keep `entry.split("\t", 2)` two-tuple unpack (`:115`) — safe because neither `diff-index` nor `diff-files` is invoked with `-M/-C`, so no `R100 old new` three-field lines occur; add a comment saying rename detection must never be enabled without widening this unpack.

Tests `tests/test_vc_git.py`:
- Parser fixture test: monkeypatch `meldq.vc._vc.popen` (and `call`) with a fake keyed on `cmd[1]` returning `io.StringIO` fixtures — `diff-index` → `"M\tmod.txt\nD\tgone.txt\n"`, `diff-files` → `"M\tmod.txt\n"`, `ls-files` → `"ignored.log\n"`; assert `_lookup_tree_cache` returns `{root/mod.txt: STATE_MODIFIED, root/gone.txt: STATE_REMOVED, root/ignored.log: STATE_IGNORED}` (duplicate `mod.txt` deduped via `set`, `git.py:108`).
- `_get_dirsandfiles` synthesizes the `STATE_REMOVED` file that is absent from disk (`git.py:134-139`).
- Real-repo test, `@pytest.mark.skipif(shutil.which("git") is None, ...)`: `git init` in `tmp_path` (env: `GIT_CONFIG_GLOBAL=os.devnull`, `GIT_AUTHOR_*`/`GIT_COMMITTER_*` set), commit `a.txt`, modify it, add untracked `new.txt`, `.gitignore` with `*.log` + tracked commit, create `x.log`; `Vc(str(tmp_path))`, `cache_inventory`, `lookup_files` → assert `a.txt`=STATE_MODIFIED, `new.txt`=STATE_NONE, `x.log`=STATE_IGNORED.

**TRAPS**
- `git.py:85` — missing `cwd` AND unawaited process: both halves of the bug matter; fixing only cwd still leaves the race.
- `git.py:91/97/101` — `.read().split("\n")` on bytes is a py3 TypeError; covered by T7.2 but the fixture test must pin str behavior.
- `git.py:110` `except OSError, e` syntax error under py3; the EAGAIN retry loop is effectively dead (blocking reads) — keep the structure verbatim anyway (behavioral spec) with `as e`.
- Empty repo (no commits): `diff-index --cached HEAD` fails, stderr goes to the terminal, `entries` stays empty, everything shows NORMAL — old behavior; do not "fix", but don't let tests run against an empty repo.
- `git.py:134` `iteritems` — silent AttributeError only when a dir listing hits the removed-file branch; convert and cover with the fixture test.

#### T7.4 — `meldq/vc/svn.py`

Old ref: `meld/vc/svn.py` (134 lines). Port verbatim: `VC_ROOT_WALK = False` + inherited `check_repo_root` (`svn.py:34`, `_vc.py:111-114`) — with svn ≥1.7 only the checkout root has `.svn`, so detection works only at the root; this matches 1.4 behavior, do not change. Keep the four compiled regexes exactly (`svn.py:47-50`), `state_map` (`:36-45`), commands (`:52-65`), `valid_repo` via `svn info` (`:66-70`).

`_get_matches` (`svn.py:72-110`): `except OSError, e` → `as e` (`:79`). `for line in entries:` (`:85`) now iterates a *text* stream; lines keep their trailing `"\n"` and the `$`-anchored regexes still match (non-MULTILINE `$` matches before a trailing newline) — identical to py2 file iteration, no change needed. `matches.sort()` sorts `(str, str, str)` tuples — py3-safe.

`_get_dirsandfiles` (`svn.py:112-134`): port verbatim. Note for the agent: `os.path.isdir(name)` (`:118`) works because `directory` is always absolute in meld (locations come from `os.path.abspath`, `meld/vcview.py:278`), so svn echoes absolute paths and `os.path.join(directory, name)` (`:119`) collapses to `name`.

Tests `tests/test_vc_svn.py` — **fixture-based, this parser is the fragile one**:
- Fixture strings in `tests/fixtures/vc/` covering: (a) svn 1.4-era `status -Nv` lines — `"M            4        4 alice        /r/foo.c"`, normal-file line with `" "` status, `"?                                    /r/new.c"`, `"!"` missing, `"C"` conflict; (b) the svn 1.6 tree-conflict line `"      >   local missing, incoming edit upon update"` (must be skipped, `svn.py:89-92`); (c) the moved-file form `"A  +    -    ?     ?   /r/dest.c"` matched by `re_status_moved` (`:47`) → tuple `("/r/dest.c", "A", "?")`; (d) a modern svn 1.14 `status -Nv` capture (9-column status field; verify `re_status_vc` still matches — the pattern only requires one status char followed by spaces and digits).
- Monkeypatch `meldq.vc._vc.popen` to return `io.StringIO(fixture)`; assert the exact sorted tuple list from `_get_matches`, and `_get_dirsandfiles` state mapping incl. `STATE_MISSING` for a vanished dir.

**TRAPS**
- `svn.py:85` — iterating the popen object: **the** py3 hard break (str regex vs bytes line → `TypeError: cannot use a string pattern on a bytes-like object`); the fixture test pins the text-mode fix.
- `svn.py:79` `except OSError, e` — py3 SyntaxError.
- `svn.py:48` regex assumes a *revision column* — locally-added-but-not-committed files show `"A 0 ? ?"` variants; that's what `re_status_moved`/`re_status_non_vc` catch; do not reorder the match attempts (`:89-107` order is load-bearing).
- Do not switch to `--xml` output "for robustness" — behavior parity first; note it as a future improvement only.

#### T7.5 — `meldq/vc/mercurial.py` + `meldq/vc/bzr.py`

Old refs: `meld/vc/mercurial.py` (100 lines), `meld/vc/bzr.py` (117 lines).

mercurial: port verbatim with `except OSError as e` (`mercurial.py:76`); `.read().split("\n")[:-1]` (`:74`) fine under text popen; the `entry.find("/") == -1` per-directory filter (`:83`) and `hgfiles` membership dict (`:88-98`) unchanged (it's a real dict, not the cvs map-trap). `valid_repo` = `hg root` (`:62-66`); `get_working_directory` returns `self.root` (`:67-68`). Per-directory `hg status -A .` (O(dirs) subprocesses) is kept — parity over speed.

bzr: port verbatim (`CMD="bzr"`, `CMDARGS=["--no-aliases","--no-plugins"]`, `bzr.py:31-32`) with:
- `except OSError as e` (`:75`), `iteritems()`→`items()` (`:95`).
- **FIX (survey latent bug) `bzr.py:83-86`**: if the first `bzr status` line is indented (or an unrecognized section header precedes any known one, e.g. `"working tree is out of date"` warnings), `cur_state` is referenced before assignment → `UnboundLocalError`. Fix: initialize `cur_state = None` before the loop; in the indented-line branch require `cur_state is not None` else skip the line. Unknown *section headers* keep the old behavior (they simply don't update `cur_state`, and with the fix their children are skipped instead of inheriting a stale state — also an improvement; note it in the commit message).
- `branch_root` read (`:69`): `.read().rstrip("\n")` fine in text mode.

Tests `tests/test_vc_mercurial.py` / `tests/test_vc_bzr.py`:
- hg fixture: `"M mod.txt\nA added.txt\n? unknown.txt\nC clean.txt\n! missing.txt\nsub/inner.txt\n"` → only depth-0 entries parsed, states per `state_map` (`mercurial.py:37-45`).
- bzr fixture: sections `"added:\n  new.txt\nmodified:\n  mod.txt\npending merges:\n  something\n"` → `pending merges:` stops parsing (`bzr.py:80-81`).
- **bzr regression test**: fixture starting `"  orphan-line\nmodified:\n  mod.txt\n"` → no exception, `orphan-line` absent from the cache, `mod.txt` = STATE_MODIFIED.
- Real-tool tests skipif `shutil.which("hg")`/`shutil.which("bzr")` missing (modern Breezy installs `bzr` as an alias; if absent the fixture tests still cover the parser).

**TRAPS**
- `bzr.py:83-86` — the UnboundLocalError is *input-dependent*: works in the demo repo, crashes in the field. The regression fixture is mandatory.
- `bzr.py:61` `valid_repo` runs `bzr check` — an expensive full-repo verification. Keep (behavioral spec), but remember `_vc.call` now DEVNULLs stdout so it can't deadlock (T7.2).
- `mercurial.py:83` `(entry[0], entry[2:])` slicing assumes `"X path"` two-char prefix — hg's `status` has used this format forever; don't defensive-code it, the fixture pins it.
- Both files: `except OSError, e` py3 SyntaxError; both EAGAIN loops are no-op wrappers — keep shape, fix syntax.

#### T7.6 — `meldq/vc/cvs.py` (highest silent-breakage density + the GTK leak)

Old ref: `meld/vc/cvs.py` (173 lines). Port with these changes:

- **Remove the toolkit leak**: delete `from meld import misc` (`cvs.py:28`). Import `shell_to_regex` from `meldq.util.misc` (moved in T7.1). Replace the `misc.run_dialog(...)` call on `.cvsignore` regex failure (`cvs.py:155-158`) with:
  ```python
  except re.error as e:
      self.warnings.append(_("Error converting to a regular expression\n"
                             "The pattern was '%s'\n"
                             "The error was '%s'") % (",".join(ignored), e))
      ignore_re = _DummyMatcher()
  ```
  (exact old msgid; `self.warnings` from T7.2; surfaced by VcView in T7.11). **This also fixes a latent crash**: old code left `ignore_re` unbound after the dialog, so `cvs.py:166` then raised `NameError` — add a regression test.
- **FIX map-membership (survey trap, `cvs.py:140` + `:165/:169`)**: `cvsfiles = map(lambda x: x[1], matches)` followed by repeated `f not in cvsfiles` — under py3 `map` is a one-shot iterator: the **first** membership test exhausts it and every later test silently answers "not in" → every file after the first unknown one gets misreported as unversioned/ignored, no exception. Replace with `cvsfiles = {m[1] for m in matches}`.
- Same class of fix at `cvs.py:65-66`: `d = map(...)`, `f = map(...)` are returned into `_vc.Vc.listdir`'s `dirs + files` concatenation (`_vc.py:165`) → `TypeError` in py3. Use list comprehensions.
- **FIX regex flags (py3.11 hard error)**: `re.findall("^([AR])\s*(.+)$(?m)", logentries)` (`cvs.py:74`) and `re.findall("^(D?)/([^/]+)/(.+)$(?m)", entries)` (`:90`) — trailing `(?m)` global flags raise `re.error: global flags not at the start of the expression` on Python ≥3.11. Rewrite as `re.findall(r"^([AR])\s*(.+)$", logentries, re.M)` / `re.findall(r"^(D?)/([^/]+)/(.+)$", entries, re.M)`.
- `except IOError, e` → `except OSError as e` (`:64`, `:71`); `print` statements (`:85`, `:113`) → `logging.getLogger(__name__).warning(...)`.
- `open(path, "U")` (`:122`) — the `"U"` mode was **removed in Python 3.11**; use `open(path, encoding="utf-8", errors="replace")` (newline=None default already gives universal newlines). The `Entries` reads (`:61`, `:70`) get `errors="replace"` too (also keep the manual `\r` normalization at `:62-63` — Entries files can mix line endings mid-file).
- `os.environ["HOME"]` (`:143`) → `os.path.expanduser("~")` (drops the KeyError guard need; keep the try/except for the file read).
- **FIX stale-state bug (`cvs.py:109-113`)**: when `date == "dummy timestamp"` and `rev[0] != "0"`, the old code only printed and fell through, so `state` kept the *previous file's* value (or NameError on the first file). Set `state = _vc.STATE_ERROR` in that branch after logging. Regression test.
- Keep the exact timestamp state inference (`:117-137`) including `time.asctime(time.gmtime(mtime)) == date` and the `"%3i"` day re-padding (`:117`) — brittle but it is the spec; the fixture tests construct matching timestamps.
- Move the inline `class dummy` (`:160-162`) to a module-level `class _DummyMatcher` with `def match(self, *args): return None` (needed by the error path above).
- The `x and y or z` idiom at `:166/:170` (`ignore_re.match(f) is None and _vc.STATE_NONE or _vc.STATE_IGNORED`) is a py2 trap in general but here `STATE_NONE == 1` is truthy so it works; still rewrite as a ternary for clarity.

Tests `tests/test_vc_cvs.py` (all pure-filesystem — CVS parsing reads `CVS/Entries`, no cvs binary needed):
- Build `tmp_path` with `CVS/Entries` containing: a dir line `D/subdir////`, a normal file (write file, `os.utime` to a chosen mtime, write `time.asctime(time.gmtime(mtime))` as the date field), a modified file (mismatched date), `-rev` removed, `0`-rev + `dummy timestamp` new, `dummy timestamp from new-entry` modified, and a conflict entry (`+`-marked date, file containing `\n=======\n`).
- `Entries.Log` fixture with `A file1`, `R file1`, `A file2` → only `file2` added.
- **Membership regression**: two unknown-to-CVS files alongside two known ones — assert *both* known files are absent from the unknown list (fails with a map iterator).
- **Ignore regression**: `.cvsignore` with `*.log {a,b}.tmp` → matching files STATE_IGNORED; `.cvsignore` with an unbalanced `[` pattern → no exception, `vc.warnings` contains the message, files fall back to STATE_NONE.
- **Stale-state regression**: entry with `dummy timestamp` and rev `"1.5"` → STATE_ERROR, not the previous file's state.

**TRAPS** (recap with lines): `:28` gtk-importing module at import time — merely loading the plugin used to require GTK; `:65-66` map→`+` TypeError; `:74`/`:90` `(?m)` = py3.11 `re.error` **at first scan**, not import; `:85`/`:113` print statements = SyntaxError; `:122` `open(..., "U")` = ValueError on py3.11; `:140/:165/:169` one-shot-iterator membership = *silent* misclassification; `:155-158` run_dialog + unbound `ignore_re` = NameError after the dialog; `:109-113` stale `state`.

#### T7.7 — Registry `meldq/vc/__init__.py` + `meldq/vc/_null.py` + descope

Old refs: `meld/vc/__init__.py` (78 lines), `meld/vc/_null.py` (56 lines).

- `meldq/vc/_null.py`: port verbatim; fix `lookup_files` (`_null.py:49-56`) `map(...)` → list comprehensions (same `+`-concat break as cvs). `CMD = "true"` is fine on Linux/macOS (Windows deferred).
- `meldq/vc/__init__.py`:
  ```python
  import importlib
  from . import _null

  # Descoped 1.4 backends (dead tools): tla, monotone, cdv, svk, darcs, rcs.
  # Their trees fall through to _null: files show as Unversioned, VC actions
  # become no-ops ('true' …); file/dir comparison still works there.
  _PLUGIN_MODULE_NAMES = ("bzr", "cvs", "git", "mercurial", "svn")

  def load_plugins():
      return [importlib.import_module(f"meldq.vc.{name}")
              for name in _PLUGIN_MODULE_NAMES]
  _plugins = load_plugins()
  ```
  This replaces the `glob.glob(.../"[a-z]*.py")` + `__import__` discovery (`__init__.py:31-33`) which breaks under zip/frozen installs. Port `get_plugins_metadata()` (`:37-46`) and `get_vcs(location)` (`:48-78`) logic verbatim — deepest-root wins, `ValueError` from a plugin constructor means "not my repo", `_null.Vc(location)` appended only when nothing matched.
- Keep the split of responsibilities: `get_vcs` never checks whether the *tool binary* exists — that stays in `VcView.choose_vc` (old `meld/vcview.py:242`), per the old contract.

Tests `tests/test_vc_registry.py`: `get_vcs(plain_tmpdir)[0].NAME == "Null"`; a dir containing `.git` → git plugin chosen; nested `outer/.git` + `outer/inner/.hg`, `get_vcs(outer/inner)` → only Mercurial (deepest root, `__init__.py:60-72`); `get_plugins_metadata()` ⊇ `{".git", ".svn", ".hg", ".bzr", "CVS"}`; `sorted(_PLUGIN_MODULE_NAMES)` contains no descoped names.

**TRAPS**: `__init__.py:26` implicit relative `import _null` = py3 ImportError; `__init__.py:33` `__import__(..., "*")` fromlist string is py2 folklore — use importlib; a *fake* plugin whose `Vc.__init__` raises anything other than `ValueError` would break `get_vcs` — preserved behavior, document in a comment.

#### T7.8 — `VcTreeModel` + `VcView` widget skeleton (layout, combo, console)

Old refs: `meld/vcview.py:87-92` (columns/store), `:120-214` (init), `:227-299` (choose_vc/location), `:617-637` (console toggle/popup), `data/ui/vcview.glade:22-235` (layout), `meld/preferences.py:251`.

In `meldq/vcview.py`:

- Column constants: `COL_NAME, COL_LOCATION, COL_STATUS, COL_REVISION, COL_TAG, COL_OPTIONS = range(6)` (replaces the interleaved scheme at `meld/vcview.py:87` / `meld/tree.py:103-104`).
- `class VcTreeModel(DiffTreeModel)`: `__init__(self)` calls `super().__init__(ntree=1, extra_cols=5)` (six columns total; the WP4 ctor owns the column count) then `setHorizontalHeaderLabels([_("Name"), _("Location"), _("Status"), _("Rev"), _("Tag"), _("Options")])` (labels from `meld/vcview.py:163,180-184`). Columns 1-5 are plain `QStandardItem`s (DisplayRole text only); column 0 is the pane column carrying `ROLE_PATH/ROLE_STATE/ROLE_ISDIR` + computed foreground/font/icon. Override the model's STATE_MISSING style entry to bold + strikethrough + `QColor("#000088")`, replicating `meld/vcview.py:92` (copy the class-level style table to an instance attribute before mutating, whatever attribute name the dirdiff WP landed). Add `def set_columns(self, index, location, status, rev, tag, options)` that ensures/creates sibling items via `itemFromIndex(index).parent()` (or `invisibleRootItem()`) `.setChild(row, col, QStandardItem(text))`.
- `class VcTreeView(QTreeView)`: `setSelectionMode(ExtendedSelection)`, `setAllColumnsShowFocus(True)`, headers visible; override `mousePressEvent` so a **right-click on an already-selected row does not collapse the multi-selection** (replicates the return-value trick at `meld/vcview.py:399-403`): if `event.button() == Qt.MouseButton.RightButton` and `indexAt(pos)` is in `selectionModel().selectedRows()`, skip `super()`.
- `class VcView(MeldDoc)`, `def __init__(self, prefs: Preferences)`:
  - `self.widget = QWidget()`; layout: `QVBoxLayout` → [`self.msgarea = MsgAreaController()` (WP4), `QHBoxLayout`(`self.fileentry = FileHistoryCombo(history_id="direntry", directory_entry=True)` (WP4 T4.5 kwargs) — id from `vcview.glade:37` `string1="direntry"` + `int1=1`; `self.combobox_vcs = QComboBox()` packed at the end, per `meld/vcview.py:212`), `self.splitter = QSplitter(Qt.Orientation.Vertical)` → [`self.treeview = VcTreeView()`, console section widget]]. `splitter.setSizes([250, 70])` (glade `:60` position 250, `:96` console height 70).
  - Console section: `QVBoxLayout` with `self.console_toggle = QToolButton()` (`setArrowType(Qt.ArrowType.DownArrow)` when open / `RightArrow` when closed, `setAutoRaise(True)`, `setCheckable(True)`) above `self.consoleview = QPlainTextEdit()` (`setReadOnly(True)`, `setLineWrapMode(NoWrap)`, `setTextInteractionFlags` keep selectable). Toggling sets `self.prefs.vc_console_visible` (bool pref, key `"vc_console_visible"`, default `False` per `meld/preferences.py:251`) and hides/shows only the `consoleview` (replaces the two EventBox/Arrow affordances at `vcview.glade:102-127/182-210` and handler `meld/vcview.py:617-625`).
  - `class _ConsoleStream:` with `__init__(self, textedit)` and `def write(self, s: str | None)` — `if s:` move cursor to `QTextCursor.MoveOperation.End`, `insertPlainText(s)`, `ensureCursorVisible()` (replaces the END-mark dance at `meld/vcview.py:186-196`). `self.consolestream = _ConsoleStream(self.consoleview)`.
  - Console context menu: `consoleview.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)`; handler builds `menu = self.consoleview.createStandardContextMenu()`, inserts a `QAction(_("Clear"))` + separator at the top (old used stock `gtk-clear`, `meld/vcview.py:627-637`); Clear does `self.consoleview.clear()`.
  - `self.model = VcTreeModel()`, `self.treeview.setModel(self.model)`; `self.treeview.doubleClicked.connect(self.on_row_activated)` and `self.treeview.activated.connect(self.on_row_activated)` (guard double-fire with a small debounce or connect only `activated` — verify Enter *and* double-click both trigger on Linux; `activated` alone covers both on most styles).
  - `self.tempdirs: list[str] = []`, `self.location = None`, `self.vc = None`.
- `choose_vc(self, vcs)` port (`meld/vcview.py:227-269`):
  - `self.combobox_vcs.blockSignals(True)` … populate … `blockSignals(False)` (replaces the `lock` attribute hack at `:205/:211/:229/:268`).
  - Tool-presence check: `if shutil.which(avc.CMD) is None:` replaces `vc._vc.call(["which", avc.CMD])` (`:242`).
  - **FIX (latent i18n bug, `meld/vcview.py:245`)**: old code is `_("%s Not Installed" % avc.CMD)` — it formats *before* translating, so the catalog msgid `"%s Not Installed"` never matches and the string is always English. Port as `_("%s Not Installed") % avc.CMD`. Keep `_("Invalid Repository")` (`:249`) and the combined `_("%s (%s)") % (avc.NAME, err_str)` (`:258`).
  - Items: `QStandardItem(text)` on the combo's model with `setData(avc, Qt.ItemDataRole.UserRole)`; disabled rows via `item.setEnabled(False)`. Tooltip: `setToolTip(tooltip_texts[len(vcs) == 1])` with `tooltip_texts = [_("Choose one Version Control"), _("Only one Version Control in this directory")]` (`:231-232`) — no version guard (delete the `gtk.pygtk_version` check at `:265`). `setEnabled(len(vcs) > 1)` (`:267`). Finally `setCurrentIndex(default_active)` — after `clear()` the index is -1, so a valid `default_active` always emits `currentIndexChanged` → `on_vc_change` (mirrors `:269`).
- `on_vc_change(self, index: int)`: guard `if index < 0 or self._combo_locked: return` (old crashes if no VC is valid, e.g. git repo with git uninstalled — fix, note in commit); `self.vc = self.combobox_vcs.itemData(index)`; `self._set_location(self.vc.root)`; `self.update_actions_sensitivity()` (`:271-275`).
- `set_location`, `_set_location`, `recompute_label` port (`:277-299`): abspath, `self.model.removeRows(0, rowCount())`, `fileentry.set_filename(location)` + `fileentry.prepend_history(location)` (WP4 API), add root row (ROLE_PATH=location, STATE_NORMAL, isdir=True), select it, `self.scheduler.remove_all_tasks()`, and `if os.path.isdir(self.vc.location): self.scheduler.add_task(self._search_recursively_iter(root_index).__next__)` (`:294-295` — note `.next`→`.__next__`). `recompute_label`: `self.label_text = os.path.basename(self.location)`; `self.label_changed.emit(self.label_text)`.

**TRAPS**
- `meld/vcview.py:295/380/397/441/457/570` — six `gen.next` bound-method references handed to the scheduler; py3 spells them `gen.__next__`. Grep the ported file for `.next` before committing.
- `:205-268` `lock` attribute — if you port it as a plain attribute, a re-entrant `currentIndexChanged` during `clear()` still fires; `blockSignals` is the correct replacement, but remember `setCurrentIndex` must happen **after** unblocking or `on_vc_change` never runs.
- `:245` — the i18n bug above; also do NOT let an auto-formatter fold `_("%s (%s)") % (...)` into an f-string (kills catalog lookup).
- `:199` `fileentry.show()` GTK bug-97503 workaround — delete, meaningless in Qt.
- Qt combo: `itemData` default role is `UserRole` — fine; if the dirdiff WP set a custom role convention on combos, match it.

#### T7.9 — Scan generator, filters, tree updates, navigation

Old refs: `meld/vcview.py:36-44, 97-100, 301-351, 559-615, 639-649`.

- Filter lambdas verbatim (`:97-100`): `entry_modified/entry_normal/entry_nonvc/entry_ignored` over `Entry.state`/`Entry.isdir`.
- `_search_recursively_iter(self, start_index)` (`:301-351`) — generator yielding status strings (the pump displays them via `status_changed`; just yield the same `_("[%s] Scanning %s")` texts):
  - Filters chosen from the toggle QActions' `isChecked()` (replaces `actiongroup.get_action(...).get_active()` at `:308-319`); `recursive = self.action_flatten.isChecked()`.
  - `entries = [e for e in self.vc.listdir(root) if showable(e)]` — **the `filter()` at `:333` must become a list**: the old code calls `len(entries)` at `:345` and iterates; a py3 filter object would make `len()` raise, and iterating-then-len is a silent empty-list bug.
  - `todo` bookkeeping: entries are `(rowpath_tuple_or_None, name_or_None)`. **py3 sort trap**: `todo.sort()` (`:322`) compared `None` against tuples/str in py2; use `todo.sort(key=lambda t: (t[0] or (), t[1] or ""))` to preserve depth-first ordering without TypeError.
  - Row addressing via the treemodel contract: `rowpath(index)` tuples in `todo`, resolved with `index_for_rowpath` at pop time; child rows created via the model's add-row helper + `self._update_item_state(child_index, entry, root[prefixlen:])`. Empty dirs: `self.model.add_empty(parent_index, _("(Empty)"))` — `add_empty` is landed by WP4 T4.2 (row with `ROLE_PATH=None`, `ROLE_STATE=STATE_EMPTY`, display text); use it.
  - `_expand_to_root` (`:36-44`) becomes: walk `index.parent()` chain calling `self.treeview.expand(ancestor)`; flatten mode expands only the root row (`:350`).
  - `self.vc.cache_inventory(rootname)` before the loop, `uncache_inventory()` after (`:320/:351`).
- `_update_item_state(self, index, vcentry, location)` (`:574-583`): set `ROLE_STATE`/`ROLE_ISDIR` on the pane column (model recomputes color/font/icon in `data()`), then `self.model.set_columns(index, location, vcentry.get_status(), vcentry.rev, vcentry.tag, vcentry.options)`.
- `refresh(self)` (`:559-560`): `self.set_location(root ROLE_PATH)`.
- `refresh_partial(self, where)` (`:562-572`): non-flatten path — find the row via `find_index_by_name`, hold it as `QPersistentModelIndex`, `insertRow` a fresh sibling after it on the parent item, set path/state, `removeRow` the old one, `self.scheduler.add_task(self._search_recursively_iter(new_index).__next__)`; flatten mode falls back to `self.refresh()` (keep the old `# XXX fixme` comment).
- `find_index_by_name(self, name) -> QModelIndex | None` (`:596-615`): same walk — compare `ROLE_PATH` equality, descend on `name.startswith(path)`; iterate children by row index instead of `iter_next`.
- `on_row_activated(self, index)` (`:367-376`): rows with children toggle expand/collapse; leaf rows `self.run_diff([path])` where path = `ROLE_PATH` of column 0.
- `next_diff(self, direction)` (`:639-649`): `direction` is `meldq.doc.Direction.UP/DOWN` — import it from `meldq.doc` (created in WP3 T3.4; do not redefine) (replaces the `gtk.gdk.SCROLL_UP` dict-key token at `:642`, callers at `meld/meldapp.py:456/459`). Start from the last selected row (or row 0), use the treemodel traversal helpers (`inorder_search_up/down`), stop at the first row whose `ROLE_STATE` ∉ `(STATE_NORMAL, STATE_EMPTY)`, then expand-to + `setCurrentIndex` + `scrollTo`.
- `on_file_changed(self, filename)` (`:585-594`): re-lookup the single file via `self.vc.lookup_files([], [(basename, path)])[1]` and `_update_item_state`.
- `_get_selected_paths/_get_selected_files` (`:411-421`): `selectionModel().selectedRows(0)` → `ROLE_PATH`; filter `None` (empty-row placeholders); strip ONE trailing slash: `p[:-1] if p.endswith("/") else p` — the old idiom `x[-1] != "/" and x or x[:-1]` (`:421`) is a py2 and-or ternary; do not port it literally (it also IndexErrors on `""`).

Test `tests/test_vcview_scan.py` (pytest-qt, offscreen): scratch git repo (as T7.3), `view = VcView(prefs)`, `view.set_location(repo)`, drain the scheduler with `while view.scheduler.tasks_pending(): view.scheduler.iteration()`; assert the tree contains `a.txt` with Status text `"Modified"` and `new.txt` `"Unversioned"` only after checking the Non-VC filter toggle + refresh + drain; check `next_diff(Direction.DOWN)` lands the cursor on the modified row; check `_get_selected_files()` returns absolute paths.

**TRAPS**
- `:333` `filter()` + `:345` `len(entries)` — the classic lazy-filter break; MUST be a list.
- `:322` `todo.sort()` — `None`-vs-tuple comparison TypeError in py3 under flatten+initial mix; use the sort key above.
- `:642` `gtk.gdk.SCROLL_UP` — not scroll code, just a token; don't import anything Qt-scroll-related for it.
- Old `tree.py:138/158` `raise StopIteration` inside the traversal generators — PEP 479 makes `next_diff` **crash with RuntimeError at tree boundaries** if WP4 didn't convert them to `return`; add an explicit boundary test here (cursor on last row, `next_diff(DOWN)` is a no-op, no exception).
- Mutating rows while iterating (refresh_partial) — `QPersistentModelIndex` only; a raw `QModelIndex` dangles after `insertRow`.

#### T7.10 — Actions, doc/shell contributions, context menu, button handlers

Old refs: `meld/vcview.py:109-157, 216-225, 353-365, 399-409, 459-504, 651-652`; `data/ui/vcview-ui.xml`; `meld/meldapp.py:163`.

- `_make_actions(self)` — create QActions parented to `self.widget`, labels via `gtk_mnemonic_to_qt(_(<exact old literal>))` so msgids stay glade/py-identical (`meld/vcview.py:124-143`):

  | attr | text msgid | tooltip msgid | icon | checkable/init |
  |---|---|---|---|---|
  | `action_compare` | `_("_Compare")` | `_("Compare selected")` | theme `dialog-information` | no |
  | `action_open` | `_("Open")`* | `_("Open selected")` | theme `document-open` | no |
  | `action_commit` | `_("_Commit")` | `_("Commit")` | bundled `vc-commit-24.png` | no |
  | `action_update` | `_("_Update")` | `_("Update")` | bundled `vc-update-24.png` | no |
  | `action_add` | `_("_Add")` | `_("Add to VC")` | bundled `vc-add-24.png` | no |
  | `action_add_binary` | `_("Add _Binary")` | `_("Add binary to VC")` | theme `list-add` | no |
  | `action_remove` | `_("_Remove")` | `_("Remove from VC")` | bundled `vc-remove-24.png` | no |
  | `action_resolved` | `_("_Resolved")` | `_("Mark as resolved for VC")` | bundled `vc-resolve-24.png` | no |
  | `action_revert` | `_("Revert")* ` | `_("Revert to original")` | theme `document-revert` | no |
  | `action_delete_locally` | `_("Delete")* ` | `_("Delete locally")` | theme `edit-delete` | no |
  | `action_flatten` | `_("_Flatten")` | `_("Flatten directories")` | theme `go-bottom` | checkable, **True** |
  | `action_filter_modified` | `_("_Modified")` | `_("Show modified")` | bundled `filter-modified-24.png` | checkable, **True** |
  | `action_filter_normal` | `_("_Normal")` | `_("Show normal")` | bundled `filter-normal-24.png` | checkable, False |
  | `action_filter_nonvc` | `_("Non _VC")` | `_("Show unversioned files")` | bundled `filter-nonvc-24.png` | checkable, False |
  | `action_filter_ignored` | `_("Ignored")` | `_("Show ignored files")` | bundled `filter-ignored-24.png` | checkable, False |

  *`VcOpen`, `VcRevert`, `VcDeleteLocally` had `None` labels in 1.4 (stock labels, `:126/:133/:134`); use plain `_("Open")`/`_("Revert")`/`_("Delete")` — new msgids are unavoidable there, keep tooltips exact. Copy the five `vc-*-24.png` + four `filter-*-24.png` from `data/icons/` into `meldq/resources/icons/` (loaded via `importlib.resources` per WP0 conventions); wrap in `QIcon.fromTheme(name, QIcon(bundled))` where a theme name exists. Note the defaults: Flatten and Show-Modified start **checked** (`:138-139`, 7th tuple element).
- Wire triggered/toggled: compare→`on_button_diff_clicked` (`:498-501`), open→`_open_files(self._get_selected_files())` (`:503-504`, MeldDoc helper), commit→open CommitDialog (T7.12), update/add/add_binary/remove/resolved/revert→`self._command_on_selected(self.vc.<cmd>_command(...))` (`:466-481`; add_binary passes `binary=1`), delete_locally→`on_button_delete_clicked` (`:482-496`), flatten→location column visibility + `refresh()` (`:405-407`), each filter toggle→`refresh()` (`:408-409`).
- `update_actions_sensitivity(self)` (`:216-225`): keep `action_vc_cmds_map` **verbatim** (`:109-118`, incl. `"VcCommit": ("commit_command", ("",))` probing with an empty message); map action-name keys to the QAction attributes; `action.setEnabled(False)` on `NotImplementedError`.
- Doc/shell contract (exact signatures):
  - `def doc_actions(self) -> list[QAction]` — all 15 actions above.
  - `def menu_contributions(self) -> dict[str, list[QAction]]` — `{"file": [], "edit": [], "changes": [], "view": [self.action_flatten, self.vcstatus_menu.menuAction()]}` where `self.vcstatus_menu = QMenu(gtk_mnemonic_to_qt(_("Version status")), self.widget)` (msgid from `meld/meldapp.py:163`) containing the four filter toggles — mirrors `vcview-ui.xml:3-13`.
  - `def toolbar_contributions(self) -> list[QAction]` — `[compare, SEP, commit, update, add, resolved, remove, revert, delete_locally, SEP, flatten, filter_modified, filter_normal, filter_nonvc, filter_ignored]` where SEP is a fresh `QAction` with `setSeparator(True)` — mirrors the three placeholders in `vcview-ui.xml:16-36`.
- Context menu (`vcview-ui.xml:38-52` order): `self.treeview.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)`; handler builds `QMenu` with compare, update, commit | open | add, add_binary, resolved, remove, revert | delete_locally and `exec(self.treeview.viewport().mapToGlobal(pos))` (replaces `popup_menu.popup(...)` at `:401` — the popup is now doc-owned, no shell injection).
- Direct-handler dialogs (safe — not inside generators): `_command_on_selected` with empty selection → `QMessageBox.information(self.widget, "Meld", _("Select some files first."))` (`:464`); delete-locally directory confirm → `QMessageBox.question(..., _("'%s' is a directory.\nRemove recursively?") % basename, Ok|Cancel)` (`:489-491`); removal failure → `QMessageBox.warning(..., _("Error removing %s\n\n%s.") % (name, e))` (`:494`, `except OSError as e` — old `:493` comma syntax).
- `on_fileentry_activate` → connect `FileHistoryCombo`'s activate signal to `set_location(self.fileentry.get_full_path())` (`:353-355`); `on_reload_activate` → re-trigger it (`:651-652`).
- `on_quit_event` (`:357-361`): `remove_all_tasks()` + `shutil.rmtree(t, ignore_errors=True)` for tempdirs. `on_delete_event` (`:363-365`): call `on_quit_event()`, return the doc contract's "OK to close" value (WP3's `RESULT_OK` equivalent; old returned `gtk.RESPONSE_OK`).

Test `tests/test_vcview_actions.py`: `len(view.doc_actions()) == 15`; `menu_contributions()["view"]` is `[flatten, submenu]` and the submenu holds 4 checkable actions; toolbar list has separators at positions 1 and 9; for a git-backed view `action_resolved.isEnabled() is False` (git.py defines no `resolved_command`) while update/commit are enabled; for svn all mapped actions enabled; toggling flatten hides/shows the Location column (`treeview.isColumnHidden(COL_LOCATION)`).

**TRAPS**
- `:150-157` `is_important`/`icon_name = stock_id` GTK toolbar plumbing — do NOT port; toolbar text style is a `MeldWindow` concern (`setToolButtonStyle`).
- GTK `"_"` mnemonics vs Qt `"&"` — translate at runtime with `gtk_mnemonic_to_qt` AFTER `_()`; converting the msgid breaks all 34 catalogs.
- `:216-225` probing calls real methods with dummy args — `commit_command("")` must stay side-effect-free (it only builds an argv list); never "optimize" into capability flags without changing every plugin.
- Toggle signal recursion: `setChecked()` during init fires `toggled` → `refresh()` before `self.vc` exists; connect signals **after** initial state is set, or guard `refresh` with `if self.vc is None: return`.

#### T7.11 — Command execution pipeline, diffs, patches, MsgArea

Old refs: `meld/vcview.py:378-397, 423-464, 506-557`.

- `def _command_iter(self, command: list[str], files: list[str], refresh: bool)` (`:423-452`) — generator:
  - Yield `"[%s] %s" % (self.label_text, msg.replace("\n", "↲"))` (the `u"↲"` literal at `:428` is plain `"↲"` now).
  - `relpath` inner helper and workdir computation verbatim (`:429-438`, uses `_commonprefix`/`self.vc.get_working_directory`).
  - `self.consolestream.write(shelljoin(command + files) + " (in %s)\n" % workdir)`; `readfunc = read_pipe_iter(command + files, self.consolestream, workdir=workdir).__next__` (`:440-441`).
  - Loop `while r is None: r = readfunc(); self.consolestream.write(r); yield 1` — `except OSError as e:` (old `except IOError, e` at `:447`) must NOT open a modal dialog: this code runs inside a pump tick; a nested `exec()` event loop would re-enter the pump and call `next()` on this very generator → `ValueError: generator already executing`. Instead: `self.msgarea.new_from_text_and_icon("dialog-error", _("Error running command.\n'%s'\n\nThe error was:\n%s") % (shelljoin(command), e))` plus a Hide button per WP6 T6.3's `add_dismissable_msg` pattern (the WP4 `MsgAreaController` API — it has no `add_error`; keep old wording `:448`).
  - `if refresh: self.refresh_partial(workdir)`; final `yield workdir, r` (`:450-452`).
- `_command` / `_command_on_selected` (`:454-464`): `self.scheduler.add_task(self._command_iter(command, files, refresh).__next__)`.
- `run_diff_iter(self, path_list, empty_patch_ok)` (`:378-393`): `difffunc = self._command_iter(self.vc.diff_command(), path_list, False).__next__`; replace `type(diff) != type(())` (`:382`) with `while not isinstance(diff, tuple):`; empty patch + `empty_patch_ok` → `self.msgarea.new_from_text_and_icon("dialog-information", _("No differences found."))` (`:390`, generator context — no modal); otherwise `self.create_diff.emit([path])` per path (`:392-393`).
- `run_diff(self, path_list, empty_patch_ok=False)` (`:395-397`): one task per path, `atfront=True`.
- `show_patch(self, prefix, patch)` (`:506-557`): port verbatim mechanics — `tempfile.mkdtemp("-meld")` tracked in `self.tempdirs`, `self.vc.get_patch_files(patch)` (regex on str patch), copy-or-create originals, `patchcmd = self.vc.patch_command(tmpdir)`, `if write_pipe(patchcmd, patch) == 0: self.create_diff.emit(list(d)) for each (destfile, pathtofile)`. Failure branch: keep the exact long msgid block (`:530-551`) with `%` args `(self.vc.NAME, __version__, self.vc.NAME, " ".join(self.vc.diff_command()), " ".join(patchcmd))` — `from meldq import __version__` replaces `import meldapp; meldapp.version` (`:529, :552`); strip-join lines as at `:556`; show via `self.msgarea.new_from_text_and_icon("dialog-error", ...)` (generator context) AND write to console.
- Surface plugin warnings: at the end of each `_search_recursively_iter` run (and after `_command_iter` completes), `for w in self.vc.warnings: self.msgarea.new_from_text_and_icon("dialog-warning", w)`; `self.vc.warnings.clear()` — this is where the cvs `.cvsignore` message (T7.6) reaches the user, replacing `misc.run_dialog`.
- Pump-pausing note: this WP deliberately keeps **zero modal dialogs inside generator frames**; `CommitDialog.exec()` (T7.12) runs from a QAction slot (plain event-loop context), where pump ticks during `exec()` only advance *other* tasks — same as GTK's `idle_add` during `gtk.Dialog.run()`. If a future change must exec() inside a generator, set `scheduler.paused = True/False` around the `exec()` per §2.5.

Test `tests/test_vcview_commands.py`: with a `_null`-backed view on `tmp_path`, drive `view._command_iter(["sh", "-c", "echo hello"], [str(tmp_path)], False)` manually with `next()` until the tuple arrives; assert console text contains the shelljoined command line and `"hello"`, and the final value is `(workdir, "hello\n")`. Failure path: command `["definitely-missing-binary-xyz"]` → MsgArea shows the error banner, generator completes without exception, no modal appeared (assert `QApplication.activeModalWidget() is None`).

**TRAPS**
- `:380/:397/:441/:457` `.next` → `.__next__` (four of the six scheduler call sites live here).
- `:382` `type(diff) != type(())` — works in py3 but is exactly the pattern lint auto-"fixes" into `isinstance` with inverted logic; write `not isinstance(...)` deliberately and test the loop exits.
- `:428` `u"↲"` — mixing unicode literal into a py2 str; in py3 it's all str, but the console stream must receive str (never bytes) — `read_pipe_iter` guarantees it (T7.1).
- `:447` `except IOError, e` — py3 SyntaxError; also `IOError` is `OSError` now.
- `:525` `write_pipe(patchcmd, patch)` — `patch` is str after T7.1/T7.2; passing it to a bytes-mode pipe would TypeError; `write_pipe` is text-mode by spec.
- Modal-in-generator re-entrancy (described above) — the single most dangerous behavioral difference vs GTK; the "no modal appeared" assertion pins it.

#### T7.12 — Commit dialog (`meldq/ui/vccommit.ui` + `CommitDialog`)

Old refs: `meld/vcview.py:58-85`; `data/ui/vcview.glade:237-511` (title `:240`, Ctrl accels `:289-290`, `changedfiles` `:317-334`, "Commit Files" `:340`, `textview` `:393-409`, "Previous Logs" `:428`, `previousentry` Custom `:451-457`, "Log Message" `:477`).

- Create `meldq/ui/vccommit.ui` (Qt Designer XML): root `QDialog` objectName `commitdialog`, `windowTitle` = `VC Log` (set again from code via `_("VC Log")` — .ui strings are not gettext-extracted, so ALL user-visible texts must be (re)assigned in code; leave placeholders in the .ui). Children: `QGroupBox groupbox_files` containing `QLabel changedfiles` (`wordWrap=True`; code sets `setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)`); `QGroupBox groupbox_message` containing `QPlainTextEdit textview` (min size ≈ 320×200 per glade `:383-384`) and an `QHBoxLayout` with `QLabel previouslogs_label` + promoted widget `previousentry` (class `HistoryCombo`, header `meldq.widgets.historycombo`); `QDialogButtonBox buttonbox` with Ok|Cancel. Minimum dialog width 450 (glade `:238`).
- `class CommitDialog(QDialog)` in `meldq/vcview.py`:
  ```python
  def __init__(self, parent: "VcView"):
      super().__init__(parent.widget.window())
      uic.loadUi(<resource path to vccommit.ui>, self)
  ```
  - Set texts: `self.setWindowTitle(_("VC Log"))`, `groupbox_files.setTitle(_("Commit Files"))`, `groupbox_message.setTitle(_("Log Message"))`, `previouslogs_label.setText(_("Previous Logs"))` — exact glade msgids.
  - Changed-files summary (`meld/vcview.py:63-66`): `selected = parent._get_selected_files()`; `topdir = _commonprefix(selected)`; `self.changedfiles.setText(("(in %s) " % topdir) + " ".join(s[len(topdir):] for s in selected))`.
  - `self.previousentry` re-keyed via `set_history_id("previousentry")` after `loadUi` (glade `:454` `string1`; Designer promotion constructs it with the default ctor); make its line edit read-only (`self.previousentry.lineEdit().setReadOnly(True)`, mirrors `:70`) so it acts as a picker; `activated[int]` (or the WP4 equivalent selection signal) → `self.textview.setPlainText(self.previousentry.currentText())` (replaces `on_previousentry_activate`, `:83-85`); `setCurrentIndex(0)` if history non-empty (`:71`).
  - Focus + preselect (`:72-75`): `self.textview.setFocus()`; `self.textview.selectAll()` (replaces the place_cursor/move_mark selection dance — GTK put the cursor at start with selection to end; `selectAll()` is the accepted equivalent).
  - Shortcuts (glade `:289-290`): `QShortcut(QKeySequence("Ctrl+Return"), self, self.accept)` and `QShortcut(QKeySequence("Ctrl+Enter"), self, self.accept)`; `buttonbox.accepted/rejected` → `accept/reject`.
  - `def run(self) -> None` (keeps the old entry-point name, `:69-82`): `response = self.exec()`; `msg = self.textview.toPlainText()`; `if response == QDialog.DialogCode.Accepted: self.parent_view._command_on_selected(self.parent_view.vc.commit_command(msg))`; `if msg.strip(): self.previousentry.prepend_text(msg)` (`HistoryCombo` API — `prepend_history` exists only on `FileHistoryCombo`; old code used `prepend_text`, `meld/vcview.py:81`); `self.deleteLater()`.
- `VcView.on_button_commit_clicked`: `CommitDialog(self).run()` (`:468-470`) — QAction slot context, modal exec is safe (see T7.11 note).

Test `tests/test_vcview_commit.py` (pytest-qt, QSettings redirected to a temp ini): open dialog against a stub VcView whose `_command_on_selected` records its arg and whose `vc` is `_null.Vc(tmp)`; type a message, `qtbot.keyClick(dlg, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)`; assert dialog accepted, recorded command equals `["true", "commit", "-m", "<msg>"]`, and a second dialog shows the message at history index 0 with the text preloaded into `textview` after selecting it.

**TRAPS**
- `:70` `previousentry.child.set_editable(False)` — the *combo* stays interactive, only typing is disabled; `setEditable(False)` on the QComboBox would be wrong (HistoryCombo is editable by contract) — use `lineEdit().setReadOnly(True)`.
- `:77` `buf.get_text(..., 0)` returned the whole buffer regardless of the OK/Cancel outcome and history is prepended **even on Cancel** (`:80-81` runs unconditionally) — that is old behavior; preserve it (message drafted then cancelled still lands in history).
- .ui strings bypass xgettext — every translatable string set in code, msgid-exact, or the D8 catalog check fails.
- `KP_Enter` (glade `:290`): Qt encodes keypad enter as `Qt.Key.Key_Enter` — the `"Ctrl+Enter"` QShortcut covers it; verify both shortcuts in the test on Linux.

#### T7.13 — Purity guard, real-tool matrix, shell wiring check, manual smoke

- `tests/test_vc_purity.py`: run `sys.executable -c "import meldq.vc, sys; sys.exit(1 if 'PyQt6' in sys.modules else 0)"` in a subprocess and assert exit 0 — pins the "plugins are pure" invariant that 1.4 violated via `cvs.py:28`/`svk.py:24`.
- `tests/test_vc_tools.py`: parametrized real-tool smoke (each `skipif shutil.which(tool) is None`): git (from T7.3), hg (`hg init`, add/modify/untracked → states), svn (`svnadmin create` + `svn checkout file://...` + add/modify → states via `lookup_files`), bzr/cvs fixture-only (tools effectively dead on CI).
- Wiring check with the shell: pytest-qt test constructing `MeldWindow`, opening a `VcView` tab on a scratch git repo, asserting: the toolbar shows the doc's contributed actions after `currentChanged`; the View menu placeholder contains "Flatten" and the "Version status" submenu; the statusbar shows a `[label] Scanning …` message while the pump drains; closing the tab calls `on_quit_event` (tempdir list emptied).
- Manual smoke script (append to the repo's manual-test notes): `pip install -e . && meldq`, open a VC comparison on a real git checkout with local modifications → expected observable behavior: tree lists modified files bold dark-red with "Modified" status; double-click a modified file opens a file comparison tab fed from the temp patch checkout; toolbar Commit opens the VC Log dialog, Ctrl+Return commits, console pane echoes `git commit -m …` output; console header arrow collapses/expands and the state survives restart; right-click with two rows selected keeps both selected and the popup's Compare diffs both.

### Contracts consumed / provided

**Consumed** (must exist, exact names): `MeldDoc` signals `label_changed(str)` / `status_changed(str)` / `create_diff(list)` / `closed()` and `self.scheduler` (WP3); `FifoScheduler.add_task(task, atfront=False)/remove_all_tasks()/tasks_pending()/iteration()` (WP2); `DiffTreeModel` with `ROLE_PATH/ROLE_STATE/ROLE_ISDIR`, state→style table, `rowpath`/`index_for_rowpath`, `inorder_search_up/down` (WP4 T4.2/T4.3, extended by WP5); `HistoryCombo`/`FileHistoryCombo` with `prepend_history`, `set_filename`, `get_full_path`, persisted history keys (WP4); `MsgArea`/`MsgAreaController` (`new_from_text_and_icon`, `clear`, `has_message`; WP4); `Preferences` bool key `"vc_console_visible"` default False (WP3); `DocActionManager` consuming `doc_actions/menu_contributions/toolbar_contributions` (WP3); `SchedulerPump` pumping only the current tab and honoring `runnable_cb` (WP3); `gettext _` from `meldq.conf` (WP0); `meldq.__version__` (WP0).

**Provided**: `meldq.vc.get_vcs(location) -> list[Vc]`, `get_plugins_metadata() -> list[str]` (consumed by dirdiff's VC-dir filtering); `meldq.vc._vc` — `STATE_*` constants (matching `widgets/treemodel.py`'s canonical values, per T7.2), `Entry/Dir/File` (plain-text `get_status()`, `(state, isdir)` consumed via roles), `Vc/CachedVc` with `warnings: list[str]`, `popen/call` text-mode helpers; `VcView(prefs)` + `set_location(path)` + `next_diff(Direction)` + `on_file_changed(filename)` (consumed by `MeldWindow`/new-comparison dialog); `meldq.doc.Direction` (provided by WP3 T3.4, consumed here); `meldq/util/misc.py` additions: `shelljoin`, `commonprefix`, `shell_escape`, `shell_to_regex`, `read_pipe_iter`, `write_pipe`, `gtk_mnemonic_to_qt`; `CommitDialog` + `meldq/ui/vccommit.ui`.

### Deleted (do-not-port)

- `meld/vc/tla.py`, `monotone.py`, `cdv.py`, `svk.py`, `darcs.py`, `rcs.py` — dead VCSes per D12; svk additionally imports gtk transitively (`svk.py:24`), rcs uses `os.system` shell redirection (`rcs.py:58-61`); their trees get the `_null` fallback (files "Unversioned", VC actions no-op).
- `data/ui/vcview.glade:514-771` `diffdialog` root — referenced by zero code, built on GTK1-era `GtkCombo` (`:659`); dead UI.
- `data/ui/vcview.glade:61` `on_vpaned_move_handle` signal hookup — no Python handler ever existed.
- `data/ui/vcview-ui.xml` — UIManager merge XML; replaced by the doc/shell contract methods.
- `meld/vcview.py:199` `fileentry.show()` — GTK bug-97503 workaround.
- `meld/vcview.py:265` `gtk.pygtk_version >= (2,12,0)` tooltip guard.
- `meld/vcview.py:150-157` `is_important` / `icon_name = stock_id` toolbar plumbing — QToolBar style is a shell concern.
- `meld/misc.py:35-48` `cmdout`/`NULL` — only svk consumed them.
- Old EAGAIN retry wrappers may be kept for shape but are documented no-ops (`git.py:81-112`, `svn.py:75-81`, `mercurial.py:72-78`, `bzr.py:70-77`) — do not extend them.
- GTK `ConsoleStream` END-mark machinery (`meld/vcview.py:186-196`) and EventBox/GtkArrow console affordances (`vcview.glade:102-127, 182-210`) — replaced by QPlainTextEdit + QToolButton.

### Acceptance criteria

1. `python -c "import meldq.vc"` succeeds on Python 3.11 with PyQt6 **not** imported: `pytest tests/test_vc_purity.py` passes (subprocess check of `sys.modules`).
2. `pytest tests/test_util_misc_vc.py tests/test_vc_base.py` green — includes: `popen` returns str with U+FFFD replacement on invalid utf-8; `Entry.states[STATE_CONFLICT] == "Conflict"` while the source msgid literal still contains `<b>Conflict</b>`; abandoned `read_pipe_iter` generator terminates its child.
3. `pytest tests/test_vc_git.py tests/test_vc_svn.py tests/test_vc_mercurial.py tests/test_vc_bzr.py tests/test_vc_cvs.py` green with **no VCS binaries installed** (fixture/monkeypatch parsers): exact state maps asserted per tool, including the svn tree-conflict skip and moved-file tuple.
4. Regression tests (each fails against a naive 2to3 port, passes after the specified fix): (a) cvs membership — two known + two unknown files, both known files correctly classified (`cvs.py:140/165/169` map-iterator bug); (b) cvs bad `.cvsignore` — no exception, warning in `vc.warnings`, no unbound `ignore_re` NameError (`cvs.py:155-158`); (c) cvs `dummy timestamp` with non-zero rev → STATE_ERROR, not stale state (`cvs.py:109-113`); (d) bzr fixture starting with an indented line → no UnboundLocalError (`bzr.py:83-86`); (e) cvs `(?m)` regexes compile on py3.11 (`cvs.py:74/90`).
5. `pytest tests/test_vc_registry.py` green: `_null` fallback on plain dirs, deepest-root selection with nested repos, metadata set, descoped modules absent.
6. Real-git test (skipif no git): `git.Vc` reports MODIFIED/NONE/IGNORED correctly on a scratch repo, and `update-index --refresh` runs **in the repo** (verify no `.git` pollution of the test CWD — the `git.py:85` fix).
7. `pytest tests/test_vcview_scan.py -q` (offscreen `QT_QPA_PLATFORM=offscreen`) green: tree populates by draining the scheduler, filter toggles change the visible entry set, flatten toggles the Location column, `next_diff(Direction.DOWN)` selects the next non-normal row and is a no-op (no exception) at the boundary.
8. `pytest tests/test_vcview_actions.py` green: 15 doc actions; view-menu contribution = Flatten + "Version status" submenu; toolbar contribution order matches `vcview-ui.xml:16-36`; `VcResolved` disabled for git, enabled for svn (NotImplementedError probing).
9. `pytest tests/test_vcview_commands.py` green: `_command_iter` streams to the console and finishes with `(workdir, output)`; failure path raises **no modal dialog** (MsgArea only) — asserts `QApplication.activeModalWidget() is None`.
10. `pytest tests/test_vcview_commit.py` green: Ctrl+Return accepts; commit command receives the typed message; message lands in persisted history and preloads via the Previous Logs combo.
11. i18n wording sanity at WP-close: spot-check this WP's msgids with `grep -F` against the 1.4 sources, confirming `"%s Not Installed"` is now looked up as a format template (`meld/vcview.py:245` fix); the three documented new labels (`Open`, `Revert`, `Delete`) go into `po/i18n-allowlist.txt` when WP8 lands; the full orphan gate runs in WP8 T8.4 and is re-verified in T9.5.
12. Manual smoke (documented in T7.13) passes on Linux and macOS: scan a real git checkout, commit via dialog, console echo, collapse state persistence across restart, right-click multi-selection preserved.

### Estimated effort

**8 person-days** (range 6–10): T7.1–T7.2 ≈ 1.5 pd; plugins T7.3–T7.7 ≈ 2.5 pd (cvs and the fixture corpus dominate); VcView T7.8–T7.12 ≈ 3 pd; integration/smoke T7.13 ≈ 1 pd. Matches the plan's 6–11 pd band for Phase 5 minus the six descoped backends, plus the added per-tool fixture test burden.

---

## WP8 — i18n, packaging, desktop integration

### Goal

Replace Meld 1.4's hand-written Makefile/intltool/#TOKEN# build machinery with a PEP 621 `pyproject.toml`, an `xgettext`/`msgmerge`/`msgfmt` pipeline that preserves all 34 existing `po/` catalogs, and an icon/desktop-integration story per decision D11. The centerpiece deliverable is a scripted **orphaned-msgid gate** that compares the new `meldq` POT against a frozen 1.4 reference POT — this is the enforcement mechanism for the project-wide rule that every user-visible string reuses the exact 1.4 English wording (D8).

### Dependencies

- **WP0 (scaffolding) + WP2 (engine)** — package skeleton `meldq/__init__.py`, `meldq/conf.py` stub, engine — required by every task.
- **WP3** (app shell: `meldq/main.py:main()`, `meldq/app.py`) — required for the console-script entry point (T8.1) and all manual launch checks.
- **WP3–WP7** (all string-bearing view/widget/vc WPs) — required only for the orphan gate (T8.4) to flip to *blocking*. T8.1–T8.3 and T8.5–T8.7 can land before them; the gate script lands early but its zero-orphans acceptance criterion is evaluated after WP3–WP7 merge (WP8 is the Phase-6 closer per PYQT_MIGRATION_PLAN.md §4).

### Old-code map

| Old file:lines | What it does | New home |
|---|---|---|
| `bin/meld:1-123` | Launcher: unbuffered stdout, `--pychecker`/`--profile`/`--sm-*` args, sys.path bootstrap via `meld.doap` sentinel (56-61), gettext init (63-69), py2/pygtk version gates (71-102), glade textdomain + icon-theme registration (109-111), `gtk.main()` (117) | Deleted as a file. Entry point `[project.scripts] meldq = "meldq.main:main"` (T8.1); gettext init → `meldq/conf.py` (T8.2); icon registration → `conf.get_icon()` (T8.6) |
| `bin/meld:60` | `#LIBDIR#` install-time token | Deleted; importlib.resources moots it (T8.2) |
| `meld/paths.py:19-48` | `locale_dir()/help_dir()/ui_dir()/icon_dir()` with `#LOCALEDIR#/#HELPDIR#/#SHAREDIR#` tokens (19-24) and in-tree fallbacks (26-30, 39-48) | `meldq/conf.py`: `locale_dir()`, `ui_file()`, `icon_path()` via `importlib.resources`; `help_dir()` not ported (T8.2) |
| `Makefile:8` | Version derived by grepping `meld/meldapp.py:50` (`version = "1.4.0"`) | `meldq/__init__.py:__version__` + `[tool.setuptools.dynamic]` (T8.1) |
| `Makefile:26-28, 39-98` | `all`/`install`: token-substituted `.install` files, hand-copied py/glade/icons, `compileall` (73-74), hicolor icon install (85-96) | `pyproject.toml` package-data + pip (T8.1); hicolor install → `tools/install_desktop.py` (T8.7) |
| `Makefile:100-101` | `intltool-merge` localizes `data/meld.desktop.in` | `tools/build_desktop.py` running `msgfmt --desktop` (T8.7) |
| `Makefile:103-109` + `tools/install_paths:1-10` | `#KEY#` → quoted-path sed filter producing `bin/meld.install`, `meld/paths.py.install` (`SPECIALS`, Makefile:13) | Deleted, no successor (T8.2) |
| `Makefile:131-157` + `tools/make_release:1-52` | svn/freshmeat/gnomefiles release automation (dead hosts) | Not ported; `git tag` + `python -m build` documented in README (T8.7) |
| `tools/check_release:23-52` | Tab lint (stale paths, :24), glade icon-path fixup (:32-48), NEWS-vs-version check against stale `meldapp.py` path (:50) | Not ported (glade fixup meaningless in Qt; lint is CI's job) |
| `INSTALL:20-32` | Doubles as make include: prefix/bindir/libdir/localedir vars; deps pygtk/gnome-python (:45-51) | Deleted; install docs → `README-meldq.md` (T8.7) |
| `po/Makefile:24-26` | `intltool-update --pot` (extracts from .py + .glade + .desktop.in) | `tools/i18n_extract.py` (xgettext over `meldq/**/*.py`) (T8.3) |
| `po/Makefile:32-36` | `msgfmt -c` → `<lang>/LC_MESSAGES/meld.mo`, install under `$(localedir)` | `tools/i18n_compile.py` → `meldq/locale/<lang>/LC_MESSAGES/meld.mo` package data (T8.5) |
| `po/Makevars:9` | `XGETTEXT_OPTIONS = --keyword=_ --keyword=N_ --keyword=N_ngettext:1,2` | Keyword flags in `tools/i18n_extract.py` (T8.3) |
| `po/POTFILES.in:1-21` | Extraction file list: `bin/meld` (:1), `data/meld.desktop.in` (:2), 6 glade files (:3-8), 13 .py files (:9-21) | Replaced by glob of `meldq/**/*.py`; glade+desktop entries feed the frozen reference POT (T8.4) |
| `po/LINGUAS` (34 langs) | Language list | Kept verbatim; read by `tools/i18n_merge.py` / `i18n_compile.py` (T8.5) |
| `po/*.po` (34 catalogs) | Translations | Kept in place; the ONE part of the old tree the new build mutates (msgmerge) (T8.3/T8.5) |
| `data/meld.desktop.in:1-15` | intltool `_Name/_GenericName/_X-GNOME-FullName/_Comment` keys (:3-6), `Encoding=` (:2), `Exec=meld` (:7), `Icon=meld` (:10), `Categories=GNOME;Application;Development;` (:12), `X-GNOME-Bugzilla-*` (:13-15) | New `data/meldq.desktop.in` with plain keys, same three English strings (T8.7) |
| `data/icons/*` (5 xpm, 21 png, hicolor 16/22/32/48 png + svg, .xcf sources) | In-app pixmaps + theme app icons | `meldq/resources/icons/*.png` (+ `meld.svg`); XPMs converted to PNG (T8.6) |
| `meld/meldapp.py:132` | `gtk.window_set_default_icon_name("icon")` (vs desktop `Icon=meld` — mismatch) | `conf.get_app_icon()`; `main.py` calls `app.setWindowIcon(...)` (T8.6) |
| `meld/meldapp.py:438-442` | Help→Contents opens `ghelp:///` + `paths.help_dir("C/meld.xml")`; bug-report opens dead bugzilla URL | `conf.HELP_URL` / `conf.BUG_REPORT_URL` constants; opened via `QDesktopServices.openUrl` in app.py (T8.2) |
| `help/` (entire subtree, 659 loc) | DocBook 4.2 manual (documents meld 0.9.6) + ScrollKeeper | **Descoped** — Help menu links to web docs (T8.2/T8.7) |

### Tasks

---

#### T8.1 — Version single-sourcing + `pyproject.toml` final form

**Old refs:** `Makefile:8` (VERSION grep), `meld/meldapp.py:50` (`version = "1.4.0"`), `tools/check_release:50` (re-parses version from a stale root-relative `meldapp.py` path), `INSTALL:20-32`, `Makefile:39-98` (install inventory), plan §11 (`meld/vc/COPYING` must travel with the vc package).

**Build:**

1. Ensure `meldq/__init__.py` contains exactly one version assignment: `__version__ = "2.0.0a0"`. This is the single source of truth; nothing else in the new tree may contain a version literal.
2. Copy `meld/vc/COPYING` → `meldq/vc/COPYING` (byte-identical; it is the vc package's separate license).
3. Create a stub `README-meldq.md` (expanded in T8.7): one paragraph — "PyQt6 port of Meld 1.4.0. Install: `pip install .` Run: `meldq`."
4. Write `pyproject.toml` at the repo root:

```toml
[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"

[project]
name = "meldq"
dynamic = ["version"]
description = "Visual diff and merge tool (PyQt6 port of Meld 1.4)"
readme = "README-meldq.md"
license = "GPL-2.0-or-later"
requires-python = ">=3.11"
dependencies = ["PyQt6>=6.6"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Environment :: X11 Applications :: Qt",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3.11",
    "Topic :: Software Development :: Version Control",
]

[project.optional-dependencies]
highlight = ["pygments"]
dev = ["pytest", "pytest-qt", "build"]

[project.urls]
Homepage = "https://meldmerge.org"

[project.scripts]
meldq = "meldq.main:main"

[tool.setuptools]
license-files = ["COPYING", "meldq/vc/COPYING"]

[tool.setuptools.packages.find]
include = ["meldq*"]

[tool.setuptools.package-data]
meldq = [
    "resources/icons/*.png",
    "resources/icons/*.svg",
    "ui/*.ui",
    "locale/*/LC_MESSAGES/*.mo",
    "vc/COPYING",
]

[tool.setuptools.dynamic]
version = {attr = "meldq.__version__"}

[tool.pytest.ini_options]
testpaths = ["tests"]
qt_api = "pyqt6"
```

5. Add/extend `.gitignore`: `dist/`, `build/`, `*.egg-info/`, `meldq/locale/`, `po/*.po~`, `__pycache__/`.

**TRAPS:**
- The repo is flat-layout with MULTIPLE top-level packages (`meld/` — the frozen py2 tree — plus `meldq/`, `tests/`, `tools/`). setuptools auto-discovery either errors or, worse, packages `meld/` whose py2 syntax (`bin/meld:90` `except ..., e`) makes pip's install-time byte-compilation spew SyntaxErrors. `packages.find.include = ["meldq*"]` is mandatory, not cosmetic.
- SPDX `license = "GPL-2.0-or-later"` string form requires setuptools ≥ 77 (PEP 639); with older setuptools the build fails on metadata validation — hence the pinned `build-system.requires`.
- `Makefile:8` + `tools/check_release:50` prove version plumbing was grep-based and already drifted (check_release reads `meldapp.py` from the wrong directory). Do not reproduce any regex-over-source versioning — `meldq.__version__` + `dynamic` only.
- `INSTALL:20` sets `PYTHON ?= python` which resolves to python2 on old systems; none of the new tools scripts may shell out to bare `python` — always `sys.executable` (they are run as `python3 tools/...` or via pytest).
- The console script is named `meldq`, NOT `meld` — a distro-installed meld 3.x on PATH must not be shadowed (inventory risk list; also `data/meld.desktop.in:7` `Exec=meld` would collide).
- `meldq/locale/**` and `meldq/resources/icons/**` must match the package-data globs exactly; a silent glob mismatch ships a wheel missing all catalogs with no build error (see T8.5 AC).

**Check:** `python -c "import meldq; print(meldq.__version__)"` → `2.0.0a0`. `pip install -e .` in a clean 3.11 venv succeeds; `pip show meldq` shows version 2.0.0a0 and GPL-2.0-or-later.

---

#### T8.2 — `meldq/conf.py`: resource paths via importlib.resources + gettext runtime

**Old refs:** `meld/paths.py:19-48` (whole file), `bin/meld:63-69` (gettext init), `bin/meld:56-61` (doap sentinel), `bin/meld:71-102` (version gates), `meld/meldapp.py:438-442` (help/bug URLs), `Makefile:103-109` + `tools/install_paths` (the mechanism being killed).

**Build** — this task is a **delta on the WP3-landed `meldq/conf.py`** (T3.1), NOT a rewrite.
WP3's late-bound `_`/`ngettext` + `init_i18n()`, `mnemonic`, `ui_file`, `running_from_source`,
`package_dir`, `icon_path`, and the module-level-Qt-imports-FORBIDDEN rule stay normative and
untouched. Add/change only the following:

```python
# --- constants: add the new ones; APPLICATION_NAME/GETTEXT_DOMAIN/HELP_URL exist from T3.1 ---
APPLICATION_NAME = "Meld"          # gobject.set_application_name("Meld"), meldapp.py:134
DESKTOP_FILE_ID = "meldq"          # basename of data/meldq.desktop.in; see T8.7
GETTEXT_DOMAIN = "meld"            # KEEP "meld": the 34 catalogs' domain; renaming loses them
WEBSITE_URL = "https://meldmerge.org"
HELP_URL = "https://meldmerge.org/help/"          # replaces meldapp.py:439 ghelp:/// URI
BUG_REPORT_URL = "<set to this fork's issue tracker before release>"
# ^ replaces meldapp.py:442 (bugzilla.gnome.org is dead). This OVERRIDES T3.1's verbatim
#   bugzilla URL — update the T3.1 constant in place; do not keep two values.

def resource_path(*parts: str) -> Path:            # add
    return package_dir().joinpath("resources", *parts)

def N_(message: str) -> str:                       # add
    """No-op marker for deferred translation (xgettext keyword, po/Makevars:9)."""
    return message
```

- `locale_dir()` — change in place: prefer `package_dir() / "locale"` (T8.5's compile target)
  when it exists; else keep T3.1's dev fallback `<repo_root>/build/locale` when
  `running_from_source()`; else `None` (`init_i18n()` keeps `fallback=True`).
- `init_i18n()` — extend in place: GUI-launched processes on macOS may have no locale env at
  all; when none of `LANGUAGE`/`LC_ALL`/`LC_MESSAGES`/`LANG` is set, derive
  `languages=[locale.getlocale()[0]]` (guard `ValueError`/`None`) and pass it to
  `gettext.translation(...)`.
- `get_icon()` / `get_app_icon()` arrive in T8.6 (Qt imported ONLY inside the functions).

Extend WP3's `tests/test_conf.py`:
- `test_conf_import_is_qt_free`: `subprocess.run([sys.executable, "-c", "import sys, meldq.conf; sys.exit(1 if [m for m in sys.modules if m.startswith('PyQt6')] else 0)"])` returncode == 0.
- `test_gettext_fallback_without_catalogs`: with `meldq/locale` absent (monkeypatch `locale_dir` to return None and re-run `init_i18n()`), `_("x") == "x"` — no exception (the `fallback=True` contract).
- `test_resource_paths_are_absolute`: `icon_path("x.png").is_absolute()`.

**TRAPS:**
- `meld/paths.py:19-24` tokens are EMPTY in the repo copy — the installed copy differed via `Makefile:103-109`/`tools/install_paths`. Porting the repo file's fallback branch (`paths.py:26-30`) would "work" in-tree and break installed; the whole dual-layout `os.path.exists(..., "data")` switch at `paths.py:39-42, 44-48` must NOT be ported. `importlib.resources.files("meldq")` is correct for editable and wheel installs alike.
- `bin/meld:56-61`: the `meld.doap` sentinel sys.path hack has no successor — do not invent one; entry points import `meldq` off the normal path.
- **Qt-free module rule:** `meldq/util/misc.py` and `meldq/engine/*` import `_` from conf, and the WP0 test suite asserts importing them does not pull PyQt6. Therefore `conf.py` must never import Qt at module scope; T8.6's `get_icon`/`get_app_icon` use function-local imports.
- Import-time `_()` calls exist in ported code (old `meld/preferences.py:262-282` default filters call `_()` in a class-body dict). WP3's late-bound `_` (a module function delegating to the module-global translation) plus T3.9's ordering rule — `conf.init_i18n()` runs before `meldq.app`/`meldq.util.prefs` are imported — handles this; do NOT replace it with an import-time direct `gettext` binding, and do not import prefs before `init_i18n()` in any new tool script.
- `bin/meld:77` — `print _("Cannot import: ") + mod + "\n" + str(e)` references `e` leaked from the `except` clauses at `bin/meld:90/96/101`. Py3 deletes except-targets at block exit; this error path never worked as intended even on py2 rewrites. Rewrite dependency-failure reporting from scratch (WP3's `main.py`); never translate `missing_reqs` literally. Reuse the two msgids `"Cannot import: "` (bin/meld:77) and `"Meld requires %s or higher."` (bin/meld:80) verbatim in main.py's PyQt6-import error path — they are in all 34 catalogs (e.g. fr.po:32-33) and otherwise become T8.4 orphans.
- `bin/meld:90,96,101` use py2 `except (X, Y), e` syntax — the file cannot even be imported under py3; treat it as read-only spec.
- Py3.11 `gettext` removed the `codeset`/`unicode` parameters — do not pass either (2to3-era examples do).
- `bin/meld:66` bound `_ = gettext.gettext` BEFORE `bindtextdomain` (line 68) — that only worked because module-level `gettext.gettext` resolves the default domain lazily. WP3's `_` delegates to the module-global translation at each call, so `init_i18n()` may run any time before the first user-visible string is rendered.

**Check:** `python -m pytest tests/test_conf.py -q` green; the Qt-free subprocess check passes.

---

#### T8.3 — POT extraction pipeline + msgmerge workflow

**Old refs:** `po/Makefile:24-26` (`intltool-update --pot`), `po/Makevars:9` (keywords), `po/POTFILES.in:1-21`, `meld/dirdiff.py:606-612` (the only `ngettext` plural sites), `po/LINGUAS` (34 entries incl. `sr@latin`).

**Build:**

1. `tools/i18n_extract.py` — py3.11, stdlib-only, shells out to `xgettext` (GNU gettext is a build-time requirement; document in README):
   - Signature: `main(argv: list[str] | None = None) -> int`; flags `--output` (default `po/meld.pot`), `--source-root` (default repo root).
   - File list: `sorted(Path("meldq").rglob("*.py"))` — the POTFILES.in mechanism is replaced by a glob so new files can't be silently omitted (`po/POTFILES.in` listed only 13 of the py files).
   - Invocation (one call): `xgettext --language=Python --from-code=UTF-8 --keyword=_ --keyword=N_ --keyword=ngettext:1,2 --add-comments=TRANSLATORS: --sort-by-file --package-name=meldq --package-version=<meldq.__version__> --msgid-bugs-address=<tracker URL> -o po/meld.pot <files...>`.
   - Exit non-zero on xgettext failure; print msgid count on success.
2. `tools/i18n_merge.py` — for each lang read from `po/LINGUAS` (strip comments/blanks): run `msgmerge --update --backup=none --quiet po/<lang>.po po/meld.pot`, then `msgfmt --statistics -o /dev/null po/<lang>.po` capturing stderr; print a per-language translated/fuzzy/untranslated table. Exit non-zero if any msgmerge fails.
3. Commit the generated `po/meld.pot` (regenerated by CI; `tests/test_i18n.py::test_pot_is_fresh` re-runs extraction into a tmp file and asserts the msgid set equals the committed POT's — catches stale commits).

**TRAPS:**
- `po/Makevars:9` declares keyword `N_ngettext:1,2` — a typo fossil; no such callable exists anywhere in the 1.4 tree. The real plural calls are plain `ngettext` (`meld/dirdiff.py:606-612`). Extract with `--keyword=ngettext:1,2`; if you faithfully copy `N_ngettext` and omit `ngettext`, xgettext's Python defaults still catch it — but do not RELY on defaults; be explicit.
- Passing a bare `--keyword` (no value) CLEARS xgettext's default keyword table. Only additive `--keyword=X` forms.
- Omitting `--from-code=UTF-8` makes xgettext abort on the first non-ASCII byte in a source file (the 1.4 strings include `©` and `…`); the failure appears only once such a string is added — bake the flag in from day one.
- `intltool-update --pot` (po/Makefile:25-26) produced ONE POT from py + glade + desktop sources. The new POT contains only Python-source msgids — that is exactly why D8 requires glade wording to be reproduced verbatim in Python code, and why T8.4's reference POT (which does include glade/desktop strings) is a separate artifact.
- `sr@latin.po`: the `@` is legal; iterate `po/LINGUAS` lines verbatim — do not "validate" language codes with `[a-z_]+` regexes.
- Without `--backup=none`, msgmerge litters `po/` with `*.po~` files (gitignored in T8.1, but don't create them).
- GTK stock-labeled actions (`meld/meldapp.py:150-152` Copy/Paste/Find, `:165-166` Stop/Refresh — label `None`) got their visible text from GTK's OWN `gtk20` catalog, not meld's. Their Qt replacements introduce NEW msgids (e.g. `"_Copy"` — hmm, note `"_File"` etc. DO exist, fr.po:745, because glade menus carried them). New msgids are fine (translators fill them later); the gate in T8.4 is one-directional (old ⊆ new) and unaffected.
- Any new script reading `po/`/glade files must `open(..., encoding="utf-8")` — the old `tools/check_release:25` read files without an encoding and would crash py3 on ru.po et al.

**Check:** `python3 tools/i18n_extract.py` writes `po/meld.pot`; `msggrep -K -e 'seconds' po/meld.pot` shows the `msgid_plural "%i seconds"` entry (once WP5's dirdiff port has landed); `python3 tools/i18n_merge.py` runs over all 34 catalogs with zero failures and `git diff --stat po/` shows only reference-comment/line-number churn.

---

#### T8.4 — Frozen 1.4 reference POT + orphaned-msgid gate

**Old refs:** `po/POTFILES.in:1` (bin/meld), `:2` (desktop.in), `:3-8` (6 glade files), `:9-21` (13 py files); `data/meld.desktop.in:3-6`; `data/ui/meldapp.glade:78/100/131`; `po/fr.po:1041` (escape-identity example); `meld/preferences.py:262-282`.

**Build:**

1. `tools/i18n_reference.py` — regenerates the frozen reference; run ONCE and commit the artifact `po/meld-1.4-reference.pot` (the script stays for audit):
   - Part A (Python): `xgettext --language=Python --from-code=UTF-8 --keyword=_ --keyword=N_ --keyword=ngettext:1,2 --add-comments=TRANSLATORS: -o <tmp>/py.pot bin/meld meld/dirdiff.py meld/filediff.py ... ` (the 13 `meld/*.py` entries from `po/POTFILES.in:9-21`, plus `bin/meld` from line 1 — `bin/meld` has no `.py` suffix, so `--language=Python` is mandatory).
   - Part B (Glade): `xgettext --language=Glade --from-code=UTF-8 -o <tmp>/glade.pot data/ui/dirdiff.glade data/ui/filediff.glade data/ui/findbar.glade data/ui/meldapp.glade data/ui/preferences.glade data/ui/vcview.glade` (POTFILES.in:3-8).
   - Part C (Desktop): `sed 's/^_//' data/meld.desktop.in > <tmp>/meld.desktop` then `xgettext --language=Desktop -kName -kGenericName -kComment -kX-GNOME-FullName -o <tmp>/desktop.pot <tmp>/meld.desktop`.
   - Combine: `msgcat --use-first --no-wrap -o po/meld-1.4-reference.pot <tmp>/py.pot <tmp>/glade.pot <tmp>/desktop.pot`.
   - Self-verify (script asserts before writing): reference contains msgids `"_Three Way Compare"` (meldapp.glade:131), `"Choose Files"` (meldapp.glade:100), `"Copyright © 2002-2009 Stephen Kennedy"` (meldapp.glade:78), `"Compare and merge your files"` (desktop.in:6), `"Backups\t1\t#*# .#* ~* *~ *.{orig,bak,swp}\n"` (preferences.py:264), and `"Cannot import: "` (bin/meld:77).
   - Informational cross-check: union of non-obsolete msgids across `po/*.po` (via `msgcat --use-first po/*.po`) minus reference msgids — print as "pre-1.4 leftovers (not gated)".
2. `po/i18n-allowlist.txt` — one PO-escaped msgid per line; `#`-prefixed comment above each entry giving the reason. Initial content: `"Meld Diff Viewer"` (desktop.in:5 `X-GNOME-FullName`, key dropped in T8.7) and `"Open the Meld manual"` / help-only strings ONLY IF app.py genuinely reworded them (try verbatim reuse first). Every later addition needs a reason comment naming the descoping decision (D12 items: strings sourced from `meld/ui/historyentry.py` / `meld/ui/notebooklabel.py` if their replacements have no such UI text).
3. `tools/i18n_check_orphans.py`:
   - Normalize both POTs: `msgcat --no-wrap <pot> -o <tmp>` so every `msgid` is single-line; parse with `re.match(r'^msgid "(.*)"$', line)` (skip the `msgid ""` header; also collect `msgid_plural` lines the same way).
   - `orphans = ref_msgids - new_msgids - allowlist`.
   - Output: one line per orphan `ORPHAN: <po-escaped msgid>`; summary `N orphaned msgids (allowlisted: M)`; exit 1 if `orphans` non-empty, else 0.
4. `tests/test_i18n.py`:
   - `test_no_orphaned_msgids`: runs the check script; asserts rc 0. Mark `@pytest.mark.skipif(shutil.which("xgettext") is None, reason="gettext tools required")` — CI installs gettext.
   - `test_orphan_gate_detects_regressions` (self-test): copy `po/meld.pot` to tmp, delete one known entry (e.g. the `"Backups\t..."` block) with a small PO-aware edit, run the checker against the doctored file via a `--new-pot` flag, assert rc 1 and the msgid appears in stdout.

**TRAPS:**
- **The escape-identity trap this gate exists for:** `po/fr.po:1041` `msgid "CVS keywords\t0\t\\$\\w+(:[^\\n$]+)?\\$\n"` was produced by py2 source `meld/preferences.py:272` `_("CVS keywords\t0\t\$\\w+(:[^\\n$]+)?\$\n")` — where `"\$"` is an INVALID escape (py3.11 SyntaxWarning, future SyntaxError) that py2 passed through as literal backslash-dollar. The porting WP must write `"\\$\\w+(:[^\\n$]+)?\\$\n"` (identical runtime string). Writing `"$\\w+..."` (dropping the backslash) or a raw string with different backslash counts changes the msgid and silently orphans the entry in all 34 catalogs. Same class of hazard throughout `preferences.py:262-282`.
- The 6 glade files are glade-2/libglade format; modern `xgettext --language=Glade` parses `translatable="yes"` properties in both glade1/glade2 — but ONLY those marked translatable (21 in meldapp.glade). If Part B produces < ~100 msgids or the sentinel assertions fail, stop and investigate before committing the reference.
- `data/ui/meldapp.glade:34` is `<property name="text" translatable="yes"></property>` — an EMPTY translatable string; xgettext skips empty msgids, so entry counts won't match intltool's historical POT exactly. The gate compares msgid sets, not counts.
- `data/meld.desktop.in:3-6` uses intltool underscore keys (`_Name` etc.); xgettext's Desktop parser only sees plain keys — the `sed 's/^_//'` preprocessing step is load-bearing. Also: providing ANY `-k` to the Desktop parser drops its default key list, so all four keys must be listed explicitly.
- Comparison granularity: 1.4 uses no `msgctxt` anywhere — msgid-only comparison is sound. Include `msgid_plural` strings in both sets so a dropped plural form is caught (`dirdiff.py:606-612`).
- Do not parse wrapped POT files with line regexes — multi-line `msgid ""` continuations will silently truncate your set. Always normalize through `msgcat --no-wrap` first.
- All file reads in these scripts: `encoding="utf-8"` (see `tools/check_release:25` failure mode).

**Check:** `python3 tools/i18n_reference.py` writes `po/meld-1.4-reference.pot` passing its own sentinel asserts. After WP3–WP7 are merged: `python3 tools/i18n_check_orphans.py` exits 0 with an allowlist containing only documented descoped strings. `python -m pytest tests/test_i18n.py -q` green.

---

#### T8.5 — .mo compilation, packaged locale dir, runtime translation verification

**Old refs:** `po/Makefile:32-36` (msgfmt -c + install layout `<lang>/LC_MESSAGES/meld.mo`), `bin/meld:68-69` (runtime binding), `po/LINGUAS`, `po/fr.po:1018-1021` (verification string).

**Build:**

1. `tools/i18n_compile.py`:
   - Flags: `--lang <code>` (repeatable; default = all of `po/LINGUAS`), `--dest` (default `meldq/locale`).
   - Per language: `mkdir -p meldq/locale/<lang>/LC_MESSAGES` then `msgfmt -c -o meldq/locale/<lang>/LC_MESSAGES/meld.mo po/<lang>.po`.
   - Exit non-zero listing any language whose msgfmt failed; on success print `compiled N/34 catalogs`.
2. `meldq/locale/` stays gitignored (T8.1) — it is a build artifact. Document the build sequence in README (T8.7): `python3 tools/i18n_compile.py && python -m build`.
3. `tests/test_i18n.py` additions (skipif no `msgfmt`):
   - `test_compiled_catalog_translates`: compile ONLY `fr` into a `tmp_path` locale dir, then
     `t = gettext.translation("meld", localedir=tmp, languages=["fr"]); assert t.gettext("Compare and merge your files") == "Comparer et fusionner des fichiers"` (fr.po:36-37) and `assert t.gettext("Backups\t1\t#*# .#* ~* *~ *.{orig,bak,swp}\n").startswith("Sauvegardes")` (fr.po:1020-1021).
   - `test_all_linguas_compile`: run the script for all 34 into tmp; assert 34 `meld.mo` files exist.

**TRAPS:**
- **Domain is `meld`, file is `meld.mo`** — NOT `meldq.mo`. `conf.GETTEXT_DOMAIN = "meld"` must match. A renamed domain does not error: `fallback=True` (T8.2) silently yields English forever. That is why the runtime acceptance check asserts a POSITIVE translation, never just "no exception".
- Keep `msgfmt -c` exactly as `po/Makefile:36` did. If a 2010-era catalog fails modern `-c` (header charset or format-flag strictness), fix the po HEADER (a mechanical metadata edit), never delete `-c` and never touch msgstr bodies.
- A wheel built WITHOUT running `i18n_compile.py` first is a perfectly valid, silently English-only wheel (the package-data glob simply matches nothing). AC 9 counts `.mo` members inside the built wheel to make this impossible to miss.
- `sr@latin` produces the directory `meldq/locale/sr@latin/LC_MESSAGES/` — legal on POSIX (Linux/macOS targets); do not sanitize the `@`.
- Runtime language selection: python `gettext.translation(...)` consults `LANGUAGE`/`LC_ALL`/`LC_MESSAGES`/`LANG` in that order — testing with `LANG=fr_FR.UTF-8` alone can be overridden by an inherited `LANGUAGE` var in the dev's shell; the manual check below uses `LANGUAGE=fr` for determinism.

**Check:** `python3 tools/i18n_compile.py` → `compiled 34/34 catalogs`; `LANGUAGE=fr python -c "from meldq.conf import _; s=_('Compare and merge your files'); print(s); assert s != 'Compare and merge your files'"` prints the French string.

---

#### T8.6 — Icons: XPM→PNG conversion, bundled resources, `get_icon()` per D11

**Old refs:** `bin/meld:111` (icon-theme search-path registration), `meld/filediff.py:466-471` (5 XPM linkmap pixbufs), `meld/tree.py:30-38` (9 tree pixbufs at import time), `meld/dirdiff.py:103` (`tree-file-newer.png`), `meld/vcview.py:127-142` (icon-named actions) + `:157` (`icon_name = stock_id` trick), `meld/meldapp.py:132` (`window_set_default_icon_name("icon")`), `:498/:515/:550` (tab icon names `tree-folder-normal`/`tree-file-normal`/`vc-icon`), `meld/ui/gnomeglade.py:120` (`load_pixbuf` scaler), `Makefile:81-96` (what shipped where), `data/ui/meldapp.glade:8/75/96/102` (`../icons/icon.png` window/about images).

**Build:**

1. `tools/convert_xpm_icons.py` — one-shot converter (committed for audit): sets `os.environ["QT_QPA_PLATFORM"] = "offscreen"`, creates a `QGuiApplication([])`, then for each of `data/icons/button_apply0.xpm, button_apply1.xpm, button_copy0.xpm, button_copy1.xpm, button_delete.xpm`: `img = QImage(str(src)); assert not img.isNull(); img.save(str(dst_png))`. No ImageMagick dependency — PyQt6 reads XPM natively.
2. Populate `meldq/resources/icons/` (all committed; every filename explicit):
   - Converted: `button_apply0.png`, `button_apply1.png`, `button_copy0.png`, `button_copy1.png`, `button_delete.png` (stems kept verbatim so filediff's WP maps 1:1 from `filediff.py:467-471`).
   - Copied from `data/icons/`: `tree-file-changed.png`, `tree-file-missing.png`, `tree-file-new.png`, `tree-file-newer.png`, `tree-file-normal.png`, `tree-folder-changed.png`, `tree-folder-missing.png`, `tree-folder-new.png`, `tree-folder-normal.png`, `vc-add-24.png`, `vc-commit-24.png`, `vc-remove-24.png`, `vc-resolve-24.png`, `vc-update-24.png`, `vc-icon.png`, `filter-ignored-24.png`, `filter-modified-24.png`, `filter-nonvc-24.png`, `filter-normal-24.png`, `icon.png`.
   - App icons: `data/icons/16x16/meld.png`→`meld-16.png`, `22x22/meld.png`→`meld-22.png`, `32x32/meld.png`→`meld-32.png`, `48x48/meld.png`→`meld-48.png`, `48x48/meld.svg`→`meld.svg`.
3. Add to `meldq/conf.py` (Qt imported ONLY inside the functions):

```python
# gtk stock id -> freedesktop theme name (the D11 mapping; complete for every stock ref in the 1.4 tree)
GTK_STOCK_TO_THEME: dict[str, str] = {
    "gtk-about": "help-about",  "gtk-add": "list-add",  "gtk-apply": "dialog-ok-apply",
    "gtk-cancel": "dialog-cancel",  "gtk-clear": "edit-clear",  "gtk-close": "window-close",
    "gtk-copy": "edit-copy",  "gtk-cut": "edit-cut",  "gtk-delete": "edit-delete",
    "gtk-dialog-error": "dialog-error",  "gtk-dialog-info": "dialog-information",
    "gtk-dialog-warning": "dialog-warning",  "gtk-find": "edit-find",
    "gtk-find-and-replace": "edit-find-replace",  "gtk-go-back": "go-previous",
    "gtk-go-down": "go-down",  "gtk-go-forward": "go-next",  "gtk-go-up": "go-up",
    "gtk-goto-bottom": "go-bottom",  "gtk-goto-first": "go-first",  "gtk-goto-last": "go-last",
    "gtk-help": "help-contents",  "gtk-info": "dialog-information",
    "gtk-italic": "format-text-italic",  "gtk-new": "document-new",  "gtk-no": "dialog-no",
    "gtk-ok": "dialog-ok",  "gtk-open": "document-open",  "gtk-paste": "edit-paste",
    "gtk-preferences": "preferences-system",  "gtk-quit": "application-exit",
    "gtk-redo": "edit-redo",  "gtk-refresh": "view-refresh",  "gtk-remove": "list-remove",
    "gtk-revert-to-saved": "document-revert",  "gtk-save": "document-save",
    "gtk-save-as": "document-save-as",  "gtk-stop": "process-stop",  "gtk-undo": "edit-undo",
}
# theme name -> QStyle.StandardPixmap attribute name, for non-Linux fallback
_QSTYLE_FALLBACK: dict[str, str] = {
    "window-close": "SP_TitleBarCloseButton", "document-open": "SP_DialogOpenButton",
    "document-save": "SP_DialogSaveButton", "dialog-error": "SP_MessageBoxCritical",
    "dialog-information": "SP_MessageBoxInformation", "dialog-warning": "SP_MessageBoxWarning",
    "go-previous": "SP_ArrowBack", "go-next": "SP_ArrowForward",
    "go-up": "SP_ArrowUp", "go-down": "SP_ArrowDown",
    "view-refresh": "SP_BrowserReload", "process-stop": "SP_BrowserStop",
    "dialog-cancel": "SP_DialogCancelButton", "dialog-ok": "SP_DialogOkButton",
    "help-contents": "SP_DialogHelpButton",
}

def get_icon(name: str) -> "QIcon":
    """Resolve gtk stock ids, freedesktop names, or bundled file stems to a QIcon.
    Chain: theme lookup -> bundled resources/icons/<name>.png -> QStyle standard icon -> null QIcon."""
    from PyQt6.QtGui import QIcon
    theme_name = GTK_STOCK_TO_THEME.get(name, name)
    icon = QIcon.fromTheme(theme_name)
    if not icon.isNull():
        return icon
    for stem in (name, theme_name):
        p = icon_path(stem + ".png")
        if p.is_file():
            return QIcon(str(p))
    sp_name = _QSTYLE_FALLBACK.get(theme_name)
    if sp_name is not None:
        from PyQt6.QtWidgets import QApplication, QStyle
        app = QApplication.instance()
        if app is not None and isinstance(app, QApplication):
            return app.style().standardIcon(getattr(QStyle.StandardPixmap, sp_name))
    return QIcon()

def get_app_icon() -> "QIcon":
    from PyQt6.QtGui import QIcon
    icon = QIcon()
    for f in ("meld-16.png", "meld-22.png", "meld-32.png", "meld-48.png", "meld.svg"):
        p = icon_path(f)
        if p.is_file():
            icon.addFile(str(p))
    return icon
```

4. `tests/test_icons.py` (uses pytest-qt's `qapp` fixture with `QT_QPA_PLATFORM=offscreen`):
   - `test_all_bundled_icons_present_and_loadable`: hard-coded list of the 30 filenames above; each `icon_path(f).is_file()` and `QImage(str(...))` not null.
   - `test_get_icon_bundled_name`: `conf.get_icon("tree-file-normal")` → `not isNull()`.
   - `test_get_icon_stock_id`: `conf.get_icon("gtk-close")` → returns a `QIcon` and (with `qapp` live) `not isNull()` — exercises theme-or-QStyle chain on any platform.
   - `test_app_icon`: `conf.get_app_icon().availableSizes()` non-empty or svg present.

**TRAPS:**
- `bin/meld:111` made bare names like `"vc-icon"` resolvable as THEME icons by appending `data/icons` to GTK's icon-theme search path — that is why `meld/meldapp.py:550` and `meld/ui/notebooklabel.py:67` (`gtk.image_new_from_icon_name`) work. `QIcon.fromTheme` will NEVER find these; without the bundled-file fallback branch in `get_icon`, every tab icon silently vanishes (null QIcon renders as blank — no exception).
- `meld/vcview.py:127-142` registers icon FILE stems (`"vc-commit-24"`) in the gtk.Action `stock_id` slot, and `vcview.py:157` copies `stock_id` into `icon_name` on each toolbar button — a GTK-only indirection. In Qt these are plain `get_icon("vc-commit-24")` calls; do not build any stock-id registry.
- `meld/tree.py:30-38` and `meld/dirdiff.py:103` scale pixbufs at IMPORT time via the `size` parameter of `gnomeglade.py:120 load_pixbuf` (14/20 px). Scaling is consumer behavior — ship original-size PNGs; consuming WPs scale via `QIcon.pixmap(QSize(...))`. Do not pre-scale assets.
- **App-icon mismatch (D11):** `meldapp.py:132` sets icon name `"icon"` → `data/icons/icon.png`, while `data/meld.desktop.in:10` declares `Icon=meld` → the hicolor `meld.png` set. These are two DIFFERENT images. Resolution: window icon = `get_app_icon()` (hicolor set, wired in WP3's `main.py` via `app.setWindowIcon(conf.get_app_icon())`), desktop `Icon=meldq` (T8.7). `icon.png` is kept solely as the About-dialog logo (`meldapp.glade:96`).
- `Makefile:81-84` shipped `*.xpm` and `*.png` from `data/icons`; the GIMP `.xcf` sources (`16x16/meld.xcf`, `22x22/meld.xcf`) were never shipped — do not copy them into `meldq/resources`.
- `data/icons/vc-checkout-24.png` is referenced by zero code and zero glade lines (verified by grep over `meld/` and `data/ui/`) — dead asset, do not copy.
- `data/icons/32x32/meld.svg` duplicates `48x48/meld.svg` — ship one svg (`meld.svg`).
- `QStyle.standardIcon` needs a `QtWidgets.QApplication` (a plain `QGuiApplication` has no `.style()`); guard with `QApplication.instance()` as shown or headless engine tests that touch conf will crash.
- PyQt6 has NO `pyrcc` (removed upstream) — do not attempt `.qrc` compilation; plain package-data files via `icon_path()` are the strategy (inventory risk list).

**Check:** `python -m pytest tests/test_icons.py -q` green; `python3 tools/convert_xpm_icons.py` is idempotent (re-run produces byte-identical PNGs or cleanly overwrites).

---

#### T8.7 — Desktop file, Linux install helper, macOS story, README

**Old refs:** `data/meld.desktop.in:1-15`, `Makefile:100-101` (intltool-merge), `Makefile:51-57, 85-96` (applications/pixmaps/hicolor install), `help/Makefile:4` (broken lang list `C de es fr`), `meld/meldapp.py:438-442` (help/bug handlers), `po/fr.po:36-49` (proof the three desktop msgids are translated).

**Build:**

1. `data/meldq.desktop.in` (plain keys — msgids byte-identical to 1.4 so the 34 catalogs localize it):

```ini
[Desktop Entry]
Name=Meld
GenericName=Diff Viewer
Comment=Compare and merge your files
Exec=meldq %F
Terminal=false
Type=Application
Icon=meldq
StartupNotify=true
StartupWMClass=meldq
Categories=Qt;Development;
```

2. `tools/build_desktop.py`: runs `msgfmt --desktop --template=data/meldq.desktop.in -d po -o data/meldq.desktop`; asserts the output contains `Name[fr]=` and `Comment[fr]=Comparer et fusionner des fichiers`; runs `desktop-file-validate data/meldq.desktop` if that tool is on PATH (warn, don't fail, when absent).
3. `tools/install_desktop.py` (Linux only; exits 0 with a message on darwin):
   - `--user` (default): install `data/meldq.desktop` → `~/.local/share/applications/meldq.desktop`, rewriting `Exec=` to the ABSOLUTE path of the `meldq` script (resolve `shutil.which("meldq")`, else `Path(sys.executable).with_name("meldq")`; error out if neither exists).
   - Icons: `meldq/resources/icons/meld-{16,22,32,48}.png` → `~/.local/share/icons/hicolor/{16x16,22x22,32x32,48x48}/apps/meldq.png`; `meld.svg` → `.../scalable/apps/meldq.svg`.
   - Best-effort `update-desktop-database ~/.local/share/applications` and `gtk-update-icon-cache` (ignore failures).
   - `--prefix <dir>` variant for system/distro use (writes under `<prefix>/share/...`, no Exec rewrite).
4. Expand `README-meldq.md`: install (`pip install .`), build-from-source sequence (`python3 tools/i18n_compile.py && python -m build`), dev setup (`pip install -e .[dev]`, gettext tools requirement), Linux desktop integration (`tools/install_desktop.py --user`, plus the warning that venv installs need the Exec rewrite), release procedure (`git tag v$(python -c 'import meldq; print(meldq.__version__)')` + `python -m build`), and an explicit **macOS launch story**: the app runs as the `meldq` console script from Terminal; no `.app` bundle, no Info.plist, no dock icon polish in this release — **py2app/briefcase packaging is deliberately deferred** to a future WP.
5. Confirm `conf.HELP_URL`/`conf.BUG_REPORT_URL`/`conf.WEBSITE_URL` (T8.2) are what `meldq/app.py`'s Help menu uses (WP3 contract: Help→Contents = `QDesktopServices.openUrl(QUrl(conf.HELP_URL))`; there is no bundled manual).

**TRAPS:**
- `data/meld.desktop.in:2` `Encoding=UTF-8` is deprecated (drop); `:12` `Categories=GNOME;Application;Development;` — `Application` is not a registered freedesktop category and `GNOME` is wrong for a Qt app; `:13-15` `X-GNOME-Bugzilla-*` keys are dead GNOME infra. None of these survive.
- `:5` `_X-GNOME-FullName=Meld Diff Viewer` is dropped → its msgid `"Meld Diff Viewer"` must be in `po/i18n-allowlist.txt` (T8.4) or the gate fails.
- The three surviving strings must be byte-identical to 1.4: `Meld` / `Diff Viewer` / `Compare and merge your files` — fr.po:36-43 proves the translations exist; any rewording silently drops every `Name[xx]`/`Comment[xx]` line from the generated file (msgfmt emits localized keys only for msgids it finds in the catalogs — no error otherwise).
- `msgfmt --desktop` requires PLAIN keys in the template; feeding it the old underscore-key file yields an output with the `_Name` lines passed through untranslated — check the generated file, not just the exit code.
- Old `Exec=meld` (desktop.in:7) had no field code, so drag-and-drop/„open with" never passed files; `Exec=meldq %F` fixes that. `Exec=meldq` also assumes PATH visibility — pip `--user`/venv installs break launchers (inventory risk), hence the absolute-path rewrite in `install_desktop.py`.
- Without `StartupWMClass=meldq` AND `QGuiApplication.setDesktopFileName("meldq")` in `main.py` (note for WP3 — `conf.DESKTOP_FILE_ID` exists for this), Linux taskbars fail to match the running window to the launcher and show a generic icon.
- `help/Makefile:4` lists `C de es fr` but `help/de/` contains only `.po` files and no Makefile — `make -C help` has been silently broken (for-loop masks the error). Do not attempt to salvage the help build; help/ is descoped (D12), translations of the manual are accepted losses.
- `meldapp.py:442` points at `bugzilla.gnome.org` (retired) — `BUG_REPORT_URL` must be this fork's tracker, not a ported dead link.

**Check:** `python3 tools/build_desktop.py` produces `data/meldq.desktop` containing `Comment[fr]=Comparer et fusionner des fichiers`; on a Linux box `python3 tools/install_desktop.py --user` then `gio launch ~/.local/share/applications/meldq.desktop` starts the app.

---

### Contracts consumed / provided

**Consumed:**
- `meldq/__init__.py` skeleton and the engine/util Qt-free-import test discipline (WP0).
- `meldq/main.py: def main(argv: list[str] | None = None) -> int` (WP3) — target of `[project.scripts]`; WP3's main is expected to call `conf.init_i18n()` first, set `app.setWindowIcon(conf.get_app_icon())`, and call `QGuiApplication.setDesktopFileName(conf.DESKTOP_FILE_ID)`.
- Every user-visible string in WP2–WP7 wrapped in `_()`/`ngettext()` from `meldq.conf`, reusing 1.4 wording verbatim (D8) — the T8.4 gate audits this.

**Provided (normative for all other WPs):**
- `meldq.conf`: `_`, `ngettext`, `N_`, `init_i18n()`, `mnemonic()`, `running_from_source()`, `GETTEXT_DOMAIN="meld"`, `APPLICATION_NAME`, `DESKTOP_FILE_ID`, `WEBSITE_URL`, `HELP_URL`, `BUG_REPORT_URL`, `package_dir()`, `resource_path()`, `icon_path(name)`, `ui_file(name)`, `locale_dir()`, `get_icon(name) -> QIcon`, `get_app_icon() -> QIcon`, `GTK_STOCK_TO_THEME`.
- `meldq.__version__` as the single version truth (about dialog, `--version`, packaging all read it).
- `pyproject.toml` with `meldq` console script, `highlight` extra (pygments — D10's follow-up feature keys off it), package-data globs for `ui/*.ui`, icons, locale.
- Tools: `tools/i18n_extract.py`, `tools/i18n_merge.py`, `tools/i18n_compile.py`, `tools/i18n_reference.py`, `tools/i18n_check_orphans.py`, `tools/convert_xpm_icons.py`, `tools/build_desktop.py`, `tools/install_desktop.py`.
- Artifacts: `po/meld.pot`, `po/meld-1.4-reference.pot` (frozen), `po/i18n-allowlist.txt`, `meldq/resources/icons/*` (30 files), `data/meldq.desktop.in`.

### Deleted (do-not-port list)

*(Old files stay in-repo as the reference spec; "deleted" = no successor in the new build.)*

- `Makefile` (all 166 lines) — replaced by pyproject/pip; release targets (:131-157) reference dead hosts (svn.gnome.org, freshmeat.net, gnomefiles.org).
- `INSTALL` as a make-include (:20-32) — pyproject metadata; its dependency docs (:42-55, pygtk/gnome-python/pygtksourceview) are obsolete.
- `tools/install_paths` + the `#TOKEN#`/`SPECIALS` mechanism (Makefile:13, :103-109; paths.py:19-24; bin/meld:60) — importlib.resources makes install-time file rewriting unnecessary.
- `tools/check_release` — the glade icon-path fixup (:32-48) has no Qt analog; tab lint and NEWS checks belong to CI; the file also has py2 prints (:29,37,40,52) and stale paths (:24,:50).
- `tools/make_release` — dead infra; also hard py3 breakage (`raise "Command error!"` :38, `string.replace` :41).
- `po/Makefile`, `po/Makevars`, `po/POTFILES.in` — intltool is abandonware; replaced by the T8.3/T8.5 scripts (`po/LINGUAS` and all 34 `.po` files are KEPT).
- `bin/meld` — py2-only syntax (:90,96,101), leaked-except bug (:77), pychecker (:34-38), GNOME `--sm-*` stripping (:41-46, Qt handles `-session` natively), `Unbuffered` stdout wrapper (:23-31), `profile` module usage (:119-123); superseded by the entry point.
- `meld/paths.py` — replaced by `conf` resource helpers; `help_dir()` (:35-36) has no successor at all.
- `help/` subtree (DocBook 4.2 + ScrollKeeper OMF + xml2po translations) — dead toolchain, documents meld 0.9.6; Help menu links to `conf.HELP_URL` instead. The de/es/fr/oc/sv help translations are accepted losses (D12).
- `intltool-merge` desktop localization (Makefile:100-101) → `msgfmt --desktop`.
- `data/meld.desktop.in` GNOME-isms: `Encoding=` (:2), `_X-GNOME-FullName` (:5), `Categories=GNOME;Application` (:12), `X-GNOME-Bugzilla-*` (:13-15).
- `data/icons/vc-checkout-24.png` (referenced nowhere) and all `.xcf` sources — not shipped.
- `meld.doap` sys.path sentinel (bin/meld:56-61) — moot under entry points.
- GNOME hicolor install for `Application`-category launchers via Makefile — replaced by opt-in `tools/install_desktop.py`.

### Acceptance criteria

1. **Version single-sourcing:** `python -c "import meldq; print(meldq.__version__)"` prints `2.0.0a0`; `grep -rn "2\.0\.0a0" meldq/ pyproject.toml` matches ONLY `meldq/__init__.py`.
2. **Install + entry point:** in a fresh Python 3.11 venv, `pip install -e .[dev,highlight]` succeeds; `command -v meldq` resolves; `meldq --version` prints `2.0.0a0` (requires WP3) and `meldq --help` exits 0.
3. **Qt-free conf:** `python -c "import sys, meldq.conf; sys.exit(1 if [m for m in sys.modules if m.startswith('PyQt6')] else 0)"` exits 0.
4. **Extraction:** `python3 tools/i18n_extract.py` regenerates `po/meld.pot` deterministically (running twice yields identical msgid sets); `pytest tests/test_i18n.py::test_pot_is_fresh -q` passes.
5. **Reference POT:** `po/meld-1.4-reference.pot` is committed and contains all six sentinel msgids listed in T8.4 (verify: `msggrep -K -e 'Three Way Compare' po/meld-1.4-reference.pot` non-empty, etc.).
6. **Orphan gate (translation preservation — the WP's headline gate):** with WP2–WP7 merged, `python3 tools/i18n_check_orphans.py` exits 0, and every entry in `po/i18n-allowlist.txt` carries a `#` reason comment naming a descoping decision. Self-test: `pytest tests/test_i18n.py::test_orphan_gate_detects_regressions -q` proves the gate exits 1 when a msgid is removed.
7. **msgmerge round-trip:** `python3 tools/i18n_merge.py` completes for all 34 languages with 0 failures; afterwards `msggrep -K -e '^Compare and merge your files$' po/fr.po` still shows msgstr `Comparer et fusionner des fichiers` (translations preserved, not fuzzied away).
8. **Catalog compile + runtime:** `python3 tools/i18n_compile.py` reports `compiled 34/34`; `LANGUAGE=fr python -c "from meldq.conf import _; s=_('Compare and merge your files'); assert s=='Comparer et fusionner des fichiers', s"` exits 0.
9. **Wheel completeness:** after `python3 tools/i18n_compile.py && python -m build`, `python -c "import zipfile,glob; names=zipfile.ZipFile(glob.glob('dist/meldq-2.0.0a0-*.whl')[0]).namelist(); print(sum(n.endswith('meld.mo') for n in names), sum('resources/icons/' in n for n in names))"` prints `34` and `>= 30`; the wheel contains no `meld/` (old-tree) modules and no `.xpm`/`.xcf` files.
10. **Icons:** `python -m pytest tests/test_icons.py -q` green (all 30 bundled files load via QImage offscreen; `get_icon` resolves a bundled stem, a gtk stock id, and returns non-null under a live QApplication).
11. **Desktop file:** `python3 tools/build_desktop.py` generates `data/meldq.desktop` with `Comment[fr]=Comparer et fusionner des fichiers` and no `_`-prefixed or `X-GNOME-*` keys; `desktop-file-validate` (where installed) reports no errors.
12. **Linux desktop integration (manual):** `python3 tools/install_desktop.py --user` on Linux installs launcher + 5 hicolor icons; `gio launch ~/.local/share/applications/meldq.desktop` opens the Meld window with the meld icon in the taskbar (requires WP3).
13. **macOS (manual):** on macOS, `meldq` from Terminal launches the app; README-meldq.md contains the explicit statement that `.app` bundling (py2app/briefcase) is deferred.
14. **Full suite:** `python -m pytest tests/test_conf.py tests/test_i18n.py tests/test_icons.py -q` passes on Linux and macOS (gettext-tool-dependent tests skip cleanly where `xgettext`/`msgfmt` are absent, and CI installs them so nothing skips there).

### Estimated effort

**4–6 person-days** (matches the survey's 3–6 pd for the build/i18n/packaging subsystem: ~1 pd packaging + conf, ~2 pd i18n pipeline + reference POT + gate, ~1 pd icons, ~1 pd desktop/README/acceptance; the orphan-gate reconciliation after WP3–WP7 merge is the elastic part).

---

## WP9 — Hardening, parity audit, and release readiness

### Goal
Turn "all WPs landed" into "the port is trustworthy": behavioral parity against the 1.4
feature list, encoding/scale torture, and packaging smoke on both platforms.

### Dependencies
WP2–WP8 (everything).

### Tasks

**T9.1 — Parity audit against 1.4.**
Walk `data/ui/*.glade` + `data/ui/*-ui.xml` (menus/toolbars/dialogs) and
`meld/meldapp.py:602-647` (CLI) and produce `docs/PARITY.md`: every 1.4 user-visible
capability → ported / changed (how) / dropped (why — must cite a descope decision).
Anything unintentionally missing becomes a fix task in this WP.

**T9.2 — Encoding & filesystem torture tests.**
Extend `tests/fixtures/encodings/`: latin-1, utf-8 (with astral-plane chars), utf-16,
binary (NUL sniff), mixed CRLF/LF, missing-trailing-newline; non-UTF-8 filename test
(Linux only, `os.fsencode`-constructed, `pytest.mark.skipif` elsewhere). Assert: load →
edit → save round-trips bytes exactly except intended edits; binary detection warns, not
crashes; astral chars don't desync inline highlights (UTF-16 offset audit from WP6).

**T9.3 — Scale checks.**
Scripted (not CI-gated) benchmark: 100k-line file pair with 1k chunks — initial diff
< 10 s, scroll stays interactive, re-diff after single-line edit < 500 ms; dirdiff over
a tree with 10k entries stays responsive (scheduler yields). Record numbers in
`docs/PARITY.md`; regressions are judgment calls, not hard gates.

**T9.4 — Cross-platform smoke.**
On macOS and Linux: `pip install .` into a clean venv → launch all four comparison
types → quit cleanly (no dangling QTimer warnings). Verify menu accelerators don't
collide with macOS system shortcuts; verify `QIcon.fromTheme` fallback icons appear on
macOS (no icon theme).

**T9.5 — Translation pipeline proof.**
Run the WP8 msgid check: regenerate POT from `meldq/`, `msgmerge` against 3
representative catalogs (uk, de, fr), assert 0 orphaned msgids caused by wording drift
(new strings are allowed, reworded ones are not). Compile catalogs and launch with
`LANGUAGE=uk` — spot-check menus are translated.

**T9.6 — Final sweep.**
`grep -rn "gtk\|gobject\|pango\|gconf\|glade" meldq/` returns nothing;
`python -m pytest tests/ -q` green; tag `v2.0.0-alpha1` (do not push without user ack).

### Acceptance criteria
1. `docs/PARITY.md` exists, complete, with benchmark numbers.
2. All torture/scale/smoke checks pass or have recorded, user-acknowledged deviations.
3. Zero GTK-era identifiers in `meldq/`.

### Estimated effort
5–8 pd.
