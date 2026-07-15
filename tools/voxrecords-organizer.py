#!/usr/bin/env python3
"""
voxrecords-organizer.py — sorts Squelchbreak recordings into
subdirectories by date and frequency.

Directory structure created:
    ~/vox-records/
    └── 2026-06-28/
        ├── 145600000/
        │   ├── voxrecord-20260628143211-abc123.wav
        │   └── voxrecord-20260628143211-abc123.json
        └── unknown/
            ├── voxrecord-20260628150011-def456.wav
            └── voxrecord-20260628150011-def456.json

Files without a JSON sidecar, or whose JSON has no frequency or
start_time, go into an "unknown" subdirectory under the date
(or "unknown-date/unknown" if the date is also missing).

Usage:
    python3 voxrecords-organizer.py [OPTIONS] [DIRECTORY]

    DIRECTORY   Root directory to organise (default: ~/vox-records)

Options:
    -n, --dry-run    Print what would be moved without actually moving anything
    -v, --verbose    Print each file as it is moved
    -h, --help       Show this help message
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


DEFAULT_DIR = os.path.expanduser("~/vox-records")
UNKNOWN_DATE = "unknown-date"
UNKNOWN_FREQ = "unknown"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Organise Squelchbreak recordings into date/frequency subdirectories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage:")[1] if "Usage:" in __doc__ else "")
    parser.add_argument(
        "directory", nargs="?", default=DEFAULT_DIR,
        help=f"Root recordings directory (default: {DEFAULT_DIR})")
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="Show what would be moved without moving anything")
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print each file as it is moved")
    return parser.parse_args()


def read_metadata(json_path):
    """Return (date_str, frequency_str) parsed from a JSON sidecar.
    Either value may be None if the field is missing or unreadable."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, None

    # Date: take the date portion of start_time ("2026-06-28 14:32:11")
    date_str = None
    start_time = meta.get("start_time", "")
    if start_time and len(start_time) >= 10:
        date_str = start_time[:10]   # "YYYY-MM-DD"

    # Frequency: store as raw Hz integer string so directory names are
    # unambiguous and sort correctly (145600000, not "145.6 MHz").
    freq_str = None
    frequency = meta.get("frequency")
    if frequency is not None:
        try:
            freq_str = str(int(float(frequency)))
        except (TypeError, ValueError):
            pass

    return date_str, freq_str


def collect_pairs(root):
    """Return list of (wav_path, json_path_or_None) for every .wav
    found directly in root (not recursing into already-organised
    subdirectories that look like YYYY-MM-DD)."""
    pairs = []
    root = Path(root)
    for wav_path in sorted(root.glob("*.wav")):
        json_path = wav_path.with_suffix(".json")
        pairs.append((wav_path, json_path if json_path.exists() else None))
    return pairs


def move_pair(wav_path, json_path, dest_dir, dry_run, verbose):
    """Move a wav + optional json into dest_dir, creating it if needed."""
    dest_dir = Path(dest_dir)
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    for src in filter(None, [wav_path, json_path]):
        dst = dest_dir / src.name
        if dry_run or verbose:
            print(f"  {'[dry-run] ' if dry_run else ''}mv {src} → {dst}")
        if not dry_run:
            if dst.exists():
                # Avoid silently overwriting; rename the destination
                base = dst.stem
                suffix = dst.suffix
                counter = 1
                while dst.exists():
                    dst = dest_dir / f"{base}_{counter}{suffix}"
                    counter += 1
            shutil.move(str(src), str(dst))


def main():
    args = parse_args()
    root = Path(args.directory).expanduser().resolve()

    if not root.exists():
        print(f"Error: directory does not exist: {root}", file=sys.stderr)
        sys.exit(1)

    pairs = collect_pairs(root)
    if not pairs:
        print(f"No .wav files found directly in {root}")
        sys.exit(0)

    moved = 0
    skipped = 0

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Organising {len(pairs)} recording(s) in {root}\n")

    for wav_path, json_path in pairs:
        date_str, freq_str = read_metadata(json_path) if json_path else (None, None)

        date_dir  = date_str  or UNKNOWN_DATE
        freq_dir  = freq_str  or UNKNOWN_FREQ
        dest_dir  = root / date_dir / freq_dir

        # Skip if it's already in the right place (shouldn't happen
        # since we only glob root/*.wav, but be defensive).
        if wav_path.parent == dest_dir:
            skipped += 1
            continue

        if args.verbose or args.dry_run:
            label = f"{freq_str} Hz" if freq_str else "no frequency"
            print(f"{wav_path.name}  [{date_dir} / {label}]")

        move_pair(wav_path, json_path, dest_dir, args.dry_run, args.verbose)
        moved += 1

    if args.dry_run:
        print(f"\n[dry-run] Would move {moved} recording(s). Run without -n to apply.")
    else:
        print(f"\nDone. Moved {moved} recording(s), skipped {skipped}.")


if __name__ == "__main__":
    main()
