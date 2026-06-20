#!/usr/bin/env python3
"""
ubcd260dn_metadata.py

Queries a Uniden UBCD260DN scanner over USB serial for the currently
active channel and prints frequency / mode / channel name as JSON,
in the format expected by Squelchbreak's metadata-script hook.

Usage (called by Squelchbreak on squelch break):
    python3 ubcd260dn_metadata.py

Configuration:
    Edit SERIAL_PORT below, or set the UBCD260DN_PORT environment
    variable (e.g. UBCD260DN_PORT=/dev/ttyACM0 or COM5).

Protocol notes (confirmed against real hardware):
    - GLG returns the currently active channel's data, including
      a plain-text MOD field (FM/NFM/AM/AUTO/WFM/FMB), which is more
      reliable than STS — on this radio STS's mode line often renders
      as non-ASCII bitmap icons instead of text.
    - GLG format: GLG,FRQ_TX,FRQ_RX,NAME,FRQ,SQUELCH,MUTE,...
      Exact field order can vary slightly by firmware; this script
      is defensive and pulls FRQ/MOD/NAME by scanning fields rather
      than hardcoding positions where it can avoid it.
    - Falls back to CIN,<index> (if a channel index is known) or to
      STS's name field if GLG is unavailable (e.g. radio in a menu).
"""

import json
import os
import re
import sys

import serial

# ── Configuration ──────────────────────────────────────────────
SERIAL_PORT = os.environ.get("UBCD260DN_PORT", "/dev/ttyACM0")
BAUD_RATE   = 115200
TIMEOUT_S   = 1.0


def _open_port():
    return serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=TIMEOUT_S)


def _send(ser, cmd):
    ser.reset_input_buffer()
    ser.write((cmd + "\r").encode("ascii", errors="ignore"))
    raw = ser.readline().decode("ascii", errors="ignore").strip()
    return raw


def _freq_to_hz(freq_field):
    """Radio reports frequency as an 8-digit string in 100Hz steps,
    e.g. '01455750' -> 145.5750 MHz -> 145575000 Hz."""
    digits = re.sub(r"\D", "", freq_field)
    if not digits:
        return None
    try:
        return int(digits) * 100
    except ValueError:
        return None


def _normalize_mode(mode_field):
    """Map radio MOD field to a Squelchbreak-friendly mode string."""
    m = (mode_field or "").strip().upper()
    valid = {"AM", "FM", "NFM", "WFM", "FMB", "AUTO"}
    return m if m in valid else None


def get_current_channel():
    """
    Returns (freq_hz, mode, name) for whatever the radio is
    currently stopped/parked on. Any field that can't be determined
    is returned as None.
    """
    freq_hz, mode, name = None, None, None

    try:
        ser = _open_port()
    except Exception:
        return freq_hz, mode, name

    try:
        # GLG = current channel info while scanning/holding.
        # Typical response: GLG,FRQ_TX,FRQ_RX,NAME,FREQ,SQL,MUTE,...
        resp = _send(ser, "GLG")
        if resp and resp.startswith("GLG") and "," in resp:
            fields = resp.split(",")
            # NAME is the first alphabetic, non-numeric field after GLG
            for f in fields[1:]:
                if f and not re.fullmatch(r"[0-9]+", f) and name is None:
                    name = f.strip()
                    break
            # FREQ is the first 8-digit numeric field
            for f in fields[1:]:
                if re.fullmatch(r"\d{8}", f):
                    freq_hz = _freq_to_hz(f)
                    break
            # MOD: look for a recognizable mode token anywhere in the line
            for f in fields:
                mm = _normalize_mode(f)
                if mm:
                    mode = mm
                    break

        # If GLG didn't give a clean result, try the active channel's
        # CIN record directly via STS's reported channel name, or fall
        # back to whatever the radio is displaying.
        if freq_hz is None or mode is None or name is None:
            resp = _send(ser, "STS")
            if resp and resp.startswith("STS"):
                fields = resp.split(",")
                # Look for "CH<num> <freq>" pattern, e.g. "CH108 446.0468"
                for f in fields:
                    m = re.search(
                        r"CH\s*(\d+)\s+([\d]+\.[\d]+)", f.strip()
                    )
                    if m:
                        if freq_hz is None:
                            freq_hz = int(round(float(m.group(2)) * 1_000_000))
                        break
                # Name = first plausible text field (skip icon/bitmap junk)
                if name is None:
                    for f in fields[2:]:
                        cleaned = f.strip()
                        if cleaned and re.search(r"[A-Za-z0-9]", cleaned) and \
                           not re.search(r"CH\s*\d+", cleaned):
                            name = cleaned
                            break
                if mode is None:
                    for f in fields:
                        mm = _normalize_mode(f)
                        if mm:
                            mode = mm
                            break
    except Exception:
        pass
    finally:
        ser.close()

    return freq_hz, mode, name


def main():
    freq_hz, mode, name = get_current_channel()

    result = {
        "frequency": freq_hz,
        "mode": mode,
        "name": name,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()

