import subprocess
import sys


def test_full_vc_package_is_qt_free():
    # Importing the WHOLE meldq.vc package runs the registry, which imports all
    # five plugins (git/svn/mercurial/bzr/cvs) + _null. None may pull in Qt —
    # the invariant 1.4 violated by cvs.py importing gtk and svk importing it
    # transitively. Stronger than test_vc_base's _vc-only check.
    code = ("import sys, meldq.vc; "
            "sys.exit(1 if any(m.split('.')[0] == 'PyQt6' "
            "for m in sys.modules) else 0)")
    result = subprocess.run([sys.executable, "-c", code])
    assert result.returncode == 0
