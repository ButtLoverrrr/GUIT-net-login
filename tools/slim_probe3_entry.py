"""诊断探针 v3：在冻结 exe 内直接调用应用的静默流程，输出配置/会话/结果。"""
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
    import config_store
    import ocr_helper
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
    try:
        w('OcrEngine.available -> %r' % ocr_helper.OcrEngine().available())
    except Exception:
        w('OcrEngine raised:\n%s' % traceback.format_exc())

    import app
    try:
        w('run_silent -> %r' % app.run_silent())
    except Exception:
        w('run_silent raised:\n%s' % traceback.format_exc())
except Exception:
    w('FATAL:\n%s' % traceback.format_exc())
w('done')
