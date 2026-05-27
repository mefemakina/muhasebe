"""
Installer .iss dosyasındaki MyAppVersion makrosunu uyumsoft_cari.__version__ ile senkronize eder.
Build pipeline'ında PyInstaller'dan ÖNCE çalıştırın:
    python tools/sync_installer_version.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from uyumsoft_cari import __version__  # noqa: E402

ISS_PATH = ROOT / "MEFE-Muhasebe-Installer.iss"


def main() -> int:
    text = ISS_PATH.read_text(encoding="utf-8")
    new_text, n = re.subn(
        r'#define MyAppVersion "[^"]*"',
        f'#define MyAppVersion "{__version__}"',
        text,
        count=1,
    )
    if n == 0:
        print(f"HATA: MyAppVersion satırı bulunamadı: {ISS_PATH}", file=sys.stderr)
        return 1
    if new_text != text:
        ISS_PATH.write_text(new_text, encoding="utf-8")
        print(f"✓ Installer versiyonu güncellendi: {__version__}")
    else:
        print(f"✓ Installer versiyonu zaten güncel: {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
