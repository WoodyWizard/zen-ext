"""GTK 4 / libadwaita window: drop files or folders in, see what Zen loaded."""

import os
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import core, i18n  # noqa: E402
from .i18n import _  # noqa: E402

APP_ID = "io.github.zen_ext.Manager"
REFRESH_SECONDS = 3

STATUS_ICON = {
    "active": "emblem-ok-symbolic",
    "pending": "view-refresh-symbolic",
    "pending-update": "view-refresh-symbolic",
    "disabled": "action-unavailable-symbolic",
    "incompatible": "dialog-warning-symbolic",
    "missing": "dialog-warning-symbolic",
    "inactive": "action-unavailable-symbolic",
}


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("Zen Extensions"), default_width=640,
                         default_height=620)
        self._shown = None

        header = Adw.HeaderBar()
        add_menu = Gio.Menu()
        add_menu.append(_("File (.xpi, .zip, .crx)…"), "win.add-file")
        add_menu.append(_("Source Folder…"), "win.add-folder")
        add_menu.append(_("From URL…"), "win.add-url")
        add_btn = Gtk.MenuButton(icon_name="list-add-symbolic", menu_model=add_menu,
                                 tooltip_text=_("Add extension"))
        header.pack_start(add_btn)
        main_menu = Gio.Menu()
        main_menu.append(_("Zen Profiles…"), "win.profiles")
        main_menu.append(_("Reapply Everything"), "win.sync")
        main_menu.append(_("Data Folder"), "win.open-data")
        lang_menu = Gio.Menu()
        lang_menu.append(_("System Default"), "win.language::auto")
        for code, name in i18n.LANGUAGES.items():
            lang_menu.append(name, f"win.language::{code}")
        main_menu.append_submenu(_("Language"), lang_menu)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=main_menu,
                                       tooltip_text=_("Menu")))

        for name, cb in [("add-file", self.on_add_file), ("add-folder", self.on_add_folder),
                         ("add-url", self.on_add_url), ("profiles", self.on_profiles),
                         ("sync", self.on_sync), ("open-data", self.on_open_data)]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_a, cb=cb: cb())
            self.add_action(action)
        lang = Gio.SimpleAction.new_stateful(
            "language", GLib.VariantType.new("s"),
            GLib.Variant("s", core.load_state().get("language") or "auto"))
        lang.connect("change-state", self.on_language)
        self.add_action(lang)

        self.banner = Adw.Banner()
        self.banner.connect("button-clicked", lambda *_: self.on_setup())

        self.list_group = Adw.PreferencesGroup()
        page = Adw.PreferencesPage()
        page.add(self.list_group)
        self.list_page = page

        self.empty = Adw.StatusPage(
            icon_name="application-x-addon-symbolic",
            title=_("Drop an Extension Here"),
            description=_("An .xpi, .zip or .crx file, a folder with manifest.json, or a link. "
                          "Add it once, and Zen loads it on every start."))

        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(self.empty, "empty")
        self.stack.add_named(page, "list")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.banner)
        box.append(self.stack)
        self.toasts = Adw.ToastOverlay(child=box)

        view = Adw.ToolbarView(content=self.toasts)
        view.add_top_bar(header)
        self.set_content(view)

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("drop", self.on_drop)
        self.add_controller(drop)
        text_drop = Gtk.DropTarget.new(str, Gdk.DragAction.COPY)
        text_drop.connect("drop", lambda _t, value, *_: self.add_sources([value.strip()]) or True)
        self.add_controller(text_drop)

        self.refresh()
        timer = GLib.timeout_add_seconds(REFRESH_SECONDS, self.refresh)
        self.connect("destroy", lambda *_a: GLib.source_remove(timer))

    # ------------------------------------------------------------ list

    def refresh(self):
        state = core.load_state()
        profiles = core.target_profiles(state)
        addons = {p.key: core.zen_addons(p) for p in profiles}
        rows = []
        pending = False
        for e in sorted(state["extensions"].values(), key=lambda e: e["name"].lower()):
            statuses = [core.status(e, p, addons[p.key]) for p in profiles]
            pending |= any(s.startswith("pending") for s in statuses)
            rows.append((e, statuses))

        if not profiles:
            self._set_banner(_("No Zen profile found. Start Zen at least once."), None)
        elif not all(core.profile_configured(p) for p in profiles):
            self._set_banner(_("The Zen profile isn't set up for your own extensions yet."), _("Set Up"))
        elif pending:
            self._set_banner(_("Restart Zen to apply the changes."), None)
        else:
            self.banner.set_revealed(False)

        # Rebuild rows only when something visible changed.
        key = [(e["id"], e["name"], e["version"], e.get("error"), tuple(s)) for e, s in rows]
        key.append(tuple(p.name for p in profiles))
        if key == self._shown:
            return True
        self._shown = key
        page = self.list_page
        page.remove(self.list_group)
        self.list_group = Adw.PreferencesGroup(title=_("Installed"))
        page.add(self.list_group)
        for e, statuses in rows:
            self.list_group.add(self._row(e, profiles, statuses))
        self.stack.set_visible_child_name("list" if rows else "empty")
        return True

    def _row(self, e, profiles, statuses):
        worst = next((s for s in ("missing", "incompatible", "pending", "pending-update",
                                  "disabled", "inactive") if s in statuses), "active")
        parts = [e["version"]]
        if len(profiles) > 1:
            parts += [f"{p.name}: {core.status_text(s)}" for p, s in zip(profiles, statuses)]
        elif statuses:
            parts.append(core.status_text(statuses[0]))
        if e.get("link"):
            parts.append(_("watches the folder"))
        if e.get("error"):
            parts.append(_("build error: {error}", error=e["error"]))
        row = Adw.ActionRow(title=GLib.markup_escape_text(e["name"]),
                            subtitle=GLib.markup_escape_text(" · ".join(parts)),
                            subtitle_lines=3)
        row.set_tooltip_text(f"{e['id']}\n{e['source']}")
        row.add_prefix(Gtk.Image(icon_name=STATUS_ICON[worst]))

        src = Path(e["source"])
        if src.exists():
            folder = src if src.is_dir() else src.parent
            open_btn = Gtk.Button(icon_name="folder-open-symbolic", valign=Gtk.Align.CENTER,
                                  tooltip_text=_("Open source folder"))
            open_btn.add_css_class("flat")
            open_btn.connect("clicked", lambda *_: Gio.AppInfo.launch_default_for_uri(
                folder.as_uri(), None))
            row.add_suffix(open_btn)
        if e.get("link"):
            rebuild_btn = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                                     tooltip_text=_("Rebuild now"))
            rebuild_btn.add_css_class("flat")
            rebuild_btn.connect("clicked", lambda *_: self.on_rebuild(e))
            row.add_suffix(rebuild_btn)
        rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                        tooltip_text=_("Remove"))
        rm.add_css_class("flat")
        rm.connect("clicked", lambda *_: self.on_remove(e))
        row.add_suffix(rm)
        return row

    def _set_banner(self, title, button):
        self.banner.set_title(title)
        self.banner.set_button_label(button)
        self.banner.set_revealed(True)

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=5))

    def force_refresh(self):
        self._shown = None
        self.refresh()

    # ------------------------------------------------------------ adding

    def add_sources(self, sources):
        """Add in a worker thread: downloads and big folders must not freeze the window."""
        def work():
            for s in sources:
                try:
                    notes = []
                    e = core.add(s, on_notes=notes.append)
                    if e["link"]:
                        msg = _("Added: {name} {version}, folder changes are picked up automatically",
                                name=e["name"], version=e["version"])
                    else:
                        msg = _("Added: {name} {version}", name=e["name"], version=e["version"])
                    GLib.idle_add(self.toast, msg)
                    for n in notes:
                        GLib.idle_add(self.toast, n)
                except (core.ZenExtError, OSError) as err:
                    GLib.idle_add(self.error, str(err))
            GLib.idle_add(self.force_refresh)
        threading.Thread(target=work, daemon=True).start()

    def on_drop(self, _target, value, _x, _y):
        self.add_sources([f.get_path() or f.get_uri() for f in value.get_files()])
        return True

    def on_add_file(self):
        dialog = Gtk.FileDialog(title=_("Choose an Extension"), modal=True)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        f = Gtk.FileFilter(name=_("Extensions (.xpi, .zip, .crx)"))
        for pattern in ("*.xpi", "*.zip", "*.crx"):
            f.add_pattern(pattern)
        filters.append(f)
        dialog.set_filters(filters)

        def done(d, res):
            try:
                files = d.open_multiple_finish(res)
            except GLib.Error:
                return
            self.add_sources([files.get_item(i).get_path() for i in range(files.get_n_items())])
        dialog.open_multiple(self, None, done)

    def on_add_folder(self):
        dialog = Gtk.FileDialog(title=_("Folder with manifest.json"), modal=True)

        def done(d, res):
            try:
                folder = d.select_folder_finish(res)
            except GLib.Error:
                return
            self.add_sources([folder.get_path()])
        dialog.select_folder(self, None, done)

    def on_add_url(self):
        entry = Gtk.Entry(placeholder_text="https://…", activates_default=True, hexpand=True)
        dialog = Adw.AlertDialog(
            heading=_("Add from URL"),
            body=_("A direct link to an .xpi/.crx, or an addons.mozilla.org / Chrome Web Store page."),
            extra_child=entry, default_response="add", close_response="cancel")
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("add", _("Add"))
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)

        def done(d, res):
            if d.choose_finish(res) == "add" and entry.get_text().strip():
                self.toast(_("Downloading…"))
                self.add_sources([entry.get_text().strip()])
        dialog.choose(self, None, done)

    # ------------------------------------------------------------ other actions

    def on_remove(self, e):
        dialog = Adw.AlertDialog(
            heading=_("Remove “{name}”?", name=e["name"]),
            body=_("The extension disappears from Zen after a restart. Its data in Zen is deleted too."),
            default_response="cancel", close_response="cancel")
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

        def done(d, res):
            if d.choose_finish(res) != "remove":
                return
            try:
                core.remove(e["id"])
                self.toast(_("Removed: {name}", name=e["name"]))
            except (core.ZenExtError, OSError) as err:
                self.error(str(err))
            self.force_refresh()
        dialog.choose(self, None, done)

    def on_rebuild(self, e):
        try:
            with core.locked_state() as state:
                core.rebuild(e["id"], state)
            self.toast(_("Rebuilt: {name}", name=e["name"]))
        except (core.ZenExtError, OSError) as err:
            self.error(str(err))
        self.force_refresh()

    def on_setup(self):
        try:
            with core.locked_state() as state:
                for p in core.target_profiles(state):
                    core.configure_profile(p)
            self.toast(_("Done. Restart Zen."))
        except OSError as err:
            self.error(str(err))
        self.force_refresh()

    def on_sync(self):
        errors = core.sync()
        for err in errors:
            self.error(err)
        if not errors:
            self.toast(_("All extensions are in place"))
        self.force_refresh()

    def on_open_data(self):
        core.DATA_DIR.mkdir(parents=True, exist_ok=True)
        Gio.AppInfo.launch_default_for_uri(core.DATA_DIR.as_uri(), None)

    def on_profiles(self):
        state = core.load_state()
        current = {p.key for p in core.target_profiles(state)}
        group = Adw.PreferencesGroup(
            description=_("Where to install extensions. Usually the profile Zen opens by default "
                          "is enough."))
        switches = []
        for p in core.find_profiles():
            row = Adw.SwitchRow(title=GLib.markup_escape_text(p.name),
                                subtitle=GLib.markup_escape_text(
                                    (_("default") + " · " if p.default else "") + str(p.path)),
                                active=p.key in current)
            group.add(row)
            switches.append((p, row))
        dialog = Adw.AlertDialog(heading=_("Zen Profiles"), extra_child=group,
                                 default_response="save", close_response="cancel")
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        def done(d, res):
            if d.choose_finish(res) != "save":
                return
            chosen = [p.path for p, row in switches if row.get_active()]
            if not chosen:
                self.error(_("Select at least one profile"))
                return
            try:
                core.set_profiles(chosen)
                self.toast(_("Profiles saved. Restart Zen."))
            except (core.ZenExtError, OSError) as err:
                self.error(str(err))
            self.force_refresh()
        dialog.choose(self, None, done)

    def on_language(self, action, value):
        action.set_state(value)
        core.set_language(value.get_string())
        # Every label is set at construction, so rebuild the window in the new language.
        app = self.get_application()
        Window(app).present()
        self.destroy()

    def error(self, text):
        dialog = Adw.AlertDialog(heading=_("Something Went Wrong"), body=text)
        dialog.add_response("ok", _("OK"))
        dialog.present(self)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)

    def _window(self):
        win = self.get_active_window() or Window(self)
        win.present()
        return win

    def do_activate(self):
        self._window()

    def do_open(self, files, _n, _hint):
        self._window().add_sources([f.get_path() or f.get_uri() for f in files])


def main(files=()):
    app = App()
    argv = ["zen-ext"] + [str(Path(f).resolve()) if os.path.exists(f) else f for f in files]
    return app.run(argv)
