"""Command line: zen-ext add|remove|list|sync|setup|profiles|language|watch|gui."""

import argparse
import sys

from . import core, i18n
from .i18n import _


def cmd_add(args):
    for source in args.sources:
        entry = core.add(source, link=args.link, ext_id=args.id, replace=args.replace,
                         on_notes=lambda n: print(f"  ! {n}"))
        fields = dict(name=entry["name"], version=entry["version"], ext_id=entry["id"])
        if entry["link"]:
            print(_("Added: {name} {version} ({ext_id}), linked to the folder, rebuilt automatically", **fields))
        else:
            print(_("Added: {name} {version} ({ext_id}), copied", **fields))
    _restart_hint()


def cmd_remove(args):
    for query in args.names:
        entry = core.remove(query)
        print(_("Removed: {name} ({ext_id})", name=entry["name"], ext_id=entry["id"]))
    _restart_hint()


def cmd_list(args):
    state = core.load_state()
    profiles = core.target_profiles(state)
    if not state["extensions"]:
        print(_("No extensions yet. Add one: zen-ext add PATH|URL"))
        return
    addons = {p.key: core.zen_addons(p) for p in profiles}
    for e in sorted(state["extensions"].values(), key=lambda e: e["name"].lower()):
        print(f"{e['name']} {e['version']}  [{e['id']}]")
        linked = "  " + _("(linked)") if e.get("link") else ""
        print("    " + _("source: {source}", source=e["source"]) + linked)
        for p in profiles:
            print(f"    {p.name}: {core.status_text(core.status(e, p, addons[p.key]))}")
        if e.get("error"):
            print("    " + _("build error: {error}", error=e["error"]))


def cmd_sync(args):
    errors = core.sync()
    for e in errors:
        print(_("Error: {error}", error=e), file=sys.stderr)
    print(_("Done") if not errors else _("Done, with errors"))
    _restart_hint()
    return 1 if errors else 0


def cmd_profiles(args):
    state = core.load_state()
    targets = {p.key for p in core.target_profiles(state)}
    for p in core.find_profiles():
        marks = []
        if p.default:
            marks.append(_("opens by default"))
        if p.key in targets:
            marks.append(_("in use") if core.profile_configured(p) else _("in use, not set up"))
        print(f"{p.name}{'  (' + ', '.join(marks) + ')' if marks else ''}\n    {p.path}")


def cmd_setup(args):
    if args.profile:
        profiles = core.set_profiles(args.profile)
    else:
        with core.locked_state() as state:
            profiles = core.target_profiles(state)
            if not profiles:
                raise core.ZenExtError(_("No Zen profile found. Set it: zen-ext setup --profile PATH"))
            for p in profiles:
                core.configure_profile(p)
    for p in profiles:
        print(_("Profile set up: {name} ({path})", name=p.name, path=p.path))
    _restart_hint()


def cmd_language(args):
    if args.lang:
        core.set_language(args.lang)
    name = i18n.LANGUAGES[i18n.current()]
    if core.load_state().get("language"):
        print(_("Language: {name}", name=name))
    else:
        print(_("Language: {name} (system default)", name=name))


def cmd_watch(args):
    from . import watch
    watch.run()


def cmd_gui(args):
    from . import gui
    return gui.main(args.files)


def _restart_hint():
    if core.zen_running():
        print(_("Zen is running: changes apply after it restarts."))


def main(argv=None):
    try:
        i18n.use(core.load_state().get("language"))
    except (OSError, ValueError):
        i18n.use()
    ap = argparse.ArgumentParser(
        prog="zen-ext",
        description=_("Your own and any other extensions in Zen without publishing them in a store. "
                      "Add one once, and Zen loads it on every start."))
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("add", help=_("add an extension: folder, .xpi, .zip, .crx or URL"))
    p.add_argument("sources", nargs="+", metavar=_("PATH|URL"))
    g = p.add_mutually_exclusive_group()
    g.add_argument("--link", dest="link", action="store_true", default=None,
                   help=_("watch the folder and rebuild on changes (default for folders)"))
    g.add_argument("--copy", dest="link", action="store_false",
                   help=_("take the folder as is, without watching"))
    p.add_argument("--id", help=_("your own ID if manifest.json has none"))
    p.add_argument("--replace", action="store_true",
                   help=_("replace an extension with the same ID already installed in Zen"))
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("remove", aliases=["rm"], help=_("remove an extension (by ID or name)"))
    p.add_argument("names", nargs="+", metavar=_("ID|NAME"))
    p.set_defaults(func=cmd_remove)

    sub.add_parser("list", aliases=["ls"], help=_("list extensions and their state in Zen")).set_defaults(func=cmd_list)
    sub.add_parser("sync", help=_("rebuild linked folders and put all files back into the profile")).set_defaults(func=cmd_sync)
    sub.add_parser("profiles", help=_("Zen profiles")).set_defaults(func=cmd_profiles)

    p = sub.add_parser("setup", help=_("enable loading unsigned extensions in the profile"))
    p.add_argument("--profile", action="append", metavar=_("PATH"),
                   help=_("profile folder, can be repeated. Without it, the profile Zen opens by default"))
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("language", aliases=["lang"],
                       help=_("interface language: en, ru or auto (follow the system)"))
    p.add_argument("lang", nargs="?", choices=["auto", *i18n.LANGUAGES])
    p.set_defaults(func=cmd_language)

    sub.add_parser("watch", help=_("background mode: rebuild linked folders")).set_defaults(func=cmd_watch)

    p = sub.add_parser("gui", help=_("app window"))
    p.add_argument("files", nargs="*", help=_("add these files right away"))
    p.set_defaults(func=cmd_gui)

    args = ap.parse_args(argv)
    if not args.cmd:
        args = ap.parse_args(["list"])
    try:
        return args.func(args) or 0
    except core.ZenExtError as e:
        print(_("Error: {error}", error=e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
