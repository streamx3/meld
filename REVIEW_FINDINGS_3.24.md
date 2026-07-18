# meldq review — findings & fix plan (2026-07-18)

Review of the fresh PyQt6 product code (`meldq/shell.py`, `meldq/main.py`,
`meldq/conf.py`, `meldq/views/*`, `meldq/widgets/sciview.py`,
`meldq/widgets/infobar.py`, `meldq/patch.py`, `meldq/patchimport.py`,
`meldq/dircompare.py`, `meldq/gitvc.py`, `meldq/engine/*`, `meldq/util/prefs.py`)
against the docs (`BUILD_PLAN_3.24.md`, `DIVERGENCE_MAP_3.24.md`,
`PYQT_PORT_PROGRESS.md`, `README.md`, `MANUAL_TESTS.md`) and the GTK 3.24
reference tree (`meld/`).

Method: multi-agent finder passes + independent inline runtime reproduction of
the critical/major items (offscreen Qt, real temp git repos, real patch files,
~10k-pair differential engine test). Legacy 1.4 code (`meldq/` top-level
`filediff.py`/`dirdiff.py`/`vcview.py`/`vc/` etc.) is reference-only and out of
scope except where the fresh tree imports it (`historycombo`).

Baseline at review time: **633 passed, 4 skipped**.

## Severity counts

| Severity | Count | Meaning |
|---|---:|---|
| Critical | 4 | destroys user data or aborts the process in a mainline flow |
| Major | 34 | wrong results or a broken advertised feature |
| Minor | 20 | edge case, polish, or doc staleness |

## What is solid (verified, not defects)

- **Diff engine is correct.** `MyersSequenceMatcher` is byte-identical to GTK
  3.24 over 6,351 differential pairs; `Differ` is genuine 3.24 lineage
  (postprocess coalescing, empty-seq guards, conflict tagging) — byte-identical
  across 3,000 random triples incl. `ignore_blanks` and incremental
  `change_sequence`.
- Patch **apply** on context-ful patches: multi-hunk/multi-file, offset drift,
  the full no-newline-at-EOF matrix, reverse round-trips, relocated-hunk offset
  search — all clean.
- Porcelain parsing of spaces/UTF-8/`MM`/`T`/`AD`/real `UU` conflicts;
  `find_repo_root` on worktrees/submodules/`.git`-file; commit messages with
  shell metacharacters; prefs round-trip + legacy-ini migration; i18n headless
  fallback; New-Comparison dialog build/accept without GC signal drops.

---

# Findings

Each finding: **ID** | severity | `file:line` | statement. "Repro ✓" = an
executed runtime reproduction exists; "read" = established by code reading.

## Critical — data loss / process abort

- **C1** | critical | `meldq/views/filediff.py:255` | `save()` opens `"wb"`
  (truncates to 0 bytes) **before** `text.encode(encoding)`. A non-UTF-8
  (latin-1 fallback) buffer + a character outside latin-1 (€, em-dash, smart
  quote) raises `UnicodeEncodeError` after truncation → file left at 0 bytes.
  Repro ✓ (file destroyed).
- **C2** | critical | `meldq/patch.py:185` (+`:158`) | `git diff -U0` pure-insert
  hunk (`@@ -5,0 +6 @@`) applies **one line too early** — empty source range
  should mean "insert after line N", but the clamped-center splice puts it
  before line N. Silent corruption, no error. Repro ✓ (inserted at index 4, not
  5).
- **C3** | critical | multiple | **Unhandled exception in a Qt slot aborts the
  whole process** (PyQt6 `qFatal`). Instances: PatchDialog used after its tab is
  closed (`shell.py:476`, dangling `self.filediff` → deleted C++ panes);
  DirDiff `copy_to`/`delete` on a dir-vs-file collision (`dirdiff.py:289`, exit
  134); `load_file`/`reload` on a chmod-000 or vanished file (`filediff.py:75`);
  VcView git calls after the repo dir is removed (`gitvc.py:16`); PatchDialog
  `_save` to an unwritable path (`shell.py:749`). Repro ✓ (several).
- **C4** | critical | `meldq/shell.py:441` + `meldq/views/filediff.py:219` |
  **Imported patch cannot be saved.** `import_patch` populates panes via
  `set_texts`, which marks every pane unmodified, and never re-marks the patched
  pane; `on_save` saves only modified panes → Import → accept → Ctrl+S writes
  nothing. Worse, `focused_pane()` defaults to 0 (read-only original), so
  Save-As right after import would write the *unpatched* text. Repro ✓ (disk
  unchanged). The headline differentiator does not complete end-to-end.

## Major — patch (the differentiator)

- **P1** | major | `meldq/shell.py:494` | Patch file read with
  `open(encoding="utf-8", errors="replace")` — universal-newline mode strips the
  `\r` that is *content* for CRLF sources, and `errors="replace"` corrupts
  non-UTF-8 patches; both make otherwise-valid patches fail `apply_hunks`. Repro
  ✓ (CRLF + latin-1 patches → PatchError; raw-bytes decode applies cleanly).
- **P2** | major | `meldq/views/filediff.py:263` | `make_patch` exports LF-only
  (buffer is `\n`-normalized, `_eol` never re-applied), so a diff of a CRLF file
  contains no CRs and fails both `git apply` and meldq's own importer. Repro ✓.
- **P3** | major | `meldq/views/filediff.py:269` | `make_patch` headers use
  `os.path.basename(path)`, so `sub/nested.txt` exports as `a/nested.txt` and
  applies nowhere. Repro ✓ (`git apply` "No such file or directory").
- **P4** | major | `meldq/patch.py:148` + `meldq/patchimport.py:32` | Rename
  patches: a pure rename yields no `FilePatch` (silently dropped); rename+edit
  fails because `_relpath` prefers the not-yet-existing new path → original=""
  → PatchError. Repro ✓.
- **P5** | major | `meldq/patchimport.py:65` | `patch_targets` escapes
  `base_dir`: an absolute (`/outside/x`) or `../` header path reads (and the
  saveable pane targets) a file outside the chosen base. Repro ✓ (read a file
  outside base).
- **P6** | major | `meldq/patch.py:121` | Truncated hunk (body ends before the
  declared `src_len`/`tgt_len`) is applied with no validation → partial silent
  change. Repro ✓ (`git apply` calls it "corrupt patch").
- **P7** | major | `meldq/patch.py:25` + `meldq/patchimport.py:32` | Git-quoted
  paths (`"a/f\303\274ile.txt"` under default `core.quotePath`) aren't unquoted
  or octal-decoded → import fails for non-ASCII filenames. Repro ✓.
- **P8** | minor | `meldq/patch.py:138` | Whitespace-stripped blank context line
  is stored as `""` not `"\n"`, so it never matches a real blank source line
  (mail-mangled patches that `git apply` accepts fail here). Repro ✓.
- **P9** | minor | `meldq/patch.py:148`/`:142` | Malformed `@@` header (one `@`)
  and space-less context lines fall through to a silent no-op ("no changes" tab)
  instead of a "cannot parse" error. Repro ✓.
- **P10** | minor | `meldq/patch.py:148` | Git binary patches produce no
  `FilePatch` → silently dropped (a mixed text+binary patch loses the binary
  parts with no warning). Repro ✓.
- **P11** | minor | `meldq/patchimport.py:63` | `+++ /dev/null` deletion yields
  `patched=""`; the review pane's save writes a 0-byte file — never unlinks —
  diverging from git/patch delete semantics. Repro ✓.
- **P12** | minor | `meldq/patch.py:93` | Context-format (non-unified) diffs:
  each `--- 1,3 ----` range line matches the unified `---` header regex →
  garbage `FilePatch` with 0 hunks → empty "no changes" tabs instead of an
  "unsupported format" error. Repro ✓.

## Major — merge / FileDiff interaction

- **M1** | major | `meldq/widgets/sciview.py:252` | Every merge-arrow click
  scroll-jumps the modified pane to EOF (`replace_all_text` = selectAll +
  replaceSelectedText → caret at end, Scintilla scrolls to caret). Repro ✓
  (first-visible 45→273 on one click; panes desynced).
- **M2** | major | `meldq/views/filediff.py:472` | `_on_action` never checks
  `has_action_marker`, and `chunk_at_line`/`outer_chunk_at_line` match
  zero-width chunks → clicking the *empty* action margin near an insert chunk
  silently deletes the other pane's added lines. Repro ✓.
- **M3** | major | `meldq/shell.py:532` | Edit ▸ Undo (`_editor_action`) goes to
  the focused widget, but a merge edits the *other* pane, whose stack the focused
  (source) pane isn't → Ctrl+Z after a merge undoes nothing. Repro ✓
  (pane0 undo unavailable, pane1 has the edit).
- **M4** | major | `meldq/views/filediff.py:374` | 3-way: a deletion made in an
  outer pane is a zero-width chunk on that pane → no background, no arrow → it
  is invisible and cannot be pushed to base. Repro ✓ (no action marker).
- **M5** | major | `meldq/views/filediff.py:377` | 3-way base-pane inline
  highlighting passes `lines[1]` as both `this` and `other`, sliced with the
  outer pane's indices → base marks wrong/nothing. Repro ✓ (no base inline
  marks where expected).
- **M6** | major | `meldq/widgets/sciview.py:258` | Merge into a read-only pane
  is rendered but silently no-ops (`replace_all_text` doesn't lift read-only);
  in patch review the left pane is read-only so an "insert" hunk's only arrow
  does nothing. Repro ✓. (Interacts with C4/P-review.)
- **M7** | major | `meldq/views/filediff.py:80` | UTF-8 BOM is decoded with plain
  `utf-8` (no `utf-8-sig`); QScintilla drops the U+FEFF → save writes the file
  without its BOM. Any edit+save of a BOM file corrupts it. Repro ✓.
- **M8** | major | `meldq/views/filediff.py:255` | No blind-overwrite check: the
  contract says "refuse blind overwrite" but `save()` never compares the current
  on-disk token with `_disk_token[pane]`; a Ctrl+S in the watcher's async gap
  clobbers an external edit. Repro ✓.
- **M9** | minor | `meldq/views/filediff.py:259` | Patch-import views share one
  path across both panes with no initial disk token; the second save fires a
  bogus "changed on disk" prompt whose Reload loads the patched file into the
  read-only reference pane. Repro ✓.
- **M10** | minor | `meldq/views/linkmap.py:43` | Chunk touching EOF-without-
  trailing-newline draws a zero-height (invisible) connector (`y_for_line(hi)`
  clamps to doc end = top of last line). Repro ✓.
- **M11** | minor | `meldq/views/filediff.py:158` | `set_files([f, None])`
  crashes `TypeError` (`_file_token(None)` — only `OSError` caught) despite the
  "missing path never crashes" docstring. Repro ✓.

## Major — save / close (shell)

- **S1** | major | `meldq/shell.py:618` (+`:671` closeEvent) | Choosing "Save"
  in the unsaved-changes prompt still `removeTab`/`accept`s when the save fails:
  `_save_all_panes` discards `_save_pane`'s `False` (failure is an 8s statusbar
  message, invisible if the statusbar is hidden) and skips modified panes with
  no path. Edits lost after the user explicitly chose Save. Repro ✓.

## Major — DirDiff

- **D1** | major | `meldq/views/dirdiff.py:285` | Activating a file present on
  only one side emits a 1-element list; `append_filediff` rejects <2 paths →
  the most common dir-diff action (inspect a new/deleted file) opens nothing.
  Repro ✓. (3.24 opens against an empty pane.)
- **D2** | major | `meldq/views/dirdiff.py:306` | "Trash-delete" falls straight
  through to `shutil.rmtree`/`os.remove` when `QFile.moveToTrash` returns False
  (NFS, trash-less volumes) — unprompted permanent deletion. No confirmation on
  delete at all. Read (spec: `meld/iohelpers.py` prompts).
- **D3** | major | `meldq/dircompare.py:82` | An unreadable directory
  (`_listdir` swallows `OSError` → None) is indistinguishable from empty → the
  tree reports it identical (NORMAL) and misclassifies its children; nothing
  surfaced in the (unused) infobar. The core "these trees are the same" claim
  can be wrong. Repro ✓.
- **D4** | major | `meldq/dircompare.py:130` | `walk()` follows directory
  symlinks with no cycle guard (`isdir=any(os.path.isdir)` + unconditional
  `todo.append`) → phantom replicated subtrees until kernel ELOOP, repeated
  content comparison. Repro ✓ (48 entries from one loop link).
- **D5** | major | `meldq/views/dirdiff.py:96` | Name/text/state filters exist
  only as API (`name_filters`/`regexes`/`state_filters`) — no UI, no prefs,
  never populated in the app → e.g. `.git` is scanned in full. Scope table
  claims "name+text filters" in v1; progress log defers "filter UI" (internal
  contradiction). Read.
- **D6** | minor | `meldq/views/dirdiff.py:289` | `copy_to` follows symlinks
  (`copytree` default `symlinks=False`, `copy2`) and silently merges into
  existing dirs (`dirs_exist_ok=True`) — diverges from 3.24 symlink preservation.
  Repro ✓. (Also part of C3's no-error-handling class.)
- **D7** | minor | `meldq/dircompare.py:127` | Case-insensitive FS (default
  APFS/HFS+): `README` vs `readme` across panes yield two phantom rows each
  claiming "present on both". Repro ✓ (macOS).
- **D8** | minor | `meldq/dircompare.py:52` | With any text filter set,
  byte-distinct non-UTF-8 files decode via `utf-8`/`replace` → compare equal →
  reported NOCHANGE even when no regex matched. Repro ✓.
- **D9** | minor | `meldq/dircompare.py:43` | Same-size files are slurped whole
  into RAM for every pane at once (16 GB for two 8 GB files) on the GUI thread;
  `MemoryError` fallback rarely triggers on 64-bit. Read.
- **D10** | minor | `meldq/views/dirdiff.py:325` | Copy actions are built only
  for `num_panes == 2`; a 3-way folder comparison can compare/delete but never
  copy, though `copy_to` supports it. Read.

## Major — version control

- **V1** | major | `meldq/gitvc.py:104` | Committing a rename duplicates the
  file in HEAD: `status()` keeps only the new path, `commit()` commits by
  pathspec, so the staged deletion of the old path is omitted. Repro ✓
  (`git ls-tree HEAD` shows both names, `D old` stays staged).
- **V2** | major | `meldq/gitvc.py:102` | Commit during a merge silently fails
  *and* clears the conflict flag: `commit()` runs `git add` (marks resolved)
  then `git commit -- paths` (git refuses partial commit mid-merge). Repro ✓
  (row flips conflict→modified, MERGE_HEAD remains, no commit, no message).
- **V3** | major | `meldq/views/vcview.py:186` (+`:209`) | No VC action surfaces
  an error — `_act`/`commit_files` discard backend booleans; failed
  add/remove/revert/commit do nothing visible. Repro ✓.
- **V4** | major | `meldq/gitvc.py:83` | Renamed file's diff shows an empty left
  pane (`git show HEAD:<newpath>` fails at HEAD) → a pure rename renders as a
  whole-file addition. Repro ✓.
- **V5** | major | `meldq/gitvc.py:113` | Revert of a staged-added file only
  `os.remove`s (never `git rm --cached`) → index entry survives → a ghost `AD`
  "removed" row. Repro ✓.
- **V6** | major | `meldq/views/vcview.py:124` | The VC tab ignores its
  location: `refresh()`/`on_commit` operate on the whole repo, so opening a
  subdirectory lists (and no-selection-commits) files outside it. Repro ✓.
- **V7** | minor | `meldq/views/vcview.py:121` | Every action calls `refresh()`
  which rebuilds the model → selection and current index wiped, losing the
  user's place. Repro ✓.
- **V8** | minor | `meldq/views/vcview.py:175` | Activating a submodule row
  opens an empty-vs-empty diff (`git show HEAD:<sub>` fails, working path is a
  dir). Repro ✓.
- **V9** | minor | `meldq/gitvc.py:22` | Missing git binary reports "Not a git
  repository." (misleading); `is_git_available` is dead in app code (only test
  skips), so there is no git-not-found degradation and `status()` raises
  uncaught if git vanishes. Read/Repro ✓.
- **V10** | major | `meldq/gitvc.py:116` | Revert permanently deletes an
  untracked file with no prompt/trash (only copy destroyed); Remove
  (`git rm -r`) likewise unprompted. Read.
- **V11** | minor | `meldq/gitvc.py:74` | `status()` skips the origin token for
  renames (`R`) but not copies (`C`) → a copied entry's origin path is parsed
  as a bogus row. Read.
- **V12** | minor | `meldq/views/vcview.py:241` | The materialized HEAD pane is
  editable and saveable (writes into a throwaway temp, unlike `import_patch`
  which sets read-only), and the temp tree dies when the VC tab closes while a
  diff tab may still reference it. Read.

## Major/minor — performance

- **PF1** | major | `meldq/views/filediff.py:381` | Per-keystroke inline
  highlighting runs char-level `difflib` over whole replace chunks — ~1.5 s per
  keystroke on a 200-line chunk. The `_INLINE_MAX` guard uses `and` (both sides
  must exceed the cap), so huge-vs-tiny still runs while a symmetric large chunk
  silently loses highlighting. Repro ✓ (1511 ms measured).
- **PF2** | major | `meldq/views/filediff.py:322` | Full synchronous re-diff on
  every `textChanged`; Myers worst case (same lines reordered — e.g. sorted
  logs) ~11 s per keystroke on 10k lines. The matcher yields every 100 loops
  precisely for a scheduler; the view spins it dry synchronously. Repro ✓
  (10.8–11.0 s).

## Minor — platform / CLI / misc

- **X1** | minor | `meldq/shell.py:155` | Ctrl+D ("Next Change") is claimed by
  QScintilla ("Duplicate selection") and never reaches the QAction while an
  editor pane has focus → the navigation key silently duplicates the current
  line. Repro ✓. (Ctrl+E works.)
- **X2** | minor | `meldq/shell.py:99`,`:326`; `dirdiff.py:257` | All 12
  `QIcon.fromTheme` names return null on macOS (no icon theme) → text-only
  toolbar, blank tab/tree icons. Repro ✓.
- **X3** | minor | `meldq/views/filediff.py:247` | Save-As adds the new path to
  the watcher but never removes the old → a permanent stale watch that
  re-arms forever. Repro ✓.
- **X4** | minor | `meldq/util/prefs.py:93` | Migrated `custom_font` family
  "monospace" resolves to a proportional `.AppleSystemUIFont` on macOS
  (`fixedPitch: False`). Repro ✓.
- **X5** | minor | `meldq/widgets/historycombo.py:101` + `meldq/shell.py:779` |
  The three same-`history_id` file combos each own an independent item list and
  `_save_history` writes wholesale → only the last-entered path is persisted.
  Repro ✓.
- **X6** | minor | `meldq/views/dirdiff.py:320`; `vcview.py:222` | `_context_menu`
  creates `QMenu(self.tree)` never deleted after `exec()` → one leaked menu +
  actions + captured index per right-click. Read.
- **X7** | minor | `meldq/main.py:54` | CLI accepts 4 positional paths but
  `append_filediff` silently drops the 4th (help says "up to 3"); no `-o`/
  `--output`/`--auto-merge`. Read.
- **X8** | minor | `meldq/shell.py:854` | New-Comparison OK always closes
  (`WA_DeleteOnClose`); insufficient input is discarded with at most a transient
  statusbar warning. Read.
- **X9** | minor | `meldq/shell.py:15` etc. | Dead wiring: unused `QEvent`
  import; `MeldSciView.focus_changed` emitted but never connected; `MeldWindow.
  menus` populated but never read. Read.
- **X10** | minor | `meldq/main.py:73` | Import-error message says "PyQt6 >= 6.6"
  while the real floor (theming) is 6.8. Read.

## Minor — documentation

- **DOC1** | minor | `README.md` | Still the upstream GTK Meld README
  (PyGObject/GTK/meson/`bin/meld`); no mention of `meldq`, PyQt6, or the real
  entry point/deps. Read.
- **DOC2** | minor | `MANUAL_TESTS.md` | Describes the 1.4-era VcView (console
  pane, Previous Logs, Flatten, Show Ignored) — none of it exists in the fresh
  VcView. Read.
- **DOC3** | minor | `BUILD_PLAN_3.24.md:30`,`:62` + `meldq/util/prefs.py:89` |
  Prefs are the 1.4 meldrc key set (`color_delete_bg`, `use_custom_font`,
  `text_codecs`…), not "GSettings-aligned to org.gnome.Meld" as claimed. Read.
- **DOC4** | minor | `BUILD_PLAN_3.24.md:81`,`:115` | M2 "COMPLETE" but the
  chunkmap/overview map from M2's own definition does not exist. Read.
- **DOC5** | minor | `BUILD_PLAN_3.24.md:52`,`:115` | "Sync scroll (reuse the
  influence-map algorithm)" claimed complete, but the code scrolls every pane to
  the same absolute line (`filediff.py:528`) — panes drift apart past the first
  insertion; `tests/test_sync_scroll.py` tests the *legacy* class. Read.
- **DOC6** | minor | `BUILD_PLAN_3.24.md:104` / `:28`,`:167` / `:168` /
  `:178` / `pyproject.toml:18` | Stale/contradictory: "~574 tests" (actual 633+4);
  scope table lists "size/time cols" that the progress log defers; "Remaining"
  says dark theme doesn't reach the trees while "Post-M6 polish" (and the code)
  say it does; `-a/--auto-compare` no-op rationale misstates the 3.24 feature
  (it auto-opens diffs for changed files); `highlight = ["pygments"]` is a dead
  extra (nothing imports pygments). Read.

---

# Fix plan

Principles (per project working style): **one commit per fix unit**, each with a
regression test; adversarial self-review before committing; **do not push** —
wait for explicit "push it"; flag anything that needs eyeballing on a real Mac
(icons, trash, fonts). Phases are ordered by user-facing risk; within a phase,
items are independent unless noted.

## Progress

Work lands on branch `fix/review-phase0` (not pushed). Suite: 633 → 649 green.

- ✅ **Phase 0 — DONE** (2026-07-18):
  - C1 — encode-first atomic save (`4f7af1b9`)
  - C2 — `-U0` insert position (`ea644e61`)
  - C4 — imported patch saveable via recorded edit (`a9a635a4`)
  - C3 — slot-exception safety net + I/O guards + PatchDialog lifetime (`c1865b34`)
- 🟡 **Phase 1 — in progress:**
  - P1 — patch files read as bytes (CRLF/latin-1 patches import) ✅
  - P2+P3 — export restores per-pane EOL + shared-relative-path headers ✅
  - P6+P8+P9+P12 — strict parse: truncated/malformed/context-format raise; mangled blank context applies ✅
  - P4+P7+P10+P11 — renames (pure + edit), git-quoted paths, binary entries reported, delete patches flagged ✅
  - P5 — patch_targets refuses absolute / ../ paths escaping the base dir ✅
  - **Phase 1 (P1–P12) DONE**
- 🟡 **Phase 2 — in progress:**
  - M1 — scroll-stable targeted merge (replace_line_range) ✅
  - M2 — action clicks guarded by has_action_marker (no destructive empty-margin merge) ✅
  - M3 — view-level undo/redo follow the last-edited pane (Ctrl+Z reverts a merge) ✅
  - M7 — UTF-8 BOM round-trips on save (utf-8-sig), plain UTF-8 never gains one ✅
  - M8 — save refuses blind overwrite of an externally-changed file (Overwrite/Reload) ✅
  - M10 — LinkMap draws a visible band for a change on the last newline-less line ✅
  - M9 — patch-import reference pane no longer gets a bogus reload prompt ✅
  - M4+M5 — 3-way outer deletions get a clickable arrow; base inline diffs the correct outer pane ✅
  - **Phase 2 merge cluster DONE** (M1,M2,M3,M4,M5,M7,M8,M9,M10,M11).
  - ⏸ **M6 DEFERRED (feature, not a mechanical fix):** merging into a read-only
    pane still no-ops. Making it apply would let a patch-review insert-arrow
    overwrite the read-only original; the right fix is a patch-review
    "reject hunk" control that edits the patched pane instead. Tracked for a
    later feature pass.
- 🟡 **Phase 3 — in progress:**
  - S1 — close/quit keeps the tab open when a chosen Save fails ✅
  - D1 — activating a one-sided file opens a diff against an empty pane ✅
  - D4 — walk() cycle guard: directory symlink loops terminate ✅
  - D3 — unreadable directory flagged ERROR + message, not reported identical ✅
  - D2+V10 — confirm before irreversible delete (trash-fail; VC revert-untracked / remove) ✅
  - D8+D9 — filtered compare is byte-faithful (latin-1, not lossy utf-8); unfiltered compare streams ✅
  - D6 — copy preserves symlinks instead of dereferencing them ✅
- ⬜ Phases 3 (rest)–7 — pending.

Owner-question defaults taken (autonomous run): D5 → default VC-dir name filter
+ defer filter UI; P10/P11 → explicit unsupported/delete messages; DOC5 → will
implement influence-map sync scroll.

## Phase 0 — Stop the bleeding (data loss + process aborts)

Nothing else ships until these land; they lose work or kill the app in ordinary
use.

1. **C1 — atomic, encode-first save.** Encode the text *before* opening the
   file; write to a temp file in the same dir and `os.replace` into place; on
   `UnicodeEncodeError` raise before any truncation and surface it. Test:
   latin-1 file + € → original bytes intact, error reported.
2. **C3 — slot-exception safety.** Two layers: (a) install a
   `sys.excepthook`/`qInstall`-style guard so a slot exception shows a message
   instead of aborting; (b) local `try/except (OSError, ValueError)` around the
   real I/O slots — `load_file`/`reload`/`set_files` (C3+M11), DirDiff
   `copy_to`/`delete` (C3+D6), VcView git calls (C2/XC2), PatchDialog `_save`
   (XC4) — each turning failure into an infobar/statusbar message. Fix the
   PatchDialog-outlives-tab dangling ref (parent the dialog to the tab or close
   it on tab close / `WA_DeleteOnClose` tied to the view). Tests: each trigger →
   message, no abort.
3. **C2 — `git diff -U0` insert position.** In `apply_hunks`/`_find`, when the
   old block is empty, splice *after* `src_start` (1-based → the line index is
   `src_start`, not `src_start-1`). Test: `@@ -5,0 +6 @@` inserts after L5;
   two-hunk -U0 patch lands both correctly.
4. **C4 — imported patch is saveable.** After `import_patch` builds the review
   tab, mark the patched (right) pane modified (or route Save to write pane 1
   regardless of the modified flag for import tabs). Ensure Save/close prompt
   see it. Test: import → `on_save()` → disk equals patched text; close prompts.

## Phase 1 — Patch differentiator correctness

The headline feature; make import/apply/export trustworthy.

5. **P1 — read patches as bytes.** Read the `.patch` file `"rb"`, decode
   encoding-aware (utf-8 → latin-1) with `newline=""`/no translation, preserving
   `\r`. Tests: CRLF patch on CRLF source imports; latin-1 patch imports.
6. **P2 + P3 — faithful export.** `make_patch`: re-apply `self._eol` to body
   lines (or diff the EOL-restored text), and use the path **relative to a
   common base** for `a/`,`b/` headers (fall back to the given label). Tests:
   CRLF export applies via `git apply` and the importer; nested-path export
   applies at repo root.
7. **P6 + P9 + P12 — parse strictly, fail loudly.** Validate that each hunk
   body meets its declared counts (else `PatchError`); reject a malformed `@@`
   header and context-format diffs with a clear "cannot parse / unsupported
   format" rather than a silent no-op. Tests: truncated hunk, one-`@` header,
   context diff → explicit error surfaced in the UI.
8. **P4 + P7 — rename & quoted paths.** Parse `rename from/to` and `diff --git`
   to recover both paths; resolve the source via `old_path` for rename+edit;
   unquote/octal-decode git-quoted `"a/…"` paths. Tests: rename, rename+edit,
   non-ASCII filename all import and apply.
9. **P5 — base_dir containment.** In `patch_targets`, reject/normalize absolute
   and `..`-escaping header paths so the resolved target stays under `base_dir`.
   Test: `/outside` and `../outside` → refused, no read outside base.
10. **P11 — deletion semantics.** For `+++ /dev/null`, model the target as a
    delete (offer to remove the file on accept) rather than writing a 0-byte
    file. Test: deletion patch removes the file, not truncates it. (May pair
    with a small UI affordance; if descoped, surface "this patch deletes X"
    explicitly.)
11. **P10 — binary patches.** Detect `GIT binary patch` and report
    "binary changes not supported" for that file instead of dropping it
    silently. Test: binary/mixed patch → message, text parts still imported.

## Phase 2 — Merge & FileDiff interaction

12. **M1 + M6 — targeted, scroll-stable merge.** Replace only the chunk's line
    range (not the whole document), preserve caret/first-visible line, and lift
    read-only on the destination pane for the edit. Tests: merge near top keeps
    scroll position; insert-hunk merge into the (formerly read-only) pane works.
13. **M2 — guard action clicks.** `_on_action` returns unless
    `has_action_marker(line)`; do not match zero-width chunks for a plain margin
    click. Test: click empty margin → no change.
14. **M3 — view-level undo/redo.** Route Edit ▸ Undo/Redo through the FileDiff
    view to the pane that actually last changed (track it), not
    `focusWidget()`. Test: merge then Undo reverts the merge.
15. **M4 + M5 — 3-way outer deletions & base inline.** Give an outer-pane
    deletion a visible affordance (a zero-height marker/arrow at the boundary
    line) that copies the deletion to base; fix `_inline_one_sided` so the base
    pane diffs against the correct outer text with correct indices. Tests:
    outer deletion is mergeable to base; base inline marks match.
16. **M7 — BOM round-trip.** Add `utf-8-sig` to the codec chain and re-add the
    BOM on save when the file had one. Test: BOM file edit+save preserves BOM.
17. **M8 — refuse blind overwrite.** In `save()`, if the current on-disk token
    differs from `_disk_token[pane]` and the change wasn't ours, prompt/refuse
    (force flag for the explicit override). Test: external change + save →
    refused/prompted.
18. **M9 — patch-import watcher.** Initialize disk tokens for import views and
    don't treat our own save of a shared path as an external change; don't offer
    Reload into the read-only reference pane. Test: double-save → no bogus
    prompt.
19. **M10 — LinkMap EOF band.** Give a chunk touching the last (newline-less)
    line a nonzero height (use line bottom / `line_height`). Test:
    final-line-only change draws a visible band.

## Phase 3 — Save/close & DirDiff

20. **S1 — honor save failure on close.** If `_save_all_panes` reports any
    failure (or a modified no-path pane), do **not** close; keep the tab and
    surface the error. Applies to `_on_tab_close_requested` and `closeEvent`.
    Test: read-only target + Save-on-close → tab stays, error shown.
21. **D1 — one-sided activation.** For a file present on one side, open a
    FileDiff against an empty pane (pass the missing side as an empty/creatable
    pane) instead of rejecting. Test: activating a new/deleted row opens a diff.
22. **D2 + V10 — confirm before irreversible delete.** When `moveToTrash`
    fails (DirDiff) or reverting/removing destroys the only copy (VC), prompt
    before permanent deletion; never fall through silently. Test: trash-fail
    path prompts (monkeypatched). *Flag for real-Mac check.*
23. **D3 — unreadable dir → ERROR.** Distinguish `_listdir` failure from empty;
    emit a STATE_ERROR entry and an infobar message. Test: chmod-000 dir → ERROR
    row, message, not NORMAL.
24. **D4 + D7 — walk cycle & case guards.** Track visited real paths (device,
    inode) to stop symlink cycles; on a case-insensitive FS, collapse
    case-colliding names to one row (or detect and warn). Tests: loop link →
    bounded entries; `README`/`readme` → single correct row.
25. **D6 — copy semantics + errors.** Preserve symlinks (`copytree(symlinks=
    True)`, handle links in `copy2` path), don't silently merge into an
    existing different-type target, and wrap in the C3 error handling. Test:
    copying a symlink row keeps it a symlink.
26. **D5 — filters UI (or explicit descope).** Either wire a minimal name/text
    filter UI + prefs into DirDiff (recommended: at least a VC-dir/name-filter
    default so `.git` is skipped), or update the docs to move filters to the
    deferred backlog. Decision needed — see "Open questions".
27. **D8 + D9 — content compare fidelity/scale.** Only treat files as
    NOCHANGE when a regex actually changed them (compare filtered bytes, not a
    lossy utf-8 decode); stream/compare in chunks instead of slurping whole
    files. Tests: byte-distinct non-UTF-8 files with a non-matching filter →
    MODIFIED; large-file compare doesn't load both fully.
28. **D10 — 3-way copy UI.** Offer per-target copy actions in 3-way mode. Test:
    3-way copy_to reachable from the menu.

## Phase 4 — Version control

29. **V1 — commit renames whole.** Include the rename's old path in the commit
    pathspec (track it in `status()`), or commit the full staged set for a
    rename. Test: commit rename → HEAD has only the new name.
30. **V2 — commit during merge.** Detect a merge state (MERGE_HEAD) and do a
    full `git commit` (no partial pathspec, no pre-`add` that clears conflicts);
    surface refusal instead of faking success. Test: resolve UU + commit →
    commit exists, MERGE_HEAD gone.
31. **V3 — surface VC errors.** `_act`/`commit_files` capture backend
    stderr/returncode and show it in the infobar. Test: failing remove → message.
32. **V4 — rename diff.** Detect renames (`git status`/`diff -M`) and load the
    old path's HEAD content for the left pane. Test: pure rename → identical
    diff, not whole-file add.
33. **V5 — revert staged-add.** Use `git rm --cached` (+ optional worktree
    delete with confirmation) so no ghost `AD` row remains. Test: revert
    staged-add → row disappears.
34. **V6 — scope to location.** Pass the opened subdirectory as a pathspec to
    `status`/commit. Test: opening `repo/sub` lists only `sub/*`.
35. **V7 — preserve selection.** Do an incremental model update (or save/restore
    selection + current index) instead of a full rebuild on every action. Test:
    action keeps selection.
36. **V9 — git availability.** Call `is_git_available` on `set_location`;
    distinguish "git not installed" from "not a repo"; guard `status()` against
    a vanished binary (covered partly by C2/XC2). Test: no-git PATH → correct
    message.
37. **V8, V11, V12 — smaller VC correctness.** Submodule rows: show a
    meaningful message rather than empty-vs-empty; parse copied (`C`) porcelain
    entries (skip the origin token like `R`); make the VC-compare HEAD pane
    read-only and keep its temp tree alive as long as any diff tab references it.
    Tests per item.

## Phase 5 — Performance (large files)

38. **PF1 + PF2 — cooperative diff/highlight.** Debounce `textChanged` and run
    the re-diff + inline highlighting from a QTimer/idle task that consumes the
    matcher's generator in slices (the generator already yields for this),
    keeping the UI responsive; cache inline results per chunk; fix the
    `_INLINE_MAX` guard to `or` (skip when *either* side is huge) and consider
    `InlineMyersSequenceMatcher`. Tests: a reorder-heavy 10k-line edit does not
    block; huge asymmetric chunk is skipped, not run.

## Phase 6 — Platform & polish

39. **X1 — Ctrl+D.** Clear QScintilla's Ctrl+D command binding (or rebind Next
    Change to a non-colliding shortcut) so navigation works in a focused editor.
    Test: Ctrl+D moves to next change, doesn't duplicate a line.
40. **X2 — icons.** Bundle the needed icons as resources (there is already a
    `resources/icons/` set) with a `QIcon.fromTheme(name, fallback)` so macOS/
    Windows aren't blank. *Flag for real-Mac check.*
41. **X3, X4, X5, X6, X9 — leaks & dead wiring.** Remove the stale Save-As
    watch; use a proper monospace default font family per-OS; share one item
    list per `history_id` (or persist all fields on accept); parent context
    menus with `WA_DeleteOnClose`; delete dead symbols. Tests where observable.
42. **X7 + X8 — CLI & dialog validation.** Reject/curtail >3 file paths with a
    clear error (align help text); validate New-Comparison input before closing.
    Tests.

## Phase 7 — Documentation

43. **DOC1 — README.** Rewrite for the fork: PyQt6 + PyQt6-QScintilla deps,
    `pip install -e ".[dev]"`, `meldq` entry point, what works vs deferred.
44. **DOC2 — MANUAL_TESTS.** Rewrite the VC section for the fresh VcView; drop
    the 1.4 console/Flatten/Previous-Logs steps.
45. **DOC3–DOC6 — reconcile BUILD_PLAN.** Make the scope table match reality:
    move chunkmap, influence-map sync scroll, GSettings-aligned prefs, filter
    UI, size/time columns to a "deferred / not-yet-done" list; correct the test
    count, the theming and `-a` notes; remove or justify the `pygments` extra;
    fix the `PyQt6 >= 6.6` message (X10).

## Suggested sequencing & verification

- **Land Phase 0 first**, as five small commits, each with a red→green
  regression test. These are the ones that lose work or crash.
- Phases 1–2 are the product core (patch + merge) and deserve the most test
  depth — extend the patch battery (the corpus already exists) and add
  offscreen merge/undo/scroll assertions.
- Every commit runs the full suite headless
  (`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q`) and must
  stay green; new tests accompany each fix.
- After Phase 2, do one **real-Mac smoke pass** for the flagged items (trash
  fallback, icons, fonts, Ctrl+D).

## Open questions for the owner

1. **D5 filters** — wire a real filter UI now, or formally move filters to the
   deferred backlog and just add a sane `.git`/VC-dir default? (Recommend the
   latter for v1 + a default name filter.)
2. **P10/P11 binary & deletion patches** — full support, or an explicit
   "unsupported / this deletes X" message for v1? (Recommend explicit messages;
   full support later.)
3. **Fix vs document** for the naive sync scroll (DOC5): implement the
   influence-map mapping now, or reclassify as deferred? (Recommend implement —
   it's small and the current behavior is visibly wrong.)
