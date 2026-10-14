# tools\ 说明（反编译重建工作线的配套工具）

本目录工具来自 2026-10-13 的「full exe 反编译 → 重建 → 精简」工作线（见
`reports\完工报告.md` 与 `docs\REBUILD_NOTES.md`），用于研究、诊断与精简重打包。

## 使用前必读

1. **路径占位符**：清洗本机路径时，脚本内的绝对路径被替换为
   `<full 版 exe 路径>`、`<项目目录>`、`<反编译参考目录>` 等占位符；
   运行前请按本机布局替换，或使用脚本支持的参数 / 环境变量。
2. **build_slim_exe.py**（精简重打包主力）已参数化，不依赖硬编码路径：

   ```powershell
   # 例：从 full 版 exe 重打包出精简版（去掉 cv2 载荷、替换 6 个第一方模块）
   python tools\build_slim_exe.py `
     --exe  <full 版 exe 路径> `
     --proj <项目目录> `
     --src  <项目目录>\src `
     --out  build\GUIT-net-login-精简版.exe
   ```

   - `--dry` 只估算；`--keep-all/--no-replace/--control/--probe` 为二分与诊断开关。
   - 原理：保留原 exe 的 PyInstaller 引导器字节，重写 CArchive PKG——
     替换 PYZ 内 6 个第一方模块的字节码、剔除 `cv2\*` 与 2 个未用 PIL 扩展、
     全量 zlib-9 重压缩。精简版能跑 OCR 的原因见 `src\ocr_helper.py`
     的 `_ensure_cv2_shim()`（按需报错的 cv2 兼容桩）。
3. `verify_slim_exe.py` / `slim_probe*_entry.py` 为诊断入口；
   `fidelity.py` 依赖原工作线的 marshal 基线（未入库），仅供参考。
