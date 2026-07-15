"""Qt-free git backend for the version-control view (milestone M4).

Just enough git for v1: find the repo, list changed/untracked files with a
state, and fetch a file's committed (HEAD) content so a working-vs-repository
FileDiff can be opened. Everything shells out to the ``git`` CLI in text/binary
mode — no Qt, no gi. hg/svn/etc. slot in behind the same shape later.
"""

import os
import subprocess

STATE_NORMAL, STATE_MODIFIED, STATE_NEW, STATE_REMOVED, STATE_CONFLICT, \
    STATE_IGNORED = range(6)


def _run(repo_root, args, binary=False):
    return subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True,
        text=not binary)


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


def status(repo_root):
    """Map relpath -> state for every file git reports as changed or untracked.

    Uses ``git status --porcelain -z`` so paths with spaces/newlines are safe;
    a rename entry ("R") carries a trailing old-path token which is skipped.
    """
    proc = _run(repo_root, ["status", "--porcelain", "-z",
                            "--untracked-files=all"])
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
        if "R" in xy:            # rename: consume the old-path token
            i += 1
        result[path] = _classify(xy)
    return result


def repo_file_content(repo_root, relpath, ref="HEAD"):
    """Bytes of `relpath` at `ref` (the committed version), or None if it does
    not exist there (e.g. an untracked/added file)."""
    proc = _run(repo_root, ["show", "%s:%s" % (ref, relpath)], binary=True)
    return proc.stdout if proc.returncode == 0 else None


def add(repo_root, relpath):
    """Stage `relpath` (start tracking / mark resolved)."""
    return _run(repo_root, ["add", "--", relpath]).returncode == 0


def remove(repo_root, relpath):
    """git-remove `relpath` (and delete it from the work tree)."""
    return _run(repo_root, ["rm", "-r", "--", relpath]).returncode == 0


def revert(repo_root, relpath):
    """Discard working changes to a tracked `relpath` (restore from HEAD). For
    an untracked file, delete it. Returns True on success."""
    if status(repo_root).get(relpath) == STATE_NEW and \
            repo_file_content(repo_root, relpath) is None:
        try:
            os.remove(os.path.join(repo_root, relpath))
            return True
        except OSError:
            return False
    return _run(repo_root, ["checkout", "HEAD", "--", relpath]).returncode == 0
