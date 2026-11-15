"""界面层：对外只暴露 Panel。

Panel 延迟导入，这样 `ui.markdown` 之类的纯逻辑模块
在没有 GTK 的环境里也能单独使用（测试、CI、静态检查）。
"""

__all__ = ["Panel"]


def __getattr__(name):
    if name == "Panel":
        from .panel import Panel
        return Panel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
