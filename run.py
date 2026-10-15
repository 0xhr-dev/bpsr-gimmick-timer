"""ギミックタイマーの起動スクリプト (exe もこれを PyInstaller で固めたもの)。

    py -3.11 run.py

実コードは src/ 配下にあるので、そこを import パスに追加して起動する。
"""

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))

import overlay  # noqa: E402


def main():
    overlay.enable_dpi_awareness()      # Tk を作る前に呼ぶこと
    try:
        app = overlay.TimerApp()
    except Exception:
        overlay.show_fatal(traceback.format_exc())
        raise
    app.run()


if __name__ == "__main__":
    main()
