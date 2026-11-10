"""Embed common/vnest_common.py into notebooks, in place.

Usage: python3 -I tools/make_standalone.py notebooks/marimo/2_evaluation/01_*.py [more notebooks]

Each notebook has exactly one shared-module cell containing the lines
    _EMBED_B64 = "..."   # >>> vnest_common (do not edit: tools/make_standalone.py)
This tool replaces that string with the current module, and checks that every wc.<name> the notebook
uses exists in the module (an unknown name would crash on the remote machine).
"""
import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "common" / "vnest_common.py"
MARK = "# >>> vnest_common (do not edit: tools/make_standalone.py)"

src = MODULE.read_text()
version = re.search(r'^VERSION = "([^"]+)"', src, re.M).group(1)
b64 = base64.b64encode(src.encode()).decode()
names = set(re.findall(r"^(?:def|class) (\w+)", src, re.M)) | set(re.findall(r"^([A-Z_][A-Z0-9_]*) =", src, re.M))

for nb in sys.argv[1:]:
    p = Path(nb)
    text = p.read_text()
    pattern = re.compile(r'_EMBED_B64 = "[A-Za-z0-9+/=]*"  ' + re.escape(MARK))
    if len(pattern.findall(text)) != 1:
        sys.exit(f"{p}: expected exactly one embed line ending with {MARK!r}")
    text = pattern.sub(lambda _: f'_EMBED_B64 = "{b64}"  {MARK}', text)
    text = re.sub(r'_EMBED_VERSION = "[^"]*"', f'_EMBED_VERSION = "{version}"', text)
    p.write_text(text)
    used = set(re.findall(r"\bwc\.([A-Za-z_]\w*)", text))
    missing = sorted(used - names)
    if missing:
        sys.exit(f"{p}: uses wc.{missing} which vnest_common {version} does not define")
    print(f"{p}: embedded vnest_common {version} ({len(src)} bytes); {len(used)} wc.* names, all defined")
