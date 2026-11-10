"""
test_settings.py — settings.py: loading, validation, template, diff, remember.

Pure Python, no GTK. Run from the repo root inside the distrobox:
    python3 -m unittest discover -s tests -v
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import settings
from settings import (Settings, LayoutSettings, OsdSettings, load, template,
                      ensure_file, diff, settings_path)


class _TmpFile(unittest.TestCase):
    """Each test gets its own empty directory and a settings.toml path in it."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)
        self.path = self.dir / "settings.toml"

    def tearDown(self):
        os.chmod(self.dir, 0o700)
        self._dir.cleanup()

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def load_capturing(self, **kw):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = load(self.path, **kw)
        return result, err.getvalue()


class LoadTests(_TmpFile):

    def test_missing_file_gives_defaults(self):
        self.assertEqual(load(self.path), Settings())

    def test_empty_file_gives_defaults_without_warning(self):
        self.write("")
        result, err = self.load_capturing()
        self.assertEqual(result, Settings())
        self.assertEqual(err, "")

    def test_template_loads_to_defaults(self):
        self.write(template())
        result, err = self.load_capturing()
        self.assertEqual(result, Settings())
        self.assertEqual(err, "")
        text = template()
        self.assertIn('# design = "classic"', text)
        self.assertIn("# hold_ms = 1500", text)
        for header in ("[layout]", "[osd]", "[reveal]", "[debug]"):
            self.assertIn(header, text)

    def test_valid_values_apply(self):
        self.write('[layout]\ndesign = "split"\n[reveal]\nhold_ms = 900\n')
        result = load(self.path)
        self.assertEqual(result.layout.design, "split")
        self.assertEqual(result.reveal.hold_ms, 900)
        self.assertEqual(result.osd, Settings().osd)
        self.assertEqual(result.reveal.release_ms, 500)

    def test_wrong_type_falls_back_per_key(self):
        self.write('[osd]\nenabled = "yes"\n[reveal]\nhold_ms = 900\n')
        result, err = self.load_capturing()
        self.assertIs(result.osd.enabled, True)
        self.assertEqual(result.reveal.hold_ms, 900)
        self.assertIn("osd.enabled", err)

    def test_bool_is_not_int(self):
        self.write("[reveal]\nhold_ms = true\n")
        result, err = self.load_capturing()
        self.assertEqual(result.reveal.hold_ms, 1500)
        self.assertIn("reveal.hold_ms", err)

    def test_unknown_choice(self):
        self.write('[layout]\ndesign = "neu"\n')
        result, err = self.load_capturing()
        self.assertEqual(result.layout.design, "classic")
        self.assertIn("layout.design", err)

    def test_below_minimum(self):
        self.write("[reveal]\nhold_ms = -5\nfade_in_ms = 0\n")
        result, err = self.load_capturing()
        self.assertEqual(result.reveal.hold_ms, 1500)
        self.assertEqual(result.reveal.fade_in_ms, 200)
        self.assertIn("reveal.hold_ms", err)
        self.assertIn("reveal.fade_in_ms", err)

    def test_unknown_key_and_section_warn(self):
        self.write('[layout]\ndesgin = "split"\n[foo]\nx = 1\n')
        result, err = self.load_capturing()
        self.assertEqual(result, Settings())
        self.assertIn("layout.desgin", err)
        self.assertIn("foo", err)

    def test_syntax_error_uses_previous(self):
        self.write("[layout\n")
        previous = Settings(layout=LayoutSettings(design="split"))
        result, err = self.load_capturing(previous=previous)
        self.assertEqual(result, previous)
        self.assertIn("settings.toml", err)
        result, err = self.load_capturing()
        self.assertEqual(result, Settings())
        self.assertIn("settings.toml", err)


class FileTests(_TmpFile):

    def test_ensure_file_creates_template_once(self):
        ensure_file(self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), template())
        self.write("x")
        ensure_file(self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "x")

    def test_settings_path_respects_xdg(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/x"}):
            self.assertEqual(settings_path(), Path("/x/deckery-hud/settings.toml"))
        env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(settings_path(),
                             Path.home() / ".config" / "deckery-hud" / "settings.toml")


class RememberTests(_TmpFile):

    def remember_capturing(self, key, value):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = settings.remember(key, value, self.path)
        return result, err.getvalue()

    def text(self):
        return self.path.read_text(encoding="utf-8")

    def test_remember_keeps_comments_and_order(self):
        self.write(template().replace("[osd]\n", "[osd]\n# meine Notiz\n"))
        self.assertTrue(settings.remember("layout.design", "split", self.path))
        self.assertEqual(load(self.path).layout.design, "split")
        text = self.text()
        self.assertIn("# meine Notiz", text)
        self.assertIn('# design = "classic"', text)
        self.assertLess(text.index("[layout]"), text.index("[osd]"))

    def test_remember_creates_missing_file_from_template(self):
        self.assertTrue(settings.remember("layout.design", "split", self.path))
        text = self.text()
        self.assertIn("# Deckery HUD — Einstellungen.", text)
        self.assertIn('design = "split"', text)

    def test_remember_adds_missing_section(self):
        self.write("[osd]\nenabled = false\n")
        self.assertTrue(settings.remember("layout.design", "split", self.path))
        result = load(self.path)
        self.assertEqual(result.layout.design, "split")
        self.assertIs(result.osd.enabled, False)

    def test_remember_overwrites_existing_value(self):
        self.write("[osd]\nenabled = true\n")
        self.assertTrue(settings.remember("osd.enabled", False, self.path))
        self.assertIs(load(self.path).osd.enabled, False)
        self.assertEqual(self.text().count("enabled ="), 1)

    def test_remember_refuses_broken_file(self):
        self.write("[layout\n")
        before = self.path.read_bytes()
        result, err = self.remember_capturing("layout.design", "split")
        self.assertFalse(result)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn("settings.toml", err)

    def test_remember_rejects_invalid(self):
        for key, value in (("layout.design", "neu"), ("osd.enabled", 1), ("nope.x", 1),
                           ("layout.nope", "x")):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    settings.remember(key, value, self.path)

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_remember_unwritable_dir(self):
        os.chmod(self.dir, 0o500)
        result, err = self.remember_capturing("layout.design", "split")
        self.assertFalse(result)
        self.assertFalse(self.path.exists())
        self.assertNotEqual(err, "")

    def test_remember_without_tomlkit(self):
        with mock.patch.dict(sys.modules, {"tomlkit": None}):
            result, err = self.remember_capturing("layout.design", "split")
        self.assertFalse(result)
        self.assertIn("tomlkit", err)


class DiffTests(unittest.TestCase):

    def test_diff(self):
        self.assertEqual(diff(Settings(), Settings(osd=OsdSettings(enabled=False))),
                         {"osd.enabled"})
        self.assertEqual(diff(Settings(), Settings()), set())


if __name__ == "__main__":
    unittest.main()
