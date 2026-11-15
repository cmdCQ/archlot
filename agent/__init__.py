"""对话层：对外只暴露 Agent。"""

from .history import MessageHistory
from .loop import Agent

__all__ = ["Agent", "MessageHistory"]
