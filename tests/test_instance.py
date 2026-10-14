"""单实例行为回归护栏（主线独立用例）。

两个真实场景：
1) 第一实例正常应答 → 第二个进程把 show 发给它并退出 0；
2) 第一实例"占着端口但卡住不应答" → 第二个进程必须**扛住**（原始代码在读超时外有 try/except），
   绝不能因为 TimeoutError/ConnectionError 让 `import app` 直接崩掉。
"""
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

import support

PY = sys.executable


def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _spawn_import(port):
    env = dict(os.environ)
    env['GUIT_INSTANCE_PORT'] = str(port)
    env['PYTHONIOENCODING'] = 'utf-8'
    code = 'import sys; sys.path.insert(0, %r); import app' % support.PROJ
    return subprocess.run([PY, '-c', code], cwd=support.PROJ, env=env, capture_output=True,
                          timeout=60, text=True, encoding='utf-8', errors='replace')


def test_second_instance_gets_show_and_exits():
    port = _free_port()
    srv = socket.socket()
    srv.bind(('127.0.0.1', port))
    srv.listen(1)
    seen = []

    def serve():
        srv.settimeout(30)
        try:
            conn, _ = srv.accept()
            seen.append(conn.recv(16))
            conn.sendall(b'ok')
            conn.close()
        except Exception as exc:
            seen.append(('err', repr(exc)))

    threading.Thread(target=serve, daemon=True).start()
    try:
        p = _spawn_import(port)
        assert p.returncode == 0, (p.returncode, p.stderr[-600:])
        assert b'show' in b''.join(x for x in seen if isinstance(x, bytes)), seen
    finally:
        srv.close()


def test_second_instance_survives_stalled_first_instance():
    """第一实例卡住不应答时，第二个进程不能崩（原始代码有内层 try/except 兜住）。"""
    port = _free_port()
    srv = socket.socket()
    srv.bind(('127.0.0.1', port))
    srv.listen(1)

    def hold():
        srv.settimeout(30)
        try:
            conn, _ = srv.accept()
            time.sleep(30)          # 收到连接但永不回 'ok'
        except Exception:
            pass

    threading.Thread(target=hold, daemon=True).start()
    t0 = time.time()
    try:
        p = _spawn_import(port)
        dt = time.time() - t0
    finally:
        srv.close()
    assert p.returncode == 0, (
        f'第一实例卡住时第二个进程崩了（rc={p.returncode}, {dt:.1f}s）:\n' + p.stderr[-900:])
    assert dt < 30, f'卡住时等待过久：{dt:.1f}s（应在读超时内放弃并继续启动）'
