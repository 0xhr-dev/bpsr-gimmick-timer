"""タイマーの下に開く設定欄。

タイマーの窓はフォーカスを取らない (取るとゲームの操作が止まる) ので、
文字の入力欄は使えない。クリックだけで設定できるようにしてある。
  - 数値: −/+ ボタン。押し続けると連続で変わる
  - キー: ボタンを押してから、割り当てたいキーを押す (hotkey.KeyCapture)

変えた値はその場でタイマーに反映され、保存も TimerApp がまとめて行う。
"""

import time
import tkinter as tk

import theme
from config import HOTKEY_KEYS, RANGES
from hotkey import KeyCapture, label as hotkey_label, same_hotkey

CAPTURE_POLL_MS = 20
CAPTURE_TIMEOUT_SEC = 10
MESSAGE_SEC = 4

# (設定名, 見出し, 単位)
NUMBER_ROWS = [
    ("first_sec", "初回", "秒"),
    ("interval_sec", "以後の間隔", "秒"),
    ("warn_sec", "黄色 (残り)", "秒"),
    ("danger_sec", "赤 (残り)", "秒"),
    ("scale", "大きさ", "%"),
    ("opacity", "不透明度", "%"),
]


def action_name(config, key):
    """ホットキーの見出し。「45秒から」は設定した間隔に合わせて変わる。"""
    return {
        "hotkey_start": f"{config['first_sec']}秒から",
        "hotkey_repeat": f"{config['interval_sec']}秒から",
        "hotkey_stop": "停止",
    }[key]


class SettingsPanel(tk.Frame):
    """app は TimerApp。config / fonts / setting_changed() / pause_hotkeys() /
    resume_hotkeys() / reset_settings() / close_settings() を使う。"""

    def __init__(self, master, app):
        super().__init__(master, bg=theme.PANEL_BG, padx=6, pady=6,
                         highlightthickness=1, highlightbackground=theme.BORDER)
        self.app = app
        self._values = {}           # 設定名 -> 値を出す Label
        self._key_labels = {}       # 設定名 -> 見出しの Label (「45秒から」が変わる)
        self._key_buttons = {}      # 設定名 -> キーのボタン
        self._capturing = None      # 読み取り中の設定名
        self._capture = None
        self._capture_deadline = 0.0
        self._capture_job = None
        self._message_job = None
        self._shown = {}            # 部品 -> 前回設定した内容。変わったときだけ configure する
        self._build()
        self.refresh()

    # ------------------------------------------------------------------

    def _build(self):
        f = self.app.fonts
        self.columnconfigure(1, weight=1)
        row = 0

        def heading(text):
            return tk.Label(self, text=text, bg=theme.PANEL_BG, fg=theme.SUB,
                            font=f["panel"], anchor="w")

        for key, text, unit in NUMBER_ROWS:
            heading(text).grid(row=row, column=0, sticky="w", pady=1)
            box = tk.Frame(self, bg=theme.PANEL_BG)
            box.grid(row=row, column=1, sticky="e", pady=1)
            # repeatdelay / repeatinterval: 押し続けると連続で押したことになる
            tk.Button(box, text="−", width=2, repeatdelay=400, repeatinterval=70,
                      command=lambda k=key: self._step(k, -1),
                      **theme.button_style(f["panel"], compact=True)).pack(side="left")
            value = tk.Label(box, text="", width=6, bg=theme.PANEL_BG, fg=theme.FG,
                             font=f["panel"])
            value.pack(side="left")
            value.unit = unit
            tk.Button(box, text="+", width=2, repeatdelay=400, repeatinterval=70,
                      command=lambda k=key: self._step(k, +1),
                      **theme.button_style(f["panel"], compact=True)).pack(side="left")
            self._values[key] = value
            row += 1

        heading("ボタン行").grid(row=row, column=0, sticky="w", pady=1)
        self._buttons_toggle = tk.Button(self, width=10, command=self._toggle_buttons,
                                         **theme.button_style(f["panel"]))
        self._buttons_toggle.grid(row=row, column=1, sticky="e", pady=1)
        row += 1

        tk.Frame(self, bg=theme.BORDER, height=1).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=(5, 4))
        row += 1

        for key in HOTKEY_KEYS:
            lbl = heading("")
            lbl.grid(row=row, column=0, sticky="w", pady=1)
            btn = tk.Button(self, width=10, command=lambda k=key: self._begin_capture(k),
                            **theme.button_style(f["panel"]))
            btn.grid(row=row, column=1, sticky="e", pady=1)
            self._key_labels[key] = lbl
            self._key_buttons[key] = btn
            row += 1

        # 案内の行は空でも場所を取っておく。出し入れすると下のボタンが上下に動いて
        # 押し間違える。1 行に収まる長さの文だけを出すこと
        self._message = tk.Label(self, text="", bg=theme.PANEL_BG, fg=theme.NOTICE,
                                 font=f["panel_small"], anchor="w")
        self._message.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(3, 0))
        row += 1

        bottom = tk.Frame(self, bg=theme.PANEL_BG)
        bottom.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        tk.Button(bottom, text="初期値に戻す", command=self._reset,
                  **theme.button_style(f["panel_small"])).pack(side="left")
        tk.Button(bottom, text="閉じる", command=self.app.close_settings,
                  **theme.button_style(f["panel_small"])).pack(side="right")


    def refresh(self):
        """今の設定値を表示し直す。

        Tk は configure されるたびに部品を描き直すので、変わったものだけ触る
        (−/+ を押し続けると 1 秒に十数回呼ばれる)。
        """
        cfg = self.app.config
        for key, value in self._values.items():
            self._set(value, text=f"{cfg[key]}{value.unit}")
        self._set(self._buttons_toggle, text="表示" if cfg["show_buttons"] else "非表示")
        for key in HOTKEY_KEYS:
            self._set(self._key_labels[key], text=f"{action_name(cfg, key)}キー")
            if key != self._capturing:
                self._set(self._key_buttons[key], text=hotkey_label(cfg[key]), fg=theme.FG)

    def _set(self, widget, **opts):
        if self._shown.get(widget) == opts:
            return
        self._shown[widget] = opts
        widget.configure(**opts)

    # ------------------------------------------------------------------
    # 数値と表示切り替え
    # ------------------------------------------------------------------

    def _step(self, key, direction):
        lo, hi, step = RANGES[key]
        current = self.app.config[key]
        new = max(lo, min(hi, current + direction * step))
        if new == current:
            return
        self.app.config[key] = new
        self.app.setting_changed(key)
        self.refresh()

    def _toggle_buttons(self):
        self.app.config["show_buttons"] = not self.app.config["show_buttons"]
        self.app.setting_changed("show_buttons")
        self.refresh()

    def _reset(self):
        self.cancel_capture()
        self.app.reset_settings()
        self.refresh()
        self._show_message("初期値に戻しました")

    # ------------------------------------------------------------------
    # キーの読み取り
    # ------------------------------------------------------------------

    def _begin_capture(self, key):
        self.cancel_capture()
        self.app.pause_hotkeys()      # 今の F9 などがタイマーを動かさないように
        self._capturing = key
        self._capture = KeyCapture()
        self._capture_deadline = time.monotonic() + CAPTURE_TIMEOUT_SEC
        self._set(self._key_buttons[key], text="キーを押す…", fg=theme.WARN)
        self._show_message("キーを押してください (Esc で取り消し)",
                           seconds=CAPTURE_TIMEOUT_SEC)
        self._capture_job = self.after(CAPTURE_POLL_MS, self._poll_capture)

    def _poll_capture(self):
        self._capture_job = None
        result = self._capture.poll()
        if result is None:
            if time.monotonic() < self._capture_deadline:
                self._capture_job = self.after(CAPTURE_POLL_MS, self._poll_capture)
                return
            result = ("cancel", None)

        key = self._capturing
        self._end_capture()
        kind, text = result
        if kind == "key":
            cfg = self.app.config
            clash = next((k for k in HOTKEY_KEYS
                          if k != key and same_hotkey(cfg[k], text)), None)
            if clash:
                self._show_message(f"{hotkey_label(text)} は「{action_name(cfg, clash)}」で使用中")
            else:
                cfg[key] = text
                self.app.setting_changed(key)
                self._show_message(f"{action_name(cfg, key)}: {hotkey_label(text)}")
        else:
            self._show_message("取り消しました")
        self.app.resume_hotkeys()
        self.refresh()

    def _end_capture(self):
        if self._capture_job is not None:
            self.after_cancel(self._capture_job)
            self._capture_job = None
        self._capturing = None
        self._capture = None

    def cancel_capture(self):
        """読み取り中なら取り消してホットキーを戻す (設定欄を閉じるときにも呼ぶ)。"""
        if self._capturing is None:
            return
        self._end_capture()
        self.app.resume_hotkeys()
        self.refresh()

    # ------------------------------------------------------------------

    def _show_message(self, text, seconds=MESSAGE_SEC):
        if self._message_job is not None:
            self.after_cancel(self._message_job)
        self._message.configure(text=text)
        self._message_job = self.after(int(seconds * 1000), self._hide_message)

    def _hide_message(self):
        self._message_job = None
        self._message.configure(text="")
