import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Hermetic git: CI runners and containers have no git identity configured, and
# git commit/merge refuse to run without one ("Please tell me who you are").
# The env vars cover author + committer without touching any real config.
os.environ.setdefault("GIT_AUTHOR_NAME", "meldq-tests")
os.environ.setdefault("GIT_AUTHOR_EMAIL", "meldq-tests@example.invalid")
os.environ.setdefault("GIT_COMMITTER_NAME", "meldq-tests")
os.environ.setdefault("GIT_COMMITTER_EMAIL", "meldq-tests@example.invalid")

# ---------------------------------------------------------------------------
# Legacy-tree test marking: these files exercise the 1.4-era reference code
# (meldq/ top-level filediff/dirdiff/vcview/vc/ + old widgets), kept as a
# behavioral archive. Run only the fresh product suite with:  -m "not legacy"
# (CI runs everything). test_editor_geometry.py is intentionally NOT marked —
# it carries fresh MeldSciView regressions alongside legacy geometry tests,
# and test_historycombo.py is unmarked because the fresh New-Comparison dialog
# actively uses that widget.
# ---------------------------------------------------------------------------
import pytest  # noqa: E402

_LEGACY_TEST_FILES = {
    "test_app_shell.py", "test_chunk_ops.py", "test_diffmap.py",
    "test_action_manager.py", "test_doc.py", "test_filediff_integration.py",
    "test_dirdiff_scan.py", "test_faketext.py", "test_filediff_load.py",
    "test_filemerge.py", "test_filediff_save.py", "test_filediff_status.py",
    "test_filediff_widget.py", "test_linkmap.py", "test_findbar.py",
    "test_newcomparison.py", "test_inline_highlight.py", "test_msgarea.py",
    "test_scheduler_pump.py", "test_rediff.py", "test_sync_scroll.py",
    "test_vc_base.py", "test_vc_git.py", "test_vc_mercurial.py",
    "test_treemodel.py", "test_vcview_actions.py", "test_vc_bzr.py",
    "test_vc_svn.py", "test_vc_cvs.py", "test_vcview_diff.py",
    "test_vcview_commands.py", "test_vcview_scan.py", "test_vcview_commit.py",
    "test_vcview_window.py", "test_vc_purity.py",
    "test_vc_registry.py", "test_util_misc_vc.py",
}


def pytest_collection_modifyitems(items):
    for item in items:
        if item.fspath.basename in _LEGACY_TEST_FILES:
            item.add_marker(pytest.mark.legacy)
