"""Encode reviewed browser captures of the real cards; never read live HA data.

Input folder: en/he-02.jpg (expanded), 03 (checked), 04 (older), 05 (source
update), 01 (collapsed), plus crop.json containing the demo main element bounds.
Capture only scripts/dashboard-demo, whose data is entirely fictional.
"""

import argparse
import json
from pathlib import Path

from PIL import Image

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
    suffix = "-he" if lang == "he" else ""
    frames[1].save(out / f"mashov-children-live{suffix}.jpg", quality=94)
    frames[0].save(
        out / f"mashov-children-live{suffix}.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[3000, 3500, 4000, 4000, 2500],
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(lang, frames[0].size, "5 reviewed UI states / 17 seconds")
