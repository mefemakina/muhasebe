from __future__ import annotations

import sys
from pathlib import Path
from tkinter import PhotoImage


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base.joinpath(*parts)


def find_transparent_logo_file() -> Path | None:
    candidates = [
        resource_path("desktop", "assets", "mefe_muhasebe_logo.png"),
        Path(__file__).resolve().parents[1] / "assets" / "mefe_muhasebe_logo.png",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def load_mefe_logo(max_size: tuple[int, int] = (92, 64)) -> PhotoImage | None:
    transparent_logo = find_transparent_logo_file()
    if transparent_logo:
        try:
            return PhotoImage(file=str(transparent_logo))
        except Exception:
            pass
    return None
