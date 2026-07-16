# PyInstaller spec for meldq (macOS .app + Windows .exe).
#
#   pip install -e ".[highlight,package]"
#   pyinstaller packaging/meldq.spec           # -> dist/Meld.app or dist/Meld/
#
# Build on the target OS: PyInstaller does not cross-compile. See
# packaging/README.md for signing/notarising and the Windows one-file variant.

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# Bundle the packaged resources (icons, and locale/ if a build produced it).
datas = collect_data_files("meldq", includes=["resources/**/*", "ui/*"])

# PyQt6.Qsci (QScintilla) ships no standard PyInstaller hook; pull it in
# explicitly along with the lexers meldq.widgets.sciview references.
hiddenimports = ["PyQt6.Qsci"]

a = Analysis(
    ["meldq_launch.py"],
    pathex=[".."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Trim the unused Qt stack so the bundle stays lean.
    excludes=["tkinter", "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtWebEngineCore",
              "PyQt6.QtWebEngineWidgets", "PyQt6.Qt3DCore", "PyQt6.QtBluetooth"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Meld",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no console window on Windows
    # Windows wants a .ico here; convert data/icons/.../org.gnome.Meld.svg once
    # and point this at it. Left None so a fresh checkout builds without assets.
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="Meld",
)
app = BUNDLE(
    coll,
    name="Meld.app",
    icon=None,              # supply an .icns here for a Dock icon on macOS
    bundle_identifier="org.streamx3.meldq",
    info_plist={
        "CFBundleName": "Meld",
        "CFBundleDisplayName": "Meld",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,   # allow the dark palette
    },
)
