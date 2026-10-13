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
        """探测外网可达性；校验响应内容，避免门户劫持重定向造成误判。"""
        probe = self.cfg.get("onlineProbe") or {}
        url = probe.get("url", "http://www.msftconnecttest.com/connecttest.txt")
        expect = probe.get("expect", "Microsoft Connect Test")
        timeout = int(probe.get("timeout", 4) or 4)
        try:
            # 同样绕开代理：探测的是「出口网络是否已放行」，走代理会误判
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=timeout) as resp:
                body = resp.read(128).decode("utf-8", "ignore")
            return expect in body
        except Exception:
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

    def fetch_captcha(self) -> bytes:
        """获取验证码图片（PNG）。"""
        data = self._request(self.cfg["captchaUrl"])
        if not data or data[:4] != b"\x89PNG":
            raise PortalError("验证码获取失败（未返回 PNG）")
        return data

    # ------------------------------------------------------------------ 提交
    def submit(self, guid: str, acc: str, pwd: str, captcha: str) -> LoginResult:
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
        # 门户未给出明确原因时，用联网探测二次确认（部分门户成功页仍是登录页样式）
        if result.kind == KIND_UNKNOWN and self.is_online():
            return LoginResult(True, "登录成功（联网探测确认）", KIND_OK)
        return result

    def _judge(self, html: str) -> LoginResult:
        """按响应内容判定成败并分类。"""
        names = self.cfg["fields"]
        still_login_page = (
            names["captcha"] in html or names["submit"] in html
        )
        if still_login_page:
            text = self._extract_error(html)
            if "验证码" in text:
                kind = KIND_CAPTCHA
            elif "密码" in text or "账号" in text or "锁定" in text:
                kind = KIND_CREDENTIAL
            else:
                kind = KIND_UNKNOWN
            return LoginResult(False, text or "登录失败（门户返回登录页）", kind)
        return LoginResult(True, "登录成功", KIND_OK)

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
        return captcha, status

    def _confirm_offline(self, ok_message: str, fallback: str = "") -> LoginResult:
        """用外网探测确认是否真的断开。

        门户确认注销很快，但**网络生效有延迟**（实测提交后 2 秒仍可上网），
        状态 span 的刷新同样滞后，因此最多探测 3 次、每次间隔 4 秒。
        """
        for _ in range(3):
            time.sleep(4)
            try:
                if not self.is_online():
                    return LoginResult(True, ok_message, KIND_OK)
            except Exception:
                pass
        if fallback:
            return LoginResult(False, fallback, KIND_UNKNOWN)
        # 门户已明确确认成功，只是生效较慢：按成功处理并说明
        return LoginResult(True, ok_message + "（生效略有延迟）", KIND_OK)

    def submit_logoff(self, captcha: str) -> LoginResult:
        """提交注销（断开网络）。

        判定顺序（依据实测的门户行为）：
        1. 门户把「注销成功!」「验证码错误!」都放在 validation-summary 块里，
           先看提取到的提示文字——含「成功」即成功，含「验证码」即验证码错误；
           （曾把「注销成功!」当失败信息返回，是断开功能误报的原因）
        2. 否则按响应页的状态 span 判定；
        3. 都不明确时用外网探测做最终判定（生效有延迟，见 _confirm_offline）。
        """
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
        if "成功" in text:
            # 门户已确认注销，网络生效可能有延迟，用外网探测复核
            return self._confirm_offline("已断开网络")

        status = self._parse_status(html)
        if status.text != "未知" and not status.online:
            return LoginResult(True, "已断开网络", KIND_OK)
        if text:
            return LoginResult(False, text, KIND_UNKNOWN)
        # 门户未给出任何明确反馈：外网探测做最终判定
        return self._confirm_offline(
            "已断开网络（联网探测确认）",
            fallback="断开失败：门户未确认状态变化",
        )


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

    if session.is_online():
        logger.info("网络已连通，无需登录")
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
