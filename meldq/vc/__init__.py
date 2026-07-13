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

import importlib

from meldq.vc import _null

# A static registry instead of the 1.4 glob.glob("[a-z]*.py") + __import__
# discovery, which breaks under zip/frozen installs. Descoped 1.4 backends
# (dead tools) are intentionally absent: cdv, darcs, monotone, rcs, svk, tla.
# Their trees fall through to _null — files show as Unversioned and VC actions
# become no-ops ("true" ...); plain file/dir comparison still works there.
_PLUGIN_MODULE_NAMES = ("bzr", "cvs", "git", "mercurial", "svn")


def load_plugins():
    return [importlib.import_module("meldq.vc.%s" % name)
            for name in _PLUGIN_MODULE_NAMES]


_plugins = load_plugins()


def get_plugins_metadata():
    ret = []
    for p in _plugins:
        # Some plugins have VC_DIR=None until instantiated
        if p.Vc.VC_DIR:
            ret.append(p.Vc.VC_DIR)
        # Most plugins have VC_METADATA=None
        if p.Vc.VC_METADATA:
            ret.extend(p.Vc.VC_METADATA)
    return ret


def get_vcs(location):
    """Pick only the Vcs with the longest repo root

       Some VC plugins search their repository root
       by walking the filesystem upwards its root
       and now that we display multiple VCs in the
       same directory, we must filter those other
       repositories that are located in the search
       path towards "/" as they are not relevant
       to the user.
    """

    vcs = []
    max_len = 0
    for plugin in _plugins:
        try:
            avc = plugin.Vc(location)
            l = len(avc.root)
            if l == max_len:
                vcs.append(avc)
            elif l > max_len:
                max_len = l
                vcs = [avc]
        except ValueError:
            # A plugin constructor raises ValueError to mean "not my repo".
            # NB: only ValueError is caught — a plugin that raised anything
            # else would propagate and break discovery (preserved 1.4 contract).
            pass

    if not vcs:
        # No plugin recognized that location, fallback to _null
        vcs.append(_null.Vc(location))

    return vcs
