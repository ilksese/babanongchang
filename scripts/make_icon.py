"""Draw the shared cartoon-tree icon used by the desktop app and the APK."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


CREAM = (244, 239, 228, 255)
CANOPY = (23, 107, 77, 255)
CANOPY_DARK = (15, 77, 56, 255)
LEAF = (168, 214, 176, 255)
TRUNK = (122, 78, 42, 255)
TRUNK_DARK = (92, 56, 30, 255)
RICE = (215, 167, 47, 255)


def _ellipse(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill) -> None:
    draw.ellipse(box, fill=fill)


def draw_tree(size: int = 1024) -> Image.Image:
    image = Image.new("RGBA", (size, size), CREAM)
    draw = ImageDraw.Draw(image)
    scale = size / 1024

    def box(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        return tuple(int(value * scale) for value in (x0, y0, x1, y1))

    _ellipse(draw, box(150, 150, 560, 520), CANOPY_DARK)
    _ellipse(draw, box(430, 130, 880, 500), CANOPY_DARK)
    _ellipse(draw, box(446, 430, 578, 820), TRUNK_DARK)
    _ellipse(draw, box(466, 418, 558, 800), TRUNK)
    _ellipse(draw, box(230, 90, 720, 470), CANOPY)
    _ellipse(draw, box(170, 230, 520, 540), CANOPY)
    _ellipse(draw, box(490, 210, 830, 500), CANOPY)
    _ellipse(draw, box(310, 130, 440, 200), LEAF)
    _ellipse(draw, box(640, 180, 700, 226), RICE)
    _ellipse(draw, box(656, 168, 682, 200), (255, 236, 176, 255))
    return image


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = draw_tree()
    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    source.save(assets / "icon-1024.png")
    source.resize((256, 256), Image.Resampling.LANCZOS).save(root / "src" / "babanongchang" / "icon.png")

    res = root / "android" / "app" / "src" / "main" / "res"
    for name, px in (("mipmap-mdpi", 48), ("mipmap-hdpi", 72), ("mipmap-xhdpi", 96),
                     ("mipmap-xxhdpi", 144), ("mipmap-xxxhdpi", 192)):
        folder = res / name
        folder.mkdir(parents=True, exist_ok=True)
        icon = source.resize((px, px), Image.Resampling.LANCZOS)
        icon.save(folder / "ic_launcher.png")
        icon.save(folder / "ic_launcher_round.png")
    print("wrote desktop and launcher icons")


if __name__ == "__main__":
    main()
