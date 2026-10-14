"""启动性能 A/B 测量：对指定项目目录跑 N 次冷启动子进程，取中位数（import 与界面就绪）。

用法： py313 perf_ab.py <项目目录> [次数]
"""
import json
import os
import statistics
import subprocess
import sys

TARGET = sys.argv[1] if len(sys.argv) > 1 else r'<本机路径>'
N = int(sys.argv[2]) if len(sys.argv) > 2 else 5
PY = sys.executable
TOOLS = os.path.dirname(os.path.abspath(PY))

CODE = r'''
import json, os, sys, time
sys.path.insert(0, os.environ["TGT"])
t0 = time.perf_counter()
import app
t1 = time.perf_counter()
import tkinter as tk
root = tk.Tk(); root.withdraw()
ui = app.LoginApp(root)
root.update_idletasks()
t2 = time.perf_counter()
heavy = [m for m in ("ddddocr", "onnxruntime", "cv2", "numpy", "torch") if m in sys.modules]
sys.stdout.write("R" + json.dumps({"import": round(t1 - t0, 4), "ui_ready": round(t2 - t1, 4), "heavy": heavy}))
sys.stdout.flush()
os._exit(0)
'''

env_base = dict(os.environ)
env_base.update({
    'TGT': TARGET,
    'PYTHONIOENCODING': 'utf-8',
    'PYTHONUTF8': '1',
    'TCL_LIBRARY': os.path.join(TOOLS, '_tcl_data'),
    'TK_LIBRARY': os.path.join(TOOLS, '_tk_data'),
    'GUIT_INSTANCE_PORT': '48091',
})

imports, uis, heavy_seen = [], [], set()
for i in range(N):
    p = subprocess.run([PY, '-c', CODE], cwd=TARGET, env=env_base, capture_output=True, timeout=120,
                       text=True, encoding='utf-8', errors='replace')
    out = (p.stdout or '').strip().split('R')[-1]
    if not out:
        print('run', i, 'failed:', p.returncode, p.stderr[-500:])
        continue
    r = json.loads(out)
    imports.append(r['import'])
    uis.append(r['ui_ready'])
    heavy_seen.update(r['heavy'])

result = {
    'target': TARGET,
    'runs': len(imports),
    'import_median': round(statistics.median(imports), 4) if imports else None,
    'import_all': imports,
    'ui_ready_median': round(statistics.median(uis), 4) if uis else None,
    'ui_ready_all': uis,
    'heavy_loaded': sorted(heavy_seen),
}
print(json.dumps(result, ensure_ascii=False))
