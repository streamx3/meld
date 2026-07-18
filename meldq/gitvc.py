"""Qt-free git backend for the version-control view (milestone M4).

Just enough git for v1: find the repo, list changed/untracked files with a
state, and fetch a file's committed (HEAD) content so a working-vs-repository
FileDiff can be opened. Everything shells out to the ``git`` CLI in text/binary
mode — no Qt, no gi. hg/svn/etc. slot in behind the same shape later.
"""

import os
import subprocess
from collections import namedtuple

STATE_NORMAL, STATE_MODIFIED, STATE_NEW, STATE_REMOVED, STATE_CONFLICT, \
    STATE_IGNORED = range(6)


class VcResult(namedtuple("VcResult", "ok message")):
    """Outcome of a VC action. Truthy when it succeeded (so `if vc.add(...)`
    and `assert vc.add(...)` keep working), and carrying git's error text so
    the UI can surface it instead of failing silently."""
    __slots__ = ()

    def __bool__(self):
        return self.ok


def _run(repo_root, args, binary=False):
    return subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True,
        text=not binary)


def _result(proc):
    if proc.returncode == 0:
        return VcResult(True, "")
    msg = (proc.stderr or "").strip() or ("git exited with %d" % proc.returncode)
    return VcResult(False, msg)


def is_git_available():
    try:
        subprocess.run(["git", "--version"], capture_output=True)
        return True
    except OSError:
        return False


def find_repo_root(path):
    """The git work-tree root containing `path`, or None."""
    start = path if os.path.isdir(path) else os.path.dirname(path) or "."
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=start,
            capture_output=True, text=True)
    except OSError:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _classify(xy):
    """Two porcelain status chars -> a state."""
    if xy == "??":
        return STATE_NEW
    if xy in ("DD", "AU", "UD", "UA", "DU", "AA", "UU") or "U" in xy:
        return STATE_CONFLICT
    if "D" in xy:
        return STATE_REMOVED
    if "A" in xy:
        return STATE_NEW
    return STATE_MODIFIED        # M / T / R / C


def status(repo_root, pathspec=None):
    """Map relpath -> state for every file git reports as changed or untracked.

    Uses ``git status --porcelain -z`` so paths with spaces/newlines are safe;
    a rename ("R") or copy ("C") entry carries a trailing origin-path token
    which is skipped. `pathspec` scopes the report to a subdirectory.
    """
    args = ["status", "--porcelain", "-z", "--untracked-files=all"]
    if pathspec:
        args += ["--", pathspec]
    proc = _run(repo_root, args)
    if proc.returncode != 0:
        return {}
    tokens = proc.stdout.split("\0")
    result = {}
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if not entry or len(entry) < 3:
            continue
        xy, path = entry[:2], entry[3:]
        if "R" in xy or "C" in xy:   # rename/copy: consume the origin-path token
            i += 1
        result[path] = _classify(xy)
    return result


def repo_file_content(repo_root, relpath, ref="HEAD"):
    """Bytes of `relpath` at `ref` (the committed version), or None if it does
    not exist there (e.g. an untracked/added file)."""
    proc = _run(repo_root, ["show", "%s:%s" % (ref, relpath)], binary=True)
    return proc.stdout if proc.returncode == 0 else None


def rename_origin(repo_root, new_relpath):
    """The old path of `new_relpath` if git reports it as a rename, else None.
    Lets a working-vs-repo diff show the committed content under the OLD name
    instead of an empty pane (a renamed path does not exist at HEAD)."""
    olds = _rename_old_paths(repo_root, {new_relpath})
    return olds[0] if olds else None


def add(repo_root, relpath):
    """Stage `relpath` (start tracking / mark resolved). -> VcResult."""
    return _result(_run(repo_root, ["add", "--", relpath]))


def remove(repo_root, relpath):
    """git-remove `relpath` (and delete it from the work tree). -> VcResult."""
    return _result(_run(repo_root, ["rm", "-r", "--", relpath]))


def commit(repo_root, message, relpaths=()):
    """Commit `relpaths` with `message`; if none given, commit whatever is
    already staged. -> VcResult.

    During a merge git refuses a partial (pathspec) commit, so commit everything
    that is staged instead — and stage the requested paths first so
    untracked/deleted files are included."""
    if relpaths:
        # Stage the selected (existing) paths so untracked files are included;
        # a rename's OLD path is a deletion git-mv already staged and can't be
        # `git add`ed (pathspec matches no working file), so add it to the
        # COMMIT pathspec only — else HEAD would keep both the old and new file.
        staged = _run(repo_root, ["add", "-A", "--", *relpaths])
        if staged.returncode != 0:
            return _result(staged)
        commit_paths = list(relpaths) + _rename_old_paths(repo_root, set(relpaths))
        if _merge_in_progress(repo_root):
            proc = _run(repo_root, ["commit", "-m", message])
        else:
            proc = _run(repo_root, ["commit", "-m", message, "--", *commit_paths])
    else:
        proc = _run(repo_root, ["commit", "-m", message])
    return _result(proc)


def _rename_old_paths(repo_root, new_paths):
    """Old paths for any rename whose new path is in `new_paths`."""
    proc = _run(repo_root, ["status", "--porcelain", "-z"])
    if proc.returncode != 0:
        return []
    tokens = proc.stdout.split("\0")
    olds = []
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if len(entry) >= 3 and "R" in entry[:2]:
            new = entry[3:]
            old = tokens[i] if i < len(tokens) else ""
            i += 1                          # consume the origin-path token
            if new in new_paths and old:
                olds.append(old)
    return olds


def revert(repo_root, relpath):
    """Discard working changes to `relpath`. A tracked file is restored from
    HEAD; a staged-added file is unstaged AND removed (git rm --cached + unlink,
    so no ghost 'AD' entry remains); a plain untracked file is deleted.
    -> VcResult."""
    state = status(repo_root).get(relpath)
    at_head = repo_file_content(repo_root, relpath) is not None
    if state == STATE_NEW and not at_head:
        # Not committed: drop the index entry (if staged) and the working file.
        _run(repo_root, ["rm", "--cached", "--", relpath])   # no-op if untracked
        try:
            os.remove(os.path.join(repo_root, relpath))
            return VcResult(True, "")
        except OSError as exc:
            return VcResult(False, str(exc))
    return _result(_run(repo_root, ["checkout", "HEAD", "--", relpath]))


def _merge_in_progress(repo_root):
    return os.path.exists(os.path.join(repo_root, ".git", "MERGE_HEAD"))
