"""ホットキーの検出と、設定画面でのキーの読み取り。

どちらも GetAsyncKeyState でキーの状態を直接読む (専用スレッドで 15ms ごと)。
タイマーの窓はフォーカスを取らない (取るとゲームの操作が止まる) ので、
キー入力のイベントは窓に届かないため。

★ ゲームより低い権限では動かない
  ゲームは管理者権限で動いている。Windows の UIPI により、管理者権限の窓が
  前面にある間は、一般権限のプロセスからはキーの状態が読めない
  (RegisterHotKey のホットキーも届かない)。exe は管理者権限で起動する
  (build.bat の --uac-admin)。is_admin() が False のときはタイマーに警告を出す。

キーはゲームにもそのまま届く (横取りしない)。ゲームで使うキーは割り当てないこと。
押されたことが分かったら操作名を queue に積むだけで、Tk には一切触らない
(Tk はメインスレッドからしか触れない)。
"""

import ctypes
import sys
import threading

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

POLL_SEC = 0.015

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


def current_mods(is_down):
    """いま押されている修飾キー (MOD_* の組み合わせ)。"""
    mods = 0
    if is_down(_VK_CTRL):
        mods |= MOD_CONTROL
    if is_down(_VK_ALT):
        mods |= MOD_ALT
    if is_down(_VK_SHIFT):
        mods |= MOD_SHIFT
    if is_down(_VK_LWIN) or is_down(_VK_RWIN):
        mods |= MOD_WIN
    return mods


def is_admin():
    """管理者権限で動いているか。ゲームが管理者権限なので、これが False だと
    ゲームを操作している間はキーが読めない。"""
    if not _IS_WIN:
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


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
            mods = current_mods(self._is_down)
            names = [name for bit, name in ((MOD_CONTROL, "ctrl"), (MOD_ALT, "alt"),
                                            (MOD_SHIFT, "shift"), (MOD_WIN, "win"))
                     if mods & bit]
            return ("key", "+".join(names + [name_for_vk(vk)]))
        return None


class HotkeyPoller:
    """設定したキーが押されたら、操作名を queue に積む。

    bindings: {操作名: ホットキー文字列}。例 {"start": "F9", "stop": "F11"}
    専用スレッドで POLL_SEC ごとにキーの状態を読み、離れている → 押された、に
    変わった瞬間だけ数える (押しっぱなしで連打にならない)。修飾キーは完全一致で
    見るので、F9 と Ctrl+F9 は別の操作に割り当てられる。

    Tk のイベントループとは別のスレッドで読むので、画面の描き直しで Tk が
    止まっている間に押されても取りこぼさない。
    """

    def __init__(self, bindings, out_queue, is_down=None):
        self._out = out_queue
        self._is_down = is_down or _async_down
        self._keys = []             # (操作名, 修飾キー, 仮想キーコード)
        self.failures = []          # 読めなかった設定の説明 (日本語)
        for action, text in bindings.items():
            try:
                mods, vk = parse_hotkey(text)
            except ValueError as e:
                self.failures.append(str(e))
                continue
            self._keys.append((action, mods, vk))
        # 始めた時点で押しっぱなしのキーは、一度離されるまで数えない
        self._prev = {vk: self._is_down(vk) for _a, _m, vk in self._keys}
        self._stop = threading.Event()
        self._thread = None

    def poll(self):
        """1 回分調べて、押された操作名のリストを返す。"""
        down = {vk: self._is_down(vk) for vk in self._prev}
        mods = current_mods(self._is_down)
        fired = [action for action, want, vk in self._keys
                 if down[vk] and not self._prev[vk] and mods == want]
        self._prev = down
        return fired

    def start(self):
        if not _IS_WIN:
            self.failures.append("キーの検出は Windows でしか使えません")
            return
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=1.0)
        self._thread = None

    def _run(self):
        while not self._stop.wait(POLL_SEC):
            for action in self.poll():
                self._out.put(action)
