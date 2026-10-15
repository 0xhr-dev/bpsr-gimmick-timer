"""ゲーム画面の上に重ねるタイマーの小窓。

プレイ中はゲームが前面にあるので、次の 3 つを満たす必要がある。
  1. 常に最前面 (-topmost に加え、2 秒ごとに SetWindowPos で押し戻す)
  2. クリックしてもゲームからフォーカスを奪わない (WS_EX_NOACTIVATE)
  3. ゲームが前面のままでも操作できる (グローバルホットキー。hotkey.py)

録画やスクリーンショットにはそのまま写る (WDA_EXCLUDEFROMCAPTURE は付けない)。

★ 排他フルスクリーンでは表示できない
  ゲームがフロントバッファを所有するため、最前面かどうかに関わらず
  どのウィンドウも合成されない。ゲームはボーダーレスウィンドウで動かすこと。

スレッドの約束ごと: Tk に触るのはメインスレッドだけ。ホットキーのスレッドは
操作名を queue に積むだけで、100ms ごとの _tick() がそれを取り出す。

見た目 (ボタン行と設定欄は出し入れできる):
    ┌───────────────────────┐
    │ 27  次 3回目      ⚙ ✕ │
    │     経過 01:48         │
    │ [▶30秒 F9][▶45秒 F10][■ F11] │
    ├───────────────────────┤
    │ 設定欄 (settings_panel) │
    └───────────────────────┘
"""

import ctypes
import datetime
import os
import queue
import sys
import time
import tkinter as tk
import traceback
from tkinter import messagebox

import schedule
import theme
from config import Config, app_dir
from hotkey import HotkeyListener, label as hotkey_label
from settings_panel import SettingsPanel

# --- Win32 -------------------------------------------------------------
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

_IS_WIN = sys.platform.startswith("win")

TICK_MS = 100
TOPMOST_INTERVAL_MS = 2000
SAVE_DELAY_MS = 500           # −/+ の押し続けで毎回書かないよう、止まってから保存する
MARGIN = 24
ERROR_LOG = "error.log"

# ホットキーの設定名 -> 操作名
ACTIONS = {"hotkey_start": "start", "hotkey_repeat": "repeat", "hotkey_stop": "stop"}


def enable_dpi_awareness():
    """Tk を作る前に呼ぶ。

    これが無いと 125% / 150% 表示で Windows が窓を引き伸ばし、文字がぼやける。
    """
    if not _IS_WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # SYSTEM_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def write_error_log(text):
    """exe は --windowed で動くので標準エラーが見えない。exe の隣へ書き残す。"""
    path = os.path.join(app_dir(), ERROR_LOG)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n{text}\n")
    except OSError:
        pass
    return path


class TimerApp:
    """タイマー本体。生成するとすぐ窓が出る。run() でイベントループに入る。

    clock と hotkeys は tools/make_screenshots.py が時刻を止めて撮るためのもの。
    """

    def __init__(self, config_path=None, clock=time.monotonic, hotkeys=True):
        self._clock = clock
        self._use_hotkeys = hotkeys
        self.config = Config(config_path).load()
        self.started_at = None
        self.skip_first = False                 # True なら初回を飛ばして間隔だけで数える

        self._actions = queue.SimpleQueue()     # ホットキーのスレッド -> メインスレッド
        self._listener = None
        self._hotkeys_paused = False
        self._hotkey_failures = []
        self._error = None
        self._drag = None
        self._shown = {}                        # 前回描いた (文字, 色)。差分だけ描く
        self._note_visible = False
        self._panel = None
        self._panel_open = False
        self._save_job = None
        self._topmost_job = None
        self._tick_job = None

        self.root = tk.Tk()
        self.root.withdraw()          # 置き場所が決まるまで隠す (左上に一瞬出ないように)
        self.root.report_callback_exception = self._on_callback_error
        self.fonts = theme.make_fonts()
        self._build()
        self._apply_all()
        self._start_hotkeys()
        self.render()
        self._place()
        self.root.deiconify()
        self.root.update_idletasks()
        # スタイルは表示した後に当てる。表示の時点で Tk が枠の窓を作り直すことがある
        self._apply_win32_styles()
        self._keep_on_top()
        self._tick_job = self.root.after(TICK_MS, self._tick)

    # ------------------------------------------------------------------
    # 操作
    # ------------------------------------------------------------------

    def start(self, skip_first=False):
        """開始。動いている最中なら 0 からやり直す。

        skip_first=True は初回 (30 秒) を飛ばし、最初から間隔 (45 秒) で数える。
        """
        self.started_at = self._clock()
        self.skip_first = skip_first
        self.render()

    def stop(self):
        self.started_at = None
        self.render()

    def elapsed(self):
        if self.started_at is None:
            return None
        return self._clock() - self.started_at

    def intervals(self):
        if self.skip_first:
            return [self.config["interval_sec"]]
        return [self.config["first_sec"], self.config["interval_sec"]]

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self._stop_hotkeys()
            self._flush_save()

    def close(self):
        self._panel.cancel_capture()
        self._stop_hotkeys()
        self._flush_save()
        for job in (self._topmost_job, self._tick_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)   # 残すと終了時に invalid command name が出る
                except Exception:
                    pass
        self.root.destroy()

    # ------------------------------------------------------------------
    # 設定 (SettingsPanel から呼ばれる)
    # ------------------------------------------------------------------

    def toggle_settings(self):
        if not self._panel_open:
            self.open_settings()
        else:
            self.close_settings()

    def open_settings(self):
        """設定欄を開く。部品は起動時に作ってあるので並べるだけ
        (40 個ほどあり、開くたびに作ると待たされる)。"""
        if self._panel_open:
            return
        self._panel.refresh()
        self._panel.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self._panel_open = True
        self._place()

    def close_settings(self):
        if not self._panel_open:
            return
        self._panel.cancel_capture()
        self._panel.grid_remove()
        self._panel_open = False
        self._place()

    def setting_changed(self, key):
        """設定欄で値が変わった。見た目に反映し、少し後で保存する。

        −/+ は押し続けると 1 秒に十数回呼ばれるので、変わった所だけ触る。
        Tk はフォントや文字を設定し直すたびに、それを使う部品を全部描き直す。
        """
        resized = False
        if key in ACTIONS:
            self._restart_hotkeys()
        elif key == "scale":
            theme.apply_scale(self.fonts, self.config["scale"])
            resized = True
        elif key == "opacity":
            self._apply_opacity()
        elif key == "show_buttons":
            self._apply_buttons_row()
            resized = True
        elif key in ("first_sec", "interval_sec"):
            resized = self._apply_digits_width()
        self.render()
        if resized:
            self._place()
        self._schedule_save()

    def reset_settings(self):
        self.config.reset()
        self._restart_hotkeys()
        self._apply_all()
        self.render()
        self._place()
        self._schedule_save()

    def reload_config(self):
        """設定ファイルから読み直す。"""
        self.config.load()
        self._restart_hotkeys()
        self._apply_all()
        self._panel.refresh()
        self.render()
        self._place()

    def pause_hotkeys(self):
        """設定欄でキーを読み取っている間は止める (今のキーでタイマーが動かないように)。"""
        self._hotkeys_paused = True
        self._stop_hotkeys()

    def resume_hotkeys(self):
        self._hotkeys_paused = False
        self._start_hotkeys()

    def _apply_all(self):
        """起動時・初期値に戻したとき・読み直したときに、設定を全部当て直す。"""
        theme.apply_scale(self.fonts, self.config["scale"])
        self._apply_opacity()
        self._apply_digits_width()
        self._apply_buttons_row()

    def _apply_opacity(self):
        try:
            self.root.attributes("-alpha", self.config["opacity"] / 100)
        except tk.TclError:
            pass

    def _apply_digits_width(self):
        """数字の欄は最大の桁数で幅を固定する (45 → 9 で窓が横に揺れないように)。
        幅が変わったら True。"""
        cfg = self.config
        width = max(2, len(str(max(cfg["first_sec"], cfg["interval_sec"]))))
        if int(self._digits.cget("width")) == width:
            return False
        self._digits.configure(width=width)
        return True

    def _apply_buttons_row(self):
        shown = bool(self._buttons.grid_info())      # grid_remove 中は空
        if self.config["show_buttons"] and not shown:
            self._buttons.grid()
        elif not self.config["show_buttons"] and shown:
            self._buttons.grid_remove()

    def _schedule_save(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(SAVE_DELAY_MS, self._flush_save)

    def _flush_save(self):
        if self._save_job is None:
            return
        try:
            self.root.after_cancel(self._save_job)
        except Exception:
            pass
        self._save_job = None
        self.config.save()

    # ------------------------------------------------------------------
    # 生成
    # ------------------------------------------------------------------

    def _build(self):
        root = self.root
        f = self.fonts
        root.title("ギミックタイマー")
        root.overrideredirect(True)          # タイトルバーを消す
        root.attributes("-topmost", True)
        root.configure(bg=theme.BORDER)      # 外周 1px を枠線として見せる

        outer = tk.Frame(root, bg=theme.BG, padx=6, pady=4)
        outer.pack(fill="both", expand=True, padx=1, pady=1)
        outer.columnconfigure(0, weight=1)
        self._outer = outer

        # --- 1 段目: 残り秒 / 回数と経過 / 設定・閉じる ---
        top = tk.Frame(outer, bg=theme.BG)
        top.grid(row=0, column=0, sticky="ew")
        self._digits = tk.Label(top, text="--", width=2, bg=theme.BG, fg=theme.DIM,
                                font=f["digits"], anchor="e")
        self._digits.pack(side="left")
        info = tk.Frame(top, bg=theme.BG)
        info.pack(side="left", padx=(6, 0))
        self._line1 = tk.Label(info, text="", bg=theme.BG, fg=theme.SUB, font=f["info"],
                               anchor="w")
        self._line1.pack(anchor="w")
        self._line2 = tk.Label(info, text="", bg=theme.BG, fg=theme.DIM, font=f["small"],
                               anchor="w")
        self._line2.pack(anchor="w")
        tools = tk.Frame(top, bg=theme.BG)
        tools.pack(side="right", anchor="n", padx=(8, 0))
        tk.Button(tools, text="✕", command=self.close,
                  **theme.button_style(f["small"], compact=True)).pack(side="right")
        tk.Button(tools, text="⚙", command=self.toggle_settings,
                  **theme.button_style(f["small"], compact=True)).pack(side="right", padx=(0, 2))

        # --- 2 段目: ボタン (設定で隠せる) ---
        self._buttons = tk.Frame(outer, bg=theme.BG)
        self._buttons.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self._buttons.columnconfigure((0, 1, 2), weight=1, uniform="buttons")
        self._btn_start = tk.Button(self._buttons, command=lambda: self.start(False),
                                    **theme.button_style(f["small"]))
        self._btn_start.grid(row=0, column=0, sticky="ew", padx=(0, 1))
        self._btn_repeat = tk.Button(self._buttons, command=lambda: self.start(True),
                                     **theme.button_style(f["small"]))
        self._btn_repeat.grid(row=0, column=1, sticky="ew", padx=1)
        self._btn_stop = tk.Button(self._buttons, command=self.stop,
                                   **theme.button_style(f["small"]))
        self._btn_stop.grid(row=0, column=2, sticky="ew", padx=(1, 0))

        # --- 警告 (キーが登録できない・設定が読めない など)。あるときだけ出す ---
        self._note = tk.Label(outer, text="", bg=theme.BG, fg=theme.NOTICE,
                              font=f["panel_small"], justify="left", anchor="w",
                              wraplength=200)
        self._note.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self._note.grid_remove()

        # 設定欄は作っておくだけで、⚙ を押すまで並べない (row=2)
        self._panel = SettingsPanel(outer, self)

        # タイトルバーが無いので、ボタン以外のどこを掴んでも動かせるようにする
        for w in (outer, top, self._digits, info, self._line1, self._line2, tools,
                  self._buttons, self._note):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

    # ------------------------------------------------------------------
    # 描画 (メインスレッドからのみ)
    # ------------------------------------------------------------------

    def render(self):
        cfg = self.config
        keys = {k: hotkey_label(cfg[k]) for k in ACTIONS}

        elapsed = self.elapsed()
        if elapsed is None:
            self._set(self._digits, str(cfg["first_sec"]), theme.DIM)
            self._set(self._line1, "待機中", theme.DIM)
            self._set(self._line2, f"{keys['hotkey_start']} で開始", theme.DIM)
        else:
            nxt = schedule.next_spawn(elapsed, self.intervals())
            lv = schedule.level(nxt.remaining, cfg["warn_sec"], cfg["danger_sec"])
            self._set(self._digits, str(schedule.display_seconds(nxt.remaining)),
                      theme.LEVEL_COLOR[lv])
            self._set(self._line1, f"次 {nxt.number}回目", theme.SUB)
            self._set(self._line2, f"経過 {schedule.format_elapsed(elapsed)}", theme.DIM)

        self._set(self._btn_start, f"▶{cfg['first_sec']}秒 {keys['hotkey_start']}")
        self._set(self._btn_repeat, f"▶{cfg['interval_sec']}秒 {keys['hotkey_repeat']}")
        self._set(self._btn_stop, f"■ {keys['hotkey_stop']}")
        self._render_note()

    def _set(self, widget, text, color=None):
        if self._shown.get(widget) == (text, color):
            return
        self._shown[widget] = (text, color)
        if color is None:
            widget.configure(text=text)
        else:
            widget.configure(text=text, fg=color)

    def _render_note(self):
        lines = list(self.config.warnings) + list(self._hotkey_failures)
        if self._error:
            lines.append(self._error)
        text = "\n".join(f"⚠ {line}" for line in lines)
        visible = bool(text)
        if visible:
            self._set(self._note, text)
        if visible != self._note_visible:
            if visible:
                self._note.configure(wraplength=max(140, self._outer.winfo_width() - 12))
                self._note.grid()
            else:
                self._note.grid_remove()
            self._note_visible = visible

    # ------------------------------------------------------------------
    # 定期処理
    # ------------------------------------------------------------------

    def _tick(self):
        while True:
            try:
                action = self._actions.get_nowait()
            except queue.Empty:
                break
            if action == "start":
                self.start(skip_first=False)
            elif action == "repeat":
                self.start(skip_first=True)
            elif action == "stop":
                self.stop()

        self.render()
        self._tick_job = self.root.after(TICK_MS, self._tick)

    # ------------------------------------------------------------------
    # ホットキー
    # ------------------------------------------------------------------

    def _start_hotkeys(self):
        self._hotkey_failures = []
        if not self._use_hotkeys or self._hotkeys_paused:
            return
        self._listener = HotkeyListener(
            {action: self.config[key] for key, action in ACTIONS.items()}, self._actions)
        self._listener.start()
        self._hotkey_failures = list(self._listener.failures)

    def _stop_hotkeys(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _restart_hotkeys(self):
        self._stop_hotkeys()
        self._start_hotkeys()

    # ------------------------------------------------------------------
    # 配置とドラッグ
    # ------------------------------------------------------------------

    def _virtual_screen(self):
        """全モニタを合わせた範囲 (x, y, w, h)。サブモニタは負の座標もある。"""
        if _IS_WIN:
            m = ctypes.windll.user32.GetSystemMetrics
            w, h = m(SM_CXVIRTUALSCREEN), m(SM_CYVIRTUALSCREEN)
            if w > 0 and h > 0:
                return m(SM_XVIRTUALSCREEN), m(SM_YVIRTUALSCREEN), w, h
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _place(self):
        """保存した位置へ置く。無ければメイン画面の右上寄り (ミニマップの下あたり)。

        設定欄を開くと窓が伸びるので、画面からはみ出す分だけ押し戻す
        (保存した位置は変えない。閉じれば元の位置に戻る)。
        """
        root = self.root
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        x, y = self.config["x"], self.config["y"]
        if x is None or y is None:
            x = root.winfo_screenwidth() - w - MARGIN
            y = int(root.winfo_screenheight() * 0.3)
        # 画面外に出るとタイトルバーが無いぶん掴めなくなるのでクランプする
        vx, vy, vw, vh = self._virtual_screen()
        x = max(vx, min(int(x), vx + vw - w))
        y = max(vy, min(int(y), vy + vh - h))
        # 位置だけ指定する。大きさまで固定すると中身の出し入れで伸び縮みしない
        root.wm_geometry(f"+{x}+{y}")

    def _drag_start(self, event):
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_move(self, event):
        if self._drag is None:
            return
        dx, dy = self._drag
        self.root.wm_geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def _drag_end(self, _event):
        if self._drag is None:
            return
        self._drag = None
        self.config["x"], self.config["y"] = self.root.winfo_x(), self.root.winfo_y()
        self._schedule_save()

    # ------------------------------------------------------------------
    # Win32
    # ------------------------------------------------------------------

    def _hwnd(self):
        """トップレベルの HWND。

        Tk の winfo_id() は内側の子ウィンドウを返すので親を辿る。
        overrideredirect のときは GetParent が 0 を返すことがあるので、
        その場合は winfo_id() 自身を使う。
        """
        h = self.root.winfo_id()
        if not _IS_WIN:
            return h
        return ctypes.windll.user32.GetParent(h) or h

    def _apply_win32_styles(self):
        if not _IS_WIN:
            return
        u = ctypes.windll.user32
        # 64bit では LONG_PTR を返す。ctypes の既定 restype は c_int なので、
        # 明示しないと上位 32bit を落として既存スタイルを壊す。
        getf = getattr(u, "GetWindowLongPtrW", u.GetWindowLongW)
        setf = getattr(u, "SetWindowLongPtrW", u.SetWindowLongW)
        getf.restype = ctypes.c_ssize_t
        getf.argtypes = [ctypes.c_void_p, ctypes.c_int]
        setf.restype = ctypes.c_ssize_t
        setf.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        try:
            # クリックしてもアクティブにならないようにする。これが無いとボタンを
            # 押すたびにゲームが非アクティブになり、キー操作がゲームに届かなくなる。
            # ドラッグとボタン押下自体は従来どおり届く。
            # WS_EX_TOOLWINDOW は Alt+Tab の一覧に出さないため。
            hwnd = self._hwnd()
            style = getf(hwnd, GWL_EXSTYLE)
            setf(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def _keep_on_top(self):
        """定期的に最前面へ押し戻す。

        ゲーム側が前面に出直したときなどに Z オーダーが入れ替わることがある。
        lift() ではなく SetWindowPos を SWP_NOACTIVATE 付きで撃つ (フォーカスには触らない)。
        """
        if _IS_WIN:
            try:
                ctypes.windll.user32.SetWindowPos(
                    self._hwnd(), HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            except Exception:
                pass
        self._topmost_job = self.root.after(TOPMOST_INTERVAL_MS, self._keep_on_top)

    # ------------------------------------------------------------------

    def _on_callback_error(self, exc, value, tb):
        path = write_error_log("".join(traceback.format_exception(exc, value, tb)))
        self._error = f"エラー: {value} (詳細は {os.path.basename(path)})"


def show_fatal(text):
    """起動できなかったことを知らせる。exe は --windowed なのでコンソールが無い。"""
    path = write_error_log(text)
    try:
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("ギミックタイマー",
                             f"起動に失敗しました。\n詳細は {path} を見てください。")
        r.destroy()
    except Exception:
        pass
