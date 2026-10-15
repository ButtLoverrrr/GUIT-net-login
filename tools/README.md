# tools\ 说明（反编译重建工作线的配套工具）

本目录工具来自 2026-10-13 的「full exe 反编译 → 重建 → 精简」工作线（见
`reports\完工报告.md` 与 `docs\REBUILD_NOTES.md`），用于研究、诊断与精简重打包。

## 使用前必读

1. **路径占位符**：清洗本机路径时，脚本内的绝对路径被替换为
   `<full 版 exe 路径>`、`<项目目录>`、`<反编译参考目录>` 等占位符；
   运行前请按本机布局替换，或使用脚本支持的参数 / 环境变量。
2. **build_slim_exe.py**（最终打包步骤，由 `scripts\build.ps1` 自动调用）已参数化，不依赖硬编码路径：

   ```powershell
   # 单独调用（正常构建不必手动跑，build.ps1 已经包含这一步）
   python tools\build_slim_exe.py `
     --exe <基础构建产物> `
     --proj <项目目录> `
     --src  <项目目录>\src `
     --out  build\GUIT-net-login.exe
   ```

   - `--dry` 只估算；`--keep-all/--no-pyz-trim/--no-replace/--control/--probe` 为二分与诊断开关。
   - 原理：保留原 exe 的 PyInstaller 引导器字节，重写 CArchive PKG——
     替换 PYZ 内第一方模块的字节码、剔除 `cv2\*` 与未用载荷、
     PYZ 剔除死模块、全量 zlib-9 重压缩；写完会回读产物自校验（条目数与引导器长度）。
   - **第一方模块清单**（`PYZ_MODULES`）：`portal_client, config_store, ocr, ocr_helper,
     app_logger, autostart`（入口脚本另计）。OCR 解耦后接口层 `src/ocr.py` 必须在内，
     否则精简产物会在 `import ocr` 时失败；改清单前先看 `tests/test_ocr_decoupling.py`
     的静态断言。
   - 精简版能跑 OCR 的原因见 `src\ocr_helper.py` 的 `_ensure_cv2_shim()`
     （按需报错的 cv2 兼容桩）。

   **实测（2026-10-14，基底 85,643,184 字节）**

   | 配方 | 结果 | 说明 |
   | --- | --- | --- |
   | 只去 cv2 + 2 个 PIL 扩展 | 47.71 MiB | 早期版本 |
   | 当前默认配方（最终产物用） | **44.9~45.3 MiB** | 再剔除 PKG/PYZ 死重量；OCR 行为不变 |

   验证方式：包内 OCR 引擎 `available()` 为 True（经 `app.build_ocr_engine(cfg)` 装配）；
   对 120 张固定样本的包装输出与 full 版逐张一致（差异 0）；GUI 冒烟通过
   （窗口、单实例端口、正常退出）。

   **排除表改动须知（实测教训）**：`numpy.libs\*`（openblas）是 `_multiarray_umath.pyd`
   的**加载期**依赖，删掉 numpy 直接导入失败；`numpy._core._add_newdocs` 与 `numpy.ma`
   也在 numpy 导入链上。**numpy 的任何子模块都不要加进 PYZ 排除表。**
   PIL 插件白名单同样要看依赖链：`IcoImagePlugin` 顶部 `from . import BmpImagePlugin`，
   只留 Ico 而删 Bmp 会让托盘图标创建失败（异常在 pystray 内部线程里被吞掉）。
   **改动排除表后，必须同时跑三项验证**：① 包内 OCR `available()` 与固定样本输出；
   ② 托盘图标可见（`Icon.visible`）；③ GUI 冒烟。

3. `verify_slim_exe.py` / `slim_probe*_entry.py` 为诊断入口；
   `fidelity.py` 依赖原工作线的 marshal 基线（未入库），仅供参考。

## 工具与 OCR 解耦的关系（2026-10-15）

OCR 已解耦为可插拔接口（`src/ocr.py` 定契约、`src/ocr_helper.py` 是默认实现、
`app.build_ocr_engine(cfg)` 是唯一装配点，见 `docs/ocr-interface.md`）。
各工具与接口的关系如下，**没有工具被删除**：

| 工具 | 现状 | 说明 |
| --- | --- | --- |
| `build_slim_exe.py` | 当前 | 重打包清单含 `ocr`（见上） |
| `analyze.py` | 当前 | `MODULES` 含 `ocr`，跨模块边含 `app → ocr` |
| `e2e_ocr.py` | 当前 | OCR 可用性改走 `app.build_ocr_engine(cfg)` |
| `slim_probe3_entry.py` | 当前 | 同上，并额外报告装配到的后端名与可用后端列表 |
| `slim_probe_entry.py` | 当前 | 探针导入清单补 `ocr` |
| `slim_probe4_entry.py` | 当前 | 诊断入口（`--probe` 用；app 的带 diag.log 变体），OCR 装配改走 `ocr.create_engine(cfg)` |
| `probe_bench.py` / `probe_fastfail.py` / `verify_backend_claims.py` | 当前 | `sys.modules` 清理清单补 `ocr` |
| `verify_slim_exe.py` / `final_check.py` / `slim_probe2_entry.py` / `try_exe.py` / `perf_ab.py` / `accept.ps1` / `shot.ps1` | 历史/诊断 | 不引用 OCR 接口，保持原样 |
| `fidelity.py` | 历史 | 对照反编译 marshal 基线（未入库）的逐指令校验；清单只含基线里存在的模块，故不含 `ocr`（原因见文件内注释） |
| `race_ocr.py` | 默认实现专项 | 只证明 `ocr_helper.OcrEngine.available()` 的并发竞态，仍直接引用默认实现 |
