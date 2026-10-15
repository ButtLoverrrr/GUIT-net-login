# 重建工程说明（反编译 → 可运行 → 可测）

> **版本说明**：本文是 2026-10-13 反编译重建工作线的记录。OCR 解耦（2026-10-15）后
> 第一方模块多了接口层 `src/ocr.py`，当前调用链是
> `app / portal_client → ocr → ocr_helper → ddddocr`（见 `docs/ocr-interface.md`）；
> 下面「第一方模块」列表是当时的基线，不在其中新增 `ocr` 以免混淆历史比对。

## 目标程序
`<本机路径>
- PyInstaller 6.x **onefile**，内嵌 **CPython 3.13**（`python313.dll`，pyc magic `f30d0d0a`）
- 第一方模块（PYZ 内）：`app`、`portal_client`、`config_store`、`ocr_helper`、`app_logger`、`autostart`
  （解耦后另有 `ocr`；当前重打包清单见 `tools/build_slim_exe.py` 的 `PYZ_MODULES`）
- 第三方：`PIL 12.3`、`numpy 2.5.4`、`opencv(cv2) 5.0.0`、`onnxruntime 1.31`、`ddddocr 1.6.1`、`pystray`
- 程序功能：tkinter 单窗口「联网设置」（学号/账号/密码/验证码 + 连接/断开/隐藏/退出 + 日志区 + 托盘），
  后端对 `http://10.6.6.6` 的 ASP.NET WebForms 门户做登录/注销，验证码用 ddddocr 识别；
  另有 `--silent` 静默登录、`--autostart` 开机自动连接、单实例（本机 TCP 回环端口）。

## 目录约定
| 路径 | 说明 |
|---|---|
| `<本机路径>
| `<本机路径>
| `<本机路径>
| `<本机路径>
| `<本机路径>
| `<本机路径>
| `<本机路径>

## 三个门禁（每次改完都要跑）
```powershell
# 1) 保真度：反编译重建是否与原始字节码语义一致（Phase 1 必须清零）
& <本机路径>
# 2) 功能测试（后端+前端+性能）
cd <本机路径>
& <本机路径>
# 3) 反汇编取证（定位某函数原始行为）
& <本机路径>
```

## 已知反编译伪影（fidelity 报告里的差异 = 必须按原始字节码还原）
反编译器 `ejfk/pycdc v0.6.0` 整体质量高（6 个模块都能 `ast.parse`），但下列位置语义被破坏：

### app.py（前端）
1. **模块级单实例逻辑错位**：原始是顶层 `try: _srv=socket.socket(...) / except Exception: pass / else: try: bind+listen except OSError: <关闭+连回第一实例+sendall(b'show')+recv=='ok'→_IS_SECONDARY=True>`；
   反编译把"连回第一实例"那段挪到了文件末尾 `if __name__=='__main__': ... else: <那段>`。
   → 后果：`import app` 时也会去连自己并 recv 超时崩溃（测试就是这么发现的）。
2. **`LoginApp._show_captcha` 尾部丢失**：Pillow 与 tkinter 两条路都失败后应汇总提示
   （原始常量：`''`、`('[验证码显示失败]')`、`('image','text')`、`'验证码显示失败：%s'`、`'；'`，用到 `lbl_captcha/configure/logger/error/join`）。
3. **`LoginApp._tray_image` 的兜底画图丢失**：`assets/app.png` 缺失时应现画 64×64 RGBA 图标
   （原始常量：`64`、`(0,0,0,0)`、`1`、`2`、`14`、`(59,130,217,255)`、`('radius','fill')`、`16`、`(11,19,27)`、`205`、`335`、`'white'`、`5`、`('start','end','fill','width')`、`('fill',)`；用到 `ImageDraw/Draw/rounded_rectangle/arc/ellipse`；局部名 `size/img/draw/cx/cy/radius`）。
4. **`LoginApp._prefetch_worker` 整段重复**：反编译版 317 条指令 vs 原始 201 条 —— `except PortalError` 分支里被复制了一整份主流程。
5. `LoginApp._open_url` 常量顺序差异（`'打开链接失败：%s'` 与 `None` 次序）→ 需核对 try/except 结构。
6. 已由我做过的一处**有意改动**（不要回退）：`SINGLE_INSTANCE_PORT = int(os.environ.get('GUIT_INSTANCE_PORT', 47823))`，并删掉了重复定义的那一行。

### portal_client.py（后端）
7. **`PortalClient._parse_status`**：反编译成 `return None(ip=None, online=None, text='未知')`（运行必崩）。原始：先算 `online = '已联网' in text`，再用 `PortalStatus(ip=ip, online=online, text=...)`（常量含 `'已联网'`、`'未知'`，CALL_KW 名表 `('ip','online','text')`）。
8. **`PortalClient.is_online`**：反编译多出一段 `try: pass except Exception: continue`（154 vs 143 条指令）。
   （业务逻辑不变：多源探测、绕过系统代理、按 expect/204 判定。）

### config_store.py（后端）
9. **`has_credential`**：反编译成 `all(user.get(key)(''.strip()) ...)`（str 不可调用，运行必崩）。
   原始生成器里用到 `bool`、`get`、`strip`（`LOAD_GLOBAL bool`）。
10. **`load_config`**：co_names 顺序差（`_merge/DEFAULT_CONFIG` 与 `Exception` 次序）→ try/except 结构需核对。

### app_logger.py / ocr_helper.py / autostart.py
11. 仅行号类噪声，无已知语义问题。

### ocr.py（OCR 接口层，解耦时新增）
12. 不在反编译基线内，不参与 `fidelity.py` 的逐指令比对；其契约、装配与配置
    类型安全由 `tests/test_ocr_decoupling.py` 覆盖（见 `docs/ocr-interface.md`）。

## 硬约束（务必遵守）
- **公开接口冻结**：`portal_client.{PortalError,LoginResult,PortalStatus,PortalClient,LoginSession,auto_login,KIND_*,auto_login,HIDDEN_FIELDS,ONLINE_PROBES}`、
  `config_store.{app_dir,config_path,DEFAULT_CONFIG,load_config,save_config,remove_config,has_credential}`、
  `app_logger.Logger.{set_sink,info,warn,error,log}`、`ocr_helper.OcrEngine.{available,classify}`、
  `autostart.{is_enabled,enable,disable,ensure_current,read_lnk,startup_dir,lnk_path,cmd_path}`。
  可以新增内部函数/常量，但不得改名或改签名。
- **不碰用户系统**：禁止注册表、禁止写 `%APPDATA%\...\Startup`（测试 harness 已把 `autostart.startup_dir` 换成临时目录）、
  禁止写 exe/仓库外的路径、禁止联网下载、禁止新增第三方依赖。
- **不做多余的事**：不新增与需求无关的功能；奥卡姆精简只允许"等价简化"（语义必须逐条对齐原始字节码或测试）。
- **不许修一个多两个 bug**：每次改动 → 跑门禁 → 有失败先回退再加分析；不允许"应该没问题"就交付。
- **文件所有权**：前端 agent 只改 `app.py`（可含 `app_logger.py`）；后端 agent 只改 `portal_client.py`、`config_store.py`、
  `ocr_helper.py`、`autostart.py`。发现对方文件的问题 → 写进报告交给我，不要自己动。
- 测试沙箱：`tests/support.py` 负责临时配置目录、模拟门户、`GUIT_INSTANCE_PORT` 随机端口、`portal_client.ONLINE_PROBES` 收敛到本地。
