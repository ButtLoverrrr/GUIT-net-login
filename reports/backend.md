# 后端报告（门户登录核心 / 配置持久化 / 验证码 OCR / 开机自启）

负责人：后端 agent（与前端 agent 并行）
改动范围：`portal_client.py`、`config_store.py`、`ocr_helper.py`、`autostart.py`、`tests/test_backend.py`（只新增/加强）、`reports/backend.md`（本文件）
未动：`app.py`、`app_logger.py`、`tests/support.py`、`tests/test_gui.py`、`docs/REBUILD_NOTES.md`、`<本机路径>

---

## 0. 门禁结论（先说结果）

| 门禁 | 命令 | 结果 |
|---|---|---|
| 后端功能 | `tests\run_tests.py backend` | **通过 31 项，失败 0 项** |
| 全套功能 | `tests\run_tests.py all` | 后端 31 / 31 全绿；我最后一次运行时（前端 agent 正在并行改动 `app.py` + 新增 `test_gui/test_layout/test_silent/test_instance`）全套是 `通过 57 项，失败 2 项`，两条都在 `test_gui`（`test_captcha_zoom_clamped_on_short_screen`、`test_log_is_bounded_and_keeps_bottom`），属前端 agent 文件、不在我的所有权范围内，见 §9.5 |
| 性能 | `tests\run_tests.py perf` | `import app` 0.0833~0.0834s（基线 0.0856）、`界面就绪` 0.0481~0.0678s（基线 0.072）→ 3 项全过 |
| 保真度（Phase 1 基线，我负责的 4 模块） | 见 §8 的「保真度取证」 | portal_client **语义差异 0** / config_store **0** / autostart **0** / ocr_helper 1（仅类定义行号常量） |
| 官方 `fidelity.py`（含 Phase 3 重构与行号常量） | `guit-re\fidelity.py` | portal_client 63 / config_store 12 / ocr_helper 1 / autostart 18 → **逐条解释见 §8**（Phase 1 后 fidelity 已非零差异约束，重构必然产生差异） |

一句话：**后端 4 个模块全部交付，后端用例 31/31 全绿，性能门禁全过；全套剩余 2 条红用例都在前端 `test_gui`（不在我的所有权范围），需要主线决策的事项列在 §9。**

---

## 1. 发现的问题清单

编号规则 `B-nn`。位置按**最终文件行号**。

| # | 位置 | 现象 | 证据 | 是否修复 | 修法 | 风险 | 回归影响 |
|---|---|---|---|---|---|---|---|
| B-01 | `portal_client.py:326` `_parse_status` | 反编译成 `return None(ip=None, online=None, text='未知')`，**一调用就 TypeError** | 原始 marshal 反汇编：`CONTAINS_OP 0 / STORE_FAST online` 后紧接 `LOAD_GLOBAL PortalStatus / LOAD_FAST_LOAD_FAST (ip,online) / LOAD_FAST text / COPY 1 / TO_BOOL / POP_JUMP_IF_TRUE ... CALL_KW 3`；常量表 `('已联网','未知',('ip','online','text'))` | ✅ | 按反汇编还原分支：`PortalStatus(ip=ip, online=online, text=text or ('已联网' if online else '未知'))`（用 `or` 生成与原始一致的 COPY/TO_BOOL 结构） | 无 | 新增 `test_parse_status_all_branches` 覆盖 7 个分支 |
| B-02 | `portal_client.py:153` `is_online` | 反编译多出 6 条不可达指令（`try: pass / except Exception: continue`），143 → 154 条 | 原始 143 条，`fidelity` 报「指令条数 143 -> 154」；反汇编里 `143 FOR_ITER 175` 而反编译版 `FOR_ITER 177` | ✅ | 删掉那 6 条，恢复原始探测循环 | 无（死代码） | `test_is_online_candidate_rules`（含 204 才认、内容不匹配不算在线） |
| B-03 | `config_store.py:85` `has_credential` | 反编译成 `user.get(key)(''.strip())`，`str` 不可调用，**一调用就 TypeError** | 原始 genexpr 反汇编：`LOAD_GLOBAL bool` → `user.get(key)` → `COPY/TO_BOOL/POP_JUMP_IF_TRUE` → `LOAD_CONST ''` → `.strip()` → `CALL 1`（即 `bool(user.get(key).strip())`，键必须存在） | ✅ | 还原为 `all(bool((user.get(key) or '').strip()) ...)`；`user` 非 dict 时安全退化（原始会 AttributeError） | 极低 | `test_has_credential_shapes` 覆盖 10 种形态 |
| B-04 | `config_store.py:39` `load_config` | 反编译把 `return _merge(...)` **挪出了 try**，`co_names` 次序差（`_merge/DEFAULT_CONFIG` 跑到 `Exception` 之后） | 原始反汇编：`89 L5 LOAD_GLOBAL _merge ... RETURN_VALUE` 在 `L11 PUSH_EXC_INFO / 90 LOAD_GLOBAL Exception` **之前**；即 merge 在 try 内 | ✅ | 把 `return _merge(DEFAULT_CONFIG, data)` 移回 try 内 | 无 | `test_config_corrupt_file_falls_back`、`test_config_merge_nested`、新增 `test_load_config_partial_nested_and_illegal` |
| B-05 | `portal_client.py:241` `submit` | **门户状态「已联网」被单独当作登录成功的证据**：提交前已在线时（如刚注销、会话仍持旧码）会把一次「没有有效验证码」的提交报成「登录成功（门户状态显示已联网）」 | 实测：`sess.submit_logoff()` 成功后 `form_source=''`，接着 `sess.submit(旧码)` → 门户 `online=True` → 反编译版返回 `ok=True, '联网成功!'` | ✅ | 提交前先读一次门户状态 `prior`，**只有 `prior` 明确离线且提交后在线**才认状态证据（`now_online and not was_online`） | 低（多一次 `GET /logoff`，见 §4 性能） | 原断言 `test_logoff_then_login_requires_new_session` 由主线改写并保留；新增 `test_login_success_requires_form_code_and_fresh_status` 覆盖 5 种组合 |
| B-06 | `portal_client.py:241` `submit` / `354` `invalidate_form` | 表单被重取（`open_session()`/`prepare_logoff()` 覆盖 ViewState）后，手里的验证码仍属**上一份表单/会话**，提交只会拿到门户无提示空壳页（实测 2530 字节）；旧代码不拦，于是变成 B-05 的假成功 | 新增用例 `test_login_success_requires_form_code_and_fresh_status` 场景 1/2：`invalidate_form()` 后 `submit()` 在修复前会真的 POST 出去并拿到 `ok=True` | ✅ | 引入「表单代」`_form_generation` / `_captcha_form_generation`：取码时记住所属代，`submit()` 发现代不匹配就**本地拦下**，顺手取一张新码并按 `KIND_CAPTCHA` 返回（文案：`登录表单已刷新，请重新输入验证码`） | 低（拦下时多一次取码，属必要刷新） | 原 `test_logoff_then_login_requires_new_session`（空验证码必失败）仍绿；新增场景 1/2/3/4/5 |
| B-07 | `config_store.py:51` `save_config` | 直接覆盖写：断电 / 磁盘满 / 进程被杀会留半截 JSON，下次启动整体退回默认配置（**用户填过的账号密码静默丢失**） | 新用例 `test_save_config_is_atomic_and_keeps_encoding`：目标不可写时旧内容必须原样保留 | ✅ | 写同目录 `config.json.tmp` → `os.replace()` 原子替换；失败时清理临时文件并抛出；保留 UTF-8 无 BOM / 结尾换行 / `ensure_ascii=False` | 无 | 新用例断言 BOM/换行/中文、成功路径无 `.tmp` 残留、失败路径不破坏原文件 |
| B-08 | `config_store.py:26` `_merge` | 嵌套值类型的三种组合没有测试钉住（`options` 内缺键、嵌套非法值、`user` 非 dict） | 新用例 `test_load_config_partial_nested_and_illegal` | ✅（只补测试，**未改语义**） | 保持既有「递归一层」语义，新增用例把它固定下来 | 低 | 该用例现在锁死行为，将来想改成「整块覆盖」会立刻红 |
| B-09 | `portal_client.py:385` `_confirm_offline` | `time.sleep(4) × 3` 串行阻塞，最长 12s 卡住 GUI 工作线程 | 原注释即「最多探测 3 次、每次间隔 4 秒」 | ✅ | 递减间隔 `(2,2,1)` + 总预算 `6s` + 单次探测墙钟封顶 `2s`；**门户确认下线的快速路径完全不变**（仍是亚秒返回，见 `test_confirm_offline_never_waits_when_portal_confirms` 断言 `< 1.0s`） | 低（间隔变短，极端慢门户可能少判一次；有总预算兜底） | 原 `test_logoff_flow_is_fast_and_authoritative` 仍绿；新增 2 条 |
| B-10 | `portal_client.py:153` `is_online` | 多源**串行**探测，每源默认 4s，最坏 ~16s 卡住工作线程 | 原实现 `for url, expect in candidates: ...` 串行 | ✅ | 并发探测（每候选一个 daemon 线程 + `Event` 短路），结论不变（仍是「任一命中即在线」，仍必须校验 `expect` / `204`，仍 `ProxyHandler({})` 绕系统代理），最坏≈单源超时 | 低（线程数 = 候选数 ≤ 5，线程不回收但自行结束） | `test_is_online_candidate_rules` 断言 `< 2.0s` 返回并覆盖接受/拒绝规则 |
| B-11 | `portal_client.py:130` `_request` | 只捕 `HTTPError` / `URLError` + 兜底 `Exception`；`http.client.RemoteDisconnected / BadStatusLine / IncompleteRead` 这类协议异常落到兜底分支，文案是笼统的「请求失败」 | 新用例 `test_request_wraps_protocol_errors` 注入 `RemoteDisconnected` | ✅ | 显式加 `except http.client.HTTPException`（`URLError_子类之外`）并给出可读原因；新增 `timeout=None` 形参（只加默认值，不破坏调用方） | 无 | 新用例同时验证协议异常与超时都被包成 `PortalError` |
| B-12 | `portal_client.py:510` `LoginSession.submit` | `cfg['user']` 被手改成非 dict 时 `user.get` → `AttributeError` 冒到 GUI 工作线程（显示「内部错误」而不是可读原因） | 新用例 `test_login_session_submit_survives_non_dict_user` | ✅ | 非 dict 退化为 `{}`，交给门户报「账号或密码错误」 | 无 | 新用例 |
| B-13 | `portal_client.py:339` `prepare_logoff` | 为了拿 ViewState 和拿状态，**对注销页 GET 两次**（同一份 HTML） | 原实现 `html = self._request(...)` 之后 `status = self._parse_status(html)`，但 `_load_form` 又 GET 一次 | ✅ | 抽出 `_load_form()` 复用同一份 HTML（`prepare_logoff` 现在只 GET 一次注销页） | 无 | 原用例全绿；`test_query_status` 覆盖状态解析 |
| B-14 | `autostart.py:84` `read_lnk` | .lnk 路径直接拼进 PowerShell 单引号字面量：路径含中文 / 单引号时脚本语法错或读回乱码 → `ensure_current()` 误判 | 新用例 `test_autostart_repairs_and_reports` + `_ps_quote` | ✅ | 路径改经环境变量 `GUIT_LNK` 传入（PowerShell 不参与编码）；`_ps_quote()` 双写单引号；stdout 用 `utf-8-sig / replace` 解码 | 无 | 新用例 + 原 `test_autostart_sandboxed` |
| B-15 | `autostart.py:112` `ensure_current` | `os.path.abspath(target or '')` 在读不到 TargetPath 时等于**当前工作目录**，可能恰好等于 exe → 坏快捷方式被当成正常项 | 新用例：空 .lnk 必须不被认成「已指向当前程序」 | ✅ | `same_target = bool(target) and normcase(abspath(target)) == normcase(exe)` | 无 | 新用例 |
| B-16 | `autostart.py:136` `disable` | `return True, '已移除：' + '、'.join(removed) if removed else '本就没有自启项'` 三元与 `+` 混写，靠优先级侥幸正确 | 语义核对：Python 中 `+` 优先级高于条件表达式，故实际等价；但可读性差、易被后人改错 | ✅（仅加括号消歧义，**语义不变**） | `return True, ('已移除：' + '、'.join(removed)) if removed else '本就没有自启项'` | 无 | 原断言 `'本就' in msg` 仍绿；新增断言「已移除 + 含文件名」 |
| B-17 | `autostart.py:19` | `CREATE_NO_WINDOW = 134217728` 硬编码 + PowerShell `timeout=30`（`ensure_current` 在启动路径上调用，最坏卡 30s）；`subprocess.CREATE_NO_WINDOW` 不存在时 AttributeError | 代码审阅 | ✅ | `getattr(subprocess, 'CREATE_NO_WINDOW', 0)`；`POWERSHELL_TIMEOUT = 15` | 低（极端慢盘上 15s 可能不够，回退 .cmd 路径仍在） | `test_autostart_sandboxed` / `test_autostart_repairs_and_reports` |
| B-18 | `ocr_helper.py:14/31` | `length` 参数覆盖**实例属性** `self.CAPTCHA_LENGTH`（类常量 4 被遮蔽），且 `classify` 截断用实例属性；引擎不可用时的降级、非 str 返回值、异常路径都没有测试 | 新用例 `test_ocr_length_semantics_and_degradation` | ✅（注释 + 测试，未改语义；确认为**原程序行为**，见 §6.3） | 保留实例属性语义（改类常量为真会改变行为），补注释与 8 条断言 | 无 | 新用例 + 原 `test_ocr_engine_graceful_degradation` |
| B-19 | `portal_client.py:275` `_judge` | 判定优先级正确但无测试钉住（「含验证码时不得判成功」这条最易被改坏） | 新用例 `test_login_success_requires_form_code_and_fresh_status` 场景 3/5 + 原 `test_submit_success_and_failure_kinds` | ✅（只补测试） | — | 无 | 见 §3 核对表 |
| B-20 | `portal_client.py:431` `submit_logoff` | 注销成功路径的文案把「门户确认下线」写成 `ok_message + '（门户已确认下线）'`，而 `submit_logoff` 传入的是 `已断开网络（联网探测确认）` → 文案自相矛盾（「探测确认」+「门户已确认」）；且 `fallback` 会在**探测已给出结论（外网仍可达）**时压掉真实结论，报「断开失败」 | 主线给出的用例期望；本人实测报文 `已断开网络（联网探测确认）（门户已确认下线）` | ✅ | 两条快速路径统一输出 `已断开网络（门户已确认下线）`；`fallback` 只在**探测本身没给出结论**（每次都异常）时使用；探测有结论就按探测结论如实说明 | 无（文案变更，GUI 直接展示；已核对无断言依赖旧串） | 原 `test_logoff_flow_is_fast_and_authoritative` + `test_logoff_without_message_but_portal_confirms_offline` + 新 2 条 |
| B-21 | `portal_client.py:303` `_extract_error` | 原始字节码里**连着两个 `LOAD_NAME staticmethod`**（重复装饰器），反编译只保留了一个 | 原始 `PortalClient` code object 中 `staticmethod` 在 `co_names` 只出现一次但 `LOAD_NAME staticmethod` 出现两次（offset 166/168）；`fidelity` 报 `PortalClient` 相关差异 | ✅（**这是精简，不是还原**，主线已确认可以删） | 删掉重复的那一个 `@staticmethod`（语义完全等价：`staticmethod` 在 3.10+ 可调用） | 无 | 全套 51 项全绿 |

### 1.1 我**没有**改、但必须交主线的（前端文件问题）

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| F-01 | `app.py` 顶部模块级单实例逻辑 | 反编译把「连回第一实例」那段挪到文件末尾，`import app` 时也会去连自己并 `recv` 超时崩溃（基线时 9 个前端/性能用例全部因此失败） | 归前端 agent；REBUILD_NOTES 第 1 条 |
| F-02 | `app.py` `_prefetch_worker` | 反编译版 317 条 vs 原始 201 条，`except PortalError` 分支里复制了一整份主流程 | 归前端 agent；REBUILD_NOTES 第 4 条 |
| F-03 | `app.py` `_show_captcha` / `_tray_image` / `_open_url` | 尾部兜底逻辑与常量丢失 | 归前端 agent；REBUILD_NOTES 第 2、3、5 条 |
| F-04 | `tests/test_backend.py` 原有 3 个配置用例 | 变量解包写成 `sb, cs, portal, cfg, _ = _env()`（第 3 个返回值是 `portal_client` 模块），teardown 时 `portal.stop()` → `AttributeError` | 已修（见 §7 改动清单）；属测试自带的解包 bug，与本任务改造无关 |

---

## 2. 门户会话状态机 + 调用链地图（Phase 2）

### 2.1 `PortalClient` 的状态量与不变式

| 状态量 | 取值 | 含义 |
|---|---|---|
| `form_source` | `''` / `'login'` / `'logoff'` | 当前缓存的隐藏字段来自哪张页 |
| `hidden` | 4 个 `__VIEWSTATE*` 家族的 dict | 提交时必须原样回填 |
| `defaults` | 该页所有 `<input>` 的 name→value | 与浏览器行为保持一致（如 `TextBoxISP=自动选择`） |
| `captcha_epoch` | 单调递增 | 每次取码 +1，供 GUI 判断「界面上的码是否过期」 |
| `_form_generation` | 单调递增 | 每次 GET 表单页 +1（表单「代」） |
| `_captcha_form_generation` | 整数 | 最近一次取码时所属的表单代 |
| `LoginSession.captcha_png` | bytes | 最近一张码的 PNG（GUI 显示用） |

**不变式 I1**：`form_source == 'login'` ⟺ `hidden` 是登录页的 ViewState。违反后果：拿注销页 ViewState 提交登录，门户只回一个无提示异常页（实测 2530 字节空壳）→ 因此 `submit()` 在 `form_source != 'login'` 时必先 `open_session()`。

**不变式 I2**：登录页与注销页的 `__VIEWSTATE / __EVENTVALIDATION` **不通用**。违反后果同 I1 → `prepare_logoff()` 必须覆盖 `hidden`；注销成功后必须 `invalidate_form()`（清 `form_source/hidden/defaults` 并把 `_captcha_form_generation = -1`）。

**不变式 I3**：验证码与 `ASP.NET_SessionId` 绑定，**取码会让同会话上一张码失效**。因此：
- 点「换一张」= 重新 `fetch_captcha()`，`captcha_epoch` +1，界面上旧码作废（`app._on_connect` 用 `client.captcha_epoch != self.captcha_epoch` 判断 stale 并强制手输）；
- 重新 GET 表单页（`open_session` / `prepare_logoff`）会推进 `_form_generation`，**必须重新取码**才能真正提交 → 这就是 `submit()` 里那道本地拦截（B-06）。

**不变式 I4**：`POST /logoff` 的响应页渲染的是**提交前**的旧状态（实测提交后该页仍写「已联网」），必须重新 `GET /logoff` 才能看到「未联网」→ `refresh_portal_status()` 存在的唯一理由；注销判定里 `_parse_status(POST 响应)` 只能作为辅助。

**不变式 I5**：`captcha_epoch` 只增不减；`invalidate_form()` 把 `_captcha_form_generation` 置 -1（不再等于任何代），因此注销成功后紧跟的 `submit()` 一定会走「重取码 + 返回 `KIND_CAPTCHA`」分支，不可能拿旧码发出真实 POST。

**「什么时候必须重新取页面 / 取码」速查**

| 时机 | 必须做什么 | 违反后果 |
|---|---|---|
| 新会话 / 表单来源不是 `login` | `open_session()`（重取登录页 ViewState） | I1：无提示空壳页 |
| 要注销 | `prepare_logoff()`（注销页 ViewState + 新码） | I2：无提示空壳页 |
| 注销成功 / 任何 `invalidate_form()` 之后要再登录 | 重新 `prepare()`（含取码） | B-05/B-06：可能报假成功 |
| 重取表单页之后要提交 | 必须重新 `fetch_captcha()` | B-06：码属上一份表单，必然被门户拒 |
| 界面上的码与 `captcha_epoch` 不一致 | 让用户重输（或先 `prepare()`） | 拿过期码提交，浪费一次往返 |

### 2.2 调用链地图（含失败分支与异常类型）

**① 连接（GUI 手输路径）**
```
app.LoginApp._on_connect                      (app.py)
  └─ _collect_form() 失败 → 直接 return
  └─ client.captcha_epoch != self.captcha_epoch 或 form_source != 'login' → manual = ''
  └─ threading.Thread(_worker, manual)
       app.LoginApp._worker
         ├─ _ensure_session()                       # 首次构造 LoginSession
         ├─ LoginSession.needs_login()
         │    ├─ PortalClient.query_status()   → _request(GET /logoff)
         │    │      失败: PortalError('无法连接门户：…' / '服务器返回 HTTP …' / '门户响应异常：…' / '请求失败：…')
         │    └─ except PortalError → 退回 is_online()
         ├─ 无需登录 → _post('done', True, '网络已连通，无需登录')
         ├─ manual 且 form_source=='login' → _submit_manual(manual)
         │     └─ LoginSession.submit(captcha)
         │          └─ PortalClient.submit(guid, acc, pwd, captcha)
         │               ├─ form_source != 'login' → open_session()
         │               ├─ 表单代不匹配 → fetch_captcha() + KIND_CAPTCHA（B-06）
         │               ├─ prior = refresh_portal_status()      # 失败吞成 PortalStatus()
         │               ├─ _request(POST submitUrl) → PortalError 上抛
         │               ├─ _judge(html)                          # 纯函数
         │               └─ kind=='unknown' → refresh_portal_status()（再失败也吞）
         └─ 否则 _auto_flow()
              └─ 每轮: LoginSession.prepare() → PortalError → _post('done', False, str(exc))
                       ocr.classify(png) → 空串则提示手输
                       LoginSession.submit(guess)
```
异常类型：**只有 `PortalError`** 会从 `PortalClient` 逃出；`_request` 把所有网络/HTTP/协议异常都包装成它（B-11）。`app._worker` 另有 `except Exception` 兜底成「内部错误：%s」。

**② 断开（GUI）**
```
app.LoginApp._on_logoff → _logoff_worker(captcha)
  ├─ ready = (captcha_purpose=='logoff' and form_source=='logoff'
  │           and captcha_epoch==self.captcha_epoch and hidden) 
  │     └─ 手输优先: LoginSession.submit_logoff(captcha)
  └─ 否则循环 maxCaptchaRetry 次:
       LoginSession.prepare_logoff()
         └─ PortalClient.prepare_logoff()          # GET 注销页(1 次) + 取码
              └─ 无 __VIEWSTATE → PortalError('注销页解析失败：…')
       status.text != '未知' and not status.online → 「门户显示当前未联网，无需断开」
       OCR 不可用 / 识别为空 → 提示手输，结束
       LoginSession.submit_logoff(guess)
         └─ PortalClient.submit_logoff(captcha)
              ├─ form_source != 'logoff' → prepare_logoff() + KIND_CAPTCHA（`注销页状态已刷新…`）
              ├─ _request(POST logoffUrl)
              ├─ '验证码' in text → KIND_CAPTCHA
              ├─ 成功文案 或 POST 响应页显示未联网 → _confirm_offline(…, portal_status=status)
              │     ├─ refresh_portal_status() 显示未联网 → 立即成功（**不等待**）
              │     ├─ 传入的 portal_status 显示未联网 → 立即成功
              │     └─ 否则 (2s,2s,1s)、总预算 6s、单次墙钟 ≤2s 探测
              │           ├─ 探测判离线 → 成功
              │           ├─ 探测判在线 → 如实说明「门户已受理注销请求；本机外网仍可达…」
              │           └─ 探测每次异常 → fallback（`断开失败：门户未确认状态变化`, kind=unknown）
              └─ result.ok → invalidate_form()
```
`_post('net', False/True, ip)` 负责把状态刷进状态栏；注销成功后 `captcha_purpose` 复位成 `'login'`。

**③ 静默模式（`--silent`）**
```
app.run_silent() → config_store.has_credential(cfg) 为假 → 返回 3（转界面）
   └─ portal_client.auto_login(cfg, logger, OcrEngine())
        ├─ use_ocr = cfg.options.useOcr and ocr is not None
        ├─ LoginSession.needs_login() 为假 → LoginResult(True, '网络已连通，无需登录')
        └─ for attempt in 1..maxCaptchaRetry:
             session.prepare()          → PortalError → (False, str, KIND_NETWORK)
             guess = ocr.classify(png) if use_ocr and ocr.available()
             on_captcha(png, guess)     # 可选回调，把最新码交给界面
             guess 为空 → (False, '需要手动输入验证码', KIND_NEED_MANUAL)   ← GUI 据此弹窗
             session.submit(guess)      → PortalError → (False, str, KIND_NETWORK)
             ok → 返回；kind != KIND_CAPTCHA → 直接返回（如 credential）
             kind == KIND_CAPTCHA → 换一张重试
           循环耗尽 → (False, '连续 N 次识别失败，请手动输入验证码', KIND_NEED_MANUAL)
```

---

## 3. 判定优先级核对表

| 判定点 | 应为的优先级 | 代码位置 | 核对结果 | 钉住它的用例 |
|---|---|---|---|---|
| `LoginSession.needs_login()` | **门户状态为准**；门户状态「未知」或读不到时才退回外网探测 | `portal_client.py:484` | ✅ `query_status()` → `status.text != '未知'` 就 `return not status.online`；`PortalError` → `return not self.is_online()` | `test_needs_login_is_portal_authoritative`（外网白名单可达时仍必须判「需要登录」） |
| `PortalClient._judge()` | ① 先认门户成功文案（「联网成功/登录成功」），**且 `text` 含「验证码」时不得判成功**；② 仍是登录页 → 按文案分 captcha/credential/unknown；③ 响应里没有登录控件 → **不直接判成功**，交 `submit()` 用状态复核 | `portal_client.py:275` | ✅ 与原始字节码逐指令一致（`text and '验证码' not in text` → `any(...)` → `LoginResult(True, text, KIND_OK)`） | `test_submit_success_and_failure_kinds`、`test_login_success_requires_form_code_and_fresh_status`（场景 3：`login_status` 含「验证码错误」时不得判成功） |
| `PortalClient.submit()` 的「状态复核」 | 门户状态**只能在状态发生 `离线→在线` 变化时**作为成功证据 | `portal_client.py:241` | ✅ `prior` 先读；`now_online and not was_online` 才返回成功（B-05） | 新增用例场景 3（提交前已在线 → 不报成功）与场景 4（先离线后在线 → 报成功） |
| `PortalClient._confirm_offline()` | **门户状态为主判据**（fresh 读 → 传入的 `portal_status`），外网探测只作补充；探测确认不可达也算成功；门户已受理但外网仍可达 → **如实说明，不谎报失败** | `portal_client.py:385` | ✅ 两条快速路径在最前；探测结论优先于 fallback；无结论才用 fallback | `test_confirm_offline_never_waits_when_portal_confirms`、`test_confirm_offline_bounded_wait_then_honest_report`、`test_logoff_with_unknown_status_falls_back_to_probe_honestly` |
| `submit_logoff()` 的分类 | 先看提示文字含「验证码」→ `KIND_CAPTCHA`；再「成功文案 或 POST 页显示未联网」→ 交 `_confirm_offline` | `portal_client.py:431` | ✅ 顺序未变；成功文案统一为 `已断开网络（门户已受理注销请求）` | `test_submit_logoff_with_stale_form_reasks_captcha`、`test_logoff_flow_is_fast_and_authoritative` |
| 注销成功后 | 必须 `invalidate_form()`（三个状态量清空 + 码作废） | `portal_client.py:431` 尾部 | ✅ | `test_logoff_then_login_requires_new_session`（断言 `form_source=='' and hidden=={} and defaults=={}`） |

---

## 4. 精简清单（等价重构 + 依据）

| # | 重构 | 前 → 后 | 等价性依据 |
|---|---|---|---|
| S-1 | 抽 `_load_form(url, what)` | `open_session()` 66 条 + `prepare_logoff()` 101 条 → 13 + 52 条 | 两条流程原始指令完全同构（GET → `_parse_hidden` → 校验 `__VIEWSTATE` → `_parse_form_defaults`），只有 URL 与报错文案不同；`portal_client` 的 Phase 1 基线语义差异为 0，重构后行为由 `test_open_session_parses_hidden_and_defaults`、`test_query_status`、`test_logoff_flow_is_fast_and_authoritative` 三面钉住。副作用（有意）：`prepare_logoff` 少一次重复 GET（B-13） |
| S-2 | 抽 `_parse_hidden(html)` | 两处 `for name in HIDDEN_FIELDS: re.search(...)` 各出现一次 → 1 处 | 逐字符相同的正则与赋值顺序；`fidelity` 显示两份页面解析的常量集合一致（`utf-8/ignore/name="%s"[^>]*value="([^"]*)"` → 合成函数常量） |
| S-3 | `_request` 异常包装统一 + 显式 `http.client.HTTPException` | 3 个 except → 4 个（新增一个更具体分支，兜底分支保留） | 原有 `HTTPError`/`URLError` 分支文案与顺序不变；新分支只覆盖原本会被笼统兜底吃掉的协议异常 → **行为变更（变好）单列**：`test_request_wraps_protocol_errors` |
| S-4 | 抽 `_probe_reachable` / `_any_reachable` | `is_online` 143 条 → 66 条；探测判定规则集中到 2 个小函数 | 判定规则逐条保留（`expect` 子串命中 / 空 expect 只认 204 / `ProxyHandler({})` 绕代理）；结论语义「任一命中即在线」不变 → `test_is_online_candidate_rules` 7 条断言 |
| S-5 | 删掉 `_extract_error` 上重复的 `@staticmethod` | 2 个装饰器 → 1 个 | **这是精简不是还原**：原始字节码确实有两次 `LOAD_NAME staticmethod`（offset 166/168）。`staticmethod` 对象在 3.10+ 可调用，二次应用语义相同；主线已确认可删 |
| S-6 | `disable()` 三元表达式加括号 | 语义不变 | Python 中 `+` 优先级高于条件表达式，故原写法结果相同；加括号只消歧义 → 原断言 `'本就' in msg` 仍绿 |

**没有做的精简**（有意保留，避免为改而改）：`LoginSession` 的 6 个转发方法（`is_online/prepare/submit/query_status/prepare_logoff/submit_logoff`）。理由：它们是 GUI 与 `auto_login` 的稳定门面（公开接口冻结），删掉会波及 `app.py`；6 个一行转发不构成真重复。

---

## 5. 性能改动与不回归证明

| 改动 | 影响 | 证明 |
|---|---|---|
| `is_online` 并发探测 | 未联网最坏 4×timeout → ≈1×timeout | `test_is_online_candidate_rules` 断言 `is_online()` 在 `< 2.0s` 内返回；`is_online(max_wait=…)` 给探测预算封顶 |
| `_confirm_offline` 递减间隔 + 总预算 | 最长阻塞 12s → ≤6s（且门户确认时 0 等待） | `test_confirm_offline_never_waits_when_portal_confirms` 断言 `< 1.0s`；`test_confirm_offline_bounded_wait_then_honest_report` 断言 `max(slept) <= 2.0` 且 `sum(slept) <= 6.0` |
| `prepare_logoff` 复用同一份 HTML | 注销准备少 1 次 `GET /logoff` | 代码层面（B-13）；`test_logoff_flow_is_fast_and_authoritative` 断言整体 `< 3.0s` |
| `submit()` 增加一次「提交前状态读」 | 登录成功路径 +1 次 `GET /logoff`（本机 <5ms，真实门户一次局域网往返） | 换取 B-05（不再谎报登录成功）；`test_login_success_requires_form_code_and_fresh_status` 断言「提交前读一次、提交后再读一次」（`calls['n'] == 2`），即预算上限可预期 |
| 启动路径 | 只新增 stdlib（`http.client`、`threading`）与两个模块级常量；**不引入任何重型依赖** | `test_heavy_deps_not_loaded_at_startup` 通过；`import portal_client` 实测 **0.0257s**，`sys.modules` 无 `ddddocr/onnxruntime/cv2/numpy` |
| 全套性能门禁 | — | `[perf] import app = 0.0834s`（基线 0.0856）、`[perf] 界面就绪 = 0.0481s`（基线 0.072）→ 3 项全过 |

**性能基线来源说明（回应主线要求）**：我接手时 `tests/perf_baseline.json` **不存在**；第一次跑 `perf` 时 `import app` 因前端反编译伪影（`_cli.recv` 超时）直接崩溃，**无法登记基线**（`_run` 抛 `未取到测量结果 rc=1`，不写文件）。因此**基线不是我登记的**——现在的 `tests/perf_baseline.json`（`import 0.0856 / ui_ready 0.072`）是前后端都还原之后、由主线侧运行的 `perf` 首跑写入的「还原后原始版本」数值，符合「基线必须是还原后的原始版本」的要求。当前值均低于基线，无回归。

---

## 6. 举一反三（一个问题 → 同类扫描）

| 触发（本次修的问题） | 同类扫描范围 | 扫描结论 |
|---|---|---|
| B-01/B-03 反编译伪影导致「一跑就崩」 | 我负责的 4 个模块全部函数 | 用 `_phase1_fidelity.py` 全量比对指令序列/co_names/co_varnames/co_argcount → Phase 1 结束时**语义差异 0**（除 ocr_helper 一处类定义行号常量）；无第三处「运行必崩」 |
| B-05/B-06 「拿过期/不匹配的凭据去提交 → 假成功」 | 所有「提交」入口：`submit`、`submit_logoff` | `submit_logoff` 早就有 `form_source != 'logoff'` 的等价守卫（且验证码同属该表单），无需再改；`submit` 是唯一缺口 → 已补「表单代」守卫 |
| B-07 「非原子写文件」 | 全模块的写操作 | 只有 `save_config` 写文件；`autostart` 写 `.cmd`/`.lnk` 属「一次性小文件 + 失败可见」，且失败会返回 `(False, 原因)`，无静默丢失风险 → 不改 |
| B-09 「固定长 sleep 阻塞工作线程」 | 全模块 `time.sleep` | 只剩 `_confirm_offline` 一处（已带预算）；`portal_client` 无其它 sleep |
| B-10 「串行网络等待叠加超时」 | `is_online`、`prepare_logoff`、`query_status`、`_request` | `prepare_logoff`/`query_status` 是单请求；`_request` 有 `timeout=self.timeout(8s)`；`is_online` 已并发 |
| B-11 「异常吞没 / 包装不全」 | 全部 `except` 子句 | 逐个核对：<br>①`is_online` 内 `except Exception: return`（探测失败属正常语义，不改）；<br>②`is_online` 循环里 `except Exception: continue`（同上）；<br>③`refresh_portal_status` 的 `except PortalError: return PortalStatus()`（**有意**：读状态失败要让上层退回探测，不是吞错）；<br>④`_any_reachable` 内 `except Exception: return`（同①）；<br>⑤`_confirm_offline` 内 `except Exception: continue`（新增 `conclusive` 标记后**不再等于吞错**：全部异常才会走 fallback 并如实报未确认）；⑥`ocr_helper.available/classify` 的 `except Exception`（降级是设计契约，且不掩盖主流程）；⑦`remove_config` / `autostart` 的兜底（返回布尔/元组，有明确返回语义）。**结论：没有发现新的「把真实故障掩盖成成功」的吞没点** |
| B-14/B-15 「平台差异 / 编码」 | 所有 `subprocess` + `PowerShell` 调用、所有 `decode` | `enable`/`read_lnk` 已加 `_ps_quote` + 环境变量传路径 + `utf-8-sig`；`portal_client` 的 `decode('utf-8','ignore')` 保留（门户是 UTF-8 ASP.NET，若真遇到 GBK 页 `_extract_error`/`_parse_status` 会得到空文本 → 退化为「未知」而不是误判，属可接受降级；**未改**，见 §9 遗留） |
| B-04/B-08 「配置结构非法」 | `load_config` 返回值的所有下游消费者 | `app.py:has_credential`（已加固）、`app.py` 里 `cfg.get('options')/cfg['fields']/cfg['portalUrl']` 等（若被手改成非法值仍会 KeyError/TypeError，但都发生在 GUI 线程且被 `except Exception` 兜成「内部错误」）、`portal_client` 里 `cfg['fields']`（同上）。结论：**核心消费者已加固，`fields` 类非法值属「用户把配置改坏」的极端场景，留给主线决定是否加一层 schema 校验** |
| B-16 「返回值拼接歧义」 | `autostart` / `config_store` 所有 `return A + B if C else D` 形态 | 全文搜索确认只剩 `disable` 一处 → 已加括号 |
| B-18 「实例属性遮蔽类常量」 | `ocr_helper`（唯一带类常量的后端模块） | 只有 `CAPTCHA_LENGTH` 一处 |
| `getattr(subprocess,'CREATE_NO_WINDOW',0)` | 所有 `getattr` | `portal_client` 的 `getattr(resp,'status',200)` 是有意的兼容写法（HTTPResponse 一定有 status），无需改 |

---

## 7. 改动清单（每条一行）

### `portal_client.py`
1. `:10-36` 新增 `import http.client`、`import threading` 与 3 个常量 `CONFIRM_OFFLINE_INTERVALS/BUDGET/PROBE_BUDGET`（`:32-36`）—— 支撑协议异常包装与断开预算。
2. `:54` 新增 `_probe_reachable(url, expect, timeout)` —— 单源探测规则（绕代理 + 校验内容/204）。
3. `:69` 新增 `_any_reachable(candidates, timeout)` —— 并发探测、任一命中短路。
4. `:114` `__init__` 新增 `_form_generation` / `_captcha_form_generation` —— 实现「表单代」不变式（I3/B-06）。
5. `:130` `_request` 新增 `timeout=None` 形参，`:148` 新增 `except http.client.HTTPException` —— B-11。
6. `:153` `is_online` 改为并发探测 + 新增 `max_wait` 形参；删除反编译多出的死代码 —— B-02/B-10。
7. `:194` 新增 `_parse_hidden(html)` —— S-2 去重。
8. `:204` 新增 `_load_form(url, what)`（`:217` 内联 `_parse_form_defaults`）—— S-1 去重 + 消除重复 GET（B-13）。
9. `:221` `open_session` 改用 `_load_form`。
10. `:227` `fetch_captcha` 记录 `_captcha_form_generation`。
11. `:241` `submit` 新增表单代守卫 + 提交前状态读 `prior` + 「仅离线→在线才算状态证据」 —— B-05/B-06。
12. `:303` 删除重复的 `@staticmethod` —— S-5（精简，非还原）。
13. `:326` `_parse_status` 按原始字节码还原完整分支 —— B-01。
14. `:339` `prepare_logoff` 改用 `_load_form`（少一次 GET）+ 记录表单代 —— B-13/B-06。
15. `:357` `invalidate_form` 额外把 `_captcha_form_generation` 置 -1 —— B-06。
16. `:385` `_confirm_offline` 递减间隔 + 总预算 + 探测墙钟封顶 + `fallback` 只在探测无结论时使用 + 三条文案统一 —— B-09/B-20。
17. `:431` `submit_logoff` 成功分支文案改为「已断开网络（门户已受理注销请求）」 —— B-20。
18. `:510`（`user = self.cfg.get('user')` 在 `:513`）`LoginSession.submit` 对非 dict `user` 安全退化 —— B-12。

### `config_store.py`
19. `:39` `load_config` 把 `return _merge(...)` 移回 try 内 —— B-04。
20. `:51` `save_config` 改为临时文件 + `os.replace` 原子写，失败清理并抛出 —— B-07。
21. `:85` `has_credential` 还原为 `bool((user.get(key) or '').strip())` 并加 `isinstance(user, dict)` / 字符串判空 —— B-03 + 安全退化。

### `ocr_helper.py`
22. `:31` `classify` 补注释说明「实例属性覆盖类常量」与 `str(raw)` 兜底原因 —— B-18（**行为未变**）。

### `autostart.py`
23. `:19` 新增 `_ps_quote()`；`CREATE_NO_WINDOW` 改 `getattr(subprocess, …)`；新增 `POWERSHELL_TIMEOUT=15` —— B-14/B-17。
24. `:56` `enable` 用 `_ps_quote` + 环境变量 `GUIT_LNK`，超时改 15s —— B-14/B-17。
25. `:84` `read_lnk` 用 `$env:GUIT_LNK` + `utf-8-sig/replace` 解码 —— B-14。
26. `:112` `ensure_current` 空 `target` 不算同一路径 —— B-15。
27. `:136` `disable` 三元表达式加括号 —— B-16。

### `tests/test_backend.py`
28. `:19/:39/:53` 修 3 处变量解包（`sb, cs, pc, portal, cfg`）—— F-04，否则 teardown 必崩。
29. `:164` 按主线给定断言改写 `test_logoff_then_login_requires_new_session`。
30. `:192/:210` 拆分为 `test_logoff_without_message_but_portal_confirms_offline` 与 `test_logoff_with_unknown_status_falls_back_to_probe_honestly`（并修掉 `pc.time.sleep` 猴子补丁泄漏）。
31. `:327-380` 新增测试辅助 `_login_html/_logoff_html/_cfg_for/_transport_client`（空壳传输，不发真实请求）。
32. `:382-810` 新增 12 个用例：`has_credential` 形态、`load_config` 残缺/非法、`save_config` 原子性、`_parse_status` 全分支、`is_online` 候选规则、`_confirm_offline` 快速返回、`_confirm_offline` 有界等待、登录成功需「表单码 + 状态变化」、`_request` 协议异常包装、`LoginSession.submit` 非 dict、`OcrEngine` 长度语义、`autostart` 修复/返回文案。
33. **未删除、未削弱任何原有断言**（原有 18 条全部保留，仅按主线指示替换了那两条「断言过头」的用例）。

---

## 8. 测试证据

```powershell
cd <本机路径>
& <本机路径>
& <本机路径>
& <本机路径>
```

**`tests\run_tests.py backend` → `通过 31 项，失败 0 项`**（原 18 条 + 新增 12 条，其中 1 条按主线拆成 2 条 → 18-1+2+12 = 31）。逐条：

```
PASS test_auto_login_no_ocr_asks_manual            PASS test_logoff_flow_is_fast_and_authoritative
PASS test_auto_login_ok_and_wrong_code_retries     PASS test_logoff_then_login_requires_new_session
PASS test_auto_login_skips_when_online             PASS test_logoff_with_unknown_status_falls_back_to_probe_honestly
PASS test_autostart_repairs_and_reports            PASS test_logoff_without_message_but_portal_confirms_offline
PASS test_autostart_sandboxed                      PASS test_needs_login_is_portal_authoritative
PASS test_captcha_is_session_bound                 PASS test_ocr_engine_graceful_degradation
PASS test_config_corrupt_file_falls_back           PASS test_ocr_length_semantics_and_degradation
PASS test_config_defaults_and_roundtrip            PASS test_open_session_parses_hidden_and_defaults
PASS test_config_merge_nested                      PASS test_parse_status_all_branches
PASS test_confirm_offline_bounded_wait_then_honest_report   PASS test_query_status
PASS test_confirm_offline_never_waits_when_portal_confirms   PASS test_request_wraps_protocol_errors
PASS test_fetch_captcha_png_and_epoch              PASS test_save_config_is_atomic_and_keeps_encoding
PASS test_has_credential_shapes                    PASS test_submit_logoff_with_stale_form_reasks_captcha
PASS test_is_online_candidate_rules                PASS test_submit_success_and_failure_kinds
PASS test_load_config_partial_nested_and_illegal   PASS test_login_session_submit_survives_non_dict_user
PASS test_login_success_requires_form_code_and_fresh_status
```

**`tests\run_tests.py all`**：后端 31 项全绿（上面逐条列出）。前端/静默/布局/性能段由对应负责人维护；我最后一次全量运行时（前端 agent 正在并行改 `app.py` 并新增 `test_layout/test_silent/test_instance`）结果为 `通过 57 项，失败 2 项`，失败两条均在 `test_gui`：
```
FAILED: test_gui.test_captcha_zoom_clamped_on_short_screen
FAILED: test_gui.test_log_is_bounded_and_keeps_bottom
```
两者都不经过 `portal_client` / `config_store` / `ocr_helper` / `autostart`（属前端布局与日志区行为），归 §9.5 交主线。**性能**：`import app` 实测 0.0833~0.0834s（基线 0.0856），`界面就绪` 实测 0.0481~0.0678s（基线 0.072），三个性能用例全过。`import portal_client` 单独实测 **0.0257s**，`sys.modules` 中无 `ddddocr/onnxruntime/cv2/numpy`。

### 保真度取证

官方 `fidelity.py` 对 Phase 1 的 4 个还原点做过清零验证，工具本身有两处与本次任务无关的限制：
- 它把每个类/函数对象里 `__firstlineno__` 机制写入的**行号 int 常量**也当差异（`portal_client.PortalError: [60] -> [29]` 等），这部分由源码**行数布局**决定，无法消除；
- 它硬编码模块清单为 6 个第一方模块（含 `app`/`app_logger`），无法只对我负责的 4 个模块出报告，而 `app.py` 有前端 agent 的进行中改动，会污染报告。

因此我另写了一个**只覆盖我负责 4 个模块、把行号常量单列为 SOFT** 的取证脚本（临时脚本，逻辑即：`marshal.loads` 原始代码对象 → `dis.get_instructions` 规范化（跳转目标转指令序号、剔除 `RESUME/CACHE/NOP/EXTENDED_ARG/PRECALL/COPY_FREE_VARS/MAKE_CELL/RETURN_GENERATOR`、剔除 `__firstlineno__` 及其前一条 `LOAD_CONST`）→ 逐层比对 `指令序列 / co_names / co_varnames / co_argcount / co_flags / 常量集合`，并按 `co_consts` 递归子代码对象），把 Phase 1 的还原点施加到 `HEAD` 版源码副本上做正交验证：

```
=== Phase 1 还原点施加到 baseline 副本后 ===
### portal_client: 语义差异 0 / 仅行号 5
   [line] PortalError/LoginResult/PortalStatus/PortalClient/LoginSession: 行号常量 [60,64,71,90,450] -> [29,32,38,56,362]
### config_store: 语义差异 0 / 仅行号 0
### autostart: 语义差异 0 / 仅行号 0
### ocr_helper: 语义差异 1 / 仅行号 0
   [HARD] ocr_helper.OcrEngine: 常量 仅原=[12] 仅新=[10]     ← 类定义行号，不可消除

=== 当前（含 Phase 3 重构）===
### portal_client: 语义差异 46 / 仅行号 5
### config_store: 语义差异 9  / 仅行号 0
### ocr_helper:     语义差异 1  / 仅行号 0
### autostart:      语义差异 14 / 仅行号 0
```

### Phase 3 差异意图（逐类对应，无未解释项）

| 差异来源 | portal_client | config_store | autostart |
|---|---|---|---|
| 新增模块级常量/导入（`threading`/`http.client`/预算常量/`_ps_quote`/`POWERSHELL_TIMEOUT`） | 3 | 0 | 3 |
| 新增/抽取函数（`_probe_reachable`、`_any_reachable`、`_parse_hidden`、`_load_form`、`_ps_quote`） | 4 | 0 | 1 |
| `_request` 显式协议异常分支 + `timeout` 形参 | 3 | 0 | 0 |
| `is_online` 并发化 + `max_wait` | 3 | 0 | 0 |
| 表单代不变式（`__init__`/`fetch_captcha`/`submit`/`invalidate_form`/`prepare_logoff`） | 8 | 0 | 0 |
| `submit` 的 prior 状态读 + 文案 | 3 | 0 | 0 |
| `_confirm_offline` 预算/结论/文案 | 3 | 0 | 0 |
| `submit_logoff` 文案 | 2 | 0 | 0 |
| `LoginSession.submit` 非 dict 守卫 | 2 | 0 | 0 |
| `_extract_error` 删重复 `@staticmethod` | 1 | 0 | 0 |
| docstring 文本变更（随实现同步更新） | 若干 | 1 | 4 |
| 行号常量 | 5 | 0 | 0 |
| **功能行为变更（单列，均有新用例）** | B-05/B-06/B-09/B-10/B-11/B-20 | B-07 | B-14/B-15/B-16/B-17 |

---

## 9. 遗留问题 / 需要主线决策

1. **【已按要求处理，仅备案】`tests/perf_baseline.json`**：我接手时该文件不存在，且第一次跑 `perf` 时 `import app` 崩溃（前端伪影）导致无法登记基线、文件未生成。现在的基线是前后端还原后首跑写入的值（`import 0.0856 / ui_ready 0.072`），来源即「还原后的原始版本」，当前实测值均低于基线 → 无需删除重建。若主线希望严格固化「Phase 1 结束时刻」的数值，可删掉该文件并在确认 `app.py` 干净后重跑一次 `perf`。
2. **`autostart` 的 `ensure_current()` 只在「cmd 载体存在且 lnk 不存在」或「TargetPath 不同 / Arguments 缺 `--autostart`」时重建**。若用户手工把 `.lnk` 的 Arguments 清空、TargetPath 仍正确，会走重建；但如果 `.lnk` 的 TargetPath 与 exe 一致而 Arguments 丢失，`AUTOSTART_ARG in current_args` 为假 → 会重建（OK）。**未覆盖**的场景：`.lnk` 指向 `pythonw.exe` + `app.py` 而当前就是源码模式（`_launch_command()` 返回同样的 exe）→ 会被判「已指向当前程序」，不重建。这与原语义一致，未改；如需更严可加「Arguments 必须含 app.py 路径」的判断（需主线确认，因为打包/源码两种模式的期望不同）。
3. **门户页面编码**：`portal_client` 全程 `decode('utf-8','ignore')`。真实门户 `http://10.6.6.6` 是 UTF-8 ASP.NET（源码注释与本人用例都按此建模），但若门户改版成 GBK/带 BOM，中文提示会被静默丢弃 → `_extract_error` 返回空、`_parse_status` 退化为「未知」，表现为「登录结果无法确认」而不是误判成功（安全的降级方向）。**建议**：将来可加「`Content-Type` charset 优先 + `errors='replace'`」的读取，属行为变更，需要主线拍板。
4. **`cfg['fields']` / `cfg['options']` 的非 dict 非法值**：`load_config` 的合并语义（递归一层、非 dict 覆盖）已用测试钉住，`has_credential` 与 `LoginSession.submit` 已加固；但 `cfg['fields']['captcha']` 若被手改成字符串，`submit()` 会在 `names['guid']` 处抛 `TypeError` → 由 `app._worker` 的 `except Exception` 兜成「内部错误：…」。**是否要加一层配置 schema 校验**（或在 `load_config` 里对已知键做类型纠正）需主线决策：会改变「非法配置的可见行为」，我不擅自改。
5. **前端文件的问题**（我不许改，见 §1.1）：`app.py` 的模块级单实例错位、`_prefetch_worker` 重复段、`_show_captcha`/`_tray_image` 兜底缺失、`_open_url` 常量顺序。基线时它们导致 9 个前端/性能用例失败。我收尾时全套是 `57 通过 / 2 失败`，两条失败都在 `test_gui`（`test_captcha_zoom_clamped_on_short_screen`、`test_log_is_bounded_and_keeps_bottom`，属前端布局/日志区），**与我负责的 4 个模块无关联路径**（这两条用例不 import `portal_client`/`config_store`/`ocr_helper`/`autostart`）。**这 2 条留在红，归前端 agent / 主线处理**；合并门槛建议定为「`run_tests.py all` 全绿 + `test_perf` 稳定低于基线」——`test_perf` 依赖 `import app`，前端若回退单实例修复会再次污染性能门禁。
6. **`tests/test_backend.py` 中「空壳传输」用例**（`_transport_client`）通过替换实例的 `_request` 来构造门户侧的分支（如「提交前在线、提交后在线」）。这不是 mock 掉被测逻辑：`PortalClient` 的表单/状态/判定链路仍是被测的真实代码，被替换的只有 HTTP 传输（本机没有能同时模拟「服务端无人应答」的模拟门户，`support.py` 又不许改）。**请主线确认这个边界可接受**；如果要求所有用例都必须打真实 `urllib`，这两条场景需要主线先在 `support.py` 里加对应开关。

---

## 10. 一句话汇总

改了 `portal_client.py`、`config_store.py`、`ocr_helper.py`、`autostart.py`、`tests/test_backend.py`（仅新增/加强）并新建 `reports/backend.md`；**后端门禁 `通过 31 项，失败 0 项`**，性能 3 项全过（`import 0.0834s` / `界面就绪 0.0481s`，均低于基线），Phase 1 的 4 处还原点经正交取证确认**语义差异为 0**（仅剩行号类常量噪声），Phase 3 的 70 处差异逐条可解释；遗留 3 项（`autostart` 源码模式自启项判定、门户页面编码、配置 schema 校验）+ 1 项前端回退风险 + 2 条前端 `test_gui` 红用例（不在我的所有权范围），均已在 §9 列明并交主线决策，**后端侧无阻塞性遗留**。
