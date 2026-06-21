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
DEBUG       = os.environ.get("UBCD260DN_DEBUG", "") == "1"


def _dbg(*args):
    if DEBUG:
        print("[debug]", *args, file=sys.stderr)


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


def _looks_like_frequency(field):
    """True for any field that is just digits, optionally with a decimal
    point (e.g. '01602500', '0160.2500', '160.25') — these are frequency
    representations and must never be mistaken for a channel name."""
    f = (field or "").strip()
    if not f:
        return False
    return bool(re.fullmatch(r"\d+(\.\d+)?", f))


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
        # Confirmed real format on this radio:
        #   GLG,FREQ,MOD,?,?,SCAN_STATE,BANK_NAME,CHANNEL_NAME,?,?,,,?
        # Example: GLG,0138.5000,FM,0,0,SCAN MODE,Bank 1,Folk vh,1,0,,,NONE
        #   [0]=GLG [1]=freq [2]=mode [3]=? [4]=? [5]=scan_state
        #   [6]=bank_name [7]=channel_name [8]=? [9]=? [10]=- [11]=- [12]=?
        resp = _send(ser, "GLG")
        _dbg("GLG raw:", repr(resp))
        if resp and resp.startswith("GLG") and "," in resp:
            fields = resp.split(",")
            _dbg("GLG fields:", fields)

            if len(fields) > 1 and _looks_like_frequency(fields[1]):
                freq_hz = int(round(float(fields[1].strip()) * 1_000_000))
                _dbg("GLG freq (field 1):", repr(fields[1]), "->", freq_hz)

            if len(fields) > 2:
                mm = _normalize_mode(fields[2])
                if mm:
                    mode = mm
                    _dbg("GLG mode (field 2):", repr(fields[2]), "->", mm)

            if len(fields) > 7 and fields[7].strip():
                name = fields[7].strip()
                _dbg("GLG name (field 7):", repr(fields[7]))

        # If GLG didn't give a clean result, try the active channel's
        # CIN record directly via STS's reported channel name, or fall
        # back to whatever the radio is displaying.
        if freq_hz is None or mode is None or name is None:
            resp = _send(ser, "STS")
            _dbg("STS raw:", repr(resp))
            if resp and resp.startswith("STS"):
                fields = resp.split(",")
                _dbg("STS fields:", fields)
                # Look for "CH<num> <freq>" pattern, e.g. "CH108 446.0468"
                for f in fields:
                    m = re.search(
                        r"CH\s*(\d+)\s+([\d]+\.[\d]+)", f.strip()
                    )
                    if m:
                        if freq_hz is None:
                            freq_hz = int(round(float(m.group(2)) * 1_000_000))
                            _dbg("STS matched freq field:", repr(f), "->", freq_hz)
                        break
                # Name = first plausible text field (skip icon/bitmap junk
                # and skip anything that's just a frequency rendering)
                if name is None:
                    for f in fields[2:]:
                        cleaned = f.strip()
                        if cleaned and re.search(r"[A-Za-z]", cleaned) and \
                           not re.search(r"CH\s*\d+", cleaned) and \
                           not _looks_like_frequency(cleaned):
                            name = cleaned
                            _dbg("STS matched name field:", repr(f))
                            break
                if mode is None:
                    for f in fields:
                        mm = _normalize_mode(f)
                        if mm:
                            mode = mm
                            _dbg("STS matched mode field:", repr(f), "->", mm)
                            break
    except Exception as e:
        _dbg("Exception:", repr(e))
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
