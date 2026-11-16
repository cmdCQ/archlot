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
    r">\s*/dev/sd|>\s*/etc/|:\(\)\s*\{|"
    # 网络内容直接进解释器、批量通配删除、find -delete、kill -9 1
    r"\|\s*(?:ba|z|k|da)?sh\b|"
    r"(?:curl|wget|aria2c)\b[^\n]*\|\s*(?:python3?|perl|ruby|node)\b|"
    r"\bfind\b[^\n]*\s-delete\b|\brm\s+-[a-zA-Z]*\s+\*|"
    r"\bkill\s+-9\s+1\b)",
    re.IGNORECASE,
)

# 真正危险的目标：删这些才需要确认
CRITICAL_DIRS = ("/", "/home", "/etc", "/usr", "/boot", "/var", "/root", "/opt",
                 "/mnt", "/srv", "/lib", "/bin", "/sbin")
SYSTEM_PREFIX = ("/etc", "/usr", "/boot", "/var", "/opt", "/mnt",
                 "/srv", "/lib", "/bin", "/sbin", "/sys", "/proc", "/dev")


def _under(path: str, roots) -> bool:
    """按路径边界判断，避免 "/root" 误伤 "/rooted"、"/etc" 误伤 "/etc2"。"""
    for root in roots:
        if root == "/":
            return True
        if path == root or path.startswith(root + "/"):
            return True
    return False

MUTATE_RE = re.compile(
    r"(^|[;&|]\s*)(rm|mv|cp|touch|mkdir|rmdir|chmod|chown|ln|truncate|"
    r"tee|install|dd|sed\s+-i)\b|>>?",
    re.IGNORECASE,
)


class Policy:
    def __init__(self, cfg):
        self.mode = cfg.confirm_mode
        self.home = os.path.expanduser("~")
        self.workspace = os.path.abspath(os.path.expanduser(cfg.workspace))

    def _expand(self, raw: str) -> str:
        """只在开头把 ~ 换成家目录；Policy 构造后不再读环境变量。"""
        if raw == "~" or raw.startswith("~/"):
            return os.path.abspath(self.home + raw[1:])
        return os.path.abspath(os.path.expanduser(raw))

    # ---------------------------------------------------------------- 路径

    def _inside(self, path: str) -> bool:
        return path == self.workspace or path.startswith(self.workspace + os.sep)

    def resolve(self, path) -> str:
        return system.resolve_path(self.workspace, path)

    # ---------------------------------------------------------------- 判定

    # rm 的长短选项、无选项都要覆盖：rm --recursive --force /etc 与 rm /etc/passwd
    RM_RE = re.compile(r"\brm\s+((?:--?[\w-]+\s+)*)(.+)")

    def _critical_target(self, path: str) -> bool:
        """这是不是"不该被自动删掉"的路径。"""
        home = self.home
        # 自己的家目录里的子目录可以删；整个家目录不能
        if path == home:
            return True
        if path in CRITICAL_DIRS:
            return True
        if _under(path, SYSTEM_PREFIX):
            return True
        # 别人的家目录（多用户机器上常见）
        parts = path.split(os.sep)
        if len(parts) > 2 and parts[1] == "home" and not path.startswith(
                home + os.sep):
            return True
        return False

    def _dangerous_rm(self, cmd: str) -> bool:
        for m in self.RM_RE.finditer(cmd):
            targets = re.findall(r"[^\s;|&]+", m.group(1) + m.group(2))
            for raw in targets:
                if raw.startswith("-"):
                    continue
                if not (raw.startswith("/") or raw.startswith("~")):
                    continue
                path = self._expand(raw)
                if self._inside(path):
                    continue
                if path.startswith(("/tmp", "/dev/null", "/var/tmp")):
                    continue
                if self._critical_target(path):
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
            if outside and (self.mode == "strict"
                            or self._critical_target(outside)):
                return Decision("ask", f"outside_write:{outside}",
                                f"这条命令会改动工作区外的 {outside}，确定吗？",
                                cmd)
            return Decision("allow",
                            f"outside_write:{outside}" if outside else "")

        if tool == "write_file":
            path = self.resolve(args.get("path", ""))
            if not self._inside(path):
                if self.mode == "strict" or self._critical_target(path):
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
