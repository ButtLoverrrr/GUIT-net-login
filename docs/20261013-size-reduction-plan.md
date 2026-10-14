# GUIT-net-login 体积压缩方案

- 日期：2026-10-13。
- 状态：**阶段 A 候选完成、静态验收通过**（2026-10-13 20:20，按
  `docs\20261013-size-reduction-agent-handoff.md` 复核并补齐：许可合规、PKG/PYZ/Analysis
  三层清单检查、FFmpeg basename 匹配、退出码、`-PythonPath`；记录见
  `docs\size-reduction-results.md` 与 `docs\CHANGELOG.md`）。**构建与全部动态验证尚未批准、
  未执行**。阶段 B、C 未开始。
- 项目：`<本机路径>
- 推荐顺序：阶段 A 精简打包 → 验收 → 阶段 B 去除 OpenCV 依赖 → 验收；阶段 C 量化单独决策。

## 1. 目标与范围

保持 Windows x64 单文件 exe、现有 GUI、托盘、验证码显示、OCR 自动识别与手输降级。优先减少闲置资源，保留当前模型及识别行为。

不在本次压缩中修改登录协议、认证判据、配置持久化或自启逻辑。不训练新模型，不改全局 Python 或系统 PATH，不直接修改 `.venv` 中第三方源码。

本次规划交付物是本文。实施后的交付物包括修改后的构建配置、产物清单、体积对比和验证记录。任何目标体积均为工程目标，不是静态检查可以保证的结果。

## 2. 现状与证据

本地文件扫描和 `build/_work/full/GUIT-net-login-full/PKG-00.toc` 确认以下内容；体积单位为 MiB，即 1024 × 1024 字节。

| 对象 | 当前体积 | 状态 |
| --- | ---: | --- |
| full exe | 160.4 MiB | 现有产物，未重新构建 |
| lite exe | 19.4 MiB | 现有产物，未重新构建 |
| `ddddocr/common_old.onnx` | 13.0 MiB | 默认 OCR 使用 |
| `ddddocr/common.onnx` | 51.6 MiB | `beta=True` 才选择，当前未使用 |
| `ddddocr/common_det.onnx` | 19.2 MiB | 目标检测模型，当前未使用 |
| `cv2/cv2.pyd` | 82.3 MiB | 当前依赖导入时需要 |
| `cv2/opencv_videoio_ffmpeg500_64.dll` | 29.4 MiB | 视频依赖，当前业务未使用 |
| `onnxruntime/capi/onnxruntime.dll` | 18.4 MiB | 保留，不能因名称相近视为重复 |
| `onnxruntime/capi/onnxruntime_pybind11_state.pyd` | 19.1 MiB | Python 推理绑定，保留 |

`src/ocr_helper.py` 调用 `ddddocr.DdddOcr(show_ad=False)`；本地 ddddocr 1.6.1 的 `models/model_loader.py` 默认选择 `common_old.onnx`。`scripts/build.ps1` 的 `--collect-all ddddocr` 和 `--collect-binaries cv2` 收集了全部模型和视频 DLL。

默认 OCR 路径的缩放、灰度转换和归一化使用 Pillow/NumPy，但 `compat/v1.py` 同时导入检测和滑块模块，预处理模块也在导入时调用 `safe_import_opencv()`。排除整个 cv2 可能导致 OCR 初始化失败，而上层会静默降级到手输，因此验收必须明确证明 OCR 可用。

注意：以上是资源原始体积；PyInstaller 单文件已经压缩，删除资源后的 exe 缩减量不能直接相加推算。现有产物也不保证对应当前未提交源码，实施时应先为同一源码建立可复现基线。

## 3. 选型与复用

本次沿用原 `docs/PLAN.md` 的 ddddocr / PyInstaller 选型，结合本地已安装源码和构建清单评估；没有新增联网检索、安装依赖或运行 demo。关键词：`PyInstaller collect_data_files excludes`、`hook-cv2 ffmpeg`、`ONNX Runtime quantization int8`、`ddddocr common_old beta`。

| 方案 | 复用能力与来源 | License 与兼容性 | 决策 |
| --- | --- | --- | --- |
| 精确收集模型和依赖 | 当前 PyInstaller 6.22.3；https://pyinstaller.org/en/stable/hooks.html | GPL-2.0 + 打包例外；沿用 Windows/Python 3.13 环境 | 阶段 A，首选 |
| 保留原模型，精简推理封装 | 当前 ddddocr 1.6.1 和 ONNX Runtime 1.31.0；https://github.com/sml2h3/ddddocr | ddddocr 与 ONNX Runtime 为 MIT；复用时保留版权及许可，模型许可随上游核对 | 阶段 B，条件执行 |
| ONNX Runtime INT8 量化 | https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html | MIT；需核对算子、CPU 支持和工具依赖 | 阶段 C，可选 |
| UPX 或更换打包器 | 原 PLAN 已评估替代打包器 | 新增工具与兼容性验证成本；UPX 可能增加杀软误报 | 当前不采用 |

不重复实现 OCR 模型或通用量化算法。阶段 B 只封装现有模型需要的预处理和输出解码；若需新增工具、替换供应商或扩大范围，先补充最新上游、包索引检索和许可评估，再申请安装或实施。

## 4. 阶段 A：精简打包，保留现有引擎

目标：保留默认 `common_old.onnx` 和现有 ddddocr 行为，移除两个闲置模型和不需要的视频组件。

| 步骤 | 输入与动作 | 输出 / 影响文件 |
| --- | --- | --- |
| A1 | 记录 Git 状态，备份当前源码及旧产物；读取现有构建清单 | 备份、SHA-256 与基线清单 |
| A2 | 核对 PyInstaller 和 opencv 的实际 hook；将 ddddocr 全量收集改为精确数据收集，保留必要代码、字符集和默认模型 | `scripts/build.ps1`；必要时新增 `scripts/hooks/` 下的 hook |
| A3 | 针对 FFmpeg DLL 做精确过滤；不能仅删除 `--collect-binaries cv2`，因为自动 hook 仍可能收集它 | 同上，构建清单约束 |
| A4 | 增加模型存在断言及闲置模型、视频 DLL 不存在断言，过滤规则限定 full 目标 | 同上；必要时新增静态清单检查脚本 |
| A5 | 经批准构建同源码基线和优化版，用固定样本验证 OCR 与界面功能 | 隔离产物、验证记录 |

收益：移除约 70.8 MiB 闲置模型原始资源，并评估约 29.4 MiB 视频 DLL 的删除收益。初步 full 目标为不高于 120 MiB；实际值取决于打包压缩率。未达目标时报告实测，不为追求数字删减核心依赖。

阶段 A 不改变模型内容，固定样本的原始 OCR 输出应与基线完全一致，lite 的功能和内容不得受 full 过滤影响。

## 5. 阶段 B：去除 OpenCV，保持模型和解码行为

启动条件：阶段 A 已通过，且仍有继续缩小体积的需求；此阶段需要单独确认实现与动态验证范围。

1. 阅读当前引擎完整输入处理、模型输入输出、字符集和重复字符/空白解码逻辑，保存参数与模型 SHA-256。
2. 在项目中新增最小 OCR 推理模块，直接使用 Pillow、NumPy、ONNX Runtime 和原 `common_old.onnx`。保持缩放到高度 64、宽度计算、LANCZOS、灰度、float32 归一化、张量布局及输出解码一致；以完整源码核对结果为准。
3. 保持 `OcrEngine.available()` / `classify()` 的调用接口、惰性初始化和手输降级；不改 GUI 与门户流程。
4. 将所需模型、字符集和上游许可放入明确的项目资源路径，记录来源版本与 SHA-256。不能只复制模型而遗漏匹配字符集。
5. full 打包排除 ddddocr 和 cv2，保留必要 ONNX Runtime DLL、Pillow 和 NumPy。根据实际导入链判断是否可去除 sympy 等间接依赖，不能凭名称过滤。
6. 拆分或整理构建与运行依赖清单，并同步 CI 使用方式。

预计影响：`src/ocr_helper.py`、新增 OCR 模块、模型/字符集资源与许可文件、`scripts/build.ps1`、依赖清单、`.github/workflows/release.yml`、`README.md`。

初步 full 目标：60–90 MiB，属于待验证目标。若为了等价实现需要大量维护代码或结果不能保持一致，则停止阶段 B，保留阶段 A。不得直接修改 site-packages 作为交付方案。

## 6. 阶段 C：INT8 量化，可选

启动条件：阶段 B 已完成或确认不采用；有固定标注样本、明确体积目标，且用户批准量化工具及验证命令。

- 用官方 ONNX Runtime 量化能力，先检查模型权重类型和算子支持，再决定动态或静态量化；不默认整图量化。
- 若采用静态量化，校准集与验收集分开。输出独立量化模型，保留原模型及其 SHA-256。
- INT8 可使被量化的 FP32 权重存储量约降为四分之一，不能据此保证整个 13.0 MiB 模型缩为 3.25 MiB。
- 对完整验证码正确率进行配对比较；建议采用至少 500 张人工标注、无凭据的固定离线样本，包含重复字符和易混淆字符。阈值为验收集完整 4 位正确率不低于基线，且不得出现新的系统性错误；有限样本无法证明总体准确率完全不变。
- 同时记录初始化耗时、推理中位数/P95、最终 exe 体积。无明显收益或兼容性差则保留原模型。

阶段 C 暂不承诺目标大小；运行库不会因权重量化自动减少。FP16、剪枝和训练专用小模型不纳入本轮实施。

## 7. 验收与审批边界

### 静态验收（默认允许）

- `git diff --check`：无空白错误。
- `git diff -- scripts/build.ps1 src/ocr_helper.py requirements.txt .github/workflows/release.yml`：核对范围；新增文件单独读取核对。
- Python AST 解析检查新增/修改源码，不导入业务模块、不运行模型。
- PowerShell `System.Management.Automation.Language.Parser.ParseFile` 检查修改脚本，不执行脚本。
- UTF-8、BOM、CRLF 和 JSON/YAML 结构校验；含中文的 `.ps1` 使用 UTF-8 BOM。
- 阅读构建 TOC 清单，断言阶段 A 仅保留默认模型，阶段 B 无 cv2 和闲置 OCR 模型；TOC 检查只能证明收集内容，不能证明运行成功。
- 使用 `Get-FileHash -Algorithm SHA256` 和文件大小记录基线及产物，禁止把解压体积和 exe 体积混为一谈。

静态工具仅使用已安装版本；没有相应工具时报告未执行，不联网安装。

### 动态验收（需批准，本次尚未批准）

静态检查无法证明裁剪后的 DLL/模型可加载、识别等价或 exe 能在无 Python 环境运行。

- 构建：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1 -Target all`。先为基线与候选准备隔离工作副本，确保脚本只写各自的 build 目录。
- 离线 OCR 比较：新增并先审阅 `tests/compare_ocr.py`，拟执行 `.venv\Scripts\python.exe tests\compare_ocr.py --samples tests\fixtures\captcha --report build\ocr-comparison.json`。参数与实现完成后再提交具体审批，不在规划阶段执行。
- GUI 冒烟：隔离副本运行 `build\GUIT-net-login-full.exe` 和 lite，测试图片显示、托盘与手输降级。须提前替换门户调用为本地模拟，避免启动预取访问真实门户。
- 无 Python 环境冒烟由用户在独立 Windows 机器进行，验证资源加载和 OCR；不因本计划启动虚拟机或安装运行时。

阶段 A/B 固定离线样本建议至少 100 张，要求原始 OCR 输出逐张一致；另外断言 full 引擎可用，避免把静默降级误当验收成功。

所有验证限于固定离线样本或本地模拟，不提交真实登录/注销，不创建自启项，不修改真实 config.json。若需采集门户验证码或真实认证，另行审批。

## 8. 风险与回滚

| 风险 | 应对 / 回滚 |
| --- | --- |
| 模型裁剪误删默认资源 | 强制清单断言，OCR 初始化失败即拒绝发布；恢复原打包规则 |
| FFmpeg 或 cv2 被上游导入依赖 | 阶段 A 保留 cv2，先验证单独去除 FFmpeg；不通过则恢复该 DLL |
| 薄封装预处理/解码有差异 | 固定样本逐张比较；不一致则回滚至 ddddocr 版本 |
| 量化算子不兼容或准确率下降 | 保留原模型，量化版不得替换正式资源 |
| 当前有未提交业务改动 | 备份当前工作区文件，不能只回滚到 Git HEAD；禁止 `git reset --hard` |
| CI 打包与本地不一致 | 记录锁定依赖和产物清单，验证后再同步发布；不在审批前推送触发 Release |

实施前备份位置：`<本机路径>

候选产物和动态验证工作副本放在 `<本机路径>

实施与检查的完整命令、体积、准确率和未验证事项记入 `docs/CHANGELOG.md`。本次未执行 lint、构建、OCR 推理或 GUI 测试。

## 9. 推荐执行范围

建议先批准阶段 A 的代码调整与静态检查，得到可审阅的构建规则后再批准隔离构建和离线验证。阶段 A 验收后用实际体积决定是否进入 B；C 最后单独评估。

用户目前仅要求规划，本文不构成实施、安装依赖、运行测试或发布授权。

## 10. 阶段 A 实施记录（2026-10-13 20:05，仅代码改造与静态验收）

授权范围：仅「阶段 A 改造 + 静态验收」。未构建、未运行 exe、未跑 OCR 推理、未联网、未安装依赖、
未修改 `src\` 下任何业务代码。完整命令与证据见 `docs\CHANGELOG.md` 同日 20:05 条目。

### 10.1 实际改动

| 文件 | 状态 | 内容 |
| --- | --- | --- |
| `scripts\build.ps1` | 修改 | full 目标：删除 `--collect-all ddddocr` 与 `--collect-binaries cv2`；新增 `--hidden-import ddddocr`、`--copy-metadata ddddocr`、`--add-data <venv>\...\ddddocr\common_old.onnx;ddddocr`、`--additional-hooks-dir scripts\hooks`；打包前断言默认模型与 hook 文件存在；构建后调用清单检查，不通过即构建失败 |
| `scripts\hooks\hook-cv2.py` | 新增 | 覆盖 `_pyinstaller_hooks_contrib` 的官方 `hook-cv2.py`，只做一处改动：过滤 `opencv_videoio_ffmpeg*.dll` |
| `scripts\check-bundle.ps1` | 新增 | 只读解析 `PKG-00.toc`，断言必需/禁止项与三组资源原始体积，退出码 0/1/2 |

对应方案步骤：A1 备份与基线 ✅、A2 精确数据收集 ✅（未新增 ddddocr 专用 hook，改用 CLI 参数即可）、
A3 FFmpeg 精确过滤 ✅、A4 断言与清单检查脚本 ✅、A5 构建与离线验证 ❌（未批准，未执行）。

### 10.2 与方案不同的三点（实施中核对源码后修正）

1. **A3 必须两处同时改**：仅删 `--collect-binaries cv2` 无效（官方 hook 仍会收集），仅覆盖 hook 也无效
   （该参数在 spec 中展开为 `collect_dynamic_libs('cv2')`，会把 DLL 加回来）。两处都已改。
2. **不存在独立的字符集数据文件**：第 5 节步骤 4 要求「不能只复制模型而遗漏匹配字符集」，实测字符集
   **内联**在 `ddddocr\models\charset_manager.py::_get_old_charset`，`charsets.py` 无任何模块引用。阶段 B
   若自写推理封装，字符集需从该函数提取或在代码中复刻，没有 JSON 可复制。
3. **`--collect-all` 的收集范围比方案描述更大**：它默认 `include_py_files=True`，旧 full 清单里除三个模型外
   还含 `api\*.py`（7 个文件）、`logo.png`、`README.md`、`charsets.py` 与 `ddddocr-1.6.1.dist-info\*`。精确收集后
   这些一并去掉，并由 `--copy-metadata` 单独保住 MIT 许可与版本元数据。

### 10.3 静态验收结论（已执行）

| 检查项（对应第 7 节） | 结果 |
| --- | --- |
| `git diff --check` | 通过，无空白错误 |
| 改动范围核对 | 仅 `scripts\build.ps1` 修改 + 两个新文件；`src\`、`requirements.txt`、`.github\` 未动 |
| Python AST（`hook-cv2.py`） | 通过，且 hook 所需变量齐全 |
| 宿主脚本语法（7.6.6 与 5.1） | 两个 `.ps1` 均通过 |
| TOC 断言方向一：旧 full 清单 | 4 类违规（两个闲置模型、ffmpeg、`ddddocr/api/*`）全部命中 → 退出码 1 |
| TOC 断言方向二：现有 lite 清单 | OCR 三类资源均为 0 项 → 退出码 0 |
| 解析覆盖率 | 1442/1442 条目配对，0 条孤儿类型标记 |
| 编码与行尾 | `.ps1` UTF-8 with BOM + CRLF；`.py` UTF-8 无 BOM + CRLF |
| SHA-256 / 体积基线 | 见 `temp\output\backup-20261013\GUIT-net-login-size-reduction\BASELINE-MANIFEST.md` |

发现并修复的两个阻断级问题（首版正则漏 `PYSOURCE` 类型标记与单行式条目导致静默跳过；首版脚本
`-f` 缺右操作数导致语法错误）见 CHANGELOG。

### 10.4 仍未验证（需另行批准）

- 未构建，因此新规则产出的 TOC **尚未被检查过**；`check-bundle.ps1` 目前只证明了「能拦住违规」，
  还没证明「新产物能通过」。
- 未做离线 OCR 对比、GUI 冒烟、无 Python 环境实测。TOC 校验只能证明收集内容，不能证明运行成功。
- 体积收益仍为估算：三项闲置资源原始体积合计 100.22 MiB。exe 缩减量必须构建后实测，不得用原始体积相加推算。
- `README.md`（第 11 行）与 `.github\workflows\release.yml`（第 108 行）的「约 160 MB」需在构建实测后同步。
- CI 触发路径含 `scripts/**`，**提交并推送即会自动发版**；本次改动保持未提交状态。

