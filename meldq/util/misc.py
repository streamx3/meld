### Copyright (C) 2002-2006 Stephen Kennedy <stevek@gnome.org>
### Copyright (C) 2009 Vincent Legoll <vincent.legoll@gmail.com>

### This program is free software; you can redistribute it and/or modify
### it under the terms of the GNU General Public License as published by
### the Free Software Foundation; either version 2 of the License, or
### (at your option) any later version.

### This program is distributed in the hope that it will be useful,
### but WITHOUT ANY WARRANTY; without even the implied warranty of
### MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
### GNU General Public License for more details.

### You should have received a copy of the GNU General Public License
### along with this program; if not, write to the Free Software
### Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""Module of commonly used helper classes and functions

Toolkit-free by contract: importing Qt from this module is forbidden and
test-enforced. The GTK dialog/menu helpers of the 1.4 module live in the
application shell instead.
"""

import codecs
import copy
import errno
import os
import re
import select
import shutil
import subprocess

from meldq.conf import _

whitespace_re = re.compile(r"\s")

def cmdout(cmd, text=None, **kwargs):
    stdin = subprocess.DEVNULL
    if text is not None:
        stdin = subprocess.PIPE
    new_kwargs = {
                  'stdin': stdin,
                  'stdout': subprocess.PIPE,
                  'stderr': subprocess.DEVNULL,
                  'text': True,
                  }
    new_kwargs.update(kwargs)
    p = subprocess.Popen(cmd, **new_kwargs)
    out = p.communicate(text)[0]
    status = p.wait()
    return out, status

def shelljoin( command ):
    def quote(s):
        # falsy strings are quoted too: '' -> '""'
        return s if s and whitespace_re.search(s) is None else '"%s"' % s
    return " ".join( [ quote(x) for x in command ] )

class struct:
    """Similar to a dictionary except that members may be accessed as s.member.

    Usage:
    s = struct(a=10, b=20, d={"cat":"dog"} )
    print(s.a + s.b)
    """
    def __init__(self, **args):
        self.__dict__.update(args)
    def __repr__(self):
        r = ["<"]
        for i in self.__dict__.keys():
            r.append("%s=%s" % (i, getattr(self, i)))
        r.append(">\n")
        return " ".join(r)
    def __eq__(self, other):
        return self.__dict__ == other.__dict__

def all_equal(alist):
    """Return true if all members of the list are equal to the first.

    An empty list is considered to have all elements equal.
    """
    if len(alist):
        first = alist[0]
        for n in alist[1:]:
            if n != first:
                return False
    return True

def shorten_names(*names):
    """Remove redunant parts of a list of names (e.g. /tmp/foo{1,2} -> foo{1,2}
    """
    prefix = os.path.commonprefix( names )
    prefixslash = prefix.rfind("/") + 1

    names = list(map(lambda x: x[prefixslash:], names)) # remove common prefix
    paths = list(map(lambda x: x.split("/"), names)) # split on /

    try:
        basenames = list(map(lambda x: x[-1], paths))
    except IndexError:
        pass
    else:
        if all_equal(basenames):
            def firstpart(alist):
                if len(alist) > 1:
                    return "[%s] " % alist[0]
                else:
                    return ""
            roots = list(map(firstpart, paths))
            base = basenames[0].strip()
            return [ r+base for r in roots ]
    # no common path. empty names get changed to "[None]"
    return list(map(lambda x: x or _("[None]"), basenames))

def read_pipe_iter(command, errorstream, yield_interval=0.1, workdir=None):
    """Read the output of a shell command iteratively.

    Each time 'callback_interval' seconds pass without reading any data,
    this function yields None.
    When all the data is read, the entire string is yielded.
    If 'workdir' is specified the command is run from that directory.

    The pipes are read as bytes; the final value is decoded as utf-8 with
    errors replaced, and only str is ever written to 'errorstream'.
    Closing the generator kills a still-running process.
    """
    if workdir == "":
        workdir = None
    proc = subprocess.Popen(command, cwd=workdir, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.stdin.close()
    childout, childerr = proc.stdout, proc.stderr
    err_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    bits = []
    try:
        while len(bits) == 0 or bits[-1] != b"":
            state = select.select([childout, childerr], [], [childout, childerr], yield_interval)
            if len(state[0]) == 0:
                if len(state[2]) == 0:
                    yield None
                else:
                    raise Exception("Error reading pipe")
            if childout in state[0]:
                try:
                    # read1 returns whatever is available and b"" only at
                    # EOF; read(4096) would block until a full buffer
                    bits.append(childout.read1(4096))
                except OSError:
                    break # ick need to fix
            if childerr in state[0]:
                try:
                    errorstream.write(err_decoder.decode(childerr.read1(4096)))
                except OSError:
                    break # ick need to fix
        status = proc.wait()
        errorstream.write(err_decoder.decode(childerr.read(), final=True))
        if status:
            errorstream.write("Exit code: %i\n" % status)
        yield b"".join(bits).decode("utf-8", errors="replace")
    finally:
        if proc.poll() is None:
            errorstream.write("killing '%s'\n" % command[0])
            proc.terminate()
            errorstream.write("killed (status was '%i')\n" % proc.wait())

def write_pipe(command, text):
    """Write 'text' into a shell command and discard its stdout output.
    """
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    proc.communicate(text)
    return proc.wait()

def commonprefix(dirs):
    """Given a list of pathnames, returns the longest common leading component.
    """
    if not dirs: return ''
    n = copy.copy(dirs)
    for i in range(len(n)):
        n[i] = n[i].split(os.sep)
    prefix = n[0]
    for item in n:
        for i in range(len(prefix)):
            if prefix[:i+1] != item[:i+1]:
                prefix = prefix[:i]
                if i == 0:
                    return ''
                break
    return os.sep.join(prefix)

def copy2(src, dst):
    """Like shutil.copy2 but ignores chmod errors.
    See [Bug 568000] Copying to NTFS fails
    """
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    shutil.copyfile(src, dst)
    try:
        shutil.copystat(src, dst)
    except OSError as e:
        if e.errno != errno.EPERM:
            raise

def copytree(src, dst, symlinks=True):
    try:
        os.mkdir(dst)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
    names = os.listdir(src)
    for name in names:
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        if symlinks and os.path.islink(srcname):
            linkto = os.readlink(srcname)
            os.symlink(linkto, dstname)
        elif os.path.isdir(srcname):
            copytree(srcname, dstname, symlinks)
        else:
            copy2(srcname, dstname)

def shell_escape(glob_pat):
    # TODO: handle all cases
    assert not re.compile(r"[][*?]").findall(glob_pat)
    return glob_pat.replace('{', '[{]').replace('}', '[}]')

def shell_to_regex(pat):
    """Translate a shell PATTERN to a regular expression.

    Based on fnmatch.translate(). We also handle {a,b,c} where fnmatch does not.
    """

    i, n = 0, len(pat)
    res = ''
    while i < n:
        c = pat[i]
        i += 1
        if c == '\\':
            try:
                c = pat[i]
            except IndexError:
                pass
            else:
                i += 1
                res += re.escape(c)
        elif c == '*':
            res += '.*'
        elif c == '?':
            res += '.'
        elif c == '[':
            try:
                j = pat.index(']', i)
            except ValueError:
                res += r'\['
            else:
                stuff = pat[i:j]
                i = j+1
                if stuff[0] == '!':
                    stuff = '^%s' % stuff[1:]
                elif stuff[0] == '^':
                    stuff = r'\^%s' % stuff[1:]
                res += '[%s]' % stuff
        elif c == '{':
            try:
                j = pat.index('}', i)
            except ValueError:
                res += r'\{'
            else:
                stuff = pat[i:j]
                i = j+1
                res += '(%s)' % "|".join([shell_to_regex(p)[:-1] for p in stuff.split(",")])
        else:
            res += re.escape(c)
    return res + "$"

class ListItem:
    __slots__ = ("name", "active", "value")
    def __init__(self, s):
        a = s.split("\t")
        self.name = a.pop(0)
        self.active = int(a.pop(0))
        self.value = " ".join(a)
    def __str__(self):
        return "<%s %s %i %s>" % ( self.__class__, self.name, self.active, self.value )


def gtk_mnemonic_to_qt(label):
    """'_Match Case' -> '&Match Case'.

    Escape literal '&' first, then convert only the FIRST underscore (the
    GTK mnemonic marker) to '&'. Always call _() BEFORE this so the msgid
    keeps its underscore form for the catalogs.
    """
    return label.replace("&", "&&").replace("_", "&", 1)


def char_to_utf16_offset(text, char_offset):
    """Python-str codepoint offset -> QTextDocument UTF-16 code-unit offset."""
    return char_offset + sum(1 for c in text[:char_offset] if ord(c) > 0xFFFF)


def utf16_to_char_offset(text, utf16_offset):
    """Inverse of char_to_utf16_offset (walk codepoints, count 2 for astral)."""
    units = 0
    for i, c in enumerate(text):
        if units >= utf16_offset:
            return i
        units += 2 if ord(c) > 0xFFFF else 1
    return len(text)
