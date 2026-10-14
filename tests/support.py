"""测试支撑：模拟 ASP.NET 门户 + 沙箱环境（不碰真实系统、不碰真实校园网）。

模拟对象依据源码里记录的实测行为：
  1. 登录/注销页都带 __VIEWSTATE 等隐藏字段，表单带控件默认值（如 TextBoxISP=自动选择）；
  2. 验证码与 ASP.NET_SessionId 绑定，重新取码会让上一张失效；
  3. 登录成功时页面仍是登录页样式，但 validation-summary 里含「联网成功!」；
  4. 注销 POST 的响应页渲染的是**提交前**的旧状态，必须重新 GET /logoff 才能看到「未联网」；
  5. 外网探测目标在未认证时也被放行（白名单），因此 /connecttest.txt 永远可达。
"""
import http.server
import io
import os
import re
import shutil
import socket
import sys
import threading
import urllib.parse

import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont

# PROJ 指向「第一方模块所在目录」：原工作区在项目根，仓库布局在 src/ 子目录，
# 自动探测兼容两种布局（子进程测试用它做 cwd / GUIT_PROJ / sys.path 注入）。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.join(_ROOT, 'src') if os.path.isfile(os.path.join(_ROOT, 'src', 'app.py')) else _ROOT

# PyInstaller 解包出的 3.13 运行时把 Tcl/Tk 脚本放在 _tcl_data / _tk_data，
# 必须显式告知 Tcl 库位置，否则 Tk 初始化失败（"Tcl wasn't installed properly"）。
_TOOLS = os.path.dirname(os.path.abspath(sys.executable))
for _env, _sub in (('TCL_LIBRARY', '_tcl_data'), ('TK_LIBRARY', '_tk_data')):
    _p = os.path.join(_TOOLS, _sub)
    if os.path.isdir(_p):
        os.environ[_env] = _p

HIDDEN = ('__VIEWSTATE', '__VIEWSTATEGENERATOR', '__VIEWSTATEENCRYPTED', '__EVENTVALIDATION')
FIELDS = {
    'guid': 'ctl00$MainContent$SSOGUITID',
    'acc': 'ctl00$MainContent$SSOACC',
    'pwd': 'ctl00$MainContent$SSOPWD',
    'captcha': 'ctl00$MainContent$TextBoxCC',
    'submit': 'ctl00$MainContent$LoginBtn',
}
ACC = '13800000000'
PWD = 'test-password'


def _captcha_png(code: str) -> bytes:
    img = PIL.Image.new('RGB', (80, 24), (245, 248, 252))
    draw = PIL.ImageDraw.Draw(img)
    try:
        font = PIL.ImageFont.load_default(size=18)      # 需要 FreeType 后端
    except Exception:
        font = PIL.ImageFont.load_default()             # 精简构建没有 _imagingft 时退回点阵字体
    for i, ch in enumerate(code):
        draw.text((8 + i * 17, 3), ch, fill=(20, 30, 60), font=font)
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


class PortalState:
    def __init__(self):
        self.online = False
        self.codes = {}          # sid -> 当前有效验证码
        self.issued = []         # 每次取码的 (sid, code)，用于断言失效逻辑
        self.counter = 0
        self.login_posts = 0
        self.logoff_posts = 0
        self.fail_mode = None    # 'captcha' | 'credential' | None：强制某类失败
        self.logoff_stale_ok_page = True   # 注销 POST 返回旧状态（实测行为）
        self.logoff_no_message = False     # 注销 POST 不给成功文案
        self.status_unknown = False        # 门户状态 span 为空 -> 解析为「未知」，用于走探测兜底路径
        self.requests = []                 # 请求流水（方法, 路径, 表单摘要），用于端到端取证
        self.accept_any_captcha = False    # True: 任意验证码都放行（用于"真实 exe + 模拟门户"联调，OCR 无法识别合成验证码）

    def next_code(self):
        self.counter += 1
        alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        n = self.counter * 7 + 11
        code = ''
        for _ in range(4):
            code += alphabet[n % len(alphabet)]
            n //= len(alphabet)
        return code


def _hidden_block(viewstate_id='LOGIN'):
    return ''.join(f'<input type="hidden" name="{h}" value="{viewstate_id}-{h}-{i}" />'
                   for i, h in enumerate(HIDDEN))


def login_page(msg='', online=False):
    err = ''
    if msg:
        err = f'<div class="validation-summary-errors"><ul><li>{msg}</li></ul></div>'
    return f'''<html><head><title>校园网认证</title></head><body>
<form method="post" action="/login" id="form1">
{_hidden_block('LOGIN')}
<input type="text" name="{FIELDS['guid']}" value="20210001" />
<input type="text" name="{FIELDS['acc']}" value="" />
<input type="password" name="{FIELDS['pwd']}" value="" />
<input type="text" name="{FIELDS['captcha']}" value="" />
<input type="submit" name="{FIELDS['submit']}" value="登录" />
<input type="text" name="ctl00$MainContent$TextBoxISP" value="自动选择" />
<span id="MainContent_LocalIP">127.0.0.1</span>
<span id="MainContent_LabelOnline">{'已联网' if online else '未联网'}</span>
</form>{err}</body></html>'''


def logoff_page(msg='', online=True, viewstate_id='LOGOFF', status_text=None):
    err = ''
    if msg:
        err = f'<div class="validation-summary-errors"><ul><li>{msg}</li></ul></div>'
    if status_text is None:
        status_text = '已联网' if online else '未联网'
    return f'''<html><head><title>断开网络</title></head><body>
<form method="post" action="/logoff" id="form2">
{_hidden_block(viewstate_id)}
<input type="text" name="{FIELDS['captcha']}" value="" />
<input type="text" name="ctl00$MainContent$TextBoxISP" value="自动选择" />
<input type="submit" name="ctl00$MainContent$LogoffBtn" value="注销" />
<span id="MainContent_LocalIP">127.0.0.1</span>
<span id="MainContent_LabelOnline">{status_text}</span>
</form>{err}</body></html>'''


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    state: PortalState = None

    def log_message(self, *a):
        pass

    # ---- helpers ----
    def _sid(self):
        cookie = self.headers.get('Cookie') or ''
        m = re.search(r'ASP.NET_SessionId=([^;]+)', cookie)
        return m.group(1) if m else None

    def _send(self, body: str, ctype='text/html; charset=utf-8', new_sid=None):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        if new_sid:
            self.send_header('Set-Cookie', f'ASP.NET_SessionId={new_sid}; path=/')
        self.end_headers()
        self.wfile.write(data)

    def _new_sid(self):
        self.state.counter += 1
        return 'sid%05d' % self.state.counter

    # ---- routes ----
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        self.state.requests.append(('GET', path, ''))
        if path == '/login':
            sid = self._sid()
            if sid is None:
                sid = self._new_sid()
                self._send(login_page(online=self.state.online), new_sid=sid)
            else:
                self._send(login_page(online=self.state.online))
            return
        if path == '/CheckCode':
            sid = self._sid()
            fresh = sid is None
            sid = sid or self._new_sid()
            code = self.state.next_code()
            self.state.codes[sid] = code
            self.state.issued.append((sid, code))
            self._send(_captcha_png(code), 'image/png', new_sid=sid if fresh else None)
            return
        if path == '/logoff':
            sid = self._sid()
            text = '' if self.state.status_unknown else None
            self._send(logoff_page(online=self.state.online, status_text=text), new_sid=sid or self._new_sid())
            return
        if path == '/connecttest.txt':
            # 白名单模拟：未认证状态下也可达
            self._send('Microsoft Connect Test', 'text/plain')
            return
        self._send('<html>404</html>')

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length).decode('utf-8', 'ignore')
        form = dict(urllib.parse.parse_qsl(body, keep_blank_values=True))
        self.state.requests.append(('POST', path, {k: v for k, v in form.items() if 'PWD' not in k}))
        sid = self._sid()
        if path == '/login':
            self.state.login_posts += 1
            captcha = (form.get(FIELDS['captcha']) or '').strip()
            bad_captcha = captcha != self.state.codes.get(sid) and not self.state.accept_any_captcha
            if self.state.fail_mode == 'captcha' or bad_captcha:
                self._send(login_page('验证码错误', self.state.online))
                return
            if self.state.fail_mode == 'credential' or form.get(FIELDS['acc']) != ACC or form.get(FIELDS['pwd']) != PWD:
                self._send(login_page('账号或密码错误', self.state.online))
                return
            self.state.online = True
            # 登录成功：门户仍是登录页样式，但带成功文案
            self._send(login_page('联网成功!', True))
            return
        if path == '/logoff':
            self.state.logoff_posts += 1
            captcha = (form.get(FIELDS['captcha']) or '').strip()
            bad_captcha = captcha != self.state.codes.get(sid) and not self.state.accept_any_captcha
            if self.state.fail_mode == 'captcha' or bad_captcha:
                self._send(logoff_page('验证码错误', self.state.online))
                return
            before = self.state.online
            self.state.online = False
            msg = '' if self.state.logoff_no_message else '断开成功!'
            # 实测：响应页渲染的是提交前的状态
            text = '' if self.state.status_unknown else (before if self.state.logoff_stale_ok_page else False)
            self._send(logoff_page(msg, before if self.state.logoff_stale_ok_page else False, status_text=text))
            return
        self._send('<html>404</html>')


class MockPortal:
    def __init__(self):
        self.state = PortalState()
        handler = type('BoundHandler', (Handler,), {'state': self.state})
        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    @property
    def base(self):
        return f'http://127.0.0.1:{self.port}'

    def config(self):
        from config_store import DEFAULT_CONFIG
        cfg = __import__('json').loads(__import__('json').dumps(DEFAULT_CONFIG))
        b = self.base
        cfg['portalUrl'] = b + '/login'
        cfg['portalHome'] = b
        cfg['captchaUrl'] = b + '/CheckCode'
        cfg['submitUrl'] = b + '/login'
        cfg['logoffUrl'] = b + '/logoff'
        cfg['onlineProbe'] = {'url': b + '/connecttest.txt', 'expect': 'Microsoft Connect Test', 'timeout': 2}
        cfg['user'] = {'guid': '20210001', 'acc': ACC, 'pwd': PWD}
        return cfg

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# --------------------------------------------------------------------------- 沙箱环境

class Sandbox:
    """把配置目录、自启目录、单实例端口都隔离到临时目录，绝不写用户系统。"""

    def __init__(self, tmpdir):
        self.tmp = tmpdir
        os.makedirs(tmpdir, exist_ok=True)
        assets_src = os.path.join(PROJ, 'assets')
        assets_dst = os.path.join(tmpdir, 'assets')
        if os.path.exists(assets_src) and not os.path.exists(assets_dst):
            shutil.copytree(assets_src, assets_dst)
        os.environ['GUIT_INSTANCE_PORT'] = str(_free_port())

    def install(self):
        if PROJ not in sys.path:
            sys.path.insert(0, PROJ)
        import config_store
        config_store.app_dir = lambda: self.tmp
        config_store.config_path = lambda: os.path.join(self.tmp, 'config.json')
        import autostart
        autostart.startup_dir = lambda: os.path.join(self.tmp, 'Startup')
        import portal_client
        portal_client.ONLINE_PROBES = ()   # 只信任用例里配置的探测源，避免真上外网
        return config_store


def portal_code(portal, client):
    """取该 HTTP 会话当前有效的验证码（模拟门户侧的真实值）。"""
    sid = None
    for c in client.jar:
        if c.name == 'ASP.NET_SessionId':
            sid = c.value
    return portal.state.codes.get(sid, '')


def last_issued(portal):
    """最近一次下发的验证码（OCR 替身用）。"""
    return portal.state.issued[-1][1] if portal.state.issued else ''


def _free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def patch_app_sandbox(app_module, tmp):
    """app.py 直接 from config_store import app_dir，需要一并替换。"""
    app_module.app_dir = lambda: tmp
