"""Interface language: English, with a Russian translation.

Strings in the code are English and double as keys into RU. The language is
ZEN_EXT_LANG if set, else the choice saved with `zen-ext language`, else the
system locale. Anything other than Russian falls back to English.
"""

import os

LANGUAGES = {"en": "English", "ru": "Русский"}

_current = None


def system_language():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return "ru" if value.lower().startswith("ru") else "en"
    return "en"


def use(saved=None):
    """Pick the language; `saved` is the stored choice (None or "auto" follow the system)."""
    global _current
    for choice in (os.environ.get("ZEN_EXT_LANG"), saved):
        if choice in LANGUAGES:
            _current = choice
            return
    _current = system_language()


def current():
    if _current is None:
        use()
    return _current


def _(text, **fields):
    if current() == "ru":
        text = RU.get(text, text)
    return text.format(**fields) if fields else text


RU = {
    # core
    "Profile folder not found: {path}": "Папка профиля не найдена: {path}",
    "No manifest.json in the folder: {path}": "В папке нет manifest.json: {path}",
    "Not an extension (.xpi, .zip, .crx): {path}": "Это не расширение (.xpi, .zip, .crx): {path}",
    "No manifest.json in the archive: {path}": "В архиве нет manifest.json: {path}",
    "Unknown CRX version: {version}": "Неизвестная версия CRX: {version}",
    "Error in {what}: {error}": "Ошибка в {what}: {error}",
    "The ID in manifest.json ({ext_id}) doesn't match the one given ({forced_id})":
        "ID в manifest.json ({ext_id}) не совпадает с указанным ({forced_id})",
    "manifest.json had no ID, assigned {ext_id}": "В manifest.json не было ID, назначен {ext_id}",
    "Invalid extension ID: {ext_id}": "Недопустимый ID расширения: {ext_id}",
    "The Chrome service worker is loaded as a background script: "
    "importScripts() and other worker APIs don't work in Zen":
        "Chrome service worker подключён как фоновый скрипт: "
        "importScripts() и другие API воркеров в Zen не работают",
    "Couldn't download {url}: {error}": "Не удалось скачать {url}: {error}",
    "The link isn't an extension (not .xpi/.zip or .crx): {url}":
        "По ссылке не расширение (ни .xpi/.zip, ни .crx): {url}",
    "Couldn't find the file on addons.mozilla.org: {error}":
        "Не удалось найти файл на addons.mozilla.org: {error}",
    "Not found: {path}": "Не найдено: {path}",
    "Only a source folder can be linked": "Связать можно только папку с исходниками",
    "No Zen profile found. Start Zen at least once or set the profile: "
    "zen-ext setup --profile PATH":
        "Профиль Zen не найден. Запусти Zen хотя бы раз или укажи профиль: "
        "zen-ext setup --profile ПУТЬ",
    "{ext_id} is already installed in Zen (e.g. from the store). "
    "Remove it in Zen or add it with --replace":
        "{ext_id} уже установлено в Zen (например, из магазина). "
        "Удали его в Zen или добавь с заменой (--replace)",
    "The source folder is gone: {path}": "Папка исходников пропала: {path}",
    "No such extension: {query}": "Нет такого расширения: {query}",
    "Several extensions match “{query}”: {names}": "Под «{query}» подходит несколько: {names}",
    "running": "работает",
    "will load after restarting Zen": "загрузится после перезапуска Zen",
    "will update after restarting Zen": "обновится после перезапуска Zen",
    "disabled in Zen": "выключено в Zen",
    "Zen can't load it": "Zen не может его загрузить",
    "removed from the profile (zen-ext sync restores it)": "удалено из профиля (zen-ext sync вернёт)",
    "not running": "не запущено",

    # cli
    "Added: {name} {version} ({ext_id}), linked to the folder, rebuilt automatically":
        "Добавлено: {name} {version} ({ext_id}), связано с папкой, пересобирается само",
    "Added: {name} {version} ({ext_id}), copied": "Добавлено: {name} {version} ({ext_id}), скопировано",
    "Removed: {name} ({ext_id})": "Удалено: {name} ({ext_id})",
    "No extensions yet. Add one: zen-ext add PATH|URL": "Расширений пока нет. Добавь: zen-ext add ПУТЬ|ССЫЛКА",
    "source: {source}": "источник: {source}",
    "(linked)": "(связано)",
    "build error: {error}": "ошибка сборки: {error}",
    "Error: {error}": "Ошибка: {error}",
    "Done": "Готово",
    "Done, with errors": "Готово, с ошибками",
    "opens by default": "открывается по умолчанию",
    "in use": "используется",
    "in use, not set up": "используется, не настроен",
    "No Zen profile found. Set it: zen-ext setup --profile PATH":
        "Профиль Zen не найден. Укажи его: zen-ext setup --profile ПУТЬ",
    "Profile set up: {name} ({path})": "Профиль настроен: {name} ({path})",
    "Language: {name}": "Язык: {name}",
    "Language: {name} (system default)": "Язык: {name} (как в системе)",
    "Zen is running: changes apply after it restarts.": "Zen запущен: изменения применятся после его перезапуска.",
    "Your own and any other extensions in Zen without publishing them in a store. "
    "Add one once, and Zen loads it on every start.":
        "Свои и любые другие расширения в Zen без публикации в магазине. "
        "Добавь один раз, дальше Zen загружает их сам при каждом запуске.",
    "add an extension: folder, .xpi, .zip, .crx or URL":
        "добавить расширение: папка, .xpi, .zip, .crx или ссылка",
    "PATH|URL": "ПУТЬ|ССЫЛКА",
    "watch the folder and rebuild on changes (default for folders)":
        "следить за папкой и пересобирать при изменениях (для папок по умолчанию)",
    "take the folder as is, without watching": "взять папку как есть, без слежения",
    "your own ID if manifest.json has none": "свой ID, если в manifest.json его нет",
    "replace an extension with the same ID already installed in Zen":
        "заменить уже установленное в Zen расширение с тем же ID",
    "remove an extension (by ID or name)": "удалить расширение (по ID или имени)",
    "ID|NAME": "ID|ИМЯ",
    "list extensions and their state in Zen": "список и состояние в Zen",
    "rebuild linked folders and put all files back into the profile":
        "пересобрать связанные папки и вернуть все файлы в профиль",
    "Zen profiles": "профили Zen",
    "enable loading unsigned extensions in the profile":
        "включить загрузку неподписанных расширений в профиле",
    "PATH": "ПУТЬ",
    "profile folder, can be repeated. Without it, the profile Zen opens by default":
        "папка профиля; можно несколько раз. Без него — профиль Zen по умолчанию",
    "background mode: rebuild linked folders": "фоновый режим: пересборка связанных папок",
    "app window": "окно программы",
    "add these files right away": "сразу добавить эти файлы",
    "interface language: en, ru or auto (follow the system)":
        "язык интерфейса: en, ru или auto (как в системе)",

    # gui
    "Zen Extensions": "Расширения Zen",
    "File (.xpi, .zip, .crx)…": "Файл (.xpi, .zip, .crx)…",
    "Source Folder…": "Папка с исходниками…",
    "From URL…": "По ссылке…",
    "Add extension": "Добавить расширение",
    "Zen Profiles…": "Профили Zen…",
    "Zen Profiles": "Профили Zen",
    "Reapply Everything": "Применить всё заново",
    "Data Folder": "Папка с данными",
    "Language": "Язык",
    "System Default": "Как в системе",
    "Menu": "Меню",
    "Drop an Extension Here": "Перетащи расширение сюда",
    "An .xpi, .zip or .crx file, a folder with manifest.json, or a link. "
    "Add it once, and Zen loads it on every start.":
        "Файл .xpi, .zip или .crx, папку с manifest.json или ссылку. "
        "Добавить нужно один раз: дальше Zen сам загружает его при каждом запуске.",
    "No Zen profile found. Start Zen at least once.": "Профиль Zen не найден. Запусти Zen хотя бы раз.",
    "The Zen profile isn't set up for your own extensions yet.":
        "Профиль Zen ещё не настроен для своих расширений.",
    "Set Up": "Настроить",
    "Restart Zen to apply the changes.": "Перезапусти Zen, чтобы применить изменения.",
    "Installed": "Установленные",
    "watches the folder": "следит за папкой",
    "Open source folder": "Открыть папку источника",
    "Rebuild now": "Пересобрать сейчас",
    "Remove": "Удалить",
    "Added: {name} {version}": "Добавлено: {name} {version}",
    "Added: {name} {version}, folder changes are picked up automatically":
        "Добавлено: {name} {version}, изменения в папке подхватываются сами",
    "Choose an Extension": "Выбери расширение",
    "Extensions (.xpi, .zip, .crx)": "Расширения (.xpi, .zip, .crx)",
    "Folder with manifest.json": "Папка с manifest.json",
    "Add from URL": "Добавить по ссылке",
    "A direct link to an .xpi/.crx, or an addons.mozilla.org / Chrome Web Store page.":
        "Прямая ссылка на .xpi/.crx или страница addons.mozilla.org / Chrome Web Store.",
    "Cancel": "Отмена",
    "Add": "Добавить",
    "Downloading…": "Скачиваю…",
    "Remove “{name}”?": "Удалить «{name}»?",
    "The extension disappears from Zen after a restart. Its data in Zen is deleted too.":
        "Расширение пропадёт из Zen после перезапуска. Его данные в Zen тоже удалятся.",
    "Removed: {name}": "Удалено: {name}",
    "Rebuilt: {name}": "Пересобрано: {name}",
    "Done. Restart Zen.": "Готово. Перезапусти Zen.",
    "All extensions are in place": "Все расширения на месте",
    "Where to install extensions. Usually the profile Zen opens by default is enough.":
        "Куда ставить расширения. Обычно достаточно профиля, который Zen открывает по умолчанию.",
    "default": "по умолчанию",
    "Save": "Сохранить",
    "Select at least one profile": "Нужен хотя бы один профиль",
    "Profiles saved. Restart Zen.": "Профили сохранены. Перезапусти Zen.",
    "Something Went Wrong": "Не получилось",
    "OK": "Понятно",

    # watch
    "zen-ext watch: watching linked folders": "zen-ext watch: слежу за связанными папками",
    "Rebuilt: {name} {version}": "Пересобрано: {name} {version}",
}
