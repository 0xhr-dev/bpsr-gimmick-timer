"""ギミックタイマーの起動スクリプト (exe もこれを PyInstaller で固めたもの)。

    py -3.11 run.py              # 管理者権限で起動し直す (UAC の確認が出る)
    py -3.11 run.py --no-admin   # 一般権限のまま (ゲーム操作中はキーが効かない)

実コードは src/ 配下にあるので、そこを import パスに追加して起動する。
"""

import ctypes
import os
import subprocess
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))

import overlay  # noqa: E402
from hotkey import is_admin  # noqa: E402


def ensure_admin():
    """ゲームが管理者権限で動くので、タイマーも管理者権限で起動し直す。

    一般権限のままだと、ゲームを操作している間はキーの状態が読めない (UIPI)。
    exe はマニフェスト (build.bat の --uac-admin) で最初から管理者権限になるので、
    ここで面倒を見るのはソースから起動したときだけ。
    UAC を断られたら一般権限のまま続ける (タイマーに警告が出る)。
    """
    if getattr(sys, "frozen", False) or "--no-admin" in sys.argv or is_admin():
        return
    params = subprocess.list2cmdline([os.path.abspath(__file__)] + sys.argv[1:])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, ROOT, 1)
    if rc > 32:        # 32 以下は失敗 (UAC を断られたなど)
        sys.exit(0)


def main():
    ensure_admin()
    overlay.enable_dpi_awareness()      # Tk を作る前に呼ぶこと
    try:
        app = overlay.TimerApp()
    except Exception:
        overlay.show_fatal(traceback.format_exc())
        raise
    app.run()


if __name__ == "__main__":
    main()
