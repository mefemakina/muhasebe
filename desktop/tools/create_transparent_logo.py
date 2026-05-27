from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "desktop" / "assets" / "mefe_muhasebe_logo.png"
OUTPUT_ICON = ROOT / "desktop" / "assets" / "mefe_muhasebe_logo.ico"


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    bg = (25, 35, 55, 255)
    draw.rounded_rectangle((0, 0, 256, 256), radius=28, fill=bg)

    center = (128, 92)
    ring_color = (224, 231, 241, 255)
    for angle in range(0, 360, 24):
        import math

        start = math.radians(angle)
        end = math.radians(angle + 13)
        x1 = center[0] + 54 * math.cos(start)
        y1 = center[1] + 54 * math.sin(start)
        x2 = center[0] + 54 * math.cos(end)
        y2 = center[1] + 54 * math.sin(end)
        draw.line((x1, y1, x2, y2), fill=ring_color, width=7)
    draw.ellipse((84, 48, 172, 136), outline=(67, 84, 114, 255), width=2)

    bar_width = 14
    bars = [
        ((100, 90, 100 + bar_width, 124), (34, 197, 246, 255)),
        ((122, 72, 122 + bar_width, 124), (247, 154, 36, 255)),
        ((144, 58, 144 + bar_width, 124), (48, 132, 255, 255)),
    ]
    for box, color in bars:
        draw.rounded_rectangle(box, radius=4, fill=color)

    title_font = load_font(30, bold=True)
    subtitle_font = load_font(12, bold=False)
    title = "MEFE"
    subtitle = "M U H A S E B E"
    title_box = draw.textbbox((0, 0), title, font=title_font)
    subtitle_box = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    draw.text(((256 - (title_box[2] - title_box[0])) / 2, 155), title, fill=(255, 255, 255, 255), font=title_font)
    draw.text(((256 - (subtitle_box[2] - subtitle_box[0])) / 2, 196), subtitle, fill=(153, 167, 190, 255), font=subtitle_font)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUTPUT)
    canvas.save(OUTPUT_ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Transparent logo written: {OUTPUT}")
    print(f"Windows icon written: {OUTPUT_ICON}")


if __name__ == "__main__":
    main()
