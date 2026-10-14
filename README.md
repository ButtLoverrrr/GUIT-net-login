# GUIT-net-login

校园网网页认证（Portal）快捷登录小工具。

双击打开一个「联网设置」窗口，填好账号后点一下「连接」即可上网，不用再开浏览器、输账号密码、抄验证码。

## 三个版本，按需选一个

| 版本 | 体积 | 验证码 | 说明 |
| --- | --- | --- | --- |
| **`GUIT-net-login-full.exe`** | 约 82 MB | **自动识别**，基本不用管 | 最省事，推荐 |
| **`GUIT-net-login-lite.exe`** | 约 19 MB | 手动输入 4 位 | 体积小，便于传发 |
| **`GUIT-net-login-slim.exe`** | 约 45 MB | **自动识别**，基本不用管 | 精简版：功能与 full 完全一致，去掉未用载荷，体积最小 |

三个都是**单文件 exe，双击即用**，对方电脑不需要安装 Python。

> slim 与 full 的区别只在打包内容：slim 去掉了程序用不到的载荷（OpenCV、未用的 PIL 图像扩展、
> 死标准库模块），识别模型与识别行为完全相同——120 张固定样本上两者输出逐张一致。

## 使用

1. 双击 exe，打开「联网设置」窗口（验证码会自动显示在窗口里）
2. 填入学号、上网账号（手机号）、上网密码
3. 点「连接」完成登录
4. 可选：勾选「记住密码」下次免输；勾选「开机自动登录」开机自动连
5. 需要断网时，点「断开网络」

窗口右下角还有「官方平台」按钮，可直接打开校园网官方主页；状态栏会显示当前 IP 与在线状态；底部显示项目地址。

> **不留垃圾**：程序不写日志；只有在勾选「记住密码」或「开机自动登录」时，才会在 exe 同目录生成一个 `config.json`。取消勾选会自动删除该文件，因此不记忆任何信息时程序不会遗留任何文件。

## 从源码构建

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1 -Target all
```

`build.ps1` 产出 lite 与 full，构建后自动校验打包清单（`scripts\check_bundle.py`：
必需项必须存在、闲置模型/FFmpeg/未用 API 必须不存在，不通过即构建失败）。

精简版在 full 基础上重打包（保留引导器、替换第一方模块、剔除未用载荷、zlib-9 重压缩）：

```powershell
.venv\Scripts\python.exe tools\build_slim_exe.py `
  --exe build\GUIT-net-login-full.exe --proj . --src src `
  --out build\GUIT-net-login-slim.exe
```

## 工程质量记录

本仓库另含一轮「反编译 → 修复 → 优化」的完整工程：`tests\`（62 条沙箱用例 + 自建模拟门户）、
`tools\`（保真度门禁、性能 A/B、精简打包脚本）、`docs\REBUILD_NOTES.md`、`docs\PACKAGING.md`、
`reports\完工报告.md`。

## 自动发布

推送代码到 `main`（`src/`、`scripts/`、`requirements.txt` 有变动时）会自动触发 [发布工作流](.github/workflows/release.yml)：

1. 读取仓库现有 `v*` 标签，**补丁版本号自动 +1**（也可在 Actions 页面手动触发，选择 patch / minor / major）
2. 把新版本号写入 `src/app.py` 的 `APP_VERSION` 常量，界面标题与底部会显示当次版本
3. 在云端构建 `lite` 与 `full`，并在 full 基础上重打包出 `slim`
4. 打标签并创建 Release，附带三个 exe 与自动生成的发布说明（无需本地手工打包上传）

## 开源协议

本项目采用 [MIT 协议](LICENSE)，可自由使用、修改与分发。

第三方依赖：`ddddocr`（MIT）、PyInstaller（GPL-2.0 + 例外，打包产物不受其约束）、tkinter（PSF）。
`scripts\hooks\hook-cv2.py` 是 PyInstaller Community Hooks 的修改版本，依上游为 GPL-2.0-or-later，
许可全文随该目录分发（`scripts\hooks\LICENSE`）。

## 免责声明

本工具仅为便利性网络连接工具：不修改、不破解、不绕过任何校园网认证、计费与限速机制；账号密码只保存在本机（可随时删除），不上传任何数据。请仅用于个人账号，并遵守所在学校的网络使用规定。
