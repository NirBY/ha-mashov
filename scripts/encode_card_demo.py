"""Encode reviewed browser captures of the real cards; never read live HA data.

Input folder: en/he-02.jpg (expanded), 03 (checked), 04 (older), 05 (source
update), 01 (collapsed), plus crop.json containing the demo main element bounds.
Capture only scripts/dashboard-demo, whose data is entirely fictional.
"""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageOps

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("captures", type=Path)
args = parser.parse_args()
rect = json.loads((args.captures / "crop.json").read_text())
out = Path(__file__).resolve().parents[1] / "docs/images"
for lang in ("en", "he"):
    frames = []
    for number in (2, 3, 4, 5, 1):
        with Image.open(args.captures / f"{lang}-{number:02}.jpg") as image:
            box = (int(rect["x"]), 0, int(rect["x"] + rect["width"]), image.height)
            frames.append(image.crop(box).convert("RGB"))
    # Full-page captures can grow when the older homework section is expanded.
    # Keep every state complete and aligned on one canvas instead of clipping it.
    size = (frames[0].width, max(frame.height for frame in frames))
    aligned = []
    for frame in frames:
        canvas = Image.new("RGB", size, "#090f1c")
        canvas.paste(frame, (0, 0))
        aligned.append(canvas)
    frames = aligned
    suffix = "-he" if lang == "he" else ""
    frames[1].save(out / f"mashov-children-live{suffix}.jpg", quality=94)
    # A GIF's first frame is also its static preview in clients that do not animate.
    # Keep the product overview intact, letterboxed rather than cropped or stretched.
    with Image.open(out / f"mashov-neon-overview{suffix}.png") as image:
        poster = ImageOps.pad(image.convert("RGB"), frames[0].size, color="#090f1c", method=Image.Resampling.LANCZOS)
    poster.save(
        out / f"mashov-children-live{suffix}.gif",
        save_all=True,
        append_images=frames,
        duration=[6000, 3000, 3500, 4000, 4000, 2500],
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(lang, frames[0].size, "product cover + 5 reviewed UI states / 23 seconds")
