"""Colour tokens, taken from the app icon: slate desk, paper sheets, ink, and the icon's red."""
from pathlib import Path

DESK = "#2B3540"  # window ground, where the page thumbnails sit
DESK_DEEP = "#222A33"  # header bar
PAPER = "#F5F4F1"  # tiles, options panel
PAPER_SHADE = "#E4E2DC"  # fields, secondary buttons, folded corner
PAPER_EDGE = "#D2CFC8"
INK = "#1F2124"
MUTED = "#6A6E75"  # secondary text on paper
MUTED_ON_DESK = "#9FABB8"  # secondary text on the desk
RED = "#D8262D"  # actions only
RED_DARK = "#B81E24"

ICON = Path(__file__).resolve().parent.parent / "pdfx-icon-final.png"
