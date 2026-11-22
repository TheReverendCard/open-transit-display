"""Make an isolated bench sketch from the working local trial3 sketch."""
import argparse
from pathlib import Path
import re
import shutil
import zipfile

default = Path.home() / "Documents/OTD/OTD_Unified_086_Trial/OTD_Unified_086_Trial/OTDUnified_v086"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, default=default)
parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "Trial3LayoutBench")
args = parser.parse_args()
source, output = args.source.resolve(), args.output.resolve()
text = (source / "OTDUnified_v086.ino").read_text(encoding="utf-8-sig")
setup = re.search(r"(?m)^void setup\(\)\s*\{", text)
if not setup or not all(name in text[:setup.start()] for name in
                        ("void drawAll(time_t", "OTDDisplayStorage.h", "selectRadioTransmit", "otdDisplayPanel")):
    parser.error("Expected a trial3 sketch with the Museum renderer and radio adapter.")
if output.exists() or output == source or source in output.parents:
    parser.error("Choose a fresh output folder outside the production sketch.")
output.mkdir(parents=True)
for path in source.iterdir():
    if path.name in ("src", "licenses"):
        shutil.copytree(path, output / path.name)
    elif path.suffix == ".h":
        shutil.copy2(path, output / path.name)
shutil.copy2(Path(__file__).with_name("Trial3LayoutBench.h"), output)
(output / (output.name + ".ino")).write_text(
    text[:setup.start()] + '\n#include "Trial3LayoutBench.h"\n', encoding="utf-8")
print(output)
