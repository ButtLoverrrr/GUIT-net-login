"""交付前终验（不弹窗）：把候选 exe 复制到临时目录，用模拟门户跑 --silent，检查协议闭环。

判定标准（宽松模式放行任意验证码）：
  rc == 0 且 门户收到 GET /logoff, GET /login, GET /CheckCode, POST /login 且门户转为在线
其中 POST /login 成功 => ddddocr + onnxruntime + numpy（含被移除的 OpenCV 兼容桩）在冻结环境里可用。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

PROJ = r'<本机路径>'
CAND = sys.argv[1] if len(sys.argv) > 1 else r'<本机路径>'

sys.path.insert(0, os.path.join(PROJ, 'tests'))
sys.path.insert(0, PROJ)
import support  # noqa: E402
import portal_client  # noqa: E402

portal_client.ONLINE_PROBES = ()
portal = support.MockPortal()
portal.state.accept_any_captcha = True          # 合成验证码不在 ddddocr 训练分布内
cfg = portal.config()

work = tempfile.mkdtemp(prefix='final-check-')
exe = os.path.join(work, 'app.exe')
shutil.copy2(CAND, exe)
open(os.path.join(work, 'config.json'), 'w', encoding='utf-8').write(json.dumps(cfg, ensure_ascii=False, indent=2))

t0 = time.time()
try:
    p = subprocess.run([exe, '--silent'], cwd=work, capture_output=True, timeout=120,
                       text=True, encoding='utf-8', errors='replace')
    rc = p.returncode
    err = (p.stderr or '')[-500:]
except subprocess.TimeoutExpired as exc:
    rc = 'TIMEOUT'
    err = (exc.stderr or b'')[-500:]

reqs = [(m, q) for m, q, _f in portal.state.requests]
print('candidate        : %s (%d bytes)' % (CAND, os.path.getsize(CAND)))
print('rc               : %s   elapsed %.1fs' % (rc, time.time() - t0))
print('stderr tail      : %s' % err)
print('portal requests  : %s' % reqs)
print('portal online    : %s   login_posts=%d' % (portal.state.online, portal.state.login_posts))
ok = (rc == 0 and portal.state.login_posts >= 1 and portal.state.online
      and ('GET', '/CheckCode') in reqs and ('POST', '/login') in reqs)
print('VERDICT          :', 'PASS (冻结 exe 内 OCR/HTTP/配置/登录闭环全部可用)' if ok else 'FAIL')
portal.stop()
shutil.rmtree(work, ignore_errors=True)
sys.exit(0 if ok else 1)
