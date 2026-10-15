import importlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def make_ext(folder, manifest, files=None):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(manifest))
    for name, text in (files or {}).items():
        f = folder / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return folder


def zip_dir(folder, out, prefix=""):
    with zipfile.ZipFile(out, "w") as z:
        for f in folder.rglob("*"):
            if f.is_file():
                z.write(f, prefix + f.relative_to(folder).as_posix())
    return out


def read_manifest(xpi):
    with zipfile.ZipFile(xpi) as z:
        return json.loads(z.read("manifest.json"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self._env = {k: os.environ.get(k) for k in ("HOME", "ZEN_EXT_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME")}
        os.environ["HOME"] = str(self.home)
        os.environ["ZEN_EXT_HOME"] = str(self.home / "data")
        os.environ.pop("XDG_CONFIG_HOME", None)
        os.environ.pop("XDG_DATA_HOME", None)
        import zen_ext.core
        self.core = importlib.reload(zen_ext.core)
        # A flatpak-style Zen profile tree with two profiles.
        root = self.home / ".var/app/app.zen_browser.zen/config/zen"
        (root / "abc.Default (release)").mkdir(parents=True)
        (root / "xyz.Default Profile").mkdir(parents=True)
        (root / "profiles.ini").write_text(
            "[Profile0]\nName=Default (release)\nIsRelative=1\nPath=abc.Default (release)\n\n"
            "[Profile1]\nName=Default Profile\nIsRelative=1\nPath=xyz.Default Profile\nDefault=1\n")
        (root / "installs.ini").write_text("[2953CB39A2589173]\nDefault=abc.Default (release)\nLocked=1\n")
        self.profile_dir = (root / "abc.Default (release)").resolve()
        self.other_dir = (root / "xyz.Default Profile").resolve()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()


class Profiles(Base):
    def test_install_default_wins_over_default_flag(self):
        profiles = self.core.find_profiles()
        self.assertEqual([p.path for p in profiles if p.default], [self.profile_dir])

    def test_userjs_block_is_idempotent_and_keeps_user_prefs(self):
        p = self.core.find_profiles()[0]
        (p.path / "user.js").write_text('user_pref("a.b", 1);')
        self.core.configure_profile(p)
        self.core.configure_profile(p)
        text = (p.path / "user.js").read_text()
        self.assertEqual(text.count(self.core.USERJS_BEGIN), 1)
        self.assertIn('user_pref("a.b", 1);', text)
        self.assertIn('user_pref("xpinstall.signatures.required", false);', text)
        self.assertTrue(self.core.profile_configured(p))
        self.core.unconfigure_profile(p)
        self.assertEqual((p.path / "user.js").read_text().strip(), 'user_pref("a.b", 1);')


class Packaging(Base):
    def test_missing_id_is_generated_from_localized_name(self):
        src = make_ext(self.home / "src", {
            "manifest_version": 2, "name": "__MSG_appName__", "version": "1.0",
            "default_locale": "en"}, {"_locales/en/messages.json": json.dumps(
                {"appName": {"message": "My Cool Ext"}})})
        meta = self.core.build_xpi(src, self.home / "out.xpi")
        self.assertEqual(meta["id"], "my-cool-ext@zen-ext.local")
        self.assertEqual(meta["name"], "My Cool Ext")
        self.assertEqual(self.core.manifest_id(read_manifest(self.home / "out.xpi")), meta["id"])

    def test_signed_xpi_with_id_is_copied_byte_for_byte(self):
        src = make_ext(self.home / "src", {
            "manifest_version": 2, "name": "X", "version": "2",
            "browser_specific_settings": {"gecko": {"id": "x@y"}}},
            {"META-INF/mozilla.rsa": "sig"})
        xpi = zip_dir(src, self.home / "x.xpi")
        self.core.build_xpi(xpi, self.home / "out.xpi")
        self.assertEqual((self.home / "out.xpi").read_bytes(), xpi.read_bytes())

    def test_modified_signed_xpi_drops_stale_signature(self):
        src = make_ext(self.home / "src", {"manifest_version": 2, "name": "X", "version": "2"},
                       {"META-INF/mozilla.rsa": "sig"})
        xpi = zip_dir(src, self.home / "x.xpi")
        self.core.build_xpi(xpi, self.home / "out.xpi")
        with zipfile.ZipFile(self.home / "out.xpi") as z:
            self.assertNotIn("META-INF/mozilla.rsa", z.namelist())

    def test_crx3_and_service_worker_shim(self):
        src = make_ext(self.home / "src", {
            "manifest_version": 3, "name": "Chrome Thing", "version": "3",
            "background": {"service_worker": "sw.js"}}, {"sw.js": "//"})
        zipped = zip_dir(src, self.home / "c.zip").read_bytes()
        header = b"\x12\x00junk"
        crx = b"Cr24" + struct.pack("<II", 3, len(header)) + header + zipped
        (self.home / "c.crx").write_bytes(crx)
        meta = self.core.build_xpi(self.home / "c.crx", self.home / "out.xpi")
        m = read_manifest(self.home / "out.xpi")
        self.assertEqual(m["background"]["scripts"], ["sw.js"])
        self.assertEqual(len(meta["notes"]), 2)

    def test_github_style_zip_with_top_folder(self):
        src = make_ext(self.home / "src", {"manifest_version": 2, "name": "G", "version": "1"},
                       {"js/a.js": "1"})
        z = zip_dir(src, self.home / "g.zip", prefix="repo-main/")
        self.core.build_xpi(z, self.home / "out.xpi")
        with zipfile.ZipFile(self.home / "out.xpi") as out:
            self.assertEqual(sorted(out.namelist()), ["js/a.js", "manifest.json"])

    def test_folder_packing_skips_vcs_and_node_modules(self):
        src = make_ext(self.home / "src", {"manifest_version": 2, "name": "F", "version": "1"},
                       {".git/HEAD": "x", "node_modules/a/b.js": "x", "bg.js": "x"})
        self.core.build_xpi(src, self.home / "out.xpi")
        with zipfile.ZipFile(self.home / "out.xpi") as out:
            self.assertEqual(sorted(out.namelist()), ["bg.js", "manifest.json"])

    def test_not_an_extension(self):
        (self.home / "a.zip").write_bytes(b"nope")
        with self.assertRaises(self.core.ZenExtError):
            self.core.build_xpi(self.home / "a.zip", self.home / "out.xpi")


class AddRemove(Base):
    def test_add_link_rebuild_remove(self):
        src = make_ext(self.home / "proj", {"manifest_version": 2, "name": "Dev", "version": "1"})
        entry = self.core.add(src)
        self.assertTrue(entry["link"])
        dst = self.profile_dir / "extensions" / "dev@zen-ext.local.xpi"
        self.assertTrue(dst.exists())
        self.assertFalse((self.other_dir / "extensions").exists())
        self.assertTrue(self.core.profile_configured(self.core.find_profiles()[0]))

        make_ext(src, {"manifest_version": 2, "name": "Dev", "version": "2"})
        with self.core.locked_state() as state:
            self.core.rebuild(entry["id"], state)
        self.assertEqual(read_manifest(dst)["version"], "2")

        self.core.remove("dev")
        self.assertFalse(dst.exists())
        self.assertEqual(self.core.load_state()["extensions"], {})

    def test_does_not_overwrite_extension_installed_from_store(self):
        src = make_ext(self.home / "e", {"manifest_version": 2, "name": "U", "version": "1",
                                         "browser_specific_settings": {"gecko": {"id": "u@b"}}})
        store_copy = self.profile_dir / "extensions" / "u@b.xpi"
        store_copy.parent.mkdir()
        store_copy.write_bytes(b"from AMO")
        with self.assertRaises(self.core.ZenExtError):
            self.core.add(src)
        self.assertEqual(store_copy.read_bytes(), b"from AMO")
        self.core.add(src, replace=True)
        self.assertNotEqual(store_copy.read_bytes(), b"from AMO")

    def test_switching_profiles_moves_extensions(self):
        src = make_ext(self.home / "e", {"manifest_version": 2, "name": "P", "version": "1"})
        self.core.add(src, link=False)
        self.core.set_profiles([self.other_dir])
        self.assertFalse((self.profile_dir / "extensions" / "p@zen-ext.local.xpi").exists())
        self.assertFalse((self.profile_dir / "user.js").exists())
        self.assertTrue((self.other_dir / "extensions" / "p@zen-ext.local.xpi").exists())

    def test_status_from_extensions_json(self):
        src = make_ext(self.home / "e", {"manifest_version": 2, "name": "S", "version": "1"})
        entry = self.core.add(src, link=False)
        p = self.core.find_profiles()[0]
        self.assertEqual(self.core.status(entry, p), "pending")
        xpi = self.core.installed_path(p, entry["id"])
        (p.path / "extensions.json").write_text(json.dumps({"addons": [{
            "id": entry["id"], "location": "app-profile", "version": "1", "active": True,
            "userDisabled": False, "appDisabled": False,
            "updateDate": int(xpi.stat().st_mtime * 1000)}]}))
        self.assertEqual(self.core.status(entry, p), "active")
        os.utime(xpi, (1, 1))
        self.assertEqual(self.core.status(entry, p), "pending-update")


class Watcher(Base):
    def test_rebuilds_after_a_quiet_tick(self):
        from zen_ext import watch
        importlib.reload(watch)
        src = make_ext(self.home / "proj", {"manifest_version": 2, "name": "W", "version": "1"})
        self.core.add(src)
        make_ext(src, {"manifest_version": 2, "name": "W", "version": "1.1"}, {"new.js": "x"})
        pending = {}
        buf = io.StringIO()
        watch.log = buf.write
        watch.tick(pending)  # change seen, waits
        self.assertEqual(self.core.load_state()["extensions"]["w@zen-ext.local"]["version"], "1")
        watch.tick(pending)  # still the same: rebuild
        self.assertEqual(self.core.load_state()["extensions"]["w@zen-ext.local"]["version"], "1.1")


if __name__ == "__main__":
    unittest.main()
