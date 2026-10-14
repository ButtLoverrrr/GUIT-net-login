'''开机自启：在「启动」文件夹创建 / 删除快捷方式。

用户已明确选择该实现方式（见 docs/PLAN.md 第 1 节「开机自启实现」），
**不写注册表**，删除快捷方式即完成回滚。

.lnk 通过系统自带 PowerShell 的 WScript.Shell COM 创建，无第三方依赖；
若 COM 创建失败，回退为等价的 .cmd（功能一致，仅载体不同）。
'''

import os
import subprocess
import sys
LNK_NAME = '校园网自动登录.lnk'
CMD_NAME = '校园网自动登录.cmd'
AUTOSTART_ARG = '--autostart'
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
POWERSHELL_TIMEOUT = 15

def _ps_quote(value: str) -> str:
    '''把字符串安全嵌进 PowerShell 单引号字面量（内部单引号要写两遍）。

    用户名 / 安装路径里出现 `'` 时，不加转义会让 PowerShell 直接报语法错误，
    自启创建或读回都会失败。
    '''

    return "'%s'" % str(value).replace("'", "''")

def startup_dir() -> str:
    '''当前用户的「启动」文件夹路径。'''

    return os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')

def lnk_path() -> str:
    return os.path.join(startup_dir(), LNK_NAME)

def cmd_path() -> str:
    return os.path.join(startup_dir(), CMD_NAME)

def is_enabled() -> bool:
    return os.path.exists(lnk_path()) or os.path.exists(cmd_path())

def _launch_command() -> tuple:
    '''返回 (可执行文件, 参数字符串, 工作目录)。

    打包运行：目标为 exe 自身；开发运行：目标为 pythonw（无控制台窗口）+ app.py。
    '''

    if getattr(sys, 'frozen', False):
        exe = os.path.abspath(sys.executable)
        return exe, AUTOSTART_ARG, os.path.dirname(exe)
    pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    exe = pyw if os.path.exists(pyw) else sys.executable
    app_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
    return exe, f'"{app_py!s}" {AUTOSTART_ARG!s}', os.path.dirname(app_py)

def enable() -> tuple:
    '''创建开机自启快捷方式，返回 (是否成功, 说明)。'''

    try:
        os.makedirs(startup_dir(), exist_ok=True)
    except Exception as exc:
        return False, '无法访问启动文件夹：%s' % exc
    exe, args, workdir = _launch_command()
    script = ("$ws = New-Object -ComObject WScript.Shell;"
              "$sc = $ws.CreateShortcut($env:GUIT_LNK);"
              "$sc.TargetPath = %s;$sc.Arguments = %s;$sc.WorkingDirectory = %s;"
              "$sc.WindowStyle = 7;$sc.Save()") % (_ps_quote(exe), _ps_quote(args), _ps_quote(workdir))
    try:
        env = dict(os.environ)
        env['GUIT_LNK'] = lnk_path()
        completed = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, timeout=POWERSHELL_TIMEOUT, creationflags=CREATE_NO_WINDOW, env=env)
        if completed.returncode == 0 and os.path.exists(lnk_path()):
            return True, lnk_path()
    except Exception:
        pass
    try:
        with open(cmd_path(), 'w', encoding='utf-8', newline='\r\n') as fp:
            fp.write('@echo off\r\n')
            fp.write(f'start "" "{exe!s}" {args!s}\r\n')
    except Exception as exc:
        return False, '创建自启失败：%s' % exc
    return True, cmd_path()

def read_lnk() -> tuple:
    '''读取现有 .lnk 的 (TargetPath, Arguments)；读不到返回 ("", "")。

    路径通过环境变量 GUIT_LNK 传给 PowerShell：路径里可能有中文/单引号，
    拼进脚本字面量会被 PowerShell 自行转码，非 ASCII 路径读回来是乱码
    （实测：解析出的 TargetPath 与真实路径不符，ensure_current 会误判）。
    '''

    path = lnk_path()
    if not os.path.exists(path):
        return ('', '')
    script = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
              "$ws = New-Object -ComObject WScript.Shell;"
              "$sc = $ws.CreateShortcut($env:GUIT_LNK);"
              "Write-Output ($sc.TargetPath + '|' + $sc.Arguments)")
    try:
        env = dict(os.environ)
        env['GUIT_LNK'] = path
        completed = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, timeout=POWERSHELL_TIMEOUT, creationflags=CREATE_NO_WINDOW, env=env)
        text = (completed.stdout or b'').decode('utf-8-sig', 'replace').strip()
        if '|' in text:
            target, args = text.split('|', 1)
            return target.strip(), args.strip()
    except Exception:
        pass
    return ('', '')


def ensure_current() -> tuple:
    '''自启项必须指向**当前正在运行的这个程序**，否则重建它。

    为什么需要：早期版本在源码模式下生成过指向 `pythonw.exe src/app.py` 的 .lnk，
    而源码模式的配置目录（项目根）并没有 config.json —— 开机自启时程序读不到
    账号，只会弹一个空窗口。启动时做一次校正即可自愈。
    '''

    if os.path.exists(cmd_path()) and not os.path.exists(lnk_path()):
        return enable()
    exe, _args, _workdir = _launch_command()
    target, current_args = read_lnk()
    # 读不到 TargetPath 时不能按「同一路径」处理：os.path.abspath('') 会返回
    # 当前工作目录，可能恰好等于 exe，从而把坏快捷方式当成正常项。
    same_target = bool(target) and os.path.normcase(os.path.abspath(target)) == os.path.normcase(exe)
    if same_target:
        if AUTOSTART_ARG in (current_args or ''):
            return True, '自启项已指向当前程序（%s）' % exe
    ok, message = enable()
    if ok:
        return True, '已把自启项校正为当前程序：%s' % exe
    return False, message


def disable() -> tuple:
    '''移除开机自启（两种载体都清理），返回 (是否成功, 说明)。'''

    removed = []
    for path in lnk_path(), cmd_path():
        try:
            if os.path.exists(path):
                os.remove(path)
                removed.append(os.path.basename(path))
        except Exception as exc:
            return False, f'删除 {os.path.basename(path)!s} 失败：{exc!s}'
    # 括号只是消歧义，语义与原来一致：有删到就报清单，否则报「本就没有」。
    return True, ('已移除：' + '、'.join(removed)) if removed else '本就没有自启项'
