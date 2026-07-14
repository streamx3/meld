# Meld 1.4 → 3.24 divergence map (re-port planning basis)

Generated 2026-07-14 by a 19-agent workflow (9 subsystems × assess + adversarial
challenge + synthesis) comparing the PyQt6 port (`meldq/`, which reproduces Meld
**1.4.0** behavior) against the **3.24.0** reference source (`meld/`). Verdicts below
are *reconciled* — where the adversarial challenger overturned the initial assessment
(always upward), the corrected value is shown.

## Bottom line

| Subsystem | Verdict | Effort (pd) | Confidence |
|---|---|---:|---|
| filediff | **rewrite** | 35–50 | high |
| vc (vcview + vc/) | **rewrite** | 14–20 | high |
| dirdiff | **rewrite** | 12–16 | medium |
| widgets (linkmap/diffmap/treemodel/findbar/historycombo/msgarea) | **rewrite** | 9–13 | high |
| shell (app/window/doc/CLI) | **rewrite** | 8–13 | high |
| patch export + VC-compare | **rewrite** | 8–12 | high |
| engine (diff/merge/undo/scheduler) | **rewrite** | 7–9 | high |
| prefs | **rewrite** | 4–6 | high |
| util/misc | adapt | 6–9 | high |
| **TOTAL** | | **103–148** | |

**A re-port of the existing code costs ~103–148 pd — *more* than a from-scratch port
against 3.24 (estimated 66–99 pd).** The 1.4-shaped code is, in many places, a
liability: you adapt-and-fight rather than design clean, and every "keep" hides
false-keep landmines (subtly wrong behavior that must be found and fixed). Even the
engine — the strongest keep candidate — needs rewrite-level work.

## What actually carries over (it is NOT the module code)

- **Qt architecture patterns / learnings** (the expensive, durable asset): the
  scheduler-pump idiom, "no modal inside a generator frame → defer via singleShot",
  model-lifetime/parenting to avoid GC segfaults, the cooperative-scan structure. These
  are baked into whatever we build next regardless of base.
- **The test harness**: pytest-qt + offscreen + fixtures + the adversarial-verification
  workflow method.
- **A few genuinely pure/reusable helpers**: `shell_to_regex` (byte-identical to 3.24),
  the Qt-only `gtk_mnemonic_to_qt` / UTF-16 offset bridges, the QSettings descriptor
  mechanism (`Value`/`Preferences` write-through + `changed` signal), `shell_escape`.
- **Domain knowledge**: how diff/merge/VC/dirdiff behave and what each widget must do.

So the value of the 1.4 port is as a **learning vehicle + pattern library + reference**,
not a code foundation.

## Per-subsystem highlights (top false-keeps + biggest 3.24 gaps)

### filediff — rewrite 35–50 pd (the crux)
- 3.24 is built on **GtkSourceView** (`meldbuffer`/`sourceview`/`gutterrendererchunk`/
  `actiongutter`/`diffgrid`); merges happen via the **ActionGutter buttons**, not
  linkmap icons. Our entire `linkmap.py` icon/keymask merge interaction is a UI 3.24
  **removed** — shipping it reproduces a 1.4 tool.
- **Engine coupling is a hard blocker**: 3.24 filediff calls `get_chunk_starts`,
  `paired_all_single_changes`, `has_chunk`, `.conflicts`, `merged_chunk_order` — our
  engine lacks all of them, and uses `AutoMergeDiffer` where 3.24 uses `Differ`.
- Colors come from the **style scheme** (light/dark), not `color_*` prefs. Silent drops:
  line numbers, word wrap, syntax highlighting are all no-ops in our port.
- New: sync points, conflict navigation, copy-up/down, swap panes, go-to-line, file
  monitor/reload prompt, read-only toggles, overview-map styles, image-diff routing.

### vc — rewrite 14–20 pd
- **Zero plugin-API overlap**: our command-list plugins vs 3.24's runner-action +
  `get_valid_actions` / `get_path_for_repo_file` / `get_path_for_conflict` /
  `refresh_vc_state`. State enum `range(12)` vs `range(15)` (RENAMED/NONEXIST/SPINNER).
- **Our `show_patch` GNU-patch reconstruction is a MAJOR false keep** — 3.24 deleted it
  entirely and compares working-vs-repository via temp checkouts + 3-way conflict merge.
- Our delete is **permanent** (`os.remove`/`rmtree`); 3.24 moves to Trash. Conflict
  resolution (3-way merge) is absent from our port entirely.

### dirdiff — rewrite 12–16 pd
- `_files_same` 0/1/2 vs 3.24's **6-valued** enum (loses shallow / ignore-blank-lines /
  DodgySame / FileError). Absent files use STATE_MISSING vs 3.24 STATE_NONEXIST.
- Our `_filter_on_state` **hides a differing file nested in an otherwise-same folder**
  when the Same filter is off (real visibility bug we faithfully reproduce).
- New: shallow compare, size/time/perms columns, comparison markers, symlink display,
  trash-delete, scanning spinner, msgarea info bars, invalid-encoding detection.

### widgets — rewrite 9–13 pd
- **LinkMap** = 1.4 icon-merge interaction 3.24 removed (→ ActionGutter). **DiffMap** →
  3.24 **ChunkMap** with a you-are-here handle + drag scrubbing. Tree state ints frozen
  at `range(12)`; colors/icons hardcoded hex vs style-scheme + symbolic emblems.
- `MsgArea.new_from_text_and_icon` arg order is **reversed** vs 3.24, and lacks
  `add_dismissable_msg`/`add_action_msg` that dirdiff/vcview call → direct API breakage.
- `FileHistoryCombo` reproduces a file entry 3.24 **deleted** (→ `MeldFileButton`).

### shell — rewrite 8–13 pd
- Our SchedulerPump drives **only the current tab** → background scans **stall on tab
  switch** (3.24 keeps all page schedulers running). No GAction/GMenu/headerbar model.
- `create_diff` drops the 3.24 options dict (auto_merge/merge_output/meta); `label_changed`
  is 1-arg vs 3.24's 2-arg. Stale bug/help/about URLs. No recent-comparisons, no
  single-instance GtkApplication, no ImageDiff routing, no async-save close state machine.

### engine — rewrite 7–9 pd
- Regular comparisons use `Differ` in 3.24, not `AutoMergeDiffer`. Missing
  `myers.postprocess()` → **finer/more chunks** than 3.24 on the same files. Missing
  `has_chunk`/`get_chunk_starts`/`paired_all_single_changes`; no `conflicts` list; no
  incremental `diffs-changed(chunk_changes)`; no async inline matcher. Empty-file
  IndexError crash where 3.24 returns 0.

### prefs — rewrite 4–6 pd
- **The 10 `color_*` keys + Display-tab color pickers are built on prefs 3.24 DELETED** —
  3.24 uses GtkSourceView **style schemes** (meld-base/meld-dark) + `style-scheme` /
  `prefer-dark-theme`. Filter storage is tab-strings vs 3.24 `a(sbs)`. Many new keys
  (folder columns, shallow compare, VC file order, overview-map style, whitespace drawer).

### util — adapt 6–9 pd
- Cleanest survivor. `shell_to_regex` byte-identical (verified 21 patterns, 0 diffs).
  But `read_pipe_iter` yields no exit code (3.24's runner needs it); `copy2`/`copytree`
  follow symlinks where 3.24 preserves them; missing `apply_text_filters` (group-aware).

## The owner's headline feature (patch handling) is greenfield either way
The map found that **neither 3.24 nor our port can apply/import an arbitrary external
`.patch` file**. A genuinely good patch-handling capability is **net-new for both** — so
the differentiator is greenfield work independent of which base we build on. 3.24's
`patchdialog.py` only *exports* a patch (with 3-pane side selection + reverse + live
highlight our port lacks).

## Strategic options (for the owner to decide)

1. **Re-port the existing code onto 3.24** — ~103–148 pd, salvages some code + continuity,
   but you fight the 1.4 legacy and clear false-keep landmines. *Not obviously better than
   fresh, and by the numbers, worse.*
2. **Fresh, scope-controlled build against the 3.24 spec** — reuse only the harness +
   Qt patterns + pure utils (already done, so not zero-based; ~50–80 pd), design clean,
   no false-keep landmines. **Recommended.**
3. **Deliberately narrow scope** — build the core (2/3-way file + dir + basic VC + strong
   patch handling) well and explicitly *skip* 3.24's long tail (imagediff, sync points,
   overview-map styles, recent-comparisons, single-instance, etc.). The most
   product-pragmatic path; pairs naturally with option 2.

**Recommendation: 2 + 3** — treat this as a fresh, scope-controlled build against the 3.24
behavior spec, keeping the 1.4 `meldq/` tree as *reference*, reusing the scaffolding, and
making strong patch handling the headline. The 1.4 port did its job: it taught us how to
build Meld in Qt. That knowledge, not its code, is what we carry forward.
