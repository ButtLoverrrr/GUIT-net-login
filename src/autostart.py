# -*- coding: utf-8 -*-
"""开机自启：在「启动」文件夹创建 / 删除快捷方式。

用户已明确选择该实现方式（见 docs/PLAN.md 第 1 节「开机自启实现」），
**不写注册表**，删除快捷方式即完成回滚。

.lnk 通过系统自带 PowerShell 的 WScript.Shell COM 创建，无第三方依赖；
若 COM 创建失败，回退为等价的 .cmd（功能一致，仅载体不同）。
"""

import os
import subprocess
import sys

LNK_NAME = "校园网自动登录.lnk"
CMD_NAME = "校园网自动登录.cmd"
# 自启参数：正常打开界面，并在网络就绪后自动连接。
# （早期版本用 --silent：只登录、不显示窗口，用户看不到程序在不在跑）
AUTOSTART_ARG = "--autostart"
CREATE_NO_WINDOW = 0x08000000


def startup_dir() -> str:
    """当前用户的「启动」文件夹路径。"""
    return os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Startup",
    )


def lnk_path() -> str:
    return os.path.join(startup_dir(), LNK_NAME)


def cmd_path() -> str:
    return os.path.join(startup_dir(), CMD_NAME)


def is_enabled() -> bool:
    return os.path.exists(lnk_path()) or os.path.exists(cmd_path())


def _launch_command() -> tuple:
    """返回 (可执行文件, 参数字符串, 工作目录)。

    打包运行：目标为 exe 自身；开发运行：目标为 pythonw（无控制台窗口）+ app.py。
    """
    if getattr(sys, "frozen", False):
        exe = os.path.abspath(sys.executable)
        return exe, AUTOSTART_ARG, os.path.dirname(exe)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    app_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
    return exe, '"%s" %s' % (app_py, AUTOSTART_ARG), os.path.dirname(app_py)


def enable() -> tuple:
    """创建开机自启快捷方式，返回 (是否成功, 说明)。"""
    try:
        os.makedirs(startup_dir(), exist_ok=True)
    except Exception as exc:
        return False, "无法访问启动文件夹：%s" % exc

    exe, args, workdir = _launch_command()
    script = (
        "$ws = New-Object -ComObject WScript.Shell;"
        "$sc = $ws.CreateShortcut('%s');"
        "$sc.TargetPath = '%s';"
        "$sc.Arguments = '%s';"
        "$sc.WorkingDirectory = '%s';"
        "$sc.WindowStyle = 7;"
        "$sc.Save()"
    ) % (lnk_path(), exe, args, workdir)

    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        if completed.returncode == 0 and os.path.exists(lnk_path()):
            return True, lnk_path()
    except Exception:
        pass

    # 回退：写等价的 .cmd（target 与参数内联）
    try:
        with open(cmd_path(), "w", encoding="utf-8", newline="\r\n") as fp:
            fp.write("@echo off\r\n")
            fp.write('start "" "%s" %s\r\n' % (exe, args))
        return True, cmd_path()
    except Exception as exc:
        return False, "创建自启失败：%s" % exc


def read_lnk() -> tuple:
    """读取现有 .lnk 的 (TargetPath, Arguments)；读不到返回 ("", "")。"""
    path = lnk_path()
    if not os.path.exists(path):
        return "", ""
    # 先设 stdout 为 UTF-8：否则中文路径在 PowerShell 5.1 下会按 GBK 输出、解析错乱
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$ws = New-Object -ComObject WScript.Shell;"
        "$sc = $ws.CreateShortcut('%s');"
        "Write-Output ($sc.TargetPath + '|' + $sc.Arguments)" % path
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
        text = (completed.stdout or b"").decode("utf-8", "ignore").strip()
        if "|" in text:
            target, args = text.split("|", 1)
            return target.strip(), args.strip()
    except Exception:
        pass
    return "", ""


def ensure_current() -> tuple:
    """自启项必须指向**当前正在运行的这个程序**，否则重建它。

    为什么需要：早期版本在源码模式下生成过指向 `pythonw.exe src/app.py` 的 .lnk，
    而源码模式的配置目录（项目根）并没有 config.json —— 开机自启时程序读不到
    账号，只会弹一个空窗口。启动时做一次校正即可自愈。
    """
    if os.path.exists(cmd_path()) and not os.path.exists(lnk_path()):
        return enable()  # 旧的 .cmd 载体：重建为规范形态（.lnk）
    exe, _args, _workdir = _launch_command()
    target, current_args = read_lnk()
    same_target = os.path.normcase(os.path.abspath(target or "")) == os.path.normcase(exe)
    if same_target and AUTOSTART_ARG in (current_args or ""):
        return True, "自启项已指向当前程序（%s）" % exe
    ok, message = enable()
    if ok:
        return True, "已把自启项校正为当前程序：%s" % exe
    return False, message


def disable() -> tuple:
    """移除开机自启（两种载体都清理），返回 (是否成功, 说明)。"""
    removed = []
    for path in (lnk_path(), cmd_path()):
        try:
            if os.path.exists(path):
                os.remove(path)
                removed.append(os.path.basename(path))
        except Exception as exc:
            return False, "删除 %s 失败：%s" % (os.path.basename(path), exc)
    return True, ("已移除：" + "、".join(removed)) if removed else "本就没有自启项"
