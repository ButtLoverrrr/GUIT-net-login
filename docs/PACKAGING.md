# 精简打包说明（体积 −41.9%，功能验证通过）

> **版本说明**：本文的模块清单与验证数据来自 2026-10-13/14 的重建工作线。
> OCR 解耦（2026-10-15）后第一方模块新增接口层 `src/ocr.py`，重打包脚本的
> `tools/build_slim_exe.py` 里 `PYZ_MODULES` 现为
> `portal_client, config_store, ocr, ocr_helper, app_logger, autostart`
> （**漏掉 `ocr` 会让精简产物在 `import ocr` 时直接失败**）；
> 新版 OCR 装配入口是 `app.build_ocr_engine(cfg)`（见 `docs/ocr-interface.md`）。
> 下列历史数字未重测，不作为当前产物的实测结论。

产物：`<本机路径>
- 大小 **50,030,419 字节（47.71 MiB）**；原版 **86,039,734 字节（82.05 MiB）** → **−41.9%**
- SHA256：`8CDA8EE77B2E444DEEA9DA258FA9E203CDF64145512D830E9D60A32BEFD93641`

## 做法：复用原引导器 + 重建归档（不重新打包、不引入外部依赖）

原 exe 是 `[PyInstaller 引导器 PE][CArchive(PKG) 归档]`。本方案**逐字节保留原引导器**，只重建 PKG：
1. 把 `app.py` 与 `portal_client/config_store/ocr/ocr_helper/app_logger/autostart` 用 CPython 3.13
   重新编译成 marshal，分别替换 PKG 里的入口脚本与 PYZ 里的 6 个模块（PYZ 按原格式重建，其余模块原样搬运）；
   （重建期为 5 个模块；OCR 解耦后加入 `ocr`，共 6 个。）
2. 剔除**经实测证明未被引用**的大块（见下）；
3. 每个条目沿用**原始的压缩标志**（PyInstaller 的引导器对 PYZ 等条目不 inflate，标志必须一致）。

构建脚本：`<本机路径>

## 剔除清单与依据

| 剔除项 | 原存储占用 | 依据 |
|---|---|---|
| `cv2\*`（OpenCV，共 12 条） | **29.27 MiB** | ddddocr 顶层 `import cv2`，但 cv2 只被它的**目标检测（DetectionEngine）/滑块匹配（SlideEngine）/颜色过滤（ColorFilter）/图像预处理**子模块使用；本程序唯一路径 `DdddOcr(show_ad=False).classification()` 用"陷阱 cv2"实测**零属性访问**。精简构建由 `ocr_helper._ensure_cv2_shim()` 装一个"按需报错"的兼容桩；若环境里有真 cv2 则照用真件 |
| `PIL\_avif.cp313-win_amd64.pyd` | 4.12 MiB | 程序只解码 PNG（验证码）与绘制形状；AVIF 插件永不触发（缺失时 PIL 会跳过该插件） |
| `PIL\_imagingft.cp313-win_amd64.pyd` | 0.96 MiB | 程序不渲染文字（PIL 文字渲染才需要 FreeType）；`ImageFont.load_default()` 仍可用 |

> 以上三项都在**精简环境**（把对应文件移开）里跑过全量测试：`tests\run_tests.py all` → **62/62 通过**。
> 代价：如果需要 ddddocr 的 `det=True`（目标检测）/滑块匹配/颜色过滤，或需要用 PIL 渲染 TrueType 文字，请用完整构建。

## 验证（都做过）

1. **结构自检**：新 exe 的 cookie/TOC 可解析，1395 条目（原 1409），`app` 可 unmarshal，PYZ 743 模块可加载，
   每条 TOC 记录 16 字节对齐且名字带 NUL 终止（这两点曾分别导致"引导器解析错位"和"文件名被追加多余字符"两类故障，已修）。
2. **冻结环境探针**：在 exe 内逐项验证 `ssl / hashlib / tkinter(8.6.15) / PIL / PIL.ImageTk / pystray / app_logger /
   config_store / ocr / ocr_helper / portal_client / autostart / numpy(2.5.4) / onnxruntime / ddddocr` 全部可导入；
   OCR 可用性经 `app.build_ocr_engine(cfg).available()`（解耦前为 `OcrEngine.available()`）确认为 True。
3. **协议闭环终验**（不弹窗）：把 exe 复制到临时目录，配一份指向本机模拟门户的 `config.json`，跑 `--silent`：
   `rc=0`（4.0s），门户依次收到 `GET /logoff → GET /login → GET /CheckCode → GET /logoff → POST /login`，
   门户状态转为在线 → 说明 **HTTP/会话/验证码/ddddocr 识别/配置读取**在冻结环境里全部工作。

命令：`& <本机路径>

## 未做（保持原样）

- 未对 ONNX 模型做 int8 量化（会改变 OCR 精度，无法在真实门户上验证）。
- 未剔除 stdlib/PYZ 里的冷门模块（`asyncio`/`pydoc_data` 等，合计约 1 MiB，但属"懒加载可能被用到"的高风险区，收益不成比例）。
- 未删除 UCRT/VC 运行时 DLL（约 1 MiB）：保留可移植性，删掉会在缺少运行库的系统上无法启动。
