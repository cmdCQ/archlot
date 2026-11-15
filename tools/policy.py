"""策略层：工具执行前唯一做决定的地方。

- 纯逻辑，不依赖 GTK / 网络 / 文件写入
- 每一条决定都有 reason，便于审计和测试
- 系统提示词里的策略段由 describe() 生成，避免两处规则漂移
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from core import system


@dataclass(frozen=True)
class Decision:
    action: str                 # allow | ask | deny
    reason: str = ""
    title: str = ""
    detail: str = ""


# 严格模式：这些一律确认
DANGER_RE = re.compile(
    r"(rm\s+-[a-zA-Z]*[rf]|sudo\b|\bsu\b|mkfs|dd\s+if=|dd\s+of=|pacman\s+-R|"
    r"yay\s+-R|paru\s+-R|systemctl\s+(stop|disable|mask)|shutdown|reboot|"
    r"poweroff|halt|killall|pkill|chmod\s+777|>\s*/etc/|truncate|fdisk|parted|"
    r"wipefs|mkswap|mv\s+[^\s]+\s+/dev/null|:\(\)\s*\{)",
    re.IGNORECASE,
)

# auto 模式：只拦真正不可逆/影响系统的
DANGER_AUTO_RE = re.compile(
    r"(sudo\b|\bsu\b|\bdoas\b|mkfs|wipefs|mkswap|fdisk|parted|sfdisk|"
    r"dd\s+of=|shutdown|reboot|poweroff|halt|init\s+0|"
    r"pacman\s+-(R|Rn|Rns|Rc|Rdd)|yay\s+-R|paru\s+-R|"
    r"systemctl\s+(poweroff|reboot|halt|kexec)|"
    r"chmod\s+-R\s+777\s+/|chown\s+-R\s+[^\s]+\s+/(etc|usr|boot|var|home)\b|"
    r">\s*/dev/sd|>\s*/etc/|:\(\)\s*\{)",
    re.IGNORECASE,
)

# 真正危险的目标：删这些才需要确认
CRITICAL_DIRS = ("/", "/home", "/etc", "/usr", "/boot", "/var", "/root", "/opt",
                 "/mnt", "/srv", "/lib", "/bin", "/sbin")
SYSTEM_PREFIX = ("/etc", "/usr", "/boot", "/var", "/root", "/opt", "/mnt",
                 "/srv", "/lib", "/bin", "/sbin", "/sys", "/proc", "/dev")

MUTATE_RE = re.compile(
    r"(^|[;&|]\s*)(rm|mv|cp|touch|mkdir|rmdir|chmod|chown|ln|truncate|"
    r"tee|install|dd|sed\s+-i)\b|>>?",
    re.IGNORECASE,
)


class Policy:
    def __init__(self, cfg):
        self.mode = cfg.confirm_mode
        self.workspace = os.path.abspath(os.path.expanduser(cfg.workspace))

    # ---------------------------------------------------------------- 路径

    def _inside(self, path: str) -> bool:
        return path == self.workspace or path.startswith(self.workspace + os.sep)

    def resolve(self, path) -> str:
        return system.resolve_path(self.workspace, path)

    # ---------------------------------------------------------------- 判定

    def _dangerous_rm(self, cmd: str) -> bool:
        for m in re.finditer(r"\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s+(.+)", cmd):
            for raw in re.findall(r"[^\s;|&]+", m.group(1)):
                if raw.startswith("-"):
                    continue
                if not (raw.startswith("/") or raw.startswith("~")):
                    continue
                path = os.path.abspath(os.path.expanduser(raw))
                if self._inside(path):
                    continue
                if path.startswith(("/tmp", "/dev/null", "/var/tmp")):
                    continue
                # 家目录里的具体子目录可以删；只有系统目录、整个 home、根目录才拦
                if path in CRITICAL_DIRS:
                    return True
                if path.startswith(SYSTEM_PREFIX):
                    return True
        return False

    def is_dangerous(self, cmd: str) -> bool:
        return bool(DANGER_AUTO_RE.search(cmd)) or self._dangerous_rm(cmd)

    def outside_write(self, cmd: str) -> str | None:
        """命令里出现工作区外的绝对路径、且命令看起来会改文件时，返回那个路径。"""
        if not MUTATE_RE.search(cmd):
            return None
        for m in re.finditer(r"""(?<![\w-])((?:~|/)[^\s;|&<>"']*)""", cmd):
            path = self.resolve(m.group(1))
            if self._inside(path):
                continue
            if path.startswith(("/tmp/", "/dev/", "/proc/", "/sys/", "/run/")):
                continue
            return path
        return None

    def review(self, tool: str, args: dict) -> Decision:
        if tool == "run_shell":
            cmd = str(args.get("command", "")).strip()
            if not cmd:
                return Decision("allow", "empty")
            if self.mode == "strict" and DANGER_RE.search(cmd):
                return Decision("ask", "dangerous_command",
                                "要执行这条命令吗？", cmd)
            if self.is_dangerous(cmd):
                return Decision("ask", "dangerous_command",
                                "要执行这条命令吗？", cmd)
            outside = self.outside_write(cmd)
            if outside and self.mode == "strict":
                return Decision("ask", f"outside_write:{outside}",
                                f"这条命令会改动工作区外的 {outside}，确定吗？",
                                cmd)
            return Decision("allow",
                            f"outside_write:{outside}" if outside else "")

        if tool == "write_file":
            path = self.resolve(args.get("path", ""))
            if not self._inside(path):
                if self.mode == "strict":
                    return Decision("ask", "outside_write",
                                    "要写工作区外的文件吗？", path)
                return Decision("allow", "outside_write")
            return Decision("allow")

        return Decision("allow")

    def describe(self) -> str:
        if self.mode == "strict":
            return ("当前是严格审查模式：可能改动系统或工作区外文件的命令，"
                    "执行前都会让用户确认。")
        return ("当前是 auto 审查模式：普通命令和工作区外的常规写入直接执行，"
                "结果里会标注工作区外的改动；只有 sudo、mkfs、dd、关机重启、"
                "卸载软件包、删除系统目录这类真正危险的操作才让用户确认。")
