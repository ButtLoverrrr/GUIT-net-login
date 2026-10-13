# -*- coding: utf-8 -*-
"""校园网门户登录核心（纯标准库，便于打包）。

适用门户：ASP.NET WebForms 网页认证（目标 http://10.6.6.6/login）。
设计依据见 docs/PLAN.md 第 2 节「现状核对」：
- POST 必须回填 __VIEWSTATE / __VIEWSTATEGENERATOR / __VIEWSTATEENCRYPTED / __EVENTVALIDATION；
- 验证码与 ASP.NET_SessionId 绑定，「取页面 → 取验证码 → 提交」必须处于同一会话；
- 登录失败时门户会返回登录页本身，错误文案位于 validation-summary-errors 的 <li> 中。
"""

import http.cookiejar
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# ASP.NET WebForms 隐藏字段：提交时必须原样回填
HIDDEN_FIELDS = (
    "__VIEWSTATE",
    "__VIEWSTATEGENERATOR",
    "__VIEWSTATEENCRYPTED",
    "__EVENTVALIDATION",
)

# 门户在 validation-summary 里给出的成功文案。
# 实测：本门户**登录成功时仍渲染登录页样式**（含验证码框与登录按钮），
# 只在提示块里写「联网成功!」，因此成功判定必须认文案，不能只看页面是否跳转。
#
# 注意：**不要**把泛化的「成功」放进来——异常页、维护通知里也可能出现该词，
# 会把失败报成成功。登录与注销各用一组明确的文案。
LOGIN_SUCCESS_WORDS = ("联网成功", "登录成功")
LOGOFF_SUCCESS_WORDS = ("断开成功", "注销成功")

# 在线探测候选：按序降级，任一命中即视为已联网。
# 实测本网络 https://www.msftconnecttest.com 与 https://connectivitycheck.gstatic.com
# 的 TLS 被阻断（curl 返回 000），只用单一 HTTPS 源会把「已联网」判成离线。
ONLINE_PROBES = (
    ("http://www.msftconnecttest.com/connecttest.txt", "Microsoft Connect Test"),
    ("http://www.gstatic.com/generate_204", ""),
    ("https://www.baidu.com", "baidu"),
    ("http://www.baidu.com", "baidu"),
)

# 结果分类：决定上层是重试（captcha）还是直接报错（credential）
KIND_OK = "ok"
KIND_CAPTCHA = "captcha"
KIND_CREDENTIAL = "credential"
KIND_NETWORK = "network"
KIND_UNKNOWN = "unknown"
KIND_NEED_MANUAL = "need_manual"


class PortalError(Exception):
    """门户交互异常（网络不通、页面结构变化等）。"""


@dataclass
class LoginResult:
    ok: bool
    message: str
    kind: str = KIND_UNKNOWN


@dataclass
class PortalStatus:
    """门户侧的连接状态：当前用户 IP 与是否在线。"""

    ip: str = ""
    online: bool = False
    text: str = ""


def _extract_span(html: str, span_id: str) -> str:
    """提取 <span id="...">内容</span> 的纯文本（剥离内层 <font> 等标签）。"""
    if not span_id:
        return ""
    match = re.search(r'id="%s"[^>]*>(.*?)</span>' % re.escape(span_id), html, re.S)
    if not match:
        return ""
    return re.sub(r"<[^>]+>", "", match.group(1)).strip()


class PortalClient:
    """单次会话内的门户交互：探测 / 取页面 / 取验证码 / 提交。"""

    def __init__(self, cfg: dict, logger=None, timeout: int = 8):
        self.cfg = cfg
        self.timeout = timeout
        self.log = logger or (lambda *_a, **_k: None)
        self.jar = http.cookiejar.CookieJar()
        # 显式绕开系统代理：门户是内网地址（如 10.6.6.6），经代理转发常导致连接失败
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.jar),
        )
        self.opener.addheaders = [("User-Agent", USER_AGENT)]
        self.hidden = {}
        self.defaults = {}  # 页面各输入控件的默认值，提交时原样带回
        # 当前 hidden/defaults 来自哪个页面（"login" / "logoff"）。
        # 两页的 __VIEWSTATE 与 __EVENTVALIDATION 不通用：实测拿登录页的
        # ViewState 去 POST /logoff，门户只回一个 2530 字节的无提示空壳页。
        self.form_source = ""
        # 验证码代数：同一会话每取一次码 +1。实测取新码会让上一张立即失效，
        # 上层用它判断「界面上那张码是否还能用」。
        self.captcha_epoch = 0

    # ------------------------------------------------------------------ 网络
    def _request(self, url: str, data: bytes = None):
        try:
            with self.opener.open(url, data=data, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise PortalError("服务器返回 HTTP %s" % exc.code) from exc
        except urllib.error.URLError as exc:
            raise PortalError("无法连接门户：%s" % exc.reason) from exc
        except Exception as exc:  # 超时等
            raise PortalError("请求失败：%s" % exc) from exc

    # -------------------------------------------------------------- 在线探测
    def is_online(self) -> bool:
        """探测外网可达性；多源降级，任一命中即视为已联网。

        必须绕开系统代理，并校验响应内容，避免门户劫持重定向造成误判。
        为什么用多源：实测本网络 `https://www.msftconnecttest.com/connecttest.txt`
        与 `https://connectivitycheck.gstatic.com/generate_204` 均不可达
        （TLS 被阻断，curl 返回 000），只探测单一 HTTPS 源会把「已联网」
        判成离线，进而把成功的登录/断网误报为失败。
        """
        probe = self.cfg.get("onlineProbe") or {}
        timeout = int(probe.get("timeout", 4) or 4)
        candidates = []
        if probe.get("url"):
            candidates.append((probe["url"], probe.get("expect", "")))
        candidates.extend(ONLINE_PROBES)

        for url, expect in candidates:
            try:
                # 同样绕开代理：探测的是「出口网络是否已放行」，走代理会误判
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(url, timeout=timeout) as resp:
                    if expect:
                        body = resp.read(256).decode("utf-8", "ignore")
                        if expect in body:
                            return True
                    elif getattr(resp, "status", 200) == 204:
                        return True
            except Exception:
                continue
        return False

    def _parse_form_defaults(self, html: str) -> dict:
        """解析页面上所有输入控件的默认值。

        提交时原样带回，与浏览器行为保持一致——门户可能依赖这些字段，
        例如登录页的 `ctl00$MainContent$TextBoxISP`（默认「自动选择」），
        此前未提交该字段，与浏览器实际提交内容不一致。
        """
        defaults = {}
        for tag in re.findall(r"<input\b[^>]*>", html, re.I):
            name = re.search(r'\bname="([^"]*)"', tag, re.I)
            if not name or not name.group(1):
                continue
            value = re.search(r'\bvalue="([^"]*)"', tag, re.I)
            defaults[name.group(1)] = value.group(1) if value else ""
        return defaults

    # ------------------------------------------------------------ 会话与页面
    def open_session(self) -> None:
        """GET 登录页，缓存隐藏字段与各控件默认值（新会话必须调用一次）。"""
        html = self._request(self.cfg["portalUrl"]).decode("utf-8", "ignore")
        self.hidden = {}
        for name in HIDDEN_FIELDS:
            match = re.search(
                r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), html
            )
            if match:
                self.hidden[name] = match.group(1)
        if "__VIEWSTATE" not in self.hidden:
            raise PortalError("登录页解析失败：未找到 __VIEWSTATE（门户可能已改版）")
        self.defaults = self._parse_form_defaults(html)
        self.form_source = "login"

    def fetch_captcha(self) -> bytes:
        """获取验证码图片（PNG）。

        取码会使同会话上一张码失效（实测），因此这里推进 captcha_epoch，
        供上层判断界面上的码是否过期。
        """
        data = self._request(self.cfg["captchaUrl"])
        if not data or data[:4] != b"\x89PNG":
            raise PortalError("验证码获取失败（未返回 PNG）")
        self.captcha_epoch += 1
        return data

    # ------------------------------------------------------------------ 提交
    def submit(self, guid: str, acc: str, pwd: str, captcha: str) -> LoginResult:
        # 来源守卫：上一次可能取的是注销页，两页的 __VIEWSTATE / __EVENTVALIDATION
        # 不通用（实测错配会让门户返回无提示的异常页）。与 submit_logoff 对称。
        if self.form_source != "login":
            self.open_session()

        # 页面上各控件的默认值（含 ISP 等）+ 隐藏字段，再用用户填写的内容覆盖
        fields = dict(self.defaults)
        fields.update(self.hidden)
        names = self.cfg["fields"]
        fields[names["guid"]] = guid or ""
        fields[names["acc"]] = acc or guid or ""
        fields[names["pwd"]] = pwd or ""
        fields[names["captcha"]] = captcha or ""
        fields[names["submit"]] = self.cfg.get("submitValue", "登录")
        payload = urllib.parse.urlencode(fields).encode("utf-8")
        html = self._request(self.cfg["submitUrl"], data=payload).decode(
            "utf-8", "ignore"
        )
        result = self._judge(html)
        if result.ok:
            return result
        if result.kind != KIND_UNKNOWN:
            return result

        # 门户没给出明确提示：**改用门户状态复核**。
        # 绝不拿「外网是否可达」当登录成功的依据——实测未认证时
        # baidu / gstatic / msftconnecttest 全都可达（放行白名单），
        # 用它确认会把失败报成成功（旧实现就是这么误报的）。
        status = self.refresh_portal_status()
        if status.text != "未知" and status.online:
            return LoginResult(True, "登录成功（门户状态显示已联网）", KIND_OK)
        return LoginResult(
            False,
            result.message or "登录结果无法确认：门户未给出明确提示，请稍后查看状态",
            KIND_UNKNOWN,
        )

    def _judge(self, html: str) -> LoginResult:
        """按响应内容判定成败并分类（纯函数，不发请求）。

        判定顺序（依据实测的门户行为）：
        1. 先认门户的**登录成功文案**（实测登录成功 = 「联网成功!」，此时页面
           仍是登录页样式）；不采用泛化的「成功」，避免异常页误判；
        2. 仍是登录页 → 按文案分类 captcha / credential / unknown；
        3. 响应里没有登录控件 —— **不直接判成功**（门户改版、维护页、错误页
           都长这样），返回 unknown 交给 submit() 用门户状态复核。
        """
        text = self._extract_error(html)
        if text and "验证码" not in text and any(w in text for w in LOGIN_SUCCESS_WORDS):
            return LoginResult(True, text, KIND_OK)

        names = self.cfg["fields"]
        still_login_page = (
            names["captcha"] in html or names["submit"] in html
        )
        if still_login_page:
            if "验证码" in text:
                kind = KIND_CAPTCHA
            elif "密码" in text or "账号" in text or "锁定" in text:
                kind = KIND_CREDENTIAL
            else:
                kind = KIND_UNKNOWN
            return LoginResult(False, text or "登录失败（门户返回登录页）", kind)
        return LoginResult(
            False,
            text or "门户未返回登录页，登录结果待确认",
            KIND_UNKNOWN,
        )

    @staticmethod
    @staticmethod
    def _extract_error(html: str) -> str:
        """提取门户返回的校验错误文本。

        ASP.NET 的错误提示有两种常见形态：`<li>错误</li>` 列表，
        或 `<p class="validation-summary-errors">错误</p>` 纯文本块。
        后者块内没有尖括号，必须先去标签再取文本，否则会漏掉错误内容
        （曾导致「验证码错误」等提示无法识别，登录/注销都只能报「未确认」）。
        """
        msgs = re.findall(r"<li>([^<]{2,80})</li>", html)
        if not msgs:
            block = re.search(
                r"validation-summary-errors[^>]*>(.*?)</(?:div|ul|p|span)",
                html,
                re.S,
            )
            if block:
                text = re.sub(r"<[^>]+>", " ", block.group(1))
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    msgs = [text]
        cleaned = [m.strip() for m in msgs if m.strip()]
        return "；".join(cleaned)

    # --------------------------------------------------------- 状态与注销
    def logoff_url(self) -> str:
        return self.cfg.get("logoffUrl") or "http://10.6.6.6/logoff"

    def _parse_status(self, html: str) -> PortalStatus:
        names = self.cfg.get("statusFields") or {}
        ip = _extract_span(html, names.get("ip", "MainContent_LocalIP"))
        text = _extract_span(html, names.get("online", "MainContent_LabelOnline"))
        online = "已联网" in text
        return PortalStatus(
            ip=ip, online=online, text=text or ("已联网" if online else "未知")
        )

    def query_status(self) -> PortalStatus:
        """查询门户侧的当前用户 IP 与在线状态（读取注销页，不做任何提交）。"""
        html = self._request(self.logoff_url()).decode("utf-8", "ignore")
        return self._parse_status(html)

    def prepare_logoff(self):
        """准备断开网络：取注销页隐藏字段与验证码，返回 (PNG 字节, 门户状态)。

        注意：注销必须回填注销页自身的 __VIEWSTATE，因此这里会覆盖会话中缓存的
        隐藏字段；调用方在注销失败后再执行登录需重新 prepare()。
        """
        html = self._request(self.logoff_url()).decode("utf-8", "ignore")
        self.hidden = {}
        for name in HIDDEN_FIELDS:
            match = re.search(
                r'name="%s"[^>]*value="([^"]*)"' % re.escape(name), html
            )
            if match:
                self.hidden[name] = match.group(1)
        if "__VIEWSTATE" not in self.hidden:
            raise PortalError("注销页解析失败：未找到 __VIEWSTATE（门户可能已改版）")
        self.defaults = self._parse_form_defaults(html)
        status = self._parse_status(html)
        captcha = self._request(self.cfg["captchaUrl"])
        if not captcha or captcha[:4] != b"\x89PNG":
            raise PortalError("验证码获取失败（未返回 PNG）")
        # 注销页的 ViewState 已就位，且这张码是当前会话最后一张
        self.form_source = "logoff"
        self.captcha_epoch += 1
        return captcha, status

    def invalidate_form(self) -> None:
        """作废当前缓存的表单状态：下一次提交前必须重新取页面。

        注销页与登录页的 __VIEWSTATE / __EVENTVALIDATION 不通用；注销成功后
        必须清掉，否则紧接着的登录会拿注销页的字段提交，门户只会返回一个
        无提示的异常页（实测 2530 字节空壳）。
        """
        self.form_source = ""
        self.hidden = {}
        self.defaults = {}

    def refresh_portal_status(self) -> PortalStatus:
        """重新 GET 注销页读取门户状态（只读，不覆盖表单状态）。

        必须重新取：POST /logoff 的响应页里渲染的是**提交前**的旧状态
        （实测提交后该页仍写「已联网」，紧接着的 GET /logoff 才变成「未联网」）。
        """
        try:
            html = self._request(self.logoff_url()).decode("utf-8", "ignore")
            return self._parse_status(html)
        except PortalError:
            return PortalStatus()

    def _confirm_offline(self, ok_message: str, fallback: str = "",
                         portal_status: "PortalStatus" = None) -> LoginResult:
        """确认断开：**以门户状态为主判据**，外网探测只作补充。

        为什么不以外网可达为准（实测依据）：本机提交注销后门户状态变成
        「未联网」，但外网依旧可达——这条出口连接并不由该门户会话控制
        （路由器 / 其他设备 / 其他认证通道）。若按外网判定，会永远得到
        「断开未生效」的结论，把已经成功的注销报成失败。

        顺序：
        1. 重新读门户状态，显示「未联网」→ 直接成功（实测亚秒级，无需等待）；
        2. 否则最多探测 3 次、每次间隔 4 秒，确认是否真的断网；
        3. 门户已受理但本机外网仍通 → 如实说明，不谎报失败。
        """
        fresh = self.refresh_portal_status()
        if fresh.text != "未知" and not fresh.online:
            return LoginResult(True, ok_message + "（门户已确认下线）", KIND_OK)
        if portal_status is not None and portal_status.text != "未知" and not portal_status.online:
            return LoginResult(True, ok_message + "（门户已确认下线）", KIND_OK)
        for _ in range(3):
            time.sleep(4)
            try:
                if not self.is_online():
                    return LoginResult(True, ok_message, KIND_OK)
            except Exception:
                pass
        if fallback:
            return LoginResult(False, fallback, KIND_UNKNOWN)
        return LoginResult(
            True,
            ok_message + "（门户已受理；本机外网仍可达，说明这条连接可能不由门户控制）",
            KIND_OK,
        )

    def submit_logoff(self, captcha: str) -> LoginResult:
        """提交注销（断开网络）。

        判定顺序（依据实测的门户行为）：
        0. **先检查表单来源**：若中途调用过 prepare()（启动预取 / 点「换一张」），
           self.hidden 已被登录页的 ViewState 覆盖，拿它提交只会拿到门户的
           无提示空壳页（实测 2530 字节），因此这里直接刷新注销页并让界面重新输码；
        1. 门户把「注销成功!」「验证码错误!」都放在 validation-summary 块里，
           先看提取到的提示文字——含「验证码」即验证码错误；
        2. 成功文案「成功」或状态 span 显示未联网 → 交 _confirm_offline（门户优先）；
        3. 都不明确时用外网探测做最终判定（见 _confirm_offline）。
        """
        if self.form_source != "logoff":
            self.prepare_logoff()
            return LoginResult(
                False, "注销页状态已刷新，请重新输入验证码", KIND_CAPTCHA
            )
        names = self.cfg.get("logoffFields") or {}
        fields = dict(self.defaults)
        fields.update(self.hidden)
        fields[names.get("captcha", "ctl00$MainContent$TextBoxCC")] = captcha or ""
        fields[names.get("submit", "ctl00$MainContent$LogoffBtn")] = names.get(
            "submitValue", "注销"
        )
        payload = urllib.parse.urlencode(fields).encode("utf-8")
        html = self._request(self.logoff_url(), data=payload).decode("utf-8", "ignore")

        text = self._extract_error(html)
        if "验证码" in text:
            return LoginResult(False, text or "验证码错误", KIND_CAPTCHA)

        status = self._parse_status(html)
        portal_offline = status.text != "未知" and not status.online
        if any(w in text for w in LOGOFF_SUCCESS_WORDS) or portal_offline:
            result = self._confirm_offline("已断开网络", portal_status=status)
        elif text:
            return LoginResult(False, text, KIND_UNKNOWN)
        else:
            # 门户未给出任何明确反馈：交 _confirm_offline，它先读门户状态、
            # 外网探测只作补充（外网可达不等于门户会话仍在线，也不等于断开失败）
            result = self._confirm_offline(
                "已断开网络（联网探测确认）",
                fallback="断开失败：门户未确认状态变化",
                portal_status=status,
            )
        if result.ok:
            # 注销用的 ViewState 不能留给后续登录（两页不通用）
            self.invalidate_form()
        return result


class LoginSession:
    """把「开会话 → 取验证码 → 提交」串起来，供 GUI 与静默模式共用。

    注意：换验证码必须重新 prepare()，因为验证码与 Session 绑定。
    """

    def __init__(self, cfg: dict, logger=None):
        self.cfg = cfg
        self.client = PortalClient(cfg, logger)
        self.captcha_png = b""

    def is_online(self) -> bool:
        return self.client.is_online()

    def needs_login(self) -> bool:
        """是否需要登录：**以门户状态为准**，外网探测只在门户状态未知时兜底。

        实测依据（这是「软件点连接一直连不上」的根因）：
        门户显示「未联网」时，本机外网探测依旧全都可达（baidu / gstatic /
        msftconnecttest 实测 200/204），这些目标显然是未认证状态下的放行白名单。
        旧逻辑用外网可达判断，于是软件直接回「网络已连通，无需登录」——
        **根本没有提交登录**，门户侧始终未认证；用户看到的就是「连不上」，
        只能自己去网页门户登录。
        """
        try:
            status = self.query_status()
        except PortalError:
            return not self.is_online()
        if status.text != "未知":
            return not status.online
        return not self.is_online()

    def prepare(self) -> bytes:
        """开启新会话并获取验证码图片，返回 PNG 字节。"""
        self.client.open_session()
        self.captcha_png = self.client.fetch_captcha()
        return self.captcha_png

    def submit(self, captcha: str) -> LoginResult:
        user = self.cfg.get("user") or {}
        return self.client.submit(
            user.get("guid", ""), user.get("acc", ""), user.get("pwd", ""), captcha
        )

    def query_status(self) -> PortalStatus:
        """查询门户侧连接状态（IP + 是否在线）。"""
        return self.client.query_status()

    def prepare_logoff(self):
        """准备断开网络：返回 (验证码 PNG, 门户状态)，同时更新本地验证码缓存。"""
        captcha, status = self.client.prepare_logoff()
        self.captcha_png = captcha
        return captcha, status

    def submit_logoff(self, captcha: str) -> LoginResult:
        """提交注销（断开网络）。"""
        return self.client.submit_logoff(captcha)


def auto_login(cfg: dict, logger, ocr=None, on_captcha=None) -> LoginResult:
    """全自动登录（供 --silent 使用）：识别成功则提交，验证码错自动换图重试。

    on_captcha(png: bytes, guess: str) 可选，用于把最新验证码交给界面显示。
    返回 kind == KIND_NEED_MANUAL 时，调用方应展示界面让用户手输。
    """
    use_ocr = bool((cfg.get("options") or {}).get("useOcr", True)) and ocr is not None
    max_retry = int(cfg.get("maxCaptchaRetry", 3) or 3)
    session = LoginSession(cfg, logger)

    if not session.needs_login():
        logger.info("门户显示已联网，无需登录")
        return LoginResult(True, "网络已连通，无需登录", KIND_OK)

    last_png = b""
    for attempt in range(1, max_retry + 1):
        try:
            last_png = session.prepare()
        except PortalError as exc:
            logger.error(str(exc))
            return LoginResult(False, str(exc), KIND_NETWORK)

        guess = ""
        if use_ocr and ocr.available():
            guess = ocr.classify(last_png)
        if on_captcha:
            on_captcha(last_png, guess)

        if not guess:
            logger.warn("自动识别未得到结果，需手动输入验证码")
            return LoginResult(False, "需要手动输入验证码", KIND_NEED_MANUAL)

        try:
            result = session.submit(guess)
        except PortalError as exc:
            logger.error(str(exc))
            return LoginResult(False, str(exc), KIND_NETWORK)

        if result.ok:
            logger.info("登录成功（识别为 %s）" % guess)
            return result
        if result.kind != KIND_CAPTCHA:
            logger.error("登录被拒绝：%s" % result.message)
            return result
        logger.warn(
            "验证码识别错误（%s），换一张重试 %d/%d" % (guess, attempt, max_retry)
        )

    logger.error("连续 %d 次验证码识别失败" % max_retry)
    return LoginResult(
        False, "连续 %d 次识别失败，请手动输入验证码" % max_retry, KIND_NEED_MANUAL
    )
