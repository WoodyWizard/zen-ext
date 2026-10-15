"""Zen profiles, packaging and deploying unsigned extensions.

How loading works: Zen (Firefox) scans <profile>/extensions/ on every start
and installs any <id>.xpi it finds there. Zen is built without
MOZ_REQUIRE_SIGNING, so with xpinstall.signatures.required=false it accepts
unsigned files too. Three prefs in user.js make this reliable:

  xpinstall.signatures.required = false  unsigned extensions are allowed
  extensions.autoDisableScopes  = 14     profile sideloads start enabled
  extensions.startupScanScopes  = 1      the profile folder is rescanned on
                                         every start (new, changed, removed)

After that nothing has to run: the .xpi files stay in the profile and Zen
loads them by itself. The watcher (watch.py) only matters for linked source
folders, it rebuilds their .xpi when the sources change.
"""

import configparser
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import i18n
from .i18n import _

APP = "zen-ext"
DATA_DIR = Path(
    os.environ.get("ZEN_EXT_HOME")
    or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / APP
)
STORE_DIR = DATA_DIR / "store"
STATE_FILE = DATA_DIR / "state.json"
LOCK_FILE = DATA_DIR / ".lock"

FLATPAK_ID = "app.zen_browser.zen"
PROFILE_ROOTS = [
    Path.home() / ".var/app" / FLATPAK_ID / "config/zen",
    Path.home() / ".var/app" / FLATPAK_ID / ".zen",
    Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "zen",
    Path.home() / ".zen",
]

# Same pattern as gIDTest in XPIProvider.sys.mjs: file names that don't match
# are ignored by Zen.
ID_RE = re.compile(
    r"^(\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}"
    r"|[a-z0-9-._]*@[a-z0-9-._]+)$",
    re.I,
)
GENERATED_ID_DOMAIN = "zen-ext.local"

# Not packed from source folders and not watched for changes.
IGNORED_DIRS = {".git", ".hg", ".svn", "node_modules", "web-ext-artifacts",
                "__pycache__", ".idea", ".vscode"}
IGNORED_FILES = {".DS_Store", "Thumbs.db"}

PREFS = {
    "xpinstall.signatures.required": False,
    "extensions.autoDisableScopes": 14,
    "extensions.startupScanScopes": 1,
}
USERJS_BEGIN = "// >>> zen-ext: managed block, do not edit >>>"
USERJS_END = "// <<< zen-ext <<<"

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"


class ZenExtError(Exception):
    pass


# ---------------------------------------------------------------- profiles


@dataclass(frozen=True)
class Profile:
    name: str
    path: Path
    default: bool

    @property
    def key(self):
        return str(self.path)


def find_profiles():
    """All Zen profiles on this machine. `default` marks the one Zen opens."""
    found = {}
    for root in PROFILE_ROOTS:
        ini = root / "profiles.ini"
        if not ini.is_file():
            continue
        cp = _read_ini(ini)
        # [Install…] in profiles.ini and every section of installs.ini name the
        # profile a given Zen installation opens; that beats Default=1.
        install_defaults = {cp.get(s, "Default") for s in cp.sections()
                            if s.startswith("Install") and cp.has_option(s, "Default")}
        installs = root / "installs.ini"
        if installs.is_file():
            icp = _read_ini(installs)
            install_defaults |= {icp.get(s, "Default") for s in icp.sections()
                                 if icp.has_option(s, "Default")}
        entries = []
        for s in cp.sections():
            if not s.startswith("Profile") or not cp.has_option(s, "Path"):
                continue
            rel = cp.get(s, "Path")
            relative = cp.get(s, "IsRelative", fallback="1") == "1"
            path = (root / rel) if relative else Path(rel)
            if not path.is_dir():
                continue
            marked = rel in install_defaults if install_defaults else cp.get(s, "Default", fallback="0") == "1"
            entries.append(Profile(cp.get(s, "Name", fallback=path.name), path.resolve(), marked))
        for p in entries:
            found.setdefault(p.key, p)
    return sorted(found.values(), key=lambda p: (not p.default, p.name.lower()))


def _read_ini(path):
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.optionxform = str
    cp.read(path, encoding="utf-8")
    return cp


def profile_from_path(path):
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        raise ZenExtError(_("Profile folder not found: {path}", path=path))
    for p in find_profiles():
        if p.path == path:
            return p
    return Profile(path.name, path, False)


def target_profiles(state):
    """Profiles extensions are deployed to: chosen in setup, else Zen's default."""
    if state.get("profiles"):
        return [profile_from_path(p) for p in state["profiles"] if Path(p).is_dir()]
    return [p for p in find_profiles() if p.default][:1]


# ---------------------------------------------------------------- user.js


def userjs_block():
    lines = [USERJS_BEGIN]
    for name, value in PREFS.items():
        lines.append(f'user_pref("{name}", {json.dumps(value)});')
    lines.append(USERJS_END)
    return "\n".join(lines) + "\n"


def _strip_block(text):
    return re.sub(re.escape(USERJS_BEGIN) + r".*?" + re.escape(USERJS_END) + r"\n?",
                  "", text, flags=re.S)


def configure_profile(profile):
    """Add the managed pref block to user.js, keeping whatever else is there."""
    userjs = profile.path / "user.js"
    text = userjs.read_text(encoding="utf-8") if userjs.exists() else ""
    rest = _strip_block(text)
    if rest and not rest.endswith("\n"):
        rest += "\n"
    _write_atomic(userjs, (rest + userjs_block()).encode())
    (profile.path / "extensions").mkdir(exist_ok=True)


def unconfigure_profile(profile):
    userjs = profile.path / "user.js"
    if not userjs.exists():
        return
    rest = _strip_block(userjs.read_text(encoding="utf-8"))
    if rest.strip():
        _write_atomic(userjs, rest.encode())
    else:
        userjs.unlink()


def profile_configured(profile):
    userjs = profile.path / "user.js"
    return userjs.exists() and userjs_block() in userjs.read_text(encoding="utf-8")


# ---------------------------------------------------------------- state


def load_state():
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {}
    state.setdefault("profiles", [])
    state.setdefault("extensions", {})
    return state


@contextmanager
def locked_state():
    """Load state under an exclusive lock and save it if the block succeeds."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load_state()
        yield state
        _write_atomic(STATE_FILE, json.dumps(state, indent=2, ensure_ascii=False).encode())


def _write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


# ---------------------------------------------------------------- packaging


class _Source:
    """Files of an extension, whatever it came as: folder, .xpi/.zip or .crx."""

    def __init__(self, path):
        self.path = Path(path)
        self.zip = None
        self.prefix = ""
        self.is_crx = False
        if self.path.is_dir():
            if not (self.path / "manifest.json").is_file():
                raise ZenExtError(_("No manifest.json in the folder: {path}", path=self.path))
            return
        data = self.path.read_bytes()
        if data[:4] == b"Cr24":
            data = _crx_to_zip(data)
            self.is_crx = True
        try:
            self.zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ZenExtError(_("Not an extension (.xpi, .zip, .crx): {path}", path=self.path)) from None
        names = self.zip.namelist()
        if "manifest.json" not in names:
            # GitHub-style archives wrap everything in one top folder.
            tops = {n.split("/", 1)[0] for n in names}
            if len(tops) == 1 and f"{next(iter(tops))}/manifest.json" in names:
                self.prefix = next(iter(tops)) + "/"
            else:
                raise ZenExtError(_("No manifest.json in the archive: {path}", path=self.path))

    def read(self, name):
        if self.zip is not None:
            try:
                return self.zip.read(self.prefix + name)
            except KeyError:
                return None
        f = self.path / name
        return f.read_bytes() if f.is_file() else None

    def files(self):
        """(archive name, bytes) pairs for everything that goes into the .xpi."""
        if self.zip is not None:
            for info in self.zip.infolist():
                if info.is_dir() or not info.filename.startswith(self.prefix):
                    continue
                yield info.filename[len(self.prefix):], self.zip.read(info)
            return
        for f in sorted(_walk(self.path)):
            yield f.relative_to(self.path).as_posix(), f.read_bytes()


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in filenames:
            if name not in IGNORED_FILES and not name.endswith(".xpi"):
                yield Path(dirpath) / name


def _crx_to_zip(data):
    version = struct.unpack("<I", data[4:8])[0]
    if version == 2:
        key_len, sig_len = struct.unpack("<II", data[8:16])
        return data[16 + key_len + sig_len:]
    if version == 3:
        header_len = struct.unpack("<I", data[8:12])[0]
        return data[12 + header_len:]
    raise ZenExtError(_("Unknown CRX version: {version}", version=version))


def _parse_json(raw, what):
    text = raw.decode("utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Chrome and Firefox both tolerate whole-line // comments in manifests.
        stripped = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("//"))
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as e:
            raise ZenExtError(_("Error in {what}: {error}", what=what, error=e)) from None


def _localized(value, manifest, src):
    m = re.fullmatch(r"__MSG_(.+)__", value or "")
    if not m:
        return value
    key = m.group(1).lower()
    for locale in (manifest.get("default_locale"), "en", "en_US"):
        raw = locale and src.read(f"_locales/{locale}/messages.json")
        if raw:
            messages = {k.lower(): v for k, v in _parse_json(raw, "messages.json").items()}
            if key in messages:
                return messages[key].get("message", value)
    return value


def manifest_id(manifest):
    for key in ("browser_specific_settings", "applications"):
        gecko = (manifest.get(key) or {}).get("gecko") or {}
        if gecko.get("id"):
            return gecko["id"]
    return None


def generate_id(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48]
    if not slug:
        slug = "ext-" + hashlib.sha1(name.encode()).hexdigest()[:10]
    return f"{slug}@{GENERATED_ID_DOMAIN}"


def build_xpi(src_path, out_path, forced_id=None):
    """Pack any supported source into an .xpi that Zen loads as is.

    Missing gecko IDs are filled in (Zen refuses to sideload without one), and
    a Chrome MV3 service worker also gets listed as a background script,
    because Zen has service-worker backgrounds switched off.
    Returns metadata: id, name, version, notes (list of warnings).
    """
    src = _Source(src_path)
    manifest = _parse_json(src.read("manifest.json"), "manifest.json")
    name = _localized(manifest.get("name"), manifest, src) or Path(src_path).stem
    notes = []
    changed = False

    ext_id = manifest_id(manifest)
    if forced_id and ext_id and forced_id != ext_id:
        raise ZenExtError(_("The ID in manifest.json ({ext_id}) doesn't match the one given ({forced_id})",
                            ext_id=ext_id, forced_id=forced_id))
    if not ext_id:
        ext_id = forced_id or generate_id(name)
        key = ("applications" if "applications" in manifest
               and "browser_specific_settings" not in manifest else "browser_specific_settings")
        manifest.setdefault(key, {}).setdefault("gecko", {})["id"] = ext_id
        changed = True
        notes.append(_("manifest.json had no ID, assigned {ext_id}", ext_id=ext_id))
    if not ID_RE.match(ext_id):
        raise ZenExtError(_("Invalid extension ID: {ext_id}", ext_id=ext_id))

    bg = manifest.get("background") or {}
    if bg.get("service_worker") and not bg.get("scripts"):
        bg["scripts"] = [bg["service_worker"]]
        manifest["background"] = bg
        changed = True
        notes.append(_("The Chrome service worker is loaded as a background script: "
                       "importScripts() and other worker APIs don't work in Zen"))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f".{out_path.name}.tmp")
    if src.zip is not None and not src.prefix and not src.is_crx and not changed:
        shutil.copyfile(src.path, tmp)  # keep the original file, signature included
    else:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for arcname, data in src.files():
                if arcname == "manifest.json":
                    data = json.dumps(manifest, indent=2, ensure_ascii=False).encode()
                elif changed and arcname.startswith("META-INF/"):
                    continue  # the old signature no longer matches the manifest
                z.writestr(arcname, data)
    os.replace(tmp, out_path)
    return {"id": ext_id, "name": name, "version": str(manifest.get("version", "?")),
            "notes": notes}


def source_signature(folder):
    """Changes whenever a file in a linked folder is added, removed or edited."""
    h = hashlib.sha1()
    for f in sorted(_walk(folder)):
        try:
            st = f.stat()
        except FileNotFoundError:
            continue
        h.update(f"{f.relative_to(folder)}\0{st.st_mtime_ns}\0{st.st_size}\n".encode())
    return h.hexdigest()


# ---------------------------------------------------------------- download


def download(url, dest_dir):
    """Fetch an extension by URL. Understands AMO and Chrome Web Store pages."""
    url = _resolve_store_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
            final = r.geturl()
    except OSError as e:
        raise ZenExtError(_("Couldn't download {url}: {error}", url=url, error=e)) from None
    if data[:2] != b"PK" and data[:4] != b"Cr24":
        raise ZenExtError(_("The link isn't an extension (not .xpi/.zip or .crx): {url}", url=url))
    name = Path(urllib.parse.urlparse(final).path).name or "extension"
    dest = Path(dest_dir) / re.sub(r"[^\w.@{}-]+", "_", urllib.parse.unquote(name))
    dest.write_bytes(data)
    return dest


def _resolve_store_url(url):
    u = urllib.parse.urlparse(url)
    m = re.search(r"/addon/([^/?#]+)", u.path)
    if u.netloc.endswith("addons.mozilla.org") and m:
        api = f"https://addons.mozilla.org/api/v5/addons/addon/{m.group(1)}/"
        req = urllib.request.Request(api, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["current_version"]["file"]["url"]
        except (OSError, KeyError, ValueError) as e:
            raise ZenExtError(_("Couldn't find the file on addons.mozilla.org: {error}", error=e)) from None
    m = re.search(r"/([a-p]{32})(?:[/?#]|$)", u.path)
    if u.netloc in ("chromewebstore.google.com", "chrome.google.com") and m:
        return ("https://clients2.google.com/service/update2/crx?response=redirect"
                "&prodversion=140.0&acceptformat=crx2,crx3"
                f"&x=id%3D{m.group(1)}%26uc")
    return url


# ---------------------------------------------------------------- deploy


def installed_path(profile, ext_id):
    return profile.path / "extensions" / f"{ext_id}.xpi"


def deploy(ext_id, profiles):
    store = STORE_DIR / f"{ext_id}.xpi"
    for profile in profiles:
        dst = installed_path(profile, ext_id)
        dst.parent.mkdir(exist_ok=True)
        tmp = dst.with_name(f".{dst.name}.tmp")
        shutil.copyfile(store, tmp)  # fresh mtime, so Zen notices the update
        os.replace(tmp, dst)


def undeploy(ext_id, profiles):
    for profile in profiles:
        installed_path(profile, ext_id).unlink(missing_ok=True)


def add(source, link=None, ext_id=None, replace=False, on_notes=None):
    """Add an extension from a folder, file or URL and deploy it.

    Folders are linked by default: the watcher rebuilds them when they change.
    Returns the state entry.
    """
    tmpdir = None
    try:
        if re.match(r"^https?://", str(source)):
            tmpdir = tempfile.mkdtemp(prefix="dl-", dir=_tmp_root())
            path = download(source, tmpdir)
            origin = str(source)
        else:
            path = Path(source).expanduser().resolve()
            if path.name == "manifest.json":
                path = path.parent
            if not path.exists():
                raise ZenExtError(_("Not found: {path}", path=path))
            origin = str(path)
        if link is None:
            link = path.is_dir()
        if link and not path.is_dir():
            raise ZenExtError(_("Only a source folder can be linked"))

        with locked_state() as state:
            if link and not ext_id:
                # Re-adding a linked folder keeps its ID, even a generated one.
                for e in state["extensions"].values():
                    if e.get("link") and e.get("source") == origin:
                        ext_id = e["id"]
            staged = STORE_DIR / f".staged-{os.getpid()}.xpi"
            try:
                meta = build_xpi(path, staged, forced_id=ext_id)
                profiles = target_profiles(state)
                if not profiles:
                    raise ZenExtError(_("No Zen profile found. Start Zen at least once or set the profile: "
                                        "zen-ext setup --profile PATH"))
                if meta["id"] not in state["extensions"] and not replace:
                    for p in profiles:
                        if installed_path(p, meta["id"]).exists():
                            raise ZenExtError(
                                _("{ext_id} is already installed in Zen (e.g. from the store). "
                                  "Remove it in Zen or add it with --replace", ext_id=meta["id"]))
                os.replace(staged, STORE_DIR / f"{meta['id']}.xpi")
            finally:
                staged.unlink(missing_ok=True)
            entry = {
                "id": meta["id"], "name": meta["name"], "version": meta["version"],
                "source": origin, "link": link,
                "added": state["extensions"].get(meta["id"], {}).get("added") or _now(),
                "updated": _now(), "notes": meta["notes"],
            }
            if link:
                entry["source_sig"] = source_signature(path)
            state["extensions"][meta["id"]] = entry
            for p in profiles:
                if not profile_configured(p):
                    configure_profile(p)
            deploy(meta["id"], profiles)
        if on_notes:
            for n in meta["notes"]:
                on_notes(n)
        return entry
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def rebuild(ext_id, state):
    """Repack a linked extension from its folder and redeploy. Caller holds the lock."""
    entry = state["extensions"][ext_id]
    folder = Path(entry["source"])
    if not folder.is_dir():
        raise ZenExtError(_("The source folder is gone: {path}", path=folder))
    staged = STORE_DIR / f".staged-{os.getpid()}.xpi"
    try:
        meta = build_xpi(folder, staged, forced_id=ext_id)
        os.replace(staged, STORE_DIR / f"{ext_id}.xpi")
    finally:
        staged.unlink(missing_ok=True)
    entry.update(name=meta["name"], version=meta["version"], notes=meta["notes"],
                 updated=_now(), source_sig=source_signature(folder))
    entry.pop("error", None)
    deploy(ext_id, target_profiles(state))
    return entry


def remove(query):
    with locked_state() as state:
        ext_id = find_entry(state, query)["id"]
        undeploy(ext_id, target_profiles(state))
        (STORE_DIR / f"{ext_id}.xpi").unlink(missing_ok=True)
        return state["extensions"].pop(ext_id)


def find_entry(state, query):
    exts = state["extensions"]
    if query in exts:
        return exts[query]
    hits = [e for e in exts.values() if query.lower() in e["name"].lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise ZenExtError(_("No such extension: {query}", query=query))
    raise ZenExtError(_("Several extensions match “{query}”: {names}",
                         query=query, names=", ".join(e["name"] for e in hits)))


def sync():
    """Rebuild linked folders and put every managed .xpi back into the profiles."""
    errors = []
    with locked_state() as state:
        profiles = target_profiles(state)
        for p in profiles:
            configure_profile(p)
        for ext_id, entry in state["extensions"].items():
            try:
                if entry.get("link"):
                    rebuild(ext_id, state)
                else:
                    deploy(ext_id, profiles)
            except (ZenExtError, OSError) as e:
                entry["error"] = str(e)
                errors.append(f"{entry['name']}: {e}")
    return errors


def set_profiles(paths):
    """Switch target profiles: configure new ones, clean up the dropped ones."""
    new = [profile_from_path(p) for p in paths]
    with locked_state() as state:
        old = target_profiles(state)
        new_keys = {p.key for p in new}
        dropped = [p for p in old if p.key not in new_keys]
        for ext_id in state["extensions"]:
            undeploy(ext_id, dropped)
        for p in dropped:
            unconfigure_profile(p)
        state["profiles"] = [p.key for p in new]
        for p in new:
            configure_profile(p)
        for ext_id in state["extensions"]:
            deploy(ext_id, new)
    return new


def purge():
    """Take every managed extension out of Zen and undo the user.js changes."""
    with locked_state() as state:
        profiles = target_profiles(state)
        for ext_id in state["extensions"]:
            undeploy(ext_id, profiles)
        for p in profiles:
            unconfigure_profile(p)
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    return profiles


def set_language(lang):
    """Save the interface language: one of i18n.LANGUAGES, or "auto" to follow the system."""
    with locked_state() as state:
        if lang in i18n.LANGUAGES:
            state["language"] = lang
        else:
            state.pop("language", None)
    i18n.use(lang)


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _tmp_root():
    d = DATA_DIR / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- status

STATUS_TEXT = {
    "active": "running",
    "pending": "will load after restarting Zen",
    "pending-update": "will update after restarting Zen",
    "disabled": "disabled in Zen",
    "incompatible": "Zen can't load it",
    "missing": "removed from the profile (zen-ext sync restores it)",
    "inactive": "not running",
}


def status_text(code):
    return _(STATUS_TEXT[code])


def zen_addons(profile):
    try:
        data = json.loads((profile.path / "extensions.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return {a["id"]: a for a in data.get("addons", []) if a.get("location") == "app-profile"}


def status(entry, profile, addons=None):
    f = installed_path(profile, entry["id"])
    if not f.exists():
        return "missing"
    info = (addons if addons is not None else zen_addons(profile)).get(entry["id"])
    if not info:
        return "pending"
    if info.get("version") != entry["version"] or abs(
            (info.get("updateDate") or 0) - f.stat().st_mtime * 1000) > 1000:
        return "pending-update"
    if info.get("userDisabled"):
        return "disabled"
    if info.get("appDisabled"):
        return "incompatible"
    return "active" if info.get("active") else "inactive"


def zen_running():
    try:
        out = subprocess.run(["flatpak", "ps", "--columns=application"],
                             capture_output=True, text=True, timeout=5).stdout
        if FLATPAK_ID in out.split():
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return subprocess.run(["pgrep", "-x", "(zen|zen-bin)"], capture_output=True,
                              timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
