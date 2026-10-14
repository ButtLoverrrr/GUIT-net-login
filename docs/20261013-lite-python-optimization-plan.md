# 不更换语言栈的 lite 体积优化方案

- 日期：2026-10-13。
- 目标：在 Python + tkinter + PyInstaller 不变的前提下压缩 lite 版。
- 当前基线：`build/GUIT-net-login-lite.exe` 约 19.4 MiB，以同一源码、同一解释器重新构建的基线为准。
- 状态：仅完成规划，未修改源码，未构建，未运行 GUI。

## 1. 结论先行

lite 没有 OCR、ONNX Runtime、OpenCV 和 NumPy，当前主要体积来自 Python 运行时、Tcl/Tk、Pillow、pystray 以及 PyInstaller 单文件封装。

推荐分两步：

1. **低风险版**：lite 改为仅使用 Tkinter 原生 `PhotoImage` 显示验证码，移除 Pillow 和 pystray 的 lite 收集；隐藏按钮改为普通最小化。预期约减少 2–5 MiB，目标区间约 14–17 MiB。
2. **激进版**：在低风险版基础上精确裁剪 Tcl/Tk、Python 标准库和 PyInstaller 隐式模块。预期可能再减少 1–4 MiB，但兼容性风险明显上升，目标区间约 11–15 MiB。

“压到几 MB”在当前技术栈下不应作为承诺。若保留完整 Tkinter GUI 和单文件自包含运行时，**约 10–15 MiB 已是现实目标**；低于 10 MiB 需要牺牲功能、依赖目标机器已有 Python/Tk，或更换原生语言栈。

## 2. 当前依赖与功能事实

现有 `src/app.py`：

- 无条件导入 `tkinter`，因此 Tcl/Tk 是 lite 的核心运行时，不能删除。
- Pillow 用于验证码 PNG 解码、放大、GitHub 图标和托盘图标。
- pystray 用于“隐藏到系统托盘”；不可用时已有 `root.iconify()` 降级路径。
- Tkinter 原生 `PhotoImage(data=base64...)` 已经是 Pillow 失败后的验证码显示兜底，适合 lite 使用，但原始 PNG 格式必须在验收中确认。
- `assets/github.png` 只有在 Pillow 可用时加载；去掉 Pillow 后应让文字链接继续显示，不应保留失效图片逻辑。
- full 必须保留 Pillow：OCR/GUI 当前共享同一个 `app.py`，full 仍需要 Pillow 的图像解码和显示；因此 lite 与 full 的构建参数必须分开。
- `requirements.txt` 同时服务 full 和 lite，不能直接删除 Pillow/pystray 依赖；应通过构建目标和独立依赖说明，或新增 lite 构建依赖集合，避免破坏 full CI。

## 3. 目标与不包含内容

### 包含

- lite 构建不收集 Pillow、pystray、PIL、pystray、ImageTk 和相关动态库。
- lite 验证码改用 Tkinter 原生 PNG 解码与整数倍放大。
- lite 的“隐藏”行为改为窗口最小化；保留按钮和退出逻辑。
- lite 保留手动输入、登录、注销、配置、状态显示、官方平台链接、单实例和开机自动登录。
- full 行为和构建规则保持不变，继续保留 Pillow、pystray 和 OCR 依赖。

### 不包含

- 不修改门户协议、成功判定、账号保存、自启协议或 OCR 模型。
- 不删除 Tcl/Tk，不改为控制台程序，不改为 onedir。
- 不修改 `.venv` 内第三方包源码。
- 不使用 UPX，不引入新打包器，不联网安装依赖。
- 不因体积优化删除 lite 的验证码图片显示、窗口隐藏、托盘之外的现有功能。

## 4. 阶段 L0：建立同源码基线

执行前读取工作区约束、项目方案、本文、`src/app.py`、`scripts/build.ps1`、依赖清单和 CI。先检查 `git status --short`，不得覆盖已有 agent 改动。

备份待修改文件、旧 lite/full 产物和相关构建清单到：

```text
<本机路径>
```

不复制真实 `config.json`、不复制整个 `.venv`。记录：

- 当前源码和构建脚本 SHA-256；
- Python、PyInstaller、Pillow、pystray 版本；
- 基线 lite/full exe 字节数和 SHA-256；
- lite 当前 PyInstaller Analysis/PKG 中 Pillow、pystray、Tkinter/Tcl/Tk 的资源列表。

用同一源码、同一 `.venv` 重新构建 lite，得到可比较基线。若只使用历史 19.4 MiB，不得据此计算本次收益。

## 5. 阶段 L1：去除 lite 的 Pillow 与 pystray

### 5.1 源码改造

建议新增一个构建目标标记，例如通过环境变量或独立模块：

```python
LITE_BUILD = os.environ.get("GUIT_LITE_BUILD") == "1"
```

但不要让运行时依赖缺失通过大量 `try/except` 静默掩盖。更推荐把 GUI 的可选能力拆成小模块，或让构建脚本为 lite 排除对应模块，同时源码已有的 `HAS_PIL` / `HAS_TRAY` 降级保持可用。

lite 具体行为：

1. `_show_captcha()` 直接使用 `tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))` 和 `.zoom(CAPTCHA_ZOOM)`。
2. 如果 Tk 原生无法解码门户实际 PNG，停止该方案，不要自动引入完整 Pillow；可以评估只引入一个更小的 PNG 解码实现，但必须先做 License、体积和准确性评估。
3. lite 不读取 `assets/github.png`，始终显示“项目地址”文字链接；full 保持现有图标。
4. lite 的 `_on_hide()` 直接调用 `root.iconify()`，不创建 pystray 线程、菜单或图标；full 保持托盘逻辑。
5. lite 不调用 `_tray_image()`、`_tray_show()`、`_tray_quit()` 和 `_stop_tray()` 的 pystray 分支；退出时直接销毁窗口。保留无副作用的通用清理即可。
6. 应用入口、单实例初始化和 tkinter 导入顺序保持不变。

优先采用条件模块或独立 `lite_features.py`，避免让 full/lite 的分支散落在 976 行 `app.py` 中。任何 src 改动必须静态检查，且只为上述 lite 需求服务。

### 5.2 构建改造

`build.ps1`：

- full 的 hidden imports 和 Pillow/pystray 收集保持原样；
- lite 增加：

```text
--exclude-module PIL
--exclude-module PIL.Image
--exclude-module PIL.ImageTk
--exclude-module pystray
```

实际参数以 PyInstaller Analysis 结果为准，不能只凭参数名判断已经排除。若 Pillow 被其他依赖间接引入，必须检查 Analysis/PKG 后补充最小排除规则；排除规则不能影响 full。

不要从全局 `requirements.txt` 删除 Pillow/pystray，因为 full 仍需要它们。可在文档中注明：lite 运行产物不含二者，构建环境仍从完整依赖清单安装。

清单检查器应增加 lite 断言：

- 禁止 `PIL/`、`pystray/`、`ImageTk`、`pystray._win32`；
- 仍存在 tkinter/Tcl/Tk 运行时和应用资源；
- full 的上述项必须继续存在；
- OCR 相关禁止项继续按现有阶段 A 规则检查。

### 5.3 L1 验收

静态：

- Python AST 检查源码；PowerShell AST 检查脚本；`git diff --check`；编码和 CRLF 检查。
- 读取 Analysis/PKG/PYZ 清单，确认 lite 没有 Pillow、pystray、OCR、OpenCV、ONNX Runtime、NumPy；确认 full 未误删 Pillow/pystray。
- 只读检查构建命令和排除规则，不运行 exe。

动态（需批准）：

- 在隔离目录构建同源码基线 lite 与 L1 lite；记录字节数、SHA-256 和缩减率。
- 在无门户请求、无真实配置、自启禁用的环境打开 L1 lite。
- 显示至少一张代表性的门户 PNG；测试放大、换图、手动输入、登录请求模拟、注销请求模拟、窗口最小化/恢复、退出。
- 确认没有尝试导入 Pillow/pystray，`HAS_PIL=False`、`HAS_TRAY=False` 的降级路径正常。
- full 构建和启动回归：验证码显示、托盘隐藏/恢复、GitHub 图标不变。

L1 失败即回滚源码/构建规则；不能通过时保留当前 19.4 MiB 版本。

## 6. 阶段 L2：精简 PyInstaller 与 Python 隐式内容

只有 L1 通过后才评估。每次只做一项变更、构建并记录，不能批量排除后无法定位故障。

候选顺序：

1. 基于 Analysis 查看未使用的标准库隐式导入，排除明确与入口无关的测试、开发工具和平台模块；
2. 精简资源，只保留 lite 使用的 `assets/app.ico`、必要 PNG/字体资源；当前 `assets/github.png` 若 L1 已不使用可不收集，但不能删除源文件而影响 full；
3. 评估 Tcl/Tk 资源是否有未使用语言包/演示文件，优先只删除明确不被 Tk 加载的内容；不得删除 `tcl86t.dll`、`tk86t.dll`、核心 `tcl`/`tk` 脚本、zlib 或 `_tkinter.pyd`；
4. 评估 PyInstaller onefile 启动壳是否存在可安全选项。不要使用 UPX，除非另行批准并做杀软与启动回归。

L2 不允许凭经验加入大范围 `--exclude-module`。每项排除必须有 Analysis 证据、启动回归和回滚点。目标是约 11–15 MiB，不保证；若收益小于 0.5 MiB 或风险无法隔离则停止。

## 7. 阶段 L3：不推荐的激进选项

以下不纳入默认方案，只作备选：

- 将 lite 改成 onedir 后压缩为 zip：下载包可能更小，但不再是单文件 exe，用户体验和杀软行为改变。
- 依赖目标机器已有 Python/Tk：可将程序压到几百 KB，但不满足当前“对方电脑无需安装 Python”。
- 手工裁剪 Python 标准库或 Tcl/Tk 核心：风险高，不建议。
- UPX 压缩：可能减少文件大小，但增加杀软误报与启动兼容性风险，收益必须与现有 onefile 压缩实测比较。

## 8. 推荐验收标准与交付物

L1/L2 每次候选都应产生：

- `build-size-results.md`：基线/候选 exe 字节数、MiB、缩减百分比、Analysis/PKG/PYZ 摘要；
- 构建命令、退出码、Python/依赖版本、产物 SHA-256；
- lite GUI 动态结果和 full 回归结果；
- 未验证事项、风险、备份和回滚路径；
- `docs/CHANGELOG.md` 记录操作与静态/动态验证等级。

通过条件：

1. lite 不含 Pillow、pystray 和 OCR 依赖；
2. lite 可以显示实际 PNG 验证码，手动连接/注销流程不被改变；
3. lite 隐藏按钮改为最小化且可恢复；
4. full 仍有 Pillow、pystray、图标和托盘功能；
5. 基线对比显示体积下降；
6. 没有真实门户提交、真实凭据输出或自启副作用；
7. 未获用户批准不替换正式 build、不提交、不推送、不触发 Release。

## 9. 可复制给其他 agent 的执行指令

```text
请在 <本机路径>
先完整读取 <本机路径>
docs\20261013-lite-python-optimization-plan.md、
docs\20261013-size-reduction-plan.md、
docs\20261013-size-reduction-agent-handoff.md。

默认只执行 L0/L1 的代码审查、必要实现和静态检查；L2、构建、OCR/GUI 运行、
联网安装、真实门户请求、自启修改、正式产物替换、提交/推送/Release 均未授权。
先检查 git status，保护现有 agent 改动并按方案备份，不读取真实 config.json。

目标：不换 Python + tkinter + PyInstaller，lite 去除 Pillow 和 pystray 的运行时收集；
验证码改用 Tkinter 原生 PhotoImage；“隐藏”改为最小化。full 必须保持 Pillow、
pystray、托盘、图标和 OCR 行为。不要从全局 requirements.txt 删除 full 所需依赖，
不要改 site-packages，不改门户、认证、配置、自启核心逻辑。

先核对 Tk 原生 PNG 是否能支持实际图片；若无法证明，不要删除 Pillow，停止并报告。
将构建排除规则限定 lite，更新清单检查器，确保 lite 无 PIL/pystray/OCR/cv2/onnxruntime/
numpy，full 仍完整。源码/脚本静态检查、清单分析和 git diff --check 后再报告。

动态构建和 GUI/无 Python 验收必须另行申请；申请时给出隔离目录、命令、影响和回滚。
最终交付最小代码差异、体积基线/候选对比、docs\CHANGELOG.md 记录和未验证事项。
``` 
