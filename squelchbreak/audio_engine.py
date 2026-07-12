"""
Squelchbreak — audio engine.

Carries over the proven VOX / manual recording logic from the Tkinter
version with minimal changes. Runs entirely in a background thread and
talks to the GTK UI thread only through a callback object (AudioEngineUI
protocol below) whose methods are expected to internally marshal back
onto the main loop (e.g. via GLib.idle_add) — this module does not import
GTK at all, so it stays testable / portable.
"""
import json
import os
import subprocess
import threading
import time
import uuid
from array import array
from struct import pack
from sys import byteorder

try:
    import pyaudio
    import wave
    PYAUDIO_OK = True
except ImportError:
    PYAUDIO_OK = False

from .constants import RATE, CHUNK_SIZE, FORMAT_STR, MAXIMUMVOL, STUCK_TIMEOUT


class AudioEngineUI:
    """
    Callback interface the engine uses to report back to the UI.
    The GTK app implements these; every method must be safe to call
    from a background thread (i.e. it should hand off to GLib.idle_add
    internally, not touch widgets directly).
    """
    def on_vu_level(self, level_0_to_1):
        pass

    def on_recording_started(self, filename_base):
        pass

    def on_recording_stopped(self):
        pass

    def on_waiting_started(self):
        """Called when VOX is armed and listening for the next trigger."""
        pass

    def on_session_saved(self, wav_path, json_path, duration_s):
        pass

    def on_log(self, message, level="normal"):
        """level in {'normal','dim','green','amber','red'}"""
        pass

    def on_status(self, message):
        pass

    def on_stream_stuck_restart(self):
        pass

    def on_fatal_error(self, message):
        pass


def list_input_devices():
    """Return [(display_name, index), ...] with index -1 meaning 'default'."""
    devices = [("Default input device", -1)]
    if not PYAUDIO_OK:
        return devices
    try:
        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                devices.append((f"[{i}] {info['name']}", i))
        p.terminate()
    except Exception:
        pass
    return devices


def resolve_device_index(device_name, devices):
    """
    Match a saved device_name string against the current device list,
    tolerating index shifts (USB card re-enumerated at a different
    index after replug) by matching on the trailing name text too.
    Returns (resolved_name, index_or_None, matched_exactly: bool).
    """
    names = [n for n, _ in devices]
    name_to_idx = dict(devices)

    if device_name in names:
        idx = name_to_idx[device_name]
        return device_name, (None if idx == -1 else idx), True

    bare = device_name.split("] ", 1)[-1] if "] " in device_name else device_name
    for n in names:
        if bare and n.endswith(bare):
            idx = name_to_idx[n]
            return n, (None if idx == -1 else idx), False

    # Nothing matched — fall back to default
    return "Default input device", None, False


class AudioEngine:
    """
    Runs the VOX or manual-record loop. Each instance is meant to be
    driven from one background thread at a time (start() spawns it).
    """

    def __init__(self, ui: AudioEngineUI, get_settings):
        """
        ui: AudioEngineUI implementation
        get_settings: callable returning a dict snapshot of current settings:
            {
              'vox_threshold': int, 'tail_silence': float,
              'filename_prefix': str, 'save_path': str,
              'meta_script': str, 'channel_name': str,
              'normalize_audio': bool, 'trim_audio': bool,
              'add_silence_pad': bool, 'device_index': int|None,
            }
          Called frequently (every loop iteration) so changes made in the
          UI while running (e.g. dragging the threshold slider) take effect
          live without needing a restart.
        """
        self.ui = ui
        self.get_settings = get_settings
        self.stop_flag = False
        self.manual_active = False   # toggled by the UI for manual-record mode

    def request_stop(self):
        self.stop_flag = True

    # ── Stream helpers ─────────────────────────────────────────────────────────

    def _open_stream(self, device_index):
        fmt = getattr(pyaudio, FORMAT_STR)
        p = pyaudio.PyAudio()
        kwargs = dict(format=fmt, channels=1, rate=RATE,
                       input=True, frames_per_buffer=CHUNK_SIZE)
        if device_index is not None:
            kwargs["input_device_index"] = device_index
        stream = p.open(**kwargs)
        return p, stream, fmt

    def _read_chunk_or_stuck(self, stream):
        """Read one chunk; raise RuntimeError if no data arrives in time."""
        deadline = time.time() + STUCK_TIMEOUT
        while time.time() < deadline:
            if self.stop_flag:
                return None
            avail = stream.get_read_available()
            if avail >= CHUNK_SIZE:
                raw = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                chunk = array('h', raw)
                if byteorder == 'big':
                    chunk.byteswap()
                return chunk
            time.sleep(0.02)
        raise RuntimeError("Audio stream stuck — no data received")

    def _push_vu(self, chunk):
        self.ui.on_vu_level(min(max(chunk) / MAXIMUMVOL, 1.0))

    # ── Public entry points (run in worker thread) ─────────────────────────────

    def run_vox(self):
        """VOX-trigger loop: wait for signal above threshold, record, repeat."""
        self.stop_flag = False
        while not self.stop_flag:
            settings = self.get_settings()
            try:
                p, stream, fmt = self._open_stream(settings.get("device_index"))
            except Exception as e:
                self.ui.on_fatal_error(f"Audio open failed: {e}")
                return
            self.ui.on_log("Listening…", "dim")
            self.ui.on_waiting_started()
            try:
                while not self.stop_flag:
                    triggered = False
                    chunk = None
                    while not self.stop_flag:
                        chunk = self._read_chunk_or_stuck(stream)
                        if chunk is None:
                            break
                        self._push_vu(chunk)
                        if max(chunk) > self.get_settings()["vox_threshold"]:
                            triggered = True
                            break
                    if not triggered:
                        break
                    self._record_one_session(p, stream, chunk)
                    if not self.stop_flag:
                        self.ui.on_waiting_started()
                break  # clean exit from outer while
            except RuntimeError as e:
                self.ui.on_log(f"⚠ {e} — restarting…", "amber")
                self.ui.on_stream_stuck_restart()
                self._safe_close(p, stream)
                time.sleep(1.0)
                continue
            finally:
                self._safe_close(p, stream)

    def run_manual(self):
        """Manual mode: stream stays open, recording starts/stops on demand."""
        self.stop_flag = False
        while not self.stop_flag:
            settings = self.get_settings()
            try:
                p, stream, fmt = self._open_stream(settings.get("device_index"))
            except Exception as e:
                self.ui.on_fatal_error(f"Audio open failed: {e}")
                return

            snd_data, rec_start, wav_filename, wf = array('h'), 0, "", None
            try:
                while not self.stop_flag:
                    chunk = self._read_chunk_or_stuck(stream)
                    if chunk is None:
                        break
                    self._push_vu(chunk)

                    if not self.manual_active and wf is not None:
                        wf.close()
                        wf = None
                        # Async fetch: the stream is still open and PortAudio
                        # keeps buffering while this runs, so don't block here.
                        meta_box = self._start_metadata_fetch(settings)
                        self._finalise_async(p, snd_data, wav_filename,
                                             rec_start, meta_box)
                        snd_data = array('h')
                        self.ui.on_recording_stopped()

                    if self.manual_active:
                        if wf is None:
                            settings = self.get_settings()
                            rec_start = time.time()
                            wav_filename = self._make_filename(settings)
                            wf = wave.open(f"{wav_filename}.wav", 'wb')
                            wf.setnchannels(1)
                            wf.setsampwidth(p.get_sample_size(fmt))
                            wf.setframerate(RATE)
                            self.ui.on_recording_started(wav_filename)
                            self.ui.on_log(
                                f"Manual rec: {os.path.basename(wav_filename)}.wav",
                                "amber")
                        snd_data.extend(chunk)
                        wf.writeframes(chunk.tobytes())
                break
            except RuntimeError as e:
                self.ui.on_log(f"⚠ {e} — restarting…", "amber")
                self.ui.on_stream_stuck_restart()
                if wf:
                    try:
                        wf.close()
                    except Exception:
                        pass
                self._safe_close(p, stream)
                time.sleep(1.0)
                continue
            finally:
                if wf:
                    try:
                        wf.close()
                    except Exception:
                        pass
                self._safe_close(p, stream)

    # ── Internals ──────────────────────────────────────────────────────────────

    def _record_one_session(self, p, stream, first_chunk):
        settings = self.get_settings()
        snd_data = array('h', first_chunk)
        rec_start = last_voice = time.time()
        wav_filename = self._make_filename(settings)

        # Kick off the metadata script in the background *before* doing
        # anything else, so a slow serial/rigctl round-trip never delays
        # audio capture — the stream keeps being read on this thread
        # while the script runs concurrently on its own.
        meta_box = self._start_metadata_fetch(settings)

        self.ui.on_recording_started(wav_filename)
        self.ui.on_log(f"Recording: {os.path.basename(wav_filename)}.wav", "amber")

        while not self.stop_flag:
            chunk = self._read_chunk_or_stuck(stream)
            if chunk is None:
                break
            snd_data.extend(chunk)
            self._push_vu(chunk)
            live_settings = self.get_settings()
            if max(chunk) > live_settings["vox_threshold"]:
                last_voice = time.time()
            if time.time() > last_voice + live_settings["tail_silence"]:
                break

        # By now the .wav audio is fully captured; waiting here for the
        # metadata script (if it's somehow still running) no longer
        # risks losing anything.
        meta = self._collect_metadata_fetch(meta_box)
        self._finalise(p, snd_data, wav_filename, rec_start, meta)
        self.ui.on_recording_stopped()

    def _finalise(self, p, snd_data, wav_filename, rec_start, meta=None):
        if not snd_data:
            return
        settings = self.get_settings()
        if settings.get("normalize_audio", True):
            snd_data = self._normalize(snd_data)
        if settings.get("trim_audio", True):
            snd_data = self._trim(snd_data, settings["vox_threshold"])
        if settings.get("add_silence_pad", True):
            snd_data = self._add_silence(snd_data, 0.5)

        wav_path = f"{wav_filename}.wav"
        fmt = getattr(pyaudio, FORMAT_STR)
        sample_width = pyaudio.PyAudio().get_sample_size(fmt)
        with wave.open(wav_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(sample_width)
            wf.setframerate(RATE)
            wf.writeframes(pack('<' + ('h' * len(snd_data)), *snd_data))

        # Explicitly release the audio buffer now that it's written to
        # disk — a long recording can be tens of MB and Python's GC
        # won't necessarily collect it promptly otherwise, which matters
        # when sessions run back-to-back over days.
        del snd_data

        duration = time.time() - rec_start
        meta = dict(meta or {})
        ch = settings.get("channel_name", "").strip()
        if ch:
            meta["channel_name"] = ch
        meta.update({
            "start_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(rec_start)),
            "end_time":   time.strftime('%Y-%m-%d %H:%M:%S'),
            "duration_s": round(duration, 1),
        })
        json_path = f"{wav_filename}.json"
        with open(json_path, 'w') as jf:
            json.dump(meta, jf, indent=4)

        self.ui.on_log(f"Saved: {os.path.basename(wav_path)} ({duration:.1f}s)", "green")
        self.ui.on_log(f"Meta:  {os.path.basename(json_path)}", "dim")
        self.ui.on_session_saved(wav_path, json_path, duration)

    def _finalise_async(self, p, snd_data, wav_filename, rec_start, meta_box):
        """
        Used by manual mode, where the audio stream stays open and
        actively buffering during finalise. Writes the .wav immediately
        (cheap, no external dependency), then waits for the metadata
        script and writes the .json sidecar on a separate thread, so the
        caller can go straight back to reading the stream instead of
        blocking on a possibly-slow script.
        """
        def _worker():
            meta = self._collect_metadata_fetch(meta_box)
            self._finalise(p, snd_data, wav_filename, rec_start, meta)

        threading.Thread(target=_worker, daemon=True).start()

    def _make_filename(self, settings):
        prefix = settings.get("filename_prefix") or "voxrecord"
        ts = time.strftime("%Y%m%d%H%M%S")
        uid = uuid.uuid4().hex[:6]
        return os.path.join(settings["save_path"], f"{prefix}-{ts}-{uid}")

    def _get_metadata(self, settings):
        script = (settings.get("meta_script") or "").strip()
        if not script:
            return {}
        try:
            result = subprocess.run([script], capture_output=True, text=True, timeout=5)
            raw = result.stdout.strip()
            if raw:
                data = json.loads(raw)
                self.ui.on_log(f"Metadata: {json.dumps(data)}", "dim")
                if "frequency" in data:
                    try:
                        freq_mhz = float(data["frequency"]) / 1_000_000
                        mode = data.get("mode", "")
                        suffix = f" {mode}" if mode else ""
                        self.ui.on_log(f"📻 {freq_mhz:.4f} MHz{suffix}", "green")
                    except (TypeError, ValueError):
                        self.ui.on_log(
                            f"📻 frequency: {data['frequency']!r} (not numeric)",
                            "amber")
                return data
            else:
                self.ui.on_log("Metadata script returned no output.", "amber")
        except Exception as e:
            self.ui.on_log(f"Metadata script error: {e}", "red")
        return {}

    def _start_metadata_fetch(self, settings):
        """
        Run the metadata script in a background thread so a slow script
        (e.g. a serial round-trip to a radio) never blocks audio capture —
        PortAudio's input buffer keeps draining on the main recording
        thread while this runs concurrently.

        Returns a dict with a single key 'result', which the metadata
        thread fills in once it finishes; safe to read from the main
        thread without a lock since it's only ever assigned once, after
        which _finalise() reads it (a join() happens first, see below).
        """
        box = {"result": None, "thread": None}

        def _worker():
            box["result"] = self._get_metadata(settings)

        t = threading.Thread(target=_worker, daemon=True)
        box["thread"] = t
        t.start()
        return box

    @staticmethod
    def _collect_metadata_fetch(box, timeout=8.0):
        """
        Wait for a background metadata fetch (started via
        _start_metadata_fetch) to complete, with a safety timeout so a
        runaway script can't hang the recorder forever. Called right
        before writing the .json sidecar — by then the .wav has already
        been fully captured and saved, so this wait no longer risks
        losing any audio.
        """
        box["thread"].join(timeout=timeout)
        return box["result"] if box["result"] is not None else {}

    @staticmethod
    def _normalize(snd_data):
        mx = max(abs(i) for i in snd_data)
        if mx == 0:
            return snd_data
        t = float(MAXIMUMVOL) / mx
        return array('h', [int(min(MAXIMUMVOL, max(-MAXIMUMVOL, i * t)))
                            for i in snd_data])

    @staticmethod
    def _trim(snd_data, threshold):
        def _trim_one(d):
            started = False
            r = array('h')
            for i in d:
                if not started and abs(i) > threshold:
                    started = True
                if started:
                    r.append(i)
            return r
        snd_data = _trim_one(snd_data)
        snd_data.reverse()
        snd_data = _trim_one(snd_data)
        snd_data.reverse()
        return snd_data

    @staticmethod
    def _add_silence(snd_data, secs):
        silence = array('h', [0] * int(secs * RATE))
        return silence + snd_data + silence

    @staticmethod
    def _safe_close(p, stream):
        try:
            stream.stop_stream()
            stream.close()
            p.terminate()
        except Exception:
            pass
