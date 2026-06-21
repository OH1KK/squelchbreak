"""
Squelchbreak — VU meter widget.

A Gtk.DrawingArea-based level meter with a segmented bar and a clear
threshold marker (dashed line + triangle pointer), matching the behaviour
of the original Tkinter version: segments light up green/amber/red
depending on level relative to the configured VOX threshold.
"""
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from .constants import NUM_VU_BARS, MAXIMUMVOL, GREEN, GREEN_DIM, AMBER, RED


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255.0
    g = int(hex_color[2:4], 16) / 255.0
    b = int(hex_color[4:6], 16) / 255.0
    return r, g, b


_GREEN_RGB     = _hex_to_rgb(GREEN)
_GREEN_DIM_RGB = _hex_to_rgb(GREEN_DIM)
_AMBER_RGB     = _hex_to_rgb(AMBER)
_RED_RGB       = _hex_to_rgb(RED)


class VuMeter(Gtk.DrawingArea):
    """
    Usage:
        meter = VuMeter()
        meter.set_threshold(2000)       # 0..32767 raw VOX threshold
        meter.set_level(0.0..1.0)       # current input level
        meter.set_recording(True/False) # changes "over threshold" colour
    """

    def __init__(self):
        super().__init__()
        self.set_content_width(200)
        self.set_content_height(56)
        self.set_hexpand(True)
        self._level = 0.0
        self._threshold = 2000
        self._recording = False
        self.set_draw_func(self._on_draw)

    def set_level(self, level_0_to_1):
        self._level = max(0.0, min(1.0, level_0_to_1))
        self.queue_draw()

    def set_threshold(self, raw_threshold):
        self._threshold = raw_threshold
        self.queue_draw()

    def set_recording(self, is_recording):
        self._recording = is_recording
        self.queue_draw()

    def _on_draw(self, area, cr, width, height, *_):
        bar_h = height - 12  # reserve bottom area for the triangle marker

        seg_w = width / NUM_VU_BARS
        gap = max(1.0, seg_w * 0.18)

        thr_ratio = min(self._threshold / MAXIMUMVOL, 1.0)
        thr_bar = int(thr_ratio * NUM_VU_BARS)
        lit_count = int(self._level * NUM_VU_BARS)

        # Background track
        cr.set_source_rgba(0, 0, 0, 0.15)
        cr.rectangle(0, 0, width, bar_h)
        cr.fill()

        # Segments
        for i in range(NUM_VU_BARS):
            x0 = i * seg_w
            x1 = (i + 1) * seg_w - gap
            if x1 <= x0:
                continue
            if i < lit_count:
                if i >= thr_bar:
                    r, g, b = _RED_RGB if self._recording else _AMBER_RGB
                elif i >= max(0, thr_bar - 4):
                    r, g, b = _GREEN_RGB
                else:
                    r, g, b = _GREEN_DIM_RGB
                cr.set_source_rgb(r, g, b)
            else:
                cr.set_source_rgba(0, 0, 0, 0.25)
            cr.rectangle(x0, 4, x1 - x0, bar_h - 8)
            cr.fill()

        # Threshold marker: dashed vertical line + downward triangle + label
        x = thr_ratio * width
        ar, ag, ab = _AMBER_RGB

        cr.set_source_rgb(ar, ag, ab)
        cr.set_line_width(2)
        cr.set_dash([3, 2])
        cr.move_to(x, 2)
        cr.line_to(x, bar_h)
        cr.stroke()
        cr.set_dash([])

        half = 5
        cr.move_to(x - half, bar_h + 1)
        cr.line_to(x + half, bar_h + 1)
        cr.line_to(x, height - 1)
        cr.close_path()
        cr.fill()

        cr.select_font_face("monospace")
        cr.set_font_size(9)
        label = "THR"
        extents = cr.text_extents(label)
        if x < width - 32:
            lx = x + 4
        else:
            lx = x - extents.width - 4
        cr.move_to(lx, 12)
        cr.show_text(label)
