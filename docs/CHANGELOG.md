# 变更记录（CHANGELOG）

格式：`YYYY-MM-DD HH:mm | 操作 | 影响文件 | 验证结果 | 回滚点`

| 时间 | 操作 | 影响文件 | 验证结果 | 回滚点 |
| --- | --- | --- | --- | --- |
| 2026-10-13 12:14 | 由 `_TEMPLATE` 复制生成初始骨架，补建 `config\`、`logs\` | 全部 | 目录结构已核对 | 无（新建，可直接删目录） |
| 2026-10-13 12:16 | 编写 `docs\PLAN.md`（需求澄清 6 项、现状核对 6 条事实、选型 9 候选评估、步骤 9 步、风险 5 项、静态验收 5 条） | `docs\PLAN.md` | 待用户确认方案 | 无（文件为纯新增） |
| 2026-10-13 12:17 | 编写 `README.md`（占位，待实现后补运行方式） | `README.md` | 未验证 | 无（文件为纯新增） |

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

