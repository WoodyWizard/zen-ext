"""Background watcher: rebuilds linked source folders when their files change.

Runs as the systemd user service zen-ext-watch. Extensions added from files
or URLs don't need it; Zen loads those from the profile on its own.
"""

import sys
import time

from . import core
from .i18n import _

POLL_SECONDS = 1.5


def log(msg):
    print(msg, flush=True)


def run():
    log(_("zen-ext watch: watching linked folders"))
    pending = {}  # ext_id -> signature seen on the previous tick
    while True:
        try:
            tick(pending)
        except Exception as e:  # keep the service alive, report and retry
            log(_("Error: {error}", error=e))
        time.sleep(POLL_SECONDS)


def tick(pending):
    state = core.load_state()
    for ext_id, entry in state["extensions"].items():
        if not entry.get("link"):
            continue
        try:
            sig = core.source_signature(entry["source"])
        except OSError:
            continue
        if sig == entry.get("source_sig"):
            pending.pop(ext_id, None)
            continue
        # Wait for one quiet tick so a half-saved file isn't packed.
        if pending.get(ext_id) != sig:
            pending[ext_id] = sig
            continue
        pending.pop(ext_id, None)
        with core.locked_state() as locked:
            if ext_id not in locked["extensions"]:
                continue
            try:
                e = core.rebuild(ext_id, locked)
                log(_("Rebuilt: {name} {version}", name=e["name"], version=e["version"]))
            except core.ZenExtError as err:
                # Remember the broken signature so it isn't retried every tick.
                locked["extensions"][ext_id].update(source_sig=sig, error=str(err))
                log(f"{entry['name']}: {err}")


if __name__ == "__main__":
    sys.exit(run())
