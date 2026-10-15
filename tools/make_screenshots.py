"""README 用のスクリーンショットを作る (見た目を変えたら撮り直す)。

    .venv\\Scripts\\python tools\\make_screenshots.py

時刻を止めた TimerApp を状態ごとに表示し、窓の範囲を撮って docs/images/ に保存する。
起動中のタイマーとぶつからないようにホットキーは登録せず、設定は一時ファイルを使う
(本物の config.json には触らない)。撮影中は窓がメイン画面の左上寄りに出る。
"""

import json
import os
import shutil
import sys
import tempfile
import time

from PIL import ImageGrab

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import overlay  # noqa: E402

OUT_DIR = os.path.join(ROOT, "docs", "images")

# (ファイル名, 経過秒 (None は待機中), 初回を飛ばすか)
STILLS = [
    ("idle.png", None, False),
    ("normal.png", 12.0, False),      # 残り 18 秒・1 回目待ち (白)
    ("warn.png", 66.0, False),        # 残り 9 秒・2 回目待ち (黄)
    ("danger.png", 116.5, False),     # 残り 3.5 秒 → 表示 4・3 回目待ち (赤)
    ("repeat.png", 20.0, True),       # 45 秒から: 残り 25 秒
]
# 残り 11 秒 → 1 秒 → 湧いて 45 秒へ繰り越す、までの 13 コマ
GIF_ELAPSED = [19.5 + i for i in range(13)]


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


class FrozenClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def show(app, clock, elapsed, skip_first=False):
    if elapsed is None:
        app.stop()
    else:
        app.start(skip_first)
        app.started_at = clock.now - elapsed
        app.render()
    app.root.update()
    time.sleep(0.2)                # 描画が画面に出るのを待つ
    app.root.update()


def grab(app):
    r = app.root
    r.update_idletasks()
    x, y = r.winfo_x(), r.winfo_y()
    return ImageGrab.grab(bbox=(x, y, x + r.winfo_width(), y + r.winfo_height()))


def save(app, name):
    path = os.path.join(OUT_DIR, name)
    grab(app).save(path)
    print(f"wrote {path}")


def main():
    overlay.enable_dpi_awareness()
    os.makedirs(OUT_DIR, exist_ok=True)

    tmp = tempfile.mkdtemp()
    try:
        cfg = os.path.join(tmp, "config.json")
        # 不透明にして撮る (半透明だと後ろのウィンドウが写り込む)
        base = {"opacity": 100, "x": 200, "y": 200}
        write_json(cfg, base)

        clock = FrozenClock()
        app = overlay.TimerApp(config_path=cfg, clock=clock, hotkeys=False)

        for name, elapsed, skip_first in STILLS:
            show(app, clock, elapsed, skip_first)
            save(app, name)

        # ボタン行を隠した最小の形
        app.config["show_buttons"] = False
        app.setting_changed("show_buttons")
        show(app, clock, 12.0)
        save(app, "compact.png")
        app.config["show_buttons"] = True
        app.setting_changed("show_buttons")

        # 設定欄を開いたところ
        app.open_settings()
        show(app, clock, 12.0)
        save(app, "settings.png")
        app.close_settings()

        frames = []
        for elapsed in GIF_ELAPSED:
            show(app, clock, elapsed)
            frames.append(grab(app).convert("P", palette=1, colors=64))
        path = os.path.join(OUT_DIR, "demo.gif")
        frames[0].save(path, save_all=True, append_images=frames[1:],
                       duration=1000, loop=0, optimize=True)
        print(f"wrote {path}")

        # 設定ファイルが読めないときの表示 (存在しないキー F99)
        write_json(cfg, dict(base, hotkey_stop="F99"))
        app.reload_config()
        show(app, clock, None)
        save(app, "notice.png")

        app.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
