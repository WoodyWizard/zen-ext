"""End-to-end check against the real Zen, in a throwaway profile.

Starts Zen headless three times with the profile in .dev/e2e:
  1. unsigned extensions without IDs (a linked folder and a Chrome-style
     MV3 .crx with a service worker) must load and run their background code;
  2. after the linked folder changes, the new version must load;
  3. after removal, the extension must be gone.
Background scripts prove they ran by requesting http://127.0.0.1:<port>/<tag>.
Your own Zen profile and a running Zen are not touched.
"""

import http.server
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".dev/e2e"
PROFILE = WORK / "profile"
os.environ["ZEN_EXT_HOME"] = str(WORK / "data")
sys.path.insert(0, str(ROOT))

from zen_ext import core  # noqa: E402

hits = []


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(self.path.strip("/"))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


def write_ext(folder, manifest, bg_name, tag, port):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (folder / bg_name).write_text(f'fetch("http://127.0.0.1:{port}/{tag}").catch(() => {{}});\n')


LOG = WORK / "zen.log"


def run_zen(expect, timeout=60):
    hits.clear()
    with open(LOG, "a") as log:
        proc = subprocess.Popen(
            ["flatpak", "run", core.FLATPAK_ID, "--headless", "--no-remote", "--profile", str(PROFILE)],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.time() + timeout
    while time.time() < deadline and not set(expect) <= set(hits):
        if proc.poll() is not None and not (PROFILE / "prefs.js").exists():
            break  # Zen exited without even creating the profile
        time.sleep(0.5)
    time.sleep(3)  # let Zen flush extensions.json
    stop_zen(proc)
    if not (PROFILE / "prefs.js").exists():
        tail = LOG.read_text(errors="replace").strip().splitlines()[-15:]
        print("FAIL Zen didn't start with the test profile, extensions were never reached.")
        print(f"     Zen output ({LOG}):")
        for line in tail or ["(empty)"]:
            print("     | " + line)
        if any("bwrap" in line for line in tail):
            print("     Looks like a shell sandbox: run the test in a regular terminal, not via \"!\".")
        sys.exit(2)
    return list(hits)


def stop_zen(proc):
    # Only processes started for the test profile; the user's Zen stays alive.
    out = subprocess.run(["pgrep", "-f", str(PROFILE)], capture_output=True, text=True).stdout
    for pid in map(int, out.split()):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
    time.sleep(1)


def addons():
    return {k: (v["version"], v["active"]) for k, v in core.zen_addons(core.Profile("e2e", PROFILE, False)).items()}


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        sys.exit(1)


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    PROFILE.mkdir(parents=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    dev = WORK / "src/dev-ext"
    write_ext(dev, {"manifest_version": 2, "name": "E2E Dev", "version": "1.0",
                    "background": {"scripts": ["bg.js"]}}, "bg.js", "dev-1.0", port)
    chrome = WORK / "src/chrome-ext"
    write_ext(chrome, {"manifest_version": 3, "name": "E2E Chrome", "version": "5.0",
                       "background": {"service_worker": "sw.js"}}, "sw.js", "chrome-5.0", port)
    zipped = WORK / "chrome.zip"
    with zipfile.ZipFile(zipped, "w") as z:
        for f in chrome.iterdir():
            z.write(f, f.name)
    crx = WORK / "chrome.crx"
    crx.write_bytes(b"Cr24" + struct.pack("<II", 3, 0) + zipped.read_bytes())

    core.set_profiles([PROFILE])
    core.add(dev)
    core.add(crx)

    got = run_zen(["dev-1.0", "chrome-5.0"])
    if "dev-1.0" not in got:
        print(f"     Extensions in Zen: {addons()}")
    check("dev-1.0" in got, "unsigned folder without an ID loaded and its background runs")
    check("chrome-5.0" in got, "Chrome .crx with a service worker loaded and runs")
    a = addons()
    check(a.get("e2e-dev@zen-ext.local") == ("1.0", True), f"extensions.json: {a}")
    state = core.load_state()
    check(all(core.status(e, core.Profile("e2e", PROFILE, False)) == "active"
              for e in state["extensions"].values()), "zen-ext sees both as active")

    write_ext(dev, {"manifest_version": 2, "name": "E2E Dev", "version": "1.1",
                    "background": {"scripts": ["bg.js"]}}, "bg.js", "dev-1.1", port)
    from zen_ext import watch
    pending = {}
    watch.tick(pending)
    watch.tick(pending)
    got = run_zen(["dev-1.1", "chrome-5.0"])
    check("dev-1.1" in got and "dev-1.0" not in got, "after editing the folder, the new version loaded")
    check(addons().get("e2e-dev@zen-ext.local") == ("1.1", True), "Zen has version 1.1")

    core.remove("e2e-chrome@zen-ext.local")
    got = run_zen(["dev-1.1"])
    time.sleep(2)
    check("chrome-5.0" not in got, "the removed extension no longer runs")
    check("e2e-chrome@zen-ext.local" not in addons(), "and is gone from Zen")
    print("All checks passed")


if __name__ == "__main__":
    main()
