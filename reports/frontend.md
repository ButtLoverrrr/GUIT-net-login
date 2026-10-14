# 前端（GUI / 交互）负责人报告 · `app.py`

范围：`app.py`（+ `tests/test_gui.py` 用例增强）。`app_logger.py` 未改动（无问题可改）。
涉及但**未改动**的文件：`portal_client.py` / `config_store.py` / `ocr_helper.py` / `autostart.py` /
`tests/support.py` / `tests/test_layout.py` / `tests/test_instance.py`（发现的问题见「遗留问题」）。

---

## 0. 门禁结果（本文所有结论的底证据）

```
cd <本机路径>
& <本机路径>
& <本机路径>
```

| 门禁 | 命令 | 结果 |
|---|---|---|
| 功能/界面/静默/布局/单实例/性能 | `tests\run_tests.py all` | **通过 61 项，失败 0 项**（exit 0） |
| 保真度 | `fidelity.py` | app 模块：`co_names` 差异 1 处 + 指令分歧 1 处 + 指令条数 +N + 常量集合差异 1 处，**全部来自两处「有意差异」，见 §1.7** |
| 性能 | `tests\run_tests.py perf` | import 0.0839s（基线 0.0848s）、界面就绪 0.0511s（基线 0.0546s）、启动路径未加载 ddddocr/onnxruntime/cv2/torch/numpy |

`tests/perf_baseline.json` 的基线 **不是我写的**（我首次跑 perf 时它还不存在，我写入过一次，后来被主线用
`guit-re/perf_ab.py` 的 5 次冷启动中位数覆盖，`_note` 里已标明"还原后的原始版本、Phase 3 改动之前"）。
我复核了该基线：我的实现在两轴上都不慢于它 → 门槛有效。

---

## 1. Phase 1 保真还原：发现的问题清单

> 判定依据一律是 **exe 内 `guit-re/work/marshal/app.marshal` 原始代码对象**（唯一真相），不是"看起来合理"。
> 反汇编命令：`& <本机路径>

### 1.1 模块级单实例逻辑错位（**P0，最严重**）

- **位置**：原文件末尾 `if __name__ == '__main__':` 的 `else:` 分支（现 `app.py:987-988` 已清理干净）
- **现象**：`import app` 就会去连自己、`recv` 超时抛 `TimeoutError` 直接崩；第二个实例连窗口都开不出来。
- **证据**：
  - 反编译版把 `create_connection/sendall/recv/_IS_SECONDARY` 这段放进了文件末尾的 `else:`；
  - 修复前跑测试直接崩：`File "app.py", line 819, in <module> / if _cli.recv(16).strip() == b'ok': / TimeoutError: timed out`（`test_perf` 的 import 探针输出）；
  - 反汇编（原始）显示客户端逻辑属于 `except OSError:` 分支内部，且**外面还套了一层 `try/except Exception: pass`**，末尾是 `JUMP_BACKWARD_NO_INTERRUPT` 回到 `if _IS_SECONDARY:` 判断。
- **是否修复**：✅ 已修复。结构还原为：

```python
try:
    _srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
except Exception:
    pass
else:
    try:
        _srv.bind(('127.0.0.1', SINGLE_INSTANCE_PORT)); _srv.listen(1); _INSTANCE_SERVER = _srv
    except OSError:
        try: _srv.close()
        except Exception: pass
        try:
            _cli = socket.create_connection(...); _cli.sendall(b'show\n')
            if _cli.recv(16).strip() == b'ok': _IS_SECONDARY = True
            _cli.close()
        except Exception: pass
if _IS_SECONDARY: os._exit(0)
```

- **验证**：`tests\run_tests.py instance` **2/2 PASS**，其中
  `test_second_instance_survives_stalled_first_instance` 专门覆盖"第一实例占着端口但卡住不应答"（修复前必挂 `TimeoutError`）。
- **风险**：低。语义与原始逐指令一致（见 §1.7 的 175 条指令全等证明）。
- **同时删除**：文件末尾多余的 `else:` 块（反编译产物，必须清除，否则 `import app` 仍会连自己）。

### 1.2 `_show_captcha` 尾部丢失（Pillow 与 tkinter 两条路都失败的汇总提示）

- **位置**：`app.py` `_show_captcha`（失败汇总分支在 `app.py:525-526`）
- **现象**：两条路都失败时静默——不提示、不写日志（界面上永远停在"正在获取…"）。
- **证据**：原始 co_consts 里独有 `''`、`'[验证码显示失败]'`、`('image','text')`、`'验证码显示失败：%s'`、`'；'`，
  co_names 独有 `lbl_captcha/configure/logger/error/join`；反编译版 167 → 147 条指令，且 Pillow 分支尾被塞了 `RETURN_CONST`。
- **是否修复**：✅ 已修复。另修掉一处更隐蔽的伪影：反编译版在 Pillow 的 `except` 之后多出 `return`，
  使 tkinter 兜底永远不会执行；原始是 `try: …成功则 return / except: errors.append(...)` 后**继续**走 tkinter。
- **验证**：还原后该函数 **167 条指令，与原始逐指令全等**。
- **风险**：低（只在失败路径生效）。

### 1.3 `_tray_image` 兜底画图丢失

- **位置**：`app.py` `_tray_image`（兜底画图在 `app.py:552-558`）
- **现象**：`assets/app.png` 缺失时返回 `None` → `pystray` 起托盘时抛错（无图标可用）。
- **证据**：原始 co_names 独有 `ImageDraw/Draw/rounded_rectangle/arc/ellipse`；`co_varnames` 独有
  `size/img/draw/cx/cy/radius`；常量集合独有 `64 (0,0,0,0) 1 2 14 (59,130,217,255) ('radius','fill') 16 (11,19,27)
  205 335 'white' 5 ('start','end','fill','width') ('fill',)`；反编译版 120 → 36 条指令。
- **是否修复**：✅ 已按反汇编逐指令还原：

```python
size = 64
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
draw.rounded_rectangle([1, 1, size - 2, size - 2], radius=14, fill=(59, 130, 217, 255))
cx, cy = size // 2, size - 16
for radius in (11, 19, 27):
    draw.arc([cx - radius, cy - radius, cx + radius, cy + radius], start=205, end=335, fill='white', width=5)
draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill='white')
return img
```

- **还原过程中的一次反直觉发现（值得存档）**：`cy` 的表达式从反汇编看是
  `LOAD_FAST size / LOAD_CONST 16 / BINARY_OP -`，即 **`size - 16`**，而不是"按比例算中心"。
  我最初按"看起来合理"写成 `size * 16 // 100`（BINARY_OP 5 乘法 + 2 整除），指令序列对不上；
  用枚举搜索（`BINARY_OP 0/2/5/6/10/11` 与 `size/2/16/100` 的组合）才定到 `cx, cy = size // 2, size - 16`。
  **这就是"字节码是唯一真相"的价值**：几何上 `64-16=48` 与 `64*16//100=10` 都能画出一个图标，但只有前者与原程序一致。
- **验证**：还原后 **120 条指令，与原始逐指令全等**；`test_tray_image_and_hide_show` 用
  `resource_path` 替换法强制走兜底分支，断言 `size == (64, 64)`（60x60 曾经因为断言写错而未被覆盖，现已真覆盖）。
- **风险**：低。

### 1.4 `_prefetch_worker` 反编译版把主流程整段重复进 `except`

- **位置**：`app.py` `_prefetch_worker`（`app.py:874-902`）
- **现象**：反编译版 317 条指令 vs 原始 201 条；`except PortalError` 里被塞了一整份主流程（重复取码、重复判断）。
- **证据**：fidelity 报告 `app.LoginApp._prefetch_worker: 指令条数 201 -> 317`；原始结构是
  **`try: 主流程 / except PortalError: 只发 warn / except Exception: 只发 warn / finally: _post('busy', False)`**，
  并且主流程内部**嵌套**一个 `try: query_status() / except PortalError: _post('net', False, '')`，
  其后的 `if not needs_login / elif guess / else` 三段都在**主 try 内**（不是被塞进内层 else）。
- **是否修复**：✅ 已修复。
- **验证**：还原后 **201 条指令，与原始逐指令全等**。
- **风险**：中（涉及启动预取的行为差异：原版失败只提示一次，反编译版会重复取码并吞掉 busy 复位）。

### 1.5 `_open_url` 常量次序

- **位置**：`app.py` `_open_url`（`app.py:597-605`）
- **现象**：REBUILD_NOTES 记为"常量次序差异"。
- **证据**：`docs/README` 里的差异条目只涉及 `co_consts` 顺序；fidelity 的 `cmp_consts` 按**集合**比较，
  而我实测该函数 `co_names`/指令序列/指令条数**与原始全等**（无任何差异条目），说明只是反汇编打印顺序造成误判。
- **是否修复**：不需要改（改了反而会破坏等价性）。已核对 try/except 结构：`try: webbrowser.open + _append_log
  + return / except Exception as exc: _append_log('打开链接失败：%s' % exc)`，与原始一致。
- **风险**：无。

### 1.6 保留主线的一处有意改动

`SINGLE_INSTANCE_PORT = int(os.environ.get('GUIT_INSTANCE_PORT', 47823))`：保留，且**已删除**原始模块级第二处
`SINGLE_INSTANCE_PORT = 47823` 重复定义（主线要求）。
这是 app 模块级唯一被允许保留的差异。

### 1.7 「其余为 0」的严格证明（不是"看起来一致"）

`fidelity.py` 的 app 段会同时列出 Phase 3 新增常量带来的差异，为把 Phase 1 单独证明干净，我做了两步实验：

**实验 A（前导段全等）**：把 `app.py` 复制到临时目录，把环境变量那行改回常量 `47823`，并在 `WM_CLOSE` 之后
补回原始那处重复定义，然后分别规范化（跳转目标→序号、剔除行号噪声）两侧指令序列，在
`CAPTCHA_ZOOM` 处截断：

```
prologue (up to & incl. CAPTCHA_ZOOM): orig=175 restored=175 identical=True
```

即 **docstring / 导入 / 单实例 try-except-else / resource_path / toast / run_silent / 常量区 全部 175 条指令逐条相同**
（含 `_show_captcha`、`_tray_image`、`_prefetch_worker` 的还原）。

**实验 B（有意差异之外无残留）**：仅允许两类差异存在 ——
① 环境变量端口那一行（3 条额外指令 `int/environ/get` + 1 个额外常量 `'GUIT_INSTANCE_PORT'`）；
② Phase 3 新增常量（`FADE_*`/`LOG_MAX_LINES`/`BTN_*`/`STATUS_*`）以及依赖它们的新方法。
其余位置（包括 `if __name__ == '__main__':` 收尾、`_instance_listener`、`main`）零差异。

**残留（已定性、无语义影响）**：`app.LoginApp` 的 `__firstlineno__` 常量 `161` → `133`。
这是**行号类噪声**（反编译重建丢了原始文件的注释/空行），`fidelity.py` 对函数级 `co_firstlineno` 本来就忽略，
只在类对象上因 `co_consts` 比较而暴露。我**没有**用填充注释去凑这个数字（那会为了一个无语义的数字往源码里塞几十行空注释，
且无法与 `resource_path`/`toast` 的行号同时对齐）。判断依据：语义唯一相关的指令序列已全等。

---

## 2. 调用链地图（事件驱动，落到 文件:函数:行）

> 行号以交付版 `app.py` 为准。`[M]` = 主线程，`[W]` = 工作线程，`[T]` = 托盘线程。

### 2.1 启动

```
main()                                             app.py:965
 ├─ _INSTANCE_SERVER is not None → Thread(_instance_listener)         [M→W]  :1009
 ├─ SetProcessDpiAwareness(1)  (异常吞)                               [M]    :1011
 ├─ args.silent → run_silent()  (=0 成功 / 1 失败 / 3 转界面)           [M]    :1015
 └─ tk.Tk() → LoginApp(root, auto_connect=args.autostart) → root.mainloop()
LoginApp.__init__                                  app.py:149
 ├─ load_config() / OcrEngine() / queue.Queue() / Logger('GUI')
 ├─ logger.set_sink(λ line: ui_queue.put(('log', line)))   ← 日志线程安全通道  :156
 ├─ _build_ui()                                    app.py:179
 │   ├─ root.bind('<Return>/<KP_Enter>/<Escape>', _on_key)   ← Phase 3        :178-180
 │   ├─ 全部控件（学号/账号/密码/验证码/换一张/记住密码/开机自动登录/连接/隐藏/断开网络/退出/
 │   │   网络状态 + 官方平台/状态栏/日志 + 滚动条/GitHub 图标 + 项目地址 + 免责声明）
 │   ├─ Entry(validate='key', validatecommand=_clean_captcha_input)  ← Phase 3 :212
 │   └─ _clamp_to_screen()（启动一次：居中；仅在装不下时才给尺寸）     :255
 ├─ _pump_queue()                                  app.py:369   [M]
 └─ root.after(150, _on_start)                                                 :164
```

### 2.2 主循环 / 消息泵（线程边界）

```
_pump_queue [M]                                     app.py:369
 ├─ 循环 ui_queue.get_nowait() → _handle(msg)        app.py:384  [M]
 └─ root.after(120, _pump_queue)   ← 每 120ms 一跳；退出前 _cancel_after() 取消
_handle [M]                                         app.py:384
 ├─ 'log' → _append_log                                   :313
 ├─ 'info'/'warn'/'error' → _append_log(前缀, level) + _set_status(text, level)  :315-319
 ├─ 'captcha' → _show_captcha(png) → var_captcha.set(guess) → 空则 _focus_captcha()
 │              → captcha_epoch = session.client.captcha_epoch                     :320-329
 ├─ 'busy' → _set_busy(busy, text)                       :327
 ├─ 'net'  → _update_net(online, ip)                     :330
 └─ 'done' → _finish(ok, message)                        :333
```

**线程边界结论**：`_post()` 是唯一跨线程出口（`ui_queue.put`）；**所有** Tk 控件写操作只在 `_handle` / 主线程回调里发生。
`logger.set_sink` 也走同一个队列（不是直接 insert），所以 `logger.info/warn/error` 可在任意线程安全调用。

### 2.3 「连接」事件

```
(控件 command) btn_connect  → _on_connect            app.py:679   [M]
(键盘) root <Return>        → _on_key → _on_connect  app.py:171   [M]   ← Phase 3
 ├─ if self.busy: return          ← 重入闸门           :623
 ├─ _collect_form()               ← 校验+落盘(见 2.6)   :625
 ├─ 用 session.client.captcha_epoch / form_source 判定手输验证码是否还新鲜 :627-631
 ├─ _set_busy(True)  → busy=True，连接按钮 disabled    :636
 └─ Thread(_worker, args=(manual,), daemon=True).start()          [M→W] :637
_worker(manual)                                      app.py:695   [W]
 ├─ _ensure_session() → LoginSession(cfg, logger)
 ├─ session.needs_login()  ← 门户权威（外网探测会被白名单放行，不可信）
 ├─ manual and client.form_source == 'login' → _submit_manual(manual)      :647
 ├─ 否则 → _auto_flow()                                                  :649
 └─ except PortalError / except Exception → logger.error + _post('done', False, …)
_auto_flow                                           app.py:714   [W]
 ├─ use_ocr = _use_ocr()  ⚠ **首次会 import ddddocr（1~15s）**             :659
 ├─ 无 OCR → session.prepare() → _post('captcha', png, '') + _post('info' …) + _post('done', False,'')  :663-666
 └─ 有 OCR → for attempt in 1..max_retry: prepare → ocr.classify → _post('captcha', png, guess)
              → session.submit(guess) → 成功 _post('done',True,msg) /
                result.kind != KIND_CAPTCHA → _post('done',False,msg) /
                否则 _post('warn','验证码识别错误，换一张重试(%d/%d)')          :668-698
_submit_manual(captcha)                              app.py:744  [W]
 └─ session.submit(captcha) → ok / KIND_CAPTCHA(→ prepare+提示重输) / 其他失败
```

### 2.4 「断开网络」事件

```
mini 按钮 → _on_logoff                               app.py:793   [M]
 ├─ if self.busy: return
 ├─ captcha = var_captcha.get().strip()
 └─ Thread(_logoff_worker, args=(captcha,), daemon=True)          [M→W]
_logoff_worker(captcha)                              app.py:800   [W]
 ├─ ready = captcha_purpose=='logoff' and form_source=='logoff' and epoch 未被换过 and hidden 非空
 ├─ 手输优先：ready 且有值 → submit_logoff → ok → captcha_purpose='login' + _post('net',False,'') + _post('done',True)
 ├─ 否则：prepare_logoff() → _post('net', status.online, status.ip) → _post('captcha', png, '')
 │        → 门户已判定未联网 → _post('done', True, '当前未联网')
 │        → 无 OCR → 提示手输；有 OCR → classify → submit_logoff → 重试 maxCaptchaRetry
 └─ 耗尽 → _post('warn', '连续 N 次自动识别失败，请输入验证码…') + _post('done', False, '')
```

### 2.5 其它事件

```
_start_prefetch  (root.after(200) 由 _on_start 挂)      app.py:865   [M]
 └─ _set_status('正在获取验证码…') + _post('busy', True, '连 接')
    └─ Thread(_prefetch_worker)                        [W] → 取码/识别/query_status → 结束 _post('busy', False)
_on_start  (root.after(150))                           app.py:349   [M]
 ├─ 回填 guid/acc/pwd/记住密码/开机自动登录 → logger.info('程序已启动') → 缺凭据则提示
 ├─ root.after(200, _start_prefetch)
 ├─ auto_connect → root.after(1500, _auto_connect_step)
 ├─ _fade_in()                              ← Phase 3（-alpha 失败静默降级）
 └─ Thread(_check_autostart)                           [W] → autostart.ensure_current()
_auto_connect_step(attempt)  root.after(12000, …)      app.py:904   [M]
 ├─ _net_online 为真 → 不再重试；attempt > 3 → 放弃提示
 ├─ self.busy → root.after(3000, 重排)
 ├─ 无凭据 → 跳过；否则 _on_connect() + root.after(12000, step(attempt+1))
_refresh_captcha → Thread(_refresh_worker)             app.py:757/763  [M→W]
_refresh_status → Thread(worker)（成功路径 _finish 内的门户状态刷新） app.py:774  [M→W]
_on_hide → root.withdraw() + pystray.Icon + Thread(icon.run)          app.py:560  [M→W/T]
_tray_show  ← 托盘线程回调 → root.after(0, root.deiconify)  ✅ 已切回主线程  :613  [T→M]
_tray_quit  ← 托盘线程回调 → _stop_tray() + root.after(0, _on_quit) ✅     :617  [T→M]
_on_quit → _cancel_after() + _stop_tray() + root.destroy()            app.py:592  [M]
_instance_listener  ← 单实例监听线程                   app.py:950  [W]
 └─ recv 含 b'show' → sendall(b'ok') → _MAIN_WINDOW.after(0, deiconify) ✅ 已切回主线程
```

### 2.6 状态机与语义

- **`self.busy`**：单一"有流程在跑"标志。置位点：`_set_busy(True)`（`_on_connect`/`_on_logoff`/`_refresh_captcha`）、
  `_post('busy', True, '连 接')`（`_start_prefetch`）。清零点：`_finish` 里的 `_set_busy(False)`、
  `_refresh_worker` 的 `finally`、`_prefetch_worker` 的 `finally`。
  闸门：`_on_connect`/`_on_logoff`/`_refresh_captcha`/`_start_prefetch`/`_auto_connect_step` 都在入口 `if self.busy: return`。
  ⚠ **已知代价**：busy 期间的点击被**静默丢弃**（无提示）——见 §3.
- **`captcha_purpose`**：'login' | 'logoff'。语义是"当前界面上这张验证码属于哪个表单"。
  登录成功/断开成功后重置为 'login'；取注销码时置 'logoff'。
- **`captcha_epoch`**：主线程缓存的"已验证过的取码轮次"，来源 `session.client.captcha_epoch`。
  `_on_connect` 用它判断手输值是否属于当前这张码（`stale = current != self.captcha_epoch`），
  过期则忽略手输值并写日志"当前验证码已过期，已自动重新获取"。
- **`_MAIN_WINDOW`**：模块级全局，`_build_ui` 里赋值，只被单实例监听线程用来 `after(0, deiconify)`。
- **`root.after` 链**：`_pump_queue` 120ms（自身重排）、`_on_start` 150ms、`_start_prefetch` 200ms
  （由 `_on_start` 挂）、`_auto_connect_step` 12000ms / busy 时 3000ms。
- **`self.photo`**：`_show_captcha` 里赋值，防 `ImageTk.PhotoImage` 被 GC（**已正确保持**）。
- **单实例监听线程**：`daemon=True`，`accept()` 循环，异常即 return；收到 `show` 才回 `ok`。

---

## 3. 精简清单（奥卡姆，全部为等价简化）

| # | 位置 | 改动 | 等价性依据 |
|---|---|---|---|
| S1 | `_pump_queue` | `self.txt_log` 反复属性查找 → 局部变量语义等价 | 与原始指令数一致（Phase 1 已证）；仅易读性 |
| S2 | `_fit_captcha_label` | 保留 `width=self.photo.width(), height=self.photo.height()`（**与原始写法完全一致**） | 实验：Tk 8.6.15 下 `width=photo.width()` 与 `width=0` 几何等价（44x24 两法相同）；结论见 §5 |
| S3 | `_clamp_to_screen` | **去掉**显式给宽高（除装不下时），只设位置 `+x+y` | 显式 `geometry('WxH')` 会关闭 Tk 对顶级窗口的自动尺寸传播；只设位置不会。据此撤掉了我先前误加的 `_fit_window()`（见 §5 复盘） |
| S4 | `run_silent` / `_worker` / `_logoff_worker` | 未改（`if x: return True\nreturn False` 类写法在本文件不存在；未做无谓改写） | —— |
| S5 | `_handle` 的 `'captcha'` 分支 | 保留（`if session is not None: … return\nreturn` 两端结构冗余，但改动会破坏 §1 已证全等的模块结构，收益为 0） | 与原始逐指令一致 |

> **没有**做"顺手改无关代码"：`portal_client.py` 等后端文件一行未动。

---

## 4. 性能与动画

### 4.1 性能（`perf` 三轴：不回归）

| 轴 | 基线（原始版） | 交付版实测 | 判定 |
|---|---|---|---|
| `import app` | 0.0848s | 0.0839s | 不回归（阈值 = 基线×1.25+0.10 = 0.206s） |
| 界面就绪 | 0.0546s | 0.0511s | 不回归（阈值 0.168s） |
| 启动路径重型依赖 | 必须为空 | `[]` | PASS |

**改动**：Phase 3 只增加启动期的 1 次 `update_idletasks` + 一次 `geometry('+x+y')`（`_clamp_to_screen`）与
10 次 `after(16ms)` 的 `-alpha` 写操作，均在 0.5s 内完成，实测低于基线。

### 4.2 动画（用户明确要求，克制 + 可降级）

| 项 | 实现 | 失败降级 | 不阻塞主线程 |
|---|---|---|---|
| 窗口淡入 `0.1→1.0` | `_fade_in` 用 `root.after(16ms)` 分 10 步写 `-alpha` | 任何异常 → `_fade_off=True` + 强制 `-alpha=1.0`（远程桌面/无合成器直接可见） | ✅ 纯 `after` 链 |
| 主按钮 hover/press | `_bind_hover` 绑 `<Enter>/<Leave>/<ButtonPress-1>/<ButtonRelease-1>`，只改 `bg` | `bind` 失败静默 | ✅ 事件回调 |
| 状态栏随状态变色 | `_set_status(text, level)` → `info/error` 对应 `STATUS_INFO_FG/STATUS_ERR_FG` | `try/except` 包住 | ✅ |
| 日志平滑跟随底部 | 只在 `yview()[1] >= 0.999`（贴底）时 `see('end')` | `try/except` | ✅ |

集中常量（可一键关闭）：`FADE_ENABLED / FADE_STEPS / FADE_INTERVAL_MS / LOG_MAX_LINES /
BTN_HOVER_BG / BTN_PRESS_BG / STATUS_OK_FG / STATUS_ERR_FG / STATUS_INFO_FG`。
**没有**改窗口布局语义：截图（`docs/ui_after.png`，494×874）与原始 `docs/orig_ui.png` 逐元素对照，
学号/上网账号/上网密码/验证码图/换一张/看不清可换一张/记住密码/开机自动登录/连接/隐藏/断开网络/退出/
网络状态/官方平台 10.6.6.6/日志区含滚动条/项目地址 v1.0.0/免责声明 **全部齐全且完整可见**。

---

## 5. 「多余改动」复盘（重要，必须记录）

我中途基于一条**错误前提**（"原始窗口 329×583、右侧被裁切"）实施过窗口自适应改造，随后被主线的实验证据推翻。
我做了**独立复核**，并已全部撤回：

1. **`_fit_window()`（已删除）**：它显式 `geometry('WxH')`，会关闭 Tk 对顶级窗口的自动尺寸传播，
   把一个"能自愈"的控件换成"必须手工维护"的。复核实验（本机 Tk 8.6.15）：
   `resizable(False, False)` + `withdraw()` 之后 `wm_geometry('403x606')` 返回 `''` 且窗口仍 200×200；
   而原始实现下**图片显示后窗口会自己从 403×606 长到 406×624** —— 我原先观察到的"差 18×3 被裁"其实是该自动增长
   在我的 `_fit_window` 干扰下没有发生。**结论：原始实现这条路径无缺陷，我的改动是多余的 → 已删除。**
2. **验证码缩放 clamp（已删除）**：同理，属未证实前提下的改动 → 恢复 `CAPTCHA_ZOOM` 常量语义。
3. **`_fit_captcha_label` 注释（已改回）**：我原先在注释里写"Label 的 width/height 是字符、会暴涨到 2648×2354"，
   **这个结论是错的**（Label 带图后按像素计）。注释已恢复为描述原始语义，并注明
   `width=photo.width()` 与 `width=0` 在本机几何等价（保留显式像素值）。
4. **`_append_log` 的"贴底才跟随 + 有界裁剪"（保留）**：这条有独立证据（日志区是 `Text`，无上限增长 +
   每次 `see('end')` 在长文本下是 O(n) 重排），且不改布局 → 保留，并用 `test_log_is_bounded_and_keeps_bottom` 覆盖。
5. **小屏高度加固（保留但降级为最小形态）**：只保留启动时"屏幕装不下才收敛尺寸 + 居中"，
   且**不打断 Tk 传播**（装得下时只设位置）。`test_layout.test_window_height_can_fit_small_screens` 覆盖。

---

## 6. 易用性完善（逐条 + 验证）

| # | 项 | 实现（位置） | 验证 |
|---|---|---|---|
| U1 | 窗口居中 | `_clamp_to_screen`（启动一次） | `test_window_centered_and_on_screen`（含不越屏） |
| U2 | 回车 = 连接 | `root.bind('<Return>'/'<KP_Enter>', _on_key)`，走与按钮**同一条** `_on_connect` 路径 | `test_enter_connects_and_escape_hides`（真的提交到门户） |
| U3 | Esc = 隐藏 | 同上 → `_on_hide` | 同上（断言 `root.state()=='withdrawn'`） |
| U4 | 验证码框自动聚焦 | `_handle('captcha')` 里 guess 为空时 `_focus_captcha()` | 手工验证（截图时输入框已聚焦）；`_focus_captcha` 异常静默 |
| U5 | 错误后自动清空 | 换码时 `_post('captcha', png, '')` → `var_captcha.set('')`（原始语义，保留） | `test_connect_flow_wrong_captcha_then_manual` |
| U6 | 粘贴去空白 + 长度上限 6 | `_clean_captcha_input` + `Entry(validate='key')` | `test_captcha_input_cleaned_on_paste`（`'ab cd\t'`→`'abcd'`；>6 截断；零宽字符清除） |
| U7 | 缺项提示更明确 | `_collect_form`：状态栏与日志同时列出缺失项（`请填写：学号、上网账号`），保留原始措辞 | `test_collect_form_validation`（未削弱） |
| U8 | 日志分级着色 | `_append_log(text, level)` + `tag_configure('warn'/'error')` | `test_log_is_bounded_and_keeps_bottom`（断言 error tag 存在） |
| U9 | `_finish` 成功/失败与状态栏/日志一致 | 成功 `_set_status(msg or '登录成功')`；失败 `_set_status(msg, 'error')` + 状态栏转红 | `test_update_net_and_queue_pump` + `test_log_is_bounded_and_keeps_bottom` 的颜色断言 |
| U10 | 退出时清理挂起的 `after` | `_cancel_after()`（取消 `_pump_queue`/淡入）；`_tray_quit` 也走 `_on_quit` | 目测：测试 stderr 中「invalid command name "_pump_queue"」显著减少（destroy 后的残留回调） |
| U11 | 密码可见性切换 | **未做** | 原始无此控件，新增会改控件集合（`test_window_constructs_and_widgets_exist` 之外的语义变化），收益低、风险中 → 按"克制"原则放弃，记录在此 |
| U12 | 错误文案人话化 | 保留后端 `message` 原义，只统一前缀（日志 `[x]`/状态栏）与成功/失败标记（✔/✘） | 不改后端返回文案，符合"不要改后端 message" |

---

## 7. 举一反三（一个问题 → 同类扫描）

| 原始问题 | 同类扫描范围 | 扫描结果 |
|---|---|---|
| §1.1 模块级单实例被挪到 `else:` | 全文件"反编译挪动控制流" | 仅此一处；`if __name__=='__main__'` 现已干净（无 `else:`） |
| §1.2 `except` 后多出 `return`（吞掉兜底路径） | 所有 `try/except` 的"失败后是否还有后续尝试" | `_show_captcha`（Pillow→tkinter）已修；`_tray_image`（asset→现画）已修；`_refresh_worker`/`_worker`/`_logoff_worker` 检查后**无**同类问题 |
| §1.4 `except` 分支被复制主流程 | 所有 `except` 分支体量 vs 原始指令数 | fidelity 报告逐函数确认：除已修的 `_prefetch_worker` 外无"指令数异常膨胀"的函数 |
| §3「busy 期间点击被静默丢弃」 | 所有入口闸门（`_on_connect`/`_on_logoff`/`_refresh_captcha`/`_start_prefetch`/`_auto_connect_step`） | 5 处同构；**未改**（改文案会动 UI 语义），记为遗留 R1 |
| 「`root.after` 未取消 → destroy 后残留回调」（我修 `_pump_queue` 时遇到） | 所有 `root.after(...)` 调用点 | 共 8 处：`_on_start`(150)、`_start_prefetch`(200)、`_pump_queue`(120)、`_auto_connect_step`(12000/3000)、`_tray_show`/`_tray_quit`(0)、`_fade_in`(16)。已收敛 `_pump_queue`/`_fade_in`；其余为短生命周期或一次性，残留仅在退出瞬间报 Tcl 噪声（不崩），记为遗留 R2 |
| 「日志无上限增长」 | 所有"只增不减"的控件/结构 | `txt_log`（已修）；`ui_queue`（消费者持续取，不成问题）；`session`（不累积） |
| 「跨线程操作 Tk」 | 所有线程体 | `_worker`/`_auto_flow`/`_submit_manual`/`_logoff_worker`/`_refresh_*`/`_prefetch_worker`/`_check_autostart` 只经 `_post`/`logger`；托盘两回调、单实例监听都已 `after(0, …)`；**无**直接跨线程改控件 |
| 「PhotoImage 被 GC」 | 所有 `PhotoImage` 赋值点 | `self.photo`（保持着）、`self.icon_github`（保持着）——均无问题 |

---

## 8. 改动清单（每条一行：文件:位置 做了什么 为什么）

| # | 文件:位置 | 改动 | 为什么 |
|---|---|---|---|
| C1 | `app.py:35` | `SINGLE_INSTANCE_PORT = int(os.environ.get('GUIT_INSTANCE_PORT', 47823))`（保留主线改动） | 测试沙箱需要随机端口，避免与真实实例互撞 |
| C2 | `app.py:38-41` | 单实例 socket 创建放回 `try`、bind/listen 放回 `else` | 还原原始控制流（§1.1） |
| C3 | `app.py:48-59` | `create_connection…close` 包回内层 `try/except Exception: pass` | 原始结构；第一实例卡住时第二实例必须能继续启动（§1.1） |
| C4 | `app.py:60-61` | 删除文件末尾残留的 `else:` 块 | 反编译产物；留着 `import app` 会连自己崩 |
| C5 | `app.py:66-70` | 加 2 行注释说明行号类噪声 | 让评审知道 `__firstlineno__` 差异的来源（§1.7） |
| C6 | `app.py:101-111` | 新增动画/日志/状态色集中常量 | 动画可集中关闭、便于评审（§4.2） |
| C7 | `app.py:149-164` | `__init__` 增加 `_after_id/_fade_job/_fade_off` | 退出清理与淡入降级状态 |
| C8 | `app.py:179-181` | `_build_ui` 绑定 `<Return>/<KP_Enter>/<Escape>`、加 `_clamp_to_screen()` 调用 | U2/U3/U1 |
| C9 | `app.py:212` | 验证码 Entry 换成实例属性 + `validate='key'` | U4/U6 |
| C10 | `app.py:247-250` | 日志 Text 增加 `warn/error` 颜色 tag | U8 |
| C11 | `app.py:236-238` | 状态栏换成实例属性 `status_label` | U9（要改颜色必须能引用） |
| C12 | `app.py:221-223` | 连接按钮用 `BTN_HOVER_BG` 作 `activebackground` + `_bind_hover` | 4.2 视觉反馈 |
| C13 | `app.py:276-294` | 新增 `_clamp_to_screen`（仅启动一次；位置优先，装不下才收敛尺寸） | U1 + 小屏可用性，且不打断 Tk 传播（§5.5） |
| C14 | `app.py:302-347` | 新增 `_bind_hover` / `_fade_in` / `_cancel_after` | 4.2 + U10 |
| C15 | `app.py:365-367` | `_on_start` 调用 `_fade_in()` | 窗口淡入 |
| C16 | `app.py:369-371` | `_pump_queue` 记录并可取消 `_after_id` | U10（退出后不再有残留回调） |
| C17 | `app.py:389-410` | `_handle` 把 level 传给日志/状态栏；captcha 分支空值聚焦 | U8/U9/U4 |
| C18 | `app.py:412-463` | `_append_log(text, level)` + 新增 `_trim_log` / `_focus_captcha` / `_clean_captcha_input` | U6/U8/§4.2（有界日志+贴底才跟随） |
| C19 | `app.py:465-471` | `_set_status(text, level)` 增加颜色 | U9 |
| C20 | `app.py:522-526` | `_show_captcha` 补回失败汇总（`configure(image='', text='[验证码显示失败]')` + `logger.error`） | §1.2 |
| C21 | `app.py:541-558` | `_tray_image` 补回 64×64 现画兜底 | §1.3 |
| C22 | `app.py:874-902` | `_prefetch_worker` 去重、改回 `try/except PortalError/except Exception/finally` + 内层 try | §1.4 |
| C23 | `app.py:532-534` | `_finish` 失败路径标记 `'error'`（状态栏转红） | U9 |
| C24 | `app.py:578-595` | `_tray_quit` 改走 `_on_quit`；`_on_quit` 先 `_cancel_after()` | U10 + 托盘退出清理一致 |
| C25 | `app.py` 末尾 | 只保留 `if __name__ == '__main__': sys.exit(main())` | §1.1（删除 `< 0.5s>` 的 `else:`） |
| C26 | `tests/test_gui.py:12-66` | `_boot` 注入 `StubOcrEngine`（不 import ddddocr）+ `settle()` 帮助函数 | 消除测试间随机失败（§9） |
| C27 | `tests/test_gui.py:69-90` | 新增 `settle()`：等启动预取结束 | 避免"预取占用 busy → 连接点击被丢弃"的假失败 |
| C28 | `tests/test_gui.py` | 新增 6 个用例：`window_centered_and_on_screen`、`fade_in_returns_to_full_opacity`、`enter_connects_and_escape_hides`、`captcha_input_cleaned_on_paste`、`log_is_bounded_and_keeps_bottom`、`captcha_zoom_is_constant_and_unclamped` | 覆盖 Phase 3 全部新增行为 |
| C29 | `tests/test_gui.py` | 修正 `test_tray_image_and_hide_show`：有图断言 `min(size)>0`，另用 `resource_path` 替换强制走兜底分支断言 `(64,64)` | 主线指出的断言错误修正（原断言在有 `assets/app.png` 时必挂） |
| C30 | `tests/test_gui.py` | `test_captcha_display_uses_pixel_size` 恢复原始断言 | 前提经复核成立（§5.3） |
| C31 | `docs/ui_after.png` | 新增改造后源码运行态截图（494×874，DPI 感知） | 证据 |

---

## 9. 测试证据

### 9.1 全量

```
cd <本机路径>
& <本机路径>
=> == 后端 == 33 PASS；== 前端/界面 == 15 PASS；== 静默模式 == 5 PASS；
   == 界面布局 == 3 PASS；== 单实例行为 == 2 PASS；== 性能 == 3 PASS
   通过 61 项，失败 0 项   (exit 0)
```

### 9.2 保真度

```
& <本机路径>
=> app 段差异 = 1(co_names) + 1(指令分歧@#50) + 2(指令条数 336→342 与 +6 说明) + 1(常量集合 'GUIT_INSTANCE_PORT')
   全部来自：①环境变量端口行 ②Phase 3 新增常量 + 类内新增方法 ③类对象 __firstlineno__ 行号噪声
```

**Phase 1 单独证明**（实验 A，脚本 `<本机路径>

```
prologue (up to & incl. CAPTCHA_ZOOM): orig=175 restored=175 identical=True
```

### 9.3 本报告写完后我遇到并修掉的测试不稳定（记录下来）

| 症状 | 根因（有线程栈证据） | 修法 |
|---|---|---|
| `settle()` 在 `run_tests.py gui` 里超时，单跑却通过 | 启动预取线程卡在 `app.py:879 _use_ocr → ocr_helper.py:25 import ddddocr`（首次导入 onnxruntime/cv2/numpy 需 >15s），期间 `busy=True`，用例发起的连接被入口闸门静默丢弃 | `tests/test_gui.py` 的 `_boot` 在 `LoginApp` 之前替换 `appmod.OcrEngine` 为 `StubOcrEngine`（不 import ddddocr），并在每个连接类用例前 `settle()` |
| `test_enter_connects_and_escape_hides` 断言门户在线失败 | 预取已把"正确"识别结果填进输入框并记为 `captcha_epoch`，随后用例把 `ui.ocr` 换成"错误"替身，手输路径用旧值被门户判验证码错误 | 用例内 `ui.var_captcha.set('')` 后触发回车（走自动识别路径） |
| `test_connect_flow_wrong_captcha_then_manual` 断言 `online is False` 失败 | 同因：预取填了正确码 → 直接登录成功 | 同上清空输入框，使流程走"识别失败→重试→转手输" |
| `test_tray_image_and_hide_show` 固定时长的 `pump` 偶发 5s 告警 | 托盘线程启动时间不定 | 断言改为 `wait_until` 条件等待（`tray_icon is not None` / `root.state()=='normal'`），不削弱断言 |

GUI 用例连续跑 3 轮：**15/15 PASS ×3**。

### 9.4 截图证据

`docs/ui_after.png`（494×874，DPI 感知截图进程 `SetProcessDpiAwareness(2)`，
命令见任务书；启动 3.5s 内窗口已可见）。与 `docs/orig_ui.png` 逐元素对照：控件齐全、无裁切。
注：截图时无账号配置，验证码区显示占位文案"正在获取…"（真实运行会显示门户验证码），
日志区显示"程序已启动 / 首次使用：请填写账号信息后点击「连接」"，与 `_on_start` 语义一致。
截图未在项目根写出 `config.json`（已核实 `Get-ChildItem config*` 无产物）。

---

## 10. 遗留问题

### 前端（我的文件）

| # | 位置 | 现象 | 判断 |
|---|---|---|---|
| R1 | `app.py:680/750/723/833/892` | `busy` 期间的点击/快捷键被**静默丢弃**（无任何提示） | 未改：加提示会改动状态栏/日志语义，且原始行为如此。建议主线裁决是否加"正在处理中…"提示 |
| R2 | `app.py:925-929`（`_auto_connect_step` 的 `after`）等 | 退出瞬间仍未取消的 `after` 会在 stderr 留下 `invalid command name "…_auto_connect_step"` 噪声（**不崩、不影响退出码**） | 已收敛 `_pump_queue`/`_fade_in`；剩余为一次性短链。若要彻底干净可在 `_on_quit` 里记录全部 job id |
| R3 | `app.py:715`（`_auto_flow` 的 `_use_ocr`） | 首次 OCR 可用性检查会触发 ddddocr 导入（实测 >15s），期间 busy=True → 用户点击被丢，表现为"程序卡住" | **未改**（属于后端导入策略）；建议后端提供"异步/懒加载预热"或把可用性检查挪到打包期常量 |
| R4 | `app.py:146` | `class LoginApp` 的 `__firstlineno__` 与原始差 28（161 vs 133） | 行号类噪声；我**刻意不用填充注释**去凑（§1.7）。若门禁要求严格清零，需要主线裁决是否接受"填充注释凑行号"这种非语义改动 |
| R5 | `app.py:560-611`（`_on_hide`） | `pystray` 不可用时退化为 `iconify()`，而 `deiconify` 恢复逻辑正常；但 `_tray_show` 在"无托盘"时是无效路径 | 观察项，无实际故障 |
| R6 | `docs/orig_ui.png` vs `docs/ui_after.png` | 交付版窗口 494×874（含 DPI），原版同尺寸；**相位/字体未变**，但我无法在 100% DPI 机器上复核 | 需主线在 100% 缩放机上复验一次居中效果 |

### 后端文件（我不许改，交主线处理）

| # | 位置 | 现象 | 证据 |
|---|---|---|---|
| B1 | `config_store.has_credential.<genexpr>` | 反编译成 `user.get(key)(''.strip())` → **运行必崩**（`str` 不可调用） | fidelity：`co_names` 缺 `bool`；指令分歧 `LOAD_DEREF user` vs `LOAD_GLOBAL bool`；26 → 29 条 |
| B2 | `portal_client._parse_status` | 反编译成 `return None(ip=None, online=None, text='未知')` → **运行必崩**；原始是先算 `online = '已联网' in text` 再 `PortalStatus(...)` | fidelity：49 → 51 条；`SyntaxWarning: 'NoneType' object is not callable` |
| B3 | `portal_client.PortalClient.is_online` | 多出一段 `try: pass except Exception: continue` | fidelity：143 → 154 条 |
| B4 | `config_store.load_config` | `co_names` 顺序差（`_merge/DEFAULT_CONFIG` 与 `Exception`）→ try/except 结构需核对 | fidelity：`co_names` 差异 + 指令分歧 @#38 |
| B5 | `app_logger.Logger` / `ocr_helper.OcrEngine` / `portal_client.{PortalError,LoginResult,PortalStatus,PortalClient,LoginSession}` | 仅 `co_consts` 行号类噪声（如 `161` 对应位置） | fidelity 差异项均为"常量集合差异 [数字]" |
| B6 | `config_store`/`ocr_helper`/`autostart`/`portal_client` 已由后端 agent 大规模重构（`portal_client` 差异 61 项） | 我看不动它们的语义，**未评估** | `fidelity.py` → `portal_client: 差异项 61`；`autostart: 18` |

> **注**：B1/B2 在本次 `run_tests all` 中并未失败，说明后端 agent 已经或正在修复它们；
> 我按"只报告不修改"的约束列出，供主线做最终一致性核对。

### 交付物

- `app.py`（前端全部改动）
- `tests/test_gui.py`（6 个新用例 + 2 处断言修正 + OCR 替身/`settle` 稳定性改造）
- `docs/ui_after.png`（改造后运行态截图）
- 本报告 `reports/frontend.md`
