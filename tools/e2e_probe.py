"""端到端取证：用**原始 exe**（以及源码态）去打我们自建的模拟门户，验证协议理解与配置格式。

做法：把 exe 复制到工作区（不污染用户目录），在同目录写 config.json 指向本机模拟门户，
以 --silent 运行，记录门户侧收到的请求流水与退出码。
"""
import json
import os
import shutil
import subprocess
import sys
import time

WORK = r'<本机路径>'
PROJ = r'<本机路径>'
EXE_SRC = r'<本机路径>'
PY313 = r'<本机路径>'
BASELINE = r'<本机路径>'

sys.path.insert(0, os.path.join(PROJ, 'tests'))
sys.path.insert(0, PROJ)
import support  # noqa: E402

os.makedirs(WORK, exist_ok=True)
target = os.path.join(WORK, 'GUIT-net-login-full.exe')
if not os.path.exists(target):
    print('copying exe into workspace ...', flush=True)
    shutil.copy2(EXE_SRC, target)

portal = support.MockPortal()
portal.state.online = False
if 'lenient' in sys.argv:
    # 合成验证码不在 ddddocr 训练分布内；联调时放行任意验证码，只为验证协议闭环
    portal.state.accept_any_captcha = True
cfg = portal.config()
cfg_path = os.path.join(WORK, 'config.json')
open(cfg_path, 'w', encoding='utf-8').write(json.dumps(cfg, ensure_ascii=False, indent=2))
print('mock portal at', portal.base, flush=True)
print('config written to', cfg_path, flush=True)

results = {}
if 'exe' in sys.argv:
    t0 = time.time()
    try:
        p = subprocess.run([target, '--silent'], cwd=WORK, capture_output=True, timeout=60)
        rc, err = p.returncode, p.stderr[-500:]
    except subprocess.TimeoutExpired as exc:
        rc, err = 'TIMEOUT', (exc.stderr or b'')
    results['exe'] = {'rc': rc, 'secs': round(time.time() - t0, 1), 'stderr': err.decode('utf-8', 'ignore')}
    print('exe result', results['exe'], flush=True)

if 'src' in sys.argv:
    # 源码态 app_dir() = 项目目录的上一级（config_store.app_dir() 的非打包语义）
    src_target = BASELINE
    for arg in sys.argv:
        if arg.startswith('--target='):
            src_target = arg.split('=', 1)[1]
    src_root = os.path.dirname(os.path.abspath(src_target))
    src_cfg = os.path.join(src_root, 'config.json')
    had_cfg = os.path.exists(src_cfg)
    open(src_cfg, 'w', encoding='utf-8').write(json.dumps(cfg, ensure_ascii=False, indent=2))
    print('src config ->', src_cfg, flush=True)
    t0 = time.time()
    env = dict(os.environ)
    env.update({'TCL_LIBRARY': r'<本机路径>',
                'TK_LIBRARY': r'<本机路径>',
                'GUIT_INSTANCE_PORT': '48011', 'PYTHONIOENCODING': 'utf-8'})
    try:
        p = subprocess.run([PY313, os.path.join(src_target, 'app.py'), '--silent'], cwd=src_root, env=env,
                           capture_output=True, timeout=60)
        rc = p.returncode
        err = p.stderr[-800:]
    except subprocess.TimeoutExpired as exc:
        rc, err = 'TIMEOUT', (exc.stderr or b'')
    results['src'] = {'rc': rc, 'secs': round(time.time() - t0, 1), 'stderr': err.decode('utf-8', 'ignore')}
    print('src result', results['src'], flush=True)
    if not had_cfg:
        try:
            os.remove(src_cfg)
            print('cleaned', src_cfg, flush=True)
        except OSError:
            pass

summary = {
    'base': portal.base,
    'online_after': portal.state.online,
    'login_posts': portal.state.login_posts,
    'logoff_posts': portal.state.logoff_posts,
    'requests': portal.state.requests[:40],
    'results': results,
}
open(os.path.join(WORK, 'e2e_report.json'), 'w', encoding='utf-8').write(json.dumps(summary, ensure_ascii=False, indent=1))
print('SUMMARY ' + json.dumps({k: v for k, v in summary.items() if k != 'requests'}, ensure_ascii=False), flush=True)
print('REQUESTS ' + json.dumps([(m, p_) for m, p_, _f in summary['requests']], ensure_ascii=False), flush=True)
portal.stop()
