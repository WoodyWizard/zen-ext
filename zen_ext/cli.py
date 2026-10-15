"""Command line: zen-ext add|remove|list|sync|setup|profiles|watch|gui."""

import argparse
import sys

from . import core


def cmd_add(args):
    for source in args.sources:
        entry = core.add(source, link=args.link, ext_id=args.id, replace=args.replace,
                         on_notes=lambda n: print(f"  ! {n}"))
        how = "связано с папкой, пересобирается само" if entry["link"] else "скопировано"
        print(f"Добавлено: {entry['name']} {entry['version']} ({entry['id']}), {how}")
    _restart_hint()


def cmd_remove(args):
    for query in args.names:
        entry = core.remove(query)
        print(f"Удалено: {entry['name']} ({entry['id']})")
    _restart_hint()


def cmd_list(args):
    state = core.load_state()
    profiles = core.target_profiles(state)
    if not state["extensions"]:
        print("Расширений пока нет. Добавь: zen-ext add ПУТЬ|ССЫЛКА")
        return
    addons = {p.key: core.zen_addons(p) for p in profiles}
    for e in sorted(state["extensions"].values(), key=lambda e: e["name"].lower()):
        print(f"{e['name']} {e['version']}  [{e['id']}]")
        print(f"    источник: {e['source']}{'  (связано)' if e.get('link') else ''}")
        for p in profiles:
            st = core.STATUS_TEXT[core.status(e, p, addons[p.key])]
            print(f"    {p.name}: {st}")
        if e.get("error"):
            print(f"    ошибка сборки: {e['error']}")


def cmd_sync(args):
    errors = core.sync()
    for e in errors:
        print(f"Ошибка: {e}", file=sys.stderr)
    print("Готово" if not errors else "Готово, с ошибками")
    _restart_hint()
    return 1 if errors else 0


def cmd_profiles(args):
    state = core.load_state()
    targets = {p.key for p in core.target_profiles(state)}
    for p in core.find_profiles():
        marks = []
        if p.default:
            marks.append("открывается по умолчанию")
        if p.key in targets:
            marks.append("используется" + ("" if core.profile_configured(p) else ", не настроен"))
        print(f"{p.name}{'  (' + ', '.join(marks) + ')' if marks else ''}\n    {p.path}")


def cmd_setup(args):
    if args.profile:
        profiles = core.set_profiles(args.profile)
    else:
        with core.locked_state() as state:
            profiles = core.target_profiles(state)
            if not profiles:
                raise core.ZenExtError("Профиль Zen не найден. Укажи его: zen-ext setup --profile ПУТЬ")
            for p in profiles:
                core.configure_profile(p)
    for p in profiles:
        print(f"Профиль настроен: {p.name} ({p.path})")
    _restart_hint()


def cmd_watch(args):
    from . import watch
    watch.run()


def cmd_gui(args):
    from . import gui
    return gui.main(args.files)


def _restart_hint():
    if core.zen_running():
        print("Zen запущен: изменения применятся после его перезапуска.")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="zen-ext",
        description="Свои и любые другие расширения в Zen без публикации в магазине. "
                    "Добавь один раз, дальше Zen загружает их сам при каждом запуске.")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("add", help="добавить расширение: папка, .xpi, .zip, .crx или ссылка")
    p.add_argument("sources", nargs="+", metavar="ПУТЬ|ССЫЛКА")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--link", dest="link", action="store_true", default=None,
                   help="следить за папкой и пересобирать при изменениях (для папок по умолчанию)")
    g.add_argument("--copy", dest="link", action="store_false",
                   help="взять папку как есть, без слежения")
    p.add_argument("--id", help="свой ID, если в manifest.json его нет")
    p.add_argument("--replace", action="store_true",
                   help="заменить уже установленное в Zen расширение с тем же ID")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("remove", aliases=["rm"], help="удалить расширение (по ID или имени)")
    p.add_argument("names", nargs="+", metavar="ID|ИМЯ")
    p.set_defaults(func=cmd_remove)

    sub.add_parser("list", aliases=["ls"], help="список и состояние в Zen").set_defaults(func=cmd_list)
    sub.add_parser("sync", help="пересобрать связанные папки и вернуть все файлы в профиль").set_defaults(func=cmd_sync)
    sub.add_parser("profiles", help="профили Zen").set_defaults(func=cmd_profiles)

    p = sub.add_parser("setup", help="включить загрузку неподписанных расширений в профиле")
    p.add_argument("--profile", action="append", metavar="ПУТЬ",
                   help="папка профиля; можно несколько раз. Без него — профиль Zen по умолчанию")
    p.set_defaults(func=cmd_setup)

    sub.add_parser("watch", help="фоновый режим: пересборка связанных папок").set_defaults(func=cmd_watch)

    p = sub.add_parser("gui", help="окно программы")
    p.add_argument("files", nargs="*", help="сразу добавить эти файлы")
    p.set_defaults(func=cmd_gui)

    args = ap.parse_args(argv)
    if not args.cmd:
        args = ap.parse_args(["list"])
    try:
        return args.func(args) or 0
    except core.ZenExtError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
