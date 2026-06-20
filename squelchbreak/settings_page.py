"""
Squelchbreak — settings page.

Built with Adw.PreferencesPage / Adw.PreferencesGroup / Adw.*Row for the
native GNOME "Settings app" look: grouped cards, switches, entry rows.
"""
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Pango


class SettingsPage(Adw.PreferencesPage):
    def __init__(self):
        super().__init__()

        # Callbacks — wired up by app.py
        self.on_save_path_changed = lambda text: None
        self.on_prefix_changed = lambda text: None
        self.on_device_changed = lambda name: None
        self.on_meta_script_changed = lambda text: None
        self.on_test_script_clicked = lambda: None
        self.on_normalize_toggled = lambda active: None
        self.on_trim_toggled = lambda active: None
        self.on_pad_toggled = lambda active: None
        self.on_browse_path_clicked = lambda: None
        self.on_browse_script_clicked = lambda: None
        self.on_create_dir_clicked = lambda: None
        self.on_refresh_devices_clicked = lambda: None

        self._device_names = ["Default input device"]
        self._suppress_device_callback = False

        self._build_device_group()
        self._build_storage_group()
        self._build_metadata_group()
        self._build_processing_group()

    # ── Audio device group ───────────────────────────────────────────────────────

    def _build_device_group(self):
        group = Adw.PreferencesGroup(title="Audio Input Device")
        self.add(group)

        self.device_row = Adw.ComboRow(title="Sound card",
                                        subtitle="Default input device")
        self._device_model = Gtk.StringList.new(self._device_names)
        self.device_row.set_model(self._device_model)

        # Custom factory so device names are never truncated with an
        # ellipsis — important when several USB sound cards have long,
        # similar-looking names that only differ near the end.
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        self.device_row.set_factory(factory)
        self.device_row.set_list_factory(factory)

        self.device_row.connect("notify::selected", self._on_device_selected)
        group.add(self.device_row)

        refresh_row = Adw.ActionRow(title="Re-scan for sound cards")
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_valign(Gtk.Align.CENTER)
        refresh_btn.add_css_class("flat")
        refresh_btn.connect("clicked", lambda b: self.on_refresh_devices_clicked())
        refresh_row.add_suffix(refresh_btn)
        refresh_row.set_activatable_widget(refresh_btn)
        group.add(refresh_row)

    @staticmethod
    def _on_factory_setup(factory, list_item):
        label = Gtk.Label(xalign=0)
        label.set_wrap(True)
        label.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        label.set_ellipsize(Pango.EllipsizeMode.NONE)
        label.set_max_width_chars(60)
        label.set_margin_top(4)
        label.set_margin_bottom(4)
        label.set_margin_start(6)
        label.set_margin_end(6)
        list_item.set_child(label)

    @staticmethod
    def _on_factory_bind(factory, list_item):
        label = list_item.get_child()
        item = list_item.get_item()
        label.set_text(item.get_string() if item else "")

    def _on_device_selected(self, row, _pspec):
        if self._suppress_device_callback:
            return
        idx = row.get_selected()
        if 0 <= idx < len(self._device_names):
            name = self._device_names[idx]
            row.set_subtitle(name)
            self.on_device_changed(name)

    def set_device_list(self, names, selected_name=None):
        """Repopulate the dropdown; preserves selection by name if possible."""
        self._suppress_device_callback = True
        self._device_names = names
        self._device_model = Gtk.StringList.new(names)
        self.device_row.set_model(self._device_model)
        if selected_name and selected_name in names:
            idx = names.index(selected_name)
        else:
            idx = 0
        self.device_row.set_selected(idx)
        self.device_row.set_subtitle(names[idx])
        self._suppress_device_callback = False

    def get_selected_device_name(self):
        idx = self.device_row.get_selected()
        if 0 <= idx < len(self._device_names):
            return self._device_names[idx]
        return "Default input device"

    # ── File storage group ───────────────────────────────────────────────────────

    def _build_storage_group(self):
        group = Adw.PreferencesGroup(title="File Storage")
        self.add(group)

        self.save_path_row = Adw.EntryRow(title="Save path")
        self.save_path_row.connect("changed",
                                   lambda e: self.on_save_path_changed(e.get_text()))
        browse_btn = Gtk.Button(icon_name="folder-open-symbolic")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.add_css_class("flat")
        browse_btn.connect("clicked", lambda b: self.on_browse_path_clicked())
        self.save_path_row.add_suffix(browse_btn)
        group.add(self.save_path_row)

        self.prefix_row = Adw.EntryRow(title="Filename prefix")
        self.prefix_row.connect("changed",
                                lambda e: self.on_prefix_changed(e.get_text()))
        group.add(self.prefix_row)

        create_dir_row = Adw.ActionRow(title="Create save directory if missing")
        create_btn = Gtk.Button(icon_name="folder-new-symbolic")
        create_btn.set_valign(Gtk.Align.CENTER)
        create_btn.add_css_class("flat")
        create_btn.connect("clicked", lambda b: self.on_create_dir_clicked())
        create_dir_row.add_suffix(create_btn)
        create_dir_row.set_activatable_widget(create_btn)
        group.add(create_dir_row)

    def set_save_path(self, text):
        self.save_path_row.set_text(text or "")

    def set_prefix(self, text):
        self.prefix_row.set_text(text or "")

    # ── Metadata / channel group ─────────────────────────────────────────────────

    def _build_metadata_group(self):
        group = Adw.PreferencesGroup(
            title="Metadata Script",
            description="Optional executable run before each recording. "
                         "Must print JSON to stdout, e.g. "
                         '{"frequency": 145600000, "mode": "NFM"}')
        self.add(group)

        self.meta_script_row = Adw.EntryRow(title="Script path")
        self.meta_script_row.connect("changed",
                                     lambda e: self.on_meta_script_changed(e.get_text()))
        browse_btn = Gtk.Button(icon_name="document-open-symbolic")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.add_css_class("flat")
        browse_btn.connect("clicked", lambda b: self.on_browse_script_clicked())
        self.meta_script_row.add_suffix(browse_btn)
        group.add(self.meta_script_row)

        test_row = Adw.ActionRow(title="Test script now",
                                  subtitle="Runs the script and shows its output in the log")
        test_btn = Gtk.Button(icon_name="media-playback-start-symbolic")
        test_btn.set_valign(Gtk.Align.CENTER)
        test_btn.add_css_class("flat")
        test_btn.connect("clicked", lambda b: self.on_test_script_clicked())
        test_row.add_suffix(test_btn)
        test_row.set_activatable_widget(test_btn)
        group.add(test_row)

    def set_meta_script(self, text):
        self.meta_script_row.set_text(text or "")

    # ── Audio processing group ───────────────────────────────────────────────────

    def _build_processing_group(self):
        group = Adw.PreferencesGroup(title="Audio Processing")
        self.add(group)

        self.normalize_row = Adw.SwitchRow(
            title="Normalize level", subtitle="Scale peak amplitude to maximum")
        self.normalize_row.connect("notify::active",
            lambda r, p: self.on_normalize_toggled(r.get_active()))
        group.add(self.normalize_row)

        self.trim_row = Adw.SwitchRow(
            title="Trim silence", subtitle="Remove leading/trailing silence at threshold")
        self.trim_row.connect("notify::active",
            lambda r, p: self.on_trim_toggled(r.get_active()))
        group.add(self.trim_row)

        self.pad_row = Adw.SwitchRow(
            title="Add 0.5s padding", subtitle="Prepend and append a short silence")
        self.pad_row.connect("notify::active",
            lambda r, p: self.on_pad_toggled(r.get_active()))
        group.add(self.pad_row)

    def set_processing_flags(self, normalize, trim, pad):
        self.normalize_row.set_active(normalize)
        self.trim_row.set_active(trim)
        self.pad_row.set_active(pad)
