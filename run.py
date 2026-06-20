#!/usr/bin/env python3
"""
Squelchbreak — VOX-triggered audio recorder for amateur radio / scanner use.

Listens to an audio input device and records whenever the signal
"breaks squelch" (exceeds a configurable threshold), saving a .wav file
plus a .json metadata sidecar. Built with GTK4 + libadwaita for a native
GNOME look and feel.

Run multiple independent instances — one per sound card / radio — by
giving each a different --config file:

    run.py --config ~/.config/squelchbreak/radio1.json
    run.py --config ~/.config/squelchbreak/radio2.json

Copyright (C) 2015-2026 Kari Karvonen <oh1kk@toimii.fi>
GNU GPL v3 or later.
"""
import argparse
import sys

from squelchbreak.app import SquelchbreakApp
from squelchbreak.constants import __version__, DEFAULT_CONFIG_PATH


def main():
    parser = argparse.ArgumentParser(
        prog="squelchbreak",
        description="VOX-triggered audio recorder for amateur radio / "
                     "scanner monitoring.")
    parser.add_argument(
        "-c", "--config", metavar="PATH", default=None,
        help="Path to a JSON config file. Run several instances at once "
             "(one per sound card/radio) by giving each its own config. "
             f"Default: {DEFAULT_CONFIG_PATH}")
    parser.add_argument(
        "-V", "--version", action="version",
        version=f"Squelchbreak {__version__}")
    args, gtk_args = parser.parse_known_args()

    app = SquelchbreakApp(config_path=args.config)
    return app.run([sys.argv[0]] + gtk_args)


if __name__ == "__main__":
    sys.exit(main())
