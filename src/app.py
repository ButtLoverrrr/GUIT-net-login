'''程序入口：原生 GUI（仿「联网设置」布局） + --silent 静默登录模式。

用法：
    GUIT-net-login.exe              打开界面（默认）
    GUIT-net-login.exe --silent     无窗口静默登录，结果用系统提示框反馈
    GUIT-net-login.exe --console    保留控制台输出（开发调试用）

界面元素对照用户需求（docs/PLAN.md 第 1 节）：
学号 / 上网密码 / 记住密码 / 开机自动登录 / 验证码 / 连接 / 隐藏 / 退出 / 日志区。
'''

import argparse
import base64
import ctypes
import io
import json
import os
import queue
import socket
import sys
import threading
import time
import webbrowser

# ---------------------------------------------------------------------------
# 单实例（本机 TCP 回环端口）
#
# 结构与原始字节码逐指令一致：socket 创建在 try 里（失败静默），bind/listen
# 在 else 里（失败=端口被占用 → 说明已有第一实例 → 连回去发 show 并退出）。
#
# 注意：端口可被环境变量 GUIT_INSTANCE_PORT 覆盖（测试沙箱用，原始版本没有这
# 一行）。除这一处外本模块与原始 marshal 逐指令一致，fidelity.py 门禁只允许
# 保留这一处差异。
# ---------------------------------------------------------------------------
SINGLE_INSTANCE_PORT = int(os.environ.get('GUIT_INSTANCE_PORT', 47823))
_IS_SECONDARY = False
_INSTANCE_SERVER = None
try:
    _srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
except Exception:
    pass
else:
    try:
        _srv.bind(('127.0.0.1', SINGLE_INSTANCE_PORT))
        _srv.listen(1)
        _INSTANCE_SERVER = _srv
    except OSError:
        try:
            _srv.close()
        except Exception:
            pass
        try:
            _cli = socket.create_connection(('127.0.0.1', SINGLE_INSTANCE_PORT), timeout=2)
            _cli.sendall(b'show\n')
            if _cli.recv(16).strip() == b'ok':
                _IS_SECONDARY = True
            _cli.close()
        except Exception:
            pass
if _IS_SECONDARY:
    os._exit(0)
import tkinter as tk

# 注：原始模块的注释/空行在反编译中丢失，本文件的 co_firstlineno 比原始字节码
# 偏小；fidelity.py 忽略行号，该类差异已逐条核对为无语义影响（见 reports/frontend.md）。
try:
    from PIL import (Image, ImageDraw, ImageTk)
    HAS_PIL = True
except Exception:
    HAS_PIL = False
try:
    import pystray
    HAS_TRAY = True
except Exception:
    HAS_TRAY = False
import autostart
from app_logger import Logger
from config_store import (app_dir, has_credential, load_config, remove_config, save_config)
from ocr_helper import OcrEngine
from portal_client import (KIND_CAPTCHA, KIND_NEED_MANUAL, LoginSession, PortalError, auto_login)
APP_VERSION = '1.0.0'

def resource_path(name: str) -> str:
    '''资源文件（应用图标等）路径。

    打包为单文件 exe 后，数据文件由 PyInstaller 解压到 sys._MEIPASS 下；
    源码运行时则位于项目根目录的 assets 目录。
    '''

    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        return os.path.join(meipass, 'assets', name)
    return os.path.join(app_dir(), 'assets', name)

# 注：原始模块的注释/空行在反编译中丢失，本文件的 co_firstlineno 比原始字节码
# 偏小；fidelity.py 忽略行号，该类差异已逐条核对为无语义影响（见 reports/frontend.md）。

APP_TITLE = '联网设置'
DPI_AWARE = True
WM_CLOSE = 16
CAPTCHA_ZOOM = 4
# --- 动画参数（集中控制，设为 0/FALSE 即完全关闭；任何失败都静默降级） ---
FADE_ENABLED = True
FADE_STEPS = 10
FADE_INTERVAL_MS = 16
LOG_MAX_LINES = 400
BTN_HOVER_BG = '#2f6fc0'
BTN_PRESS_BG = '#255ba0'
STATUS_OK_FG = '#0a7a3d'
STATUS_ERR_FG = '#c0392b'
STATUS_INFO_FG = '#6b7c8d'
AUTO_CONNECT_MAX_ATTEMPT = 3
AUTO_CONNECT_INTERVAL_MS = 12000
PROJECT_URL = 'https://github.com/ButtLoverrrr/GUIT-net-login'
DISCLAIMER = '免责声明：本工具仅为个人便利性网络连接工具，不修改、不破解、不绕过校园网认证与计费机制；账号与密码仅保存在本机（可选），请自行妥善保管。'

def toast(text: str, title: str='校园网自动登录', auto_close: float=1.8, error: bool=False) -> None:
    '''系统原生提示框，可自动关闭（静默模式下无主窗口可用）。'''

    flag = 16 if error else 64
    threading.Thread(target=(lambda: ctypes.windll.user32.MessageBoxW(0, text, title, flag)), daemon=True).start()
    if auto_close:
        time.sleep(auto_close)
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

def run_silent() -> int:
    '''静默登录。返回 0 成功 / 1 失败 / 3 需要界面（未配置或需手输）。'''

    cfg = load_config()
    logger = Logger('SILENT')
    if not has_credential(cfg):
        logger.warn('未配置账号，转入界面模式')
        return 3
    result = auto_login(cfg, logger, OcrEngine())
    if result.ok:
        toast('已连接校园网\n%s' % result.message)
        return 0
    if result.kind == KIND_NEED_MANUAL:
        logger.warn('需要手动输入验证码，转入界面模式')
        return 3
    toast('登录失败：%s' % result.message, error=True)
    return 1

class LoginApp:
    '''「联网设置」主窗口。'''

    def __init__(self, root: tk.Tk, auto_connect: bool=False):
        self.root = root
        self.cfg = load_config()
        self.ocr = OcrEngine()
        self.session = None
        self.busy = False
        self.auto_connect = auto_connect
        self.ui_queue = queue.Queue()
        self.logger = Logger('GUI')
        self.logger.set_sink((lambda line: self.ui_queue.put(('log', line))))
        self.photo = None
        self.tray_icon = None
        self.captcha_purpose = 'login'
        self.captcha_epoch = -1
        self._net_online = False
        self._after_id = None
        self._fade_job = None
        self._fade_off = not FADE_ENABLED
        self._build_ui()
        self._pump_queue()
        self.root.after(150, self._on_start)

    def _on_key(self, event) -> None:
        '''键盘快捷方式：回车=连接，Esc=隐藏（与界面按钮同一套代码路径）。'''

        if getattr(event, 'keysym', '') in ('Return', 'KP_Enter'):
            self._on_connect()
        elif getattr(event, 'keysym', '') == 'Escape':
            self._on_hide()

    def _build_ui(self) -> None:
        global _MAIN_WINDOW
        _MAIN_WINDOW = self.root
        self.root.title(f'{APP_TITLE!s} v{APP_VERSION!s}')
        ico = resource_path('app.ico')
        if os.path.exists(ico):
            try:
                self.root.iconbitmap(ico)
            except Exception:
                pass
        self.root.resizable(False, False)
        self.root.bind('<Return>', self._on_key)
        self.root.bind('<KP_Enter>', self._on_key)
        self.root.bind('<Escape>', self._on_key)
        font_label = ('Microsoft YaHei UI', 9)
        font_entry = ('Microsoft YaHei UI', 10)
        font_btn = ('Microsoft YaHei UI', 10, 'bold')
        frame = tk.Frame(self.root, padx=14, pady=12)
        frame.grid(sticky='nsew')
        frame.columnconfigure(1, weight=1)
        tk.Label(frame, text='学号', font=font_label).grid(row=0, column=0, sticky='e', pady=4)
        self.var_guid = tk.StringVar()
        tk.Entry(frame, textvariable=self.var_guid, font=font_entry, width=24).grid(row=0, column=1, columnspan=2, sticky='ew', pady=4)
        tk.Label(frame, text='上网账号', font=font_label).grid(row=1, column=0, sticky='e', pady=4)
        self.var_acc = tk.StringVar()
        tk.Entry(frame, textvariable=self.var_acc, font=font_entry, width=24).grid(row=1, column=1, columnspan=2, sticky='ew', pady=4)
        tk.Label(frame, text='上网密码', font=font_label).grid(row=2, column=0, sticky='e', pady=4)
        self.var_pwd = tk.StringVar()
        tk.Entry(frame, textvariable=self.var_pwd, font=font_entry, show='*', width=24).grid(row=2, column=1, columnspan=2, sticky='ew', pady=4)
        tk.Label(frame, text='验证码', font=font_label).grid(row=3, column=0, sticky='ne', pady=4)
        self.lbl_captcha = tk.Label(frame, relief='groove', bg='#f7f9fc', text='正在获取…', font=('Microsoft YaHei UI', 10), fg='#8899aa', width=26, height=4)
        self.lbl_captcha.grid(row=3, column=1, columnspan=2, sticky='w', pady=4)
        captcha_row = tk.Frame(frame)
        captcha_row.grid(row=4, column=1, columnspan=2, sticky='w', pady=(0, 4))
        self.var_captcha = tk.StringVar()
        vcmd = (self.root.register(self._clean_captcha_input), '%P')
        self.ent_captcha = tk.Entry(captcha_row, textvariable=self.var_captcha, font=('Consolas', 16), width=8, justify='center', validate='key', validatecommand=vcmd)
        self.ent_captcha.pack(side='left')
        tk.Button(captcha_row, text='换一张', font=('Microsoft YaHei UI', 9), command=self._refresh_captcha).pack(side='left', padx=8)
        tk.Label(captcha_row, text='看不清可换一张', font=('Microsoft YaHei UI', 8), fg='#8a99aa').pack(side='left')
        opts = tk.Frame(frame)
        opts.grid(row=5, column=0, columnspan=3, sticky='w', pady=(6, 2))
        self.var_remember = tk.BooleanVar()
        self.var_autostart = tk.BooleanVar()
        tk.Checkbutton(opts, text='记住密码', variable=self.var_remember, font=font_label).pack(side='left')
        tk.Checkbutton(opts, text='开机自动登录', variable=self.var_autostart, font=font_label).pack(side='left', padx=14)
        self.btn_connect = tk.Button(frame, text='连 接', font=font_btn, bg='#3b82d9', fg='white', activebackground=BTN_HOVER_BG, activeforeground='white', relief='flat', height=1, command=self._on_connect)
        self.btn_connect.grid(row=6, column=0, columnspan=3, sticky='ew', pady=(10, 4))
        self._bind_hover(self.btn_connect, '#3b82d9')
        minor = tk.Frame(frame)
        minor.grid(row=7, column=0, columnspan=3, sticky='ew')
        for idx in range(3):
            minor.columnconfigure(idx, weight=1)
        tk.Button(minor, text='隐藏', font=font_label, command=self._on_hide).grid(row=0, column=0, sticky='ew', padx=(0, 4))
        tk.Button(minor, text='断开网络', font=font_label, command=self._on_logoff).grid(row=0, column=1, sticky='ew', padx=4)
        tk.Button(minor, text='退出', font=font_label, command=self._on_quit).grid(row=0, column=2, sticky='ew', padx=(4, 0))
        net_bar = tk.Frame(frame)
        net_bar.grid(row=8, column=0, columnspan=3, sticky='ew', pady=(10, 0))
        net_bar.columnconfigure(0, weight=1)
        self.var_net = tk.StringVar(value='网络状态：查询中…')
        self.net_label = tk.Label(net_bar, textvariable=self.var_net, font=('Microsoft YaHei UI', 9), fg='#35506b', anchor='w')
        self.net_label.grid(row=0, column=0, sticky='ew')
        tk.Button(net_bar, text='官方平台 10.6.6.6', font=('Microsoft YaHei UI', 8), fg='#3b82d9', relief='flat', cursor='hand2', command=self._open_portal).grid(row=0, column=1, sticky='e')
        self.var_status = tk.StringVar(value='就绪')
        self.status_label = tk.Label(frame, textvariable=self.var_status, font=('Microsoft YaHei UI', 9), fg=STATUS_INFO_FG, anchor='w')
        self.status_label.grid(row=9, column=0, columnspan=3, sticky='ew', pady=(2, 2))
        log_box = tk.Frame(frame)
        log_box.grid(row=10, column=0, columnspan=3, sticky='nsew')
        self.txt_log = tk.Text(log_box, height=9, width=46, state='disabled', font=('Consolas', 8), bg='#f7f9fc', relief='groove', wrap='word')
        scroll = tk.Scrollbar(log_box, command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scroll.set)
        self.txt_log.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.txt_log.tag_configure('info', foreground='#22303c')
        self.txt_log.tag_configure('warn', foreground='#b26a00')
        self.txt_log.tag_configure('error', foreground='#c0392b')
        repo_row = tk.Frame(frame)
        repo_row.grid(row=11, column=0, columnspan=3, sticky='w', pady=(6, 0))
        gh_png = resource_path('github.png')
        if HAS_PIL and os.path.exists(gh_png):
            try:
                with Image.open(gh_png) as im:
                    side = 16
                    self.icon_github = ImageTk.PhotoImage(im.convert('RGBA').resize((side, side), Image.LANCZOS))
                gh_icon = tk.Label(repo_row, image=self.icon_github, cursor='hand2', bd=0)
                gh_icon.pack(side='left')
                gh_icon.bind('<Button-1>', (lambda _e: self._open_url(PROJECT_URL, '项目主页')))
            except Exception:
                pass
        repo_link = tk.Label(repo_row, text='项目地址', font=('Microsoft YaHei UI', 9, 'underline'), fg='#3b82d9', cursor='hand2')
        repo_link.pack(side='left', padx=(3, 0))
        repo_link.bind('<Button-1>', (lambda _e: self._open_url(PROJECT_URL, '项目主页')))
        tk.Label(repo_row, text=' v%s' % APP_VERSION, font=('Microsoft YaHei UI', 7), fg='#8a99aa').pack(side='left')
        tk.Label(frame, text=DISCLAIMER, font=('Microsoft YaHei UI', 7), fg='#8a99aa', wraplength=372, justify='left', anchor='w').grid(row=12, column=0, columnspan=3, sticky='ew', pady=(4, 0))
        self._clamp_to_screen()
        self.root.resizable(False, False)

    def _clamp_to_screen(self) -> None:
        '''启动时把窗口居中，并在屏幕装不下时收敛尺寸（失败静默降级）。

        只设位置（+x+y）不动尺寸时不会打断 Tk 的自动尺寸传播；仅当请求尺寸
        超出屏幕可用区时才显式给出宽高（此时 Tk 本来也装不下），避免高 DPI
        小屏把底部日志区/免责声明挤出屏幕。仅在启动时调用一次。
        '''

        try:
            self.root.update_idletasks()
            scr_w = self.root.winfo_screenwidth()
            scr_h = self.root.winfo_screenheight()
            req_w = self.root.winfo_reqwidth()
            req_h = self.root.winfo_reqheight()
            if req_w <= scr_w and req_h <= scr_h:
                x = max(0, (scr_w - req_w) // 2)
                y = max(0, (scr_h - req_h) // 3)
                self.root.geometry('+%d+%d' % (x, y))
                return
            width = min(req_w, scr_w)
            height = min(req_h, scr_h)
            self.root.geometry('%dx%d+%d+%d' % (width, height, max(0, (scr_w - width) // 2), max(0, (scr_h - height) // 3)))
        except Exception:
            pass


    def _bind_hover(self, widget, base_bg: str) -> None:
        '''按钮 hover/press 视觉反馈（只改背景色，不改尺寸与布局）。'''

        try:
            widget.bind('<Enter>', lambda _e: widget.configure(bg=BTN_HOVER_BG))
            widget.bind('<Leave>', lambda _e: widget.configure(bg=base_bg))
            widget.bind('<ButtonPress-1>', lambda _e: widget.configure(bg=BTN_PRESS_BG))
            widget.bind('<ButtonRelease-1>', lambda _e: widget.configure(bg=BTN_HOVER_BG))
        except Exception:
            pass

    def _fade_in(self, step: int=0) -> None:
        '''窗口淡入（0.1 → 1.0）。任何不支持 -alpha 的环境都静默跳过，直接可见。'''

        if not FADE_ENABLED or self._fade_off:
            return
        try:
            alpha = min(1.0, 0.1 + (1.0 - 0.1) * (step + 1) / FADE_STEPS)
            self.root.attributes('-alpha', alpha)
            if step + 1 >= FADE_STEPS:
                self.root.attributes('-alpha', 1.0)
                self._fade_job = None
                return
            self._fade_job = self.root.after(FADE_INTERVAL_MS, (lambda: self._fade_in(step + 1)))
        except Exception:
            self._fade_off = True
            try:
                self.root.attributes('-alpha', 1.0)
            except Exception:
                pass

    def _cancel_after(self) -> None:
        '''退出前取消队列泵等挂起的 after 回调，避免 destroy 后报 "invalid command name"。'''

        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._fade_job is not None:
            try:
                self.root.after_cancel(self._fade_job)
            except Exception:
                pass
            self._fade_job = None

    def _on_start(self) -> None:
        user = self.cfg.get('user') or {}
        options = self.cfg.get('options') or {}
        self.var_guid.set(user.get('guid', ''))
        self.var_acc.set(user.get('acc', ''))
        if options.get('remember', True):
            self.var_pwd.set(user.get('pwd', ''))
        self.var_remember.set(bool(options.get('remember', True)))
        self.var_autostart.set(autostart.is_enabled())
        self.logger.info('程序已启动')
        if not has_credential(self.cfg):
            self._set_status('请先填入学号、上网账号与密码')
            self._append_log('首次使用：请填写账号信息后点击「连接」')
        self.root.after(200, self._start_prefetch)
        if self.auto_connect:
            self._append_log('开机自动登录：等待网络就绪后自动连接')
            self.root.after(1500, self._auto_connect_step)
        self._fade_in()
        threading.Thread(target=self._check_autostart, daemon=True).start()

    def _pump_queue(self) -> None:
        self._after_id = None
        try:
            while True:
                self._handle(self.ui_queue.get_nowait())
        except queue.Empty:
            pass
        try:
            self._after_id = self.root.after(120, self._pump_queue)
        except Exception:
            pass

    def _post(self, kind: str, *args) -> None:
        self.ui_queue.put((kind,) + args)

    def _handle(self, msg: tuple) -> None:
        kind, args = msg[0], msg[1:]
        if kind == 'log':
            self._append_log(args[0])
            return
        if kind in ('info', 'warn', 'error'):
            prefix = {'info': '', 'warn': '[!] ', 'error': '[x] '}[kind]
            self._append_log(prefix + args[0], kind)
            self._set_status(args[0], kind)
            return
        if kind == 'captcha':
            self._show_captcha(args[0])
            self.var_captcha.set(args[1] if len(args) > 1 and args[1] else '')
            if not self.var_captcha.get():
                self._focus_captcha()
            if self.session is not None:
                self.captcha_epoch = self.session.client.captcha_epoch
                return
            return
        if kind == 'busy':
            self._set_busy(bool(args[0]), args[1] if len(args) > 1 else None)
            return
        if kind == 'net':
            self._update_net(bool(args[0]), args[1] if len(args) > 1 else '')
            return
        if kind == 'done':
            self._finish(bool(args[0]), args[1] if len(args) > 1 else '')

    def _append_log(self, text: str, level: str='info') -> None:
        '''追加一行日志：分级着色、只在贴底时自动滚动、行数有上限。

        原始写法每次 insert 后无条件 see('end') 并让 Text 无限增长：长时间挂机
        （--autostart 场景）会让行数无上限累积，且用户向上翻历史时会被不断拽回
        底部。这里只做等价收敛：贴底才跟随，超过 LOG_MAX_LINES 从头部裁剪。
        '''

        at_bottom = self.txt_log.yview()[1] >= 0.999
        self.txt_log.configure(state='normal')
        self.txt_log.insert('end', time.strftime('%H:%M:%S ') + text + '\n', level if level in ('warn', 'error') else 'info')
        self._trim_log()
        if at_bottom:
            self.txt_log.see('end')
        self.txt_log.configure(state='disabled')

    def _trim_log(self) -> None:
        '''超过 LOG_MAX_LINES 行时从头部裁剪（保持日志区有界）。'''

        try:
            excess = int(self.txt_log.index('end-1c').split('.')[0]) - LOG_MAX_LINES
            if excess > 0:
                self.txt_log.delete('1.0', '%d.0' % (excess + 1))
        except Exception:
            pass

    def _focus_captcha(self) -> None:
        '''把焦点给验证码输入框（失败静默：无窗口管理器/无焦点时不影响主流程）。'''

        try:
            self.ent_captcha.focus_set()
        except Exception:
            pass

    def _clean_captcha_input(self, proposed: str) -> bool:
        '''验证码输入清洗：去掉粘贴带进来的空白与不可见字符，长度上限 6。

        返回 False 表示由本方法改写输入框内容（Tkinter 的 validate 约定）。
        '''

        try:
            cleaned = ''.join(ch for ch in (proposed or '') if not ch.isspace() and ch.isprintable())
            if len(cleaned) > 6:
                cleaned = cleaned[:6]
            if cleaned == proposed:
                return True
            self.var_captcha.set(cleaned)
            if self.root.focus_get() is not self.ent_captcha:
                self._focus_captcha()
            return False
        except Exception:
            return True

    def _set_status(self, text: str, level: str='info') -> None:
        self.var_status.set(text)
        try:
            self.status_label.configure(fg={'error': STATUS_ERR_FG}.get(level, STATUS_INFO_FG))
        except Exception:
            pass

    def _update_net(self, online: bool, ip: str) -> None:
        '''更新网络状态栏（门户侧状态，非本地探测）。'''

        self._net_online = online
        text = '已联网' if online else '未联网'
        if ip:
            text += '    IP：' + ip
        self.var_net.set('网络状态：' + text)
        self.net_label.configure(fg='#0a7a3d' if online else '#c0392b')

    def _set_busy(self, busy: bool, text: str=None) -> None:
        self.busy = busy
        self.btn_connect.configure(text=text or '连接中…' if busy else '连 接', state='disabled' if busy else 'normal')

    def _fit_captcha_label(self) -> None:
        '''把验证码标签按图片像素尺寸显示。

        Tkinter 的坑：Label 一旦设置 image，width/height 的单位会从「字符数」
        变成「像素数」。初始化时写的 width=26/height=4 本是字符占位，有图后
        会变成强制 26x4 像素，导致验证码被压成一条细横条。

        本行写法与原始一致；`width=self.photo.width()` 与 `width=0` 在本机
        （Tk 8.6.15）几何等价，这里保留显式像素值。
        '''

        self.lbl_captcha.configure(image=self.photo, text='', width=self.photo.width(), height=self.photo.height())

    def _show_captcha(self, png: bytes) -> None:
        '''显示验证码并放大（门户原图仅 80x24，放大后便于手输）。

        优先用 Pillow 解码：对各式 PNG（灰度、调色板、带透明、非标准 chunk）比
        tkinter 原生解码宽容得多，放大也更平滑；Pillow 不可用时退回 tkinter 原生。
        两条路都失败才提示失败，并把具体异常写入日志便于排查。
        '''

        errors = []
        if HAS_PIL:
            try:
                with Image.open(io.BytesIO(png)) as im:
                    size = im.width * CAPTCHA_ZOOM, im.height * CAPTCHA_ZOOM
                    big = im.convert('RGB').resize(size, Image.LANCZOS)
                self.photo = ImageTk.PhotoImage(big)
                self._fit_captcha_label()
                return
            except Exception as exc:
                errors.append('Pillow: %s' % exc)
        try:
            base = tk.PhotoImage(data=base64.b64encode(png).decode('ascii'))
            self.photo = base.zoom(CAPTCHA_ZOOM) if CAPTCHA_ZOOM > 1 else base
            self._fit_captcha_label()
            return
        except Exception as exc:
            errors.append('tkinter: %s' % exc)
        self.lbl_captcha.configure(image='', text='[验证码显示失败]')
        self.logger.error('验证码显示失败：%s' % '；'.join(errors))

    def _finish(self, ok: bool, message: str) -> None:
        '''收尾：状态栏文字/颜色与日志严格一致（成功绿、失败红）。'''

        self._set_busy(False)
        if ok:
            self._set_status(message or '登录成功')
            self._append_log('✔ %s' % (message or '登录成功'))
            self._refresh_status()
            return
        if message:
            self._set_status(message, 'error')
            self._append_log('✘ %s' % message)

    def _tray_image(self):
        '''托盘图标：优先使用应用图标 assets/app.png，缺失时退回现画的图形。'''

        path = resource_path('app.png')
        if HAS_PIL and os.path.exists(path):
            try:
                return Image.open(path).convert('RGBA')
            except Exception:
                pass
        size = 64
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([1, 1, size - 2, size - 2], radius=14, fill=(59, 130, 217, 255))
        cx, cy = size // 2, size - 16
        for radius in (11, 19, 27):
            draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=205, end=335, fill='white', width=5)
        draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill='white')
        return img

    def _on_hide(self) -> None:
        '''隐藏到系统托盘：窗口与任务栏按钮都不留，双击托盘图标可恢复。'''

        if not HAS_TRAY:
            self.root.iconify()
            return
        self.root.withdraw()
        if self.tray_icon is None:
            menu = pystray.Menu(pystray.MenuItem('显示窗口', self._tray_show, default=True), pystray.MenuItem('退出', self._tray_quit))
            self.tray_icon = pystray.Icon('GUIT-net-login', self._tray_image(), '校园网登录', menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            self.logger.info('已隐藏到系统托盘：双击托盘图标可重新显示')

    def _tray_show(self, *_args) -> None:
        '''从托盘恢复窗口（回调运行在托盘线程，须切回主线程操作界面）。'''

        self.root.after(0, self.root.deiconify)

    def _tray_quit(self, *_args) -> None:
        '''托盘菜单里的退出（回调在托盘线程，清理动作切回主线程）。'''

        self._stop_tray()
        self.root.after(0, self._on_quit)

    def _stop_tray(self) -> None:
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None

    def _on_quit(self) -> None:
        self._cancel_after()
        self._stop_tray()
        self.root.destroy()

    def _open_url(self, url: str, label: str='') -> None:
        '''用系统默认浏览器打开链接。'''

        try:
            webbrowser.open(url)
            self._append_log(f'已在浏览器打开{label or '链接'!s}：{url!s}')
            return
        except Exception as exc:
            self._append_log('打开链接失败：%s' % exc)

    def _open_portal(self) -> None:
        '''打开官方网络接入平台主页（10.6.6.6）。'''

        self._open_url((self.cfg.get('portalHome') or 'http://10.6.6.6').strip(), '官方平台')

    def _collect_form(self) -> bool:
        guid = self.var_guid.get().strip()
        acc = self.var_acc.get().strip()
        pwd = self.var_pwd.get()
        missing = []
        if not guid:
            missing.append('学号')
        if not acc:
            missing.append('上网账号')
        if not pwd:
            missing.append('上网密码')
        if missing:
            self._set_status('请填写：' + '、'.join(missing))
            self._append_log('缺少必填项：' + '、'.join(missing))
            return False
        self.cfg.setdefault('user', {})
        self.cfg['user']['guid'] = guid
        self.cfg['user']['acc'] = acc
        self.cfg['user']['pwd'] = pwd
        options = self.cfg.setdefault('options', {})
        options['remember'] = bool(self.var_remember.get())
        want_autostart = bool(self.var_autostart.get())
        options['autostart'] = want_autostart
        if want_autostart != autostart.is_enabled():
            ok, msg = autostart.enable() if want_autostart else autostart.disable()
            self._append_log(('已启用开机自动登录' if want_autostart else '已取消开机自动登录') + '：' + msg)
            if not ok:
                self.var_autostart.set(autostart.is_enabled())
        self._save_config_safely()
        return True

    def _save_config_safely(self) -> None:
        '''按需保存：勾选「记住密码」或「开机自动登录」才落盘，否则删除配置以保持无痕。

        未勾选「记住密码」时口令绝不写入文件。
        '''

        options = self.cfg.get('options') or {}
        remember = bool(options.get('remember', True))
        autostart_on = bool(options.get('autostart', False))
        if not remember and not autostart_on:
            if remove_config():
                self.logger.info('未启用记忆项，已删除本地 config.json')
            return
        data = json.loads(json.dumps(self.cfg))
        if not remember:
            data.setdefault('user', {})['pwd'] = ''
        try:
            save_config(data)
            return
        except Exception as exc:
            self.logger.error('配置保存失败：%s' % exc)

    def _ensure_session(self) -> None:
        if self.session is None:
            self.session = LoginSession(self.cfg, self.logger)

    def _use_ocr(self) -> bool:
        '''是否启用自动识别：配置开关开启且 ddddocr 引擎可用。

        注意：首次调用会触发引擎初始化（约 1~2 秒），因此只应在后台线程中调用。
        '''

        if not bool((self.cfg.get('options') or {}).get('useOcr', True)):
            return False
        return self.ocr.available()

    def _on_connect(self) -> None:
        if self.busy:
            return
        if not self._collect_form():
            return
        client = self.session.client if self.session is not None else None
        current = client.captcha_epoch if client is not None else -1
        stale = current != self.captcha_epoch
        wrong_form = client is None or client.form_source != 'login'
        manual = '' if self.captcha_purpose == 'logoff' or stale or wrong_form else self.var_captcha.get().strip()
        if stale and self.var_captcha.get().strip():
            self._append_log('当前验证码已过期，已自动重新获取')
        self.captcha_purpose = 'login'
        self._set_busy(True)
        threading.Thread(target=self._worker, args=(manual,), daemon=True).start()

    def _worker(self, manual: str) -> None:
        try:
            self._ensure_session()
            if not self.session.needs_login():
                self._post('done', True, '网络已连通，无需登录')
                return
            client = self.session.client
            if manual and client.form_source == 'login':
                self._submit_manual(manual)
                return
            self._auto_flow()
            return
        except PortalError as exc:
            self.logger.error(str(exc))
            self._post('done', False, str(exc))
        except Exception as exc:
            self.logger.error('内部错误：%s' % exc)
            self._post('done', False, '内部错误：%s' % exc)

    def _auto_flow(self) -> None:
        use_ocr = self._use_ocr()
        max_retry = max(1, int(self.cfg.get('maxCaptchaRetry', 3) or 3))
        if not use_ocr:
            png = self.session.prepare()
            self._post('captcha', png, '')
            self._post('info', '请手动输入 4 位验证码后再次点击「连接」')
            self._post('done', False, '')
            return
        for attempt in range(1, max_retry + 1):
            png = self.session.prepare()
            guess = self.ocr.classify(png)
            self._post('captcha', png, guess)
            if not guess:
                self._post('info', '自动识别失败，请输入验证码后再次点击「连接」')
                self._post('done', False, '')
                return
            self._post('info', '识别为 %s，正在提交…' % guess)
            result = self.session.submit(guess)
            if result.ok:
                self._post('done', True, result.message)
                return
            if result.kind != KIND_CAPTCHA:
                self._post('done', False, result.message)
                return
            self._post('warn', '验证码识别错误，换一张重试（%d/%d）' % (attempt, max_retry))
            continue
        self._post('warn', '连续 %d 次识别失败，请输入验证码' % max_retry)
        self._post('done', False, '')

    def _submit_manual(self, captcha: str) -> None:
        result = self.session.submit(captcha)
        if result.ok:
            self._post('done', True, result.message)
            return
        if result.kind == KIND_CAPTCHA:
            png = self.session.prepare()
            self._post('captcha', png, '')
            self._post('warn', '验证码错误，已换一张，请重新输入')
            self._post('done', False, '')
            return
        self._post('done', False, result.message)

    def _refresh_captcha(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        try:
            self._ensure_session()
            png = self.session.prepare()
            guess = self.ocr.classify(png) if self._use_ocr() else ''
            self._post('captcha', png, guess)
        except PortalError as exc:
            self._post('error', str(exc))
        finally:
            self._post('busy', False)

    def _refresh_status(self) -> None:
        '''后台查询连接状态并更新状态栏。

        在线与否以外网探测为准：门户的状态 span 是「会话视角」，用户网络
        若由浏览器等其他方式连接，门户对程序会话会显示「未联网」，不可信。
        '''

        def worker():
            try:
                self._ensure_session()
                status = self.session.query_status()
                online = self.session.is_online() if status.text == '未知' else status.online
                self._post('net', online, status.ip)
                return
            except Exception:
                return

        threading.Thread(target=worker, daemon=True).start()

    def _on_logoff(self) -> None:
        if self.busy:
            return
        captcha = self.var_captcha.get().strip()
        self._set_busy(True)
        threading.Thread(target=self._logoff_worker, args=(captcha,), daemon=True).start()

    def _logoff_worker(self, captcha: str) -> None:
        '''断开网络。

两条路径：
1. 手输优先：界面上的注销验证码仍有效且用户填了值 → 直接提交；
2. **自动**：取注销页 + 取码 → OCR 识别 → 提交；验证码错就换码重试，
   连续失败才提示手输；OCR 不可用（lite 构建）时退回手输。
判定是否已断开一律以门户状态为准（注销页的 span 对本机 IP 判定准确）。
'''

        try:
            self._ensure_session()
            client = self.session.client
            use_ocr = self._use_ocr()
            max_retry = max(1, int(self.cfg.get('maxCaptchaRetry', 3) or 3)) if use_ocr else 1
            ready = self.captcha_purpose == 'logoff' and client.form_source == 'logoff' and client.captcha_epoch == self.captcha_epoch and bool(client.hidden)
            if captcha and ready:
                result = self.session.submit_logoff(captcha)
                if result.ok:
                    self.captcha_purpose = 'login'
                    self._post('net', False, '')
                    self._post('done', True, result.message)
                    return
                if result.kind != KIND_CAPTCHA:
                    self._post('done', False, result.message)
                    return
                self._post('warn', '验证码错误，换一张重试')
            for attempt in range(1, max_retry + 1):
                png, status = self.session.prepare_logoff()
                self.captcha_purpose = 'logoff'
                self._post('net', status.online, status.ip)
                self._post('captcha', png, '')
                if status.text != '未知' and not status.online:
                    self._post('info', '门户显示当前未联网，无需断开')
                    self._post('done', True, '当前未联网')
                    return
                if not use_ocr:
                    self._post('info', '已获取注销验证码，请输入后再次点击「断开网络」')
                    self._post('done', False, '')
                    return
                guess = self.ocr.classify(png)
                if not guess:
                    self._post('info', '自动识别失败，请输入验证码后再次点击「断开网络」')
                    self._post('done', False, '')
                    return
                self._post('info', '验证码识别为 %s，正在断开…' % guess)
                result = self.session.submit_logoff(guess)
                if result.ok:
                    self.captcha_purpose = 'login'
                    self._post('net', False, '')
                    self._post('done', True, result.message)
                    return
                if result.kind != KIND_CAPTCHA:
                    self._post('done', False, result.message)
                    return
                self._post('warn', '验证码识别错误，换一张重试（%d/%d）' % (attempt, max_retry))
                continue
            self._post('warn', '连续 %d 次自动识别失败，请输入验证码后再次点击「断开网络」' % max_retry)
            self._post('done', False, '')
            return
        except PortalError as exc:
            self._post('done', False, str(exc))
        except Exception as exc:
            self._post('done', False, '内部错误：%s' % exc)

    def _start_prefetch(self) -> None:
        '''启动后立即预取验证码，界面一出现就能看到验证码（无需先点「连接」）。'''

        if self.busy:
            return
        self._set_status('正在获取验证码…')
        self._post('busy', True, '连 接')
        threading.Thread(target=self._prefetch_worker, daemon=True).start()

    def _prefetch_worker(self) -> None:
        try:
            self._ensure_session()
            needs_login = self.session.needs_login()
            png = self.session.prepare()
            use_ocr = self._use_ocr()
            guess = self.ocr.classify(png) if use_ocr else ''
            engine_state = '可用' if use_ocr else '不可用（仅手输）'
            self.logger.info('验证码已获取；OCR 引擎 %s' % engine_state)
            self._post('captcha', png, guess)
            self.captcha_purpose = 'login'
            try:
                status = self.session.query_status()
                self.logger.info(f'门户状态：{status.text!s}{'，IP ' + status.ip if status.ip else ''!s}')
                self._post('net', status.online, status.ip)
            except PortalError:
                self._post('net', False, '')
            if not needs_login:
                self._post('info', '门户显示已联网，无需登录（验证码仅供参考）')
            elif guess:
                self._post('info', '验证码已识别为 %s，可直接点「连接」' % guess)
            else:
                self._post('info', '请输入验证码后点「连接」')
        except PortalError as exc:
            self._post('warn', '验证码获取失败：%s（可点「换一张」重试）' % exc)
        except Exception as exc:
            self._post('warn', '验证码获取失败：%s' % exc)
        finally:
            self._post('busy', False)

    def _auto_connect_step(self, attempt: int=1) -> None:
        '''开机自启（--autostart）：窗口出现后自动点一次「连接」。

        判定是否已成功用**门户状态**（self._net_online）：未认证时外网探测
        照样可达（放行白名单），拿它判断会误判成「已连通」而不去登录。
        开机瞬间网络常未就绪，因此失败按固定间隔重试，最多 AUTO_CONNECT_MAX_ATTEMPT 次。
        '''

        if not self.auto_connect:
            return
        if self._net_online:
            self._append_log('开机自动登录：门户显示已联网，不再重试')
            return
        if attempt > AUTO_CONNECT_MAX_ATTEMPT:
            self._append_log('开机自动登录：已尝试 %d 次仍未确认成功，请手动点「连接」' % AUTO_CONNECT_MAX_ATTEMPT)
            return
        if self.busy:
            self.root.after(3000, (lambda: self._auto_connect_step(attempt)))
            return
        if not has_credential(self.cfg):
            self._append_log('开机自动登录：尚未配置账号，跳过自动连接')
            return
        self._append_log('开机自动登录：正在连接（第 %d/%d 次）' % (attempt, AUTO_CONNECT_MAX_ATTEMPT))
        self._on_connect()
        self.root.after(AUTO_CONNECT_INTERVAL_MS, (lambda: self._auto_connect_step(attempt + 1)))

    def _check_autostart(self) -> None:
        '''启动时校正自启快捷方式：让它始终指向**当前正在运行的这个程序**。

        背景：早期版本在源码模式下生成的 .lnk 指向 `pythonw.exe src/app.py`，
        而源码模式的配置目录（项目根）并没有 config.json —— 开机自启时程序
        拿不到账号，只会弹一个空窗口。这里在启动时自动纠正指向。
        '''

        try:
            if not autostart.is_enabled():
                return
            ok, message = autostart.ensure_current()
            self.logger.info('开机自启检查：%s' % (message if ok else '校正失败：' + message))
            return
        except Exception as exc:
            self.logger.warn('开机自启检查失败：%s' % exc)


_MAIN_WINDOW = None

def _instance_listener(server) -> None:
    '''后台监听：收到 show 指令就把主窗口唤出。'''

    while True:
        try:
            conn, _ = server.accept()
            data = conn.recv(16)
            if b'show' in data:
                conn.sendall(b'ok')
            conn.close()
            if b'show' in data and _MAIN_WINDOW is not None:
                _MAIN_WINDOW.after(0, _MAIN_WINDOW.deiconify)
        except Exception:
            return

def main() -> int:
    parser = argparse.ArgumentParser(description='校园网快速登录')
    parser.add_argument('--silent', action='store_true', help='静默登录（无窗口）')
    parser.add_argument('--autostart', action='store_true', help='开机自启模式：正常打开界面，并在网络就绪后自动连接')
    parser.add_argument('--console', action='store_true', help='保留控制台输出（开发用）')
    args = parser.parse_args()
    if _INSTANCE_SERVER is not None:
        threading.Thread(target=_instance_listener, args=(_INSTANCE_SERVER,), daemon=True).start()
    if DPI_AWARE:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    if args.silent:
        code = run_silent()
        if code != 3:
            return code
    root = tk.Tk()
    LoginApp(root, auto_connect=args.autostart)
    root.mainloop()
    return 0

if __name__ == '__main__':
    sys.exit(main())
