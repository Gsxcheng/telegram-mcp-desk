"""Regenerate packaging/tgmcp-desk.ico from the in-app icon drawing (run before PyInstaller)."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tgmcp_desk.ui.common import app_icon  # noqa: E402


def main() -> None:
    app = QApplication.instance() or QApplication([])  # noqa: F841 - fonts need an app
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("tgmcp-desk.ico"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [
        app_icon().pixmap(s, s).toImage().convertToFormat(QImage.Format.Format_ARGB32)
        for s in sizes
    ]
    # Write a PNG-compressed multi-size ICO by hand (Qt's ICO writer stores one size).
    import io
    import struct

    from PySide6.QtCore import QBuffer, QIODevice

    blobs = []
    for img in images:
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        blobs.append(bytes(buf.data()))
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for size, blob in zip(sizes, blobs, strict=True):
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    data = io.BytesIO()
    data.write(header + entries)
    for blob in blobs:
        data.write(blob)
    out.write_bytes(data.getvalue())
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
