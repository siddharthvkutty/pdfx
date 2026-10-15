"""Write the app icon, padded to a square, to the path given as the first argument.

.ico for the Windows Start Menu shortcut, .png for the Linux launcher. Run with the venv's Python (it has Pillow).
"""
import sys
from pathlib import Path

from PIL import Image

source = Path(__file__).resolve().parent.parent / "src" / "pdfx" / "pdfx-icon-final.png"
out = Path(sys.argv[1])

image = Image.open(source).convert("RGBA")
side = max(image.size)  # the artwork is not square; launchers expect a square icon
square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))

if out.suffix.lower() == ".ico":
    square.save(out, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
else:
    square.resize((512, 512), Image.Resampling.LANCZOS).save(out)
