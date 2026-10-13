# GUIT-net-login

校园网网页认证（Portal）快捷登录小工具。

双击打开一个「联网设置」窗口，填好账号后点一下「连接」即可上网，不用再开浏览器、输账号密码、抄验证码。

## 两个版本，按需选一个

| 版本 | 体积 | 验证码 | 说明 |
| --- | --- | --- | --- |
| **`GUIT-net-login-full.exe`** | 约 160 MB | **自动识别**，基本不用管 | 最省事，推荐 |
| **`GUIT-net-login-lite.exe`** | 约 19 MB | 手动输入 4 位 | 体积小，便于传发 |

两个都是**单文件 exe，双击即用**，对方电脑不需要安装 Python。

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

## 自动发布

推送代码到 `main`（`src/`、`scripts/`、`requirements.txt` 有变动时）会自动触发 [发布工作流](.github/workflows/release.yml)：

1. 读取仓库现有 `v*` 标签，**补丁版本号自动 +1**（也可在 Actions 页面手动触发，选择 patch / minor / major）
2. 把新版本号写入 `src/version.py`，界面标题与底部会显示当次版本
3. 在云端构建 `lite` 与 `full` 两个 exe
4. 打标签并创建 Release，附带两个 exe 与自动生成的发布说明（无需本地手工打包上传）

## 开源协议

本项目采用 [MIT 协议](LICENSE)，可自由使用、修改与分发。

第三方依赖：`ddddocr`（MIT）、PyInstaller（GPL-2.0 + 例外，打包产物不受其约束）、tkinter（PSF）。

## 免责声明

本工具仅为便利性网络连接工具：不修改、不破解、不绕过任何校园网认证、计费与限速机制；账号密码只保存在本机（可随时删除），不上传任何数据。请仅用于个人账号，并遵守所在学校的网络使用规定。
