# 体积压缩执行交接手册

- 项目：`D:\Dev\Projects\GUIT-net-login`。
- 日期：2026-10-13。
- 配套方案：`docs/20261013-size-reduction-plan.md`，必须完整读取。
- 本文作用：把方案转为可执行步骤，供其他 agent 接手；本次只编写文档，不批准代码实施、动态执行或发布。

## 1. 当前状态与优先级

读取时工作区已有阶段 A 候选实现：`scripts/build.ps1`、`scripts/hooks/hook-cv2.py`、`scripts/check-bundle.ps1`。原方案第 10 节记录静态检查通过、未构建、未做 OCR/GUI 动态验证。接手时重新核对状态和最新文件，不能将他人的验收记录当成本次亲自验证的结果。

执行顺序：审查现有实现 → 补缺 → 静态验收 → 获批隔离构建 → 离线 OCR/GUI 验收 → 结果报告。默认仅阶段 A，B/C 不自动启动。

阶段 A 目标：只保留默认 `common_old.onnx`，排除闲置 `common.onnx`、`common_det.onnx` 和 FFmpeg DLL；保留 cv2、ONNX Runtime、Pillow、NumPy 与现有识别行为。full 120 MiB 为待验证目标，不能保证。lite 当前约 19.4 MiB，主要做回归检查，本轮不追求进一步裁剪。

## 2. 接手前必须核对的事项

以下为交接审查项，不表示最新文件必然仍存在对应问题。实施 agent 应逐条读取当前文件后给出结论。

1. **上游许可**：自定义 cv2 hook 沿用 contrib hook 的实现，而已读取的上游文件包含 `Copyright (c) 2020 PyInstaller Development Team`、`GPL-2.0-or-later`。核对候选是否保留版权、SPDX、适用许可文本及修改说明；不要将其标成 MIT，也不要假定打包例外覆盖所有自定义 hook 源码分发。许可不清楚时停止发布并说明，可另行采用基于公共接口的最小过滤实现。
2. **TOC 完整解析**：候选清单检查器使用文本解析。原方案记录修复过单行条目漏检；接手必须核对最新实现并用单行、多行、转义路径、未知结构样例验证。优先采用标准库 `ast.literal_eval` 解析 Python 字面量，禁止 `eval`/`exec`。如果保留文本解析，必须证明完整覆盖并在未知格式时失败，不能只报告“解析到了一些条目”。
3. **资源与模块分开检查**：PKG 中的 PYZ 是一个归档条目。PKG 检查不能证明 PYZ 内未包含 `ddddocr.api` 等模块；应同时读取 PYZ/Analysis 清单，兼容点分模块名与文件路径。
4. **FFmpeg 匹配范围**：按目标文件 basename 匹配 `opencv_videoio_ffmpeg*.dll`，覆盖包目录、根目录及其他目录，不只匹配 `cv2/` 前缀。
5. **退出码**：若检查 `.ps1` 使用 `exit`，核对其父脚本调用方式。推荐独立 `powershell -File` 子进程并立即检查其退出码，避免退出父构建流程。禁止依据未启动原生命令的脚本调用推断 `$LASTEXITCODE`。
6. **lite 保留项**：Pillow/ImageTk、pystray、Tkinter/Tcl/Tk、应用图标和验证码显示必须保留。修正“lite 排除 PIL”等过时注释。不要为了体积数字削减已有功能。
7. **证据来源**：hook 注释中声称 PE 导入表不依赖 FFmpeg，应找到实际静态检查命令与结果；找不到则标记未复核，注释不能当成运行兼容性证据。

## 3. 操作 0：授权、读取、任务清单

完整读取工作区 AGENTS、FOLDER_INDEX、项目局部指令、方案、本文、构建脚本、候选 hook/检查器、依赖清单、发布工作流和相关 CHANGELOG。维护 todo，记录用户批准的范围。

只读核对命令（Windows PowerShell，项目根目录）：

```powershell
Set-Location 'D:\Dev\Projects\GUIT-net-login'
git status --short
git diff -- scripts/build.ps1
git diff --check
Get-ChildItem scripts -Recurse -File
Get-ChildItem .venv\Lib\site-packages\ddddocr -Filter *.onnx | Select-Object Name, Length
Get-FileHash .venv\Lib\site-packages\ddddocr\common_old.onnx -Algorithm SHA256
```

新文件不出现在普通 git diff 中，须单独读取。不得读取或输出真实 `config.json` 凭据；本任务不需要它。

输出：当前状态、真实模型选择、字符集位置、已安装依赖版本、阶段 A 待修事项、授权边界。无法读取关键文件时停止依赖该文件的操作。

## 4. 操作 1：备份并固定同源码基线

在用户授权实施后、修改已有文件前备份；不覆盖现有备份。

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$repoRoot = 'D:\Dev\Projects\GUIT-net-login'
$backupRoot = "D:\Dev\temp\output\backup-$(Get-Date -Format 'yyyyMMdd')\GUIT-net-login-size-reduction-$stamp"
$runRoot = "D:\Dev\temp\output\GUIT-net-login-size-reduction-$stamp"
```

备份实际待修改文件、旧 full/lite exe、相关 spec/TOC。用独立目录、逐文件复制，记录相对路径、SHA-256、字节数、Git 状态；空间不足停止。不要复制真实配置、整份 venv 或 `.git`，不要 `git reset --hard`。

准备 `$runRoot\baseline` 和 `$runRoot\candidate` 工作副本，仅复制必要 src/assets/scripts/依赖清单。两者使用同一份当前业务源码与原环境，保留他人业务改动。

现有构建脚本将解释器和模型固定在项目 `.venv`，复制副本不能直接构建。应增加可选 `-PythonPath` 参数，默认仍使用原值；显式传入原项目 `.venv\Scripts\python.exe`，模型路径依据所选环境定位，不能依据副本里的不存在 `.venv` 定位。阶段 A 已授权代码范围应包含该参数；若无法定位环境则失败，不自动安装依赖。

baseline 副本仅恢复压缩前收集规则：`--collect-all ddddocr`、`--collect-all onnxruntime`、`--collect-binaries cv2`，不使用过滤 hook及候选禁止项校验。candidate 使用候选规则。两者输出写各自 build；备份差异。历史 160.4 MiB exe 只供参考，不能代替同源码基线。

## 5. 操作 2：补齐阶段 A 实现

允许影响：构建脚本、cv2 hook、清单检查器；必要时新增 `scripts/check_bundle.py`、许可文件、构建说明和 CHANGELOG。不改 src、模型、依赖版本、认证、自启或 CI。

具体完成条件：

- full 精确添加 `common_old.onnx` 到 `ddddocr/`，保留代码、内联字符集、许可和元数据；去掉 ddddocr 全量数据收集。
- 同时移除 full 的 `--collect-binaries cv2` 与过滤自动 hook 收集的 FFmpeg，防止 DLL 被重新加回。
- 保留 cv2 配置脚本、hidden imports、扩展定位及源码收集模式；hook 只作用 full。不改 site-packages。
- ONNX Runtime 全量收集先保留，不能未经分析删除核心 DLL/provider 或强行缩小运行库。
- 清单检查器：0=通过，1=断言失败，2=缺失/损坏/无法解析。未知结构失败，报出违规条目，不执行清单引用的代码。
- full 必需：默认模型、cv2 扩展及其实际加载配置、必要 ONNX Runtime 库。禁止：闲置模型、任意目录 FFmpeg；核对资源和 PYZ 模块中的未使用 API。
- lite 禁止 OCR 数据/模块（ddddocr/cv2/onnxruntime/numpy/sympy/matplotlib），界面依赖必须存在。路径布局允许随实际 wheel 变化，不为固定文件名误删必需项。

输出：最小差异、许可来源说明、清单断言、隔离构建参数。不因阶段 A 未达大小目标自动改 OCR 实现。

## 6. 操作 3：静态验收

1. Python `ast.parse` 语法检查修改源码；不导入业务或 hook。PowerShell `Parser.ParseFile` 检查修改 `.ps1`。
2. 检查 UTF-8/行尾：Python/Markdown 无 BOM，中文 `.ps1` 有 BOM，Windows CRLF。
3. 审阅清单检查器后运行只读分析：旧 full 清单预期返回 1，命中闲置模型和 FFmpeg；旧 lite 预期通过既定 lite 规则；缺失/损坏输入返回 2。候选尚未构建时不得称其清单已通过。
4. 检查器数据样例覆盖：单行/多行元组、转义路径、根目录 FFmpeg、PYZ 点分模块、缺默认模型、lite 错收 OCR、未知结构。只解析数据，不执行业务样例。
5. `git diff --check`，单独审阅新增文件。模型和业务源码 SHA-256 与本次基线相同。
6. 完整命令和结果记入 CHANGELOG，缺工具报告未执行，不联网安装。

输出：静态通过的候选，仍未证明可运行。未获动态授权时先交付这些成果，再一次性申请构建/OCR/GUI 验证权限。

## 7. 操作 4：隔离构建（需批准）

申请时提供实际目录、完整命令和预计副作用。构建会执行 PyInstaller/hooks/cv2 配置；OCR 会加载模型。写入限于此次 runRoot，不联网安装、不改原 venv、不写正式 build、不认证、不修改自启。

命令模板：只有 `-PythonPath` 实现并静态通过后才使用，审批时替换成实际绝对路径。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$runRoot\baseline\scripts\build.ps1" -Target all -PythonPath "$repoRoot\.venv\Scripts\python.exe"
powershell -NoProfile -ExecutionPolicy Bypass -File "$runRoot\candidate\scripts\build.ps1" -Target all -PythonPath "$repoRoot\.venv\Scripts\python.exe"
```

记录完整日志、退出码、版本、full/lite exe 字节数与哈希、PKG/PYZ/Analysis 清单。候选两版检查均通过，TOC 必须与本次产物对应，禁止用旧清单证明新产物。

## 8. 操作 5：离线识别与界面验收（需批准）

A/B 使用至少 100 张有代表性的固定离线验证码 PNG。可用现有已授权样本；缺样本报告缺项，不私自采集门户验证码。等价比较无需标签；准确率必须有人工标签。C 则至少 500 张标注验收样本，静态量化的校准集与验收集分开。

记录原始 OCR 输出和 OcrEngine 包装后输出，基线/候选逐张一致；没有标签只报告输出一致率及有效四位比例，不称其为准确率。

仅在原 venv 导入 OCR 比较，不能证明 exe 可用。必须明确验证候选打包环境 `available() == True`，避免静默降级误判通过。不要导入 app.py 做普通 OCR 对比，它在模块顶层占用单实例端口。

准备专用离线比较脚本，先静态审阅，再提交实际参数和命令。若使用专用打包诊断入口，它必须复用同一 OCR 封装、模型与收集规则，但诊断包通过不能替代正式 exe 冒烟。若要给正式入口新增离线 self-test 参数，属于超出阶段 A 的 src 改动，先说明并另获授权；必须在单实例和 GUI 初始化前分流。

GUI 模拟副本须屏蔽门户请求和 `_check_autostart`；操作不走真实配置保存和自启创建路径。验证 full/lite：窗口、固定图片显示、换图、托盘恢复、手输降级、退出。标明模拟点，不把模拟成功当真实认证成功。

正式 exe 的无 Python Windows 验收应在没有本项目自启项、没有真实配置且网络隔离的独立机器进行。证明 full OCR 可用、lite 手输可用，不依赖本机 site-packages。未经批准不启动虚拟机或安装运行时，不做真实登录/注销。

## 9. 操作 6：结果报告、停止与回滚

新增 `docs/size-reduction-results.md`，包含：授权范围、文件差异、Python/依赖版本、模型哈希、baseline/candidate 两版 exe 字节数、缩减百分比、清单结果、样本数/输出差异、命令/退出码、打包 OCR/GUI/独立机器验证、未验证事项、备份位置。

通过条件：静态与候选清单通过、默认模型和识别逻辑未变化、full 体积下降、样本输出一致、打包 OCR 可用、lite 功能保留。120 MiB 为目标，未达单列原因；lite 比同环境基线增加超过 1 MiB 应解释资源差异。

停止条件：许可不清、关键资源缺失、解析不完整、OCR 不可用或结果不一致、真实凭据/自启副作用、需新依赖或扩大范围。缺授权或样本时状态写“候选完成，验收未完整”，不得宣称已交付可运行产物。

回滚：从此次备份逐文件恢复本次改动，保留其他 agent 文件；先比较当前内容，发现并发更新停止覆盖。删除只属于本次的候选文件也须符合用户授权。禁止回退整个仓库。正式产物替换、提交、推送、标签、Release 单独授权；scripts 推送会触发自动发布。

## 10. 可复制给执行 agent 的任务指令

以下文本由用户实际发送给执行 agent 后，授权其中代码实施与静态检查。本文件本身不代替用户授权。

```text
请接手 D:\Dev\Projects\GUIT-net-login 的体积压缩阶段 A。
完整读取工作区约束及 docs\20261013-size-reduction-plan.md、
docs\20261013-size-reduction-agent-handoff.md，按交接手册步骤执行。

我授权你备份待修改文件、审查并完善已有阶段 A 候选代码、完成静态检查和记录。
允许修改构建脚本、cv2 hook、清单检查器，新增必要只读解析脚本/许可文件/文档；
包括为隔离构建增加 PythonPath 参数。不要覆盖其他 agent 的已有成果。
先核验已有静态记录并解决许可、TOC/PYZ 完整检查、FFmpeg 匹配、退出码问题。

只做 A；保留现有模型与识别行为，full/lite 界面功能均保留。
不修改 src、认证、凭据、自启、依赖版本、CI；不改 site-packages，不做 B/C。
未授权构建、OCR/GUI/测试运行、联网安装、真实门户请求、正式产物替换、提交或发布。

完成可审阅候选与静态验收后，一次性给出实际隔离路径、完整动态命令、影响和回滚，
申请构建及离线验收授权；已授权的静态工作不要反复确认。
动态获批后比较同源码同环境基线/候选 full/lite，验证清单、模型哈希、至少 100 张
固定 PNG 输出等价、候选打包 OCR 可用、GUI 和无 Python 环境行为。
缺样本或权限时明确未验证，不把静态通过当可运行证明。

最终交付代码差异、docs\size-reduction-results.md 和 CHANGELOG。
报告实际字节数/缩减率、命令退出码、OCR 对比、lite 回归、限制和回滚位置。
```
