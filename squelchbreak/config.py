"""
Squelchbreak — config file load/save.

Each launched instance of Squelchbreak can point at its own JSON config
file via --config, so several radios can run as independent processes,
each remembering its own sound card, save path, threshold, etc.

This module is intentionally GTK-free: it works on plain Python values,
so the GUI layer just reads/writes a dict.
"""
import json
import os

from .constants import CONFIG_FIELDS, DEFAULT_CONFIG_PATH

DEFAULTS = {
    "vox_threshold":   2000,
    "tail_silence":    5.0,
    "filename_prefix": "voxrecord",
    "save_path":       os.path.expanduser("~/vox-records"),
    "meta_script":     "",
    "channel_name":    "",
    "normalize_audio": True,
    "trim_audio":      True,
    "add_silence_pad": True,
    "mode":            "vox",
    "device_name":     "Default input device",
}


def default_config_path():
    return DEFAULT_CONFIG_PATH


def make_default_state():
    """Return a fresh dict of default config values."""
    return dict(DEFAULTS)


def load_config(path):
    """
    Load a JSON config file into a dict, validated/coerced against
    CONFIG_FIELDS. Missing keys fall back to DEFAULTS. Raises on
    hard I/O or JSON errors so the caller can decide how to react;
    callers that want a "quiet" first-run experience should check
    os.path.exists() first.
    """
    path = os.path.abspath(os.path.expanduser(path))
    with open(path, "r") as f:
        raw = json.load(f)

    state = make_default_state()
    warnings = []
    for key, kind in CONFIG_FIELDS:
        if key not in raw:
            continue
        val = raw[key]
        try:
            if kind == "int":
                val = int(val)
            elif kind == "float":
                val = float(val)
            elif kind == "bool":
                val = bool(val)
            else:
                val = str(val)
            state[key] = val
        except (TypeError, ValueError) as e:
            warnings.append(f"Config field '{key}' invalid ({e}), using default.")
    return state, warnings


def save_config(path, state):
    """Write the given state dict to path as indented JSON."""
    path = os.path.abspath(os.path.expanduser(path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = {key: state.get(key, DEFAULTS[key]) for key, _ in CONFIG_FIELDS}
    with open(path, "w") as f:
        json.dump(out, f, indent=4)
    return path
