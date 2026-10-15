"""核验：探测源"立即失败"（连接被拒）时，is_online 是否立刻返回而不是白等满 timeout 窗口。"""
import json
import os
import sys
import time

TARGET = sys.argv[1]
PROJ = r'<本机路径>'
sys.path.insert(0, os.path.join(PROJ, 'tests'))
sys.path.insert(0, PROJ)

import support  # noqa: E402

sb = support.Sandbox(os.path.join(os.environ.get('TEMP', '.'), 'verify-fast'))
sb.install()
# 'ocr'：OCR 接口层（portal_client 直接依赖）；'ocr_helper'：默认实现——都要清。
for _m in ('portal_client', 'config_store', 'autostart', 'ocr', 'ocr_helper', 'app_logger'):
    sys.modules.pop(_m, None)
while PROJ in sys.path:
    sys.path.remove(PROJ)
sys.path.insert(0, TARGET)
import portal_client  # noqa: E402

# 4 个必定被拒绝的端口
cfg = {'onlineProbe': {'url': 'http://127.0.0.1:1/a', 'expect': '', 'timeout': 4},
       'fields': {}, 'user': {}}
portal_client.ONLINE_PROBES = tuple(('http://127.0.0.1:%d/b' % p, '') for p in (2, 3, 4))
client = portal_client.PortalClient(cfg)
t0 = time.time()
r = client.is_online()
dt = time.time() - t0
print('FASTFAIL ' + json.dumps({'target': TARGET, 'seconds': round(dt, 2), 'result': r,
                                'source_timeout': 4}, ensure_ascii=False))
