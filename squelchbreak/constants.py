"""
Squelchbreak — shared constants: version, audio parameters, color palette.
"""
import os

__version__ = "2026.06.21.01"

APP_ID       = "fi.toimii.squelchbreak"
APP_TITLE    = "Squelchbreak"
HOMEPAGE_URL = "https://github.com/OH1KK/squelchbreak"
ISSUES_URL   = f"{HOMEPAGE_URL}/issues"

# ── Audio parameters ──────────────────────────────────────────────────────────
RATE         = 44100
CHUNK_SIZE   = 1024
FORMAT_STR   = "paInt16"
MAXIMUMVOL   = 32767
NUM_VU_BARS  = 40

# Stuck-detection: if no bytes arrive within this many seconds, restart stream
STUCK_TIMEOUT = 4.0

# ── Config file ────────────────────────────────────────────────────────────────
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/squelchbreak/default.json")

# Fields persisted to / loaded from the JSON config file.
# Each entry: (key_name, kind) where kind in {"str","int","float","bool"}
CONFIG_FIELDS = [
    ("vox_threshold",   "int"),
    ("tail_silence",    "float"),
    ("filename_prefix", "str"),
    ("save_path",       "str"),
    ("meta_script",     "str"),
    ("channel_name",    "str"),
    ("normalize_audio", "bool"),
    ("trim_audio",      "bool"),
    ("add_silence_pad", "bool"),
    ("mode",            "str"),    # "vox" | "manual"
    ("device_name",     "str"),    # matched by device name on load, not raw index
]

# ── Colour palette (phosphor-green instrument panel accent on Adwaita) ────────
# These are used only for the custom-drawn VU meter; everything else uses
# libadwaita's native theming so it follows the user's GNOME light/dark mode.
GREEN       = "#00e676"
GREEN_DIM   = "#1b5e3a"
AMBER       = "#ffab00"
RED         = "#ff5252"
MUTED_DARK  = "#3a3a3a"
MUTED_LIGHT = "#c8c8c8"
