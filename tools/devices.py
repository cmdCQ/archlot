"""输入设备机制：uinput 真实键码、wtype、剪贴板。

只负责“怎么把事件发出去”，不决定什么时候发、要不要确认。
"""

from __future__ import annotations

import fcntl
import os
import re
import struct
import subprocess
import time

from core import system

# ---------------------------------------------------------------- uinput 键盘
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_SET_ABSBIT = 0x40045567
UI_SET_PROPBIT = 0x4004556E
UI_DEV_SETUP = 0x405C5503
UI_ABS_SETUP = 0x401C5504
INPUT_PROP_POINTER = 0x00

EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
SYN_REPORT = 0
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
REL_WHEEL, REL_HWHEEL = 0x08, 0x06
ABS_X, ABS_Y = 0x00, 0x01
ABS_MAX = 32767

_KEYS = {
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34, "h": 35,
    "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49, "o": 24, "p": 25,
    "q": 16, "r": 19, "s": 31, "t": 20, "u": 22, "v": 47, "w": 17, "x": 45,
    "y": 21, "z": 44,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10,
    "0": 11, "-": 12, "=": 13, "[": 26, "]": 27, ";": 39, "'": 40, "`": 41,
    "\\": 43, ",": 51, ".": 52, "/": 53, " ": 57,
}
_SHIFTED = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
    "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]",
    ":": ";", '"': "'", "~": "`", "|": "\\", "<": ",", ">": ".", "?": "/",
}
NAMED = {
    "backspace": 14, "return": 28, "enter": 28, "escape": 1, "tab": 15,
    "space": 57, "delete": 111, "home": 102, "end": 107, "up": 103,
    "down": 108, "left": 105, "right": 106, "pageup": 104, "pagedown": 109,
    "insert": 110,
}
UINPUT_MODS = {"ctrl": 29, "control": 29, "alt": 56, "shift": 42,
               "super": 125, "meta": 125}


class UinputKeyboard:
    """绕过虚拟键盘协议，直接向 /dev/uinput 发真实键码。

    noVNC / KVM 网页控制台不认 wtype 的 keymap，会把字母吃掉或变成数字，
    这种目标必须用真实键码输入。
    """

    def __init__(self):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, 1)          # EV_KEY
        for code in range(1, 128):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        buf = bytearray(1116)
        name = b"archlot-virtual-kbd"
        buf[0:len(name)] = name
        struct.pack_into("HHHH", buf, 80, 3, 0x1234, 0x5678, 1)
        struct.pack_into("I", buf, 88, 0)
        os.write(self.fd, buf)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        # 合成器注册新设备需要一点时间，太早发键会被吞掉。
        time.sleep(0.45)
        self._emit(42, 1)
        self._emit(42, 0)
        time.sleep(0.08)

    def _emit(self, code, value):
        now = time.time()
        sec = int(now)
        usec = int((now - sec) * 1_000_000)
        os.write(self.fd, struct.pack("llHHi", sec, usec, 1, code, value))
        os.write(self.fd, struct.pack("llHHi", sec, usec, 0, 0, 0))

    def _tap(self, code, shift=False, delay=0.012):
        if shift:
            self._emit(42, 1)
        self._emit(code, 1)
        time.sleep(delay)
        self._emit(code, 0)
        if shift:
            self._emit(42, 0)

    def type(self, text, delay=0.015):
        unsupported = []
        for ch in text:
            if ch == "\n":
                self._tap(28)
            elif ch == "\t":
                self._tap(15)
            elif ch == "\b":
                self._tap(14)
            elif ch in _KEYS:
                self._tap(_KEYS[ch])
            elif ch.isupper() and ch.lower() in _KEYS:
                self._tap(_KEYS[ch.lower()], shift=True)
            elif ch in _SHIFTED:
                self._tap(_KEYS[_SHIFTED[ch]], shift=True)
            else:
                unsupported.append(ch)
        return unsupported

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


def type_with_uinput(text):
    """返回 (成功?, 不支持字符列表)。"""
    try:
        kb = UinputKeyboard()
    except OSError as exc:
        return False, [f"无法打开 /dev/uinput：{exc}"]
    try:
        missing = kb.type(text)
        time.sleep(0.05)
        return True, missing
    finally:
        kb.close()


def press_combo_uinput(combo):
    """用真实键码按组合键。返回 (成功?, 错误信息)。"""
    parts = [p for p in combo.split("+") if p]
    held = []
    main = None
    for part in parts:
        low = part.lower()
        if low in UINPUT_MODS:
            held.append(UINPUT_MODS[low])
        elif low in NAMED:
            main = NAMED[low]
        elif low in _KEYS:
            main = _KEYS[low]
        elif len(low) == 1 and low in _SHIFTED:
            main = _KEYS[_SHIFTED[low]]
            held.append(42)
        elif low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 12:
            main = 58 + int(low[1:]) - 1
        else:
            return False, f"不认识的按键：{part}"
    if main is None:
        return False, "缺少主键"

    try:
        kb = UinputKeyboard()
    except OSError as exc:
        return False, f"无法打开 /dev/uinput：{exc}"
    try:
        for code in held:
            kb._emit(code, 1)
        kb._tap(main)
        for code in reversed(held):
            kb._emit(code, 0)
        time.sleep(0.05)
    finally:
        kb.close()
    return True, ""


# ---------------------------------------------------------------- 虚拟鼠标

BUTTONS = {"left": BTN_LEFT, "right": BTN_RIGHT, "middle": BTN_MIDDLE}
WTYPE_MODS = {
    "ctrl": "ctrl", "control": "ctrl", "shift": "shift",
    "alt": "alt", "super": "logo", "meta": "logo",
    "logo": "logo", "win": "logo",
}


class VirtualMouse:
    """基于 /dev/uinput 的绝对坐标鼠标。"""

    def __init__(self):
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
            fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
            fcntl.ioctl(fd, UI_SET_PROPBIT, INPUT_PROP_POINTER)
            for btn in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE):
                fcntl.ioctl(fd, UI_SET_KEYBIT, btn)
            for rel in (REL_WHEEL, REL_HWHEEL):
                fcntl.ioctl(fd, UI_SET_RELBIT, rel)
            for axis in (ABS_X, ABS_Y):
                fcntl.ioctl(fd, UI_SET_ABSBIT, axis)
                absinfo = struct.pack("iiiiii", 0, 0, ABS_MAX, 0, 0, 0)
                fcntl.ioctl(fd, UI_ABS_SETUP, struct.pack("H2x", axis) + absinfo)
            setup = struct.pack(
                "HHHH80sI", 0x0003, 0xC05, 0x0001, 0x0001,
                b"archlot-virtual-mouse", 0,
            )
            fcntl.ioctl(fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(fd, UI_DEV_CREATE)
        except Exception:
            os.close(fd)
            raise
        self.fd = fd
        time.sleep(0.15)

    def _emit(self, etype, code, value):
        os.write(self.fd, struct.pack("llHHi", 0, 0, etype, code, value))

    def move(self, x, y):
        sw, sh = system.screen_size()
        ax = max(0, min(ABS_MAX, round(x / max(1, sw - 1) * ABS_MAX)))
        ay = max(0, min(ABS_MAX, round(y / max(1, sh - 1) * ABS_MAX)))
        self._emit(EV_ABS, ABS_X, ax)
        self._emit(EV_ABS, ABS_Y, ay)
        self._emit(EV_SYN, SYN_REPORT, 0)
        time.sleep(0.05)

    def click(self, x, y, button="left", double=False):
        self.move(x, y)
        code = BUTTONS.get(button, BTN_LEFT)
        count = 2 if double else 1
        for _ in range(count):
            self._emit(EV_KEY, code, 1)
            self._emit(EV_SYN, SYN_REPORT, 0)
            time.sleep(0.02)
            self._emit(EV_KEY, code, 0)
            self._emit(EV_SYN, SYN_REPORT, 0)
            time.sleep(0.05)

    def scroll(self, dy, dx=0):
        for _ in range(abs(int(dy))):
            self._emit(EV_REL, REL_WHEEL, -1 if dy > 0 else 1)
            self._emit(EV_SYN, SYN_REPORT, 0)
            time.sleep(0.03)
        for _ in range(abs(int(dx))):
            self._emit(EV_REL, REL_HWHEEL, 1 if dx > 0 else -1)
            self._emit(EV_SYN, SYN_REPORT, 0)
            time.sleep(0.03)


# ---------------------------------------------------------------- wtype / 剪贴板

def press_wtype(combo):
    """用 wtype 按组合键。返回 (成功?, stderr)。"""
    parts = [p for p in re.split(r"\+|\s+", combo) if p]
    if not parts:
        return False, "按键为空"
    mods = [WTYPE_MODS[p.lower()] for p in parts[:-1] if p.lower() in WTYPE_MODS]
    key = parts[-1]
    argv = ["wtype"]
    for m in mods:
        argv += ["-M", m]
    argv += ["-k", key]
    for m in reversed(mods):
        argv += ["-m", m]
    rc, _, err = system.run(argv, timeout=15)
    if rc != 0:
        rc, _, err = system.run(["wtype", "--", key], timeout=15)
    return rc == 0, err.strip()


def paste_text(text):
    """写剪贴板并 ctrl+v。wl-copy 会 fork，必须丢掉管道。"""
    try:
        subprocess.run(
            ["wl-copy"], input=text.encode(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"写剪贴板失败：{exc}"
    time.sleep(0.15)
    press_wtype("ctrl+v")
    return True, ""
