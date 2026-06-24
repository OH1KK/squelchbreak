"""
Squelchbreak — application shell.

Adw.ApplicationWindow with a headerbar, a hamburger menu (modern GNOME
convention instead of a classic File/Edit/Help menubar), a view switcher
between the Main and Settings pages, and Adw.Toast for save/load
confirmations. Owns the background audio thread and bridges its callbacks
back onto the GTK main loop via GLib.idle_add.
"""
import os
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio

from . import config as cfgmod
from .audio_engine import (
    AudioEngine, AudioEngineUI, list_input_devices, resolve_device_index,
    PYAUDIO_OK,
)
from .constants import (
    __version__, APP_ID, APP_TITLE, DEFAULT_CONFIG_PATH,
    HOMEPAGE_URL, ISSUES_URL,
)
from .main_page import MainPage
from .settings_page import SettingsPage


MENU_XML = """
<interface>
  <menu id="primary-menu">
    <section>
      <item>
        <attribute name="label">Open Config…</attribute>
        <attribute name="action">app.open_config</attribute>
      </item>
      <item>
        <attribute name="label">Save Config</attribute>
        <attribute name="action">app.save_config</attribute>
      </item>
      <item>
        <attribute name="label">Save Config As…</attribute>
        <attribute name="action">app.save_config_as</attribute>
      </item>
    </section>
    <section>
      <item>
        <attribute name="label">Refresh Audio Devices</attribute>
        <attribute name="action">app.refresh_devices</attribute>
      </item>
    </section>
    <section>
      <item>
        <attribute name="label">About Squelchbreak</attribute>
        <attribute name="action">app.about</attribute>
      </item>
      <item>
        <attribute name="label">Quit</attribute>
        <attribute name="action">app.quit</attribute>
      </item>
    </section>
  </menu>
</interface>
"""


class EngineUIBridge(AudioEngineUI):
    """Translates AudioEngine callbacks (worker thread) into GLib.idle_add calls."""

    def __init__(self, win):
        self.win = win

    def on_vu_level(self, level):
        GLib.idle_add(self.win._apply_vu_level, level)

    def on_recording_started(self, filename_base):
        GLib.idle_add(self.win._on_recording_started, filename_base)

    def on_recording_stopped(self):
        GLib.idle_add(self.win._on_recording_stopped)

    def on_waiting_started(self):
        GLib.idle_add(self.win._on_waiting_started)

    def on_session_saved(self, wav_path, json_path, duration_s):
        GLib.idle_add(self.win._on_session_saved, wav_path, duration_s)

    def on_log(self, message, level="normal"):
        GLib.idle_add(self.win._log, message, level)

    def on_status(self, message):
        GLib.idle_add(self.win._set_status, message)

    def on_stream_stuck_restart(self):
        GLib.idle_add(self.win._set_status, "Audio stream stuck — restarting…")

    def on_fatal_error(self, message):
        GLib.idle_add(self.win._on_fatal_error, message)


class SquelchbreakWindow(Adw.ApplicationWindow):
    def __init__(self, app, config_path=None):
        super().__init__(application=app)
        self.set_default_size(720, 640)

        self.config_path = os.path.abspath(
            os.path.expanduser(config_path or DEFAULT_CONFIG_PATH))
        self.state = cfgmod.make_default_state()

        self.recording = False
        self.vox_listening = False
        self.manual_active = False
        self.audio_thread = None
        self.engine = AudioEngine(EngineUIBridge(self), self._get_engine_settings)
        self._pulse_source_id = None
        self._pulse_bright = True
        self._devices = [("Default input device", -1)]

        self._build_ui()
        self._populate_devices(initial=True)
        self._load_config_into_ui(self.config_path, quiet=True)
        self._update_title()

        if not PYAUDIO_OK:
            self._log("⚠ pyaudio not found. Install: pip install pyaudio", "amber")
        self._log(f"Config file: {self.config_path}", "dim")

    # ── UI construction ─────────────────────────────────────────────────────────

    def _build_ui(self):
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # View switcher (Main / Settings) in the headerbar title position
        self.view_stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.view_stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        # Status indicator (IDLE / WAITING / REC) shown at the right of headerbar
        self.status_label = Gtk.Label(label="IDLE")
        self.status_label.add_css_class("dim-label")
        self.status_label.set_margin_end(6)
        header.pack_end(self.status_label)

        # Hamburger menu button
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        builder = Gtk.Builder.new_from_string(MENU_XML, -1)
        menu_model = builder.get_object("primary-menu")
        menu_button.set_menu_model(menu_model)
        header.pack_end(menu_button)

        # Toast overlay wraps the page content so Adw.Toast can appear anywhere
        self.toast_overlay = Adw.ToastOverlay()
        toolbar_view.set_content(self.toast_overlay)

        self.main_page = MainPage()
        self.settings_page = SettingsPage()

        self.view_stack.add_titled(self.main_page, "main", "Main")
        self.view_stack.get_page(self.main_page).set_icon_name(
            "audio-input-microphone-symbolic")
        self.view_stack.add_titled(self.settings_page, "settings", "Settings")
        self.view_stack.get_page(self.settings_page).set_icon_name(
            "preferences-system-symbolic")

        self.toast_overlay.set_child(self.view_stack)

        self._wire_main_page()
        self._wire_settings_page()

    def _wire_main_page(self):
        mp = self.main_page
        mp.on_start_clicked = self._on_start
        mp.on_stop_clicked = self._on_stop
        mp.on_manual_rec_clicked = self._on_manual_rec
        mp.on_mode_changed = self._on_mode_changed
        mp.on_threshold_changed = lambda v: self.state.__setitem__("vox_threshold", v)
        mp.on_tail_silence_changed = lambda v: self.state.__setitem__("tail_silence", v)
        mp.on_channel_name_changed = lambda t: self.state.__setitem__("channel_name", t)

    def _wire_settings_page(self):
        sp = self.settings_page
        sp.on_save_path_changed = lambda t: self.state.__setitem__("save_path", t)
        sp.on_prefix_changed = lambda t: self.state.__setitem__("filename_prefix", t)
        sp.on_device_changed = lambda n: self.state.__setitem__("device_name", n)
        sp.on_meta_script_changed = lambda t: self.state.__setitem__("meta_script", t)
        sp.on_test_script_clicked = self._on_test_script
        sp.on_normalize_toggled = lambda a: self.state.__setitem__("normalize_audio", a)
        sp.on_trim_toggled = lambda a: self.state.__setitem__("trim_audio", a)
        sp.on_pad_toggled = lambda a: self.state.__setitem__("add_silence_pad", a)
        sp.on_browse_path_clicked = self._on_browse_path
        sp.on_browse_script_clicked = self._on_browse_script
        sp.on_create_dir_clicked = self._on_create_dir
        sp.on_refresh_devices_clicked = lambda: self._populate_devices(initial=False)

    # ── Config load/save ────────────────────────────────────────────────────────

    def _update_title(self):
        self.set_title(f"{APP_TITLE} — {os.path.basename(self.config_path)}")

    def _apply_state_to_ui(self):
        s = self.state
        self.main_page.set_threshold(s["vox_threshold"])
        self.main_page.set_tail_silence(s["tail_silence"])
        self.main_page.set_channel_name(s["channel_name"])
        self.main_page.set_mode(s["mode"])
        self.settings_page.set_save_path(s["save_path"])
        self.settings_page.set_prefix(s["filename_prefix"])
        self.settings_page.set_meta_script(s["meta_script"])
        self.settings_page.set_processing_flags(
            s["normalize_audio"], s["trim_audio"], s["add_silence_pad"])

    def _collect_state_from_ui(self):
        # Most fields are kept live in self.state via callbacks already;
        # device name is read explicitly since ComboRow selection doesn't
        # always fire 'changed' the same way entries do.
        self.state["device_name"] = self.settings_page.get_selected_device_name()
        return self.state

    def _load_config_into_ui(self, path, quiet=False):
        if not os.path.exists(path):
            if not quiet:
                self._log(f"Config file not found: {path}", "amber")
            self._apply_state_to_ui()
            return
        try:
            state, warnings = cfgmod.load_config(path)
            self.state = state
            self.config_path = os.path.abspath(path)
            self._apply_state_to_ui()
            self._populate_devices(initial=False)  # re-resolve device by name
            self._update_title()
            for w in warnings:
                self._log(w, "amber")
            if not quiet:
                self._log(f"Config loaded: {path}", "green")
                self._toast(f"Config loaded: {os.path.basename(path)}")
        except Exception as e:
            self._log(f"Could not load config: {e}", "red")
            self._toast(f"Load failed: {e}")

    def _save_config_from_ui(self, path=None, quiet=False):
        path = path or self.config_path
        self._collect_state_from_ui()
        try:
            saved_path = cfgmod.save_config(path, self.state)
            self.config_path = saved_path
            self._update_title()
            if not quiet:
                self._log(f"Config saved: {saved_path}", "green")
                self._toast("Settings saved")
        except Exception as e:
            self._log(f"Could not save config: {e}", "red")
            self._toast(f"Save failed: {e}")

    # ── Device handling ──────────────────────────────────────────────────────────

    def _populate_devices(self, initial=False):
        devices = list_input_devices()
        names = [n for n, _ in devices]
        self._devices = devices

        wanted = self.state.get("device_name", "Default input device")
        resolved_name, _idx, exact = resolve_device_index(wanted, devices)
        if not exact and wanted != "Default input device":
            self._log(f"⚠ Saved device '{wanted}' not found, using "
                      f"'{resolved_name}'.", "amber")
        self.state["device_name"] = resolved_name
        self.settings_page.set_device_list(names, selected_name=resolved_name)
        if not initial:
            self._log(f"Found {len(devices) - 1} input device(s).", "dim")

    def _get_engine_settings(self):
        """Live snapshot handed to the audio engine on every loop iteration."""
        s = self.state
        _name, idx, _exact = resolve_device_index(
            s.get("device_name", "Default input device"), self._devices)
        return {
            "vox_threshold": s["vox_threshold"],
            "tail_silence": s["tail_silence"],
            "filename_prefix": s["filename_prefix"],
            "save_path": s["save_path"],
            "meta_script": s["meta_script"],
            "channel_name": s["channel_name"],
            "normalize_audio": s["normalize_audio"],
            "trim_audio": s["trim_audio"],
            "add_silence_pad": s["add_silence_pad"],
            "device_index": idx,
        }

    # ── Start / stop / manual rec ────────────────────────────────────────────────

    def _on_mode_changed(self, mode):
        self.state["mode"] = mode

    def _on_start(self):
        if not PYAUDIO_OK:
            self._show_error_dialog("pyaudio is not installed.\n\npip install pyaudio")
            return
        save_path = os.path.expanduser(self.state["save_path"])
        if not os.access(save_path, os.W_OK):
            self._confirm_create_dir(save_path)
            return
        self._begin_run()

    def _confirm_create_dir(self, save_path):
        dialog = Adw.MessageDialog.new(
            self, "Directory missing",
            f"{save_path}\n\nThis directory doesn't exist. Create it now?")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Create")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.connect("response", self._on_create_dir_dialog_response, save_path)
        dialog.present()

    def _on_create_dir_dialog_response(self, dialog, response, save_path):
        if response == "create":
            try:
                os.makedirs(save_path, exist_ok=True)
                self._log(f"Directory ready: {save_path}", "green")
                self._begin_run()
            except Exception as e:
                self._log(f"Could not create directory: {e}", "red")
                self._toast(f"Could not create directory: {e}")

    def _begin_run(self):
        self._collect_state_from_ui()
        mode = self.state["mode"]
        self.main_page.set_running_state(True, mode)

        if mode == "manual":
            self.engine.manual_active = False
            self.manual_active = False
            self._log("Monitor started (manual mode).", "green")
            self._set_status("MONITOR")
            target = self.engine.run_manual
        else:
            self._log("VOX started. Waiting for audio…", "green")
            self.vox_listening = True
            self._start_waiting_pulse()
            target = self.engine.run_vox

        self.audio_thread = threading.Thread(target=target, daemon=True)
        self.audio_thread.start()

    def _on_stop(self):
        self.engine.request_stop()
        self.engine.manual_active = False
        self.vox_listening = False
        self.manual_active = False
        self.recording = False
        self._stop_waiting_pulse()
        self.main_page.set_running_state(False, self.state["mode"])
        self.main_page.set_rec_now_label(False)
        self._set_status("IDLE")
        self._set_status_color("dim")
        self._log("Stopped.", "dim")

    def _on_manual_rec(self):
        self.manual_active = not self.manual_active
        self.engine.manual_active = self.manual_active
        self.main_page.set_rec_now_label(self.manual_active)

    # ── Engine → UI callbacks (already marshalled onto main loop) ──────────────

    def _apply_vu_level(self, level):
        self.main_page.set_vu_level(level)
        return False

    def _on_recording_started(self, filename_base):
        self.recording = True
        self.vox_listening = False
        self._stop_waiting_pulse()
        self.main_page.set_recording_color_mode(True)
        self._set_status("REC")
        self._set_status_color("red")
        return False

    def _on_recording_stopped(self):
        self.recording = False
        self.main_page.set_recording_color_mode(False)
        if self.state["mode"] == "vox" and not self.engine.stop_flag:
            self.vox_listening = True
            self._start_waiting_pulse()
        else:
            self._set_status("IDLE")
            self._set_status_color("dim")
        return False

    def _on_waiting_started(self):
        self.vox_listening = True
        self._start_waiting_pulse()
        return False

    def _on_session_saved(self, wav_path, duration_s):
        self._toast(f"Saved {os.path.basename(wav_path)} ({duration_s:.1f}s)")
        return False

    def _on_fatal_error(self, message):
        self._log(message, "red")
        self._toast(message)
        self._on_stop()
        return False

    # ── Status indicator + pulse animation ──────────────────────────────────────

    def _set_status(self, text):
        self.status_label.set_label(text)

    def _set_status_color(self, css_class):
        for c in ("dim-label", "success", "warning", "error"):
            self.status_label.remove_css_class(c)
        mapping = {"dim": "dim-label", "green": "success",
                   "amber": "warning", "red": "error"}
        self.status_label.add_css_class(mapping.get(css_class, "dim-label"))

    def _start_waiting_pulse(self):
        self._stop_waiting_pulse()
        self._pulse_bright = True
        self._set_status("WAITING")

        def _tick():
            if not self.vox_listening:
                self._set_status("IDLE")
                self._set_status_color("dim")
                self._pulse_source_id = None
                return False
            self._set_status_color("green" if self._pulse_bright else "dim")
            self._pulse_bright = not self._pulse_bright
            return True

        self._pulse_source_id = GLib.timeout_add(600, _tick)

    def _stop_waiting_pulse(self):
        if self._pulse_source_id is not None:
            GLib.source_remove(self._pulse_source_id)
            self._pulse_source_id = None

    # ── Settings page actions: browse dialogs, test script ─────────────────────

    def _on_browse_path(self):
        dialog = Gtk.FileDialog(title="Select save directory")
        dialog.select_folder(self, None, self._on_browse_path_done)

    def _on_browse_path_done(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                path = folder.get_path()
                self.state["save_path"] = path
                self.settings_page.set_save_path(path)
        except GLib.Error:
            pass  # cancelled

    def _on_browse_script(self):
        dialog = Gtk.FileDialog(title="Select metadata script")
        dialog.open(self, None, self._on_browse_script_done)

    def _on_browse_script_done(self, dialog, result):
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                self.state["meta_script"] = path
                self.settings_page.set_meta_script(path)
        except GLib.Error:
            pass

    def _on_create_dir(self):
        path = os.path.expanduser(self.state["save_path"])
        try:
            os.makedirs(path, exist_ok=True)
            self._log(f"Directory ready: {path}", "green")
            self._toast("Directory created")
        except Exception as e:
            self._log(f"Could not create directory: {e}", "red")
            self._toast(f"Could not create directory: {e}")

    def _on_test_script(self):
        settings = self._get_engine_settings()
        result = self.engine._get_metadata(settings)
        import json as _json
        if result:
            msg = f"Script → {_json.dumps(result)}"
        else:
            msg = "Script returned nothing (or no script set)."
        self._log(msg, "green" if result else "amber")
        self.view_stack.set_visible_child_name("main")

    # ── Logging / toast helpers ──────────────────────────────────────────────────

    def _log(self, message, level="normal"):
        self.main_page.log(message, level)

    def _toast(self, message):
        toast = Adw.Toast.new(message)
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _show_error_dialog(self, message):
        dialog = Adw.MessageDialog.new(self, "Error", message)
        dialog.add_response("ok", "OK")
        dialog.present()

    def do_close_request(self):
        self.engine.request_stop()
        self._save_config_from_ui(self.config_path, quiet=True)
        return False


class SquelchbreakApp(Adw.Application):
    def __init__(self, config_path=None):
        # NON_UNIQUE is required here: Squelchbreak is designed to run as
        # several fully independent OS processes at once (one per radio/
        # sound card, see --config). GLib's default behaviour treats the
        # application_id as a single-instance lock via D-Bus — launching
        # a second process would just re-activate the first one's window
        # instead of starting a new instance. Disabling that is what lets
        # `squelchbreak --config radio1.json` and
        # `squelchbreak --config radio2.json` open as two separate
        # windows/processes rather than one stealing focus from the other.
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.config_path = config_path
        self.window = None

        self._add_action("open_config", self._action_open_config)
        self._add_action("save_config", self._action_save_config)
        self._add_action("save_config_as", self._action_save_config_as)
        self._add_action("refresh_devices", self._action_refresh_devices)
        self._add_action("about", self._action_about)
        self._add_action("quit", self._action_quit)

    def _add_action(self, name, callback):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda a, p: callback())
        self.add_action(action)

    def do_activate(self):
        if not self.window:
            self.window = SquelchbreakWindow(self, config_path=self.config_path)
        self.window.present()

    # ── Menu actions ──────────────────────────────────────────────────────────────

    def _action_open_config(self):
        dialog = Gtk.FileDialog(title="Open config file")
        filt = Gtk.FileFilter()
        filt.set_name("JSON config")
        filt.add_pattern("*.json")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(filt)
        dialog.set_filters(filters)

        def done(dlg, result):
            try:
                file = dlg.open_finish(result)
                if file:
                    self.window._load_config_into_ui(file.get_path())
            except GLib.Error:
                pass
        dialog.open(self.window, None, done)

    def _action_save_config(self):
        self.window._save_config_from_ui(self.window.config_path)

    def _action_save_config_as(self):
        dialog = Gtk.FileDialog(title="Save config as")
        dialog.set_initial_name(os.path.basename(self.window.config_path))

        def done(dlg, result):
            try:
                file = dlg.save_finish(result)
                if file:
                    self.window._save_config_from_ui(file.get_path())
            except GLib.Error:
                pass
        dialog.save(self.window, None, done)

    def _action_refresh_devices(self):
        self.window._populate_devices(initial=False)

    def _action_about(self):
        about = Adw.AboutWindow(
            transient_for=self.window,
            application_name=APP_TITLE,
            application_icon="audio-input-microphone-symbolic",
            version=__version__,
            developer_name="Kari Karvonen, OH1KK",
            license_type=Gtk.License.GPL_3_0,
            comments="VOX-triggered audio recorder for amateur radio "
                     "scanner monitoring. Listens for a signal breaking "
                     "squelch and records it automatically.",
            website=HOMEPAGE_URL,
            issue_url=ISSUES_URL,
        )
        about.present()

    def _action_quit(self):
        if self.window:
            self.window._save_config_from_ui(self.window.config_path, quiet=True)
        self.quit()
