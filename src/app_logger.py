# -*- coding: utf-8 -*-
"""日志：只在界面显示，**不写任何文件**。

设计约束（用户要求）：程序不在使用者电脑上产生额外文件，因此日志不落盘。
日志通过 sink 回调交给界面日志区；静默模式（--silent）没有 sink 时直接丢弃。
"""


class Logger:
    """日志转发器：把消息交给 sink（GUI 用于显示到日志区）。"""

    def __init__(self, tag: str = "", sink=None):
        self._tag = tag  # 来源标识（GUI / SILENT），无 sink 时仅作语义标记
        self._sink = sink  # callable(str) -> None，可为 None

    def set_sink(self, sink) -> None:
        self._sink = sink

    def log(self, message: str, level: str = "INFO") -> None:
        if not self._sink:
            return
        prefix = {"WARN": "[!] ", "ERROR": "[x] "}.get(level, "")
        try:
            self._sink(prefix + message)
        except Exception:
            # 日志失败绝不影响主流程
            pass

    def info(self, message: str) -> None:
        self.log(message, "INFO")

    def warn(self, message: str) -> None:
        self.log(message, "WARN")

    def error(self, message: str) -> None:
        self.log(message, "ERROR")
