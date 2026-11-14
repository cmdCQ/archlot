"""Archlot 的工具集：shell、文件、截图、鼠标、键盘、窗口。"""

import base64
import fcntl
import json
import os
import re
import struct
import subprocess
import tempfile
import threading
import time

HOME = os.path.expanduser("~")
SHOT_PATH = os.path.join(tempfile.gettempdir(), "archlot-shot.jpg")


# ---------------------------------------------------------------- uinput 键盘
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
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


# ---------------------------------------------------------------- 基础工具

def run(cmd, timeout=60, cwd=None, input_text=None):
    try:
        p = subprocess.run(
            cmd, cwd=cwd or HOME, input=input_text,
            capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"超时（{timeout}s）"
    except FileNotFoundError as exc:
        return 127, "", f"找不到命令：{exc}"


def niri_json(*args, timeout=5):
    rc, out, _ = run(["niri", "msg", "-j", *args], timeout=timeout)
    if rc != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def screen_size():
    outs = niri_json("outputs") or {}
    for out in outs.values():
        lg = out.get("logical")
        if lg:
            return lg["width"], lg["height"]
    return 1920, 1080


def list_windows():
    return niri_json("windows") or []


def image_size(path):
    """读取 PNG / JPEG 的宽高，只为标准库。"""
    with open(path, "rb") as f:
        head = f.read(64)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        if head[:2] != b"\xff\xd8":
            return None
        f.seek(2)
        while True:
            marker = f.read(2)
            if len(marker) < 2 or marker[0] != 0xFF:
                return None
            code = marker[1]
            if code in (0xC0, 0xC1, 0xC2):
                length = struct.unpack(">H", f.read(2))[0]
                data = f.read(length - 2)
                return struct.unpack(">HH", data[1:5])[::-1]  # h, w -> w, h
            length = struct.unpack(">H", f.read(2))[0]
            f.seek(length - 2, 1)


def clip(text, n=6000):
    text = text or ""
    if len(text) <= n:
        return text
    return text[:n] + f"\n…（截断，共 {len(text)} 字符）"


# ---------------------------------------------------------------- 虚拟鼠标

EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
SYN_REPORT = 0
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
REL_WHEEL, REL_HWHEEL = 0x08, 0x06
ABS_X, ABS_Y = 0x00, 0x01

UI_DEV_CREATE = 0x5501
UI_DEV_SETUP = 0x405C5503
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_RELBIT = 0x40045566
UI_SET_ABSBIT = 0x40045567
UI_SET_PROPBIT = 0x4004556E
UI_ABS_SETUP = 0x401C5504
INPUT_PROP_POINTER = 0x00
ABS_MAX = 32767

BUTTONS = {"left": BTN_LEFT, "right": BTN_RIGHT, "middle": BTN_MIDDLE}
MODS = {
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
        sw, sh = screen_size()
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


# ---------------------------------------------------------------- 工具实现

class Tools:
    def __init__(self, ui, workspace=None):
        self.ui = ui            # 提供 confirm() / flash_screenshot()
        self.workspace = os.path.abspath(os.path.expanduser(
            workspace or "~/archlot-workspace"))
        os.makedirs(self.workspace, exist_ok=True)
        self._mouse = None
        self.last_shot = None   # (width, height) 图片像素
        self._lock = threading.Lock()

    # -- 鼠标/键盘 --
    @property
    def mouse(self):
        if self._mouse is None:
            self._mouse = VirtualMouse()
        return self._mouse

    def _resolve(self, path):
        path = os.path.expanduser(str(path or ""))
        if not os.path.isabs(path):
            path = os.path.join(self.workspace, path)
        return os.path.abspath(path)

    def _outside_write(self, cmd):
        """命令里出现工作区外的绝对路径、且命令看起来会改文件时，返回那个路径。"""
        if not MUTATE_RE.search(cmd):
            return None
        for m in re.finditer(r"""(?<![\w-])((?:~|/)[^\s;|&<>"']*)""", cmd):
            raw = m.group(1)
            path = os.path.abspath(os.path.expanduser(raw))
            if path == self.workspace or path.startswith(self.workspace + os.sep):
                continue
            if path.startswith(("/tmp/", "/dev/", "/proc/", "/sys/", "/run/")):
                continue
            return path
        return None

    def _to_screen(self, x, y):
        sw, sh = screen_size()
        if self.last_shot:
            iw, ih = self.last_shot
            if iw and ih:
                return x * sw / iw, y * sh / ih
        return float(x), float(y)

    # -- 工具表 --
    def execute(self, name, args):
        fn = getattr(self, "_t_" + name, None)
        if fn is None:
            return {"text": f"未知工具：{name}"}
        try:
            return fn(args or {})
        except Exception as exc:  # noqa: BLE001
            return {"text": f"工具 {name} 出错：{exc}"}

    def _t_run_shell(self, a):
        cmd = str(a.get("command", "")).strip()
        if not cmd:
            return {"text": "命令为空"}
        if DANGER_RE.search(cmd) and not self.ui.confirm("要执行这条命令吗？", cmd):
            return {"text": "用户拒绝了这条命令。"}
        outside = self._outside_write(cmd)
        if outside and not self.ui.confirm(
                f"这条命令会改动工作区外的 {outside}，确定吗？", cmd):
            return {"text": "用户拒绝了工作区外的改动。"}
        rc, out, err = run(["bash", "-lc", cmd], cwd=self.workspace,
                           timeout=int(a.get("timeout", 60)))
        body = out.strip()
        if err.strip():
            body += ("\n[stderr]\n" + err.strip())
        return {"text": f"exit={rc}\n{clip(body)}"}

    def _t_read_file(self, a):
        path = self._resolve(a.get("path", ""))
        limit = int(a.get("limit", 20000))
        if not os.path.isfile(path):
            return {"text": f"不是文件：{path}"}
        with open(path, "r", errors="replace") as f:
            return {"text": clip(f.read(limit + 1), limit)}

    def _t_write_file(self, a):
        path = self._resolve(a.get("path", ""))
        if not (path == self.workspace or
                path.startswith(self.workspace + os.sep)):
            if not self.ui.confirm("要写工作区外的文件吗？", path):
                return {"text": "用户拒绝了这次写入。"}
        content = str(a.get("content", ""))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return {"text": f"已写入 {path}（{len(content)} 字符）"}

    def _t_list_dir(self, a):
        path = self._resolve(a.get("path", self.workspace))
        try:
            entries = sorted(os.listdir(path))[:200]
        except OSError as exc:
            return {"text": f"打不开：{exc}"}
        lines = []
        for name in entries:
            full = os.path.join(path, name)
            lines.append(name + ("/" if os.path.isdir(full) else ""))
        return {"text": "\n".join(lines) or "（空目录）"}

    def _t_screenshot(self, a):
        scale = float(a.get("scale", 0.6))
        self.ui.hide_for_shot()
        try:
            rc, _, err = run(
                ["grim", "-s", str(scale), "-t", "jpeg", "-q", "80", SHOT_PATH],
                timeout=15)
        finally:
            self.ui.show_after_shot()
        if rc != 0:
            return {"text": f"截图失败：{err.strip()}"}
        size = image_size(SHOT_PATH) or (0, 0)
        self.last_shot = size
        sw, sh = screen_size()
        return {
            "text": (f"截图完成：图片 {size[0]}x{size[1]}，逻辑屏幕 {sw}x{sh}。"
                     "后续 click/move_mouse 的坐标请用这张图的像素坐标。"),
            "image": SHOT_PATH,
        }

    def _t_click(self, a):
        x, y = self._to_screen(int(a.get("x", 0)), int(a.get("y", 0)))
        parked = self.ui.park_panel(x, y)
        try:
            self.mouse.click(x, y, str(a.get("button", "left")),
                             bool(a.get("double", False)))
        finally:
            if parked:
                self.ui.unpark_panel()
        return {"text": f"已点击 ({int(x)}, {int(y)})"}

    def _t_move_mouse(self, a):
        x, y = self._to_screen(int(a.get("x", 0)), int(a.get("y", 0)))
        self.mouse.move(x, y)
        return {"text": f"鼠标移到 ({int(x)}, {int(y)})"}

    def _t_scroll(self, a):
        dy = int(a.get("dy", 0))
        dx = int(a.get("dx", 0))
        self.mouse.scroll(dy, dx)
        return {"text": f"已滚动 dy={dy} dx={dx}"}

    def _t_type_text(self, a):
        text = str(a.get("text", ""))
        if not text:
            return {"text": "文本为空"}
        method = str(a.get("method", "auto"))
        if method == "keys":
            ok, missing = type_with_uinput(text)
            if not ok:
                return {"text": f"真实键码输入失败：{missing[0]}"}
            note = f"（{len(missing)} 个字符不支持：{''.join(missing[:8])}）" if missing else ""
            return {"text": f"已用真实键码输入 {len(text) - len(missing)} 个字符{note}"}
        if method == "paste":
            return self._paste_text(text)
        if text.isascii():
            rc, _, err = run(["wtype", "--", text], timeout=30)
            if rc != 0:
                return {"text": f"打字失败：{err.strip()}"}
        else:
            # wl-copy 会 fork 到后台常驻，继承 stdout/stderr 会让父进程读不到 EOF
            # 一直卡到超时。这里丢弃管道，让它立刻返回。
            try:
                subprocess.run(
                    ["wl-copy"], input=text.encode(),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=5, check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return {"text": f"写剪贴板失败：{exc}"}
            time.sleep(0.15)
            self._press("ctrl+v")
        return {"text": f"已输入 {len(text)} 个字符"}

    def _paste_text(self, text):
        try:
            subprocess.run(
                ["wl-copy"], input=text.encode(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"text": f"写剪贴板失败：{exc}"}
        time.sleep(0.15)
        self._press("ctrl+v")
        return {"text": f"已通过剪贴板粘贴 {len(text)} 个字符"}

    def _t_press_key(self, a):
        keys = str(a.get("keys", "")).strip()
        if not keys:
            return {"text": "按键为空"}
        if str(a.get("method", "auto")) == "keys":
            return self._press_keys_uinput(keys)
        self._press(keys)
        return {"text": f"已按键 {keys}"}

    def _press_keys_uinput(self, combo):
        parts = [p for p in combo.split("+") if p]
        mods = {"ctrl": 29, "control": 29, "alt": 56, "shift": 42, "super": 125,
                "meta": 125}
        named = {"backspace": 14, "return": 28, "enter": 28, "escape": 1,
                 "tab": 15, "space": 57, "delete": 111, "home": 102, "end": 107,
                 "up": 103, "down": 108, "left": 105, "right": 106,
                 "pageup": 104, "pagedown": 109, "insert": 110}
        held = []
        main = None
        for part in parts:
            low = part.lower()
            if low in mods:
                held.append(mods[low])
            elif low in named:
                main = named[low]
            elif low in _KEYS:
                main = _KEYS[low]
            elif len(low) == 1 and low in _SHIFTED:
                main = _KEYS[_SHIFTED[low]]
                held.append(42)
            elif low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 12:
                main = 58 + int(low[1:]) - 1
            else:
                return {"text": f"不认识的按键：{part}"}
        if main is None:
            return {"text": "缺少主键"}
        try:
            kb = UinputKeyboard()
        except OSError as exc:
            return {"text": f"无法打开 /dev/uinput：{exc}"}
        try:
            for code in held:
                kb._emit(code, 1)
            kb._tap(main)
            for code in reversed(held):
                kb._emit(code, 0)
            time.sleep(0.05)
        finally:
            kb.close()
        return {"text": f"已用真实键码按下 {combo}"}

    def _press(self, combo):
        parts = [p for p in re.split(r"\+|\s+", combo) if p]
        mods = [MODS[p.lower()] for p in parts[:-1] if p.lower() in MODS]
        key = parts[-1]
        argv = ["wtype"]
        for m in mods:
            argv += ["-M", m]
        argv += ["-k", key]
        for m in reversed(mods):
            argv += ["-m", m]
        rc, _, err = run(argv, timeout=15)
        if rc != 0:
            run(["wtype", "--", key], timeout=15)

    def _t_list_windows(self, a):
        lines = []
        for w in list_windows():
            marks = " *焦点*" if w.get("is_focused") else ""
            title = (w.get("title") or "")[:60]
            lines.append(f"{w.get('id')}  {w.get('app_id')}  {title}{marks}")
        return {"text": "\n".join(lines) or "没有窗口"}

    def _t_focus_window(self, a):
        wins = list_windows()
        target = None
        if a.get("id") is not None:
            target = next((w for w in wins if str(w.get("id")) == str(a["id"])), None)
        elif a.get("app_id"):
            needle = str(a["app_id"]).lower()
            target = next((w for w in wins if needle in (w.get("app_id") or "").lower()), None)
        elif a.get("title"):
            needle = str(a["title"]).lower()
            target = next((w for w in wins if needle in (w.get("title") or "").lower()), None)
        if not target:
            return {"text": "没找到这个窗口"}
        run(["niri", "msg", "action", "focus-window", "--id", str(target["id"])], timeout=5)
        return {"text": f"已聚焦 {target.get('app_id')}：{target.get('title')}"}


MUTATE_RE = re.compile(
    r"(^|[;&|]\s*)(rm|mv|cp|touch|mkdir|rmdir|chmod|chown|ln|truncate|"
    r"tee|install|dd|sed\s+-i)\b|>>?",
    re.IGNORECASE,
)

DANGER_RE = re.compile(
    r"(rm\s+-[a-zA-Z]*[rf]|sudo\b|mkfs|dd\s+if=|dd\s+of=|pacman\s+-R|yay\s+-R|"
    r"paru\s+-R|systemctl\s+(stop|disable|mask)|shutdown|reboot|poweroff|"
    r"killall|pkill|chmod\s+777|>\s*/etc/|truncate|fdisk|parted)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- 工具 schema

TOOLS = [
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "在工作区执行 bash 命令并返回输出。危险命令或工作区外写操作会先让用户确认。",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "timeout": {"type": "integer", "description": "超时秒数，默认 60"},
        }, "required": ["command"]},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "读取文本文件内容。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer", "description": "最多读取字符数，默认 20000"},
        }, "required": ["path"]},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "写入文件（默认工作区；写工作区外会请求确认）。会覆盖原内容。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        }, "required": ["path", "content"]},
    }},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "列出目录内容。",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "默认工作区"},
        }},
    }},
    {"type": "function", "function": {
        "name": "screenshot",
        "description": "截取整个屏幕给自己看。之后 click/move_mouse 的坐标用截图图片像素。",
        "parameters": {"type": "object", "properties": {
            "scale": {"type": "number", "description": "缩放，默认 0.6；要看小字/精确点击可临时用 0.8"},
        }},
    }},
    {"type": "function", "function": {
        "name": "click",
        "description": "用鼠标点击屏幕。坐标是最近一张截图的像素坐标。",
        "parameters": {"type": "object", "properties": {
            "x": {"type": "integer"}, "y": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "double": {"type": "boolean"},
        }, "required": ["x", "y"]},
    }},
    {"type": "function", "function": {
        "name": "move_mouse",
        "description": "移动鼠标（截图像素坐标），不点击。",
        "parameters": {"type": "object", "properties": {
            "x": {"type": "integer"}, "y": {"type": "integer"},
        }, "required": ["x", "y"]},
    }},
    {"type": "function", "function": {
        "name": "scroll",
        "description": "滚动鼠标滚轮。dy 正数向下，负数向上。",
        "parameters": {"type": "object", "properties": {
            "dy": {"type": "integer"}, "dx": {"type": "integer"},
        }},
    }},
    {"type": "function", "function": {
        "name": "type_text",
        "description": "向当前焦点窗口输入文字。method=auto 默认（英文用 wtype，中文走剪贴板）；method=keys 用真实键码（noVNC/KVM 网页控制台、游戏等收不到文字时用）；method=paste 强制剪贴板粘贴。",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"},
            "method": {"type": "string", "enum": ["auto", "keys", "paste"]},
        }, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "press_key",
        "description": "按组合键，例如 ctrl+l、alt+Tab、Return、Escape。method=keys 用真实键码（noVNC/KVM 控制台等收不到按键时用）。",
        "parameters": {"type": "object", "properties": {
            "keys": {"type": "string"},
            "method": {"type": "string", "enum": ["auto", "keys"]},
        }, "required": ["keys"]},
    }},
    {"type": "function", "function": {
        "name": "list_windows",
        "description": "列出当前所有窗口（id、app_id、标题、是否焦点）。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "focus_window",
        "description": "切换焦点到某个窗口，可按 id / app_id / 标题片段。",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "integer"},
            "app_id": {"type": "string"},
            "title": {"type": "string"},
        }},
    }},
]
