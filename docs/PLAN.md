# GUIT-net-login 方案（PLAN）

> 规则：本文件是执行前的唯一依据，**未写进本文件的方案视为未完成**；方案有变必须更新本文件并重新确认，禁止边猜边做。
> 「选型与复用」一节为必填：先搜现成方案，再决定是否自研（见 `工作区规范` 第 4 节）。

- 项目路径：`<仓库根>\`
- 立项日期：2026-10-13
- 状态：**已交付**（代码与打包完成，待真实登录实测校准）

## 1. 需求与澄清

| 需求不明点 | 提问 | 用户答复 | 最终理解 |
| --- | --- | --- | --- |
| 交付形态 | 目录版 / 单文件 exe / 两者 | 单文件 exe | 交付物为单文件 exe，双击即用，目标机器无需装 Python |
| 应用形态 | 浏览器页面 / 原生窗口 | 原生窗口（附「联网设置」截图） | 原生 GUI，仿截图布局 |
| GUI 技术路线 | tkinter / PowerShell WinForms / PySide6 | 反问「哪条方便分发给别人」 | 由「便于分发」倒推：**Python + tkinter + 单文件 exe**（理由见第 4 节） |
| 验证码处理 | 手输 / OCR 自动 + 兜底 | OCR 自动 + 手输兜底 | 先自动识别并提交，验证码错则换图重试，仍失败则显示图片由用户手输 |
| 与既有项目关系 | 扩展 campus-net-autologin / 新建 | 新建，旧项目保留 | 新建 `GUIT-net-login`；`campus-net-autologin` 原地保留、独立演进 |
| 开机自启实现 | 注册表 Run 键 / 启动文件夹快捷方式 | 启动文件夹快捷方式 | 写 `shell:startup` 的 `.lnk`（不碰注册表），删除快捷方式即取消 |
| 账号字段构成 | 只有学号够不够 | 「上网不仅要学号还要上网账号，也就是手机号」 | 界面必须提供独立的「上网账号（手机号）」输入框，对应门户 `SSOACC`；学号、上网账号、密码**三者均为必填** |

## 2. 现状核对

- 相关文件与目录：
  - `<仓库根>\`（本项目，2026-10-13 由 `_TEMPLATE` 复制骨架，已补 `config\`、`logs\`）
  - `同级目录的 campus-net-autologin\`（既有无界面 PowerShell 版，保留不动）
  - 开发环境：Python 3.13.16（含 tkinter，官方安装包自带）
- 事实结论（读到的证据，不凭记忆）：
  - 开发所用 Python 的 tkinter 组件**齐全**：`DLLs\_tkinter.pyd`、`tcl86t.dll`、`tk86t.dll`、`zlib1.dll`、`tcl\{tcl8.6,tk8.6}`、`Lib\tkinter\`、`Scripts\pip.exe` 均在 → **做 GUI 无需再安装任何运行时**。
  - 本机**无 MSVC**：`C:\Program Files*\Microsoft Visual Studio\*` 目录与 `vswhere.exe` 均不存在，`upx` 也不存在 → **Nuitka 路线不可行**（它需要 C 编译器）。
  - 目标门户 `http://10.6.6.6/login` 结构（本会话已实测，非推测）：ASP.NET WebForms；`POST /login` 必须携带隐藏字段 `__VIEWSTATE` / `__VIEWSTATEGENERATOR` / `__VIEWSTATEENCRYPTED` / `__EVENTVALIDATION`；表单项为 `ctl00$MainContent$SSOGUITID`（学工号）、`SSOACC`（上网账号）、`SSOPWD`（密码）、`TextBoxCC`（4 位验证码）、`LoginBtn`（提交）；验证码来自 `GET /CheckCode`（PNG，约 1 KB），与 `ASP.NET_SessionId` 绑定；登录失败时返回登录页本身（含验证码输入框）与 `validation-summary-errors` 错误文本。
  - 本机**系统代理** `127.0.0.1:54819`（注册表级）会拦截 pip 的索引请求（实测返回 403 / 空页面），仅 `unset` 环境变量无效 → 装依赖必须显式绕过（`NO_PROXY=*` 或直连）。
  - 既有 `campus-net-autologin` 的流程设计可借鉴：登录遵循「探测在线 → 抓页面 → POST → 复检」四步，幂等（已在线即退出）。其代码为 PowerShell，本项目不复用代码，但沿用该流程与幂等原则。

## 3. 目标与范围

- 目标：提供一个带原生界面的便携 exe；双击显示「联网设置」窗口，自动识别验证码完成登录（失败可手输 4 位），支持记住密码与开机自动登录。
- 包含：
  1. GUI 入口：仿截图布局（学号 / 上网密码 / 记住密码 / 开机自动登录 / 连接 / 隐藏 / 退出 / 状态日志框）。
  2. 登录核心：在线探测 → 取隐藏字段与验证码 → OCR 识别 → POST → 按响应判成败 → 失败换图重试（上限 3 次）。
  3. 验证码显示：窗口内展示图片，点击换一张；识别失败时聚焦输入框等待手输。
  4. 记住密码：勾选后写入 `config\config.json`（已在 `.gitignore` 排除），取消则不落盘。
  5. 开机自动登录：勾选后生成启动文件夹 `.lnk`（带 `--silent` 参数），取消即删除；`--silent` 不显示窗口，后台登录并以原生提示反馈结果。
  6. 日志：`logs\` 按月分文件，UTF-8 无 BOM。
  7. 打包：`scripts\build.ps1` 产出两个目标 —— `lite`（无 OCR，约 20 MB）与 `full`（含 ddddocr，约 160 MB）；产物进 `build\`（已 gitignore）。
  8. 状态与注销：读取门户「断开网络」页解析「当前用户 IP / 当前在线状态」并显示在状态栏；提供「断开网络」按钮（输入验证码后提交注销），并在登录前后自动刷新状态。
  9. 入口与声明：状态栏右侧提供打开官方平台主页（`portalHome`）的按钮；界面底部与 `README.md` 含免责声明（定位为个人便利性连接工具）。
- 不包含：
  - 不修改、不破解门户认证逻辑；不做账号爆破、流量劫持、批量登录。
  - 不写注册表（含 Run 键）；不安装系统服务。
  - 不触碰 `campus-net-autologin` 的任何文件。

## 4. 选型与复用（必填，禁止重复造轮子）

**检索记录**

- 检索时间：2026-10-13
- 检索渠道（≥2 个）：GitHub / PyPI / 技术对比文（打包与 OCR 引擎对照）/ 本机环境清点
- 关键词：`校园网 portal 自动登录 GUI`、`captcha OCR chinese windows`、`PyInstaller Nuitka onefile 体积 误报`、`RapidOCR ddddocr license`、`tkinter exe 分发`
- 辅助命令：`powershell -NoProfile -ExecutionPolicy Bypass -File <临时脚本目录>\find-repos.ps1 -Keyword '<关键词>' -Language python -MinStars 200 -OutFile <临时输出目录>\repos-search.md`（本次未执行，改用公开检索留痕；如需补跑可追加）

**候选评估（≥2 个候选）**

| 候选 | 地址 | 星标 | 最近提交 | License | 依赖/体积 | 是否跑通 demo | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tkinter（GUI） | Python 标准库（PSF） | — | 随 Python 更新 | PSF-2.0 | 0 依赖，exe 增量约 8 MB | 是（组件齐全） | **直接使用** |
| PySide6（GUI） | pypi.org/project/PySide6 | — | 活跃 | LGPL-3.0 | 约 150 MB 依赖，exe 300 MB+ | 未跑 | 淘汰（分发体积过大） |
| PowerShell + WinForms（GUI） | .NET 自带 | — | — | MIT / .NET | 0 依赖 | 语法可行 | 淘汰（无法复用 ddddocr；`.ps1` 默认 Restricted 不利于分发） |
| ddddocr（OCR） | github.com/sml2h3/ddddocr | 14.6k | 2026-03 | **MIT** | numpy / onnxruntime / Pillow / opencv，约 140 MB | 是（本会话 3.13.12 实测：10/10 输出 4 位，抽样准确率约 60~80%） | **直接使用** |
| RapidOCR（OCR） | github.com/RapidAI/RapidOCR | 4k+ | 活跃 | **Apache-2.0** | 约 15 MB（onnx 系） | 未跑 | 备选（通用 OCR 非验证码专用，体积更小） |
| PaddleOCR（OCR） | github.com/PaddlePaddle/PaddleOCR | 45k+ | 活跃 | Apache-2.0 | 依赖 paddlepaddle，体积大 | 未跑 | 淘汰（依赖过重） |
| PyInstaller（打包） | pypi.org/project/pyinstaller | 12k+ | 活跃 | GPL-2.0 + 例外（**产物不受 GPL 约束**） | 构建期依赖 | 是（本会话已成功产出 exe） | **直接使用** |
| Nuitka（打包） | nuitka.net | — | 活跃 | Apache-2.0 | **需 MSVC** | 否 | 淘汰（本机无 C 编译器；留作后续优化项，见第 6 节） |
| cx_Freeze（打包） | pypi.org/project/cx_Freeze | — | 活跃 | MIT | 构建期依赖 | 否 | 淘汰（不支持 `--onefile`） |

**决策**

- 最终选择：**Python 3.13.16（现成）+ tkinter 界面 + ddddocr 验证码识别 + PyInstaller 单文件 exe**。
- 理由：
  1. 用户选定「OCR 自动识别」，而 ddddocr 只存在于 Python 生态 —— 选 PowerShell 路线等于放弃该需求；
  2. 分发友好：单 exe 双击即用，目标机器无需 Python、无需改执行策略；PowerShell 路线要求对方会绕过 Restricted；
  3. 本机零新增安装：开发环境已具备 tkinter 与 pip，无需安装任何运行时；
  4. Nuitka 虽体积更小、杀软误报更低，但本机无 MSVC 暂不可行，留作后续优化（见第 6 节）。
- 落位：项目虚拟环境 `<仓库根>\.venv\`，依赖锁版本写入 `requirements.txt`；运行时复用 `python.exe`。
- 若不采用任何现成方案，写明「为什么不复用」：GUI 与验证码识别均**复用现成能力**，未重复造轮子；仅登录协议对接与界面布局为自研（门户结构独有，无现成库可套）。
- 许可合规：tkinter = PSF-2.0；ddddocr = MIT（保留版权声明，可商用）；PyInstaller 为 GPL-2.0 + 例外，**打包产物不受 GPL 传染**；RapidOCR = Apache-2.0（备选）。以上均允许闭源分发，无 License 传染风险。

## 5. 步骤拆解

| 步骤 | 动作 | 输入 | 输出 / 影响文件 | 完成判据 |
| --- | --- | --- | --- | --- |
| 1 | 建骨架与目录 | `_TEMPLATE` | `GUIT-net-login\{src,tests,docs,scripts,config,logs}` | 目录存在（已完成） |
| 2 | 写方案与确认记录 | 现状核对、检索结果 | `docs\PLAN.md`、`docs\CHANGELOG.md` | 本文件 + 用户确认 |
| 3 | 写配置样例 | 门户字段结构 | `config\config.sample.json` | `ConvertFrom-Json` 可解析 |
| 4 | 建项目 venv 并装依赖 | Python 3.13 + 清华源 | `.venv\`、`requirements.txt` | `pip list` 含 ddddocr / pyinstaller |
| 5 | 写登录核心 | 门户协议事实 | `src\portal_client.py` | 静态检查通过 |
| 6 | 写 GUI 入口 | 用户截图 | `src\app.py`（含 `--silent` 分支） | 静态检查通过 |
| 7 | 写自启与打包脚本 | 启动文件夹规范 | `src\autostart.py`、`scripts\build.ps1` | PS 语法解析零错误 |
| 8 | 静态验收 | 全部源码 | — | 第 7 节静态命令全绿 |
| 9 | 打包与实测（需批准） | 源码 + venv | `build\GUIT-net-login-lite.exe`、`...-full.exe` | 双击可登录、exe 可脱离 Python 运行 |

## 6. 风险与回滚

- 可能破坏：
  1. **杀软误报**：PyInstaller `--onefile` 在部分杀软下会被拦截（分发场景的已知痛点）→ 应对：默认出 `onefile`；若误报则改出 `onedir` 目录版并打 zip，README 写明加白名单方法；后续可评估装 MSVC 转 Nuitka。
  2. **ddddocr 与 Python 版本**：官方声明最高支持 **3.12**，本机为 **3.13.16**（本会话已在 3.13.12 实测通过，3.13.16 待首次运行确认）→ 若初始化失败，回退：只构建 `lite`（纯手输）版本，或另行安装 Python 3.12。
  3. **离线装不了依赖**：未登录校园网时 pip 不可用且系统代理拦截 → 应对：`NO_PROXY=*` 直连清华源；必要时复用本会话已下载的 wheel 目录（`本机缓存的 wheel 目录`）离线安装。
  4. **重复登录被门户踢线**：默认先探测在线状态，在线则不提交。
  5. **明文口令**：勾选「记住密码」时 `config\config.json` 为明文 → 已由 `.gitignore` 排除；DPAPI 加密列为后续增强项，不阻塞本次交付。
- 备份位置：本项目为新建，不覆盖任何既有文件，无需备份；若后续调整既有项目，先备份至 `<备份目录>\`。
- 回滚步骤：
  1. 取消开机自启：删除 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\` 下本项目生成的 `.lnk`；
  2. 清除本地口令：删除 `config\config.json`；
  3. 整体回滚：删除 `<仓库根>\` 整个目录，无系统残留。

## 7. 验收标准

> 仅静态检查（`工作区规范` 第 5 节）：默认只写 lint / 类型检查 / 结构校验命令；需要动态命令（跑程序、测试、服务）时必须标注「（需批准）」。

```powershell
# 1) Python 语法与静态检查（不执行程序）
python.exe -m py_compile (Get-ChildItem 'src\*.py').FullName
python.exe -m ruff check '.\src'

# 2) 脚本语法解析（AST，不执行）
powershell -NoProfile -Command "Get-ChildItem 'scripts\*.ps1' | ForEach-Object { $e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($_.FullName,[ref]$null,[ref]$e); if($e){'FAIL '+$_.Name; $e|%{$_.Message}} else {'OK '+$_.Name} }"

# 3) 配置结构校验
powershell -NoProfile -Command "Get-Content 'config\config.sample.json' -Raw -Encoding UTF8 | ConvertFrom-Json | Format-List portalUrl"

# 4) 编码校验（.ps1 需 UTF-8 with BOM；.py/.json/.md 需 UTF-8 无 BOM）
powershell -NoProfile -Command "Get-ChildItem '.' -Recurse -Include *.ps1,*.py,*.json,*.md | ForEach-Object { $b=[byte[]](Get-Content $_.FullName -Encoding Byte -TotalCount 3); '{0} BOM={1}' -f $_.Name, ($b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) }"

# 5) 依赖清单
powershell -NoProfile -Command "Get-Content '.\requirements.txt' -Encoding UTF8"
```

**动态验收命令（如有；需先说明为什么静态不够、影响与回滚、期望证据，获批后执行）**

```powershell
# 批准前留空。静态检查无法证明「能登录」与「exe 可脱离 Python 运行」，故需动态验证：
#   a) 源码方式：.venv\Scripts\python.exe src\app.py
#   b) 打包方式：build\GUIT-net-login-full.exe
# 影响：向校园网门户提交一次登录（GET 取页面 + POST 表单），不改任何系统设置。
# 回滚：无持久化改动；删除 config\config.json 即清除本地口令。
# 期望证据：界面提示登录成功；联网恢复（可打开外网页面）；logs\ 追加一条成功记录。
```

## 8. 确认记录

| 时间 | 确认方式 | 内容 |
| --- | --- | --- |
| 2026-10-13 11:55 | 用户原始需求 | 「帮我做成一个小应用快速登录」→ 明确要 portable 原生界面（附「联网设置」截图） |
| 2026-10-13 12:06 | AskUserQuestion | 项目位置 `Projects\GUIT-net-login`；界面精简版仿截图；自启用启动文件夹快捷方式 |
| 2026-10-13 12:09 | AskUserQuestion | GUI 由「哪个方便分发给别人」倒推 → 单文件 exe；验证码 OCR 自动 + 手输兜底；旧项目新建并存 |
| 2026-10-13 12:15 | 用户答复「开始」 | 确认第 2~7 节方案，进入实现 |
| 2026-10-13 12:31 | 用户补充需求 | 「上网不仅要学号还要上网账号，也就是手机号」→ 界面新增「上网账号」必填项，`config_store.has_credential` 与表单校验同步收紧 |
| 2026-10-13 12:36 | 待用户实测 | 真实账号登录验证（字段名、验证码大小写敏感性、结果判定） |
| 2026-10-13 12:47 | 用户补充需求 | 角落加官方平台入口按钮；填入免责声明（已实现） |
| 2026-10-13 13:00 | 用户补充需求 | 「官网还有个显示用户连接状态的和断开网络连接，帮我完善」→ 新增状态栏与「断开网络」注销功能（已实现，注销提交路径待用户实测） |
