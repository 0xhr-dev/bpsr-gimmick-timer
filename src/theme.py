"""配色とフォント。

フォントは tkinter.font.Font のオブジェクトにしておく。大きさを変えると
それを使っている部品が全部その場で描き直されるので、設定の「大きさ」は
apply_scale() で size を書き換えるだけで済む。
"""

import tkinter.font as tkfont

BG = "#121417"
BORDER = "#2c3036"
FG = "#f2f2f2"
SUB = "#b8bcc3"
DIM = "#8b9098"
WARN = "#ffd23f"
DANGER = "#ff4d4d"
NOTICE = "#ff9f43"
ACCENT = "#7cc4ff"
BTN_BG = "#23272d"
BTN_HOVER = "#343a42"
PANEL_BG = "#181b1f"

LEVEL_COLOR = {"normal": FG, "warn": WARN, "danger": DANGER}

# (フォント名, 100% のときの大きさ, 太字か, 大きさの設定に合わせて変えるか)
_SPECS = {
    "digits": ("Consolas", 28, True, True),   # 等幅なので桁が変わっても横に揺れない
    "info": ("Yu Gothic UI", 9, False, True),
    "small": ("Yu Gothic UI", 8, False, True),
    "panel": ("Yu Gothic UI", 9, False, False),
    "panel_small": ("Yu Gothic UI", 8, False, False),
}
_MIN_SIZE = 7


def make_fonts():
    """Tk を作った後に呼ぶ。"""
    return {name: tkfont.Font(family=family, size=size,
                              weight="bold" if bold else "normal")
            for name, (family, size, bold, _scaled) in _SPECS.items()}


def apply_scale(fonts, percent):
    """大きさを変える。同じ大きさでも configure すると全部描き直しになるので、変わるものだけ。"""
    for name, (_family, size, _bold, scaled) in _SPECS.items():
        new = max(_MIN_SIZE, round(size * percent / 100))
        if scaled and fonts[name].cget("size") != new:
            fonts[name].configure(size=new)


def button_style(font, compact=False):
    return dict(bg=BTN_BG, fg=FG, activebackground=BTN_HOVER, activeforeground=FG,
                relief="flat", bd=0, highlightthickness=0, font=font,
                padx=3 if compact else 5, pady=0 if compact else 1, cursor="hand2")
