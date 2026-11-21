# -*- mode: python ; coding: utf-8 -*-

import os
import tempfile
from pathlib import Path

from PIL import Image
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent
icon_png = root / "src" / "babanongchang" / "icon.png"
icon_override = os.environ.get("BABANONGCHANG_ICON")
if icon_override:
    icon_ico = Path(icon_override)
else:
    icon_ico = Path(tempfile.gettempdir()) / "babanongchang.ico"
    Image.open(icon_png).save(icon_ico, format="ICO", sizes=[(256, 256), (48, 48), (32, 32), (16, 16)])

datas = [(str(icon_png), "babanongchang")]
binaries = []
hiddenimports = collect_submodules("babanongchang")
for package in (
    "rapidocr",
    "onnxruntime",
    "cv2",
    "numpy",
    "omegaconf",
    "shapely",
    "pyclipper",
    "yaml",
    "PIL",
    "tomlkit",
    "colorlog",
    "tqdm",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [str(root / "packaging" / "entry.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="babanongchang",
    icon=str(icon_ico),
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="babanongchang",
)
