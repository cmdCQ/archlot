"""系统机制：子进程、niri IPC、屏幕/窗口/图片信息。

这一层不包含任何策略，也不依赖 UI。
"""

from __future__ import annotations

import json
import os
import signal
import struct
import subprocess
import tempfile
import time

HOME = os.path.expanduser("~")
SHOT_DIR = os.path.join(tempfile.gettempdir(), f"archlot-shots-{os.getpid()}")


def new_shot_path():
    """每次截图一个独立文件；同一轮多张截图不能互相覆盖。"""
    os.makedirs(SHOT_DIR, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=SHOT_DIR, prefix="shot-", suffix=".jpg")
    os.close(fd)
    return path


def cleanup_shots():
    try:
        for name in os.listdir(SHOT_DIR):
            try:
                os.unlink(os.path.join(SHOT_DIR, name))
            except OSError:
                pass
    except OSError:
        pass


def _kill(p):
    """结束整个进程组，命令拉起的子进程也不会漏。"""
    try:
        os.killpg(p.pid, signal.SIGTERM)
    except OSError:
        try:
            p.terminate()
        except OSError:
            pass
    try:
        p.wait(timeout=0.5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        try:
            p.kill()
        except OSError:
            pass


def run(cmd, timeout=60, cwd=None, input_text=None, cancel=None):
    """跑子进程，返回 (rc, stdout, stderr)。

    用 Popen + 100ms 轮询而不是 subprocess.run：cancel 被设置时立刻
    结束整个进程组，不用等命令自己跑完。取消返回 130，超时返回 124。
    """
    try:
        p = subprocess.Popen(
            cmd, cwd=cwd or HOME,
            stdin=subprocess.PIPE if input_text is not None
            else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
    except FileNotFoundError as exc:
        return 127, "", f"找不到命令：{exc}"
    deadline = time.monotonic() + timeout
    pending = input_text
    while True:
        try:
            out, err = p.communicate(input=pending, timeout=0.1)
            return p.returncode, out or "", err or ""
        except subprocess.TimeoutExpired:
            # 重试 communicate 不会丢已经读到的输出。
            pending = None
            if cancel is not None and cancel.is_set():
                _kill(p)
                out, err = p.communicate()
                return 130, out or "", (err or "") + "已取消"
            if time.monotonic() >= deadline:
                _kill(p)
                out, err = p.communicate()
                return 124, out or "", (err or "") + f"超时（{timeout}s）"


def niri_json(*args, timeout=5):
    rc, out, _ = run(["niri", "msg", "-j", *args], timeout=timeout)
    if rc != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def screen_size():
    """整个 layout 的逻辑尺寸（grim 不带 -o 时截的就是这个范围）。"""
    outs = niri_json("outputs") or {}
    w = h = 0
    for out in outs.values():
        lg = out.get("logical") or {}
        if not lg:
            continue
        w = max(w, int(lg.get("x", 0)) + int(lg["width"]))
        h = max(h, int(lg.get("y", 0)) + int(lg["height"]))
    return (w, h) if w and h else (1920, 1080)


def list_windows():
    return niri_json("windows") or []


def image_size(path):
    """读取 PNG / JPEG 的宽高，只用标准库。"""
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


def resolve_path(workspace, path):
    """相对路径按工作区解析，绝对路径原样展开。"""
    path = os.path.expanduser(str(path or ""))
    if not os.path.isabs(path):
        path = os.path.join(workspace, path)
    return os.path.abspath(path)
