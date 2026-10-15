"""設定の保存先 (config.json)。

設定はタイマーの設定欄で変える。このファイルはその保存先で、手で書く必要は無い。
置き場所は exe なら exe の隣、ソースから動かすならフォルダ直下。
(PyInstaller の onefile は毎回一時フォルダへ展開されるので、__file__ の隣に
書くと終了のたびに消える。)

読めない値は既定値に戻して警告を返す。
"""

import json
import os
import sys

from hotkey import parse_hotkey, same_hotkey

DEFAULTS = {
    "first_sec": 30,          # 開始から 1 回目まで
    "interval_sec": 45,       # 以後の間隔
    "warn_sec": 10,           # 残りがこれ以下で黄色
    "danger_sec": 5,          # 残りがこれ以下で赤
    "hotkey_start": "F9",     # 初回から開始 (動作中はやり直し)
    "hotkey_repeat": "F10",   # 間隔から開始 (初回を飛ばす)
    "hotkey_stop": "F11",     # 停止
    "scale": 100,             # 大きさ (%)
    "opacity": 90,            # 不透明度 (%)
    "show_buttons": True,     # ボタン行を出すか
    "x": None,                # 窓の位置 (null なら画面右上寄り)
    "y": None,
}

# 設定欄の −/+ が動く範囲と刻み: (最小, 最大, 刻み)
RANGES = {
    "first_sec": (1, 600, 1),
    "interval_sec": (1, 600, 1),
    "warn_sec": (0, 60, 1),
    "danger_sec": (0, 60, 1),
    "scale": (60, 200, 10),
    "opacity": (30, 100, 5),
}

HOTKEY_KEYS = ("hotkey_start", "hotkey_repeat", "hotkey_stop")

# 警告に出す名前
LABELS = {
    "first_sec": "初回", "interval_sec": "以後の間隔", "warn_sec": "黄色",
    "danger_sec": "赤", "hotkey_start": "開始キー", "hotkey_repeat": "間隔から開始のキー",
    "hotkey_stop": "停止キー", "scale": "大きさ", "opacity": "不透明度",
    "show_buttons": "ボタン行", "x": "窓の位置", "y": "窓の位置",
}


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_path():
    return os.path.join(app_dir(), "config.json")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _valid(key, v):
    if key in RANGES:
        lo, hi, _step = RANGES[key]
        return _is_int(v) and lo <= v <= hi
    if key in HOTKEY_KEYS:
        try:
            parse_hotkey(v)
        except ValueError:
            return False
        return True
    if key == "show_buttons":
        return isinstance(v, bool)
    if key in ("x", "y"):
        return v is None or _is_int(v)
    return False


class Config:
    """設定値。values は常に全キーが揃った正しい値になっている。"""

    def __init__(self, path=None):
        self.path = path or default_path()
        self.values = dict(DEFAULTS)
        self.warnings = []

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        if not _valid(key, value):
            raise ValueError(f"{key} に {value!r} は設定できません")
        self.values[key] = value

    def load(self):
        """読み直す。ファイルが無ければ既定値で作る。"""
        self.values = dict(DEFAULTS)
        self.warnings = []

        if not os.path.exists(self.path):
            self.save()
            return self

        try:
            with open(self.path, encoding="utf-8-sig") as f:   # メモ帳の BOM 付きも読む
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("中身が { } ではありません")
        except (OSError, ValueError) as e:
            self.warnings.append(f"設定ファイルが読めないので初期値で動きます ({e})")
            return self

        for key in DEFAULTS:
            if key not in raw:
                continue
            if _valid(key, raw[key]):
                self.values[key] = raw[key]
            else:
                self.warnings.append(f"設定「{LABELS[key]}」が読めないので初期値に戻しました")

        # 同じキーが 2 つの操作に割り当たっていたら、後ろの方を初期値に戻す
        seen = []
        for key in HOTKEY_KEYS:
            if any(same_hotkey(self.values[key], s) for s in seen):
                self.warnings.append(f"「{LABELS[key]}」が他の操作と同じキーなので初期値に戻しました")
                self.values[key] = DEFAULTS[key]
            seen.append(self.values[key])
        return self

    def reset(self):
        """位置以外を初期値に戻す。"""
        x, y = self.values["x"], self.values["y"]
        self.values = dict(DEFAULTS, x=x, y=y)

    def save(self):
        """全部書き戻す。書けたら読み込み時の警告は消す (もう直っているので)。"""
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.values, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp, self.path)
        except OSError:
            # 書き込めない場所 (読み取り専用のフォルダなど) でも動作は続ける
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        self.warnings = []
        return True

