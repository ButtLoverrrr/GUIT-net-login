# -*- coding: utf-8 -*-
"""日志：按月写入 logs/GUIT-net-login-YYYYMM.log（UTF-8 无 BOM，CRLF）。

采用朴素的文件追加，配合 GUI 回调把同一份消息显示到界面日志区。
"""

import datetime
import os
import threading

from config_store import log_dir


class Logger:
    """同时输出到文件与内存回调（GUI 用）。"""

    def __init__(self, tag: str = "", sink=None):
        self._lock = threading.Lock()
        self._tag = tag  # 来源标识，写入日志便于区分 GUI / SILENT 运行
        self._sink = sink  # callable(str) -> None，可为 None

    def set_sink(self, sink) -> None:
        self._sink = sink

    def _write_file(self, line: str) -> None:
        try:
            folder = log_dir()
            os.makedirs(folder, exist_ok=True)
            name = "GUIT-net-login-%s.log" % datetime.datetime.now().strftime("%Y%m")
            with open(os.path.join(folder, name), "a", encoding="utf-8", newline="\r\n") as fp:
                fp.write(line + "\r\n")
        except Exception:
            # 日志失败绝不影响主流程
            pass

    def log(self, message: str, level: str = "INFO") -> None:
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source = (" %s" % self._tag) if self._tag else ""
        line = "%s [%s]%s %s" % (stamp, level, source, message)
        with self._lock:
            self._write_file(line)
            if self._sink:
                try:
                    self._sink(line)
                except Exception:
                    pass

    def info(self, message: str) -> None:
        self.log(message, "INFO")

    def warn(self, message: str) -> None:
        self.log(message, "WARN")

    def error(self, message: str) -> None:
        self.log(message, "ERROR")
