# GUIT-net-login 重建源码包

本包是 `GUIT-net-login-full.exe`（PyInstaller onefile / Python 3.13 冻结）的**反编译 → 修复 → 优化**后的完整工程，
以及复现/验证/重新打包所需的一切。原始 exe 的 SHA256：
`E4366A5B643D5EBBA13754207A6B6FBFDFBD2EAA5A9AECE198F7FAABFC7BE711`

## 目录

| 路径 | 说明 |
|---|---|
| `*.py`（根目录 6 个模块） | 交付源码：`app.py`(入口+GUI) `portal_client.py`(门户会话) `config_store.py`(配置) `ocr_helper.py`(ddddocr 封装) `app_logger.py`(日志) `autostart.py`(开机自启) |
| `assets/` | 图标资源（`app.ico` / `app.png` / `github.png`，与原始 exe 内一致） |
| `tests/` | 62 条用例 + 自建模拟 ASP.NET 门户与全沙箱 harness（不碰真实校园网/用户系统） |
| `docs/` | `REBUILD_NOTES.md`(工程说明) `STRUCTURE.md`(逐函数结构与调用链) `PACKAGING.md`(精简打包依据) 反汇编取证 `*.dis.txt` 运行态截图 |
| `reports/` | `完工报告.md`(主线总报告) `frontend.md` `backend.md`(两个 subagent 详报) |
| `tools/` | 保真度门禁、启动性能 A/B、网络等待 A/B、精简打包、端到端与终验脚本 |
| `reference/` | **反编译原始产物**（`src/*.py`）与 **exe 内原始字节码**（`marshal/*.marshal`）——保真度比对的"唯一真相" |

## 运行

需要 **CPython 3.13**（本程序由 3.13 冻结）。第三方依赖：
- 必需：`tkinter`（标准库自带）、`Pillow`（验证码显示）、`pystray`（托盘）
- 验证码自动识别需要：`ddddocr`（+ 它的 `numpy` / `onnxruntime`；`opencv-python` 仅 ddddocr 的
  检测/滑块/颜色过滤子模块需要，本程序不用 —— 精简构建用 `ocr_helper._ensure_cv2_shim()` 的兼容桩替代）

```powershell
# 直接用某个 3.13 解释器跑源码（config.json 与日志会落在"源代码目录的上一级"——见 config_store.app_dir()）
& <python3.13> app.py                 # 打开界面
& <python3.13> app.py --silent         # 无窗口静默登录（结果用系统提示框反馈）
& <python3.13> app.py --autostart      # 开机自启模式：开界面并在网络就绪后自动连接
```

## 跑测试（62 条，全部本地沙箱）

```powershell
cd <本包根目录>
& <本机路径>
```

覆盖：配置读写/损坏/原子写、隐藏字段解析、验证码与会话绑定、登录成功/验证码错/账号错、
门户优先的在线判定、注销（快速路径/有界等待/探测兜底）、探测并发与早退、协议异常包装、
OCR 降级与初始化线程安全、自启 enable/ensure/disable、GUI（连接/断开/回车/Esc/淡入/日志有界/托盘/居中）、
静默模式返回码、单实例（含"第一实例卡住不许崩"）、启动性能门禁。

## 保真度门禁（反编译重建 vs exe 内原始字节码）

```powershell
& <本机路径>
```
`reference/marshal/*.marshal` 就是 exe 内的原始代码对象；`tools/fidelity.py` 会把本工程源码重新编译后与之逐指令比对。

## 重新打包成单文件 exe（体积 −41.9%）

```powershell
& <本机路径>
& <本机路径>
```
做法：**复用原 exe 的 PyInstaller 引导器**（逐字节保留），只重建尾部 PKG —— 换入本工程源码的 3.13 编译产物、
剔除实测未被引用的大件（OpenCV 29.3 MiB / PIL AVIF 4.1 MiB / PIL FreeType 1.0 MiB）、逐条目沿用原压缩标志。
详细依据与验证见 `docs/PACKAGING.md`。脚本里的 `EXE`/`PROJ` 是绝对路径，换机器请改这两处。

## 端到端验证（自建模拟门户，不碰真实校园网）

```powershell
& <py313> tools\e2e_probe.py exe lenient        # 用"真实 exe"打模拟门户
& <py313> tools\e2e_ocr.py <项目目录> --lenient   # 进程内：真实 HTTP + 真实 ddddocr
& <py313> tools\final_check.py <某个 exe>         # 交付前终验：rc=0 + 完整请求链 + 门户转在线
```

## 已知取舍

- 精简构建**不含 OpenCV**：本程序只调用 `DdddOcr(show_ad=False).classification()`，cv2 只被 ddddocr 的
  目标检测/滑块/颜色过滤子模块使用（已用"陷阱 cv2"实测该路径零属性访问）。若要 `det=True` 等能力，请用完整构建。
- 精简构建**不含 PIL 的 AVIF 插件与 FreeType 后端**：程序只解码 PNG 与绘制形状，不渲染文字。
- `docs/` 里的 `*.dis.txt` 是 PowerShell 重定向产物（UTF-16），多数编辑器能正常打开。
