"""端到端（真实 ddddocr + 真实 urllib + 模拟门户，进程内）：验证"识别→提交→门户确认"闭环。

不依赖真实校园网；不写用户系统；config 只存在于内存。
"""
import json
import os
import sys
import time

PROJ = r'<本机路径>'
TARGET = sys.argv[1] if len(sys.argv) > 1 else r'<本机路径>'
sys.path.insert(0, os.path.join(PROJ, 'tests'))
sys.path.insert(0, TARGET)
sys.path.insert(0, PROJ)

import support                      # noqa: E402
import portal_client                # noqa: E402

portal_client.ONLINE_PROBES = ()    # 只信任用例内的探测源
portal = support.MockPortal()
cfg = portal.config()
portal.state.online = False
if '--lenient' in sys.argv:
    # 合成验证码不在 ddddocr 训练分布内；联调时放行任意验证码，只为验证协议闭环
    portal.state.accept_any_captcha = True

import app as appmod                # noqa: E402
appmod.load_config = lambda: json.loads(json.dumps(cfg))
lines = []
appmod.toast = lambda *a, **k: None

# OCR 可用性走正式装配入口（OCR 已解耦为可插拔接口，见 src/ocr.py 与
# docs/ocr-interface.md）：这里必须与 run_silent() 用**同一份配置**，
# 否则报告里的 ocr_available 与真实登录路径可能不是同一个后端。
_ocr_cfg = json.loads(json.dumps(cfg))
ocr_engine = appmod.build_ocr_engine(_ocr_cfg)

t0 = time.time()
rc = appmod.run_silent()
dt = time.time() - t0

report = {
    'target': TARGET,
    'return_code': rc,
    'seconds': round(dt, 2),
    'portal_online_after': portal.state.online,
    'login_posts': portal.state.login_posts,
    'requests': [(m, p) for m, p, _f in portal.state.requests],
    'ocr_backend': getattr(ocr_engine, 'name', ''),
    'ocr_available': ocr_engine.available(),
}
print('E2E ' + json.dumps(report, ensure_ascii=False), flush=True)
for m, p, f in portal.state.requests:
    if m == 'POST' and p == '/login':
        print('  POST /login 表单键=', sorted(f.keys()), flush=True)
        print('  验证码字段值=', f.get('ctl00$MainContent$TextBoxCC'), ' 账号=', f.get('ctl00$MainContent$SSOACC'), flush=True)
portal.stop()
