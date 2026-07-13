### Copyright (C) 2002-2005 Stephen Kennedy <stevek@gnome.org>

### Redistribution and use in source and binary forms, with or without
### modification, are permitted provided that the following conditions
### are met:
###
### 1. Redistributions of source code must retain the above copyright
###    notice, this list of conditions and the following disclaimer.
### 2. Redistributions in binary form must reproduce the above copyright
###    notice, this list of conditions and the following disclaimer in the
###    documentation and/or other materials provided with the distribution.

### THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
### IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
### OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
### IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
### INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
### NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
### DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
### THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
### (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
### THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import logging
import os
import re
import time

from meldq.conf import _
from meldq.util import misc
from meldq.vc import _vc

log = logging.getLogger(__name__)


class _DummyMatcher:
    """A no-op ignore matcher: match() always returns None (== "not ignored").

    Used when there are no .cvsignore patterns, or when they failed to compile
    (was an inline class in the py2 original; hoisted so the compile-error path
    can bind it — the old code left ``ignore_re`` unbound there and crashed).
    """

    def match(self, *args):
        return None


class Vc(_vc.Vc):
    CMD = "cvs"
    NAME = "CVS"
    VC_DIR = "CVS"
    VC_ROOT_WALK = False
    PATCH_INDEX_RE = "^Index:(.*)$"

    def commit_command(self, message):
        return [self.CMD, "commit", "-m", message]

    def diff_command(self):
        return [self.CMD, "diff", "-u"]

    def update_command(self):
        return [self.CMD, "update"]

    def add_command(self, binary=0):
        if binary:
            return [self.CMD, "add", "-kb"]
        return [self.CMD, "add"]

    def remove_command(self, force=0):
        return [self.CMD, "rm", "-f"]

    def revert_command(self):
        return [self.CMD, "update", "-C"]

    def valid_repo(self):
        if _vc.call([self.CMD, "version"]):
            return False
        else:
            return True

    def _get_dirsandfiles(self, directory, dirs, files):

        try:
            with open(os.path.join(directory, self.VC_DIR, "Entries"),
                      encoding="utf-8", errors="replace") as fh:
                entries = fh.read()
            # poor man's universal newline
            entries = entries.replace("\r", "\n").replace("\n\n", "\n")
        except OSError:  # no cvs dir
            d = [_vc.Dir(x[1], x[0], _vc.STATE_NONE) for x in dirs]
            f = [_vc.File(x[1], x[0], _vc.STATE_NONE, None) for x in files]
            return d, f

        try:
            with open(os.path.join(directory, self.VC_DIR, "Entries.Log"),
                      encoding="utf-8", errors="replace") as fh:
                logentries = fh.read()
        except OSError:
            pass
        else:
            # (?m) must be a re.M flag arg, not a trailing inline group — a
            # trailing "(?m)" is a hard re.error on Python >= 3.11.
            matches = re.findall(r"^([AR])\s*(.+)$", logentries, re.M)
            toadd = []
            for match in matches:
                if match[0] == "A":
                    toadd.append(match[1])
                elif match[0] == "R":
                    try:
                        toadd.remove(match[1])
                    except ValueError:
                        pass
                else:
                    log.warning("Unknown Entries.Log line '%s'", match[0])
            entries += "\n".join(toadd)

        retfiles = []
        retdirs = []
        matches = re.findall(r"^(D?)/([^/]+)/(.+)$", entries, re.M)
        matches.sort()

        for match in matches:
            isdir = match[0]
            name = match[1]
            path = os.path.join(directory, name)
            rev, date, options, tag = match[2].split("/")
            if tag:
                tag = tag[1:]
            if isdir:
                if os.path.exists(path):
                    state = _vc.STATE_NORMAL
                else:
                    state = _vc.STATE_MISSING
                retdirs.append(_vc.Dir(path, name, state))
            else:
                if rev.startswith("-"):
                    state = _vc.STATE_REMOVED
                elif date == "dummy timestamp":
                    if rev[0] == "0":
                        state = _vc.STATE_NEW
                    else:
                        # Was: print + fall through, leaking the previous
                        # file's state (or NameError on the first file). Now
                        # an explicit error state.
                        log.warning("Revision '%s' not understood", rev)
                        state = _vc.STATE_ERROR
                elif date == "dummy timestamp from new-entry":
                    state = _vc.STATE_MODIFIED
                else:
                    date = re.sub(r"\s*\d+", lambda x: "%3i" % int(x.group()),
                                  date, count=1)
                    plus = date.find("+")
                    if plus >= 0:
                        state = _vc.STATE_CONFLICT
                        try:
                            with open(path, encoding="utf-8",
                                      errors="replace") as fh:
                                txt = fh.read()
                        except OSError:
                            pass
                        else:
                            if txt.find("\n=======\n") == -1:
                                state = _vc.STATE_MODIFIED
                    else:
                        try:
                            mtime = os.stat(path).st_mtime
                        except OSError:
                            state = _vc.STATE_MISSING
                        else:
                            if time.asctime(time.gmtime(mtime)) == date:
                                state = _vc.STATE_NORMAL
                            else:
                                state = _vc.STATE_MODIFIED
                retfiles.append(_vc.File(path, name, state, rev, tag, options))
        # known files (a set: the py2 code used a one-shot map() iterator that
        # the first `in` test exhausted, silently misclassifying everything
        # after the first unknown file)
        cvsfiles = {m[1] for m in matches}
        # ignored
        try:
            with open(os.path.join(os.path.expanduser("~"), ".cvsignore"),
                      encoding="utf-8", errors="replace") as fh:
                ignored = fh.read().split()
        except OSError:
            ignored = []
        try:
            with open(os.path.join(directory, ".cvsignore"),
                      encoding="utf-8", errors="replace") as fh:
                ignored += fh.read().split()
        except OSError:
            pass

        if len(ignored):
            try:
                regexes = [misc.shell_to_regex(i)[:-1] for i in ignored]
                ignore_re = re.compile("(" + "|".join(regexes) + ")")
            except re.error as e:
                self.warnings.append(
                    _("Error converting to a regular expression\n"
                      "The pattern was '%s'\n"
                      "The error was '%s'") % (",".join(ignored), e))
                ignore_re = _DummyMatcher()
        else:
            ignore_re = _DummyMatcher()

        for f, path in files:
            if f not in cvsfiles:
                state = (_vc.STATE_NONE if ignore_re.match(f) is None
                         else _vc.STATE_IGNORED)
                retfiles.append(_vc.File(path, f, state, ""))
        for d, path in dirs:
            if d not in cvsfiles:
                state = (_vc.STATE_NONE if ignore_re.match(d) is None
                         else _vc.STATE_IGNORED)
                retdirs.append(_vc.Dir(path, d, state))

        return retdirs, retfiles
