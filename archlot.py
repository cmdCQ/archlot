#!/usr/bin/env python3
"""Archlot 入口：解析命令行，把各模块接起来。"""

from __future__ import annotations

import logging
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gio, Gtk  # noqa: E402

from agent import Agent  # noqa: E402
from core.config import (APP_ID, ARCHLOT_VERSION, LOG_PATH,  # noqa: E402
                         Config)
from core.contracts import ToolContext  # noqa: E402
from core.memory import Memory  # noqa: E402
from tools import Tools  # noqa: E402
from tools.policy import Policy  # noqa: E402
from ui import Panel  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
CSS_PATH = os.path.join(BASE, "style.css")


def setup_logging():
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        logging.basicConfig(
            filename=LOG_PATH, level=logging.INFO,
            format=fmt, datefmt="%H:%M:%S")
    except OSError:
        logging.basicConfig(level=logging.INFO, format=fmt,
                            datefmt="%H:%M:%S")


class Archlot(Gtk.Application):
    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.cfg = Config.load()
        os.makedirs(self.cfg.workspace, exist_ok=True)
        self.panel = None
        self.agent = None

    def do_command_line(self, cmdline):
        args = cmdline.get_arguments()[1:]
        self.ensure_ui()
        if "--setup" in args:
            self.panel.open_setup()
        elif "--toggle" in args:
            self.panel.toggle()
        elif "--daemon" in args:
            pass
        else:
            self.panel.show()
        return 0

    def ensure_ui(self):
        if self.panel is not None:
            return
        memory = Memory()
        policy = Policy(self.cfg)
        panel = Panel(self, self.cfg, CSS_PATH)
        ctx = ToolContext(
            workspace=self.cfg.workspace,
            policy=policy,
            confirm=panel.confirm,
            panel=panel,
            memory=memory,
            before_shot=panel.hide_for_shot,
            after_shot=panel.show_after_shot,
            max_tool_seconds=self.cfg.max_tool_seconds,
        )
        tools = Tools(ctx)
        agent = Agent(self.cfg, panel, tools, memory, policy)
        panel.agent = agent
        self.panel = panel
        self.agent = agent


def main():
    if "--version" in sys.argv:
        print(f"Archlot {ARCHLOT_VERSION}")
        return 0
    setup_logging()
    app = Archlot()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
