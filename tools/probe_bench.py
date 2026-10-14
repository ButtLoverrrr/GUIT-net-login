"""独立核验：外网探测「慢源」下的墙钟耗时（原始串行 vs 重构后并发）。

构造 4 个"接受连接但永不响应"的本地监听端口作为探测源：
  串行实现 -> 4 x timeout
  并发实现 -> ≈ 1 x timeout
"""
import json
import os
import socket
import sys
import threading
import time

TARGET = sys.argv[1]
PROJ = r'<本机路径>'
sys.path.insert(0, os.path.join(PROJ, 'tests'))
sys.path.insert(0, PROJ)

import support        # noqa: E402

sb = support.Sandbox(os.path.join(os.environ.get('TEMP', '.'), 'verify-probe'))
sb.install()

# 关键：把 TARGET 提到 sys.path 最前并清掉已加载的模块，确保测的是 TARGET 的实现
for _m in ('portal_client', 'config_store', 'autostart', 'ocr_helper', 'app_logger'):
    sys.modules.pop(_m, None)
while PROJ in sys.path:
    sys.path.remove(PROJ)
sys.path.insert(0, TARGET)
import portal_client  # noqa: E402

servers = []
ports = []


def hang(sock):
    servers.append(sock)

    def loop():
        while True:
            try:
                conn, _ = sock.accept()
                threading.Thread(target=lambda c=conn: time.sleep(30), daemon=True).start()
            except Exception:
                return

    threading.Thread(target=loop, daemon=True).start()


for _ in range(4):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', 0))
    s.listen(4)
    ports.append(s.getsockname()[1])
    hang(s)

# 自检：4 个源必须都是"能连上但不应答"
alive = 0
for p in ports:
    c = socket.socket()
    c.settimeout(1)
    try:
        c.connect(('127.0.0.1', p))
        alive += 1
    except Exception:
        pass
    finally:
        c.close()
assert alive == 4, ('挂起源自检失败', ports, alive)
assert len(set(ports)) == 4, ports

portal = support.MockPortal()
cfg = portal.config()
cfg['onlineProbe'] = {'url': 'http://127.0.0.1:%d/x' % ports[0], 'expect': '', 'timeout': 2}
portal_client.ONLINE_PROBES = tuple(('http://127.0.0.1:%d/x' % p, '') for p in ports[1:])
client = portal_client.PortalClient(cfg)
t0 = time.time()
result = client.is_online()
dt = time.time() - t0
print('PROBE-BENCH ' + json.dumps({'target': TARGET, 'seconds': round(dt, 2), 'result': result,
                                   'sources': len(ports), 'per_source_timeout': 2}, ensure_ascii=False))
for s in servers:
    try:
        s.close()
    except Exception:
        pass
portal.stop()
