# -*- mode: python ; coding: utf-8 -*-
#
# MEFE Muhasebe - PyInstaller spec dosyası
# -------------------------------------------------------------
# Bu spec dosyası tek dosya (--onefile) Windows EXE üretir.
# Yapılandırma:
#   - main.py giriş noktası
#   - MEFE şeffaf logosu ve .ico ikonu pakete dahil edilir
#   - sv-ttk tema paketinin TCL kaynak dosyaları otomatik toplanır
#   - PIL/Pillow hidden import olarak işaretlenir (Tkinter PhotoImage için)
#
# Build:
#   pyinstaller --clean --noconfirm mefe_muhasebe.spec
#
# Çıktı:
#   dist\MEFE-Muhasebe.exe
# -------------------------------------------------------------

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent.parent
datas = []

# Logo varlıkları
transparent_logo = ROOT / "desktop" / "assets" / "mefe_muhasebe_logo.png"
if transparent_logo.exists():
    datas.append((str(transparent_logo), "desktop/assets"))

# sv-ttk Sun Valley tema TCL dosyalarını otomatik ekle (varsa)
try:
    datas += collect_data_files("sv_ttk")
except Exception:
    pass

app_icon = ROOT / "desktop" / "assets" / "mefe_muhasebe_logo.ico"


a = Analysis(
    ["main.py"],
    pathex=[str(ROOT / "desktop")],
    binaries=[],
    datas=datas,
    hiddenimports=["PIL", "PIL.Image", "PIL.ImageTk", "sv_ttk"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MEFE-Muhasebe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_icon) if app_icon.exists() else None,
)
