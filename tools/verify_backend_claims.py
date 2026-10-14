"""独立核验后端的两条性能/行为声明（不依赖 subagent 自己的用例）：

1) 注销确认的最坏等待：门户状态「未知」+ 探测源不可达时，submit_logoff 的墙钟耗时
   （原始实现 = 4s x 3 = 12s；声称改后 <= 6s）
2) prepare_logoff 对注销页的 GET 次数（声称从 2 次降到 1 次）
"""
import json
import os
import sys
import tempfile
import time

TARGET = sys.argv[1]
PROJ = r'<本机路径>'
sys.path.insert(0, os.path.join(PROJ, 'tests'))
sys.path.insert(0, PROJ)

import support        # noqa: E402

sb = support.Sandbox(tempfile.mkdtemp(prefix='verify-'))
sb.install()

# 关键：把 TARGET 提到 sys.path 最前并清掉已加载的模块，确保测的是 TARGET 的实现
for _m in ('portal_client', 'config_store', 'autostart', 'ocr_helper', 'app_logger'):
    sys.modules.pop(_m, None)
while PROJ in sys.path:
    sys.path.remove(PROJ)
sys.path.insert(0, TARGET)
import portal_client  # noqa: E402
portal_client.ONLINE_PROBES = ()
portal = support.MockPortal()
cfg = portal.config()
# 探测源指向一个必定连不上的端口 -> 「探测无法给出结论」
cfg['onlineProbe'] = {'url': 'http://127.0.0.1:1/connecttest.txt', 'expect': 'x', 'timeout': 2}
portal.state.online = True
portal.state.logoff_no_message = True
portal.state.status_unknown = True

sess = portal_client.LoginSession(cfg)
sess.prepare_logoff()
get_logoff_before = len([1 for m, p, _ in portal.state.requests if m == 'GET' and p == '/logoff'])

t0 = time.time()
result = sess.submit_logoff(support.portal_code(portal, sess.client))
dt = time.time() - t0
get_logoff_total = len([1 for m, p, _ in portal.state.requests if m == 'GET' and p == '/logoff'])

# 单独量一次 prepare_logoff 的注销页 GET 次数
portal.state.requests.clear()
sess2 = portal_client.LoginSession(cfg)
sess2.prepare_logoff()
prep_gets = len([1 for m, p, _ in portal.state.requests if m == 'GET' and p == '/logoff'])

print('VERIFY ' + json.dumps({
    'target': TARGET,
    'worst_case_logoff_seconds': round(dt, 2),
    'logoff_gets_during_submit': get_logoff_total - get_logoff_before,
    'prepare_logoff_get_count': prep_gets,
    'result_ok': result.ok,
    'message': result.message,
}, ensure_ascii=False))
portal.stop()
