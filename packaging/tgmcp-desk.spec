# PyInstaller spec: one-folder Windows build of TGMCP Desk.
# Build:  uv run python packaging/make_icon.py && uv run pyinstaller packaging/tgmcp-desk.spec
from pathlib import Path

ROOT = Path(SPECPATH).parent
HELPERS = ROOT / "src" / "tgmcp_desk" / "helpers"

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    # Helper scripts run under telegram-mcp's own Python, so they ship as plain files.
    datas=[(str(p), "tgmcp_desk/helpers") for p in HELPERS.glob("*.py")],
    excludes=["tkinter", "unittest", "pydoc", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TGMCP Desk",
    console=False,
    icon=str(ROOT / "packaging" / "tgmcp-desk.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="TGMCP Desk")
