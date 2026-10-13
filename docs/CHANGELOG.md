# 变更记录（CHANGELOG）

格式：`YYYY-MM-DD HH:mm | 操作 | 影响文件 | 验证结果 | 回滚点`

## 2026-10-13 Python lite 体积优化方案补充

- 改动：新增 `docs/20261013-lite-python-optimization-plan.md`，规划不更换 Python + tkinter + PyInstaller 的 lite 优化；分 L0 基线、L1 去 Pillow/pystray、L2 精简隐式内容、L3 风险选项。
- 目标：优先评估 Tkinter 原生 `PhotoImage` 替代 Pillow 验证码显示，隐藏按钮改为最小化；full 保持 Pillow、pystray、托盘与图标。lite 目标约 10–15 MiB，仅为工程目标，不承诺“几 MB”。
- 范围：仅新增方案文档，未修改源码、构建脚本、依赖和产物；未删除全局 requirements.txt 中 full 所需依赖。
- 验证：文档静态编码与 `git diff --check` 见本次会话结果；未构建、未运行 OCR/GUI、未进行动态体积测量。
- 回滚：本次仅新增方案文档和记录，保留工作区已有 agent 改动。

## 2026-10-13 执行交接手册补充

- 改动：新增 `docs/20261013-size-reduction-agent-handoff.md`，将体积压缩方案细化为阶段 A 的审查、备份、隔离基线、静态检查、动态审批、验收与报告步骤，附可复制 agent 指令。
- 现状：方案和构建文件存在其他 agent 的更新；保留原文件及其验收记录，本次未修改候选代码、模型或原方案。
- 审查提醒：上游 hook 版权与许可、TOC/PYZ 完整解析、FFmpeg 匹配范围、检查脚本退出码、隔离构建解释器路径均列入接手核对项，未宣称最新实现已完成或仍存在这些问题。
- 检查命令：`git diff --check`；`file docs/20261013-size-reduction-agent-handoff.md`；`iconv -f UTF-8 -t UTF-8 docs/20261013-size-reduction-agent-handoff.md >/dev/null`。结果见本次交付记录；仅做文档静态检查，未运行项目、构建、OCR 或 GUI。
- 回滚：本次仅新增交接文档与此条记录；如需撤销，仅撤销本次内容，保留他人并发修改。


| 时间 | 操作 | 影响文件 | 验证结果 | 回滚点 |
| --- | --- | --- | --- | --- |
| 2026-10-13 12:14 | 由 `_TEMPLATE` 复制生成初始骨架，补建 `config\`、`logs\` | 全部 | 目录结构已核对 | 无（新建，可直接删目录） |
| 2026-10-13 12:16 | 编写 `docs\PLAN.md`（需求澄清 6 项、现状核对 6 条事实、选型 9 候选评估、步骤 9 步、风险 5 项、静态验收 5 条） | `docs\PLAN.md` | 待用户确认方案 | 无（文件为纯新增） |
| 2026-10-13 12:17 | 编写 `README.md`（占位，待实现后补运行方式） | `README.md` | 未验证 | 无（文件为纯新增） |

## 2026-10-13 19:25 收紧成功判定：禁用「外网可达」确认登录成功 + 登录/注销表单来源互斥守卫

**问题**（代码评审提出，逐条核实成立）

1. `submit()` 在门户结果不明确（`KIND_UNKNOWN`）时调用 `is_online()` 确认成功 ——
   但本项目已实测：**未认证时外网探测照样可达**（放行白名单），据此确认会把失败报成成功。
2. `_judge()` 在响应**不含登录控件**时直接判成功 —— 门户改版、维护页、错误页都长这样。
3. 成功文案里含泛化的「成功」——异常文案也可能命中。
4. `submit()` **缺少表单来源守卫**：注销成功后 `client.hidden` 仍来自注销页，
   而 GUI 只检查「hidden 非空」（`app.py` 手输分支），下一次连接可能拿注销页的
   ViewState 提交登录 —— 与 `submit_logoff` 已有的守卫不对称。

**修复**

| # | 位置 | 改动 |
| --- | --- | --- |
| 1 | `portal_client.py` `submit()` | `KIND_UNKNOWN` 时改为 `refresh_portal_status()` 复核：**门户状态显示在线才算成功**；彻底删除 `is_online()` 作为成功依据；无法确认时返回「登录结果无法确认」（不再报成功） |
| 2 | `portal_client.py` `_judge()` | 不含登录控件 → 返回 `KIND_UNKNOWN`（交由 `submit()` 用门户状态复核），不再直接判成功 |
| 3 | `portal_client.py` 常量 | 分组收窄：`LOGIN_SUCCESS_WORDS = ("联网成功", "登录成功")`、`LOGOFF_SUCCESS_WORDS = ("断开成功", "注销成功")`，删除泛化「成功」 |
| 4 | `portal_client.py` | `submit()` 开头加来源守卫（`form_source != "login"` → 重新 `open_session()`，与 `submit_logoff` 对称）；新增 `invalidate_form()`，`submit_logoff()` 成功后清空 `hidden`/`defaults`/`form_source` |
| 4b | `app.py` | `_on_connect` 的手输判定加「表单必须来自登录页」条件；`_worker` 的手输分支由「hidden 非空」改为 `form_source == "login"` |

**验证**（桩测试 13/13 通过，全程不接触真实门户）

| 检查 | 结果 |
| --- | --- |
| `_judge` 成功文案 `联网成功!` | ok=True |
| `_judge` 验证码错误 / 账号密码错误 | `captcha` / `credential` |
| `_judge` 异常页（无登录控件） | `(False, unknown)` —— 不再直接成功 |
| `_judge` 泛化「操作成功完成」 | `(False, unknown)` —— 不再算成功 |
| **submit**：门户未联网 + 外网可达=True | **ok=False**（旧实现会报成功） |
| **submit**：门户显示已联网 | ok=True（消息：登录成功（门户状态显示已联网）） |
| **来源守卫**：表单来自注销页时提交登录 | 先 `GET /login` 重新取页面，再 `POST /login`，`form_source` 复位为 `login` |
| **注销后清理** | `form_source=''`、`hidden={}` |
| 真实回归（真凭据登录） | `ok=True message=联网成功!`（成功文案直命中） |
| 真实回归（注销链路错码） | `ok=False kind=captcha 验证码错误!` |
| 真实回归（门户已联网时 `auto_login`） | `门户显示已联网，无需登录` |

**影响文件**：`src\portal_client.py`、`src\app.py`

**回滚点**：`temp\output\backup-20261013\`

## 2026-10-13 19:10 断开网络改为自动识别验证码；开机自启改为「打开软件 + 自动连接」

**需求**（用户反馈：连接与断开都已成功，剩下两点体验问题）

1. 「断开网络」还要手动输验证码 → 希望像连接一样自动识别；
2. 「开机自动登录」要**开机自动打开软件、自动连接**。

**改动**

1. `src\app.py` `_logoff_worker` 重写为两条路径：
   - 手输优先：界面上的注销码仍有效且用户填了值 → 直接提交；
   - **自动**：取注销页 + 取码 → OCR → 提交；验证码错就换码重试（上限 `maxCaptchaRetry`），
     连续失败或 OCR 不可用（lite 构建）才提示手输。
   判定是否已断开一律以**门户状态**为准（注销页 span 对本机 IP 判定准确）。
2. 新增 `--autostart`：正常打开界面，并在网络就绪后自动连接
   （`_auto_connect_step`：最多 3 次、间隔 12 秒；成功判据 = 门户状态，而不是外网可达）。
   开机瞬间网卡/DHCP 常未就绪，故做重试。
3. `src\autostart.py`：
   - 自启参数由 `--silent`（只登录、不显示界面）改为 `--autostart`；
   - 新增 `read_lnk()` 与 `ensure_current()`：程序启动时自动把自启项校正为指向
     **当前正在运行的这个程序**——自愈历史上指向 `pythonw.exe src\app.py` 的旧快捷方式
     （源码模式配置目录没有 config.json，开机只会弹一个空窗口）。

**验证**（全部用桩：未做真实注销、未真实提交登录、未改动真实自启项）

| 检查 | 结果 |
| --- | --- |
| 点一次「断开网络」（`submit_logoff` 用桩） | `验证码识别为 gyec，正在断开…` → `✔ 已断开网络（门户已确认下线·桩）`；提交 1 次，**无需手输** |
| `--autostart` 启动（`query_status` 桩=未联网、`submit` 用桩） | `开机自动登录：正在连接（第 1/3 次）` → `✔ 联网成功!（桩）`；门户仍显示未联网时按 12 秒间隔继续重试 |
| 单 root 单独进程复测 | 验证码图片正常显示，无「验证码显示失败」 |
| 三个模块语法 | `py_compile src\app.py src\portal_client.py src\autostart.py` 通过 |

**影响文件**：`src\app.py`、`src\autostart.py`

**回滚点**：`temp\output\backup-20261013\`（`app.py`、`portal_client.py`、`autostart.py`、`config.json`、`CHANGELOG.md`、旧 exe）

## 2026-10-13 19:40 登录前判断改以门户状态为准（修复「点连接一直连不上」的真正原因）

**问题**（用户实测：软件里点「连接」始终连不上，只能去网页门户登录）

实测发现：**门户显示「未联网」时，本机外网探测依旧全都可达**
（`http://www.msftconnecttest.com/...` 200、`http://www.gstatic.com/generate_204` 204、
`http://www.baidu.com` 200）——这些目标显然是未认证状态下的放行白名单。

旧逻辑用「外网是否可达」判断是否需要登录，于是软件直接回
**「网络已连通，无需登录」并结束——根本没有提交登录**，门户侧始终未认证。
证据（实测）：

| 场景 | 结果 |
| --- | --- |
| 门户 `未联网` + 外网可达 True → `auto_login()` | 返回 `网络已连通，无需登录`，门户状态**保持未联网** |
| 同上 → 打包版 `GUIT-net-login-full.exe --silent` | 退出码 **0**（自称成功），门户**仍未联网** |
| 同上 → 直接调用 `POST /login` | 返回 `联网成功!`，门户转为**已联网** |

**修复**

新增 `LoginSession.needs_login()`：**以门户状态为准**（`GET /logoff` 的
`MainContent_LabelOnline`），门户状态未知时才退回外网探测。并让三处调用点全部改用它：

1. `portal_client.auto_login()`（`--silent` 走这条）；
2. `app.py` `_worker()`（GUI 点「连接」）；
3. `app.py` `_prefetch_worker()`（启动预取的提示文案）。

**验证**

| 检查 | 结果 |
| --- | --- |
| 实况（门户已联网） | `needs_login=False`（正确跳过登录） |
| 桩：门户 `未联网` | `needs_login=True`（未认证时必须去登录） |
| 桩：门户 `已联网` | `needs_login=False` |
| 桩：门户状态未知 | `needs_login=False`（退回外网探测，外网可达） |
| **关键回归**：门户 `未联网` 桩下跑 `auto_login()` | **真的提交登录** → `ok=True message=联网成功!`（不再短路） |
| 语法 | `py_compile src\portal_client.py src\app.py` 通过 |

**影响文件**：`src\portal_client.py`、`src\app.py`

**说明**：本次验证全程只读门户状态 + 桩函数模拟，**没有再做真实注销**（用户明确要求停止）。

## 2026-10-13 19:05 接口失败根因修复（连接误报失败、断开误报失败、在线状态误判）

**问题**（用户实测：点「连接」一直失败、点「断开网络」一直失败）

用真实凭据对门户逐接口实测后定位到 5 个判定缺陷（完整证据见 `docs\DIAGNOSIS-20261013.md`）：

1. **登录成功被判失败**：本门户登录成功后**仍然渲染登录页样式**（含验证码框与登录按钮），
   只在 `validation-summary` 里写 `联网成功!`。旧 `_judge()` 只判「是否仍是登录页」，
   把真实成功降级为 `KIND_UNKNOWN`，只能靠外网探测兜底；兜底一慢就弹
   `登录失败：联网成功!`。
2. **注销前 ViewState 被覆盖**：`prepare()`（启动预取 / 点「换一张」）会把 `hidden`
   换成登录页的 ViewState；此时点「断开网络」拿它去 POST `/logoff`，门户只回
   **2530 字节无提示空壳页**，程序报 `断开失败：门户未确认状态变化`。
3. **验证码取新即作废**：同会话取新码会让上一张立即失效（实测），界面预取的码
   可能在点击时已过期 → 必然回 `验证码错误!`。
4. **在线探测单源脆弱**：`https://www.msftconnecttest.com/...` 与
   `https://connectivitycheck.gstatic.com/...` 在本网络 **TLS 被阻断**（curl 000），
   单源探测把「已联网」判成离线。
5. **断开判据用错**：旧逻辑用「外网是否可达」判断开。实测本机注销后门户状态已变
   「未联网」，但外网依旧可达（出口另有旁路通道），于是永远判不出断开、报
   「生效略有延迟」；状态栏同样显示错误的在线状态。

**修复**（`src\portal_client.py`、`src\app.py`）

1. `_judge()` 先认门户成功文案（`SUCCESS_WORDS`，实测登录成功 = `联网成功!`），再判页面。
2. 隐藏字段带来源标记 `form_source`（`login` / `logoff`）；`submit_logoff()` 发现来源
   不是 `logoff` 时先刷新注销页并返回 `KIND_CAPTCHA`，界面提示重新输码。
3. 新增 `captcha_epoch`（每取一次码 +1）；界面记录当前展示的码属于哪个 epoch，
   提交前若已过期则放弃手输值、自动重新取码 + OCR（`app.py` `_on_connect` / `_logoff_worker`）。
4. `is_online()` 改为**多源降级**（HTTP connecttest → gstatic 204 → baidu），任一命中即在线；
   配置里 `onlineProbe.url` 仍作首选。
5. 新增 `refresh_portal_status()`：注销后**重新 GET `/logoff`** 读门户状态
   （POST 响应页里是提交前的旧值）；`_confirm_offline()` 改为门户状态优先，外网探测仅作补充；
   GUI 状态栏与「断开前是否已离线」同样以门户状态为准。
   —— 本节同时**推翻** 18:15 的「只用 HTTPS 单源」决定：单源 HTTPS 在本网络不可达，
   改多源后既保留内容校验、又不再误判。

**验证**（真实凭据，全部实测）

| 检查 | 命令 / 方式 | 结果 |
| --- | --- | --- |
| 登录判定 | `diagnose_guit.py` | `ok=True message=联网成功!`（不再依赖外网探测兜底） |
| 门户成功原文 | 同上（留存 `diag\03-POST-login.html`） | `summary=联网成功!`，页面仍含验证码框 → 判据必须认文案 |
| ViewState 守卫 | `verify_patches.py` A 组 | 错配提交被拒：`kind=captcha`、`注销页状态已刷新，请重新输入验证码`，`form_source` 复位为 `logoff` |
| 验证码 epoch | `verify_patches.py` B 组 | `0 → 1 → 2` 递进正常 |
| 多源在线探测 | `verify_patches.py` C 组（首选源设为不可达的 HTTPS） | `is_online=True`，1.12 秒（降级成功） |
| **真实注销** | `verify_logoff_v2.py` | `ok=True 已断开网络（门户已确认下线）`，**耗时 0.06 秒**（旧实现 13.6 秒） |
| **注销后门户状态** | 同上 | `未联网`（门户即时生效）；外网仍可达 → 证实出口不由门户控制 |
| **立即重连** | 同上 | 第 1 次 OCR 错 → 自动换码；第 2 次 `联网成功!`，门户回到 `已联网` |
| 语法 | `.venv\Scripts\python.exe -m py_compile src\portal_client.py src\app.py` | 通过 |

**影响文件**：`src\portal_client.py`、`src\app.py`、`docs\DIAGNOSIS-20261013.md`（新增）

**回滚点**：`temp\output\backup-20261013\`（原 `portal_client.py`、`app.py`、`config.json`、`CHANGELOG.md`、旧 exe）

**遗留（网络侧现实，非程序缺陷）**：注销后外网仍可达 → 这条出口连接不由该门户会话控制
（路由器 / 其他设备 / 其他认证通道）。程序现如实提示，不再谎报失败。

## 2026-10-13 18:15 在线探测改用 HTTPS（修复离线误判为在线）

**问题**（用户实测：网页注销断网后，程序点「连接」却提示「网络已连通，无需登录」）

原探测地址为 HTTP 明文（`http://www.msftconnecttest.com/connecttest.txt`）。校园网未认证
状态下，HTTP 请求会被门户劫持或特殊处理，导致离线时探测仍能拿到包含期望内容的响应，
`is_online()` 误判为在线——断网的用户被程序告知「无需登录」，无法进入登录流程。

**修复**

探测地址改为 **HTTPS**（`https://www.msftconnecttest.com/connecttest.txt`）：
HTTPS 无法被透明劫持伪造——离线时 TLS 握手必然失败，`is_online()` 因异常正确返回
`False`；在线时行为不变（实测 0.52 秒返回 True）。联网判断（登录前检查、断开前检查、
状态栏）已在前一版统一走 `is_online()`，本修复使其在离线场景下可靠。

**验证**

| 检查 | 结果 |
| --- | --- |
| 在线状态 HTTPS 探测 | True，0.52 秒 |
| 离线场景 | TLS 握手必失败 → False（结构性保证，无法被劫持伪造） |

## 2026-10-13 17:15 修复注销成功被误报为失败

**问题**（用户实测仍报「断开失败：门户未确认状态变化」，随后用诊断脚本真实提交一次注销定位）

门户对注销请求的响应有个迷惑行为：**把「注销成功!」也放在 `validation-summary-errors` 块里**（与「验证码错误!」同一位置）。同时：

1. 状态 span 仍显示「已联网」（门户状态刷新滞后）；
2. 网络真正断开**有延迟**（提交后 2 秒探测仍可上网）；
3. 旧逻辑把提取到的提示文字一律当失败信息——于是「注销成功!」被当成失败返回。

实际网络**确实断开了**（用户侧确认），纯属误报。

**修复**（`submit_logoff` 判定重写）

1. 提取提示文字后：含「成功」→ 按**成功**处理；含「验证码」→ 验证码错误；
2. 新增 `_confirm_offline()`：**外网探测复核，最多 3 次、每次间隔 4 秒**（覆盖网络生效延迟）；
3. 状态 span 判定保留作为中间路径；完全无反馈时也由外网探测收尾。

**验证**

| 检查 | 方式 | 结果 |
| --- | --- | --- |
| 注销真实生效 | 诊断脚本 OCR 识别验证码后真实提交 | 门户返回「注销成功!」，网络确实断开（用户确认） |
| 错误验证码 | 提交 `ZZZZ`（不会断网） | `kind=captcha`、`message='验证码错误!'` |
| 语法 | `py_compile` | 通过 |

## 2026-10-13 16:35 修复错误提示提取、取消自动隐藏、增加单实例

**改动**（用户反馈三项）

1. **修复门户错误提示提取**（`PortalClient._extract_error`）：门户把错误提示放在
   `<p class="validation-summary-errors">验证码错误!</p>`，块内是**纯文本**，
   原实现却在块内继续按 `>文本<` 匹配，导致提示全部丢失——登录与注销失败时都只能
   报出含糊的「门户未确认状态变化」。改为去标签后取文本，错误原因得以正确显示。
2. **取消连接/断开后的自动隐藏**：`_finish()` 中登录成功后不再延迟调用 `_on_hide()`，
   窗口保持原样，是否隐藏交由用户决定。
3. **新增单实例机制**：以**本地回环端口**（`127.0.0.1:47823`）充当实例锁，判定放在
   **模块级、早于 tkinter/Pillow/pystray 加载之前**执行——端口可用即本进程为唯一实例，
   端口被占则连接并握手（发送 `show`），收到 `ok` 回执确认是同一程序的已有实例后，
   由已有实例把窗口唤出，当前进程随即 `os._exit(0)` 退出。
   - 早期判定是必要的：把判定放在 GUI 库加载之后时，退出阶段会被线程/socket 清理拖住，
     实测滞留成 `Not Responding` 的僵尸进程（第二个实例 30 秒仍不退出）。
   - 端口若恰被其它程序占用（无 `ok` 回执），照常启动，不会误判。

**验证**

| 检查 | 方式 | 结果 |
| --- | --- | --- |
| 错误提取（注销） | 提交错误验证码（不会真注销） | `kind=captcha`、message=`验证码错误!` |
| 错误提取（登录） | 错误验证码 + 测试账号 | `kind=captcha`、message=`验证码错误!` |
| 单实例（源码级） | 先后启动两个实例 | 第二个 **3 秒**内退出（退出码 0） |
| 单实例（exe 实测） | 启动 exe 两次并轮询进程数 | 第二个实例**自行退出**，进程数回到 2、无残留 |
| 取消自动隐藏 | 代码检查 `_finish` | 连接成功后不再调用 `_on_hide` |
| 语法 | `py_compile src\*.py` | 通过 |
| 打包 | `build.ps1 -Target all` | 见下 |

## 2026-10-13 16:18 构建产物名统一为项目名

**改动**（用户要求：「产物名字也改成项目名字」）

1. 构建产物由 `CampusNetLogin-lite.exe` / `CampusNetLogin-full.exe` 改为 **`GUIT-net-login-lite.exe`** / **`GUIT-net-login-full.exe`**，与项目名统一。
2. 涉及的引用一并更新：`scripts\build.ps1`（`--name` 与产物路径）、`.github\workflows\release.yml`（发布说明表格与上传路径）、`README.md`、`docs\PLAN.md`、`src\app.py`（模块 docstring 中的命令行示例）。
3. 顺带把发布说明与 README 中的体积描述更新为当前实际值（约 160 MB / 约 19 MB）。
4. 历史 Release（v1.0.0 ~ v1.0.5）中的旧名资产保留不变，不影响已发布的下载链接。

**验证**

| 检查 | 方式 | 结果 |
| --- | --- | --- |
| 残留引用 | 全仓库检索 `CampusNetLogin` | 除 CHANGELOG 历史记录外已无残留 |
| 本地构建 | `build.ps1 -Target all` | `GUIT-net-login-lite.exe` 18.5 MB、`GUIT-net-login-full.exe` 159.4 MB |
| 启动实测 | 运行新名 lite 并读窗口标题 | 「联网设置 v1.0.0」正常，目录无残留 |

## 2026-10-13 15:59 项目地址改为「GitHub 图标 + 项目地址」链接

**改动**

1. 界面底部的项目地址由「完整 URL 文本」改为「**GitHub 图标 +「项目地址」四个字**」的可点击链接，不再显示长网址；版本号小字保留在行尾。
2. 新增 `assets/github.png`：由用户提供的官方图标处理而来（原图 512×512 已带透明背景 → 裁掉无效边距得 495×495 → 输出 128×128，程序内再缩至 16×16）。
3. `src/app.py`：图标通过 `resource_path("github.png")` 读取，**存在才渲染**——图片缺失时自动降级为纯文字链接，不影响启动；图标与文字均绑定点击打开仓库。
4. `build.ps1` 原有的 `--add-data assets;assets` 已覆盖该图片，无需额外改动。

**验证**

| 检查 | 方式 | 结果 |
| --- | --- | --- |
| 图标处理 | Pillow 裁剪并预览 16/18/24/32/48 多尺寸 | 16px 可辨、18px 以上清晰；透明底与界面融合无白块 |
| 界面效果 | 源码级运行并截图 | 底部呈现「〔图标〕项目地址 v1.0.0」，点击可打开仓库 |
| **资源打包** | 特征字节抽查 exe | `github.png` **5/5** 命中、`app.ico` **3/3** 命中 |
| 打包体积 | `build.ps1 -Target all` | lite 18.5 MB、full 159.4 MB |
| 启动实测 | 运行 lite 并读窗口标题 | 「联网设置 v1.0.0」正常，目录无残留 |

## 2026-10-13 15:47 应用图标（用户提供的图片）

**改动**

1. 新增 `assets/app.ico`（多尺寸）与 `assets/app.png`：由用户提供的图片裁切生成——以短边为边长、**从顶部取正方形**，保留主体、裁掉下方多余部分。
2. `src/app.py`：
   - 新增 `resource_path()`：打包后从 `sys._MEIPASS\assets` 读取，源码运行时从项目 `assets` 目录读取；
   - 主窗口通过 `iconbitmap()` 应用图标（标题栏与任务栏）；
   - 托盘图标改为**优先使用 `assets/app.png`**，文件缺失时退回原先现画的蓝色图形，保证不影响启动。
3. `scripts/build.ps1`：新增 `--icon assets\app.ico`（exe 文件图标）与 `--add-data assets;assets`（让程序运行时能读到图标文件）。

**验证**

| 检查 | 方式 | 结果 |
| --- | --- | --- |
| 裁切 | Pillow 读取尺寸与裁切 | 292×330 → 顶部 **292×292** 正方形，主体完整 |
| ICO 生成 | 多尺寸导出 | 95.3 KB，含 16/24/32/48/64/128/256 共 7 种尺寸 |
| **exe 图标嵌入** | 解析 PE 资源表 + ICO 特征字节抽查 | 资源表 94.8 KB；特征片段抽查 **5/5 命中** |
| 打包 | `build.ps1 -Target all` | lite 18.4 MB、full 159.4 MB（较上版各 +0.1 MB） |
| 启动实测 | 运行 lite 读窗口标题 | 「联网设置 v1.0.0」正常，目录无残留 |

## 2026-10-13 15:30 爬取门户对齐接口：补齐 ISP 字段、验证码放大 4 倍

**背景**：用户要求「完整爬取一遍网站来对齐接口避免错误」。当时外网未放行、门户（内网）可达，正好完整核对。

**爬取结果（仅 GET 页面与验证码，未提交任何表单）**

| 项目 | 实测结果 | 结论 |
| --- | --- | --- |
| 登录页字段 | `SSOGUITID` / `SSOACC` / `SSOPWD` / `TextBoxCC` / `LoginBtn` + 4 个隐藏字段 | 与程序配置**完全一致** |
| **登录页额外字段** | `ctl00$MainContent$TextBoxISP`（默认「自动选择」）**程序未提交** | **已修复** |
| 注销页字段 | `TextBoxCC` / `LogoffBtn` + 4 个隐藏字段 | 与配置一致 |
| 状态解析 span | `MainContent_LocalIP`、`MainContent_LabelOnline` 均能正确解析 | 与配置一致 |
| **验证码图片** | **80×24 px，RGBA** | 远小于早前文档记载的 155×52 → 放大倍数由 2 调整为 **4** |
| 站点链接 | `./`、`Content/Site.css`、`checking`、`favicon.ico`、`http://172.16.0.1`、`login`、`logoff` | 备查 |

**修复**

1. `PortalClient` 新增 `_parse_form_defaults()`：解析页面**全部输入控件的默认值**，提交时原样带回（`fields = dict(self.defaults)` 后再 `update(self.hidden)`）。登录与注销两条提交路径都已应用——现在会带上 `TextBoxISP=自动选择`，与浏览器实际提交内容一致。
2. `CAPTCHA_ZOOM` 由 2 调整为 **4**（原图仅 80×24，2 倍后仍偏小）。
3. 修复 `_show_captcha()` 误写 `self.CAPTCHA_ZOOM`（应为模块常量 `CAPTCHA_ZOOM`）导致的「验证码显示失败」——该问题由用户提供的界面日志精确定位。
4. **修复验证码被压扁**：Tkinter 的 Label 一旦设置 `image`，`width`/`height` 的单位会从「字符数」变为「像素数」，原占位值 `width=26/height=4` 会把图片强制压成 26×4 像素。新增 `_fit_captcha_label()`，显示图片时按图片实际像素尺寸刷新标签，两条解码路径均已应用。

**验证**

| 检查 | 方式 | 结果 |
| --- | --- | --- |
| Python 语法 | `py_compile src\*.py` | 6 个模块通过 |
| 提交字段构成 | 复刻 `submit()` 字段构造但**不发送** | 登录 10 个字段（**含 TextBoxISP**）、注销 6 个字段 |
| 验证码放大 | 真实图 80×24 → 320×96（LANCZOS） | 生成对比图确认字符可辨 |
| **标签渲染尺寸** | 复刻界面 Label 配置并读取实际尺寸 | 占位 214×82 → 显示后 **324×100**（图片 320×96 + 4px 边框），与图片一致 |
| 打包 | `build.ps1 -Target all` | lite 18.3 MB、full 159.3 MB |
| 启动实测 | 运行 lite 并读窗口标题 | 「联网设置 v1.0.0」正常，程序目录无残留 |

**说明**：本次改动已完成并本地验证；因当时外网不通，推送与云端发布待网络恢复后补做。

## 2026-10-13 15:00 验证码显示改用 Pillow；「隐藏」改为隐藏到系统托盘

**改动**（用户反馈：验证码又显示「加载失败」；希望隐藏到托盘、任务栏不留窗口）

1. **验证码显示改用 Pillow 解码**（`_show_captcha()`）：
   - 优先 `PIL.Image` 解码 + `LANCZOS` 平滑放大 2 倍，再用 `ImageTk.PhotoImage` 显示；Pillow 不可用时退回 tkinter 原生 `PhotoImage.zoom()`。
   - 原因：tkinter 原生 PNG 解码对非标准 chunk 较为严格，门户验证码可能触发解析失败；Pillow 容错更好。
   - 失败时不再只显示「加载失败」，而是把**具体异常写入界面日志**，便于定位。
2. **「隐藏」按钮改为隐藏到系统托盘**（`_on_hide()`）：使用 `pystray` 创建托盘图标（Pillow 绘制的蓝色圆角底 + 白色信号图形），窗口 `withdraw()` 后**任务栏与窗口均不残留**；托盘菜单提供「显示窗口」（双击图标亦可）与「退出」；托盘回调切回主线程操作界面。
3. `requirements.txt` 新增 `pystray==0.19.5`。
4. `scripts\build.ps1`：
   - lite 版**不再排除 PIL**（与 pystray 同为界面基础能力，必须保留），相应体积由约 11 MB 增至约 18 MB；
   - 新增 `--hidden-import pystray._win32` 与 `--hidden-import PIL.ImageTk`，避免动态/隐式导入被漏收。

**验证**

| 检查 | 方式 | 结果 |
| --- | --- | --- |
| 语法 | `py_compile src\*.py` | 通过 |
| pystray 后端 | 源码级导入 `pystray._win32` | OK；Icon 与菜单（显示窗口 / 退出）创建成功 |
| 托盘图标 | Pillow 绘制并保存预览 | 生成正常（蓝色圆角底 + 白色信号） |
| 打包体积 | `build.ps1 -Target all` | lite 18.3 MB（含 Pillow+pystray）、full 159.3 MB |
| 启动实测 | 运行 lite 并读窗口标题 | 「联网设置 v1.0.0」正常；运行后目录无残留 |

## 2026-10-13 14:45 修复：打包后 ModuleNotFoundError（分发前实测发现）

**问题**（在回答「可以分发了吗」前对 Release 产物做实测时发现）

- 现象：运行 Release 里的 exe 报 `ModuleNotFoundError: No module named 'version'`，窗口打不开。
- 根因：`src/version.py` 作为独立模块，PyInstaller `--onefile` 打包时未被收集；`build.ps1` 追加 `--paths src` 后**仍未解决**。
- 影响范围：**v1.0.1、v1.0.2 的 Release 产物不可用**（v1.0.0 无此问题，因为当时尚未引入版本号模块）。

**修复**

1. 删除 `src/version.py`，版本号改为 `app.py` 内常量 `APP_VERSION`（注释标明由工作流替换），彻底消除对独立模块收集的依赖。
2. 发布工作流改为**正则替换 `app.py` 中的 `APP_VERSION` 行**，并用 `[System.IO.File]::WriteAllText` 以无 BOM UTF-8 写回。
3. `build.ps1` 保留 `--paths src`（对将来的其它模块仍有意义）。
4. 发布 v1.0.3 后**重新下载云端产物实测**：窗口标题为「联网设置 v1.0.3」，GUI 正常，运行后程序目录无任何残留。

**验证方法改进（重要经验）**

- 此前用「运行 exe 看 stderr 有无 Traceback」判断成败是**假阳性**——`--noconsole` 模式下崩溃信息不会输出到 stderr，本地那次"验证通过"实为误判。
- 改用 `tasklist /v` 读取**窗口标题**判断（标题存在 = GUI 真正创建），才是可靠判据。

**过程记录（网络限制应对）**

| 环节 | 情况 | 处置 |
| --- | --- | --- |
| `git push` | 本机 GitHub HTTPS 通道 TLS 握手失败（schannel / OpenSSL 后端均失败，带代理亦不通） | 改用 **GitHub REST API** 推送：单文件用 Contents API、多文件用 Git Data API（blob→tree→commit→更新 ref），同样能触发工作流 |

## 2026-10-13 14:20 自动发布首次跑通（v1.0.1）

**改动**

1. 修正工作流 Python 版本：`3.11` → **`3.13`**。`requirements.txt` 锁定的 numpy 2.5.x 要求 Python ≥ 3.12，用 3.11 会导致依赖安装失败。

**验证（GitHub Actions 运行 `38355981940`，耗时约 1.5 分钟）**

| 步骤 | 结果 |
| --- | --- |
| 检出代码 / 安装 Python / 计算版本号 / 写入版本号 | 全部 success |
| 建立虚拟环境并安装依赖 | success |
| 构建 lite 与 full | success |
| 生成发布说明 | success |
| **创建标签并发布 Release** | success |

**产物**

- 由 v1.0.0 **自动递增**得到新标签 `v1.0.1`，Release「GUIT-net-login v1.0.1」已发布；
- 附件：`CampusNetLogin-full.exe` 158.7 MB、`CampusNetLogin-lite.exe` 11.5 MB（均为云端构建）；
- `v1.0.0` 保留为历史版本；
- 文档类提交（`docs/`、`README.md`）不在触发路径内，不会造成无谓发版。

**首次失败与处置（过程留痕）**

| 运行 ID | 结果 | 原因与处置 |
| --- | --- | --- |
| 38355794723 | failure | 依赖安装失败：云端 Python 3.11 装不上 numpy==2.5.4（要求 ≥3.12）→ 工作流改用 3.13 |
| 38355981940 | **success** | 全流程贯通，自动发版可用 |

## 2026-10-13 14:15 自动发布：版本号自动迭代（GitHub Actions）

**改动**（用户要求：「推送更新自动迭代版本号」）

1. 新增 `.github/workflows/release.yml`：把「构建 + 打标签 + 发 Release + 上传附件」搬到云端自动化。
   - **触发**：`src/`、`scripts/`、`requirements.txt`、本工作流自身推送到 `main` 时自动运行；也可在 Actions 页面手动触发并选择 `patch` / `minor` / `major`。
   - **版本号迭代**：读取仓库现有 `v*` 标签取最大值，按递增类型生成新版本号（默认补丁位 +1），无需手改任何文件。
   - **流程**：写入版本号到 `src/version.py` → 建 venv 装依赖 → `build.ps1 -Target all` → 用 `gh release create` 打标签并发布，附件为两个 exe，发布说明自动包含最近提交列表。
   - 使用 Actions 内置 `GITHUB_TOKEN`（`contents: write`），**不再需要个人 Token**。
2. 新增 `src/version.py`：版本号单一来源；`src/app.py` 引入并在**窗口标题**（`联网设置 vX.Y.Z`）与**底部项目地址行**显示。
3. `README.md`：新增「自动发布」一节。

**验证**

| 检查 | 方式 | 结果 |
| --- | --- | --- |
| 工作流 YAML 语法 | `yaml.safe_load()` 解析 | 通过；触发方式 `push` + `workflow_dispatch`，8 个步骤齐全 |
| Python 语法 | `py_compile src\*.py` | 通过（含新增 version.py） |
| 版本号接入 | `grep __version__ src\app.py` | 标题与底部两处均已使用 |
| 端到端 | 推送触发 Actions | 见下方运行记录 |

## 2026-10-13 14:00 去除文件残留：不写日志、配置单文件化

**改动**（用户要求：「不要在本地产生 log」「不要在其他用户电脑上产生额外文件」）

1. `src\app_logger.py`：**彻底移除文件写入**——日志只送到界面日志区（sink 回调），静默模式无 sink 时直接丢弃；不再创建 `logs\` 目录。
2. `src\config_store.py`：配置由 `config\config.json` 改为**程序同目录下的单文件 `config.json`**（不再创建子目录）；新增 `remove_config()`；移除 `config_dir()`、`log_dir()`。
3. `src\app.py`：
   - `Logger` 接入界面 sink，日志统一由一处输出（去除原先 logger 与 `_post("log")` 的重复输出）；
   - `_save_config_safely()` 改为**按需落盘**：仅当勾选「记住密码」或「开机自动登录」时才写 `config.json`，两者都未勾选则删除该文件；未勾选「记住密码」时口令绝不写入文件。
4. 目录调整：`config\config.sample.json` 移至根目录 `config.sample.json`；删除 `logs\` 与 `config\` 目录。
5. `scripts\build.ps1`：配置样例复制路径同步更新。
6. `.gitignore`：改为忽略根目录 `config.json`。
7. `README.md`：补充「不留垃圾」说明。

**验证**

| 检查 | 命令 / 方式 | 结果 |
| --- | --- | --- |
| Python 语法 | `py_compile src\*.py` | 6 个模块通过 |
| 残留引用 | `grep -rn "log_dir\|logs/" src\*.py` | 无 |
| 删除逻辑接入 | `grep -n remove_config src\app.py` | 已接入 `_save_config_safely()` |
| 目录结构 | 列出项目根 | 无 `logs\`、无 `config\`，仅 `config.sample.json` |
| 打包 | `build.ps1 -Target all` | `CampusNetLogin-lite.exe` 11.0 MB、`CampusNetLogin-full.exe` 158.2 MB |
| **运行零残留实测** | 运行 full 版 30 秒后检查程序目录 | **无 `logs\` 目录、无 `config.json`**（未点「连接」时不产生任何文件） |

**问题与处置**

| 级别 | 问题 | 处置 |
| --- | --- | --- |
| 提示 | full 构建中断：`[safe-delete] ... trash-failed`——本机沙箱的删除保护层（`genie-trash`）无法回收 165 MB 的旧 exe，导致 PyInstaller 覆盖同名文件失败 | 重新触发删除（最终生效）后重新构建即通过。与项目代码无关，属本地环境行为；已记录的规避办法是构建前确保 `build\` 中无同名旧产物 |

## 2026-10-13 13:54 界面显示项目地址

**改动**

1. `src\app.py`：窗口底部新增一行「项目地址：<链接>」——带下划线、鼠标手型、点击后用系统默认浏览器打开（新增常量 `PROJECT_URL`）。
2. 打开链接的逻辑抽取为通用方法 `_open_url(url, label)`，`_open_portal()` 改为复用它，避免重复代码。
3. 免责声明下移一行（`row=12`）。

**验证**

| 检查 | 方式 | 结果 |
| --- | --- | --- |
| Python 语法 | `py_compile src\*.py` | 6 个模块通过 |
| 编码与行尾 | 前 3 字节 + CRLF 规整 | 15 个文件合规 |
| 元素写入 | `grep PROJECT_URL src\app.py` | 常量定义 + 控件文本 + 点击绑定均在位 |
| 打包 | `build.ps1 -Target all` | lite / full 均构建通过 |

## 2026-10-13 13:50 开源协议与首个 Release（v1.0.0）

**改动**

1. 新增 `LICENSE`：采用 **MIT 协议**（与 `ddddocr` 等依赖一致，允许自由使用、修改、分发，仅需保留版权声明）。
2. `README.md` 新增「开源协议」一节，并列明第三方依赖的协议。
3. 打标签 `v1.0.0` 并创建 GitHub Release，附带版本说明与两个构建产物。

**验证**

| 检查 | 命令 / 方式 | 结果 |
| --- | --- | --- |
| 协议文件 | 检查 `LICENSE` | MIT 全文，已入库 |
| 标签推送 | `git push origin v1.0.0` | `* [new tag] v1.0.0 -> v1.0.0` |
| Release 创建 | GitHub API | 成功，标题「GUIT-net-login v1.0.0」 |
| 资产上传 | GitHub Release Assets API | `CampusNetLogin-lite.exe` 11.0 MB、`CampusNetLogin-full.exe` 158.2 MB |

## 2026-10-13 13:42 项目更名、验证码放大与若干修复

**改动**

1. **项目更名为 `GUIT-net-login`**：本地目录改名（原 `campus-net-login`）、日志文件改为 `logs\GUIT-net-login-YYYYMM.log`、文档标题同步；虚拟环境随之重建。
2. `src\app.py`：**验证码图片放大 2 倍显示**（155×52 → 310×104，新增常量 `CAPTCHA_ZOOM`），并改为独占一行，输入框与「换一张」按钮移到下一行，另加「看不清可换一张」提示——用于自动识别失败需手工输入时能看清字符。
3. `src\portal_client.py`：门户请求与联网探测均**显式绕开系统代理**（`ProxyHandler({})`）。门户是内网地址，经代理转发常导致连接失败；联网探测若走代理也会造成「是否已认证」的误判。
4. `src\app.py`：修复状态行与日志区**共用同一 grid 行**（均为 row=8）造成的布局重叠。
5. `scripts\build.ps1`：改用 `python -m PyInstaller` 调用，替代 `.venv\Scripts\pyinstaller.exe`——后者是含绝对路径的启动器，项目目录改名或移动后即失效（本次改名后即复现）。
6. **文档隐私复查**：清除个人代号；逐类确认无本机路径与用户名、真实 IP、手机号、学号、学校名残留（仅保留门户地址 `10.6.6.6`，属软件必需配置）。

**验证**

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Python 语法 | `py_compile src\*.py` | 6 个模块通过 |
| 编码与行尾 | 前 3 字节 + CRLF 规整 | `.ps1` BOM=True；其余 BOM=False；均 CRLF |
| 验证码放大 | `tk.PhotoImage.zoom(2)` | 155×52 → **310×104 px** |
| 构建脚本（端到端） | `build.ps1 -Target all` | `CampusNetLogin-lite.exe` 11 MB、`CampusNetLogin-full.exe` 158.2 MB |
| 隐私扫描 | 关键词检索（路径/IP/手机号/学号/校名/代号） | 全部为空 |

## 2026-10-13 13:22 发布到 GitHub（公开仓库）

**改动**

1. 本地初始化 git 仓库（分支 `main`）并完成首次提交 `1bf0a15`（15 个文件）。
2. 安全处理：
   - `.gitignore` 增加 `config/config.json`、`config/*.local.json`、`logs/`，防止账号口令与运行痕迹入库；
   - 本文件中原先记录的真实出口 IP 已脱敏（公开仓库不保留实际值）。
3. 创建公开仓库并推送：<https://github.com/ButtLoverrrr/GUIT-net-login>
4. 推送后立即将 remote URL 中的临时 Token 移除，改为不含凭据的地址。

**验证**

| 检查 | 结果 |
| --- | --- |
| 入库文件数 | 15 个；`.venv\`、`build\`、`logs\`、`config\config.json` 均未入库 |
| 敏感信息扫描 | `172.22.x.x` 类真实 IP、学号、手机号均无残留 |
| 推送结果 | `* [new branch] main -> main`，`main` 已设置追踪 `origin/main` |
| remote 状态 | `https://github.com/ButtLoverrrr/GUIT-net-login.git`（不含 Token） |

## 2026-10-13 13:02 新增：网络状态显示与断开网络（注销）

**改动**（用户需求：「官网还有个显示用户连接状态的和断开网络连接，帮我完善」+ 官网注销页截图）

1. `src\config_store.py`、`config\config.sample.json`：新增 `logoffUrl`（默认 `http://10.6.6.6/logoff`）、`logoffFields`（注销表单：验证码 `ctl00$MainContent$TextBoxCC`、按钮 `ctl00$MainContent$LogoffBtn`/「注销」）、`statusFields`（状态 span id：`MainContent_LocalIP` / `MainContent_LabelOnline`）。
2. `src\portal_client.py`：新增 `PortalStatus` 数据类、`_extract_span()` 工具（剥离内层 `<font>`）、`query_status()`（只读查询状态）、`prepare_logoff()`（取注销页隐藏字段与验证码）、`submit_logoff()`（提交注销，按响应状态与复查双重判定成败）；`LoginSession` 同步暴露三个方法。
3. `src\app.py`：
   - 状态栏左侧新增「网络状态：已联网 / 未联网 + IP」，在线绿色、离线红色（`_update_net()`）；
   - 次要按钮行改为「隐藏 / **断开网络** / 退出」；新增 `_on_logoff()` 与 `_logoff_worker()`：首次点击取注销页与验证码，输入后再次点击提交；验证码错误自动换图并提示；
   - 新增 `captcha_purpose`（`login` / `logoff`）标记当前验证码用途，避免把注销验证码误用于登录提交；
   - 启动预取、登录成功后、断开成功后均自动刷新状态栏（`_refresh_status()`）。
4. `README.md`：界面说明表补充「网络状态」「断开网络」两行。

**验证**

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Python 语法编译 | `py_compile src\*.py` | 6 个模块通过 |
| 状态解析实测（只读） | `LoginSession.query_status()` | 成功解析出「已联网」状态与 IP 字段，与官网注销页显示一致（**实际 IP 已脱敏，不入库**） |
| 注销页准备实测（只读） | `LoginSession.prepare_logoff()` | 取到验证码 1137 B PNG-OK；注销页 4 个隐藏字段已缓存 |
| 配置结构 | `ConvertFrom-Json` | `logoffUrl` / `logoffFields` / `statusFields` 均可解析 |
| 打包与启动实测 | `build.ps1 -Target all` + 运行 exe | 见下方行 |

**未验证（需实测）**：`submit_logoff()` 的真实提交路径——断开网络会中断当前网络，故未在开发期自动执行，留待用户按需点击验证。

## 2026-10-13 12:47 新增：官方平台入口按钮与免责声明

**改动**（用户需求：「在角落添加显示 http://10.6.6.6 官方网络接入平台主页的按钮」「填入免责声明」）

1. `src\app.py`：状态栏右侧新增「官方平台 10.6.6.6」按钮，点击用系统默认浏览器打开官网（新增 `_open_portal()`，新增 `webbrowser` 导入）；窗口底部新增免责声明文本（模块常量 `DISCLAIMER`）。
2. `src\config_store.py` 与 `config\config.sample.json`：新增 `portalHome` 配置项（默认 `http://10.6.6.6`），官网地址可由配置覆盖。
3. `README.md`：界面说明表补充官网按钮与验证码显示行为；新增「免责声明」一节。

## 2026-10-13 12:42 交互修正：验证码改为启动即预取显示

**改动**（用户反馈：「为什么验证码不能直接显示」）

1. `src\app.py`：新增 `_start_prefetch()` / `_prefetch_worker()`，窗口出现后 200 ms 即在后台拉取验证码并显示（含自动识别结果填入输入框）。
2. **无论当前是否已联网都拉取并显示验证码**——原实现在已联网时直接跳过，是用户看到验证码区空白的主因。
3. 验证码占位文案由「点击『连接』获取」改为「正在获取…」。
4. OCR 引擎初始化（约 1~2 秒）从 UI 线程（`_on_start`）移入后台预取线程，避免窗口出现时卡顿；新增 `_use_ocr()` 统一判断，三处调用收口。
5. `_set_busy()` 支持自定义按钮文案：预取期间禁用按钮但保持「连 接」字样。

## 2026-10-13 12:36 需求修正：新增「上网账号（手机号）」必填项

**改动**（用户补充需求：「上网不仅要学号还要上网账号，也就是手机号」）

1. `src\app.py`：界面新增「上网账号」输入框（位于学号与上网密码之间），全部控件行号顺延；
   `_on_start` 增加回填、`_collect_form` 改为三项（学号 / 上网账号 / 上网密码）分别校验并提示所缺项。
2. `src\config_store.py`：`has_credential()` 收紧为「学号 + 上网账号 + 密码」三者齐备；
   静默模式（`--silent`）的准入条件随之变严，未填全则转入界面。
3. `config\config.sample.json`：`user` 节点加 `_comment` 字段说明三个字段与门户字段对应关系。
4. `README.md`：界面说明表拆分为「学号 / 上网账号 / 上网密码」三行，明确上网账号为认证账号、必填。
5. `docs\PLAN.md`：第 1 节需求澄清补录该条；第 8 节确认记录补录变更时间。

**验证**

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Python 语法编译 | `.venv\Scripts\python.exe -m py_compile src\*.py` | 6 个模块通过 |
| 配置结构 | `ConvertFrom-Json` | 可解析，`user._comment` 与三个字段均存在 |
| 编码与行尾 | 前 3 字节 + CRLF 检查 | `.ps1` BOM=True，其余 BOM=False，均 CRLF |
| 打包与启动实测 | `build.ps1 -Target all` + 运行两个 exe | 见下方「重新打包」行 |

**说明**：字段对应关系 —— 学号 = `SSOGUITID`，上网账号 = `SSOACC`，密码 = `SSOPWD`，验证码 = `TextBoxCC`。
本次仅调整界面与校验，门户交互逻辑（`portal_client.py`）无需改动：`submit()` 本就分别接收 `guid` 与 `acc`。

## 2026-10-13 12:32 实现与打包（用户确认方案后执行）

**改动**

1. 新增 `src\portal_client.py`：登录核心。在线探测（校验响应内容防网关劫持）、取隐藏字段、取验证码、POST 提交、结果判定（`ok` / `captcha` / `credential` / `network` / `unknown` 分类），并提供 `LoginSession` 与 `auto_login()` 两种封装。
2. 新增 `src\config_store.py`：配置读写，**便携语义**（配置始终位于 exe 同目录）。含字段名映射默认值，门户改版只需改配置。
3. 新增 `src\app_logger.py`：日志写 `logs\GUIT-net-login-YYYYMM.log`（UTF-8 无 BOM、CRLF），写盘失败不影响主流程。
4. 新增 `src\ocr_helper.py`：ddddocr 惰性封装；不可用或异常时返回空串，自动降级为手输。
5. 新增 `src\autostart.py`：开机自启（启动文件夹 `.lnk`，经 WScript.Shell COM 创建，失败回退 `.cmd`），**不写注册表**；`disable()` 可完全回滚。
6. 新增 `src\app.py`：GUI 主程序（学号 / 上网密码 / 验证码 / 记住密码 / 开机自动登录 / 连接 / 隐藏 / 退出 / 日志区），后台线程执行登录、队列回传界面，`--silent` 静默模式。
7. 新增 `config\config.sample.json`、`requirements.txt`（版本已锁定）。
8. 新增 `scripts\build.ps1`：产出 `lite`（无 OCR）与 `full`（含 OCR）两个单文件 exe。
9. 建立项目虚拟环境 `.venv`（基于 `SDK\Python\3.13\` 的 3.13.16）。

**验证命令与结果**

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Python 语法编译 | `.venv\Scripts\python.exe -m py_compile src\*.py` | 6 个模块全部通过 |
| 导入一致性（AST，不执行） | `ast.parse` 提取 import 并校验本地模块存在性 | 全部可解析 |
| 脚本语法解析（AST，不执行） | `[Parser]::ParseFile` | `OK build.ps1` |
| 配置结构 | `ConvertFrom-Json` | `portalUrl=http://10.6.6.6/login`、`submitUrl`、`submitValue=登录` 均可解析 |
| 编码与行尾 | 读取前 3 字节 + CRLF 规整 | `.ps1` BOM=True；`.py/.json/.md` BOM=False；均 CRLF |
| 依赖安装 | `pip install --no-index --find-links=<wheel 缓存>` | 离线装成功 14 个包，未联网 |
| **源码级功能自检**（动态，PLAN 步骤 9 已批准） | 运行 `portal_client` + `ocr_helper` | 门户可访问 OK；拉取验证码 963 B PNG-OK；**OCR 可用 True**；识别结果 `p2ra` |
| 打包产物内容 | `pyi-archive_viewer -l` | full 含 `ddddocr\common.onnx`(50 MB)、`common_det.onnx`、`common_old.onnx` 与 onnxruntime DLL；lite 含 0 个 OCR 组件 |
| 打包结果 | `scripts\build.ps1 -Target all` | `CampusNetLogin-lite.exe` 约 11 MB；`CampusNetLogin-full.exe` 约 158 MB |
| **打包版启动实测**（动态，PLAN 步骤 9 已批准） | 运行两个 exe 并读取其写出的日志 | lite：`程序已启动；OCR 不可用（仅手输）`；full：`程序已启动；OCR 可用`；两者均成功创建界面并正常退出 |

**问题与处置**

| 级别 | 问题 | 处置 |
| --- | --- | --- |
| 阻断 | `build.ps1` 首次构建中断：pyinstaller.exe 把 INFO 写入 stderr，在 `$ErrorActionPreference='Stop'` 下被 PS 判为 NativeCommandError | 调用原生命令期间临时放宽该设置，改用 `$LASTEXITCODE` 判定成败；复检构建通过 |
| 提示 | PyInstaller 构建日志出现 `No module named 'onnx'` | ddddocr 实际使用 onnxruntime，不依赖 `onnx`；源码级自检已证明 OCR 可用，属无害警告 |
| 提示 | ddddocr 官方声明最高支持 Python 3.12，本机为 3.13.16 | 实测 3.13.16 下 OCR 初始化与识别均正常，无需回退 lite |
| 提示 | 系统代理 `127.0.0.1:54819` 会拦截 pip | 依赖改用本会话已缓存的 wheel 离线安装，完全绕开网络与代理 |

**待办（需本机执行，属动态检查）**

```powershell
# 1) 源码方式启动界面（开发验证）
.venv\Scripts\python.exe src\app.py
# 2) 打包版启动（分发形态验证）
build\CampusNetLogin-full.exe
# 期望证据：窗口出现「联网设置」；填入学号密码点「连接」后日志显示登录成功；系统联网正常。
```

## 2026-10-13 20:05 体积压缩阶段 A：精确收集（去闲置 OCR 模型与 FFmpeg 组件）+ 打包清单断言

**授权范围**：用户明确要求「开始阶段 A 改造 + 静态验收」。本次**只做代码改造与静态检查**，
未执行构建、未运行 exe、未跑 OCR 推理、未联网、未安装依赖。

**改动**

| # | 文件 | 改动 |
| --- | --- | --- |
| 1 | `scripts\build.ps1` | full 目标删除 `--collect-all ddddocr`、`--collect-binaries cv2`；改为 `--hidden-import ddddocr` + `--copy-metadata ddddocr` + `--add-data <venv>\...\ddddocr\common_old.onnx;ddddocr` + `--additional-hooks-dir scripts\hooks`；打包前断言默认模型与 hook 文件存在 |
| 2 | `scripts\hooks\hook-cv2.py` | 新增。覆盖官方 hook，从 `collect_dynamic_libs('cv2')` 结果中过滤 `opencv_videoio_ffmpeg*.dll`，其余逻辑与上游一致 |
| 3 | `scripts\check-bundle.ps1` | 新增。只读解析 `<workpath>\GUIT-net-login-<target>\PKG-00.toc`，断言必需项存在 / 禁止项不存在，输出 ddddocr、cv2、onnxruntime 三组已收集资源的原始体积；退出码 0 通过 / 1 断言失败 / 2 清单缺失 |
| 4 | `scripts\build.ps1` | 构建结束后自动调用 `check-bundle.ps1`，非 0 退出即 `throw`，产物视为不可发布 |
| 5 | 编码规整 | `build.ps1`、`check-bundle.ps1` 为 UTF-8 **with BOM** + CRLF；`hook-cv2.py` 为 UTF-8 无 BOM + CRLF |

改动文件哈希：

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `scripts\build.ps1` | 7864 | `55F155285F3F7E0A1C8F20609370FD82447774019330D4E2D1DBA0D129FCCAFD` |
| `scripts\check-bundle.ps1` | 9305 | `B9D20A5A6CAA629D66F03E637CE579B495D7A952223C4FD51E74EDB8C4555692F` |
| `scripts\hooks\hook-cv2.py` | 6101 | `44639167D6E9A6BA9A686347BC2538B1306219A48BFE38DEF21989C8BF825EAC` |

**为什么这样改（读取源码与清单得到的事实，非推测）**

1. `ddddocr\models\model_loader.py`：`old=False` 且 `beta=False` 时取 `common_old.onnx`；`beta=True` 才取 `common.onnx`；`load_detection_model` 取 `common_det.onnx`。`src\ocr_helper.py` 只调 `DdddOcr(show_ad=False)` → 后两个模型在运行路径上永不加载。
2. 字符集**内联**在 `ddddocr\models\charset_manager.py::_get_old_charset`，全包无任何模块 `import charsets`（`charsets.py` 为死代码）→ 精确收集不需要额外字符集数据文件。
3. `ddddocr` 包内不含 `importlib` / `__import__` / `import_module`，全部静态 `from ... import`；运行时唯一读盘依赖是 `models\model_loader.py` 用 `__file__` 推导出的模型目录 → 只补 `common_old.onnx` 即完整。
4. `pefile` 静态解析 `cv2\cv2.pyd` 的 PE 导入表：依赖为 ADVAPI32 / COMDLG32 / GDI32 / KERNEL32 / MF / MFPlat / MFReadWrite / OLEAUT32 / SHLWAPI / USER32 / d3d11 / dxgi / ole32 / python3，**不含 ffmpeg DLL**。`opencv_videoio_ffmpeg500_64.dll` 只在运行时由 videoio 动态加载，故排除不造成导入期缺失。
5. ffmpeg DLL 进入包的唯一途径是 `_pyinstaller_hooks_contrib\stdhooks\hook-cv2.py` 的 `collect_dynamic_libs('cv2')`；`--collect-binaries cv2` 在 spec 中展开为同一调用，因此**必须同时**去掉该参数并用 `--additional-hooks-dir` 覆盖 hook（用户 hook 优先级 1000 > contrib -1000，见 `PyInstaller\building\build_main.py`）。
6. `--collect-all X` 默认 `include_py_files=True`；旧 full 清单中 ddddocr 相关 82 行，含 `api\*.py`、`logo.png`、`README.md`、`charsets.py` 与 `ddddocr-1.6.1.dist-info\*` —— 确认「全量收集」并非只收模型。

**静态验收命令与结果**

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 空白错误 | `git diff --check` | 无输出（无空白错误） |
| 改动范围 | `git status --short` | `M scripts/build.ps1`、`?? scripts/check-bundle.ps1`、`?? scripts/hooks/`、`?? docs/20261013-size-reduction-plan.md`；未动 `src\` |
| 脚本语法 | `[Parser]::ParseFile`（主机 7.6.6 与 Windows 宿主 5.1 各一次） | `build.ps1` tokens=617 PASS；`check-bundle.ps1` tokens=1109 PASS（两种宿主结论一致） |
| Python 语法 | `ast.parse`（不导入、不执行） | `hook-cv2.py` PASS；顶层语句 20；hook 变量赋值 `binaries/datas/hiddenimports/excludedimports/module_collection_mode` 齐备 |
| CLI 参数存在性 | 在 PyInstaller 6.22.3 `building/makespec.py` 中检索 | `--add-data`(240) `--hidden-import`(268) `--copy-metadata`(311) `--additional-hooks-dir`(328) 均存在 |
| TOC 断言（旧 full 清单） | `check-bundle.ps1 -Target full -TocPath <备份>\manifests\PKG-00.toc.full` | 解析 1442 条；4 类违规全部命中 → 退出码 1（证明断言有效） |
| TOC 断言（现有 lite 清单） | `check-bundle.ps1 -Target lite` | 解析 1012 条；`ddddocr/*`、`cv2/*`、`onnxruntime/*` 均 0 项 → 退出码 0 |
| 解析覆盖率 | `temp\scratch\toc-coverage.py` | 1419 目的名行 + 23 单行式 = 1442 全部配对，0 条孤儿类型标记 |
| 编码与行尾 | 读取前 3 字节 + CRLF 计数 | `.ps1` BOM=True、CRLF 全量；`hook-cv2.py` BOM=False、CRLF 全量；无裸 LF |
| 备份完整性 | `Get-FileHash` + 体积 | 见 `temp\output\backup-20261013\GUIT-net-login-size-reduction\BASELINE-MANIFEST.md` |

旧 full 清单被命中的违规项：`ddddocr/common.onnx`、`ddddocr/common_det.onnx`、`cv2/opencv_videoio_ffmpeg500_64.dll`、`ddddocr/api/*`（7 个文件）。

**验收中发现并修复的问题**

| 级别 | 问题 | 处置 |
| --- | --- | --- |
| 阻断 | `check-bundle.ps1` 首版用一条大正则枚举类型标记 `DATA/BINARY/EXTENSION/OPTION/PYMODULE/SOURCE`，实测 TOC 还含 **`PYSOURCE`**（full 6 条），且存在 23 条「目标名与类型同行」的单行式条目 → 这些条目被静默跳过，断言可能失效 | 改为逐行解析（三行式 + 单行式两种形态，类型标记按 `[A-Z][A-Z0-9_-]*` 通配）；复验解析 1442/1442，覆盖率 100% |
| 阻断 | 首版 `Write-Host ("...{0}..." -f )` 缺右操作数，两种宿主均报语法错误 | 解析器检出后修复（补 `$Target`） |
| 提示 | 路径反转义写作 `-replace '\\\\','\'` 放在哈希表字面量内被解析器拒绝 | 改为 `$dest.Replace('\\','/')`，语义更直白 |

**未验证事项（本次明确未做，属动态检查，需另行批准）**

- 未构建：新的收集规则尚未产生实际 TOC，`check-bundle.ps1` 对**新**清单的通过情形尚未验证（仅用旧清单证明了「能拦住违规」）。
- 未做离线 OCR 对比、GUI 冒烟、无 Python 环境实测；TOC 校验只能证明收集内容，不能证明运行成功。
- 预期收益仅为估算：三项闲置资源原始体积合计 100.22 MiB（`common.onnx` 51.58 + `common_det.onnx` 19.19 + ffmpeg 29.45）；exe 为已压缩单文件，实际缩减量必须构建后实测。
- `README.md` 第 11 行与 `.github/workflows/release.yml` 第 108 行的发布说明仍写「约 160 MB」，属构建后才可更新的陈旧信息，本次未改。
- CI 触发条件包含 `scripts/**`：**一旦提交并推送即会自动加版本号并发布 Release**，故本次改动保持未提交状态。

**回滚点**

备份目录 `D:\Dev\temp\output\backup-20261013\GUIT-net-login-size-reduction\`：`files\`（`build.ps1` / `ocr_helper.py` / `requirements.txt`）、`manifests\`（两份 spec + 旧 `PKG-00.toc.full`）、`artifacts\`（旧 full 160.42 MiB、lite 19.41 MiB exe）、`BASELINE-MANIFEST.md`（含全部 SHA-256 与 git HEAD `4e30b86`）。回滚＝按清单逐文件覆盖，并删除本次新增的 `scripts\hooks\hook-cv2.py` 与 `scripts\check-bundle.ps1`。

## 2026-10-13 20:20 接手完善阶段 A：许可合规、三层清单检查器、-PythonPath、隔离副本

**授权范围**（用户原话要点）：备份待修改文件、审查并完善已有阶段 A 候选代码、完成静态检查与记录；
可改构建脚本 / cv2 hook / 清单检查器，可新增只读解析脚本 / 许可文件 / 文档，含 `-PythonPath` 参数。
只做 A，不改 src / 认证 / 凭据 / 自启 / 依赖版本 / CI / site-packages，不做 B/C。
**未授权且未执行**：构建、OCR/GUI/测试运行、联网安装、真实门户请求、正式产物替换、提交、发布。

**对交接手册四个问题的处置**

| 问题 | 处置 |
| --- | --- |
| 许可 | 确认 `hook-cv2.py` 是 contrib hook（GPL-2.0-or-later）的修改版本：文件头保留上游版权与 SPDX、列明全部修改点；随目录分发 `scripts\hooks\LICENSE`（contrib 2026.8 的 GPL 全文）；`scripts\hooks\README.md` 说明「项目 MIT 与该文件 GPL 聚合并存，不得标为 MIT」 |
| TOC/PYZ 完整检查 | 新增 `scripts\check_bundle.py`（标准库，`ast.literal_eval`，禁 `eval`/`exec`），同时解析 PKG / PYZ / Analysis 三层；结构或条目形态未知即退出码 2；PKG 与 Analysis 重叠条目去重，避免命中数与体积双计 |
| FFmpeg 匹配 | 按目标名与源路径 **basename** 匹配 `opencv_videoio_ffmpeg*.dll`，覆盖根目录与任意目录 |
| 退出码 | 检查器为 Python 原生进程，`build.ps1` 以 `& $Python …` 启动并立即读 `$LASTEXITCODE`（0/1/2）；不再依赖 `.ps1` 内 `exit` 的传播 |

**改动**

| 文件 | 状态 | 字节 | SHA-256 |
| --- | --- | ---: | --- |
| `scripts\build.ps1` | 修改 | 10248 | `24F602404051BE19844F962534FD091F935EBA509E492092272A3C4B251D0043` |
| `scripts\check_bundle.py` | 新增 | 29093 | `8391AFA59E10BAF3AEEE113A2F4DA2F77A465DB45AAACDAB2CD857A280F5930F` |
| `scripts\hooks\hook-cv2.py` | 修改 | 9906 | `E239A288149087071E2A1FAF8570EDA61D884FC4DF39322415AA1BEC039C5353` |
| `scripts\hooks\LICENSE` | 新增 | 27666 | `91D0BAAFF00773038E72C0A1FC9D5D2D38706B7A2B9C04F34296608F931B9CD0` |
| `scripts\hooks\README.md` | 新增 | 4395 | `9BDFC073429B61D6D69F26F55E000D25DAD2B0C48A0D2853A608CEA773A8B926` |
| `scripts\check-bundle.ps1` | 删除 | — | 过渡实现，被 `check_bundle.py` 取代（备份留档） |
| `docs\size-reduction-results.md` | 新增 | — | 阶段 A 结果报告与授权申请 |

`build.ps1` 同时：新增 `-PythonPath`（隔离副本没有自己的 .venv；site-packages 用
`sysconfig` 从所选解释器定位，而不是写死项目 `.venv` 路径）；修正 .DESCRIPTION 中
「lite 排除 PIL」的错误注释（PIL/pystray 是界面能力，必须保留）。

**隔离副本与备份**

| 路径 | 内容 |
| --- | --- |
| `temp\output\GUIT-net-login-size-reduction-20261013-2004\baseline\` | 同源码基线（压缩前收集规则 + `-PythonPath`） |
| `temp\output\GUIT-net-login-size-reduction-20261013-2004\candidate\` | 候选（本阶段新实现） |
| `…\fixtures\`、`…\fixtures-venv\`、`…\logs\` | 检查器自检样例与全部校验输出 |
| `temp\output\backup-20261013\GUIT-net-login-size-reduction-20261013-2004\` | 修改前的三份脚本、三份文档、full/lite 的 PKG/PYZ/Analysis/EXE-00.toc 与 spec |

两副本 `src\*.py` 与原件哈希逐一一致；未复制真实 config.json、venv、.git。

**静态验收（全部只读）**

| 检查 | 结果 |
| --- | --- |
| `ast.parse`（repo 与 candidate 的 `check_bundle.py`、`hook-cv2.py`，不导入不执行） | 4/4 PASS |
| `[Parser]::ParseFile`（repo / baseline / candidate 三份 `build.ps1`，主机 7.6.6 与 Windows 宿主 5.1） | 6/6 PASS（tokens 770 / 499 / 770） |
| 检查器自检 `--selftest`（8 个合成样例：full 合规 / 6 类违规 / 缺模型 / lite 合规 / lite 误收 / 结构未知 / 字面量损坏 / 缺 PYZ） | 8/8 退出码符合预期，自检退出码 0（managed 与 venv 两个解释器各跑一次） |
| 旧 full 清单 `--target full` | 退出码 1，6 类违规命中：两个闲置模型、ffmpeg（basename 匹配）、`ddddocr/api/` 资源 7 项、PYZ 模块 `ddddocr.api` + 6 个子模块 |
| 旧 lite 清单 `--target lite` | 退出码 0，OCR 三类资源与模块均 0 项 |
| 损坏输入三样例 | 退出码均为 2 |
| `git diff --check` | 无输出 |
| 编码与行尾（9 个文件） | `.ps1` UTF-8 BOM+CRLF；`.py`/`.md` 无 BOM+CRLF；无裸 LF |
| 范围 | `git diff --stat -- src requirements.txt .github` 为空；模型 `common_old.onnx` 13,606,051 字节 / SHA-256 `B8F2AD9C…BF68` 未变 |

**验收中发现并修复**

| 级别 | 问题 | 处置 |
| --- | --- | --- |
| 阻断 | 检查器首版把 PKG 与 Analysis 的 datas/binaries 直接合并，重叠条目导致违规命中数翻倍、体积小结双计 | 按 (目标名， 类型) 去重；复验合并后 1442 条与 PKG 完全一致 |
| 提示 | 自检样例最初用 `\\` 写路径，与真实清单的单反斜杠不符 | 改为原始字符串，样例与真实格式一致 |

**遗留与申请**

- 旧 full 清单被检出的 6 类违规，说明**若不改造**会把闲置模型、FFmpeg 与未使用的
  `ddddocr.api`（资源 + PYZ 模块）打进 exe；候选规则即针对这些项。
- candidate 的 TOC/PYZ 尚不存在（未构建），其清单**尚未通过**检查器。
- exe 实际缩减字节数未测（100.22 MiB 为原始资源体积，不可按比例折算）。
- 离线 OCR 对比缺固定样本（仓库与 temp 仅 3 张截图，非样本集）：需用户提供 ≥100 张 PNG
  或另行授权采集；缺样本时该项记「未验证」。
- 构建/离线验收的命令、副作用、回滚已写在 `docs\size-reduction-results.md` 第 7、9 节，
  等待一次性授权。

## 2026-10-13 20:45 获批执行隔离构建与离线 OCR 等价对比（阶段 A 动态验收）

**授权**：用户以「继续」批准第 7 节申请；随后再次确认「构建」。**未授权且未执行**：
GUI 冒烟、无 Python 环境实测、正式产物替换、提交、发布。

**执行与退出码**

| 步骤 | 退出码 | 说明 |
| --- | ---: | --- |
| 基线构建 lite+full（压缩前规则） | 0 | `logs\build-baseline.log` |
| 候选构建 lite+full（阶段 A 规则，内嵌清单检查通过才允许结束） | 0（首跑 1，已修复） | `logs\build-candidate.log` |
| 四份产物清单校验 | baseline full **1**（6 类违规，符合预期）/ 其余 **0** | `logs\check-*.log`、`check-*.json` |
| 诊断包构建 ×2（baseline / candidate 规则） | 0（首跑 1，已修复） | `logs\build-diag.log` |
| 诊断包运行 ×2（120 张固定样本） | 0 / 0 | `logs\ocr-diag-*.json` |

**实测体积（同源码同环境）**

| 产物 | 字节 | MiB | SHA-256 |
| --- | ---: | ---: | --- |
| baseline full | 168,215,822 | 160.42 | `36EDA7ED599BE7DF2F56ECB8248118284EB48510A82BBC5CA255744372653B1F` |
| candidate full | **86,039,734** | **82.05** | `E4366A5B643D5EBBA13754207A6B6FBFDFBD2EAA5A9AECE198F7FAABFC7BE711` |
| baseline lite | 20,357,535 | 19.41 | `EEA48A8BF98555A69141CAEA446BD35F933A144AAB881AE31EF47B96213EBD56` |
| candidate lite | 20,357,657 | 19.41 | `C4BBE4C1A85BB793C572114C0B9F9E26833EDF33C12A2C89DD846BE393EB4192` |

- **full 缩减 82,176,088 字节 = 78.37 MiB = −48.85%**；120 MiB 目标达成。
- lite +122 字节（构建参数未变）；PKG 条目集合 **1012 = 1012 逐条一致**。
- baseline full 与历史 full 仅差 121 字节 → 同源码重建可复现。
- 产物只在 runRoot（`D:\Dev\temp\output\GUIT-net-login-size-reduction-20261013-2004\`），
  仓库 `build\` 未动，正式产物未替换。

**离线 OCR 等价对比（120 张固定合成样本，种子 20261013）**

把同一诊断入口分别按 baseline / candidate 收集规则打包为 `--console` 诊断 exe
（复用同一 `OcrEngine` 封装与模型规则；诊断包通过不替代正式 exe 冒烟），各自运行：

| 指标 | baseline 规则 | candidate 规则 |
| --- | --- | --- |
| exe 字节 | 163,785,693 | 81,594,221 |
| `frozen` / `ddddocr_available` / `OcrEngine.available()` | True / True / True | True / True / True |
| 包内模型 SHA-256 | `B8F2AD9C…BF68` | `B8F2AD9C…BF68` |
| 运行错误 | 0 | 0 |
| 120 张原始输出 + 包装输出 | — | **逐张一致，差异 0** |

结论：候选打包环境 OCR 可用（排除静默降级），移除两个闲置模型、FFmpeg 组件与
`ddddocr.api` 未改变任何识别输出。样本为合成 PNG（种子固定可复现），不代表真实验证码
分布，不用于准确率结论；包装输出恰 4 位 105/120。

**过程中发现并修复**

| 级别 | 问题 | 处置 |
| --- | --- | --- |
| 阻断 | 候选构建首跑 exit=1：`sysconfig` 探测的内嵌双引号被 Windows 宿主 5.1 剥掉，Python 收到 `get_paths()[purelib]` → NameError | 改为只用 Python 单引号并注释原因；在 5.1 宿主下验证探测返回正确路径后重跑成功 |
| 阻断 | `tools\build-diag.ps1` 首跑解析失败：含中文未写 UTF-8 BOM，5.1 按 ANSI 读取吞掉引号（AGENTS 第 2 节的坑） | 补 BOM + CRLF 后通过 |

**交接第 9 节通过条件核对**：除 GUI 冒烟与无 Python 环境实测外全部满足；
候选可进入正式 exe 冒烟与分发评估。详细数据见 `docs\size-reduction-results.md`。

## 2026-10-13 21:07 GUI 冒烟通过、正式产物替换、README 体积同步（用户授权「一口气做完」）

**GUI 冒烟（隔离模拟副本，无真实门户请求）**

模拟目录 `<runRoot>\gui-smoke\{full,lite}\`：候选 exe + 把 portalUrl / portalHome / captchaUrl /
submitUrl / logoffUrl / onlineProbe.url 全部指向 `http://127.0.0.1:9` 的 config.json，
user 字段留空、`options.autoConnect=false` → 不发出真实门户请求、不尝试登录；未改 src。

| 项 | full | lite |
| --- | --- | --- |
| 主窗口标题 | 联网设置 v1.0.0 | 联网设置 v1.0.0 |
| 进程（启动器+工作子进程） | 2，稳定 20s | 2，稳定 20s |
| 单实例端口 47823 监听 | True | True |
| 脚本退出码 | 0 | 0 |

实现说明：onefile 产物是「启动器父进程 + 工作子进程」两层，窗口在子进程上——首版脚本按
启动返回的 PID 查 MainWindowTitle 恒为空而误报失败，已改为按进程名枚举全部同名进程。

**正式产物替换与文档同步**

- `build\GUIT-net-login-{full,lite}.exe` 替换为 candidate 产物（逐字节一致，full SHA-256
  前缀 `E4366A5B`）；旧产物备份在两处 backup 目录，`build\` 在 .gitignore 内。
- `README.md` 体积表「约 160 MB」→「约 82 MB」；`release.yml` 内的发布说明文案按授权边界
  未改，需发版前人工同步。

**提交**：已本地提交（见下），**未推送**——`scripts/**` 推送会触发 release.yml 自动加版本
号并发布 Release，是否推送由用户决定。
