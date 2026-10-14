"""启动性能基线测试：冷启动导入耗时、界面构建耗时、重型依赖是否被拖进启动路径。

基线写在 tests/perf_baseline.json（首次运行生成）。当前值超过基线 25%+0.10s 即判定回归。
"""
import json
import os
import subprocess
import sys
import tempfile

import support

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = support.PROJ
BASELINE = os.path.join(HERE, 'perf_baseline.json')
HEAVY = ('ddddocr', 'onnxruntime', 'cv2', 'torch', 'numpy')

_IMPORT_CODE = r'''
import json, os, sys, time
sys.path.insert(0, os.environ["GUIT_PROJ"])
t0 = time.perf_counter()
import app
t1 = time.perf_counter()
print(json.dumps({"import": round(t1 - t0, 4),
                  "heavy_loaded": [m for m in ("ddddocr", "onnxruntime", "cv2", "torch", "numpy") if m in sys.modules]}))
'''

_BOOT_CODE = r'''
import json, os, sys, time
sys.path.insert(0, os.environ["GUIT_PROJ"])
os.environ.setdefault("GUIT_INSTANCE_PORT", "47899")
import tkinter as tk
t0 = time.perf_counter()
import app
t1 = time.perf_counter()
root = tk.Tk()
root.withdraw()
ui = app.LoginApp(root)
root.update_idletasks()
t2 = time.perf_counter()
out = {"import": round(t1 - t0, 4), "ui_ready": round(t2 - t1, 4),
       "heavy_loaded": [m for m in ("ddddocr", "onnxruntime", "cv2", "torch", "numpy") if m in sys.modules]}
sys.stdout.write("RESULT" + json.dumps(out))
sys.stdout.flush()
os._exit(0)
'''


def _run(code, env_extra=None):
    env = dict(os.environ)
    env['GUIT_PROJ'] = PROJ
    env['PYTHONIOENCODING'] = 'utf-8'
    env['GUIT_INSTANCE_PORT'] = str(support._free_port())
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([sys.executable, '-c', code], cwd=PROJ, env=env,
                       capture_output=True, timeout=120, text=True, encoding='utf-8', errors='replace')
    out = (p.stdout or '').strip().split('RESULT')[-1]
    if not out:
        raise AssertionError(f'未取到测量结果 rc={p.returncode}\nstdout={p.stdout}\nstderr={p.stderr[-2000:]}')
    return json.loads(out)


def _baseline():
    if os.path.exists(BASELINE):
        return json.load(open(BASELINE, encoding='utf-8'))
    return {}


def _record(key, value):
    data = _baseline()
    data[key] = value
    json.dump(data, open(BASELINE, 'w', encoding='utf-8'), indent=1)


def test_cold_start_import_time():
    r = _run(_IMPORT_CODE)
    base = _baseline().get('import')
    print(f'    [perf] import app = {r["import"]}s (基线 {base})')
    assert r['import'] < 5.0, f'导入耗时异常：{r["import"]}s'
    if base is None:
        _record('import', r['import'])
    else:
        assert r['import'] <= base * 1.25 + 0.10, f'导入耗时分回归：{r["import"]}s > 基线 {base}s'


def test_ui_ready_time():
    r = _run(_BOOT_CODE)
    base = _baseline().get('ui_ready')
    print(f'    [perf] 界面就绪 = {r["ui_ready"]}s (基线 {base})')
    assert r['ui_ready'] < 5.0, f'界面就绪耗时异常：{r["ui_ready"]}s'
    if base is None:
        _record('ui_ready', r['ui_ready'])
    else:
        assert r['ui_ready'] <= base * 1.25 + 0.10, f'界面就绪回归：{r["ui_ready"]}s > 基线 {base}s'


def test_heavy_deps_not_loaded_at_startup():
    r = _run(_BOOT_CODE)
    assert r['heavy_loaded'] == [], f'启动路径不应加载重型依赖：{r["heavy_loaded"]}'
