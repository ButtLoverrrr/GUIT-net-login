"""前端测试：tkinter 主窗口 + 队列泵 + 连接/断开流程 + 托盘 + 单实例。全部沙箱化。"""
import json
import os
import subprocess
import sys
import tempfile
import time

import support


class StubOcrEngine:
    """`ocr.OcrBackend` 契约的替身：不 import ddddocr（接口见 src/ocr.py）。

    为什么必须在 _boot 里就装上：`_prefetch_worker` 会调 `_use_ocr()` →
    `Engine.available()` → `import ddddocr`，而 ddddocr 首次导入要拉起
    onnxruntime/cv2/numpy，实测会阻塞预取线程 15 秒以上（线程栈实证：
    app.py → ocr_helper.py → ddddocr/__init__）。这会与本用例自己的
    连接流程抢 busy 状态，造成随机失败。真实 OCR 由 test_backend 覆盖，这里
    只关心界面流程。
    """

    def __init__(self, portal, mode='right'):
        self.portal = portal
        self.mode = mode

    def available(self):
        return self.mode != 'absent'

    def classify(self, png):
        if self.mode == 'right':
            return support.last_issued(self.portal)
        return 'ZZZZ'


def _boot(ocr_mode='right'):
    sb = support.Sandbox(tempfile.mkdtemp(prefix='guit-gui-'))
    cs = sb.install()
    import tkinter as tk
    import app as appmod
    support.patch_app_sandbox(appmod, sb.tmp)
    portal = support.MockPortal()
    cfg = portal.config()
    import config_store
    original = config_store.load_config
    config_store.load_config = lambda: json.loads(json.dumps(cfg))
    appmod.load_config = config_store.load_config
    root = tk.Tk()
    root.withdraw()
    # 必须在 LoginApp 之前替换引擎装配点：__init__ 里就装配了一个，而启动预取
    # 200ms 后就会用到它。（OCR 已解耦为可插拔接口，见 src/ocr.py 与 docs/ocr-interface.md）
    real_factory = appmod.build_ocr_engine
    appmod.build_ocr_engine = lambda *_a, **_k: StubOcrEngine(portal, ocr_mode)
    try:
        ui = appmod.LoginApp(root)
    finally:
        appmod.build_ocr_engine = real_factory
    ui.ocr = StubOcrEngine(portal, ocr_mode)
    return sb, cs, portal, cfg, appmod, root, ui, original, config_store


def pump(root, ui, seconds=1.0):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def wait_until(root, cond, seconds=8.0):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)
        if cond():
            return True
    return False


def settle(root, ui, seconds=0.6):
    """等启动预取（_on_start 里 200ms 后触发）跑完。

    预取期间 self.busy 为 True，而 _on_connect/_on_logoff 在 busy 时直接 return；
    用例若在预取进行中发起连接，点击会被静默丢弃（表现为"等不到流程结束"）。
    """

    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)
    return wait_until(root, lambda: not ui.busy, 15)


class StubOcr(StubOcrEngine):
    """兼容旧签名：StubOcr(portal, wrong=True)。"""

    def __init__(self, portal, wrong=False):
        super().__init__(portal, 'wrong' if wrong else 'right')


def test_window_constructs_and_widgets_exist():
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        pump(root, ui, 0.3)
        assert ui.root.title().startswith(appmod.APP_TITLE), ui.root.title()
        assert ui.txt_log.get('1.0', 'end').strip() != ''
        assert ui.btn_connect.cget('text') in ('连 接', '连接中…')
        assert ui.var_guid.get() == '20210001'
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_collect_form_validation():
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        ui.var_guid.set('')
        ui.var_acc.set('')
        ui.var_pwd.set('')
        assert ui._collect_form() is False
        assert '学号' in ui.var_status.get() and '上网密码' in ui.var_status.get(), ui.var_status.get()
        ui.var_guid.set('20210001')
        ui.var_acc.set(support.ACC)
        ui.var_pwd.set(support.PWD)
        assert ui._collect_form() is True
        assert ui.cfg['user']['acc'] == support.ACC
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_captcha_display_uses_pixel_size():
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        import io
        import PIL.Image
        buf = io.BytesIO()
        PIL.Image.new('RGB', (80, 24), (255, 255, 255)).save(buf, 'PNG')
        ui._show_captcha(buf.getvalue())
        root.update()
        root.update_idletasks()
        root.update()
        assert ui.photo is not None, '验证码图像必须被渲染'
        assert ui.photo.width() == 80 * appmod.CAPTCHA_ZOOM, ui.photo.width()
        # 原始写法（像素写入 Label width）经复核是正确的：Label 带图后 width/height 以像素计。
        assert int(ui.lbl_captcha.cget('width')) == ui.photo.width(), 'Label 尺寸必须改成像素，否则被压扁'
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_update_net_and_queue_pump():
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        ui._post('net', True, '10.0.0.9')
        ui._post('busy', True, '连接中…')
        ui._post('log', 'hello')
        pump(root, ui, 0.4)
        assert '已联网' in ui.var_net.get() and '10.0.0.9' in ui.var_net.get(), ui.var_net.get()
        assert ui.btn_connect.cget('text') == '连接中…'
        assert 'hello' in ui.txt_log.get('1.0', 'end')
        ui._post('done', True, '登录成功')
        pump(root, ui, 0.4)
        assert ui.btn_connect.cget('state') == 'normal'
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_connect_flow_end_to_end():
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        assert settle(root, ui), '启动预取未在超时内结束'
        ui.var_guid.set('20210001')
        ui.var_acc.set(support.ACC)
        ui.var_pwd.set(support.PWD)
        ui.cfg = json.loads(json.dumps(cfg))
        ui.ocr = StubOcr(portal)
        portal.state.online = False
        ui.var_captcha.set('')
        ui._on_connect()
        assert wait_until(root, lambda: ui.btn_connect.cget('state') == 'normal' and portal.state.online, 15), \
            '连接流程未能在超时内完成：' + ui.var_status.get()
        assert portal.state.online is True
        assert ui.busy is False
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_connect_flow_wrong_captcha_then_manual():
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        assert settle(root, ui), '启动预取未在超时内结束'
        ui.var_guid.set('20210001')
        ui.var_acc.set(support.ACC)
        ui.var_pwd.set(support.PWD)
        ui.cfg = json.loads(json.dumps(cfg))
        ui.cfg['maxCaptchaRetry'] = 2
        ui.ocr = StubOcr(portal, wrong=True)
        portal.state.online = False
        # 预取会用「正确」替身把识别结果填进输入框；本用例想验证的是"识别失败 →
        # 换码重试 → 转手输"，所以先清空输入框，走自动识别分支。
        ui.var_captcha.set('')
        ui._on_connect()
        assert wait_until(root, lambda: ui.btn_connect.cget('state') == 'normal' and not ui.busy, 15), \
            '连接流程未能在超时内结束：' + ui.var_status.get()
        log = ui.txt_log.get('1.0', 'end')
        assert '验证码' in log or '识别' in log, log
        assert portal.state.online is False
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_logoff_flow_end_to_end():
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        assert settle(root, ui), '启动预取未在超时内结束'
        ui.var_guid.set('20210001')
        ui.var_acc.set(support.ACC)
        ui.var_pwd.set(support.PWD)
        ui.cfg = json.loads(json.dumps(cfg))
        ui.ocr = StubOcr(portal)
        portal.state.online = True
        ui._on_logoff()
        assert wait_until(root, lambda: ui.btn_connect.cget('state') == 'normal' and portal.state.online is False, 15), \
            '断开流程未能在超时内完成：' + ui.var_status.get()
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_tray_image_and_hide_show():
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        img = ui._tray_image()
        assert img is not None and hasattr(img, 'size'), '托盘图标必须可构造'
        assert min(img.size) > 0

        # assets/app.png 缺失时，必须现场画出 64x64 的兜底图标（反编译丢失的那段逻辑）
        real_resource_path = appmod.resource_path
        appmod.resource_path = lambda name: os.path.join(sb.tmp, 'missing-assets', name)
        try:
            fallback = ui._tray_image()
        finally:
            appmod.resource_path = real_resource_path
        assert fallback is not None, '兜底分支必须返回图像'
        assert fallback.size == (64, 64), fallback.size

        try:
            ui._on_hide()
            assert wait_until(root, lambda: ui.tray_icon is not None, 8), '托盘图标未在超时内出现'
            ui._tray_show()
            assert wait_until(root, lambda: root.state() == 'normal', 8), root.state()
        finally:
            ui._stop_tray()
        assert ui.tray_icon is None
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_second_launch_defers_to_first():
    """单实例：第二个进程必须把 show 送给第一个并立即退出（退出码 0）。"""
    sb = support.Sandbox(tempfile.mkdtemp(prefix='guit-si-'))
    sb.install()
    import socket
    import threading
    port = int(os.environ['GUIT_INSTANCE_PORT'])
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(('127.0.0.1', port))
    srv.listen(1)
    seen = []

    def serve():
        srv.settimeout(20)
        try:
            conn, _ = srv.accept()
            seen.append(conn.recv(16))
            conn.sendall(b'ok')
            conn.close()
        except Exception as exc:
            seen.append(('err', str(exc)))

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    env = dict(os.environ)
    env['GUIT_INSTANCE_PORT'] = str(port)
    p = subprocess.run([sys.executable, os.path.join(support.PROJ, 'app.py')], cwd=support.PROJ,
                       env=env, capture_output=True, timeout=40)
    srv.close()
    assert p.returncode == 0, (p.returncode, p.stderr[-800:])
    assert b'show' in b''.join(x for x in seen if isinstance(x, bytes)), seen


# --------------------------------------------------------------------------- 新增：动画 / 易用性 / 流畅度


def test_window_centered_and_on_screen():
    """窗口必须按屏幕可用区居中，且不超出屏幕（高 DPI 小屏保护）。"""
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        root.update_idletasks()
        root.update()
        scr_w = root.winfo_screenwidth()
        scr_h = root.winfo_screenheight()
        assert root.winfo_width() <= scr_w, (root.winfo_width(), scr_w)
        assert root.winfo_height() <= scr_h, (root.winfo_height(), scr_h)
        assert 0 <= root.winfo_x() <= max(1, scr_w - root.winfo_width()), root.winfo_x()
        assert 0 <= root.winfo_y() <= max(1, scr_h - root.winfo_height()), root.winfo_y()
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_fade_in_returns_to_full_opacity():
    """淡入动画结束后必须回到完全不透明；不支持 -alpha 时必须静默降级且不影响可见。"""
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        root.update()
        try:
            root.attributes('-alpha', 1.0)
            alpha_supported = True
        except Exception:
            alpha_supported = False
        ui._fade_off = False
        ui._fade_in()
        pump(root, ui, 1.2)
        if alpha_supported:
            assert float(root.attributes('-alpha')) == 1.0, root.attributes('-alpha')
        else:
            assert ui._fade_off is True, '不支持 -alpha 时必须标记降级'
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_enter_connects_and_escape_hides():
    """回车=连接（与按钮同一条路径），Esc=隐藏。

    说明：Tk 不会把键盘事件投递给未映射（withdraw）的窗口，所以本用例必须先映射
    窗口再 event_generate（实测 withdrawn 时 hits 为空，mapped 时正常）。
    """
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        root.deiconify()
        assert settle(root, ui), '启动预取未在超时内结束'
        ui.var_guid.set('20210001')
        ui.var_acc.set(support.ACC)
        ui.var_pwd.set(support.PWD)
        ui.cfg = json.loads(json.dumps(cfg))
        ui.ocr = StubOcr(portal)
        portal.state.online = False
        ui.var_captcha.set('')
        root.event_generate('<Return>')
        root.update()
        assert ui.busy is True, '回车必须走 _on_connect（busy 立即可见）'
        assert wait_until(root, lambda: ui.btn_connect.cget('state') == 'normal', 15), ui.var_status.get()
        assert portal.state.online is True, '回车触发的连接必须真的提交到门户'
        root.event_generate('<Escape>')
        root.update()
        assert root.state() == 'withdrawn', root.state()
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_captcha_input_cleaned_on_paste():
    """粘贴验证码必须去掉空白与不可见字符，并限制长度。"""
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        assert ui._clean_captcha_input('ab cd\t') is False
        assert ui.var_captcha.get() == 'abcd', repr(ui.var_captcha.get())
        assert ui._clean_captcha_input('ABCD') is True
        assert ui._clean_captcha_input('ABCDEFGH') is False
        assert ui.var_captcha.get() == 'ABCDEF', repr(ui.var_captcha.get())
        assert ui._clean_captcha_input('\u200b') is False
        assert ui.var_captcha.get() == '', repr(ui.var_captcha.get())
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_log_is_bounded_and_keeps_bottom():
    """日志区必须有界（长跑不无限增长），错误行有 error 标记，状态栏颜色随之切换。"""
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        for i in range(appmod.LOG_MAX_LINES + 50):
            ui._append_log('填充 %d' % i)
        root.update_idletasks()
        txt = ui.txt_log.get('1.0', 'end-1c')
        assert '填充 0' not in txt.split('\n')[0], '超长日志必须从头部裁剪'
        assert txt.rstrip('\n').endswith('填充 %d' % (appmod.LOG_MAX_LINES + 49)), txt[-60:].replace('\n', '|')
        assert len(txt.split('\n')) <= appmod.LOG_MAX_LINES + 1, len(txt.split('\n'))
        ui._append_log('boom', 'error')
        assert 'error' in ui.txt_log.tag_names('end-2l'), ui.txt_log.tag_names('end-2l')
        ui._set_status('出错了', 'error')
        assert ui.status_label.cget('fg') == appmod.STATUS_ERR_FG, ui.status_label.cget('fg')
        ui._set_status('好了', 'info')
        assert ui.status_label.cget('fg') == appmod.STATUS_INFO_FG, ui.status_label.cget('fg')
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()


def test_captcha_scale_respects_zoom_and_caps():
    """验证码显示尺寸：小图按倍数放大，大图被收到上限以内。

    站点的两个验证码端点原图差很多（实测）：
      /CheckCode       80x24   -> 按 CAPTCHA_ZOOM 放大
      /ACaptcha.ashx  200x60   -> 固定倍数会到 800x240 撑满窗口，必须收上限
    """
    sb, cs, portal, cfg, appmod, root, ui, original, config_store = _boot()
    try:
        import io
        import PIL.Image

        def render(size):
            buf = io.BytesIO()
            PIL.Image.new('RGB', size, (255, 255, 255)).save(buf, 'PNG')
            ui._show_captcha(buf.getvalue())
            root.update_idletasks()
            root.update()
            return ui.photo.width(), ui.photo.height()

        # 小图：不被上限影响，走满倍数
        w, h = render((80, 24))
        assert (w, h) == (80 * appmod.CAPTCHA_ZOOM,
                          24 * appmod.CAPTCHA_ZOOM), (w, h)

        # 大图：必须在上限内，且保持宽高比
        w, h = render((200, 60))
        assert w <= appmod.CAPTCHA_MAX_W, w
        assert h <= appmod.CAPTCHA_MAX_H, h
        assert abs(w / float(h) - 200.0 / 60.0) < 0.1, (w, h)
    finally:
        config_store.load_config = original
        portal.stop()
        root.destroy()
