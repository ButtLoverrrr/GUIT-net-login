"""诊断探针 v2：聚焦 numpy 扩展模块为何在冻结环境里加载失败。"""
import ctypes
import os
import sys
import traceback

LOG = os.environ.get('SLIM_PROBE_LOG') or os.path.join(os.path.expanduser('~'), 'slim_probe2.log')
_lines = []


def w(msg):
    _lines.append(str(msg))
    try:
        with open(LOG, 'w', encoding='utf-8') as fp:
            fp.write('\n'.join(_lines))
    except Exception:
        pass


MP = getattr(sys, '_MEIPASS', '.')
w('meipass = %r' % MP)
for sub in ('numpy', os.path.join('numpy', 'linalg'), 'numpy.libs', 'numpy', os.path.join('numpy', '_core')):
    p = os.path.join(MP, sub)
    try:
        w('listdir %-22s = %r' % (sub, sorted(os.listdir(p))[:22]))
    except Exception as exc:
        w('listdir %-22s FAILED %r' % (sub, exc))

pyd = os.path.join(MP, 'numpy', 'linalg', '_umath_linalg.cp313-win_amd64.pyd')
w('_umath_linalg.pyd exists=%s size=%s' % (os.path.exists(pyd), os.path.getsize(pyd) if os.path.exists(pyd) else None))
if os.path.exists(pyd):
    try:
        ctypes.WinDLL(pyd)
        w('ctypes.WinDLL(_umath_linalg.pyd) OK')
    except Exception:
        w('ctypes.WinDLL(_umath_linalg.pyd) FAILED:\n%s' % traceback.format_exc())

ob = os.path.join(MP, 'numpy.libs')
for dll in sorted(os.listdir(ob)) if os.path.isdir(ob) else []:
    try:
        ctypes.WinDLL(os.path.join(ob, dll))
        w('WinDLL %-40s OK' % dll)
    except Exception as exc:
        w('WinDLL %-40s FAILED %r' % (dll, exc))

try:
    import numpy.linalg._umath_linalg as m
    w('import numpy.linalg._umath_linalg OK -> %r' % (m,))
except Exception:
    w('import numpy.linalg._umath_linalg FAILED:\n%s' % traceback.format_exc())

try:
    import numpy
    w('import numpy OK version=%s file=%s' % (numpy.__version__, numpy.__file__))
except Exception:
    w('import numpy FAILED:\n%s' % traceback.format_exc())
    try:
        import numpy._core._multiarray_umath as mu
        w('  但 numpy._core._multiarray_umath OK')
    except Exception:
        w('  numpy._core._multiarray_umath 也失败:\n%s' % traceback.format_exc())

w('done')
