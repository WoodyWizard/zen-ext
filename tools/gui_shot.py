"""Render the window to a PNG with demo data: python3 tools/gui_shot.py OUT.png [--empty]"""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp())
os.environ["ZEN_EXT_HOME"] = str(tmp / "data")
sys.path.insert(0, str(ROOT))

from zen_ext import core, gui  # noqa: E402  (gui picks the GTK version)
from gi.repository import GLib, Gtk  # noqa: E402

out = sys.argv[1]
profile = tmp / "profile"
(profile / "extensions").mkdir(parents=True)
if "--empty" not in sys.argv:
    core.set_profiles([profile])
    for name, ver, link in [("Zen Tabs", "0.3.1", True), ("Мой переводчик", "1.0", False),
                            ("Chrome Thing", "5.2", False)]:
        src = tmp / "src" / name
        src.mkdir(parents=True)
        (src / "manifest.json").write_text(json.dumps(
            {"manifest_version": 2, "name": name, "version": ver}))
        core.add(src, link=link)
    first = core.load_state()["extensions"]["zen-tabs@zen-ext.local"]
    mtime = core.installed_path(core.Profile("p", profile, False), first["id"]).stat().st_mtime
    (profile / "extensions.json").write_text(json.dumps({"addons": [{
        "id": first["id"], "location": "app-profile", "version": "0.3.1", "active": True,
        "updateDate": int(mtime * 1000)}]}))

app = gui.App()


def shoot(win):
    paintable = Gtk.WidgetPaintable.new(win)
    w, h = win.get_width(), win.get_height()
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, w, h)
    node = snap.to_node()
    texture = win.get_native().get_renderer().render_texture(node, None)
    texture.save_to_png(out)
    print("saved", out, w, h)
    app.quit()
    return False


def on_activate(a):
    win = gui.Window(a)
    win.present()
    GLib.timeout_add(1200, shoot, win)


app.connect("activate", on_activate)
app.do_activate = lambda: None
app.run([])
