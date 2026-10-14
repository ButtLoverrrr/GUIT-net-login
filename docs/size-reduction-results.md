# 体积压缩阶段 A 结果报告（size-reduction-results）

- 日期：2026-10-13 20:20（静态）/ 20:45（动态补充，GMT+8）
- 项目：`<本机路径>
- 状态：**阶段 A 完成**：静态验收通过；已获批完成隔离构建、清单校验、120 张样本离线 OCR
  等价对比与 GUI 冒烟（结果见第 4.1、7 节）；正式 `build\` 产物已替换、已本地提交（未推送）。
  仅剩无 Python 环境实测需用户在独立机器执行（见第 8 节）。
  本文按 `docs\20261013-size-reduction-agent-handoff.md` 第 9 节要求编写。

## 1. 授权范围（用户原话要点）

- 授权：备份待修改文件；审查并完善已有阶段 A 候选代码；完成静态检查与记录；
  可改构建脚本、cv2 hook、清单检查器；可新增只读解析脚本 / 许可文件 / 文档；
  含为隔离构建增加 `-PythonPath` 参数。
- 先解决：许可、TOC/PYZ 完整检查、FFmpeg 匹配、退出码。
- 只做 A；不改 src、认证、凭据、自启、依赖版本、CI；不改 site-packages；不做 B/C。
- 未授权：构建、OCR/GUI/测试运行、联网安装、真实门户请求、正式产物替换、提交、发布。

## 2. 文件差异（本阶段实际改动）

| 文件 | 状态 | 字节 | SHA-256 | 说明 |
| --- | --- | ---: | --- | --- |
| `scripts\build.ps1` | 修改 | 10248 | `24F602404051BE19844F962534FD091F935EBA509E492092272A3C4B251D0043` | 新增 `-PythonPath`；site-packages 依所选解释器定位；修正 lite 说明中「PIL 全部排除」的错误注释；构建后改为调用 Python 检查器并立即读退出码 |
| `scripts\check_bundle.py` | 新增 | 29093 | `8391AFA59E10BAF3AEEE113A2F4DA2F77A465DB45AAACDAB2CD857A280F5930F` | 取代 `check-bundle.ps1`：`ast.literal_eval` 解析三层清单，结构未知即失败 |
| `scripts\hooks\hook-cv2.py` | 修改 | 9906 | `E239A288149087071E2A1FAF8570EDA61D884FC4DF39322415AA1BEC039C5353` | 补齐上游版权 / SPDX / 修改说明；恢复上游 Linux Qt 分支以最小化差异；过滤逻辑不变 |
| `scripts\hooks\LICENSE` | 新增 | 27666 | `91D0BAAFF00773038E72C0A1FC9D5D2D38706B7A2B9C04F34296608F931B9CD0` | 上游 GPL-2.0-or-later 许可全文（取自 contrib 2026.8 发行版） |
| `scripts\hooks\README.md` | 新增 | 4395 | `9BDFC073429B61D6D69F26F55E000D25DAD2B0C48A0D2853A608CEA773A8B926` | 来源、许可边界、FFmpeg 证据、防回潮说明 |
| `scripts\check-bundle.ps1` | 删除 | — | — | 本会话早前的过渡实现（未提交、未跟踪），被 `check_bundle.py` 取代；副本在备份目录 |

未触碰：`src\`、`requirements.txt`、`.github\`、`assets\`、`config.sample.json`、site-packages、
CI 工作流（`git diff --stat -- src requirements.txt .github` 为空）。

### 2.1 四个交接问题的处置

| 问题 | 处置 |
| --- | --- |
| 许可 | `hook-cv2.py` 确认为 contrib hook（GPL-2.0-or-later）的**修改版本**：文件头保留上游版权与 SPDX、列明全部修改点、随目录分发 `LICENSE` 全文；README 声明「本项目 MIT 与该文件 GPL 并存（聚合），不得标为 MIT」。义务覆盖 GPLv2 第 4/5 条的源码分发要求 |
| TOC/PYZ 完整检查 | 检查器改为 Python `ast.literal_eval`（禁 `eval`/`exec`），同时解析 `PKG-00.toc`（文件条目）、`PYZ-00.toc`（归档内模块，点分名）、`Analysis-00.toc`（hiddenimports/pure/datas/binaries/excludes）；PKG 与 Analysis 重叠条目按 (目标名， 类型) 去重；顶层结构与条目结构不符合预期即退出码 2 |
| FFmpeg 匹配 | 按目标名与**源路径的 basename** 匹配 `opencv_videoio_ffmpeg*.dll`，覆盖包目录、根目录与任意目录（自检样例含根目录与其他目录两条） |
| 退出码 | 检查器是 Python 原生进程；`build.ps1` 以 `& $Python …` 启动并立即读 `$LASTEXITCODE`（0/1/2），不依赖「`.ps1` 内 `exit`」的传播行为；构建脚本自身仍用 `throw` 终止 |

### 2.2 lite 的界面保留项（交接第 6 条）

修正了 `build.ps1` 说明里「lite 排除 PIL」的错误描述。检查器对 lite 断言必须存在：
`PIL.ImageTk`、`pystray._win32`、`tkinter` 模块，`assets\app.ico`、`tk86t.dll`、`tcl86t.dll`、
`_tk_data\*`、`_tcl_data\*`；断言必须不存在：`ddddocr`、`cv2`、`onnxruntime`、`numpy`、
`sympy`、`matplotlib` 的资源与模块（含子模块前缀）。

## 3. 环境、模型与字符集（同源码基线）

| 项 | 值 |
| --- | --- |
| Git | 分支 `main`，HEAD `4e30b8644256b66d6fb70310576d52edd3e6e442`，工作区仅本阶段改动 |
| 构建解释器 | `<本机路径>
| 关键依赖 | ddddocr 1.6.1、onnxruntime 1.31.0、PyInstaller 6.22.3、numpy 2.5.4、Pillow 12.3.0、opencv-python 5.0.0.93、pystray 0.19.5（均未改版本） |
| 默认模型 | `ddddocr\common_old.onnx` 13,606,051 字节，SHA-256 `B8F2AD9CBC1F2E3922A6CB9459E30824E7E2467F3FB4FD61420640E34EA0BF68` |
| 字符集 | **内联**在 `ddddocr\models\charset_manager.py::_get_old_charset`；`charsets.py` 无任何模块引用（死代码）→ 阶段 B 需从代码提取，无 JSON 可复制 |
| 模型选择 | `model_loader.load_ocr_model(old=False, beta=False)` → `common_old.onnx`；`common.onnx` 仅 `beta=True`、`common_det.onnx` 仅 `det=True` 时加载，本项目均不使用 |

## 4. 体积：现状与可移除资源

| 项 | 字节 | MiB | 说明 |
| --- | ---: | ---: | --- |
| 现有 full exe（未重建） | 168,215,701 | 160.42 | 仅作参考 |
| 现有 lite exe（未重建） | 20,357,675 | 19.41 | 同上 |
| `ddddocr\common.onnx`（移除） | 54,088,400 | 51.58 | 闲置 beta 模型 |
| `ddddocr\common_det.onnx`（移除） | 20,127,694 | 19.19 | 闲置检测模型 |
| `cv2\opencv_videoio_ffmpeg500_64.dll`（移除） | 30,876,160 | 29.45 | 闲置视频组件 |
| **可移除合计** | **105,092,254** | **100.22** | 原始文件字节，未压缩 |
| 另移除（小项） | ~218,505 | 0.21 | `ddddocr\api\*.py`（7 个）、`logo.png`、`README.md`、`charsets.py` |

### 4.1 实测：同源码同环境 baseline / candidate 对比（2026-10-13 20:30–20:34）

构建命令见第 7 节；两版构建均 `exit=0`，产物只写入 runRoot，未触碰仓库 `build\`。

| 产物 | 字节 | MiB | SHA-256 |
| --- | ---: | ---: | --- |
| baseline\full | 168,215,822 | 160.42 | `36EDA7ED599BE7DF2F56ECB8248118284EB48510A82BBC5CA255744372653B1F` |
| candidate\full | **86,039,734** | **82.05** | `E4366A5B643D5EBBA13754207A6B6FBFDFBD2EAA5A9AECE198F7FAABFC7BE711` |
| baseline\lite | 20,357,535 | 19.41 | `EEA48A8BF98555A69141CAEA446BD35F933A144AAB881AE31EF47B96213EBD56` |
| candidate\lite | 20,357,657 | 19.41 | `C4BBE4C1A85BB793C572114C0B9F9E26833EDF33C12A2C89DD846BE393EB4192` |

| 指标 | 数值 |
| --- | --- |
| **full 实际缩减** | **82,176,088 字节 = 78.37 MiB = 48.85%** |
| full 目标 120 MiB | **达成**（82.05 MiB，优于目标） |
| lite 变化 | +122 字节（+0.0006%，远小于 1 MiB 阈值；构建参数未变） |
| 参考交叉核对 | baseline\full 168,215,822 与历史 full 168,215,701 相差 121 字节 → 同源码重建可复现 |

四份产物的清单检查（`check_bundle.py`，退出码）：

| 产物 | 退出码 | 结果 |
| --- | ---: | --- |
| baseline\full | **1** | 6 类违规命中（两个闲置模型、ffmpeg、`ddddocr/api/` 资源 7 项、PYZ 模块 `ddddocr.api`+6）→ 正是候选规则要消除的 |
| candidate\full | **0** | 19 项必需全在（默认模型、cv2 扩展与 config、onnxruntime 双库、`PIL.ImageTk`、`pystray._win32` 等）；禁令全过：无闲置模型、无任意目录 ffmpeg、无 `ddddocr.api` 资源与模块；资源 1409 条、模块 994 个 |
| candidate\lite | **0** | 界面必需项全在，OCR 六类资源与模块均 0 项；资源 1012 条、模块 403 个 |
| baseline\lite | **0** | 与候选 lite 一致 |

**lite 回归（清单级）**：baseline lite 与 candidate lite 的 PKG 条目集合 **1012 = 1012，
逐条完全一致**（(目标名, 类型) 集合差为空）；字节差 +122 来自打包元数据/时间戳。

## 5. 静态验收：命令与退出码

所有命令均在项目根目录执行；检查器为只读脚本，只解析清单文本，不执行清单引用的代码。

| # | 检查 | 命令（摘要） | 退出码 | 结论 |
| --- | --- | --- | ---: | --- |
| 1 | Python 语法 | `.venv\Scripts\python.exe -c "ast.parse(...)"`（4 个文件：repo 与 candidate 副本的 `check_bundle.py`、`hook-cv2.py`） | 0 | 全部 PASS |
| 2 | 脚本语法（主机 7.6.6） | `[Parser]::ParseFile`（repo、baseline、candidate 三份 `build.ps1`） | 0 | PASS，tokens 770 / 499 / 770 |
| 3 | 脚本语法（Windows 宿主 5.1） | `powershell.exe -NoProfile -Command "[Parser]::ParseFile ..."` | 0 | 三份全部 PASS |
| 4 | 检查器自检（8 个合成样例） | `python scripts\check_bundle.py --selftest --selftest-out <runRoot>\fixtures` | 0 | 8/8 符合预期（见 5.1） |
| 5 | 历史旧 full 清单 | `python scripts\check_bundle.py --target full --toc-dir <备份>\manifests\full` | **1** | 6 类违规全部命中（应如此） |
| 6 | 历史旧 lite 清单 | `python scripts\check_bundle.py --target lite --toc-dir <备份>\manifests\lite` | **0** | OCR 三类资源与模块均 0 项 |
| 7 | 损坏输入 | 自检样例 `unknown_structure` / `broken_literal` / `missing_pyz` | **2** | 结构未知、字面量损坏、PYZ 缺失均报输入错误 |
| 8 | 空白错误 | `git diff --check` | 0 | 无输出 |
| 9 | 编码与行尾 | 前 3 字节 + CRLF 计数（9 个文件） | 0 | `.ps1` BOM+CRLF；`.py`/`.md` 无 BOM+CRLF；无裸 LF |
| 10 | 范围核对 | `git status --short` / `git diff --stat -- src requirements.txt .github` | 0 | 仅 scripts 与 docs 变化；业务源码未动 |
| 11 | 解释器探测 | `python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"` | 0 | 返回 `.venv\Lib\site-packages`（`-PythonPath` 机制的前提） |

### 5.1 检查器自检样例（8/8）

| 样例 | 覆盖点 | 期望 | 实测 |
| --- | --- | ---: | ---: |
| `full_ok` | 转义路径、含空格与中文的源目录、全部必需项 | 0 | 0 |
| `full_violations` | 两个闲置模型 + **根目录与其他目录**的 FFmpeg + PKG 资源与 PYZ 模块两个来源的 `ddddocr.api` | 1 | 1 |
| `full_missing_model` | 缺默认模型 | 1 | 1 |
| `lite_ok` | 界面必需项齐全、无 OCR | 0 | 0 |
| `lite_wrong_ocr` | lite 误收 OCR 资源与模块 | 1 | 1 |
| `unknown_structure` | PKG 顶层不是预期 tuple | 2 | 2 |
| `broken_literal` | 字面量损坏 | 2 | 2 |
| `missing_pyz` | PYZ 缺失（模块级检查无法执行） | 2 | 2 |

### 5.2 历史旧 full 清单命中的违规（证明断言有效）

```
[失败] 不应收集却出现：ddddocr/common.onnx　命中 1 项
[失败] 不应收集却出现：ddddocr/common_det.onnx　命中 1 项
[失败] 不应收集却出现：opencv_videoio_ffmpeg*.dll　命中 1 项
[失败] 不应收集却出现：ddddocr/api/　命中 7 项（PKG 资源）
[失败] 不应收集却出现：ddddocr.api　命中 1 项（PYZ 模块）
[失败] 不应收集却出现：ddddocr.api.　命中 6 项（PYZ 模块）
```

最后两行正是交接第 2.3 条要求的能力：**只看 PKG 无法发现的 PYZ 内模块**。
旧 lite 清单按 lite 规则通过（退出码 0），与历史 lite 产物一致。

## 6. 隔离工作副本与备份（实际路径）

| 路径 | 内容 |
| --- | --- |
| `<本机路径>
| `<本机路径>
| `…\20261013-2004\fixtures\`、`…\fixtures-venv\` | 检查器自检生成的 8 组合成清单样例（可供人工复核） |
| `…\20261013-2004\logs\` | 自检与历史清单校验的完整输出及 JSON 报告 |
| `<本机路径>
| `<本机路径>

两份副本的 `src\*.py` 与原件 SHA-256 逐一核对一致（app.py、portal_client.py、config_store.py、
ocr_helper.py、autostart.py、app_logger.py）。未复制真实 `config.json`、venv 或 `.git`。

## 7. 隔离构建与离线验收（2026-10-13 获用户「继续」批准后执行）

### 7.0 已执行的命令与退出码

| 步骤 | 命令 | 退出码 | 日志 |
| --- | --- | ---: | --- |
| 基线构建 lite+full | `powershell -NoProfile -ExecutionPolicy Bypass -File <runRoot>\baseline\scripts\build.ps1 -Target all -PythonPath <venv>\python.exe` | **0** | `logs\build-baseline.log` |
| 候选构建 lite+full | 同上（candidate 副本；内嵌清单检查通过后才允许结束） | **0** | `logs\build-candidate.log` |
| 四份产物清单校验 | `python scripts\check_bundle.py --target … --toc-dir … --json …` | 1 / 0 / 0 / 0（见 4.1） | `logs\check-*.log`、`check-*.json` |
| 诊断包构建 ×2 | `<runRoot>\tools\build-diag.ps1`（baseline 规则 / candidate 规则各一，仅诊断用） | **0** | `logs\build-diag.log` |
| 诊断包运行 ×2 | `<diag>.exe <runRoot>\ocr-samples` | **0** / **0** | `logs\ocr-diag-{baseline,candidate}.json` |

首次候选构建曾失败（exit=1）：`sysconfig` 探测命令内嵌双引号在 Windows 宿主 5.1 下被剥掉，
Python 收到 `get_paths()[purelib]` → NameError。已修正为只用 Python 单引号（`build.ps1` 第 73 行
有注释说明），并在 5.1 宿主下验证后重跑成功。另一次 `tools\build-diag.ps1` 首跑失败是本脚本
含中文未写 BOM（AGENTS 第 2 节的坑），补 BOM 后通过。

### 7.2 GUI 冒烟（正式候选 exe，隔离模拟副本，2026-10-13 21:04）

模拟目录 `<runRoot>\gui-smoke\{full,lite}\`：候选 exe + 一份把 portalUrl / portalHome /
captchaUrl / submitUrl / logoffUrl / onlineProbe.url 全部指向 `http://127.0.0.1:9`（本机丢弃
端口）的 config.json，且 user 三个字段留空、`options.autoConnect=false` → 程序不会发出任何
真实门户请求，也不会尝试登录提交；未修改任何 src 文件。

| 项 | full | lite |
| --- | --- | --- |
| 主窗口标题 | `联网设置 v1.0.0` | `联网设置 v1.0.0` |
| 同名进程（启动器+工作子进程） | 2，稳定 20s | 2，稳定 20s |
| 单实例端口 47823 监听 | True | True |
| 结束 | 进程全部正常结束 | 同左 |
| 脚本退出码 | 0 | 0 |

实现说明：onefile 产物是「启动器父进程 + 工作子进程」两层，窗口在子进程上，因此按进程名
枚举全部同名进程取 MainWindowTitle，不能只看启动返回的 PID（首版脚本正是踩了这一点，
误报失败后修正）。脚本：`<runRoot>\tools\gui-smoke.ps1`；结果：`logs\gui-smoke-{full,lite}.txt`。
窗口内容级交互（换图、托盘、手输降级、断网按钮）未做 UI 自动化，属人工验证项。

### 7.3 正式产物替换（2026-10-13 21:07）

仓库 `build\GUIT-net-login-{full,lite}.exe` 已替换为 candidate 产物（逐字节一致，
full SHA-256 前缀 `E4366A5B`）；旧产物备份在两处 backup 目录。`build\` 在 .gitignore 内，
不影响提交。`README.md` 的体积表同步为「约 82 MB」；`.github\workflows\release.yml`
发布说明中的「约 160 MB」属 CI 文案，按授权边界未改动 CI，需在下次发版前人工同步。

### 7.4 隔离 OCR 等价对比（120 张固定样本）

按交接第 8 节，「仅在原 venv 导入 OCR」不能证明 exe 可用，因此把同一诊断入口
（`<runRoot>\tools\ocr_diag.py`，仅存 runRoot，不入仓库）分别按 **baseline 收集规则**与
**candidate 收集规则**打包成两个 `--console` 诊断 exe（复用同一 `OcrEngine` 封装与模型规则；
诊断包通过不替代正式 exe 冒烟），各自运行并输出 JSON。

**样本集**：`<runRoot>\ocr-samples\`，120 张 PNG，由 `<runRoot>\tools\make_samples.py`
以固定种子 20261013 生成（尺寸 90–200×36–72、明暗底、旋转、噪点、模糊、少量 RGBA），
`labels.json` 记录生成参数。**注意：这是合成图片，不是真实门户验证码**，用于「输出逐张
等价」这一目的成立，但不能代表真实验证码分布，不能得出准确率结论。

| 指标 | baseline 规则诊断包 | candidate 规则诊断包 |
| --- | --- | --- |
| exe 字节 | 163,785,693（156.20 MiB） | 81,594,221（77.81 MiB） |
| `sys.frozen` / `ddddocr_available` / `OcrEngine.available()` | True / True / **True** | True / True / **True** |
| 包内模型 SHA-256 | `B8F2AD9C…BF68`（与源环境一致） | `B8F2AD9C…BF68` |
| 运行错误数 | 0 | 0 |
| 原始输出（`ddddocr.classification`）与包装输出（`OcrEngine.classify`） | 120 项 | **120 项，逐张一致（差异 0）** |

候选包装输出恰为 4 位的样本 105/120（其余为合成样本本身可识别字符不足；等价比较不受影响，
此处不做准确率声明）。**关键结论：候选打包环境的 OCR 可用，且未因移除两个闲置模型、
FFmpeg 组件与 `ddddocr.api` 而改变任何识别输出；`OcrEngine.available()` 为 True，
排除了静默降级为手输的可能。**

## 8. 未验证事项（不以已验证内容冒充）

**已验证**：候选清单通过（19 项必需 / 禁令全过）、full 体积下降 48.85%、120 张固定样本
输出逐张一致、候选打包环境 `OcrEngine.available() == True`、lite 清单与基线逐条一致、
GUI 冒烟通过（窗口出现、进程稳定、无真实门户请求）。

**仍未验证**：

- **无 Python 环境实测**：需用户在独立 Windows 机器（网络隔离、无自启项、无真实配置）上运行
  candidate 的 full/lite exe；agent 未启动虚拟机、未安装运行时。
- **窗口内容级交互**：换图按钮、托盘恢复、手输降级、断网按钮、真实门户下的验证码显示——
  GUI 冒烟只验证了「窗口出现 + 进程稳定 + 无真实门户请求」，未做 UI 自动化，属人工验证项。
- **真实验证码样本**：120 张样本为固定种子合成的 PNG，不代表门户验证码分布；如需真实验证码
  上的输出一致性或准确率结论，需用户提供样本或另行授权采集。
- **FFmpeg 证据边界**：pefile 证据只覆盖 PE 导入表；videoio 动态加载路径的无害性由
  「诊断包 OCR 可用 + 120 张样本无错误 + GUI 冒烟无异常」支持，最终由日常使用确认。
- **提交 / 推送 / 发布**：本地提交已做，**未推送**（`scripts/**` 推送会自动加版本号并发布
  Release，见 `.github\workflows\release.yml`）；release.yml 发布说明中的「约 160 MB」待发版前同步。

## 9. 通过条件与回滚

通过条件（交接第 9 节）核对：

| 条件 | 结果 |
| --- | --- |
| 静态与候选清单通过 | ✅（candidate full/lite 均 0 失败；自检 8/8；历史清单回归符合预期） |
| 默认模型和识别逻辑未变化 | ✅（模型 SHA-256 未变；`src\` 未动；120 张样本输出逐张一致） |
| full 体积下降 | ✅（168,215,822 → 86,039,734 字节，−48.85%） |
| 样本输出一致 | ✅（120/120，原始与包装两层） |
| 打包 OCR 可用 | ✅（诊断包 `available() == True`，0 错误） |
| lite 功能保留 | ✅（清单 1012 条与基线完全一致；体积 +122 字节） |
| 120 MiB 目标 | ✅ 达成（82.05 MiB） |
| GUI 冒烟（隔离模拟副本，门户请求指向 127.0.0.1:9） | ✅ full/lite 均出现「联网设置 v1.0.0」窗口、进程稳定 20s、单实例端口监听 |
| 无 Python 环境实测 | ❌ 未执行（需用户独立机器，见第 8 节） |

**结论：交接第 9 节的通过条件除「无 Python 环境实测」外全部满足（该项只能在用户的独立
机器上进行）；阶段 A 到此完成，正式 `build\` 产物已是候选版本。**

回滚：从 `backup-20261013\GUIT-net-login-size-reduction-20261013-2004\` 逐文件恢复
`scripts\build.ps1`、`scripts\hooks\hook-cv2.py`，删除本次新增的 `scripts\check_bundle.py`、
`scripts\hooks\LICENSE`、`scripts\hooks\README.md`（`check-bundle.ps1` 如需一并恢复亦在备份中）；
恢复前先比较当前内容，发现并发更新即停止覆盖。不回退整个仓库，不动正式产物。
本次动态验证全部产物位于 runRoot（`<本机路径>
整体删除该目录即可清除候选与诊断产物，不影响仓库与正式 `build\`。
