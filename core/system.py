"""系统机制：子进程、niri IPC、屏幕/窗口/图片信息。

这一层不包含任何策略，也不依赖 UI。
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import tempfile

HOME = os.path.expanduser("~")
SHOT_PATH = os.path.join(
    tempfile.gettempdir(), f"archlot-shot-{os.getpid()}.jpg")


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
