# 代码结构与调用链静态分析（原始字节码级）

> 数据来源：exe 内 PyInstaller PYZ 的原始 marshal 代码对象（CPython 3.13），
> 由 `guit-re/analyze.py` 静态提取，不执行程序。

## 模块规模与导入

| 模块 | 代码对象数 | 指令总数 | 顶层 import |
|---|---|---|---|
| `app.py` | 52 | 12658 | `argparse`, `base64`, `ctypes`, `io`, `json`, `os`, `queue`, `socket`, `sys`, `threading`, `time`, `webbrowser`, `tkinter`, `PIL`, `pystray`, `autostart`, `app_logger`, `config_store`, `ocr_helper`, `portal_client` |
| `portal_client.py` | 36 | 5385 | `http.cookiejar`, `re`, `time`, `urllib.error`, `urllib.parse`, `urllib.request`, `dataclasses` |
| `config_store.py` | 9 | 935 | `json`, `os`, `sys` |
| `ocr_helper.py` | 6 | 325 | — |
| `app_logger.py` | 8 | 239 | — |
| `autostart.py` | 10 | 1795 | `os`, `subprocess`, `sys` |

## 函数清单（含指令数 / 起始行 / 内部调用）

### app.py

| 函数 | 起始行 | 指令数 | 关键调用 |
|---|---|---|---|
| `<module>` | 1 | 512 | _cli.close, _cli.recv, _cli.sendall, _srv.close, _srv.listen, bind.SINGLE_INSTANCE_PORT |
| `resource_path` | 96 | 99 | getattr.sys, join.app_dir, path.join |
| `toast` | 129 | 185 | PostMessageW.WM_CLOSE, start, time.sleep, user32.FindWindowW |
| `toast.<lambda>` | 133 | 46 | user32.MessageBoxW |
| `run_silent` | 143 | 180 | KIND_NEED_MANUAL.warn, Logger.has_credential, auto_login.OcrEngine, has_credential.warn, load_config, load_config.Logger |
| `LoginApp` | 161 | 286 | — |
| `LoginApp.__init__` | 164 | 239 | Queue.Logger, _build_ui, _build_ui._pump_queue, after._on_start, load_config, load_config.OcrEngine |
| `LoginApp.__init__.<lambda>` | 175 | 31 | ui_queue.put |
| `LoginApp._build_ui` | 188 | 2293 | APP_TITLE.APP_VERSION, APP_VERSION, APP_VERSION.resource_path, Button._on_hide, Button._on_logoff, Button._on_quit |
| `LoginApp._build_ui.<lambda>` | 332 | 24 | _open_url.PROJECT_URL |
| `LoginApp._build_ui.<lambda>` | 340 | 24 | _open_url.PROJECT_URL |
| `LoginApp._on_start` | 351 | 566 | Thread._check_autostart, _check_autostart.start, _set_status._append_log, after._auto_connect_step, after._start_prefetch, auto_connect._append_log |
| `LoginApp._pump_queue` | 373 | 111 | after._pump_queue, ui_queue.get_nowait |
| `LoginApp._post` | 381 | 33 | ui_queue.put |
| `LoginApp._handle` | 384 | 402 | _append_log, _finish.bool, _set_busy.bool, _set_status, _show_captcha, _update_net.bool |
| `LoginApp._append_log` | 406 | 133 | strftime, time.strftime, txt_log.configure, txt_log.see |
| `LoginApp._set_status` | 412 | 29 | var_status.set |
| `LoginApp._update_net` | 415 | 98 | configure, var_net.set |
| `LoginApp._set_busy` | 424 | 61 | — |
| `LoginApp._fit_captcha_label` | 431 | 88 | photo.height, photo.width |
| `LoginApp._show_captcha` | 445 | 481 | CAPTCHA_ZOOM._fit_captcha_label, CAPTCHA_ZOOM.convert, Image.LANCZOS, ImageTk.PhotoImage, PhotoImage._fit_captcha_label, append |
| `LoginApp._finish` | 473 | 143 | _append_log, _refresh_status, _set_busy, _set_status |
| `LoginApp._tray_image` | 485 | 272 | Image.new, Image.open, ImageDraw.Draw, open.convert, path.exists, resource_path |
| `LoginApp._on_hide` | 506 | 290 | Icon._tray_image, MenuItem._tray_quit, MenuItem._tray_show, logger.info, root.iconify, root.withdraw |
| `LoginApp._tray_show` | 523 | 50 | root.deiconify |
| `LoginApp._tray_quit` | 527 | 66 | _stop_tray, root.destroy |
| `LoginApp._stop_tray` | 532 | 66 | tray_icon.stop |
| `LoginApp._on_quit` | 540 | 44 | _stop_tray, root.destroy |
| `LoginApp._open_url` | 544 | 102 | _append_log, webbrowser.open |
| `LoginApp._open_portal` | 552 | 68 | cfg.get, strip |
| `LoginApp._collect_form` | 559 | 621 | _append_log.join, _set_status.join, append, autostart.disable, autostart.enable, autostart.is_enabled |
| `LoginApp._save_config_safely` | 593 | 294 | bool.get, cfg.get, dumps.cfg, logger.error, logger.info, remove_config |
| `LoginApp._ensure_session` | 614 | 53 | cfg.logger |
| `LoginApp._use_ocr` | 618 | 94 | cfg.get, get, ocr.available |
| `LoginApp._on_connect` | 627 | 348 | Thread._worker, _set_busy, _worker.start, busy._collect_form, get.strip, strip._append_log |
| `LoginApp._worker` | 649 | 306 | _ensure_session, _post, _post.str, _submit_manual._auto_flow, error.str, form_source._submit_manual |
| `LoginApp._auto_flow` | 670 | 514 | _post, _post.message, _use_ocr, cfg.get, classify._post, ocr.classify |
| `LoginApp._submit_manual` | 702 | 208 | _post, _post.message, prepare._post, session.prepare, session.submit |
| `LoginApp._refresh_captcha` | 715 | 82 | Thread._refresh_worker, _refresh_worker.start, busy._set_busy |
| `LoginApp._refresh_worker` | 721 | 204 | _ensure_session, _post, _post.str, ocr.classify, prepare._use_ocr, session.prepare |
| `LoginApp._refresh_status` | 733 | 44 | Thread.start, threading.Thread |
| `LoginApp._refresh_status.worker` | 739 | 144 | _ensure_session, _post.ip, session.is_online, session.query_status |
| `LoginApp._on_logoff` | 754 | 124 | Thread._logoff_worker, _logoff_worker.start, get.strip, strip._set_busy, var_captcha.get |
| `LoginApp._logoff_worker` | 761 | 1035 | _ensure_session, _post, _post.message, _post.str, bool.hidden, cfg.get |
| `LoginApp._start_prefetch` | 838 | 101 | Thread._prefetch_worker, _post, _prefetch_worker.start, busy._set_status |
| `LoginApp._prefetch_worker` | 846 | 564 | _ensure_session, _post, ip, logger.info, ocr.classify, online.ip |
| `LoginApp._auto_connect_step` | 882 | 266 | AUTO_CONNECT_MAX_ATTEMPT._on_connect, _append_log.AUTO_CONNECT_MAX_ATTEMPT, _net_online._append_log, after, after.AUTO_CONNECT_INTERVAL_MS, cfg._append_log |
| `LoginApp._auto_connect_step.<lambda>` | 899 | 19 | _auto_connect_step |
| `LoginApp._auto_connect_step.<lambda>` | 908 | 22 | _auto_connect_step |
| `LoginApp._check_autostart` | 911 | 148 | autostart.ensure_current, autostart.is_enabled, logger.warn |
| `_instance_listener` | 930 | 144 | _MAIN_WINDOW.deiconify, accept, accept.recv, sendall, sendall.close |
| `main` | 945 | 301 | LoginApp.autostart, _INSTANCE_SERVER.start, _instance_listener._INSTANCE_SERVER, add_argument, argparse.ArgumentParser, autostart.mainloop |

### portal_client.py

| 函数 | 起始行 | 指令数 | 关键调用 |
|---|---|---|---|
| `<module>` | 1 | 139 | Exception, dataclass |
| `PortalError` | 60 | 12 | — |
| `LoginResult` | 64 | 28 | — |
| `PortalStatus` | 71 | 34 | — |
| `_extract_span` | 80 | 131 | group.strip, re.S, re.escape, sub.group |
| `PortalClient` | 90 | 169 | str.str |
| `PortalClient.__init__` | 93 | 223 | HTTPCookieProcessor.jar, cookiejar.CookieJar, request.ProxyHandler |
| `PortalClient.__init__.<lambda>` | 96 | 2 | — |
| `PortalClient._request` | 115 | 230 | Exception.PortalError, PortalError.code, PortalError.reason, open.timeout, read, timeout.read |
| `PortalClient.is_online` | 127 | 373 | append.get, cfg.get, extend.ONLINE_PROBES, get, getattr, int.get |
| `PortalClient._parse_form_defaults` | 158 | 200 | group, group.group, re.I |
| `PortalClient.open_session` | 175 | 209 | PortalError._parse_form_defaults, _request.cfg, cfg.decode, group, hidden.PortalError, re.escape |
| `PortalClient.fetch_captcha` | 190 | 81 | PortalError, _request.cfg |
| `PortalClient.submit` | 203 | 453 | KIND_UNKNOWN.refresh_portal_status, LoginResult.KIND_OK, _request.cfg, cfg.get, decode, decode._judge |
| `PortalClient._judge` | 241 | 216 | KIND_UNKNOWN, LOGIN_SUCCESS_WORDS, LoginResult.KIND_OK, _extract_error, any.LOGIN_SUCCESS_WORDS |
| `PortalClient._judge.<genexpr>` | 252 | 22 | — |
| `PortalClient._extract_error` | 273 | 239 | join, re.S, re.findall, re.sub, strip, strip.strip |
| `PortalClient.logoff_url` | 299 | 37 | cfg.get |
| `PortalClient._parse_status` | 302 | 126 | _extract_span.get, cfg.get |
| `PortalClient.query_status` | 311 | 65 | _request.logoff_url, decode._parse_status, logoff_url.decode |
| `PortalClient.prepare_logoff` | 316 | 307 | PortalError, PortalError._parse_form_defaults, _parse_form_defaults._parse_status, _request.cfg, _request.logoff_url, group |
| `PortalClient.invalidate_form` | 342 | 23 | — |
| `PortalClient.refresh_portal_status` | 353 | 92 | PortalError.PortalStatus, _request.logoff_url, decode._parse_status, logoff_url.decode |
| `PortalClient._confirm_offline` | 365 | 268 | KIND_OK.range, LoginResult.KIND_OK, LoginResult.KIND_UNKNOWN, refresh_portal_status, sleep.is_online, time.sleep |
| `PortalClient.submit_logoff` | 399 | 527 | KIND_CAPTCHA, KIND_CAPTCHA._parse_status, LOGOFF_SUCCESS_WORDS, LoginResult.KIND_CAPTCHA, LoginResult.KIND_UNKNOWN, _confirm_offline |
| `PortalClient.submit_logoff.<genexpr>` | 432 | 22 | — |
| `LoginSession` | 450 | 70 | — |
| `LoginSession.__init__` | 456 | 31 | PortalClient |
| `LoginSession.is_online` | 461 | 27 | client.is_online |
| `LoginSession.needs_login` | 464 | 109 | PortalError.is_online, online.is_online, query_status |
| `LoginSession.prepare` | 482 | 70 | client.fetch_captcha, client.open_session |
| `LoginSession.submit` | 488 | 115 | cfg.get, get, get.get, submit.get |
| `LoginSession.query_status` | 494 | 27 | client.query_status |
| `LoginSession.prepare_logoff` | 498 | 38 | client.prepare_logoff |
| `LoginSession.submit_logoff` | 504 | 28 | client.submit_logoff |
| `auto_login` | 509 | 642 | LoginResult.KIND_NEED_MANUAL, LoginResult.KIND_OK, LoginResult.str, LoginSession, LoginSession.needs_login, available |

### config_store.py

| 函数 | 起始行 | 指令数 | 关键调用 |
|---|---|---|---|
| `<module>` | 1 | 116 | — |
| `app_dir` | 57 | 190 | abspath.__file__, getattr.sys, sys.executable |
| `config_path` | 64 | 45 | app_dir.CONFIG_FILE_NAME, join.app_dir |
| `_merge` | 69 | 145 | dict, dict.dict, dict.update, get.dict, isinstance.dict, isinstance.get |
| `load_config` | 82 | 148 | _merge.DEFAULT_CONFIG, dict.DEFAULT_CONFIG, dict.ValueError, isinstance.dict, json.load, load |
| `save_config` | 94 | 86 | json.dump, open.config_path, write |
| `remove_config` | 101 | 89 | config_path, os.remove, path.exists |
| `has_credential` | 113 | 49 | all, get |
| `has_credential.<genexpr>` | 119 | 67 | bool.get, strip |

### ocr_helper.py

| 函数 | 起始行 | 指令数 | 关键调用 |
|---|---|---|---|
| `<module>` | 1 | 14 | — |
| `OcrEngine` | 12 | 39 | — |
| `OcrEngine.__init__` | 17 | 22 | — |
| `OcrEngine.available` | 22 | 87 | DdddOcr |
| `OcrEngine.classify` | 34 | 122 | _engine.classification, available, join.str |
| `OcrEngine.classify.<genexpr>` | 42 | 41 | isalnum |

### app_logger.py

| 函数 | 起始行 | 指令数 | 关键调用 |
|---|---|---|---|
| `<module>` | 1 | 14 | — |
| `Logger` | 9 | 66 | — |
| `Logger.__init__` | 12 | 14 | — |
| `Logger.set_sink` | 16 | 8 | — |
| `Logger.log` | 19 | 77 | _sink, get |
| `Logger.info` | 29 | 20 | log |
| `Logger.warn` | 32 | 20 | log |
| `Logger.error` | 35 | 20 | log |

### autostart.py

| 函数 | 起始行 | 指令数 | 关键调用 |
|---|---|---|---|
| `<module>` | 1 | 87 | — |
| `startup_dir` | 23 | 67 | environ.get |
| `lnk_path` | 35 | 45 | join.startup_dir, startup_dir.LNK_NAME |
| `cmd_path` | 39 | 45 | join.startup_dir, startup_dir.CMD_NAME |
| `is_enabled` | 43 | 86 | exists.cmd_path, exists.lnk_path |
| `_launch_command` | 47 | 375 | abspath.__file__, getattr.sys, path.dirname, path.exists, sys.executable |
| `enable` | 61 | 354 | CREATE_NO_WINDOW, _launch_command.lnk_path, cmd_path, exists.lnk_path, lnk_path.lnk_path, makedirs.startup_dir |
| `read_lnk` | 101 | 213 | CREATE_NO_WINDOW, decode, decode.strip, lnk_path, path.exists, split |
| `ensure_current` | 129 | 288 | _launch_command.read_lnk, abspath, enable, enable._launch_command, exists.cmd_path, exists.lnk_path |
| `disable` | 149 | 235 | join, lnk_path, lnk_path.cmd_path, os.remove, path.basename, path.exists |

## 跨模块调用边（静态）

- `app` → `portal_client`：LoginSession, PortalError, auto_login
- `app` → `config_store`：app_dir, has_credential, load_config, remove_config, save_config
- `app` → `ocr_helper`：OcrEngine
- `app` → `app_logger`：Logger
- `app` → `autostart`：disable, enable, ensure_current, is_enabled






## 关键流程的事实依据（从字节码提取的字符串/常量）

### app

- `<module>`: 程序入口：原生 GUI（仿「联网设置」布局） + --silent 静默登录模式。 /  / 用法： /     GUI ｜ 127.0.0.1 ｜ 1.0.0 ｜ name ｜ return ｜ 资源文件（应用图标等）路径。 /  / 打包为单文件 exe 后，数据文件由 PyInstaller 解压到 sys._
- `resource_path`: 资源文件（应用图标等）路径。 /  / 打包为单文件 exe 后，数据文件由 PyInstaller 解压到 sys._ ｜ _MEIPASS ｜ assets
- `toast`: 系统原生提示框，可自动关闭（静默模式下无主窗口可用）。
- `run_silent`: 静默登录。返回 0 成功 / 1 失败 / 3 需要界面（未配置或需手输）。 ｜ SILENT ｜ 未配置账号，转入界面模式 ｜ 已连接校园网 / %s ｜ 需要手动输入验证码，转入界面模式 ｜ 登录失败：%s
- `LoginApp`: LoginApp ｜ 「联网设置」主窗口。 ｜ root ｜ auto_connect ｜ return ｜ 网络状态：查询中…
- `LoginApp.__init__`: GUI ｜ login
- `LoginApp.__init__.<lambda>`: log
- `LoginApp._build_ui`:  v ｜ app.ico ｜ nsew ｜ 学号 ｜ e ｜ ew
- `LoginApp._build_ui.<lambda>`: 项目主页
- `LoginApp._build_ui.<lambda>`: 项目主页
- `LoginApp._on_start`: user ｜ options ｜ guid ｜ acc ｜ remember ｜ pwd
- `LoginApp._handle`: log ｜ [!]  ｜ [x]  ｜ captcha ｜ busy ｜ net
- `LoginApp._append_log`: normal ｜ end ｜ %H:%M:%S  ｜ disabled
- `LoginApp._update_net`: 更新网络状态栏（门户侧状态，非本地探测）。 ｜ 已联网 ｜ 未联网 ｜     IP： ｜ 网络状态： ｜ #0a7a3d
- `LoginApp._set_busy`: 连接中… ｜ 连 接 ｜ disabled ｜ normal
- `LoginApp._fit_captcha_label`: 把验证码标签按图片实际像素尺寸显示。 /  / Tkinter 的坑：Label 一旦设置 image，width/he
- `LoginApp._show_captcha`: 显示验证码并放大（门户原图仅 80x24，放大后便于手输）。 /  / 优先用 Pillow 解码：对各式 PNG（灰度 ｜ RGB ｜ Pillow: %s ｜ ascii ｜ tkinter: %s ｜ [验证码显示失败]
- `LoginApp._finish`: 登录成功 ｜ ✔ %s ｜ ✘ %s
- `LoginApp._tray_image`: 托盘图标：优先使用应用图标 assets/app.png，缺失时退回现画的图形。 ｜ app.png ｜ RGBA ｜ white
- `LoginApp._on_hide`: 隐藏到系统托盘：窗口与任务栏按钮都不留，双击托盘图标可恢复。 ｜ 显示窗口 ｜ 退出 ｜ GUIT-net-login ｜ 校园网登录 ｜ 已隐藏到系统托盘：双击托盘图标可重新显示
- `LoginApp._tray_show`: 从托盘恢复窗口（回调运行在托盘线程，须切回主线程操作界面）。
- `LoginApp._tray_quit`: 托盘菜单里的退出。
- `LoginApp._open_url`: 用系统默认浏览器打开链接。 ｜ 已在浏览器打开 ｜ 链接 ｜ ： ｜ 打开链接失败：%s
- `LoginApp._open_portal`: 打开官方网络接入平台主页（10.6.6.6）。 ｜ portalHome ｜ http://10.6.6.6 ｜ 官方平台
- `LoginApp._collect_form`: 学号 ｜ 上网账号 ｜ 上网密码 ｜ 请填写： ｜ 、 ｜ 缺少必填项：
- `LoginApp._save_config_safely`: 按需保存：勾选「记住密码」或「开机自动登录」才落盘，否则删除配置以保持无痕。 /  / 未勾选「记住密码」时口令绝不写入 ｜ options ｜ remember ｜ autostart ｜ 未启用记忆项，已删除本地 config.json ｜ user
- `LoginApp._use_ocr`: 是否启用自动识别：配置开关开启且 ddddocr 引擎可用。 /  / 注意：首次调用会触发引擎初始化（约 1~2 秒） ｜ options ｜ useOcr
- `LoginApp._on_connect`: login ｜ logoff ｜ 当前验证码已过期，已自动重新获取
- `LoginApp._worker`: done ｜ 网络已连通，无需登录 ｜ login ｜ 内部错误：%s
- `LoginApp._auto_flow`: maxCaptchaRetry ｜ captcha ｜ info ｜ 请手动输入 4 位验证码后再次点击「连接」 ｜ done ｜ 自动识别失败，请输入验证码后再次点击「连接」
- `LoginApp._submit_manual`: done ｜ captcha ｜ warn ｜ 验证码错误，已换一张，请重新输入
- `LoginApp._refresh_worker`: captcha ｜ error ｜ busy
- `LoginApp._refresh_status`: 后台查询连接状态并更新状态栏。 /  / 在线与否以外网探测为准：门户的状态 span 是「会话视角」，用户网络 / 若
- `LoginApp._refresh_status.worker`: 未知 ｜ net
- `LoginApp._logoff_worker`: 断开网络。 /  / 两条路径： / 1. 手输优先：界面上的注销验证码仍有效且用户填了值 → 直接提交； / 2. * ｜ maxCaptchaRetry ｜ logoff ｜ login ｜ net ｜ done
- `LoginApp._start_prefetch`: 启动后立即预取验证码，界面一出现就能看到验证码（无需先点「连接」）。 ｜ 正在获取验证码… ｜ busy ｜ 连 接
- `LoginApp._prefetch_worker`: 可用 ｜ 不可用（仅手输） ｜ 验证码已获取；OCR 引擎 %s ｜ captcha ｜ login ｜ 门户状态：
- `LoginApp._auto_connect_step`: 开机自启（--autostart）：窗口出现后自动点一次「连接」。 /  / 判定是否已成功用**门户状态**（self ｜ 开机自动登录：门户显示已联网，不再重试 ｜ 开机自动登录：已尝试 %d 次仍未确认成功，请手动点「连接」 ｜ 开机自动登录：尚未配置账号，跳过自动连接 ｜ 开机自动登录：正在连接（第 %d/%d 次）
- `LoginApp._check_autostart`: 启动时校正自启快捷方式：让它始终指向**当前正在运行的这个程序**。 /  / 背景：早期版本在源码模式下生成的 .ln ｜ 开机自启检查：%s ｜ 校正失败： ｜ 开机自启检查失败：%s
- `_instance_listener`: 后台监听：收到 show 指令就把主窗口唤出。
- `main`: 校园网快速登录 ｜ --silent ｜ store_true ｜ 静默登录（无窗口） ｜ --autostart ｜ 开机自启模式：正常打开界面，并在网络就绪后自动连接

### portal_client

- `<module>`: 校园网门户登录核心（纯标准库，便于打包）。 /  / 适用门户：ASP.NET WebForms 网页认证（目标 htt ｜ Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ｜ ok ｜ captcha ｜ credential ｜ network
- `PortalError`: PortalError ｜ 门户交互异常（网络不通、页面结构变化等）。
- `LoginResult`: LoginResult ｜ ok ｜ message ｜ kind
- `PortalStatus`: PortalStatus ｜ 门户侧的连接状态：当前用户 IP 与是否在线。 ｜ ip ｜ online ｜ text
- `_extract_span`: 提取 <span id="...">内容</span> 的纯文本（剥离内层 <font> 等标签）。 ｜ id="%s"[^>]*>(.*?)</span> ｜ <[^>]+>
- `PortalClient`: PortalClient ｜ 单次会话内的门户交互：探测 / 取页面 / 取验证码 / 提交。 ｜ cfg ｜ timeout ｜ User-Agent ｜ url
- `PortalClient.__init__`: User-Agent
- `PortalClient._request`: 服务器返回 HTTP %s ｜ 无法连接门户：%s ｜ 请求失败：%s
- `PortalClient.is_online`: 探测外网可达性；多源降级，任一命中即视为已联网。 /  / 必须绕开系统代理，并校验响应内容，避免门户劫持重定向造成误判 ｜ onlineProbe ｜ timeout ｜ url ｜ expect ｜ utf-8
- `PortalClient._parse_form_defaults`: 解析页面上所有输入控件的默认值。 /  / 提交时原样带回，与浏览器行为保持一致——门户可能依赖这些字段， / 例如登录 ｜ <input\b[^>]*> ｜ \bname="([^"]*)" ｜ \bvalue="([^"]*)"
- `PortalClient.open_session`: GET 登录页，缓存隐藏字段与各控件默认值（新会话必须调用一次）。 ｜ portalUrl ｜ utf-8 ｜ ignore ｜ name="%s"[^>]*value="([^"]*)" ｜ __VIEWSTATE
- `PortalClient.fetch_captcha`: 获取验证码图片（PNG）。 /  / 取码会使同会话上一张码失效（实测），因此这里推进 captcha_epoch， / ｜ captchaUrl ｜ 验证码获取失败（未返回 PNG）
- `PortalClient.submit`: login ｜ fields ｜ guid ｜ acc ｜ pwd ｜ captcha
- `PortalClient._judge`: 按响应内容判定成败并分类（纯函数，不发请求）。 /  / 判定顺序（依据实测的门户行为）： / 1. 先认门户的**登录 ｜ 验证码 ｜ fields ｜ captcha ｜ submit ｜ 密码
- `PortalClient._extract_error`: 提取门户返回的校验错误文本。 /  / ASP.NET 的错误提示有两种常见形态：`<li>错误</li>` 列表， / ｜ <li>([^<]{2,80})</li> ｜ validation-summary-errors[^>]*>(.*?)</(?:div|ul|p|span) ｜ <[^>]+> ｜   ｜ \s+
- `PortalClient.logoff_url`: logoffUrl ｜ http://10.6.6.6/logoff
- `PortalClient._parse_status`: statusFields ｜ ip ｜ MainContent_LocalIP ｜ online ｜ MainContent_LabelOnline ｜ 已联网
- `PortalClient.query_status`: 查询门户侧的当前用户 IP 与在线状态（读取注销页，不做任何提交）。 ｜ utf-8 ｜ ignore
- `PortalClient.prepare_logoff`: 准备断开网络：取注销页隐藏字段与验证码，返回 (PNG 字节, 门户状态)。 /  / 注意：注销必须回填注销页自身的  ｜ utf-8 ｜ ignore ｜ name="%s"[^>]*value="([^"]*)" ｜ __VIEWSTATE ｜ 注销页解析失败：未找到 __VIEWSTATE（门户可能已改版）
- `PortalClient.invalidate_form`: 作废当前缓存的表单状态：下一次提交前必须重新取页面。 /  / 注销页与登录页的 __VIEWSTATE / __EVE
- `PortalClient.refresh_portal_status`: 重新 GET 注销页读取门户状态（只读，不覆盖表单状态）。 /  / 必须重新取：POST /logoff 的响应页里渲 ｜ utf-8 ｜ ignore
- `PortalClient._confirm_offline`: 确认断开：**以门户状态为主判据**，外网探测只作补充。 /  / 为什么不以外网可达为准（实测依据）：本机提交注销后门 ｜ 未知 ｜ （门户已确认下线） ｜ （门户已受理；本机外网仍可达，说明这条连接可能不由门户控制）
- `PortalClient.submit_logoff`: 提交注销（断开网络）。 /  / 判定顺序（依据实测的门户行为）： / 0. **先检查表单来源**：若中途调用过 pr ｜ logoff ｜ 注销页状态已刷新，请重新输入验证码 ｜ logoffFields ｜ captcha ｜ ctl00$MainContent$TextBoxCC
- `LoginSession`: LoginSession ｜ 把「开会话 → 取验证码 → 提交」串起来，供 GUI 与静默模式共用。 /  / 注意：换验证码必须重新 prepar ｜ cfg ｜ return ｜ 是否需要登录：**以门户状态为准**，外网探测只在门户状态未知时兜底。 /  / 实测依据（这是「软件点连接一直连不上」 ｜ 开启新会话并获取验证码图片，返回 PNG 字节。
- `LoginSession.needs_login`: 是否需要登录：**以门户状态为准**，外网探测只在门户状态未知时兜底。 /  / 实测依据（这是「软件点连接一直连不上」 ｜ 未知
- `LoginSession.prepare`: 开启新会话并获取验证码图片，返回 PNG 字节。
- `LoginSession.submit`: user ｜ guid ｜ acc ｜ pwd
- `LoginSession.query_status`: 查询门户侧连接状态（IP + 是否在线）。
- `LoginSession.prepare_logoff`: 准备断开网络：返回 (验证码 PNG, 门户状态)，同时更新本地验证码缓存。
- `LoginSession.submit_logoff`: 提交注销（断开网络）。
- `auto_login`: 全自动登录（供 --silent 使用）：识别成功则提交，验证码错自动换图重试。 /  / on_captcha(png ｜ options ｜ useOcr ｜ maxCaptchaRetry ｜ 门户显示已联网，无需登录 ｜ 网络已连通，无需登录

### config_store

- `<module>`: 配置读写：**单文件、便携语义**。 /  / 配置文件固定为程序同目录下的 `config.json`（不建子目录）， ｜ config.json ｜ http://10.6.6.6/login ｜ http://10.6.6.6 ｜ http://10.6.6.6/CheckCode ｜ http://10.6.6.6/logoff
- `app_dir`: 程序所在目录：打包运行时是 exe 所在目录，开发运行时是项目根目录。 ｜ frozen
- `config_path`: 配置文件路径：程序同目录下的单个 config.json（不建子目录）。
- `_merge`: 浅层合并：以 base 为骨架，用 override 覆盖同名键（嵌套 dict 递归一层）。
- `load_config`: 读取配置；文件缺失或损坏时返回默认配置（不抛异常，保证程序能启动）。 ｜ r ｜ utf-8 ｜ 配置根节点必须是对象
- `save_config`: 保存配置（UTF-8 无 BOM）到程序同目录的 config.json。 ｜ w ｜ utf-8
- `remove_config`: 删除本地配置文件；返回是否确实删除（用于「不留痕迹」场景）。
- `has_credential`: 是否已填写完整登录信息：学号 + 上网账号（手机号） + 密码。 /  / 上网账号对应门户 SSOACC 字段，是真正 ｜ user

### autostart

- `<module>`: 开机自启：在「启动」文件夹创建 / 删除快捷方式。 /  / 用户已明确选择该实现方式（见 docs/PLAN.md 第 ｜ 校园网自动登录.lnk ｜ 校园网自动登录.cmd ｜ --autostart ｜ return ｜ 当前用户的「启动」文件夹路径。
- `startup_dir`: 当前用户的「启动」文件夹路径。 ｜ APPDATA ｜ Microsoft ｜ Windows ｜ Start Menu ｜ Programs
- `_launch_command`: 返回 (可执行文件, 参数字符串, 工作目录)。 /  / 打包运行：目标为 exe 自身；开发运行：目标为 pytho ｜ frozen ｜ pythonw.exe ｜ app.py ｜ " ｜ " 
- `enable`: 创建开机自启快捷方式，返回 (是否成功, 说明)。 ｜ 无法访问启动文件夹：%s ｜ $ws = New-Object -ComObject WScript.Shell;$sc = $ws.CreateSh ｜ ');$sc.TargetPath = ' ｜ ';$sc.Arguments = ' ｜ ';$sc.WorkingDirectory = '
- `read_lnk`: 读取现有 .lnk 的 (TargetPath, Arguments)；读不到返回 ("", "")。 ｜ [Console]::OutputEncoding=[System.Text.Encoding]::UTF8;$ws = ｜ powershell ｜ -NoProfile ｜ -NonInteractive ｜ -Command
- `ensure_current`: 自启项必须指向**当前正在运行的这个程序**，否则重建它。 /  / 为什么需要：早期版本在源码模式下生成过指向 `py ｜ 自启项已指向当前程序（%s） ｜ 已把自启项校正为当前程序：%s
- `disable`: 移除开机自启（两种载体都清理），返回 (是否成功, 说明)。 ｜ 删除  ｜  失败： ｜ 已移除： ｜ 、 ｜ 本就没有自启项

### ocr_helper

- `<module>`: 验证码识别封装（ddddocr，MIT）。 /  / 设计要点： / - 延迟初始化：ddddocr 首次加载 onnx ｜ OcrEngine ｜ ddddocr 的薄封装：可用时返回 4 位识别结果，不可用返回空串。 ｜ png_bytes
- `OcrEngine`: OcrEngine ｜ ddddocr 的薄封装：可用时返回 4 位识别结果，不可用返回空串。 ｜ length ｜ return ｜ 惰性初始化并返回是否可用。 ｜ png_bytes
- `OcrEngine.available`: 惰性初始化并返回是否可用。
- `OcrEngine.classify`: 识别验证码；失败或无引擎时返回空串。
