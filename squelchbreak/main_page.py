"""
Squelchbreak — main page: VU meter, mode toggle, record controls, log.
"""
import time

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango

from .vu_meter import VuMeter
from .constants import GREEN, AMBER, RED


class MainPage(Gtk.Box):
    """
    Emits no custom signals; the parent window wires button clicks to
    its own handlers via the `on_*` callback attributes set after
    construction (see app.py). This keeps the widget simple and avoids
    custom GObject signal boilerplate for a single-window app.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)

        # Callbacks — wired up by app.py
        self.on_start_clicked = lambda: None
        self.on_stop_clicked = lambda: None
        self.on_manual_rec_clicked = lambda: None
        self.on_mode_changed = lambda mode: None
        self.on_threshold_changed = lambda value: None
        self.on_tail_silence_changed = lambda value: None
        self.on_channel_name_changed = lambda text: None

        self._build_vu_section()
        self._build_controls_section()
        self._build_log_section()

    # ── VU meter + threshold slider ──────────────────────────────────────────────

    def _build_vu_section(self):
        group = Gtk.Frame()
        group.set_label("Input Level")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.set_margin_top(8)
        inner.set_margin_bottom(8)
        inner.set_margin_start(8)
        inner.set_margin_end(8)

        self.vu_meter = VuMeter()
        inner.append(self.vu_meter)

        thr_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        thr_label = Gtk.Label(label="Threshold:")
        thr_label.add_css_class("dim-label")
        thr_row.append(thr_label)

        self.threshold_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 200, 10000, 50)
        self.threshold_scale.set_hexpand(True)
        self.threshold_scale.set_draw_value(False)
        self.threshold_scale.set_value(2000)
        self.threshold_scale.connect("value-changed", self._on_threshold_scale)
        thr_row.append(self.threshold_scale)

        self.threshold_value_label = Gtk.Label(label="2000")
        self.threshold_value_label.set_width_chars(6)
        thr_row.append(self.threshold_value_label)

        inner.append(thr_row)
        group.set_child(inner)
        self.append(group)

    def _on_threshold_scale(self, scale):
        value = int(scale.get_value())
        self.threshold_value_label.set_label(str(value))
        self.vu_meter.set_threshold(value)
        self.on_threshold_changed(value)

    def set_threshold(self, value):
        """Programmatic update (e.g. on config load) without re-firing callback loops."""
        self.threshold_scale.set_value(value)
        self.threshold_value_label.set_label(str(value))
        self.vu_meter.set_threshold(value)

    def set_vu_level(self, level):
        self.vu_meter.set_level(level)

    def set_recording_color_mode(self, is_recording):
        self.vu_meter.set_recording(is_recording)

    # ── Controls: mode toggle, action buttons, tail silence, channel name ─────────

    def _build_controls_section(self):
        group = Gtk.Frame()
        group.set_label("Controls")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner.set_margin_top(10)
        inner.set_margin_bottom(10)
        inner.set_margin_start(10)
        inner.set_margin_end(10)

        # Row 1: mode toggle + action buttons
        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        # Mode toggle, implemented as two linked ToggleButtons
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        mode_box.add_css_class("linked")
        self.vox_toggle = Gtk.ToggleButton(label="VOX Auto")
        self.manual_toggle = Gtk.ToggleButton(label="Manual")
        self.vox_toggle.set_active(True)
        self.vox_toggle.connect("toggled", self._on_vox_toggle)
        self.manual_toggle.connect("toggled", self._on_manual_toggle)
        mode_box.append(self.vox_toggle)
        mode_box.append(self.manual_toggle)
        row1.append(mode_box)

        self.start_button = Gtk.Button(label="▶  Start VOX")
        self.start_button.add_css_class("suggested-action")
        self.start_button.connect("clicked", lambda b: self.on_start_clicked())
        row1.append(self.start_button)

        self.stop_button = Gtk.Button(label="■  Stop")
        self.stop_button.add_css_class("destructive-action")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", lambda b: self.on_stop_clicked())
        row1.append(self.stop_button)

        self.rec_now_button = Gtk.Button(label="⏺  Rec Now")
        self.rec_now_button.set_sensitive(False)
        self.rec_now_button.connect("clicked", lambda b: self.on_manual_rec_clicked())
        row1.append(self.rec_now_button)

        inner.append(row1)

        # Row 2: tail silence + channel name
        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)

        tail_label = Gtk.Label(label="VOX tail silence (s):")
        tail_label.add_css_class("dim-label")
        row2.append(tail_label)
        self.tail_spin = Gtk.SpinButton.new_with_range(1, 60, 0.5)
        self.tail_spin.set_value(5.0)
        self.tail_spin.connect("value-changed",
                               lambda s: self.on_tail_silence_changed(s.get_value()))
        row2.append(self.tail_spin)

        ch_label = Gtk.Label(label="Channel name:")
        ch_label.add_css_class("dim-label")
        row2.append(ch_label)
        self.channel_entry = Gtk.Entry()
        self.channel_entry.set_hexpand(True)
        self.channel_entry.set_placeholder_text("e.g. Tampere-pyörre 145.600 MHz")
        self.channel_entry.connect("changed",
                                   lambda e: self.on_channel_name_changed(e.get_text()))
        row2.append(self.channel_entry)

        inner.append(row2)

        group.set_child(inner)
        self.append(group)

    def _on_vox_toggle(self, btn):
        if btn.get_active():
            self.manual_toggle.set_active(False)
            self.rec_now_button.set_sensitive(False)
            self.start_button.set_label("▶  Start VOX")
            self.on_mode_changed("vox")
        elif not self.manual_toggle.get_active():
            # Prevent both being off — re-assert this one
            btn.set_active(True)

    def _on_manual_toggle(self, btn):
        if btn.get_active():
            self.vox_toggle.set_active(False)
            self.start_button.set_label("▶  Monitor")
            self.on_mode_changed("manual")
        elif not self.vox_toggle.get_active():
            btn.set_active(True)

    def set_mode(self, mode):
        """Programmatic mode set (e.g. from loaded config)."""
        if mode == "manual":
            self.manual_toggle.set_active(True)
        else:
            self.vox_toggle.set_active(True)

    def set_tail_silence(self, value):
        self.tail_spin.set_value(value)

    def set_channel_name(self, text):
        self.channel_entry.set_text(text or "")

    def set_running_state(self, running, mode):
        """Enable/disable buttons appropriately for current run state."""
        self.start_button.set_sensitive(not running)
        self.stop_button.set_sensitive(running)
        self.rec_now_button.set_sensitive(running and mode == "manual")
        self.vox_toggle.set_sensitive(not running)
        self.manual_toggle.set_sensitive(not running)

    def set_rec_now_label(self, recording):
        self.rec_now_button.set_label("■  Stop Rec" if recording else "⏺  Rec Now")

    # ── Activity log ───────────────────────────────────────────────────────────

    def _build_log_section(self):
        group = Gtk.Frame()
        group.set_label("Activity Log")
        group.set_vexpand(True)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_monospace(True)
        self.log_view.set_top_margin(6)
        self.log_view.set_bottom_margin(6)
        self.log_view.set_left_margin(8)
        self.log_view.set_right_margin(8)
        self._log_buffer = self.log_view.get_buffer()

        self._tag_dim   = self._log_buffer.create_tag("dim",   foreground="#888888")
        self._tag_green = self._log_buffer.create_tag("green", foreground=GREEN)
        self._tag_amber = self._log_buffer.create_tag("amber", foreground=AMBER)
        self._tag_red   = self._log_buffer.create_tag("red",   foreground=RED)

        scroller.set_child(self.log_view)
        group.set_child(scroller)
        self.append(group)

    def log(self, message, level="normal"):
        ts = time.strftime("%H:%M:%S")
        tag = {"dim": self._tag_dim, "green": self._tag_green,
               "amber": self._tag_amber, "red": self._tag_red}.get(level)
        end_iter = self._log_buffer.get_end_iter()
        text = f"[{ts}] {message}\n"
        if tag:
            self._log_buffer.insert_with_tags(end_iter, text, tag)
        else:
            self._log_buffer.insert(end_iter, text)

        # Trim the oldest lines when the buffer exceeds the cap so the
        # log doesn't grow without bound over a multi-day session.
        MAX_LOG_LINES = 500
        line_count = self._log_buffer.get_line_count()
        if line_count > MAX_LOG_LINES:
            try:
                start = self._log_buffer.get_start_iter()
                # In modern PyGObject (GTK4 bindings), get_iter_at_line()
                # returns a (success: bool, iter: Gtk.TextIter) tuple rather
                # than a bare Gtk.TextIter — unpack accordingly.
                result = self._log_buffer.get_iter_at_line(
                    line_count - MAX_LOG_LINES)
                trim_end = result[1] if isinstance(result, tuple) else result
                self._log_buffer.delete(start, trim_end)
            except Exception:
                pass  # never let a trim failure crash the logging path

        # Scroll to bottom
        mark = self._log_buffer.get_insert()
        self.log_view.scroll_mark_onscreen(mark)
