#!/usr/bin/env python3
"""Split the integrated blueprint into pages/EvoForge_v4.2_NN.md (byte-identical slices).
Usage: python3 -I tools/split_pages.py   (from the package root)"""
import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "EvoForge_Blueprint_50pages_v4.2.md")
OUT = os.path.join(ROOT, "pages")
os.makedirs(OUT, exist_ok=True)
for f in glob.glob(os.path.join(OUT, "*.md")):
    os.remove(f)
text = open(SRC, encoding="utf-8").read()
for part in re.split(r"(?m)^(?=<!-- PAGE:\d\d/50 -->)", text)[1:]:
    n = int(re.match(r"<!-- PAGE:(\d\d)/50 -->", part).group(1))
    with open(os.path.join(OUT, f"EvoForge_v4.2_{n:02d}.md"), "w", encoding="utf-8") as fh:
        fh.write(part)
print("pages written:", len(glob.glob(os.path.join(OUT, "*.md"))))
