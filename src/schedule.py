"""湧き時刻の計算。

intervals は「開始から 1 回目まで」「1 回目から 2 回目まで」… の秒数で、
**最後の値を以後ずっと繰り返す**。既定の [30, 45] なら 30, 75, 120, 165 … 秒に湧く。

ちょうど湧いた瞬間 (経過 30.0 秒など) は「次は 2 回目、残り 45 秒」として扱う。
残りが 0 になる瞬間を作らないので、表示は 1 → 45 と途切れずに繰り越す。

Tk を import しないこと (テストと tools/ から単体で使う)。
"""

import math
from dataclasses import dataclass

# 浮動小数の誤差で 45.0000001 を 46 と切り上げないための余裕
_EPS = 1e-6


@dataclass(frozen=True)
class NextSpawn:
    number: int        # 次に湧くのが何回目か (1 始まり)
    remaining: float   # 次の湧きまでの秒数 (0 < remaining <= その区間の長さ)


def next_spawn(elapsed, intervals):
    """経過秒 elapsed のときの、次の湧きを返す。"""
    if not intervals:
        raise ValueError("intervals が空です")
    elapsed = max(0.0, float(elapsed))

    # 先頭から最後の 1 つ手前までは、1 回ずつ並べて探す
    t = 0.0
    for i, step in enumerate(intervals[:-1]):
        t += step
        if elapsed < t:
            return NextSpawn(i + 1, t - elapsed)

    # ここからは最後の値の繰り返し。t がその起点
    last = intervals[-1]
    k = math.floor((elapsed - t) / last)
    number = len(intervals) + k
    remaining = t + (k + 1) * last - elapsed
    if remaining <= _EPS:          # 割り算の誤差で境界の手前に落ちたとき
        number += 1
        remaining += last
    return NextSpawn(number, remaining)


def display_seconds(remaining):
    """画面に出す残り秒 (切り上げの整数)。残り 0.3 秒なら 1。"""
    return max(0, math.ceil(remaining - _EPS))


def level(remaining, warn_sec, danger_sec):
    """残り秒から色の段階を決める: 'danger' / 'warn' / 'normal'。"""
    if remaining <= danger_sec:
        return "danger"
    if remaining <= warn_sec:
        return "warn"
    return "normal"


def format_elapsed(seconds):
    """経過秒を MM:SS (1 時間を超えたら H:MM:SS) にする。"""
    s = int(max(0.0, seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"
