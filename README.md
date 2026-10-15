# GUIT-net-login

校园网网页认证（Portal）快捷登录小工具。

双击打开一个「联网设置」窗口，填好账号后点一下「连接」即可上网，不用再开浏览器、输账号密码、抄验证码。

## 下载

| 文件 | 体积 | 说明 |
| --- | --- | --- |
| **`GUIT-net-login.exe`** | 约 45 MB | **单文件，双击即用**，验证码自动识别，基本零输入 |

单个**单文件 exe**，对方电脑不需要安装 Python。

> 打包只做了「去掉程序用不到的东西」：不含 OpenCV、未用的 PIL 图像扩展与死标准库模块；
> 识别模型与识别行为没有任何改动——120 张固定样本上与未精简构建的输出逐张一致。

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
pwsh -NoProfile -File scripts\build.ps1
```

`build.ps1` 是两段式，最终**只产出一个产物** `build\GUIT-net-login.exe`：

1. PyInstaller 基础构建（精确收集：只收 ddddocr 默认模型，不收闲置模型与 FFmpeg 组件），
   中间产物放在 `build\_work\` 下；
2. 自动调用 `scripts\check_bundle.py` 校验打包清单（必需项必须在、闲置项必须不在，
   不通过即构建失败）；
3. `tools\build_slim_exe.py` 在基础 exe 上剔除程序用不到的载荷（cv2、未用 PIL 扩展、
   死标准库模块）并换成当前源码，输出最终单文件 exe（工具自带写后自校验）。

## 工程质量记录

本仓库另含一轮「反编译 → 修复 → 优化」的完整工程：`tests\`（67 条沙箱用例 + 自建模拟门户）、
`tools\`（保真度门禁、性能 A/B、精简打包脚本）、`docs\REBUILD_NOTES.md`、`docs\PACKAGING.md`、
`docs\ocr-interface.md`（验证码识别接口：实现可插拔，默认 ddddocr，可配置更换）、
`reports\完工报告.md`。

## 自动发布

推送代码到 `main`（`src/`、`scripts/`、`tools/`、`requirements.txt` 有变动时）会自动触发 [发布工作流](.github/workflows/release.yml)：

1. 读取仓库现有 `v*` 标签，**补丁版本号自动 +1**（也可在 Actions 页面手动触发，选择 patch / minor / major）
2. 把新版本号写入 `src/app.py` 的 `APP_VERSION` 常量，界面标题与底部会显示当次版本
3. 在云端构建单个单文件 exe（构建脚本内部完成「基础构建 → 清单校验 → 精简重打包」）
4. 打标签并创建 Release，附带该 exe 与自动生成的发布说明（无需本地手工打包上传）

## 开源协议

本项目采用 [MIT 协议](LICENSE)，可自由使用、修改与分发。

第三方依赖：`ddddocr`（MIT）、PyInstaller（GPL-2.0 + 例外，打包产物不受其约束）、tkinter（PSF）。
`scripts\hooks\hook-cv2.py` 是 PyInstaller Community Hooks 的修改版本，依上游为 GPL-2.0-or-later，
许可全文随该目录分发（`scripts\hooks\LICENSE`）。

## 免责声明

本工具仅为便利性网络连接工具：不修改、不破解、不绕过任何校园网认证、计费与限速机制；账号密码只保存在本机（可随时删除），不上传任何数据。请仅用于个人账号，并遵守所在学校的网络使用规定。
