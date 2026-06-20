# Installing Squelchbreak

Squelchbreak needs three things on Ubuntu: PyGObject + GTK4 + libadwaita
(for the GUI), PyAudio (for the audio I/O), and Python 3 itself (already
on Ubuntu by default).

## 1. System packages (GTK4 / libadwaita / PyGObject)

```bash
sudo apt update
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

- `python3-gi` — PyGObject, the Python bindings for GObject-based libraries
- `gir1.2-gtk-4.0` — GTK4 introspection data
- `gir1.2-adw-1` — libadwaita introspection data (GNOME's modern widget
  library: headerbars, toast notifications, preference rows, etc.)

These are the same packages installed system-wide for native GNOME apps
like Settings, Files, and Text Editor, so if you're running a recent
GNOME desktop they may already be present.

### Checking what's installed

```bash
python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Gtk, Adw; print('GTK', Gtk._version, '/ Adwaita', Adw._version, 'OK')"
```

If that prints a version instead of an error, you're set for the GUI half.

## 2. PyAudio (audio capture)

```bash
sudo apt install python3-pyaudio
```

or, if you prefer pip / a virtual environment:

```bash
sudo apt install portaudio19-dev   # PyAudio's C dependency
pip install --user pyaudio
```

### Checking PyAudio

```bash
python3 -c "import pyaudio; print('PyAudio OK')"
```

## 3. Running Squelchbreak

From the `squelchbreak/` project directory:

```bash
python3 run.py
```

To run a specific radio's config (see README.md for the multi-radio
setup), pass `--config`:

```bash
python3 run.py --config ~/.config/squelchbreak/radio1.json
```

## Optional: install as a regular command

If you'd like to run `squelchbreak` from anywhere without `cd`-ing into
the project folder:

```bash
chmod +x run.py
mkdir -p ~/.local/bin
ln -s "$(pwd)/run.py" ~/.local/bin/squelchbreak
```

Make sure `~/.local/bin` is on your `PATH` (Ubuntu adds this
automatically for most desktop sessions). Then:

```bash
squelchbreak --config ~/.config/squelchbreak/radio1.json
```

## Troubleshooting

**`ValueError: Namespace Gtk not available`**
The `gir1.2-gtk-4.0` package (or `gir1.2-adw-1`) isn't installed — see
step 1 above.

**`ModuleNotFoundError: No module named 'gi'`**
`python3-gi` isn't installed, or you're running inside a virtual
environment that can't see system site-packages. PyGObject is a thin
wrapper over system libraries and generally doesn't work well installed
via pip into an isolated venv on Linux — installing `python3-gi` via
`apt` for your system Python is the recommended path.

**`OSError: [Errno -9996] Invalid input device`**
The previously-selected sound card has been unplugged or renumbered.
Open Settings → Audio Input Device and pick a card from the refreshed
list, or click "Re-scan for sound cards".

**No sound at all / device list is empty**
Check `pactl list short sources` (PulseAudio/PipeWire) or `arecord -l`
(ALSA) to confirm Linux itself sees the card before troubleshooting
Squelchbreak.
