import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from config import DEFAULTS, RANGES, Config  # noqa: E402


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def read(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_missing_file_is_created_with_defaults(self):
        cfg = Config(self.path).load()
        self.assertEqual(cfg.values, DEFAULTS)
        self.assertEqual(cfg.warnings, [])
        self.assertEqual(self.read(), DEFAULTS)

    def test_valid_values_are_used(self):
        self.write({"first_sec": 45, "interval_sec": 60, "hotkey_start": "ctrl+F9",
                    "scale": 70, "opacity": 50, "show_buttons": False, "x": -1200, "y": 300})
        cfg = Config(self.path).load()
        self.assertEqual((cfg["first_sec"], cfg["interval_sec"]), (45, 60))
        self.assertEqual(cfg["hotkey_start"], "ctrl+F9")
        self.assertEqual((cfg["scale"], cfg["opacity"], cfg["show_buttons"]), (70, 50, False))
        self.assertEqual((cfg["x"], cfg["y"]), (-1200, 300))     # サブモニタの負の座標
        self.assertEqual(cfg["warn_sec"], DEFAULTS["warn_sec"])  # 書いていないキーは初期値
        self.assertEqual(cfg.warnings, [])

    def test_bad_values_fall_back_with_warning(self):
        self.write({"first_sec": 0, "warn_sec": "10", "hotkey_stop": "F99",
                    "opacity": 10, "show_buttons": 1, "x": 1.5})
        cfg = Config(self.path).load()
        for key in ("first_sec", "warn_sec", "hotkey_stop", "opacity", "show_buttons", "x"):
            self.assertEqual(cfg[key], DEFAULTS[key], key)
        self.assertEqual(len(cfg.warnings), 6)

    def test_duplicate_hotkeys_are_fixed(self):
        self.write({"hotkey_start": "F7", "hotkey_repeat": "f7"})
        cfg = Config(self.path).load()
        self.assertEqual(cfg["hotkey_start"], "F7")
        self.assertEqual(cfg["hotkey_repeat"], DEFAULTS["hotkey_repeat"])
        self.assertEqual(len(cfg.warnings), 1)

    def test_bom_is_accepted(self):
        # Windows のメモ帳は BOM 付きで保存することがある
        with open(self.path, "w", encoding="utf-8-sig") as f:
            f.write(json.dumps({"warn_sec": 8}))
        self.assertEqual(Config(self.path).load()["warn_sec"], 8)

    def test_broken_json_uses_defaults_then_save_repairs(self):
        self.write('{"first_sec": 30,')      # 書きかけ
        cfg = Config(self.path).load()
        self.assertEqual(cfg.values, DEFAULTS)
        self.assertEqual(len(cfg.warnings), 1)
        cfg["first_sec"] = 20
        self.assertTrue(cfg.save())
        self.assertEqual(cfg.warnings, [])         # 直ったので警告は消える
        self.assertEqual(self.read()["first_sec"], 20)

    def test_setitem_validates(self):
        cfg = Config(self.path).load()
        cfg["interval_sec"] = 60
        self.assertEqual(cfg["interval_sec"], 60)
        for key, bad in (("interval_sec", 0), ("scale", 300), ("hotkey_stop", "F99"),
                         ("show_buttons", "yes")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                cfg[key] = bad

    def test_reset_keeps_position(self):
        cfg = Config(self.path).load()
        cfg["x"], cfg["y"] = 10, 20
        cfg["first_sec"] = 45
        cfg.reset()
        self.assertEqual(cfg["first_sec"], DEFAULTS["first_sec"])
        self.assertEqual((cfg["x"], cfg["y"]), (10, 20))

    def test_defaults_are_inside_ranges(self):
        for key, (lo, hi, step) in RANGES.items():
            self.assertTrue(lo <= DEFAULTS[key] <= hi, key)
            self.assertEqual((DEFAULTS[key] - lo) % step, 0, key)   # −/+ で初期値に戻れる


if __name__ == "__main__":
    unittest.main()
