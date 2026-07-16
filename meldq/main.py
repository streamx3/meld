"""Console entry point: [project.scripts] meldq = "meldq.main:main"."""

import argparse
import sys

from meldq import __version__, conf
from meldq.conf import _


def _missing_reqs(mod, exc=None):
    # fixed version of bin/meld:75-81: the message uses str(exc) from the
    # PARAMETER, not a leaked global except-var (the py2 bug at bin/meld:77).
    sys.stderr.write(_("Cannot import: ") + mod + "\n")
    if exc is not None:
        sys.stderr.write(str(exc) + "\n")
    sys.exit(1)


def parse_args(argv):
    usages = [
        ("", _("Start with an empty window")),
        ("<%s|%s>" % (_("file"), _("dir")), _("Start a version control comparison")),
        ("<%s> <%s> [<%s>]" % ((_("file"),) * 3), _("Start a 2- or 3-way file comparison")),
        ("<%s> <%s> [<%s>]" % ((_("dir"),) * 3), _("Start a 2- or 3-way directory comparison")),
        ("<%s> <%s>" % (_("file"), _("dir")), _("Start a comparison between file and dir/file")),
    ]
    pad = max(len(u[0]) for u in usages)
    epilog = "\n".join("  meldq %-*s %s" % (pad, u[0], u[1]) for u in usages)

    parser = argparse.ArgumentParser(
        prog="meldq",
        description=_("Meld is a file and directory comparison tool."),
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    parser.add_argument("-L", "--label", action="append", default=[],
                        help=_("Set label to use instead of file name"))
    parser.add_argument("-a", "--auto-compare", action="store_true",
                        help=_("Automatically compare all differing files on startup"))
    parser.add_argument("-u", "--unified", action="store_true", help=_("Ignored for compatibility"))
    parser.add_argument("-c", "--context", action="store_true", help=_("Ignored for compatibility"))
    parser.add_argument("-e", "--ed", action="store_true", help=_("Ignored for compatibility"))
    parser.add_argument("-r", "--recursive", action="store_true", help=_("Ignored for compatibility"))
    parser.add_argument("--diff", action="append", nargs="+", dest="diff",
                        default=[], metavar="PATH",
                        help=_("Creates a diff tab for up to 3 supplied files or directories."))
    parser.add_argument("paths", nargs="*")

    args = parser.parse_args(argv)
    for group in args.diff:
        if len(group) not in (1, 2, 3, 4):
            parser.error(_("wrong number of arguments supplied to --diff"))
    if len(args.paths) > 4:
        parser.error(_("too many arguments (wanted 0-4, got %d)") % len(args.paths))
    return args


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    profile = "--profile" in argv
    if profile:
        argv.remove("--profile")

    # init i18n BEFORE importing meldq.app / meldq.util.prefs: the prefs
    # defaults evaluate _() at import time.
    conf.init_i18n()

    try:
        from PyQt6.QtGui import QIcon
        from PyQt6.QtWidgets import QApplication
    except ImportError as exc:
        _missing_reqs("PyQt6 >= 6.6", exc)

    try:
        from meldq.shell import MeldWindow
    except ImportError as exc:
        # sciview imports PyQt6.Qsci at load time; surface the real cause.
        _missing_reqs("PyQt6-QScintilla", exc)
    from meldq.util.prefs import Preferences

    app = QApplication(sys.argv)
    app.setApplicationName("Meld")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("meldq")
    app.setWindowIcon(QIcon(str(conf.icon_path("icon.png"))))

    args = parse_args(argv)
    prefs = Preferences()
    window = MeldWindow(prefs)
    window.show()

    # --diff groups accept 1-4 paths each; route through open_paths so a
    # single-path group opens a VC view (like a bare positional path). Labels
    # apply only to the primary positional comparison (3.24 behaviour).
    for files in args.diff:
        window.open_paths(files, args.auto_compare)
    window.open_paths(args.paths, args.auto_compare, args.label or None)

    if profile:
        import cProfile
        result = {}
        cProfile.runctx("result['rc'] = app.exec()", globals(), locals())
        return result["rc"]
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
