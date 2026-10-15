import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from schedule import display_seconds, format_elapsed, level, next_spawn  # noqa: E402

DEFAULT = [30, 45]


class NextSpawnTest(unittest.TestCase):
    def check(self, elapsed, number, remaining, intervals=DEFAULT):
        nxt = next_spawn(elapsed, intervals)
        self.assertEqual(nxt.number, number, f"elapsed={elapsed}")
        self.assertAlmostEqual(nxt.remaining, remaining, places=6, msg=f"elapsed={elapsed}")

    def test_first_spawn_at_30(self):
        self.check(0, 1, 30)
        self.check(12, 1, 18)
        self.check(29.9, 1, 0.1)

    def test_exact_spawn_rolls_over(self):
        # 湧いた瞬間は「次は 2 回目、残り 45 秒」。残り 0 を作らない
        self.check(30, 2, 45)
        self.check(75, 3, 45)
        self.check(120, 4, 45)

    def test_then_every_45(self):
        self.check(30.1, 2, 44.9)
        self.check(74.9, 2, 0.1)
        self.check(116.5, 3, 3.5)
        self.check(30 + 45 * 100 + 1, 102, 44)

    def test_single_interval_repeats_from_start(self):
        self.check(0, 1, 45, [45])
        self.check(45, 2, 45, [45])
        self.check(100, 3, 35, [45])

    def test_longer_prefix(self):
        # 10 → 20 → 以後 30 ごと: 10, 30, 60, 90 …
        self.check(5, 1, 5, [10, 20, 30])
        self.check(10, 2, 20, [10, 20, 30])
        self.check(30, 3, 30, [10, 20, 30])
        self.check(89, 4, 1, [10, 20, 30])

    def test_negative_elapsed_is_start(self):
        self.check(-3, 1, 30)

    def test_float_boundary_never_reaches_zero(self):
        # 0.1 を積み上げた値は 75.0 ちょうどにならない。境界で残り 0 や 46 にならないこと
        t = 0.0
        for _ in range(750):
            t += 0.1
        nxt = next_spawn(t, DEFAULT)
        self.assertGreater(nxt.remaining, 0)
        self.assertLessEqual(display_seconds(nxt.remaining), 45)

    def test_empty_intervals(self):
        with self.assertRaises(ValueError):
            next_spawn(0, [])


class DisplayTest(unittest.TestCase):
    def test_display_rounds_up(self):
        self.assertEqual(display_seconds(30), 30)
        self.assertEqual(display_seconds(29.99), 30)
        self.assertEqual(display_seconds(0.3), 1)
        self.assertEqual(display_seconds(45.0000001), 45)

    def test_level(self):
        self.assertEqual(level(10.1, 10, 5), "normal")
        self.assertEqual(level(10, 10, 5), "warn")
        self.assertEqual(level(5.01, 10, 5), "warn")
        self.assertEqual(level(5, 10, 5), "danger")
        self.assertEqual(level(0.2, 10, 5), "danger")

    def test_format_elapsed(self):
        self.assertEqual(format_elapsed(0), "00:00")
        self.assertEqual(format_elapsed(108.7), "01:48")
        self.assertEqual(format_elapsed(3725), "1:02:05")


if __name__ == "__main__":
    unittest.main()
