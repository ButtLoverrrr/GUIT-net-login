"""诊断探针：作为冻结 exe 的入口脚本运行，把冻结环境的关键信息与导入结果写入日志文件。"""
import os
import sys
import traceback

LOG = os.environ.get('SLIM_PROBE_LOG') or os.path.join(os.path.expanduser('~'), 'slim_probe.log')
_lines = []


def w(msg):
    _lines.append(str(msg))
    try:
        with open(LOG, 'w', encoding='utf-8') as fp:
            fp.write('\n'.join(_lines))
    except Exception:
        pass


w('frozen = %r' % (getattr(sys, 'frozen', None),))
w('executable = %r' % (sys.executable,))
w('meipass = %r' % (getattr(sys, '_MEIPASS', None),))
w('prefix = %r' % (sys.prefix,))
w('path = %r' % (sys.path,))
w('argv = %r' % (sys.argv,))
w('env TCL_LIBRARY = %r' % (os.environ.get('TCL_LIBRARY'),))
try:
    meipass = getattr(sys, '_MEIPASS', '.')
    w('meipass top-level = %r' % (sorted(os.listdir(meipass))[:80],))
    inner = os.path.join(meipass, '_internal')
    if os.path.isdir(inner):
        w('_internal top-level = %r' % (sorted(os.listdir(inner))[:80],))
except Exception:
    w('listdir failed:\n%s' % traceback.format_exc())

for mod in ('encodings.utf_8', 'zlib', 'struct', 'ctypes', 'socket', 'ssl', 'hashlib',
            'tkinter', 'tkinter.constants', 'app_logger', 'config_store', 'ocr_helper',
            'portal_client', 'autostart', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'PIL.ImageDraw',
            'pystray', 'numpy', 'onnxruntime', 'ddddocr'):
    try:
        __import__(mod)
        w('import %-20s OK' % mod)
    except Exception:
        w('import %-20s FAILED:\n%s' % (mod, traceback.format_exc()))

try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.update()
    w('Tk 可用；tk 版本 = %s' % root.tk.call('info', 'patchlevel'))
    root.destroy()
except Exception:
    w('Tk 初始化失败:\n%s' % traceback.format_exc())

w('probe done')
