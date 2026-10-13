# -*- coding: utf-8 -*-
"""程序入口：原生 GUI（仿「联网设置」布局） + --silent 静默登录模式。

用法：
    CampusNetLogin.exe              打开界面（默认）
    CampusNetLogin.exe --silent     无窗口静默登录，结果用系统提示框反馈
    CampusNetLogin.exe --console    保留控制台输出（开发调试用）

界面元素对照用户需求（docs/PLAN.md 第 1 节）：
学号 / 上网密码 / 记住密码 / 开机自动登录 / 验证码 / 连接 / 隐藏 / 退出 / 日志区。
"""

import argparse
import base64
import ctypes
import json
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser

import autostart
from app_logger import Logger
from config_store import has_credential, load_config, save_config
from ocr_helper import OcrEngine
from portal_client import (
    KIND_CAPTCHA,
    KIND_NEED_MANUAL,
    LoginSession,
    PortalError,
    auto_login,
)

APP_TITLE = "联网设置"
DPI_AWARE = True
WM_CLOSE = 0x0010
# 验证码显示放大倍数：门户原图约 155x52，放大后手输时更易辨认
CAPTCHA_ZOOM = 2
# 免责声明：明确工具定位，避免被误解为破解/绕过工具
DISCLAIMER = (
    "免责声明：本工具仅为个人便利性网络连接工具，不修改、不破解、不绕过校园网认证与计费机制；"
    "账号与密码仅保存在本机（可选），请自行妥善保管。"
)


def toast(text: str, title: str = "校园网自动登录", auto_close: float = 1.8, error: bool = False) -> None:
    """系统原生提示框，可自动关闭（静默模式下无主窗口可用）。"""
    flag = 0x10 if error else 0x40
    threading.Thread(
        target=lambda: ctypes.windll.user32.MessageBoxW(0, text, title, flag),
        daemon=True,
    ).start()
    if auto_close:
        time.sleep(auto_close)
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def run_silent() -> int:
    """静默登录。返回 0 成功 / 1 失败 / 3 需要界面（未配置或需手输）。"""
    cfg = load_config()
    logger = Logger("SILENT")
    if not has_credential(cfg):
        logger.warn("未配置账号，转入界面模式")
        return 3
    result = auto_login(cfg, logger, OcrEngine())
    if result.ok:
        toast("已连接校园网\n%s" % result.message)
        return 0
    if result.kind == KIND_NEED_MANUAL:
        logger.warn("需要手动输入验证码，转入界面模式")
        return 3
    toast("登录失败：%s" % result.message, error=True)
    return 1


class LoginApp:
    """「联网设置」主窗口。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()
        self.logger = Logger("GUI")
        self.ocr = OcrEngine()
        self.session = None
        self.busy = False
        self.ui_queue = queue.Queue()
        self.photo = None
        self.captcha_purpose = "login"  # 当前显示的验证码用途：login / logoff
        self._net_online = False
        self._build_ui()
        self._pump_queue()
        self.root.after(150, self._on_start)

    # ------------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        self.root.title(APP_TITLE)
        self.root.resizable(False, False)
        font_label = ("Microsoft YaHei UI", 9)
        font_entry = ("Microsoft YaHei UI", 10)
        font_btn = ("Microsoft YaHei UI", 10, "bold")

        frame = tk.Frame(self.root, padx=14, pady=12)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)

        # 学号（门户 SSOGUITID）
        tk.Label(frame, text="学号", font=font_label).grid(row=0, column=0, sticky="e", pady=4)
        self.var_guid = tk.StringVar()
        tk.Entry(frame, textvariable=self.var_guid, font=font_entry, width=24).grid(
            row=0, column=1, columnspan=2, sticky="ew", pady=4
        )

        # 上网账号（门户 SSOACC，即手机号）——独立的认证账号，必填
        tk.Label(frame, text="上网账号", font=font_label).grid(row=1, column=0, sticky="e", pady=4)
        self.var_acc = tk.StringVar()
        tk.Entry(frame, textvariable=self.var_acc, font=font_entry, width=24).grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=4
        )

        # 上网密码
        tk.Label(frame, text="上网密码", font=font_label).grid(row=2, column=0, sticky="e", pady=4)
        self.var_pwd = tk.StringVar()
        tk.Entry(frame, textvariable=self.var_pwd, font=font_entry, show="*", width=24).grid(
            row=2, column=1, columnspan=2, sticky="ew", pady=4
        )

        # 验证码：图片独占一行并放大 2 倍显示（自动识别失败需手输时，避免看不清）
        tk.Label(frame, text="验证码", font=font_label).grid(row=3, column=0, sticky="ne", pady=4)
        self.lbl_captcha = tk.Label(
            frame, relief="groove", bg="#f7f9fc",
            text="正在获取…", font=("Microsoft YaHei UI", 10), fg="#8899aa",
            width=26, height=4,
        )
        self.lbl_captcha.grid(row=3, column=1, columnspan=2, sticky="w", pady=4)

        captcha_row = tk.Frame(frame)
        captcha_row.grid(row=4, column=1, columnspan=2, sticky="w", pady=(0, 4))
        self.var_captcha = tk.StringVar()
        tk.Entry(
            captcha_row, textvariable=self.var_captcha, font=("Consolas", 16),
            width=8, justify="center",
        ).pack(side="left")
        tk.Button(
            captcha_row, text="换一张", font=("Microsoft YaHei UI", 9),
            command=self._refresh_captcha,
        ).pack(side="left", padx=8)
        tk.Label(
            captcha_row, text="看不清可换一张", font=("Microsoft YaHei UI", 8), fg="#8a99aa",
        ).pack(side="left")

        # 选项
        opts = tk.Frame(frame)
        opts.grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 2))
        self.var_remember = tk.BooleanVar()
        self.var_autostart = tk.BooleanVar()
        tk.Checkbutton(opts, text="记住密码", variable=self.var_remember, font=font_label).pack(
            side="left"
        )
        tk.Checkbutton(
            opts, text="开机自动登录", variable=self.var_autostart, font=font_label
        ).pack(side="left", padx=14)

        # 主按钮
        self.btn_connect = tk.Button(
            frame, text="连 接", font=font_btn, bg="#3b82d9", fg="white",
            activebackground="#2f6fc0", activeforeground="white",
            relief="flat", height=1, command=self._on_connect,
        )
        self.btn_connect.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 4))

        # 次要按钮：隐藏 / 断开网络 / 退出
        minor = tk.Frame(frame)
        minor.grid(row=7, column=0, columnspan=3, sticky="ew")
        for idx in range(3):
            minor.columnconfigure(idx, weight=1)
        tk.Button(minor, text="隐藏", font=font_label, command=self._on_hide).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        tk.Button(minor, text="断开网络", font=font_label, command=self._on_logoff).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        tk.Button(minor, text="退出", font=font_label, command=self._on_quit).grid(
            row=0, column=2, sticky="ew", padx=(4, 0)
        )

        # 网络状态栏（左：门户连接状态；右：官方平台入口）
        net_bar = tk.Frame(frame)
        net_bar.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        net_bar.columnconfigure(0, weight=1)
        self.var_net = tk.StringVar(value="网络状态：查询中…")
        self.net_label = tk.Label(
            net_bar, textvariable=self.var_net, font=("Microsoft YaHei UI", 9),
            fg="#35506b", anchor="w",
        )
        self.net_label.grid(row=0, column=0, sticky="ew")
        tk.Button(
            net_bar, text="官方平台 10.6.6.6", font=("Microsoft YaHei UI", 8),
            fg="#3b82d9", relief="flat", cursor="hand2", command=self._open_portal,
        ).grid(row=0, column=1, sticky="e")

        # 操作状态
        self.var_status = tk.StringVar(value="就绪")
        tk.Label(frame, textvariable=self.var_status, font=("Microsoft YaHei UI", 9),
                 fg="#6b7c8d", anchor="w").grid(row=9, column=0, columnspan=3,
                                                sticky="ew", pady=(2, 2))

        # 日志
        log_box = tk.Frame(frame)
        log_box.grid(row=10, column=0, columnspan=3, sticky="nsew")
        self.txt_log = tk.Text(log_box, height=9, width=46, state="disabled",
                               font=("Consolas", 8), bg="#f7f9fc", relief="groove",
                               wrap="word")
        scroll = tk.Scrollbar(log_box, command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scroll.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # 免责声明
        tk.Label(
            frame, text=DISCLAIMER, font=("Microsoft YaHei UI", 7), fg="#8a99aa",
            wraplength=372, justify="left", anchor="w",
        ).grid(row=11, column=0, columnspan=3, sticky="ew", pady=(8, 0))

    # ------------------------------------------------------------ 启动与轮询
    def _on_start(self) -> None:
        user = self.cfg.get("user") or {}
        options = self.cfg.get("options") or {}
        self.var_guid.set(user.get("guid", ""))
        self.var_acc.set(user.get("acc", ""))
        if options.get("remember", True):
            self.var_pwd.set(user.get("pwd", ""))
        self.var_remember.set(bool(options.get("remember", True)))
        self.var_autostart.set(autostart.is_enabled())
        # OCR 引擎初始化（约 1~2 秒）放在后台预取线程里做，避免界面出现时卡顿
        self.logger.info("程序已启动")
        self._append_log("程序已启动")
        if not has_credential(self.cfg):
            self._set_status("请先填入学号、上网账号与密码")
            self._append_log("首次使用：请填写账号信息后点击「连接」")
        # 窗口出现后立即后台预取验证码，用户无需先点「连接」即可看到
        self.root.after(200, self._start_prefetch)

    def _pump_queue(self) -> None:
        try:
            while True:
                self._handle(self.ui_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self._pump_queue)

    def _post(self, kind: str, *args) -> None:
        self.ui_queue.put((kind,) + args)

    def _handle(self, msg: tuple) -> None:
        kind, args = msg[0], msg[1:]
        if kind == "log":
            self._append_log(args[0])
        elif kind in ("info", "warn", "error"):
            prefix = {"info": "", "warn": "[!] ", "error": "[x] "}[kind]
            self._append_log(prefix + args[0])
            self._set_status(args[0])
        elif kind == "captcha":
            self._show_captcha(args[0])
            self.var_captcha.set(args[1] if len(args) > 1 and args[1] else "")
        elif kind == "busy":
            self._set_busy(bool(args[0]), args[1] if len(args) > 1 else None)
        elif kind == "net":
            self._update_net(bool(args[0]), args[1] if len(args) > 1 else "")
        elif kind == "done":
            self._finish(bool(args[0]), args[1] if len(args) > 1 else "")

    # ------------------------------------------------------------ 界面动作
    def _append_log(self, text: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", time.strftime("%H:%M:%S ") + text + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.var_status.set(text)

    def _update_net(self, online: bool, ip: str) -> None:
        """更新网络状态栏（门户侧状态，非本地探测）。"""
        self._net_online = online
        text = "已联网" if online else "未联网"
        if ip:
            text += "    IP：" + ip
        self.var_net.set("网络状态：" + text)
        self.net_label.configure(fg="#0a7a3d" if online else "#c0392b")

    def _set_busy(self, busy: bool, text: str = None) -> None:
        self.busy = busy
        self.btn_connect.configure(
            text=(text or "连接中…") if busy else "连 接",
            state="disabled" if busy else "normal",
        )

    def _show_captcha(self, png: bytes) -> None:
        """显示验证码；放大 2 倍便于肉眼辨认（门户原图仅 155x52）。

        zoom() 走整数倍最近邻放大，不依赖 Pillow，因此 lite 版同样生效。
        """
        try:
            base = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
            self.photo = base.zoom(self.CAPTCHA_ZOOM) if self.CAPTCHA_ZOOM > 1 else base
            self.lbl_captcha.configure(image=self.photo, text="")
        except Exception:
            self.lbl_captcha.configure(image="", text="[验证码加载失败]")

    def _finish(self, ok: bool, message: str) -> None:
        self._set_busy(False)
        if ok:
            self._set_status(message or "登录成功")
            self._append_log("✔ %s" % (message or "登录成功"))
            self._refresh_status()
            self.root.after(1200, self._on_hide)
        elif message:
            self._set_status(message)
            self._append_log("✘ %s" % message)

    def _on_hide(self) -> None:
        self.root.iconify()

    def _on_quit(self) -> None:
        self.root.destroy()

    def _open_portal(self) -> None:
        """用系统默认浏览器打开官方网络接入平台主页（10.6.6.6）。"""
        url = (self.cfg.get("portalHome") or "http://10.6.6.6").strip()
        try:
            webbrowser.open(url)
            self._append_log("已在浏览器打开官方平台：%s" % url)
        except Exception as exc:
            self._append_log("打开官方平台失败：%s" % exc)

    # ------------------------------------------------------------ 表单与配置
    def _collect_form(self) -> bool:
        guid = self.var_guid.get().strip()
        acc = self.var_acc.get().strip()
        pwd = self.var_pwd.get()
        missing = []
        if not guid:
            missing.append("学号")
        if not acc:
            missing.append("上网账号")
        if not pwd:
            missing.append("上网密码")
        if missing:
            self._set_status("请填写：" + "、".join(missing))
            self._append_log("缺少必填项：" + "、".join(missing))
            return False
        self.cfg.setdefault("user", {})
        self.cfg["user"]["guid"] = guid
        self.cfg["user"]["acc"] = acc
        self.cfg["user"]["pwd"] = pwd
        options = self.cfg.setdefault("options", {})
        options["remember"] = bool(self.var_remember.get())

        want_autostart = bool(self.var_autostart.get())
        options["autostart"] = want_autostart
        if want_autostart != autostart.is_enabled():
            ok, msg = autostart.enable() if want_autostart else autostart.disable()
            self._append_log(("已启用开机自动登录" if want_autostart else "已取消开机自动登录")
                             + "：" + msg)
            if not ok:
                self.var_autostart.set(autostart.is_enabled())

        self._save_config_safely()
        return True

    def _save_config_safely(self) -> None:
        data = json.loads(json.dumps(self.cfg))
        if not (data.get("options") or {}).get("remember", True):
            data.setdefault("user", {})["pwd"] = ""
        try:
            save_config(data)
        except Exception as exc:
            self._append_log("配置保存失败：%s" % exc)

    # ------------------------------------------------------------ 登录流程
    def _ensure_session(self) -> None:
        if self.session is None:
            self.session = LoginSession(self.cfg, self.logger)

    def _use_ocr(self) -> bool:
        """是否启用自动识别：配置开关开启且 ddddocr 引擎可用。

        注意：首次调用会触发引擎初始化（约 1~2 秒），因此只应在后台线程中调用。
        """
        if not bool((self.cfg.get("options") or {}).get("useOcr", True)):
            return False
        return self.ocr.available()

    def _on_connect(self) -> None:
        if self.busy:
            return
        if not self._collect_form():
            return
        # 若输入框里是「注销用」验证码，登录需重新获取，避免误用失效验证码
        manual = "" if self.captcha_purpose == "logoff" else self.var_captcha.get().strip()
        self.captcha_purpose = "login"
        self._set_busy(True)
        threading.Thread(target=self._worker, args=(manual,), daemon=True).start()

    def _worker(self, manual: str) -> None:
        try:
            self._ensure_session()
            if self.session.is_online():
                self._post("done", True, "网络已连通，无需登录")
                return
            if manual and self.session.client.hidden:
                self._submit_manual(manual)
            else:
                self._auto_flow()
        except PortalError as exc:
            self.logger.error(str(exc))
            self._post("done", False, str(exc))
        except Exception as exc:  # 兜底：任何异常都不让界面卡在「连接中」
            self.logger.error("内部错误：%s" % exc)
            self._post("done", False, "内部错误：%s" % exc)

    def _auto_flow(self) -> None:
        use_ocr = self._use_ocr()
        max_retry = max(1, int(self.cfg.get("maxCaptchaRetry", 3) or 3))

        if not use_ocr:
            png = self.session.prepare()
            self._post("captcha", png, "")
            self._post("info", "请手动输入 4 位验证码后再次点击「连接」")
            self._post("done", False, "")
            return

        for attempt in range(1, max_retry + 1):
            png = self.session.prepare()
            guess = self.ocr.classify(png)
            self._post("captcha", png, guess)
            if not guess:
                self._post("info", "自动识别失败，请输入验证码后再次点击「连接」")
                self._post("done", False, "")
                return
            self._post("info", "识别为 %s，正在提交…" % guess)
            result = self.session.submit(guess)
            if result.ok:
                self._post("done", True, result.message)
                return
            if result.kind != KIND_CAPTCHA:
                self._post("done", False, result.message)
                return
            self._post("warn", "验证码识别错误，换一张重试（%d/%d）" % (attempt, max_retry))

        self._post("warn", "连续 %d 次识别失败，请输入验证码" % max_retry)
        self._post("done", False, "")

    def _submit_manual(self, captcha: str) -> None:
        result = self.session.submit(captcha)
        if result.ok:
            self._post("done", True, result.message)
            return
        if result.kind == KIND_CAPTCHA:
            png = self.session.prepare()
            self._post("captcha", png, "")
            self._post("warn", "验证码错误，已换一张，请重新输入")
            self._post("done", False, "")
            return
        self._post("done", False, result.message)

    def _refresh_captcha(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        try:
            self._ensure_session()
            png = self.session.prepare()
            guess = self.ocr.classify(png) if self._use_ocr() else ""
            self._post("captcha", png, guess)
        except PortalError as exc:
            self._post("error", str(exc))
        finally:
            self._post("busy", False)

    # ------------------------------------------------------- 状态与断开网络
    def _refresh_status(self) -> None:
        """后台查询门户连接状态（IP + 是否在线）并更新状态栏。"""
        def worker():
            try:
                self._ensure_session()
                status = self.session.query_status()
                self._post("net", status.online, status.ip)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_logoff(self) -> None:
        if self.busy:
            return
        captcha = self.var_captcha.get().strip()
        self._set_busy(True)
        threading.Thread(target=self._logoff_worker, args=(captcha,), daemon=True).start()

    def _logoff_worker(self, captcha: str) -> None:
        """断开网络：首次点击取注销页与验证码，再次点击（带验证码）提交注销。"""
        try:
            self._ensure_session()
            ready = self.captcha_purpose == "logoff" and bool(self.session.client.hidden)
            if captcha and ready:
                result = self.session.submit_logoff(captcha)
                if result.ok:
                    self.captcha_purpose = "login"
                    self._post("net", False, "")
                    self._post("done", True, result.message)
                    return
                if result.kind == KIND_CAPTCHA:
                    png, status = self.session.prepare_logoff()
                    self._post("net", status.online, status.ip)
                    self._post("captcha", png, "")
                    self._post("warn", "验证码错误，已换一张，请重新输入后再次点击「断开网络」")
                    self._post("done", False, "")
                    return
                self._post("done", False, result.message)
                return

            png, status = self.session.prepare_logoff()
            self.captcha_purpose = "logoff"
            self._post("net", status.online, status.ip)
            self._post("captcha", png, "")
            if not status.online:
                self._post("info", "当前未联网，无需断开")
                self._post("done", True, "当前未联网")
                return
            self._post("info", "已获取注销验证码，请输入后再次点击「断开网络」")
            self._post("done", False, "")
        except PortalError as exc:
            self._post("done", False, str(exc))
        except Exception as exc:
            self._post("done", False, "内部错误：%s" % exc)

    # ------------------------------------------------------------ 启动预取
    def _start_prefetch(self) -> None:
        """启动后立即预取验证码，界面一出现就能看到验证码（无需先点「连接」）。"""
        if self.busy:
            return
        self._set_status("正在获取验证码…")
        self._post("busy", True, "连 接")  # 预取期间禁用按钮，但保持按钮文案
        threading.Thread(target=self._prefetch_worker, daemon=True).start()

    def _prefetch_worker(self) -> None:
        try:
            self._ensure_session()
            online = self.session.is_online()
            # 无论是否已联网，都把验证码拉回来显示，避免窗口上空着一块
            png = self.session.prepare()
            use_ocr = self._use_ocr()
            guess = self.ocr.classify(png) if use_ocr else ""
            engine_state = "可用" if use_ocr else "不可用（仅手输）"
            self.logger.info("验证码已获取；OCR 引擎 %s" % engine_state)
            self._post("log", "验证码已获取；OCR 引擎 %s" % engine_state)
            self._post("captcha", png, guess)
            self.captcha_purpose = "login"
            # 顺带查询门户侧连接状态（IP + 是否在线）
            try:
                status = self.session.query_status()
                self.logger.info(
                    "门户状态：%s%s" % (status.text, ("，IP " + status.ip) if status.ip else "")
                )
                self._post("net", status.online, status.ip)
            except PortalError:
                self._post("net", False, "")
            if online:
                self._post("info", "网络已连通，无需登录（验证码仅供参考）")
            elif guess:
                self._post("info", "验证码已识别为 %s，可直接点「连接」" % guess)
            else:
                self._post("info", "请输入验证码后点「连接」")
        except PortalError as exc:
            self._post("warn", "验证码获取失败：%s（可点「换一张」重试）" % exc)
        except Exception as exc:
            self._post("warn", "验证码获取失败：%s" % exc)
        finally:
            self._post("busy", False)


def main() -> int:
    parser = argparse.ArgumentParser(description="校园网快速登录")
    parser.add_argument("--silent", action="store_true", help="静默登录（无窗口）")
    parser.add_argument("--console", action="store_true", help="保留控制台输出（开发用）")
    args = parser.parse_args()

    if DPI_AWARE:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    if args.silent:
        code = run_silent()
        if code != 3:
            return code
        # 需要界面：继续往下走，打开窗口让用户手输

    root = tk.Tk()
    LoginApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
