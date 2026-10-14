'''校园网门户登录核心（纯标准库，便于打包）。

适用门户：ASP.NET WebForms 网页认证（目标 http://10.6.6.6/login）。
设计依据见 docs/PLAN.md 第 2 节「现状核对」：
- POST 必须回填 __VIEWSTATE / __VIEWSTATEGENERATOR / __VIEWSTATEENCRYPTED / __EVENTVALIDATION；
- 验证码与 ASP.NET_SessionId 绑定，「取页面 → 取验证码 → 提交」必须处于同一会话；
- 登录失败时门户会返回登录页本身，错误文案位于 validation-summary-errors 的 <li> 中。
'''

import http.client
import http.cookiejar
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
HIDDEN_FIELDS = ('__VIEWSTATE', '__VIEWSTATEGENERATOR', '__VIEWSTATEENCRYPTED', '__EVENTVALIDATION')
LOGIN_SUCCESS_WORDS = ('联网成功', '登录成功')
LOGOFF_SUCCESS_WORDS = ('断开成功', '注销成功')
ONLINE_PROBES = (('http://www.msftconnecttest.com/connecttest.txt', 'Microsoft Connect Test'), ('http://www.gstatic.com/generate_204', ''), ('https://www.baidu.com', 'baidu'), ('http://www.baidu.com', 'baidu'))
KIND_OK = 'ok'
KIND_CAPTCHA = 'captcha'
KIND_CREDENTIAL = 'credential'
KIND_NETWORK = 'network'
KIND_UNKNOWN = 'unknown'
KIND_NEED_MANUAL = 'need_manual'
# 断开确认的兜底探测节奏：递减间隔 + 总预算，避免固定 4s×3 阻塞工作线程。
# 门户状态始终是第一判据（见 _confirm_offline），这里只覆盖「门户未确认」的情况。
CONFIRM_OFFLINE_INTERVALS = (2.0, 2.0, 1.0)
CONFIRM_OFFLINE_BUDGET = 6.0
# 上述节奏不可能超过 2s/次；用它给探测预算封顶，避免某个探测源被拖到 4s 超时。
CONFIRM_OFFLINE_PROBE_BUDGET = 2.0
# 进程内共用的 SSL 上下文（首次用到时才创建，见 _shared_ssl_context）
_SSL_CONTEXT = None
_SSL_CONTEXT_LOCK = threading.Lock()

class PortalError(Exception):
    '''门户交互异常（网络不通、页面结构变化等）。'''

@dataclass
class LoginResult:
    ok: bool
    message: str
    kind: str = KIND_UNKNOWN

@dataclass
class PortalStatus:
    '''门户侧的连接状态：当前用户 IP 与是否在线。'''

    ip: str = ''
    online: bool = False
    text: str = ''

def _probe_reachable(url: str, expect: str, timeout: float) -> bool:
    '''单个探测源是否命中（必须绕开系统代理，并校验响应内容）。

    expect 非空 → 必须读到该子串（防门户劫持页误判为「已联网」）；
    expect 为空 → 必须拿到 204 空响应，否则不算命中。
    '''

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as resp:
        if expect:
            body = resp.read(256).decode('utf-8', 'ignore')
            return expect in body
        return getattr(resp, 'status', 200) == 204


def _any_reachable(candidates, timeout: float) -> bool:
    '''并发探测多个外网源：任一命中即返回 True，全部失败才返回 False。

    为什么并发：串行探测 4 个源、每源 timeout=4s，未联网时最坏 ~16s 卡住
    GUI 工作线程；并发后最坏约等于单源超时，结论不变（仍是「任一命中」）。

    另外统计"已完成的探测数"：全部源都**已经出了结论**（例如连接被立即拒绝）
    就立刻返回 False，不再白等满整个 timeout 窗口——未联网时这一等曾让断开
    确认多花 2s。
    '''

    if not candidates:
        return False
    hit = threading.Event()
    done = threading.Semaphore(0)

    def run(url, expect):
        try:
            if _probe_reachable(url, expect, timeout):
                hit.set()
        except Exception:
            pass
        finally:
            done.release()

    for url, expect in candidates:
        threading.Thread(target=run, args=(url, expect), daemon=True).start()
    deadline = time.monotonic() + timeout + 0.5
    finished = 0
    total = len(candidates)
    while finished < total:
        if hit.is_set():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if done.acquire(timeout=min(0.1, remaining)):
            finished += 1
    # 边界：命中可能恰好发生在最后一次探测与最后判定之间，再确认一次。
    return hit.is_set()


def _shared_ssl_context():
    '''进程内复用一个 SSL 上下文。

    为什么必须复用：`urllib.request.build_opener()` 会实例化 `HTTPSHandler`，而它每次都会
    调 `ssl.create_default_context()` → `load_default_certs()` → **枚举 Windows 证书库**。
    实测（tools/py313，本机）：每次约 8~12ms，但证书库是系统级共享资源，在多线程/多进程
    并发访问时会退化到十几秒——表现为「程序启动后一直卡在获取验证码、连接按钮不可点」。
    进程内只建一次即可消除这个启动期抖动；探 HTTPS 源时行为不变。

    失败（无 ssl 等）时返回 None，交给 urllib 的默认行为。
    '''

    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        with _SSL_CONTEXT_LOCK:
            if _SSL_CONTEXT is None:
                try:
                    import ssl
                    _SSL_CONTEXT = ssl.create_default_context()
                except Exception:
                    _SSL_CONTEXT = False
    return _SSL_CONTEXT or None


def _extract_span(html: str, span_id: str) -> str:
    '''提取 <span id="...">内容</span> 的纯文本（剥离内层 <font> 等标签）。'''

    if not span_id:
        return ''
    match = re.search('id="%s"[^>]*>(.*?)</span>' % re.escape(span_id), html, re.S)
    if not match:
        return ''
    return re.sub('<[^>]+>', '', match.group(1)).strip()

class PortalClient:
    '''单次会话内的门户交互：探测 / 取页面 / 取验证码 / 提交。'''

    def __init__(self, cfg: dict, logger=None, timeout: int=8):
        self.cfg = cfg
        self.timeout = timeout
        self.log = logger or (lambda *_a, **_k: None)
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=_shared_ssl_context()),
        )
        self.opener.addheaders = [('User-Agent', USER_AGENT)]
        self.hidden = {}
        self.defaults = {}
        self.form_source = ''
        self.captcha_epoch = 0
        # 表单「代」：每次 GET 表单页 +1；取码时记住所属代，提交前核对，
        # 防止拿上一份表单/会话的旧码去提交。
        self._form_generation = 0
        self._captcha_form_generation = 0

    def _request(self, url: str, data: bytes=None, timeout: float=None):
        '''发起一次门户请求；任何失败都包装成 PortalError（上层只需捕一种异常）。

        捕获超集：HTTP 错误（服务器有响应但状态码非 2xx）、URL 错误（DNS /
        连接被拒 / 超时 / 代理）、以及 http.client 层的协议异常
        （门户主动断连时抛 RemoteDisconnected 等，它不是 URLError 子类，
        漏掉会以裸异常冒到 GUI 工作线程，显示成「内部错误」而不是可读原因）。
        '''

        if timeout is None:
            timeout = self.timeout
        try:
            with self.opener.open(url, data=data, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise PortalError('服务器返回 HTTP %s' % exc.code) from exc
        except urllib.error.URLError as exc:
            raise PortalError('无法连接门户：%s' % exc.reason) from exc
        except http.client.HTTPException as exc:
            raise PortalError('门户响应异常：%s' % exc) from exc
        except Exception as exc:
            raise PortalError('请求失败：%s' % exc) from exc

    def is_online(self, max_wait: float=None) -> bool:
        '''探测外网可达性；多源并发降级，任一命中即视为已联网。

        必须绕开系统代理，并校验响应内容，避免门户劫持重定向造成误判。
        为什么用多源：实测本网络 `https://www.msftconnecttest.com/connecttest.txt`
        与 `https://connectivitycheck.gstatic.com/generate_204` 均不可达
        （TLS 被阻断，curl 返回 000），只探测单一 HTTPS 源会把「已联网」
        判成离线，进而把成功的登录/断网误报为失败。

        max_wait: 可选的额外墙钟上限（秒）。给定时用它给单源超时封顶，
        使本函数在「门户未确认、只能靠探测兜底」的场景里也能快速返回。
        '''

        probe = self.cfg.get('onlineProbe') or {}
        timeout = int(probe.get('timeout', 4) or 4)
        if max_wait is not None:
            timeout = max(1, min(timeout, int(max_wait)))
        candidates = []
        if probe.get('url'):
            candidates.append((probe['url'], probe.get('expect', '')))
        candidates.extend(ONLINE_PROBES)
        return _any_reachable(candidates, timeout)

    def _parse_form_defaults(self, html: str) -> dict:
        '''解析页面上所有输入控件的默认值。

        提交时原样带回，与浏览器行为保持一致——门户可能依赖这些字段，
        例如登录页的 `ctl00$MainContent$TextBoxISP`（默认「自动选择」），
        此前未提交该字段，与浏览器实际提交内容不一致。
        '''

        defaults = {}
        for tag in re.findall('<input\\b[^>]*>', html, re.I):
            name = re.search('\\bname="([^"]*)"', tag, re.I)
            if not name or not name.group(1):
                continue
            value = re.search('\\bvalue="([^"]*)"', tag, re.I)
            defaults[name.group(1)] = value.group(1) if value else ''
        return defaults

    @staticmethod
    def _parse_hidden(html: str) -> dict:
        '''抽取 ASP.NET 隐藏字段（__VIEWSTATE 家族）。'''

        hidden = {}
        for name in HIDDEN_FIELDS:
            match = re.search('name="%s"[^>]*value="([^"]*)"' % re.escape(name), html)
            if match:
                hidden[name] = match.group(1)
        return hidden

    def _load_form(self, url: str, what: str) -> str:
        '''GET 一个表单页并缓存它的隐藏字段与控件默认值。

        登录页（open_session）与注销页（prepare_logoff）流程完全一致，只有
        URL 与报错文案不同；两者都必须校验 __VIEWSTATE 存在，否则后续提交
        只会拿到门户的无提示空壳页。返回页面 HTML 供调用方继续解析
        （注销页还要从同一份 HTML 里读门户状态，避免重复 GET）。
        '''

        html = self._request(url).decode('utf-8', 'ignore')
        self.hidden = self._parse_hidden(html)
        if '__VIEWSTATE' not in self.hidden:
            raise PortalError('%s解析失败：未找到 __VIEWSTATE（门户可能已改版）' % what)
        self.defaults = self._parse_form_defaults(html)
        self._form_generation += 1
        return html

    def open_session(self) -> None:
        '''GET 登录页，缓存隐藏字段与各控件默认值（新会话必须调用一次）。'''

        self._load_form(self.cfg['portalUrl'], '登录页')
        self.form_source = 'login'

    def fetch_captcha(self) -> bytes:
        '''获取验证码图片（PNG）。

        取码会使同会话上一张码失效（实测），因此这里推进 captcha_epoch，
        供上层判断界面上的码是否过期。
        '''

        data = self._request(self.cfg['captchaUrl'])
        if not data or data[:4] != b'\x89PNG':
            raise PortalError('验证码获取失败（未返回 PNG）')
        self.captcha_epoch += 1
        self._captcha_form_generation = self._form_generation
        return data

    def submit(self, guid: str, acc: str, pwd: str, captcha: str) -> LoginResult:
        if self.form_source != 'login':
            self.open_session()
        if self._captcha_form_generation != self._form_generation:
            # 表单被重新取过、但验证码还是上一轮那张：该码属于上一份表单/会话，
            # 直接提交只会拿到门户的无提示空壳页（实测 2530 字节），必须让界面
            # 重新取码；否则会把「没有有效验证码」当成一次真实登录尝试。
            self.fetch_captcha()
            return LoginResult(False, '登录表单已刷新，请重新输入验证码', KIND_CAPTCHA)
        fields = dict(self.defaults)
        fields.update(self.hidden)
        names = self.cfg['fields']
        fields[names['guid']] = guid or ''
        fields[names['acc']] = acc or guid or ''
        fields[names['pwd']] = pwd or ''
        fields[names['captcha']] = captcha or ''
        fields[names['submit']] = self.cfg.get('submitValue', '登录')
        payload = urllib.parse.urlencode(fields).encode('utf-8')
        prior = self.refresh_portal_status()
        html = self._request(self.cfg['submitUrl'], data=payload).decode('utf-8', 'ignore')
        result = self._judge(html)
        if result.ok:
            return result
        if result.kind != KIND_UNKNOWN:
            return result
        status = self.refresh_portal_status()
        was_online = prior.text != '未知' and prior.online
        now_online = status.text != '未知' and status.online
        # 只有已知「提交前不在线、提交后在线」才算状态证据；提交前就已在线时，
        # 状态 span 无法区分「本次登录成功」和「本来就通着」，不能据此报成功。
        if now_online and not was_online:
            return LoginResult(True, '登录成功（门户状态显示已联网）', KIND_OK)
        return LoginResult(False, result.message or '登录结果无法确认：门户未给出明确提示，请稍后查看状态', KIND_UNKNOWN)

    def _judge(self, html: str) -> LoginResult:
        '''按响应内容判定成败并分类（纯函数，不发请求）。

判定顺序（依据实测的门户行为）：
1. 先认门户的**登录成功文案**（实测登录成功 = 「联网成功!」，此时页面
   仍是登录页样式）；不采用泛化的「成功」，避免异常页误判；
2. 仍是登录页 → 按文案分类 captcha / credential / unknown；
3. 响应里没有登录控件 —— **不直接判成功**（门户改版、维护页、错误页
   都长这样），返回 unknown 交给 submit() 用门户状态复核。
'''

        text = self._extract_error(html)
        if text and '验证码' not in text:
            if any((w in text for w in LOGIN_SUCCESS_WORDS)):
                return LoginResult(True, text, KIND_OK)
        names = self.cfg['fields']
        still_login_page = names['captcha'] in html or names['submit'] in html
        if still_login_page:
            if '验证码' in text:
                kind = KIND_CAPTCHA
            elif '密码' in text or '账号' in text or '锁定' in text:
                kind = KIND_CREDENTIAL
            else:
                kind = KIND_UNKNOWN
            return LoginResult(False, text or '登录失败（门户返回登录页）', kind)
        return LoginResult(False, text or '门户未返回登录页，登录结果待确认', KIND_UNKNOWN)

    @staticmethod
    def _extract_error(html: str) -> str:
        '''提取门户返回的校验错误文本。

        ASP.NET 的错误提示有两种常见形态：`<li>错误</li>` 列表，
        或 `<p class="validation-summary-errors">错误</p>` 纯文本块。
        后者块内没有尖括号，必须先去标签再取文本，否则会漏掉错误内容
        （曾导致「验证码错误」等提示无法识别，登录/注销都只能报「未确认」）。
        '''

        msgs = re.findall('<li>([^<]{2,80})</li>', html)
        if not msgs:
            block = re.search('validation-summary-errors[^>]*>(.*?)</(?:div|ul|p|span)', html, re.S)
            if block:
                text = re.sub('<[^>]+>', ' ', block.group(1))
                text = re.sub('\\s+', ' ', text).strip()
                if text:
                    msgs = [text]
        cleaned = [m.strip() for m in msgs if m.strip()]
        return '；'.join(cleaned)

    def logoff_url(self) -> str:
        return self.cfg.get('logoffUrl') or 'http://10.6.6.6/logoff'

    def _parse_status(self, html: str) -> PortalStatus:
        names = self.cfg.get('statusFields') or {}
        ip = _extract_span(html, names.get('ip', 'MainContent_LocalIP'))
        text = _extract_span(html, names.get('online', 'MainContent_LabelOnline'))
        online = '已联网' in text
        return PortalStatus(ip=ip, online=online, text=text or ('已联网' if online else '未知'))

    def query_status(self) -> PortalStatus:
        '''查询门户侧的当前用户 IP 与在线状态（读取注销页，不做任何提交）。'''

        html = self._request(self.logoff_url()).decode('utf-8', 'ignore')
        return self._parse_status(html)

    def prepare_logoff(self):
        '''准备断开网络：取注销页隐藏字段与验证码，返回 (PNG 字节, 门户状态)。

        注意：注销必须回填注销页自身的 __VIEWSTATE，因此这里会覆盖会话中缓存的
        隐藏字段；调用方在注销失败后再执行登录需重新 prepare()。
        '''

        # 状态取自同一份 HTML，避免为了拿 ViewState 和拿状态而 GET 两次注销页。
        html = self._load_form(self.logoff_url(), '注销页')
        status = self._parse_status(html)
        captcha = self._request(self.cfg['captchaUrl'])
        if not captcha or captcha[:4] != b'\x89PNG':
            raise PortalError('验证码获取失败（未返回 PNG）')
        self.form_source = 'logoff'
        self.captcha_epoch += 1
        self._captcha_form_generation = self._form_generation
        return captcha, status

    def invalidate_form(self) -> None:
        '''作废当前缓存的表单状态：下一次提交前必须重新取页面。

        注销页与登录页的 __VIEWSTATE / __EVENTVALIDATION 不通用；注销成功后
        必须清掉，否则紧接着的登录会拿注销页的字段提交，门户只会返回一个
        无提示的异常页（实测 2530 字节空壳）。
        '''

        self.form_source = ''
        self.hidden = {}
        self.defaults = {}
        # 让 submit() 拒绝拿上一轮的码提交（注销成功后门户会话仍认那张旧码，
        # 不拦就会把「没有有效验证码」误报成「登录成功」）。
        self._captcha_form_generation = -1

    def refresh_portal_status(self) -> PortalStatus:
        '''重新 GET 注销页读取门户状态（只读，不覆盖表单状态）。

        必须重新取：POST /logoff 的响应页里渲染的是**提交前**的旧状态
        （实测提交后该页仍写「已联网」，紧接着的 GET /logoff 才变成「未联网」）。
        '''

        try:
            html = self._request(self.logoff_url()).decode('utf-8', 'ignore')
            return self._parse_status(html)
        except PortalError:
            return PortalStatus()

    def _confirm_offline(self, ok_message: str, fallback: str='', portal_status: 'PortalStatus'=None) -> LoginResult:
        '''确认断开：**以门户状态为主判据**，外网探测只作补充。

        为什么不以外网可达为准（实测依据）：本机提交注销后门户状态变成
        「未联网」，但外网依旧可达——这条出口连接并不由该门户会话控制
        （路由器 / 其他设备 / 其他认证通道）。若按外网判定，会永远得到
        「断开未生效」的结论，把已经成功的注销报成失败。

        顺序：
        1. 重新读门户状态，显示「未联网」→ 直接成功（实测亚秒级，无需等待）；
        2. 否则按递减间隔（2s/2s/1s，总预算 6s）最多探测 3 次，确认是否真的断网；
           每次探测的墙钟也被压到 2s 内，避免单个慢探测源把工作线程拖住；
        3. 门户已受理但本机外网仍通 → 如实说明，不谎报失败。

        判据优先级没变（门户 > 探测），改的是等待节奏、总时长上限，以及
        fallback 的使用时机：只有**探测本身也没给出结论**（每次探测都异常）
        时才交给 fallback；探测有结论时以探测结论为准。
        '''

        fresh = self.refresh_portal_status()
        if fresh.text != '未知' and not fresh.online:
            return LoginResult(True, '已断开网络（门户已确认下线）', KIND_OK)
        if portal_status is not None and portal_status.text != '未知' and not portal_status.online:
            return LoginResult(True, '已断开网络（门户已确认下线）', KIND_OK)
        deadline = time.monotonic() + CONFIRM_OFFLINE_BUDGET
        conclusive = False
        for interval in CONFIRM_OFFLINE_INTERVALS:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
            try:
                # 探测也要吃预算：否则「2s 间隔 + 4s 单源超时」会突破总预算。
                probe_budget = max(1.0, min(CONFIRM_OFFLINE_PROBE_BUDGET, deadline - time.monotonic()))
                online = self.is_online(max_wait=probe_budget)
            except Exception:
                continue
            conclusive = True
            if not online:
                return LoginResult(True, ok_message, KIND_OK)
        if not conclusive and fallback:
            return LoginResult(False, fallback, KIND_UNKNOWN)
        # 门户没给出「未联网」，但探测证明本机外网仍通：如实说明，不谎报失败，
        # 并把「门户已受理注销请求」与「外网仍可达」两件事都写清楚。
        return LoginResult(True, '已断开网络（门户已受理注销请求；本机外网仍可达，说明这条连接可能不由门户控制）', KIND_OK)

    def submit_logoff(self, captcha: str) -> LoginResult:
        '''提交注销（断开网络）。

判定顺序（依据实测的门户行为）：
0. **先检查表单来源**：若中途调用过 prepare()（启动预取 / 点「换一张」），
   self.hidden 已被登录页的 ViewState 覆盖，拿它提交只会拿到门户的
   无提示空壳页（实测 2530 字节），因此这里直接刷新注销页并让界面重新输码；
1. 门户把「注销成功!」「验证码错误!」都放在 validation-summary 块里，
   先看提取到的提示文字——含「验证码」即验证码错误；
2. 成功文案「成功」或状态 span 显示未联网 → 交 _confirm_offline（门户优先）；
3. 都不明确时用外网探测做最终判定（见 _confirm_offline）。
'''

        if self.form_source != 'logoff':
            self.prepare_logoff()
            return LoginResult(False, '注销页状态已刷新，请重新输入验证码', KIND_CAPTCHA)
        names = self.cfg.get('logoffFields') or {}
        fields = dict(self.defaults)
        fields.update(self.hidden)
        fields[names.get('captcha', 'ctl00$MainContent$TextBoxCC')] = captcha or ''
        fields[names.get('submit', 'ctl00$MainContent$LogoffBtn')] = names.get('submitValue', '注销')
        payload = urllib.parse.urlencode(fields).encode('utf-8')
        html = self._request(self.logoff_url(), data=payload).decode('utf-8', 'ignore')
        text = self._extract_error(html)
        if '验证码' in text:
            return LoginResult(False, text or '验证码错误', KIND_CAPTCHA)
        status = self._parse_status(html)
        portal_offline = status.text != '未知' and not status.online
        if any((w in text for w in LOGOFF_SUCCESS_WORDS)) or portal_offline:
            result = self._confirm_offline('已断开网络（门户已受理注销请求）', portal_status=status)
        else:
            if text:
                return LoginResult(False, text, KIND_UNKNOWN)
            result = self._confirm_offline('已断开网络', fallback='断开失败：门户未确认状态变化', portal_status=status)
        if result.ok:
            self.invalidate_form()
        return result


class LoginSession:
    '''把「开会话 → 取验证码 → 提交」串起来，供 GUI 与静默模式共用。

    注意：换验证码必须重新 prepare()，因为验证码与 Session 绑定。
    '''

    def __init__(self, cfg: dict, logger=None):
        self.cfg = cfg
        self.client = PortalClient(cfg, logger)
        self.captcha_png = b''

    def is_online(self) -> bool:
        return self.client.is_online()

    def needs_login(self) -> bool:
        '''是否需要登录：**以门户状态为准**，外网探测只在门户状态未知时兜底。

        实测依据（这是「软件点连接一直连不上」的根因）：
        门户显示「未联网」时，本机外网探测依旧全都可达（baidu / gstatic /
        msftconnecttest 实测 200/204），这些目标显然是未认证状态下的放行白名单。
        旧逻辑用外网可达判断，于是软件直接回「网络已连通，无需登录」——
        **根本没有提交登录**，门户侧始终未认证；用户看到的就是「连不上」，
        只能自己去网页门户登录。
        '''

        try:
            status = self.query_status()
        except PortalError:
            return not self.is_online()
        if status.text != '未知':
            return not status.online
        return not self.is_online()

    def prepare(self) -> bytes:
        '''开启新会话并获取验证码图片，返回 PNG 字节。'''

        self.client.open_session()
        self.captcha_png = self.client.fetch_captcha()
        return self.captcha_png

    def submit(self, captcha: str) -> LoginResult:
        # 配置里 user 不是对象时（手改 config.json）不能让它冒 AttributeError
        # 到 GUI 工作线程：退化为空账号，由门户报「账号或密码错误」更清楚。
        user = self.cfg.get('user')
        if not isinstance(user, dict):
            user = {}
        return self.client.submit(user.get('guid', ''), user.get('acc', ''), user.get('pwd', ''), captcha)

    def query_status(self) -> PortalStatus:
        '''查询门户侧连接状态（IP + 是否在线）。'''

        return self.client.query_status()

    def prepare_logoff(self):
        '''准备断开网络：返回 (验证码 PNG, 门户状态)，同时更新本地验证码缓存。'''

        captcha, status = self.client.prepare_logoff()
        self.captcha_png = captcha
        return captcha, status

    def submit_logoff(self, captcha: str) -> LoginResult:
        '''提交注销（断开网络）。'''

        return self.client.submit_logoff(captcha)


def auto_login(cfg: dict, logger, ocr=None, on_captcha=None) -> LoginResult:
    '''全自动登录（供 --silent 使用）：识别成功则提交，验证码错自动换图重试。

    on_captcha(png: bytes, guess: str) 可选，用于把最新验证码交给界面显示。
    返回 kind == KIND_NEED_MANUAL 时，调用方应展示界面让用户手输。
    '''

    use_ocr = bool((cfg.get('options') or {}).get('useOcr', True)) and ocr is not None
    max_retry = int(cfg.get('maxCaptchaRetry', 3) or 3)
    session = LoginSession(cfg, logger)
    if not session.needs_login():
        logger.info('门户显示已联网，无需登录')
        return LoginResult(True, '网络已连通，无需登录', KIND_OK)
    last_png = b''
    for attempt in range(1, max_retry + 1):
        try:
            last_png = session.prepare()
        except PortalError as exc:
            logger.error(str(exc))
            return LoginResult(False, str(exc), KIND_NETWORK)
        guess = ''
        if use_ocr and ocr.available():
            guess = ocr.classify(last_png)
        if on_captcha:
            on_captcha(last_png, guess)
        if not guess:
            logger.warn('自动识别未得到结果，需手动输入验证码')
            return LoginResult(False, '需要手动输入验证码', KIND_NEED_MANUAL)
        try:
            result = session.submit(guess)
        except PortalError as exc:
            logger.error(str(exc))
            return LoginResult(False, str(exc), KIND_NETWORK)
        if result.ok:
            logger.info('登录成功（识别为 %s）' % guess)
            return result
        if result.kind != KIND_CAPTCHA:
            logger.error('登录被拒绝：%s' % result.message)
            return result
        logger.warn('验证码识别错误（%s），换一张重试 %d/%d' % (guess, attempt, max_retry))
        continue
    logger.error('连续 %d 次验证码识别失败' % max_retry)
    return LoginResult(False, '连续 %d 次识别失败，请手动输入验证码' % max_retry, KIND_NEED_MANUAL)

# WARNING: Decompyle incomplete
