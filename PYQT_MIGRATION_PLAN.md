# Meld 1.4.0 → PyQt6 Migration Plan

*Based on a full-source survey of the tree at tag `release-1_4_0` (~9,900 LOC Python,
6 glade files, 4 UIManager XML files, 34 translation catalogs). Every `.py` file, glade
file, and build script was read; all toolkit imports verified covered.*

---

## 1. Executive summary

Meld 1.4.0 is a Python 2 + PyGTK/GTK2 + libglade application built by a hand-written
Makefile with gettext/intltool i18n. A PyQt6 port is **two migrations in one**: Python 2→3
and GTK2→Qt6, and since PyGTK doesn't exist on Python 3, it is a **cutover, not a gradual
in-place migration** — the practical strategy is a bottom-up rebuild in a new package tree,
reusing the engine nearly verbatim.

**The good news** — the architecture is cleanly layered:

| Layer | Purity | Fate |
|---|---|---|
| Diff engine (`matchers`, `merge`) | 100% toolkit-free | Copy as-is (py3 fixes only) |
| Diff model (`diffutil`), undo (`undo`), scheduler (`task`) | 90–100% | GObject → QObject/pyqtSignal seam only |
| VC plugins (`vc/*.py`, 13 backends) | ~98% | py3 bytes/str work, two small GTK leaks |
| Views (`filediff`, `dirdiff`, `vcview`, `meldapp`) | 30–60% | Real Qt rework |
| Custom widgets (`meld/ui/*`) | ~0% | Half deleted (Qt has built-ins), half rewritten |
| Build/i18n (Makefile, intltool, glade XML) | — | Replaced wholesale (pyproject + xgettext) |

**Total estimated effort: ~65–110 person-days** (≈ 3–5 months for one full-time developer),
dominated by `filediff` (18–30 pd) and cross-cutting infrastructure (12–20 pd).

**The two genuinely hard problems** (everything else is mechanical or well-trodden):

1. **The text-comparison machinery** — chunk backgrounds painted *under* text, pixel-based
   synchronized proportional scrolling, and the linkmap bezier canvas assume GTK's
   pixel-valued adjustments and TextIter model. QPlainTextEdit's scrollbar is
   block-indexed, not pixel-indexed. Feasible, but needs a validating spike **first**.
2. **The undo model** — Meld captures deleted text in a *before*-delete signal handler to
   build its own cross-pane undo stack with save-point checkpoints. Qt only reports changes
   *after* the fact (`contentsChange`). This is a redesign, not a translation.

**Licensing note:** PyQt6 is GPLv3/commercial. Meld is "GPLv2 or later", so the combination
is distributable under GPLv3 — fine, but it effectively pins distribution at v3. If LGPL
matters, PySide6 is API-near-identical (`Signal` vs `pyqtSignal`, minor enum paths) and the
whole plan applies unchanged.

**Context note:** 1.4.0 is the 2010 codebase. Its small size (10k LOC vs ~35k for modern
GTK4 Meld) makes it the right porting base, but it lacks 15 years of upstream diff/VC
fixes; cherry-picking engine fixes from meld 3.x is possible later since the engine files
survived largely intact upstream.

---

## 2. Current architecture (survey findings)

```
bin/meld                    launcher: sys.path setup (meld.doap sentinel!), gettext + glade textdomain
meld/
  matchers.py    (263)      Myers O(NP) diff — pure, generator-incremental
  diffutil.py    (443)      Differ: chunk model, merge cache — GObject only for 'diffs-changed' signal
  merge.py       (257)      3-way auto-merge — pure
  undo.py        (248)      UndoSequence + checkpoints — GObject only for 3 signals
  task.py        (222)      FifoScheduler/LifoScheduler — pure; THE concurrency model
  misc.py        (357)      grab-bag: ~80 lines GTK dialogs/menus + pure path/shell helpers
  meldapp.py     (647)      main window, notebook, UIManager, prefs dialog, new-comparison dialog
  melddoc.py     (142)      doc base: scheduler + UIManager merge on tab switch
  filediff.py   (1502)      2/3-pane text diff: TextViews, tags, sync scroll, linkmap drawing
  filemerge.py   (136)      auto-merge variant of filediff
  diffmap.py     (151)      overview bar (expose-event cairo drawing, scrollbar geometry)
  dirdiff.py    (1043)      dir comparison: 3 TreeViews on one TreeStore, scan generator
  tree.py        (160)      DiffTreeStore: interleaved per-pane columns, Pango markup in model
  vcview.py      (652)      VC browser: TreeView + console + commit dialog
  vc/*.py      (~1900)      13 subprocess/regex VCS backends — nearly pure
  ui/                       gnomeglade.Component (glade autoconnect base for EVERYTHING),
                            findbar, historyentry (gconf), msgarea, notebooklabel, wraplabel
  util/prefs.py  (244)      gconf backend, ConfigParser ~/.meld/meldrc.ini fallback
  util/sourceviewer.py      4-generation gtksourceview shim (optional syntax highlighting)
data/ui/*.glade             glade-2/libglade format, 21 Custom creation_function hooks
data/ui/*-ui.xml            GtkUIManager merge XML (menus/toolbars per document type)
```

**Architectural keystone:** there are *no threads* anywhere. All concurrency is
cooperative: generators yielding every N iterations, pumped by a single
`gobject.idle_add(scheduler)` loop. This transfers to Qt cleanly (a 0 ms `QTimer` that
stops when idle) and must be preserved — every subsystem's port depends on it.

**Coupling hub:** `gnomeglade.Component` (glade XML load + name-based `on_widget__signal`
autoconnect + `__getattr__` widget access) is the base class of every view. Its replacement
is on the critical path of the entire port.

---

## 3. Decisions to make before porting (D1–D12)

### D1. Editor widget: QPlainTextEdit subclass *(recommended)* vs QScintilla
QPlainTextEdit offers per-block geometry (`firstVisibleBlock`, `blockBoundingGeometry`),
`ExtraSelections` for full-width line fills, and a paintable viewport — everything the
chunk rendering needs, in the same document/cursor idiom the code already uses.
QScintilla brings line numbers/highlighting for free but fights the TextBuffer-centric
design of `filediff.py` and adds a heavyweight dependency.
**Prototype first (Spike S1)** — the sweep flagged that if under-text chunk borders can't
be layered acceptably in `paintEvent`, the widget choice itself is invalidated.

### D2. Undo: adopt QTextDocument undo + rebuild grouping/checkpoints on top
Options: (a) shadow buffers to reconstruct deleted text, (b) adopt Qt's per-document undo
stacks and re-implement cross-pane grouping (`beginEditBlock`/`endEditBlock`) plus the
`checkpointed` modified-flag protocol on `modificationChanged`. **(b) recommended** — less
code, native behavior; the casualty is exact GTK-era undo grouping semantics. Do *not* use
`QUndoStack`: Meld's per-buffer checkpoints spanning a shared multi-buffer stack don't fit it.

### D3. Action-merging layer replacing gtk.UIManager — design ONCE, first
Qt has no declarative menu/toolbar XML merging. All four document types
(filediff/dirdiff/vcview/filemerge) merge their actions into the shared window on tab
switch. Replacement: each doc exposes `get_actions()/get_menus()`; the shell swaps QMenu
sections/QToolBar contents on `QTabWidget.currentChanged`. The placeholder layout in
`data/ui/meldapp-ui.xml` is the spec. **This blocks every view port — settle it in Phase 2.**

### D4. Scheduler pump: keep task.py, drive with a self-stopping QTimer(0)
`task.py` ports without modification (py3 `.next()` fixes aside). The pump must *stop* on
empty task list and restart from the scheduler's `runnable` callback — a naive always-on
0 ms timer busy-spins at idle; a naive `idle_add` transliteration starves repaints.

### D5. Tree model: one QStandardItemModel + roles, shared by dirdiff and vcview
Kill two GTK artifacts at once: the interleaved `ntree × ncol` column packing and
**Pango-markup-strings-stored-in-the-model** (`tree.py` textstyle, `_vc.Entry.states`).
Replace with one column per pane and `Qt.ForegroundRole`/`Qt.FontRole`/custom roles.
Do **not** port markup as an HTML delegate — selection, eliding, and row height all regress.
`DiffTreeStore` is shared by dirdiff and vcview: port it once, with both consumers in view.
**Prototype (Spike S2):** 3 QTreeViews sharing one model via `setTreePosition(pane)` +
hidden columns is uncommon Qt — verify rendering before committing; fallback (3 mirrored
models) doubles the sync surface.

### D6. Signals and class hierarchy
6 `__gsignals__` classes, ~95 connect/emit sites → `pyqtSignal` mechanically. Two traps:
- **MeldDoc multiple inheritance** (`gobject.GObject` + `gnomeglade.Component`) violates
  PyQt's single-QObject-base metaclass rule → collapse to one QObject/QWidget base +
  composition *before* any widget code can instantiate.
- `connect_after` ("run after default handler") has **no Qt equivalent** — each `after_`
  site becomes an event filter or subclass override, case by case.
- Widget signals emitted as control flow (`tree.emit('cursor-changed')`) → direct slot calls.

### D7. UI files: rebuild by hand; code-built layouts for main views, Designer .ui for dialogs
The glade files are glade-2/libglade format with 21 `Custom` `creation_function` hooks —
**no converter exists**. Recommendation: dynamic main views (filediff's 7-column table with
1/2/3-pane show/hide) as code-built layouts; static dialogs (preferences, commit, findbar)
as Designer `.ui` + `uic.loadUi` with widget promotion for custom classes. Every glade
`<signal handler=...>` must be re-derived manually — autoconnected handlers are invisible
to Python grep (and some are dead: `on_textview_move_cursor`, `on_linkmap_scroll_event`,
`on_vpaned_move_handle`).

### D8. i18n: KEEP gettext; do NOT switch to Qt Linguist
34 catalogs exist. The trap: many msgids live in glade XML (extracted by dead intltool).
**Set all UI strings from Python via `_()` using the exact glade wording**, then `msgmerge`
to verify zero orphaned entries. Replace intltool with `xgettext` (parses Python natively)
and `msgfmt --desktop` for the .desktop file. Qt Linguist would abandon all 34 catalogs.

### D9. Preferences: QSettings + explicit migration
`util/prefs.py` prefers gconf, falls back to `~/.meld/meldrc.ini` (non-XDG). Port to
`QSettings` with: (a) one-time import of old gconf/INI values, (b) format conversion —
stored colors are X11 names invalid for QColor (`DarkSeaGreen1`), fonts are Pango strings
(`Monospace 12`) → QFont format, (c) **debounced writes** (current code rewrites the whole
INI on every assignment; meldapp writes window size on every resize).
Casualties to accept explicitly: gconf cross-process change notification, GNOME desktop
monospace font (→ `QFontDatabase.systemFont(FixedFont)`), gnome editor command, toolbar style.

### D10. Syntax highlighting: Pygments + QSyntaxHighlighter, as a follow-up feature
gtksourceview has no Qt counterpart. Pygments lexer-guessing feeding per-block
`QSyntaxHighlighter` is the pragmatic path (~3–5 pd, with per-block incremental
highlighting for large-file performance). QScintilla only if D1 chose it. Line-number
gutter is the standard hand-written Qt recipe. **Ship the first Qt version without it** —
it's optional in 1.4.0 anyway (`pygtksourceview` was an optional dep).

### D11. Icons: QIcon.fromTheme + bundled fallback theme
62 stock-icon refs map to freedesktop names on Linux (`gtk-close`→`window-close`,
`STOCK_GO_BACK`→`go-previous`), but Windows/macOS have no icon theme — bundle a small
fallback set. Convert the 5 `button_*.xpm` linkmap action pixmaps to PNG. Reconcile the
app-icon mismatch: `meldapp.py` sets icon name `"icon"`, the .desktop declares `Icon=meld` —
pick one strategy via `QApplication.setWindowIcon`.

### D12. Scope cuts (decide explicitly, saves ~15–20% of the port)
- **Dead VCS plugins**: tla/Arch, monotone, cdv/Codeville, svk (~700 LOC + untestable);
  port git, svn, hg, bzr, cvs — stub the rest behind `_null`.
- **help/ subsystem**: DocBook 4.2 + ScrollKeeper + yelp are dead; content documents meld
  0.9.6. Ship fresh HTML/hosted docs; accept loss of 5 help translations.
- **GTK2-gap widgets**: `wraplabel`, `notebooklabel`, most of `historyentry`, the msgarea
  style-stealing hack — Qt has built-ins; **delete, don't port**.
- X11 oddities: `ISO_Prev_Group` keyboard workaround, left-side-scrollbar
  `GTK_CORNER_TOP_RIGHT` asymmetry in dirdiff, legacy `--sm-config-prefix`/`--sm-client-id`
  session-manager arg stripping in `bin/meld` (Qt handles `-session` natively).

---

## 4. Phasing

### Phase 0 — Spikes & test harness (1–2 weeks) ⚠ gate for everything
- **S1: filediff rendering spike.** QPlainTextEdit subclass: chunk backgrounds +
  boundary lines in viewport `paintEvent`, `ExtraSelections` for line fills, two panes with
  proportional sync-scroll on `firstVisibleBlock`/`blockBoundingGeometry` math, one linkmap
  QWidget drawing `QPainterPath` beziers between them. *Pass/fail decides D1.*
- **S2: tree spike.** 3 QTreeViews × 1 QStandardItemModel, `setTreePosition`, hidden
  columns, role-based styling. *Decides D5's fallback question.*
- **Engine test suite** (pure py2-compatible pytest for `matchers`/`diffutil`/`merge`/
  `undo` against golden diffs) — written *before* the port, these become the port's safety net.
- Settle D1–D12; set up the new package skeleton (`pyproject.toml`, `meldqt/` or in-place),
  single-source `__version__` (today it's grepped out of `meldapp.py` by the Makefile).

### Phase 1 — Engine port: py2→py3 + QObject seam (3–6 pd)
`matchers`, `diffutil`, `merge`, `undo`, `task`, plus splitting `misc.py` into pure vs UI
halves. Mechanical, but walk the **traps checklist** (§6) line by line — most failures here
are *silent*. Convert `Differ`/`UndoSequence` to `QObject` + `pyqtSignal`. Fix latent bugs
found by the survey (§7) as explicit decisions. Engine tests green under py3/PyQt6.

### Phase 2 — Shell & infrastructure (2–3 weeks)
QMainWindow + QTabWidget + statusbar/progress, **the D3 action-merging layer**, the D4
scheduler pump, QSettings backend + migration (D9), the `gnomeglade.Component` replacement
base, and the two custom widgets everything shares: HistoryCombo (editable QComboBox +
QCompleter + QSettings history) and MsgArea banner (model: KMessageWidget). New-comparison
dialog, about dialog, preferences dialog (.ui rebuilds). New `bin/meld` launcher (the old
one is py2-only with a broken error path — rewrite, don't translate; mind the `meld.doap`
running-from-source sentinel).

### Phase 3 — dirdiff (8–14 pd)
`DiffTreeStore`→role-based model (with vcview's needs in scope), scan generator on the
scheduler, tree-path-tuple algorithms behind a `rowpath()` helper with
`QPersistentModelIndex` for mutation paths, EmblemCellRenderer → `QStyledItemDelegate`,
diffmap overview (drop GTK2 stepper math → `QStyle.subControlRect(SC_ScrollBarGroove)`).
Pause the scheduler around any modal dialog raised from inside the scan generator.

### Phase 4 — filediff (4–6 weeks — the crux)
Editor widget from S1, per-pane line↔pixel geometry rebuilt on block geometry (word-wrap
makes line height non-uniform — hardest fidelity risk), sync-scroll interpolation (math
survives; units change), linkmap canvas + clickable merge-action icons with
modifier-morphing (redesign on `QApplication.keyboardModifiers()`, not GTK keymask
plumbing), diffmap, inline char-level highlights (the utf16 hack at `filediff.py:895`
becomes *naturally correct* — QTextCursor positions are UTF-16 units), findbar
(re-derive selection semantics: Qt has one cursor anchor/position, not GTK's dual marks),
**undo redesign per D2**, and a rewrite of file loading (`codecs.open('rU')` is dead in
py3; rebuild the encoding-cascade + CR/LF + binary-sniff logic on `io` incremental
decoders and re-test the fallback chain). Then `filemerge` on top (small).

### Phase 5 — vcview + plugins (6–11 pd)
`vcview` UI on the Phase-3 model work. Plugins: centralize subprocess text-mode +
encoding (`errors='replace'`) in `_vc.popen` — bytes-vs-str is a hard break in every
plugin. Remove the two GTK leaks (cvs.py `run_dialog`, svk.py's `misc` import). Descope
dead VCSes per D12. `shutil.which` instead of `['which', cmd]`. **Behavioral testing per
tool** — svn.py parses 1.4-era `svn status` columns; a correct mechanical port can still
misreport against modern tools.

### Phase 6 — Packaging, i18n, desktop (3–6 pd)
`pyproject.toml` + entry point; kill the `#LIBDIR#`/`#LOCALEDIR#` sed-substitution
contract (`tools/install_paths` → `importlib.resources`); xgettext pipeline + msgmerge
verification of all 34 catalogs (D8); .desktop + icons for Linux; PyInstaller groundwork
for Windows/macOS (explicit gettext locale detection on Windows — no `LANG` there).

### Phase 7 — Hardening (1–2 weeks)
Encoding matrix (non-UTF8 filenames via `os.fsdecode`, astral-plane chars in diffs, mixed
newlines), large-file performance (highlighting, re-diff on edit), cross-platform pass,
manual test script per view (toolbar/menu state on tab switch is where missed signal
re-wiring hides).

**Dependency spine:** S1/S2 → Phase 1 → Phase 2 (D3+D4 block all views) → Phases 3/5
(shared model) and 4 in parallel if two people → 6 → 7.

---

## 5. Effort summary

| Subsystem | Difficulty | Est. (pd) | Dominant cost |
|---|---|---|---|
| Core engine | low | 3–6 | py2→py3 traps, QObject seam |
| filediff (+filemerge, diffmap) | **very high** | 18–30 | geometry rebuild, undo redesign, file loading |
| dirdiff (+tree) | high | 8–14 | model redesign, path-tuple discipline |
| vcview + plugins | medium | 6–11 | bytes/str, per-tool verification |
| App shell + prefs + sourceviewer | high | 10–18 | action merging, QSettings, editor widget decision |
| ui/ widgets | medium | 3–6 | base-class replacement; half is deletions |
| Build / i18n / packaging | medium | 3–6 | pipeline replacement, catalog preservation |
| Cross-cutting (scheduler, signals, glade infra, icons, py3 sweep) | high | 12–20 | one-time infrastructure |
| **Total** | | **~65–110** | |

---

## 6. Traps checklist (silent py3 breakage — audit every one)

These *import fine and fail at a distance*; a naive 2to3 pass ships all of them:

- [ ] `filter()`/`map()` laziness: `matchers.py:71` (result stored in `self.diffs`, later
  `len()`/sliced — breaks diffing), `diffutil.py:51/432`, `misc.py:171-189`
  (`shorten_names`), **`dirdiff.py:500-501` (map-for-side-effect: scan adds nothing to the
  model)**, `dirdiff.py:863/866` + `filediff.py:1214/1219` (pane show/hide no-ops),
  `cvs.py:140/165-169` (one-shot iterator membership tests)
- [ ] True division as index: `diffutil.py:311/316/332` (`toindex/2` → float → TypeError
  only when pane 0/2 is queried) — must be `//`
- [ ] Generator protocol: 32 `.next` references, most as *callables* passed to the
  scheduler (`scheduler.add_task(gen.next)`) → `gen.__next__` or lambda; PEP 479:
  `raise StopIteration` inside generators at `tree.py:138/158` becomes RuntimeError
  (crashes next-diff navigation at tree boundaries)
- [ ] `misc.struct.__cmp__` → `__eq__`/`__ne__` (compared by consumers)
- [ ] `FakeText.__getslice__` never called in py3 → diff input silently wrong (`filediff.py`)
- [ ] Bytes/str: every `vc/` plugin's popen parsing; `_files_same` reads binary files in
  text mode (`dirdiff.py:83`) and collides with the regex text-filter feature — define
  bytes-vs-decoded semantics + parity tests (this decides same/modified verdicts)
- [ ] `codecs.open(.., 'rU')` removed; chunked decode can split multibyte seqs (`filediff.py:706-796`)
- [ ] Invalid escape sequences in default filter regexes + import-time gettext
  (`preferences.py:262-282`)
- [ ] `except X, e` (24), `print` (35), `iteritems` (3), raise-comma (1) — mechanical

## 7. Latent bugs found by the survey (fix-or-preserve, decide per bug)

- `merge.py:131` — `seq2` undefined (NameError in delete+delete conflict-split tail)
- `undo.py:182` — `self.actions[end + 1]` IndexError at stack top
- `msgarea.py:72` — `self.__actionarea` vs `__action_area` (unreachable until ported);
  mutable default arg `buttons=[]` at `:242`
- `vc/bzr.py:83-86` — possible UnboundLocalError on `cur_state`
- `vc/git.py:85` — `update-index --refresh` missing `cwd`
- `bin/meld:77` — py2-only leaked `except` variable in the missing-requirements path

## 8. What gets deleted (negative work — do not port)

GTK2 backport widgets (`wraplabel`, `notebooklabel`, most of `historyentry`), msgarea
style-stealing paint hack (→ QSS), dirdiff key-nav bindings (`dirdiff.py:628-644` — native
in QTreeView), scrollbar stepper math (`diffmap.py:64-79` → one QStyle call),
`gtk.pygtk_version` guards, glade `Custom` dispatcher (`gnomeglade.py:49`), the dead
`popup_new` menu + 5 handlers in meldapp.glade, gnomevfs feature-gating (Qt's
`QMimeData.urls()` is unconditional), the `#TOKEN#` install substitution, intltool,
ScrollKeeper, the 4-generation sourceviewer shim.

## 9. Testing strategy

1. **Engine golden tests before the port** (Phase 0) — deterministic, headless; they
   validate Phase 1 and catch the §6 traps.
2. **pytest-qt** for widget logic (sync-scroll math, model state, findbar semantics).
3. **Per-VCS behavioral fixtures** — scripted repos for git/svn/hg/bzr/cvs; assert parsed
   states, not just "no exception".
4. **Encoding matrix** — latin-1/utf-8/utf-16 files, non-UTF8 filenames, astral-plane
   chars, mixed newlines, binary detection.
5. **Manual smoke script per view** — esp. toolbar/menu/status state on tab switches
   (missed glade-autoconnect re-wiring produces stale UI, not crashes).

## 10. Appendix: Electron-path research (Monaco vs CodeMirror 6)

*Web-verified 2026-07; claims marked ✓ passed 3-vote adversarial verification; others are
primary-source-backed (official docs/changelogs/maintainer statements) but the verify pass
was cut short by an API limit. Zero claims were refuted.*

**3-way merge is a custom build on every web foundation — nobody ships it:**
- ✓ Monaco's diff API (`IDiffEditorOptions`/`IDiffEditorConstructionOptions`) models exactly
  two documents; no 3-pane options exist.
- Monaco's 3-way-merge feature request was closed "not planned" (2023-03-13, locked);
  VS Code's merge editor depends on unbundled VS Code internals, and its author (hediet)
  said extraction is possible but deliberately not invested in
  (microsoft/monaco-editor#3268).
- ✓ `@codemirror/merge` as of 6.12.1 (2026-03-11) documents only 2-pane `MergeView` and a
  unified single-editor view; maintainer marijn stated (Oct 2023) there are no plans for
  3-way, pointing to the legacy CM5 merge addon as the only fallback (CM5 is EOL — not a
  real option).

**2-way editable diff is free on both:**
- ✓ Monaco `DiffEditor`: side-by-side by default (`renderSideBySide`), both panes editable
  via `originalEditable: true`, selectable diff algorithm. MIT licensed.
- `@codemirror/merge` MergeView: both panes are ordinary editors, editable unless
  explicitly restricted; actively maintained (~40 releases 2022→2026). Caveat: its diff
  falls back to whole-document-changed on very large/divergent inputs (`scanLimit`,
  `timeout` knobs) — Meld would feed it chunks from its own engine anyway.

**CodeMirror 6 is the right foundation for Meld's custom UX** (if the Electron path is taken):
- Exposes exactly the primitives Meld's linkmap/sync-scroll needs: `lineBlockAt(pos)`,
  `lineBlockAtHeight()`, `viewportLineBlocks`, `coordsAtPos`, `scrollDOM` — per-line pixel
  geometry that the Qt plan has to rebuild from `blockBoundingGeometry` by hand.
- Decorations API: line decorations (chunk backgrounds), mark decorations (inline
  char-level highlights), widget/block decorations — no paint-layering tricks needed.
- Undo: `isolateHistory` (forced group boundaries), `Transaction.addToHistory: false`
  (exclude programmatic merges from user undo), configurable grouping — a much closer fit
  to Meld's undo/checkpoint semantics than either QTextDocument or Monaco. **The Qt plan's
  single riskiest item (D2) is substantially easier here.**
- Viewport-virtualized; official demo stays interactive at millions of lines.
- Sync scrolling across instances: no built-in API; maintainer-recommended pattern is
  scroll/update listeners pushing positions — same interpolation math as the Qt port.
- Monaco is a poor fit for the same job: the DiffEditor is a sealed 2-pane component (a
  3-pane Meld UI means three standalone editors + reimplementing diff rendering anyway),
  and production migrations away from it for custom-UI reasons are documented (Sourcegraph:
  Monaco was 2.4 MB / 40% of page JS, moved to CM6; Replit: +5 MB uncompressed, no
  code-splitting, moved to CM6). Bundle size itself is irrelevant inside Electron, but the
  monolithic architecture is what blocks deep customization.

**Effort impact:** the 15–25 pd Electron diff/merge-UI estimate stands (3-way view, linkmap,
action buttons are custom regardless of foundation), but its *risk* drops — the undo and
per-line-geometry problems that make the Qt filediff port "very high" difficulty have
first-class APIs in CM6. Overall Electron-rewrite estimate tightens to ~55–90 pd, still in
the same band as the PyQt port (~65–110 pd). The decision remains a product/runtime call,
not an effort call: PyQt keeps the proven engine and native footprint; Electron+CM6 buys
easier UI iteration at the cost of rewriting (and re-verifying) the merge engine in TS.

## 11. Odds and ends the gap-check caught

- `bin/meld` uses **`meld.doap` as the running-from-source sentinel** for sys.path — the
  new launcher needs an equivalent (or `importlib.resources` makes it moot).
- `meld/vc/COPYING` is separate licensing for the vc package — must travel with it.
- No single-instance/DBus anywhere — nothing to port; don't hunt for it.
- Only atk use is one accessible name in historyentry → `setAccessibleName`; glade files
  contain zero accessibility blocks.
- gconf history keys (`historyentry.py:183`) and `~/.meld` both feed the D9 migration.
