"""诊断探针 v3：在冻结 exe 内直接调用应用的静默流程，输出配置/会话/结果。

OCR 已解耦为可插拔接口（见 src/ocr.py 与 docs/ocr-interface.md），因此本探针
不再直接构造 `ocr_helper.OcrEngine()`，改走正式装配入口 `app.build_ocr_engine(cfg)`
——与 `--silent` 走的是同一条装配路径，顺带报告装配到的后端名。
"""
import os
import sys
import traceback

LOG = os.environ.get('SLIM_PROBE_LOG') or os.path.join(os.path.expanduser('~'), 'slim_probe3.log')
_lines = []


def w(msg):
    _lines.append(str(msg))
    try:
        with open(LOG, 'w', encoding='utf-8') as fp:
            fp.write('\n'.join(_lines))
    except Exception:
        pass


try:
    import app
    import config_store
    import ocr
    import portal_client

    w('app_dir = %r' % config_store.app_dir())
    w('exe     = %r' % sys.executable)
    w('config exists = %s' % os.path.exists(config_store.config_path()))
    cfg = config_store.load_config()
    w('portalUrl=%r' % cfg.get('portalUrl'))
    w('captchaUrl=%r' % cfg.get('captchaUrl'))
    w('logoffUrl=%r' % cfg.get('logoffUrl'))
    w('onlineProbe=%r' % cfg.get('onlineProbe'))
    w('user=%r' % (cfg.get('user'),))
    w('has_credential=%s' % config_store.has_credential(cfg))
    w('ONLINE_PROBES=%r' % (portal_client.ONLINE_PROBES,))

    sess = portal_client.LoginSession(cfg)
    try:
        w('query_status -> %r' % (sess.query_status(),))
    except Exception:
        w('query_status raised:\n%s' % traceback.format_exc())
    try:
        w('is_online -> %r' % sess.is_online())
    except Exception:
        w('is_online raised:\n%s' % traceback.format_exc())
    try:
        w('needs_login -> %r' % sess.needs_login())
    except Exception:
        w('needs_login raised:\n%s' % traceback.format_exc())

    # 正式装配入口（接口层 src/ocr.py）：与 run_silent() 同一份配置。
    try:
        engine = app.build_ocr_engine(cfg)
        w('ocr backend = %r' % (getattr(engine, 'name', ''),))
        w('ocr available -> %r' % engine.available())
    except Exception:
        w('ocr engine raised:\n%s' % traceback.format_exc())
    try:
        w('available backends -> %r' % (ocr.available_backends(),))
    except Exception:
        w('available_backends raised:\n%s' % traceback.format_exc())

    try:
        w('run_silent -> %r' % app.run_silent())
    except Exception:
        w('run_silent raised:\n%s' % traceback.format_exc())
except Exception:
    w('FATAL:\n%s' % traceback.format_exc())
w('done')
