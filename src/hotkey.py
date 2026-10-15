"""グローバルホットキー (Win32 RegisterHotKey) と、設定画面でのキーの読み取り。

ゲームが前面にあっても押したキーを受け取るために使う。
pynput / keyboard のようなフック方式はゲーム上で取りこぼすことがあるので
使わない。RegisterHotKey は OS が直接 WM_HOTKEY を届けるので、フックが
外されることも無い。

登録したキーはゲームには届かなくなる (OS が先に取る)。ゲームで使うキーは
割り当てないこと。

RegisterHotKey は「登録したスレッドのメッセージキュー」に WM_HOTKEY を積むので、
専用スレッドで登録して GetMessageW を回す。届いた操作名は queue に積むだけで、
Tk には一切触らない (Tk はメインスレッドからしか触れない)。
"""

import ctypes
import sys
import threading
from ctypes import wintypes

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000      # 押しっぱなしで連打扱いにしない

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
}

_MOD_LABEL = {MOD_CONTROL: "Ctrl", MOD_ALT: "Alt", MOD_SHIFT: "Shift", MOD_WIN: "Win"}

_NAMED_KEYS = {
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "insert": 0x2D,
    "delete": 0x2E,
    "pause": 0x13,
    "scrolllock": 0x91,
}

_IS_WIN = sys.platform.startswith("win")


def _vk_for(name):
    """キー名 (小文字) を仮想キーコードにする。分からなければ None。"""
    if name in _NAMED_KEYS:
        return _NAMED_KEYS[name]
    if len(name) == 1 and (name.isdigit() or "a" <= name <= "z"):
        return ord(name.upper())                    # VK_0..VK_9 / VK_A..VK_Z
    if name.startswith("f") and name[1:].isdigit():
        n = int(name[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1                     # VK_F1..VK_F24
    if name.startswith("num") and name[3:].isdigit():
        n = int(name[3:])
        if 0 <= n <= 9:
            return 0x60 + n                         # VK_NUMPAD0..9
    return None


def parse_hotkey(text):
    """'F9' や 'ctrl+shift+T' を (修飾キー, 仮想キーコード) にする。

    書けないものは日本語のメッセージ付きで ValueError を投げる。
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("ホットキーが空です")
    parts = [p.strip().lower() for p in text.split("+")]
    if any(not p for p in parts):
        raise ValueError(f"ホットキー「{text}」の書き方が正しくありません")

    *mod_names, key_name = parts
    mods = 0
    for m in mod_names:
        if m not in _MODIFIERS:
            raise ValueError(f"ホットキー「{text}」: 修飾キー「{m}」は使えません")
        mods |= _MODIFIERS[m]

    vk = _vk_for(key_name)
    if vk is None:
        raise ValueError(f"ホットキー「{text}」: キー「{key_name}」は使えません")
    return mods, vk


def label(text):
    """ボタンに出す表記に整える ('ctrl+f9' -> 'Ctrl+F9')。書けなければそのまま返す。"""
    try:
        mods, _vk = parse_hotkey(text)
    except ValueError:
        return str(text)
    key = text.split("+")[-1].strip()
    key = key.upper() if len(key) <= 3 else key.capitalize()
    names = [_MOD_LABEL[bit] for bit in (MOD_CONTROL, MOD_ALT, MOD_SHIFT, MOD_WIN)
             if mods & bit]
    return "+".join(names + [key])


def same_hotkey(a, b):
    """表記が違っても同じキーなら True ('F9' と 'f9'、'ctrl+shift+t' と 'shift+ctrl+T')。"""
    try:
        return parse_hotkey(a) == parse_hotkey(b)
    except ValueError:
        return False


# --- 設定画面でのキーの読み取り ------------------------------------------

VK_ESCAPE = 0x1B
_VK_CTRL, _VK_ALT, _VK_SHIFT, _VK_LWIN, _VK_RWIN = 0x11, 0x12, 0x10, 0x5B, 0x5C

# 割り当てられるキー。parse_hotkey() が読めるものと同じ範囲
CAPTURE_VKS = (
    [0x70 + i for i in range(24)]                 # F1..F24
    + [ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"]
    + [0x60 + i for i in range(10)]               # テンキー 0..9
    + list(_NAMED_KEYS.values())
)
_NAME_OF_NAMED = {vk: name for name, vk in _NAMED_KEYS.items()}


def name_for_vk(vk):
    """仮想キーコードを parse_hotkey() が読める名前にする。"""
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x70 + 1}"
    if 0x60 <= vk <= 0x69:
        return f"num{vk - 0x60}"
    if vk in _NAME_OF_NAMED:
        return _NAME_OF_NAMED[vk]
    if (0x30 <= vk <= 0x39) or (0x41 <= vk <= 0x5A):
        return chr(vk)
    raise ValueError(f"割り当てられないキーです (vk={vk:#x})")


def _async_down(vk):
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


class KeyCapture:
    """次に押されたキーをホットキー文字列にする (設定画面の「キーを押してください」)。

    タイマーの窓はフォーカスを取らない (取るとゲームの操作が止まる) ので、
    キー入力のイベントは届かない。代わりに GetAsyncKeyState でキーの状態を
    直接見る。数十 ms ごとに poll() を呼ぶこと。

    始めた時点で押しっぱなしのキーは、一度離されるまで数えない。
    """

    def __init__(self, is_down=None):
        self._is_down = is_down or _async_down
        self._prev = {vk: self._is_down(vk) for vk in [VK_ESCAPE] + CAPTURE_VKS}

    def poll(self):
        """押されたら ("key", "ctrl+F9")、Esc なら ("cancel", None)、まだなら None。"""
        for vk, was_down in self._prev.items():
            down = self._is_down(vk)
            self._prev[vk] = down
            if not down or was_down:
                continue
            if vk == VK_ESCAPE:
                return ("cancel", None)
            mods = [name for name, mvk in (("ctrl", _VK_CTRL), ("alt", _VK_ALT),
                                           ("shift", _VK_SHIFT)) if self._is_down(mvk)]
            if self._is_down(_VK_LWIN) or self._is_down(_VK_RWIN):
                mods.append("win")
            return ("key", "+".join(mods + [name_for_vk(vk)]))
        return None


class HotkeyListener:
    """専用スレッドでホットキーを登録し、押された操作名を queue に積む。

    bindings: {操作名: ホットキー文字列}。例 {"start": "F9", "stop": "F10"}
    start() は登録が終わるまで待ってから戻るので、直後に failures を見てよい。
    """

    def __init__(self, bindings, out_queue):
        self._bindings = list(bindings.items())
        self._out = out_queue
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        self.failures = []          # 登録できなかったキーの説明 (日本語)

    def start(self):
        if not _IS_WIN:
            self.failures.append("ホットキーは Windows でしか使えません")
            return
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self):
        if self._thread is None:
            return
        if self._thread_id is not None:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=2.0)
        self._thread = None

    def _run(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()

        actions = {}
        for hotkey_id, (action, text) in enumerate(self._bindings, start=1):
            try:
                mods, vk = parse_hotkey(text)
            except ValueError as e:
                self.failures.append(str(e))
                continue
            if user32.RegisterHotKey(None, hotkey_id, mods | MOD_NOREPEAT, vk):
                actions[hotkey_id] = action
            else:
                self.failures.append(
                    f"{label(text)} を登録できません (他のアプリが使用中の可能性)")

        msg = wintypes.MSG()
        # PostThreadMessageW はキューが出来ていないスレッドには届かない。
        # stop() が間に合わず空振りしないよう、ready を立てる前にキューを作らせる。
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        self._ready.set()

        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam in actions:
                    self._out.put(actions[msg.wParam])
        finally:
            for hotkey_id in actions:
                user32.UnregisterHotKey(None, hotkey_id)
