import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from hotkey import (CAPTURE_VKS, MOD_ALT, MOD_CONTROL, MOD_SHIFT, HotkeyPoller,  # noqa: E402
                    KeyCapture, label, name_for_vk, parse_hotkey, same_hotkey)


class ParseTest(unittest.TestCase):
    def test_function_keys(self):
        self.assertEqual(parse_hotkey("F9"), (0, 0x78))
        self.assertEqual(parse_hotkey("f10"), (0, 0x79))
        self.assertEqual(parse_hotkey("F1"), (0, 0x70))
        self.assertEqual(parse_hotkey("F24"), (0, 0x87))

    def test_modifiers(self):
        self.assertEqual(parse_hotkey("ctrl+shift+t"), (MOD_CONTROL | MOD_SHIFT, ord("T")))
        self.assertEqual(parse_hotkey("Alt + 1"), (MOD_ALT, ord("1")))

    def test_named_and_numpad(self):
        self.assertEqual(parse_hotkey("pause"), (0, 0x13))
        self.assertEqual(parse_hotkey("num5"), (0, 0x65))

    def test_invalid(self):
        for text in ("", "   ", "F25", "F0", "ctrl+", "+F9", "hyper+F9", "ctrl+shift", "ab", None, 9):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_hotkey(text)

    def test_label(self):
        self.assertEqual(label("f9"), "F9")
        self.assertEqual(label("ctrl+shift+t"), "Ctrl+Shift+T")
        self.assertEqual(label("shift+ctrl+f1"), "Ctrl+Shift+F1")
        self.assertEqual(label("bogus"), "bogus")

    def test_same_hotkey(self):
        self.assertTrue(same_hotkey("F9", "f9"))
        self.assertTrue(same_hotkey("ctrl+shift+t", "Shift+Ctrl+T"))
        self.assertFalse(same_hotkey("F9", "ctrl+F9"))
        self.assertFalse(same_hotkey("F99", "F99"))      # 読めないものは同じとみなさない


class NameForVkTest(unittest.TestCase):
    def test_every_capturable_key_round_trips(self):
        # 読み取ったキーは必ず設定として保存・登録できること
        for vk in CAPTURE_VKS:
            with self.subTest(vk=hex(vk)):
                self.assertEqual(parse_hotkey(name_for_vk(vk)), (0, vk))

    def test_names(self):
        self.assertEqual(name_for_vk(0x78), "F9")
        self.assertEqual(name_for_vk(0x65), "num5")
        self.assertEqual(name_for_vk(ord("T")), "T")
        self.assertEqual(name_for_vk(0x13), "pause")


class KeyCaptureTest(unittest.TestCase):
    def setUp(self):
        self.down = set()
        self.capture = None

    def start(self):
        self.capture = KeyCapture(is_down=lambda vk: vk in self.down)

    def test_waits_until_a_key_is_pressed(self):
        self.start()
        self.assertIsNone(self.capture.poll())
        self.down.add(0x79)                       # F10
        self.assertEqual(self.capture.poll(), ("key", "F10"))

    def test_modifiers_are_included(self):
        self.start()
        self.down.update({0x11, 0x10})            # Ctrl + Shift (修飾キーだけでは決まらない)
        self.assertIsNone(self.capture.poll())
        self.down.add(ord("T"))
        self.assertEqual(self.capture.poll(), ("key", "ctrl+shift+T"))

    def test_key_held_at_start_is_ignored_until_released(self):
        self.down.add(0x78)                       # 設定欄を開いた時点で F9 を押しっぱなし
        self.start()
        self.assertIsNone(self.capture.poll())
        self.down.discard(0x78)
        self.assertIsNone(self.capture.poll())
        self.down.add(0x78)
        self.assertEqual(self.capture.poll(), ("key", "F9"))

    def test_escape_cancels(self):
        self.start()
        self.down.add(0x1B)
        self.assertEqual(self.capture.poll(), ("cancel", None))


class HotkeyPollerTest(unittest.TestCase):
    BINDINGS = {"start": "F9", "repeat": "F10", "stop": "ctrl+F9"}

    def setUp(self):
        self.down = set()

    def make(self):
        return HotkeyPoller(self.BINDINGS, out_queue=None, is_down=lambda vk: vk in self.down)

    def test_fires_once_per_press(self):
        p = self.make()
        self.assertEqual(p.poll(), [])
        self.down.add(0x78)                       # F9 を押す
        self.assertEqual(p.poll(), ["start"])
        self.assertEqual(p.poll(), [])            # 押しっぱなしでは連打にならない
        self.down.discard(0x78)
        self.assertEqual(p.poll(), [])
        self.down.add(0x78)
        self.assertEqual(p.poll(), ["start"])

    def test_modifiers_must_match_exactly(self):
        p = self.make()
        self.down.update({0x11, 0x78})            # Ctrl+F9
        self.assertEqual(p.poll(), ["stop"])      # F9 単体 (start) は動かない
        self.down.clear()
        p.poll()
        self.down.update({0x10, 0x79})            # Shift+F10 は割り当てていない
        self.assertEqual(p.poll(), [])

    def test_key_held_at_start_is_ignored(self):
        self.down.add(0x79)
        p = self.make()
        self.assertEqual(p.poll(), [])
        self.down.discard(0x79)
        p.poll()
        self.down.add(0x79)
        self.assertEqual(p.poll(), ["repeat"])

    def test_bad_binding_is_reported(self):
        p = HotkeyPoller({"start": "F99", "stop": "F11"}, out_queue=None,
                         is_down=lambda vk: False)
        self.assertEqual(len(p.failures), 1)
        self.assertEqual([a for a, _m, _vk in p._keys], ["stop"])


if __name__ == "__main__":
    unittest.main()
