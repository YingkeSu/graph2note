# PyInstaller specification for the native macOS desktop bundle.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


# build_macos_app.sh invokes PyInstaller from the repository root. Using the
# working directory also works when this spec is opened directly by hand.
ROOT = Path.cwd().resolve()

datas = collect_data_files("graph2note")
hiddenimports = (
    collect_submodules("graph2note")
    + collect_submodules("eval")
    + collect_submodules("uvicorn")
    + collect_submodules("webview")
)

a = Analysis(
    [str(ROOT / "macos" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    name="Graph2Note",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=bool(os.environ.get("GRAPH2NOTE_DEBUG_BUILD")),
    exclude_binaries=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Graph2Note",
)
app = BUNDLE(
    coll,
    name="Graph2Note.app",
    icon=None,
    bundle_identifier="com.graph2note.app",
    info_plist={
        "CFBundleDisplayName": "Graph2Note",
        "CFBundleName": "Graph2Note",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "13.0",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
    },
)
