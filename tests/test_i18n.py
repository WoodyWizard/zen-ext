import ast
import os
import string
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from zen_ext import core, i18n  # noqa: E402


def ui_strings():
    """Every literal passed to _() in the package, plus the status texts."""
    found = set(core.STATUS_TEXT.values())
    for f in (ROOT / "zen_ext").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                found.add(node.args[0].value)
    return found


def fields(text):
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name}


class Translations(unittest.TestCase):
    def test_every_string_has_russian(self):
        strings = ui_strings()
        self.assertGreater(len(strings), 50)
        missing = sorted(s for s in strings if s not in i18n.RU)
        self.assertEqual(missing, [])

    def test_no_unused_translations(self):
        self.assertEqual(sorted(set(i18n.RU) - ui_strings()), [])

    def test_placeholders_match(self):
        for en, ru in i18n.RU.items():
            self.assertEqual(fields(en), fields(ru), en)


class Language(unittest.TestCase):
    def setUp(self):
        self._env = {k: os.environ.get(k) for k in
                     ("ZEN_EXT_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")}
        for k in self._env:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        i18n.use()

    def test_english_by_default(self):
        os.environ["LANG"] = "de_DE.UTF-8"
        i18n.use()
        self.assertEqual(i18n._("Removed: {name}", name="X"), "Removed: X")

    def test_russian_locale(self):
        os.environ["LANG"] = "ru_RU.UTF-8"
        i18n.use()
        self.assertEqual(i18n._("Removed: {name}", name="X"), "Удалено: X")

    def test_saved_choice_beats_locale(self):
        os.environ["LANG"] = "en_US.UTF-8"
        i18n.use("ru")
        self.assertEqual(i18n.current(), "ru")
        i18n.use("auto")
        self.assertEqual(i18n.current(), "en")

    def test_env_beats_saved_choice(self):
        os.environ["ZEN_EXT_LANG"] = "en"
        i18n.use("ru")
        self.assertEqual(i18n.current(), "en")


if __name__ == "__main__":
    unittest.main()
