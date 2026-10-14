"""后端测试：门户会话、配置、OCR、自启。全部走本地模拟门户，不碰真实校园网/系统。"""
import json
import os
import tempfile
import time

import support


def _env():
    sb = support.Sandbox(tempfile.mkdtemp(prefix='guit-be-'))
    cs = sb.install()
    import portal_client
    portal = support.MockPortal()
    cfg = portal.config()
    return sb, cs, portal_client, portal, cfg


def test_is_online_returns_early_when_all_probes_conclude_fast():
    """【主线收尾新增】所有探测源都已给出结论（例如连接被立即拒绝）时必须立刻返回 False，
    不再白等满 timeout 窗口 —— 未联网时这一等曾让「断开确认」多花 ~2s。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        calls = []
        real = pc._probe_reachable

        def fake(url, expect, timeout):
            calls.append(url)
            return False

        pc._probe_reachable = fake
        try:
            t0 = time.time()
            assert pc.PortalClient(cfg).is_online() is False
            dt = time.time() - t0
        finally:
            pc._probe_reachable = real
        assert len(calls) >= 1, calls
        assert dt < 0.5, f'探测全部有结论时应立即返回，实测 {dt:.2f}s'
    finally:
        portal.stop()


def test_is_online_still_waits_for_slow_sources():
    """反向护栏：源本身很慢（未出结论）时不能提前返回 False，仍须等到 timeout 并由命中决定。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        real = pc._probe_reachable

        def slow_hit(url, expect, timeout):
            time.sleep(0.3)
            return True

        pc._probe_reachable = slow_hit
        try:
            t0 = time.time()
            assert pc.PortalClient(cfg).is_online() is True
            dt = time.time() - t0
        finally:
            pc._probe_reachable = real
        assert 0.2 <= dt < 2.0, f'命中必须被采纳，实测 {dt:.2f}s'
    finally:
        portal.stop()


def test_ocr_available_is_thread_safe():
    """【主线收尾新增】预取线程与用户点击线程可能同时首次调用 available()：
    旧写法会让后到者误判「OCR 不可用」→ 明明能识别却要求手输验证码（已实测复现）。"""
    import sys
    import threading
    import time
    import types
    import ocr_helper

    fake = types.ModuleType('ddddocr')

    class _Engine:
        def __init__(self, show_ad=False):
            time.sleep(0.4)          # 放大初始化窗口

    fake.DdddOcr = _Engine
    old = sys.modules.get('ddddocr')
    sys.modules['ddddocr'] = fake
    try:
        engine = ocr_helper.OcrEngine()
        out = []
        barrier = threading.Barrier(3)

        def worker():
            barrier.wait()
            out.append(engine.available())

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        assert sorted(out) == [True, True, True], f'并发首次调用出现误判：{out}'
        assert engine.classify(b'') == ''
    finally:
        if old is None:
            sys.modules.pop('ddddocr', None)
        else:
            sys.modules['ddddocr'] = old


def test_config_defaults_and_roundtrip():
    sb, cs, pc, portal, cfg = _env()  # 第 3 个返回值是 portal_client 模块
    try:
        got = cs.load_config()
        assert got['portalUrl'] == cs.DEFAULT_CONFIG['portalUrl'], got['portalUrl']
        assert cs.has_credential(got) is False
        data = json.loads(json.dumps(cs.DEFAULT_CONFIG))
        data['user'] = {'guid': '1', 'acc': '2', 'pwd': '3'}
        cs.save_config(data)
        assert os.path.exists(os.path.join(sb.tmp, 'config.json'))
        back = cs.load_config()
        assert back['user']['pwd'] == '3', back['user']
        assert cs.has_credential(back) is True
        assert cs.remove_config() is True
        assert cs.remove_config() is False
        assert cs.has_credential(cs.load_config()) is False
    finally:
        portal.stop()


def test_config_corrupt_file_falls_back():
    sb, cs, pc, portal, cfg = _env()  # 第 3 个返回值是 portal_client 模块
    try:
        with open(os.path.join(sb.tmp, 'config.json'), 'w', encoding='utf-8') as fp:
            fp.write('{ not json at all')
        got = cs.load_config()
        assert got['captchaUrl'] == cs.DEFAULT_CONFIG['captchaUrl']
        with open(os.path.join(sb.tmp, 'config.json'), 'w', encoding='utf-8') as fp:
            fp.write('[1,2,3]')
        assert cs.load_config()['submitValue'] == '登录'
    finally:
        portal.stop()


def test_config_merge_nested():
    sb, cs, pc, portal, cfg = _env()  # 第 3 个返回值是 portal_client 模块
    try:
        with open(os.path.join(sb.tmp, 'config.json'), 'w', encoding='utf-8') as fp:
            json.dump({'options': {'remember': False}, 'maxCaptchaRetry': 5}, fp)
        got = cs.load_config()
        assert got['options']['remember'] is False
        assert got['options']['useOcr'] is True, '未覆盖的同层键必须保留默认值'
        assert got['maxCaptchaRetry'] == 5
    finally:
        portal.stop()


def test_open_session_parses_hidden_and_defaults():
    sb, cs, pc, portal, cfg = _env()
    try:
        client = pc.PortalClient(cfg)
        assert client.form_source == ''
        client.open_session()
        for name in pc.HIDDEN_FIELDS:
            assert name in client.hidden, name
        assert client.defaults.get('ctl00$MainContent$TextBoxISP') == '自动选择'
        assert client.form_source == 'login'
    finally:
        portal.stop()


def test_fetch_captcha_png_and_epoch():
    sb, cs, pc, portal, cfg = _env()
    try:
        client = pc.PortalClient(cfg)
        client.open_session()
        png = client.fetch_captcha()
        assert png[:4] == b'\x89PNG'
        assert client.captcha_epoch == 1
        client.fetch_captcha()
        assert client.captcha_epoch == 2, '每次取码都要推进 epoch（旧码失效）'
    finally:
        portal.stop()


def test_submit_success_and_failure_kinds():
    sb, cs, pc, portal, cfg = _env()
    try:
        client = pc.PortalClient(cfg)
        client.open_session()
        client.fetch_captcha()
        good = portal.state.issued[-1][1]
        bad = pc.PortalClient(cfg)
        bad.open_session()
        bad.fetch_captcha()
        r = bad.submit('', support.ACC, support.PWD, 'ZZZZ')
        assert r.ok is False and r.kind == pc.KIND_CAPTCHA, r
        r = bad.submit('', support.ACC, 'wrong-password', support.portal_code(portal, bad))
        assert r.ok is False and r.kind == pc.KIND_CREDENTIAL, r
        r = bad.submit('', support.ACC, support.PWD, support.portal_code(portal, bad))
        assert r.ok is True, r
        assert portal.state.online is True
    finally:
        portal.stop()


def test_needs_login_is_portal_authoritative():
    """核心回归：外网探测白名单可达时，仍必须按门户状态判断需要登录。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        sess = pc.LoginSession(cfg)
        portal.state.online = False
        assert sess.client.is_online() is True, '模拟环境里白名单探测始终可达'
        assert sess.needs_login() is True, '门户显示未联网 → 必须判定需要登录'
        portal.state.online = True
        assert sess.needs_login() is False, '门户显示已联网 → 无需登录'
    finally:
        portal.stop()


def test_query_status():
    sb, cs, pc, portal, cfg = _env()
    try:
        sess = pc.LoginSession(cfg)
        st = sess.query_status()
        assert st.ip == '127.0.0.1', st
        assert st.text == '未联网' and st.online is False, st
        portal.state.online = True
        st = sess.query_status()
        assert st.text == '已联网' and st.online is True, st
    finally:
        portal.stop()


def test_logoff_flow_is_fast_and_authoritative():
    """注销：门户 POST 后响应页是旧状态，必须重新读门户确认，且不应有 4s×3 的等待。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        portal.state.online = True
        sess = pc.LoginSession(cfg)
        png, status = sess.prepare_logoff()
        assert png[:4] == b'\x89PNG'
        assert status.text == '已联网', status
        client = sess.client
        t0 = time.time()
        r = sess.submit_logoff(support.portal_code(portal, client))
        dt = time.time() - t0
        assert r.ok is True, r
        assert portal.state.online is False
        assert dt < 3.0, f'门户已确认下线时不应等待探测重试（实测 {dt:.2f}s）'
        assert client.form_source == '', '注销成功后必须作废表单，避免下次拿注销页字段提交'
    finally:
        portal.stop()


def test_logoff_then_login_requires_new_session():
    sb, cs, pc, portal, cfg = _env()
    try:
        portal.state.online = True
        sess = pc.LoginSession(cfg)
        sess.prepare_logoff()
        sess.submit_logoff(support.portal_code(portal, sess.client))
        client = sess.client
        assert client.form_source == '' and client.hidden == {} and client.defaults == {}, '注销成功后必须作废表单状态'
        r = sess.submit('')          # 空验证码：必须失败，绝不能"假装成功"
        assert r.ok is False, r
    finally:
        portal.stop()


def test_submit_logoff_with_stale_form_reasks_captcha():
    sb, cs, pc, portal, cfg = _env()
    try:
        portal.state.online = True
        sess = pc.LoginSession(cfg)
        sess.prepare()                     # 中途预取登录页，覆盖了表单来源
        r = sess.submit_logoff('ABCD')
        assert r.ok is False and r.kind == pc.KIND_CAPTCHA, r
        assert '验证码' in r.message
    finally:
        portal.stop()


def test_logoff_without_message_but_portal_confirms_offline():
    """注销 POST 无成功文案，但重新读门户显示未联网 -> 立即成功、不等待探测。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        portal.state.online = True
        portal.state.logoff_no_message = True
        sess = pc.LoginSession(cfg)
        sess.prepare_logoff()
        t0 = time.time()
        r = sess.submit_logoff(support.portal_code(portal, sess.client))
        dt = time.time() - t0
        assert r.ok is True, r
        assert '已断开网络' in r.message, r.message
        assert dt < 3.0, f'不应等待探测重试（{dt:.2f}s）'
    finally:
        portal.stop()


def test_logoff_with_unknown_status_falls_back_to_probe_honestly():
    """门户状态「未知」时才走探测兜底，且如实说明"本机外网仍可达"。"""
    sb, cs, pc, portal, cfg = _env()
    _sleep = pc.time.sleep
    try:
        portal.state.online = True
        portal.state.logoff_no_message = True
        portal.state.status_unknown = True          # 门户不渲染状态 span -> 解析为「未知」
        sess = pc.LoginSession(cfg)
        sess.prepare_logoff()
        pc.time.sleep = lambda *_: None             # 跳过探测间隔
        r = sess.submit_logoff(support.portal_code(portal, sess.client))
        assert r.ok is True, r
        assert '仍可达' in r.message, r.message
    finally:
        pc.time.sleep = _sleep                      # 不要把猴子补丁泄漏给后续用例
        portal.stop()


def test_captcha_is_session_bound():
    sb, cs, pc, portal, cfg = _env()
    try:
        sess = pc.LoginSession(cfg)
        sess.prepare()
        first = support.portal_code(portal, sess.client)
        sess.prepare()                        # 换一张，上一张必须失效
        r = sess.submit(first)
        assert r.ok is False and r.kind == pc.KIND_CAPTCHA, r
        r = sess.submit(support.portal_code(portal, sess.client))
        assert r.ok is True, r
    finally:
        portal.stop()


def test_auto_login_ok_and_wrong_code_retries():
    sb, cs, pc, portal, cfg = _env()
    try:
        class RightOcr:
            available = staticmethod(lambda: True)

            @staticmethod
            def classify(png):
                return support.last_issued(portal)

        class WrongOcr:
            available = staticmethod(lambda: True)
            classify = staticmethod(lambda png: 'ZZZZ')

        log = []
        cfg['maxCaptchaRetry'] = 2
        r = pc.auto_login(cfg, _Logger(log), ocr=RightOcr())
        assert r.ok is True, r
        portal.state.online = False
        r = pc.auto_login(cfg, _Logger(log), ocr=WrongOcr())
        assert r.ok is False and r.kind == pc.KIND_NEED_MANUAL, r
        assert portal.state.login_posts >= 3
    finally:
        portal.stop()


def test_auto_login_skips_when_online():
    sb, cs, pc, portal, cfg = _env()
    try:
        portal.state.online = True
        r = pc.auto_login(cfg, _Logger([]), ocr=None)
        assert r.ok is True and '无需登录' in r.message, r
    finally:
        portal.stop()


def test_auto_login_no_ocr_asks_manual():
    sb, cs, pc, portal, cfg = _env()
    try:
        portal.state.online = False
        r = pc.auto_login(cfg, _Logger([]), ocr=None)
        assert r.ok is False and r.kind == pc.KIND_NEED_MANUAL, r
    finally:
        portal.stop()


def test_ocr_engine_graceful_degradation():
    import ocr_helper
    eng = ocr_helper.OcrEngine()
    assert eng.available() in (True, False)
    assert isinstance(eng.classify(b''), str)
    broken = ocr_helper.OcrEngine()
    broken._initialized = True
    broken._engine = None
    assert broken.available() is False and broken.classify(b'\x89PNG') == ''


def test_autostart_sandboxed():
    sb = support.Sandbox(tempfile.mkdtemp(prefix='guit-as-'))
    cs = sb.install()
    import autostart
    assert autostart.is_enabled() is False
    ok, msg = autostart.enable()
    assert ok is True, msg
    assert autostart.is_enabled() is True
    ok2, msg2 = autostart.ensure_current()
    assert ok2 is True, msg2
    ok3, msg3 = autostart.disable()
    assert ok3 is True and autostart.is_enabled() is False
    ok4, msg4 = autostart.disable()
    assert '本就' in msg4, msg4


# =========================================================================== 新增：Phase 1 还原与 Phase 3 改动的回归用例
#
# 目标：把「反编译伪影被还原」「精简重构后行为不变」「鲁棒性改动真的生效」
# 三件事都钉在断言上。仍然只用本地模拟门户 + 临时目录，不碰真实网络/系统。

# 模拟门户的注销页里，状态 span 出现 bad 时的哨兵值（反编译伪影会走到这个分支）。
# 直接写特殊字符在编辑器/终端里容易乱码，用 chr() 拼出来更稳。
_BAD_STATUS = chr(0x672a) + chr(0x77e5)      # 「未知」：门户没给状态时的兜底文案


def _login_html(online=False):
    """最小登录页：含 captcha/submit 控件名 + 可选状态 span。"""
    return ("<html><form>"
            '<input type="hidden" name="__VIEWSTATE" value="VS" />'
            '<input type="text" name="ctl00$MainContent$TextBoxCC" value="" />'
            '<input type="submit" name="ctl00$MainContent$LoginBtn" value="登录" />'
            '<span id="MainContent_LocalIP">10.0.0.9</span>'
            '<span id="MainContent_LabelOnline">%s</span>'
            "</form></html>") % ('已联网' if online else '未联网')


def _logoff_html(online=True):
    return ("<html><form>"
            '<input type="hidden" name="__VIEWSTATE" value="VS" />'
            '<input type="text" name="ctl00$MainContent$TextBoxCC" value="" />'
            '<span id="MainContent_LocalIP">10.0.0.9</span>'
            '<span id="MainContent_LabelOnline">%s</span>'
            "</form></html>") % ('已联网' if online else '未联网')


def _cfg_for(url):
    """按模拟门户 config 的形状造一份配置，只改探测源地址（避免真上外网）。"""
    sb, cs, pc, portal, cfg = _env()
    portal.stop()
    cfg['onlineProbe'] = {'url': url, 'expect': 'nope', 'timeout': 1}
    return pc, cfg


def _transport_client(pc, cfg, login_html='', login_status=None, logoff='<html></html>'):
    """空壳传输的 PortalClient：_request 全部由测试给答案，不发任何请求。

    pc 传的是 portal_client 模块（用例里就是这个名字），异常类型跟着走。
    """

    client = pc.PortalClient(cfg)
    state = {'login_html': login_html, 'login_status': login_status, 'logoff': logoff}

    def fake_request(url, data=None, timeout=None):
        if url == cfg['captchaUrl']:
            return b'\x89PNG\r\n\x1a\n'
        if url == cfg['logoffUrl']:
            return state['logoff'].encode('utf-8')
        if data is not None:
            # 提交（POST）：模拟门户对这次提交没有任何可判定响应
            if state['login_status'] is None:
                raise pc.PortalError('模拟门户：提交无响应')
            return state['login_status'].encode('utf-8')
        return state['login_html'].encode('utf-8')

    client._request = fake_request
    return client


# ---------------------------------------------------------------- config_store

def test_has_credential_shapes():
    """has_credential 必须覆盖各种残缺形态（还原伪影 + 手改配置的安全退化）。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        assert cs.has_credential({}) is False
        assert cs.has_credential({'user': None}) is False
        assert cs.has_credential({'user': {}}) is False
        assert cs.has_credential({'user': {'guid': '1'}}) is False, '缺 acc/pwd 不算完整'
        assert cs.has_credential({'user': {'guid': '1', 'acc': '2'}}) is False
        assert cs.has_credential({'user': {'guid': '  ', 'acc': '2', 'pwd': '3'}}) is False, '空白不算填了'
        assert cs.has_credential({'user': {'guid': '1', 'acc': '2', 'pwd': '3'}}) is True
        assert cs.has_credential({'user': {'guid': '1', 'acc': '2', 'pwd': '3', 'extra': 'x'}}) is True
        # 手改配置把值写坏时不能崩：非字符串一律按「没填」处理
        assert cs.has_credential({'user': {'guid': 1, 'acc': 2, 'pwd': 3}}) is False
        assert cs.has_credential({'user': {'guid': '', 'acc': {'a': 1}, 'pwd': 3}}) is False
        assert cs.has_credential({'user': {'guid': '1', 'acc': None, 'pwd': 3}}) is False
        assert cs.has_credential({'user': [1, 2]}) is False, 'user 不是对象不能崩'
        assert cs.has_credential({'user': {'guid': '1', 'acc': '2', 'pwd': '3'}}) is True
    finally:
        portal.stop()


def test_load_config_partial_nested_and_illegal():
    """load_config：缺字段 / options 内缺键 / 嵌套非法值都不能污染默认骨架。"""
    sb, cs, pc, portal, cfg = _env()
    path = os.path.join(sb.tmp, 'config.json')
    try:
        with open(path, 'w', encoding='utf-8') as fp:
            json.dump({'user': {'guid': 'g'}}, fp)
        got = cs.load_config()
        assert got['user'] == {'guid': 'g', 'acc': '', 'pwd': ''}, got['user']  # 嵌套 dict 递归一层
        assert got['options'] == cs.DEFAULT_CONFIG['options'], '未出现的键必须保留默认'
        assert cs.has_credential(got) is False, '只填了学号 → 不算完整凭据'
        assert got['submitUrl'] == cs.DEFAULT_CONFIG['submitUrl']
        with open(path, 'w', encoding='utf-8') as fp:
            json.dump({'options': {'remember': False}}, fp)
        got = cs.load_config()
        assert got['options']['remember'] is False
        assert got['options']['useOcr'] is True, 'options 内缺的键必须补默认值'
        assert got['options']['autostart'] is False
        with open(path, 'w', encoding='utf-8') as fp:
            json.dump({'fields': 'not-a-dict', 'user': [1, 2], 'onlineProbe': 5}, fp)
        got = cs.load_config()
        assert got['fields'] == 'not-a-dict' and got['user'] == [1, 2], '非 dict 覆盖按既有语义保留'
        assert cs.has_credential(got) is False, 'user 不是对象时要安全退化'
        with open(path, 'w', encoding='utf-8') as fp:
            fp.write('null')
        assert cs.load_config()['submitValue'] == '登录'
        with open(path, 'w', encoding='utf-8') as fp:
            fp.write('')
        assert cs.load_config()['captchaUrl'] == cs.DEFAULT_CONFIG['captchaUrl']
    finally:
        portal.stop()


def test_save_config_is_atomic_and_keeps_encoding():
    """save_config：UTF-8 无 BOM、末尾换行、中文不转义；写失败不留半截文件。"""
    sb, cs, pc, portal, cfg = _env()
    path = os.path.join(sb.tmp, 'config.json')
    try:
        data = json.loads(json.dumps(cs.DEFAULT_CONFIG))
        data['submitValue'] = '登录·测试'
        cs.save_config(data)
        raw = open(path, 'rb').read()
        assert not raw.startswith(b'\xef\xbb\xbf'), '不能写 UTF-8 BOM'
        assert raw.endswith(b'\n'), '要保留结尾换行'
        assert '登录·测试'.encode('utf-8') in raw, 'ensure_ascii=False：中文不能转义'
        assert cs.load_config()['submitValue'] == '登录·测试'
        assert not os.path.exists(path + '.tmp'), '成功路径不能留下临时文件'
        # 写失败：目标被占成目录 → os.replace 必然失败；旧内容必须原样保留
        before = open(path, 'rb').read()
        broken = os.path.join(sb.tmp, 'broken.json')
        os.makedirs(broken)
        real_path = cs.config_path
        cs.config_path = lambda: broken
        try:
            try:
                cs.save_config(data)
            except Exception:
                pass
            else:
                raise AssertionError('目标不可写时必须抛出，不能静默成功')
        finally:
            cs.config_path = real_path
        assert open(path, 'rb').read() == before, '原子写失败不得破坏原配置'
        assert not os.path.exists(broken + '.tmp'), '失败路径必须清理临时文件'
    finally:
        portal.stop()


# ---------------------------------------------------------------- portal_client

def test_parse_status_all_branches():
    """_parse_status 全分支：反编译伪影（return None(...)）会让本用例直接崩。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        client = pc.PortalClient(cfg)
        off = client._parse_status(_logoff_html(online=False))
        assert (off.ip, off.online, off.text) == ('10.0.0.9', False, '未联网'), off
        on = client._parse_status(_logoff_html(online=True))
        assert (on.ip, on.online, on.text) == ('10.0.0.9', True, '已联网'), on
        # 状态 span 缺失 / 空 → 未知，online 必须为 False
        empty = client._parse_status('<html><span id="MainContent_LocalIP">1.2.3.4</span></html>')
        assert empty.text == _BAD_STATUS and empty.online is False and empty.ip == '1.2.3.4', empty
        blank = client._parse_status('<span id="MainContent_LocalIP">1.2.3.4</span>'
                                     '<span id="MainContent_LabelOnline">   </span>')
        assert blank.text == _BAD_STATUS and blank.online is False, blank
        # 内层标签要剥掉；「已联网」子串出现在别的文案里也按在线算（既有语义）
        nested = client._parse_status('<span id="MainContent_LabelOnline"><font>已联网</font></span>')
        assert nested.text == '已联网' and nested.online is True, nested
        # 自定义 statusFields 生效
        cfg2 = dict(cfg)
        cfg2['statusFields'] = {'ip': 'IPX', 'online': 'ONX'}
        c2 = pc.PortalClient(cfg2)
        custom = c2._parse_status('<span id="IPX">9.9.9.9</span><span id="ONX">已联网</span>')
        assert (custom.ip, custom.text, custom.online) == ('9.9.9.9', '已联网', True), custom
    finally:
        portal.stop()


def test_is_online_candidate_rules():
    """is_online：expect 子串必须命中、无 expect 时只认 204、全部失败才 False。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        good = portal.base + '/connecttest.txt'
        client = pc.PortalClient(cfg)
        client.cfg['onlineProbe'] = {'url': good, 'expect': 'Microsoft Connect Test', 'timeout': 2}
        assert client.is_online() is True, '命中 expect 子串 → 在线'
        client.cfg['onlineProbe'] = {'url': good, 'expect': '绝对不存在的期望串', 'timeout': 1}
        assert client.is_online() is False, '内容不匹配 → 不能算在线（防门户劫持页误判）'
        client.cfg['onlineProbe'] = {'url': good, 'expect': '', 'timeout': 1}
        assert client.is_online() is False, '无 expect 时只有 204 才算在线，200 不算'
        # 204 才认：直接替换模块里的 build_opener，让探测拿到 204 空响应
        real_build = pc.urllib.request.build_opener

        class _Resp:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, *a):
                return b''

        class _Opener:
            def open(self, *a, **k):
                return _Resp()

        pc.urllib.request.build_opener = lambda *a, **k: _Opener()
        try:
            client.cfg['onlineProbe'] = {'url': good, 'expect': '', 'timeout': 1}
            assert client.is_online() is True, '204 空响应 → 在线'
        finally:
            pc.urllib.request.build_opener = real_build
        client.cfg['onlineProbe'] = {'url': 'http://127.0.0.1:%d/nothing' % portal.port, 'expect': 'x', 'timeout': 1}
        assert client.is_online() is False, '连接失败 → 离线'
        client.cfg['onlineProbe'] = {}
        assert client.is_online(max_wait=1) is False, '没有候选源 → 离线'
        t0 = time.time()
        client.cfg['onlineProbe'] = {'url': good, 'expect': 'Microsoft Connect Test', 'timeout': 2}
        assert client.is_online() is True
        assert time.time() - t0 < 2.0, '并发探测必须在预算内返回'
    finally:
        portal.stop()


def test_confirm_offline_never_waits_when_portal_confirms():
    """门户已确认下线 → 立即返回；不得走探测等待（回归：原来固定 4s×3）。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        client = pc.PortalClient(cfg)
        client.logoff_url = lambda: portal.base + '/logoff'   # 门户状态：未联网
        t0 = time.time()
        r = client._confirm_offline('已断开网络')
        dt = time.time() - t0
        assert r.ok is True and '门户已确认下线' in r.message, r
        assert dt < 1.0, f'门户已确认时不得等待（实测 {dt:.2f}s）'
        # portal_status 参数同样能直接判定，且不等待
        t0 = time.time()
        r = client._confirm_offline('已断开网络', portal_status=pc.PortalStatus(ip='', online=False, text='未联网'))
        assert r.ok is True and '门户已确认下线' in r.message and time.time() - t0 < 1.0, r
    finally:
        portal.stop()


def test_confirm_offline_bounded_wait_then_honest_report():
    """门户未确认时：按递减间隔探测、有总预算；结论要么「探测确认」要么如实说明仍可达。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        client = pc.PortalClient(cfg)
        client.logoff_url = lambda: 'http://127.0.0.1:%d/definitely-not-a-page' % portal.port
        real_sleep = pc.time.sleep
        slept = []
        pc.time.sleep = lambda s: slept.append(s)
        try:
            # 探测源命中 → 外网仍可达 → 如实说明，不谎报失败
            client.cfg['onlineProbe'] = {'url': portal.base + '/connecttest.txt',
                                         'expect': 'Microsoft Connect Test', 'timeout': 1}
            r = client._confirm_offline('已断开网络')
            assert r.ok is True, r
            assert '仍可达' in r.message, r.message
            assert slept and max(slept) <= 2.0, f'间隔必须是递减的小值：{slept}'
            assert sum(slept) <= pc.CONFIRM_OFFLINE_BUDGET, f'总等待不得超预算：{slept}'
            slept.clear()
            # 探测源不可达 → 探测即可确认下线
            client.cfg['onlineProbe'] = {'url': 'http://127.0.0.1:%d/nothing' % portal.port, 'expect': 'x', 'timeout': 1}
            r = client._confirm_offline('已断开网络')
            assert r.ok is True and '已断开网络' in r.message, r
            assert sum(slept) <= pc.CONFIRM_OFFLINE_BUDGET
            # fallback：只有「探测也没给出结论」时才使用；探测确认可达 → 如实说明
            r = client._confirm_offline('已断开网络', fallback='断开失败：门户未确认状态变化')
            assert r.ok is True, r   # 探测确认可达性 → 仍算成功
        finally:
            pc.time.sleep = real_sleep
        # 探测每次抛异常 → 没有结论 → 才交 fallback，不谎报成功
        def _boom(*a, **k):
            raise RuntimeError('boom')

        client.is_online = _boom
        r = client._confirm_offline('已断开网络', fallback='断开失败：门户未确认状态变化')
        assert r.ok is False and r.message == '断开失败：门户未确认状态变化', r
        # 没有 fallback 时也不能谎报：探测无结论、门户没确认 → 仍按「如实说明」返回
        r = client._confirm_offline('已断开网络')
        assert r.ok is True and '仍可达' in r.message, r
    finally:
        portal.stop()


def test_login_success_requires_form_code_and_fresh_status():
    """核心回归：门户状态「已联网」不能单独充当登录成功的证据（会误报成功）。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        # 1) 注销/换表后拿旧码提交 → 直接判失败，不再产生假成功
        client = _transport_client(pc, cfg, login_html=_logoff_html(True),
                                   login_status=None, logoff=_logoff_html(False))
        client.open_session()                 # 表单代 +1
        client.fetch_captcha()                # 这轮的码属于当前表单
        client.invalidate_form()              # 注销成功后的作废
        try:
            stale = client.submit('', 'a', 'b', 'ABCD')
        except pc.PortalError:
            raise AssertionError('换表后的提交必须在本地拦下，不该真的发出去')
        assert stale.ok is False and stale.kind == pc.KIND_CAPTCHA, stale
        # 2) 表单被重新取过但码没重取 → 也必须拦下
        client2 = _transport_client(pc, cfg, login_html=_logoff_html(True),
                                    login_status=None, logoff=_logoff_html(False))
        client2.open_session()
        try:
            r = client2.submit('', 'a', 'b', 'ABCD')
        except pc.PortalError:
            raise AssertionError('重取表单后拿旧码提交，必须在本地拦下')
        assert r.ok is False and r.kind == pc.KIND_CAPTCHA, r
        assert client2.captcha_epoch >= 1, '拦下时要顺手把新码取回来给界面'
        # 3) 提交前就已在线 → 提交后的「已联网」不是证据，不能报成功
        client3 = _transport_client(pc, cfg, login_html=_logoff_html(True),
                                    login_status=_login_html(True), logoff=_logoff_html(True))
        client3.open_session()
        client3.fetch_captcha()
        r = client3.submit('', 'a', 'b', 'ABCD')
        assert r.ok is False and r.kind == pc.KIND_UNKNOWN, r
        # 4) 提交前未在线、提交后在线 → 这才是真实的状态证据
        #    用一个只读状态由 False→True 变化的假传输模拟这一步（login 页只用于填表单）
        client4 = _transport_client(pc, cfg, login_html=_logoff_html(False),
                                    login_status=_login_html(True), logoff=_logoff_html(False))
        calls = {'n': 0}
        real_req = client4._request

        def flipping(url, data=None, timeout=None):
            if url == cfg['logoffUrl']:
                calls['n'] += 1
                return _logoff_html(calls['n'] > 1).encode('utf-8')
            return real_req(url, data, timeout)

        client4._request = flipping
        client4.open_session()
        client4.fetch_captcha()
        r = client4.submit('', 'a', 'b', 'ABCD')
        assert calls['n'] == 2, '提交前读一次、提交后再读一次'
        assert r.ok is True and '门户状态显示已联网' in r.message, r
        # 5) 门户状态读不到（页面没有状态 span）→ 不能凭状态报成功
        client5 = _transport_client(pc, cfg, login_html='<html><input type="hidden" name="__VIEWSTATE" value="VS" /></html>',
                                    login_status=_login_html(True), logoff='<html>没有任何状态控件</html>')
        client5.open_session()
        client5.fetch_captcha()
        r = client5.submit('', 'a', 'b', 'ABCD')
        assert r.ok is False and r.kind == pc.KIND_UNKNOWN, r
    finally:
        portal.stop()


def test_request_wraps_protocol_errors():
    """http.client 层异常（门户主动断连等）必须也包装成 PortalError。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        import http.client
        client = pc.PortalClient(cfg)
        client.timeout = 1

        class Boom:
            def open(self, *a, **k):
                raise http.client.RemoteDisconnected('remote closed')

        client.opener = Boom()
        try:
            client._request(cfg['portalUrl'])
        except pc.PortalError as exc:
            assert '门户响应异常' in str(exc), exc
        else:
            raise AssertionError('必须包装成 PortalError')
        try:
            client._request('http://127.0.0.1:%d/x' % portal.port, timeout=0.001)
        except pc.PortalError:
            pass
        else:
            raise AssertionError('超时也必须包装成 PortalError')
    finally:
        portal.stop()


def test_login_session_submit_survives_non_dict_user():
    """user 被手改成非对象时，LoginSession.submit 不能抛 AttributeError。"""
    sb, cs, pc, portal, cfg = _env()
    try:
        cfg['user'] = 'not-a-dict'
        sess = pc.LoginSession(cfg)
        sess.prepare()
        r = sess.submit(support.portal_code(portal, sess.client))
        assert r.ok is False, r   # 门户报账号或密码错误，而不是内部崩溃
        assert r.kind in (pc.KIND_CREDENTIAL, pc.KIND_UNKNOWN), r
    finally:
        portal.stop()


def test_ocr_length_semantics_and_degradation():
    """OcrEngine：构造参数 length 覆盖类常量；引擎不可用时安静退化。"""
    import ocr_helper
    eng = ocr_helper.OcrEngine(6)
    assert eng.CAPTCHA_LENGTH == 6
    assert ocr_helper.OcrEngine.CAPTCHA_LENGTH == 4, '实例参数不得污染类常量'

    class Fake:
        def classification(self, png):
            return 'ab-12 34xy'

    eng._initialized = True
    eng._engine = Fake()
    assert eng.available() is True
    assert eng.classify(b'\x89PNG') == 'ab1234', '先剔非字母数字再截长度'
    eng2 = ocr_helper.OcrEngine()
    eng2._initialized = True     # 别让它去 import 真的 ddddocr（会把假引擎换掉）
    eng2._engine = Fake()
    assert eng2.classify(b'\x89PNG') == 'ab12'

    class Boom:
        def classification(self, png):
            raise RuntimeError('model broke')

    eng._engine = Boom()
    assert eng.classify(b'\x89PNG') == '', '识别异常必须返回空串'
    assert eng.classify(b'') == '', '空输入不触发识别'
    never = ocr_helper.OcrEngine()
    never._engine = None
    assert never.classify(b'\x89PNG') == ''


def test_autostart_repairs_and_reports():
    """autostart：cmd 载体、坏 .lnk、异常路径都要有确定答案。"""
    sb = support.Sandbox(tempfile.mkdtemp(prefix='guit-as2-'))
    sb.install()
    import autostart
    os.makedirs(autostart.startup_dir(), exist_ok=True)
    # 只有 .cmd（PowerShell 不可用时的回退载体）→ ensure_current 必须重建 .lnk
    with open(autostart.cmd_path(), 'w', encoding='utf-8') as fp:
        fp.write('@echo off\r\n')
    ok, msg = autostart.ensure_current()
    assert ok is True, msg
    assert os.path.exists(autostart.lnk_path()) or os.path.exists(autostart.cmd_path())
    ok, msg = autostart.disable()
    assert ok is True and autostart.is_enabled() is False
    assert '已移除' in msg, msg
    # 坏 .lnk（空文件）不能读成「已指向当前程序」
    with open(autostart.lnk_path(), 'w', encoding='utf-8') as fp:
        fp.write('')
    target, args = autostart.read_lnk()
    assert target == '' and args == ''
    ok, msg = autostart.ensure_current()
    assert ok is True, msg
    assert not (msg.startswith('自启项已指向当前程序')), msg
    # 删除成功后必须如实回答「移除了什么 / 本就没有」
    assert autostart.disable()[0] is True
    assert '本就' in autostart.disable()[1]
    # 换一个干净的 Startup 目录再放一个载体，确认 disable 的返回文案不含歧义
    real_dir = autostart.startup_dir
    other = os.path.join(tempfile.mkdtemp(prefix='guit-as3-'), 'Startup')
    os.makedirs(other, exist_ok=True)
    autostart.startup_dir = lambda: other
    try:
        with open(autostart.cmd_path(), 'w', encoding='utf-8') as fp:
            fp.write('@echo off\r\n')
        ok2, msg2 = autostart.disable()
        assert ok2 is True and autostart.is_enabled() is False, msg2
        assert '已移除' in msg2 and autostart.CMD_NAME in msg2, msg2
    finally:
        autostart.startup_dir = real_dir



class _Logger:
    def __init__(self, sink):
        self.lines = sink

    def _add(self, msg):
        if isinstance(self.lines, list):
            self.lines.append(msg)

    def info(self, m):
        self._add(m)

    def warn(self, m):
        self._add(m)

    def error(self, m):
        self._add(m)

    def set_sink(self, s):
        pass
