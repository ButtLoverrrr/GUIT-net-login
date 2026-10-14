"""静默模式（--silent / run_silent）测试：不弹系统对话框、走本地模拟门户。

覆盖三条返回码语义：0 = 已连接、1 = 登录失败、3 = 需要界面（未配置或需手输验证码）。
"""
import json
import tempfile

import support


class _StubOcr:
    def __init__(self, portal, mode='right'):
        self.portal = portal
        self.mode = mode

    def available(self):
        return self.mode != 'absent'

    def classify(self, png):
        if self.mode == 'right':
            return support.last_issued(self.portal)
        return 'ZZZZ'


def _boot(mode='right'):
    sb = support.Sandbox(tempfile.mkdtemp(prefix='guit-silent-'))
    sb.install()
    import app as appmod
    support.patch_app_sandbox(appmod, sb.tmp)
    portal = support.MockPortal()
    cfg = portal.config()
    appmod.load_config = lambda: json.loads(json.dumps(cfg))
    appmod.toast = lambda *a, **k: None            # 绝不弹真实系统对话框
    appmod.OcrEngine = lambda *a, **k: _StubOcr(portal, mode)
    return sb, appmod, portal, cfg


def test_silent_success_returns_zero():
    sb, appmod, portal, cfg = _boot('right')
    try:
        portal.state.online = False
        assert appmod.run_silent() == 0, '识别成功应返回 0'
        assert portal.state.online is True, '必须真的向门户提交登录'
    finally:
        portal.stop()


def test_silent_needs_manual_returns_three():
    sb, appmod, portal, cfg = _boot('wrong')
    try:
        portal.state.online = False
        assert appmod.run_silent() == 3, '识别失败应转界面（返回 3）'
        assert portal.state.online is False
    finally:
        portal.stop()


def test_silent_without_credential_returns_three():
    sb, appmod, portal, cfg = _boot('right')
    try:
        cfg['user'] = {'guid': '', 'acc': '', 'pwd': ''}
        assert appmod.run_silent() == 3, '未配置账号应转界面'
        assert portal.state.login_posts == 0, '未配置时不得发起登录请求'
    finally:
        portal.stop()


def test_silent_already_online_returns_zero():
    sb, appmod, portal, cfg = _boot('right')
    try:
        portal.state.online = True
        assert appmod.run_silent() == 0
        assert portal.state.login_posts == 0, '已联网时不应重复提交登录'
    finally:
        portal.stop()


def test_silent_ocr_absent_returns_three():
    sb, appmod, portal, cfg = _boot('absent')
    try:
        portal.state.online = False
        assert appmod.run_silent() == 3, '无 OCR 引擎（lite 构建）应转界面手输'
    finally:
        portal.stop()
