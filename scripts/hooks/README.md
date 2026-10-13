# scripts\hooks\ 说明（cv2 打包 hook 的来源、许可与证据）

- 项目：`GUIT-net-login`，体积压缩阶段 A（方案见 `docs\20261013-size-reduction-plan.md`）。
- 本目录内的 `hook-cv2.py` 覆盖 `_pyinstaller_hooks_contrib` 自带的 `hook-cv2.py`，
  唯一目的是在 full 构建中**不收集** OpenCV 的 FFmpeg 视频组件。
- 生效范围：仅 `scripts\build.ps1` 的 full 目标通过 `--additional-hooks-dir scripts\hooks` 加载；
  lite 直接 `--exclude-module cv2`，不经过本 hook。

## 1. 来源与许可

| 项 | 内容 |
| --- | --- |
| 上游文件 | `_pyinstaller_hooks_contrib/stdhooks/hook-cv2.py` |
| 上游版本 | pyinstaller-hooks-contrib **2026.8**（本环境 `.venv` 安装版，PyInstaller 6.22.3 配套） |
| 上游版权 | Copyright (c) 2020 PyInstaller Development Team |
| 上游许可 | **GPL-2.0-or-later**（contrib 的 METADATA 同样声明 GPLv2 分类器） |
| 本文件 | 上游文件的**修改版本**：文件头注明来源与修改点；其余逻辑逐行保持一致 |
| 许可全文 | 随本目录分发：`LICENSE`（取自 `pyinstaller_hooks_contrib-2026.8.dist-info/licenses/LICENSE`，含 GPL-2.0 全文） |

许可边界与义务：

1. 本仓库其余源码为 MIT（仓库根目录 `LICENSE`），但 `hook-cv2.py` 依上游为
   **GPL-2.0-or-later**，两者是同仓库内并存的独立许可（聚合），互不改变。
2. 分发 `hook-cv2.py` 源码时，必须一并分发：上游版权声明、`SPDX-License-Identifier:
   GPL-2.0-or-later` 标识、文件头内的修改说明，以及 `LICENSE` 全文（GPLv2 第 4/5 条）。
3. **不得**把 `hook-cv2.py` 标为 MIT；PyInstaller 的 bootloader 许可例外只适用于
   bootloader，不覆盖 hook 源码。

## 2. 为什么可以不收集 FFmpeg 组件（静态证据）

结论先行：`opencv_videoio_ffmpeg500_64.dll`（29, 45 MiB）不是 `cv2.pyd` 的导入期依赖，
只在运行时由 videoio 模块动态加载；本项目不使用 `VideoCapture` / `VideoWriter`。

复核命令（读取 PE 导入表，只读分析，不执行 cv2.pyd）：

```powershell
& D:\Dev\Projects\GUIT-net-login\.venv\Scripts\python.exe -c "import pefile; pe = pefile.PE(r'.venv\Lib\site-packages\cv2\cv2.pyd', fast_load=True); pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'], pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']]); names = [e.dll.decode() for a in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT') for e in getattr(pe, a, []) or []]; print(sorted(set(names))); print('ffmpeg 引用:', any('ffmpeg' in n.lower() for n in names))"
```

2026-10-13 实测结果：导入表为 `ADVAPI32.dll, COMDLG32.dll, GDI32.dll, KERNEL32.dll,
MF.dll, MFPlat.DLL, MFReadWrite.dll, OLEAUT32.dll, SHLWAPI.dll, USER32.dll, d3d11.dll,
dxgi.dll, ole32.dll, python3.dll`，**不含任何 ffmpeg DLL**（`ffmpeg 引用: False`）。

边界与后续动作：

- 该证据只覆盖「导入期」；**动态加载路径（videoio）并未被证明无害**，必须由一次
  无 Python 环境的 exe 实测（OCR 可用 + 界面正常）收尾。实测通过前，不得据此再删除
  cv2 的其他 DLL 或 `cv2.pyd` 本体。
- ddddocr 的 OCR 路径（`core\ocr_engine.py`、`preprocessing\image_processor.py`）只用
  `cv2.imdecode / resize / cvtColor / threshold / findContours / matchTemplate` 等图像处理
  函数，均不进入 videoio 代码路径；此结论基于对本环境 ddddocr 1.6.1 源码的静态阅读。

## 3. 为什么必须同时删掉 `--collect-binaries cv2`

`--collect-binaries cv2` 会在生成的 spec 中展开为 `binaries += collect_dynamic_libs('cv2')`，
它发生在 hook 之后，会把本 hook 过滤掉的 FFmpeg DLL 重新加回包里。因此
`scripts\build.ps1` 的 full 目标同时：

1. 删除 `--collect-binaries cv2`；
2. 通过 `--additional-hooks-dir scripts\hooks` 让本文件以更高优先级
   （`HOOK_PRIORITY_USER_HOOKS = 1000`，contrib 为 `-1000`）覆盖官方 hook。

## 4. 防回潮

构建完成后 `scripts\check_bundle.py` 会校验清单：任何目录下出现
`opencv_videoio_ffmpeg*.dll`、`ddddocr/common.onnx`、`ddddocr/common_det.onnx`
或 `ddddocr.api*` 模块，都会判为失败（退出码 1），构建脚本随即 `throw`。
