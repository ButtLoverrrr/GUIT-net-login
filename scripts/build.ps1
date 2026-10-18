<#
.SYNOPSIS
    构建 GUIT-net-login 的单文件 exe（只产出 `build\GUIT-net-login.exe` 一个产物）。

.DESCRIPTION
    两段式构建，最终只有一个产物：

    1) 基础构建（PyInstaller onefile，采用「精确收集」策略，见体积压缩阶段 A）：
       - 只收 ddddocr 的默认模型 common_old.onnx（闲置的 common.onnx / common_det.onnx 不收）；
       - 不再收集 OpenCV 的 FFmpeg 视频组件 opencv_videoio_ffmpeg*.dll，
         由 scripts\hooks\hook-cv2.py 覆盖官方 hook 实现；
       - 产物落在 build\_work\dist\GUIT-net-login-base.exe，**不放 build\ 根**，
         保证 build\ 里只有给用户的最终 exe。
    2) 清单校验（scripts\check_bundle.py）：默认模型与必需模块必须在，闲置模型、FFmpeg
       组件与未使用的 ddddocr.api 必须不在；不通过即构建失败。
    3) 精简重打包（tools\build_slim_exe.py）：以基础 exe 为基底，剔除程序用不到的载荷
       （cv2 / 未用 PIL 扩展 / 死标准库模块）并把第一方模块换成当前源码，输出
       `build\GUIT-net-login.exe`；工具自带写后自校验（回读条目数与引导器长度）。

    校验只证明收集内容，不能证明运行成功；OCR 与界面仍需动态验证。

.PARAMETER PythonPath
    可选：构建用解释器的绝对路径。默认使用本项目 `.venv\Scripts\python.exe`。
    在隔离工作副本中构建（副本没有自己的 .venv）时，必须显式传入原项目解释器；
    ddddocr 模型路径会依据该解释器所在环境定位，而不是副本目录。

.EXAMPLE
    pwsh -NoProfile -File scripts\build.ps1

.EXAMPLE
    # 在隔离副本中构建（副本不含 .venv）
    pwsh -NoProfile -File <副本>\scripts\build.ps1 `
        -PythonPath D:\Dev\Projects\GUIT-net-login\.venv\Scripts\python.exe
#>
[CmdletBinding()]
param(
    [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# CI 诊断：任何终止性错误都转成 GitHub 注解（::error:: 仅在 CI 环境生效，本地正常打印）。
# 这样即使 CI 日志被管道缓冲/截断，真实错误也能出现在 check-run 注解里。
trap {
    $errLines = ($_ | Out-String) -split "`r?`n" | Where-Object { $_.Trim() }
    if ($env:GITHUB_ACTIONS -eq 'true') {
        foreach ($line in $errLines) { Write-Host "::error::$line" }
    }
    else {
        foreach ($line in $errLines) { Write-Host $line -ForegroundColor Red }
    }
    break
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SourceDir   = Join-Path $ProjectRoot 'src'
$EntryPoint  = Join-Path $SourceDir 'app.py'
$DistDir     = Join-Path $ProjectRoot 'build'
$BaseName    = 'GUIT-net-login-base'
$BaseWorkDir = Join-Path $DistDir "_work\$BaseName"
$BaseDistDir = Join-Path $DistDir '_work\dist'
$BaseExe     = Join-Path $BaseDistDir "$BaseName.exe"
$FinalExe    = Join-Path $DistDir 'GUIT-net-login.exe'
$SampleCfg   = Join-Path $ProjectRoot 'config.sample.json'
$HooksDir    = Join-Path $ProjectRoot 'scripts\hooks'
$CheckScript = Join-Path $PSScriptRoot 'check_bundle.py'
$SlimScript  = Join-Path $ProjectRoot 'tools\build_slim_exe.py'

# 用 python -m PyInstaller 而非 pyinstaller.exe：venv 的 .exe 启动器内含绝对路径，
# 项目目录改名或移动后会失效，模块方式不受影响。
# -PythonPath：隔离构建副本没有自己的 .venv，必须显式指向真实环境。
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
}
else {
    $Python = $PythonPath
}
if (-not (Test-Path $Python)) {
    throw "未找到构建用解释器：$Python；可创建 .venv 并安装 requirements.txt，或用 -PythonPath 指定"
}

# 依赖资源的 site-packages 必须取自所选解释器，而不是本项目 .venv 的固定路径，
# 否则在隔离副本中会指向不存在的目录。
# 注意两处宿主差异：
#   1. 探测命令里只用 Python 单引号字符串——Windows 宿主 5.1 向原生命令传参会剥掉
#      内嵌的双引号（经典引号问题），写成 get_paths()["purelib"] 会收到 NameError。
#   2. 必须先把输出收集成数组、再读 $LASTEXITCODE——pwsh 7 里「原生命令 | Select-Object
#      -First 1」会提前终止管道，$LASTEXITCODE 变成空，导致误判失败（CI 首跑即栽在这）。
$pyProbe = @('-c', "import sysconfig; print(sysconfig.get_paths()['purelib'])")
$probeOutput = @(& $Python @pyProbe)
$probeExit = $LASTEXITCODE
if ($probeExit -ne 0 -or $probeOutput.Count -eq 0 -or [string]::IsNullOrWhiteSpace([string]$probeOutput[0])) {
    throw "无法用 $Python 定位 site-packages（退出码 $probeExit）"
}
$SitePackages = ([string]$probeOutput[0]).Trim()
if (-not (Test-Path $SitePackages)) {
    throw "解释器报告的 site-packages 不存在：$SitePackages"
}
$DdddOcrModel = Join-Path $SitePackages 'ddddocr\common_old.onnx'

# ---------------------------------------------------------------- 1) 基础构建
Write-Host '==== 基础构建（PyInstaller，精确收集） ====' -ForegroundColor Cyan

# 阶段 A：ddddocr 改为精确收集，不再用 `--collect-all ddddocr`。
# 原写法会把三个 ONNX 模型（common 51.58 MiB、common_det 19.19 MiB、common_old 12.98 MiB）
# 连同 api/ 子包源码、logo.png、README.md 全部当 DATA 收进包，而本项目只用到默认模型
# common_old.onnx。代码侧全部为静态 import，字节码分析会随 `import ddddocr` 自动收集
# core / models / preprocessing / utils；仍显式声明 --hidden-import，避免将来改成字符串
# 形式导入后静默漏收（漏收会静默降级成手输，不易察觉）。
# FFmpeg 过滤不靠删参数：--additional-hooks-dir 让 scripts\hooks\hook-cv2.py 覆盖官方
# hook；同时必须移除 `--collect-binaries cv2`——它在 spec 中展开为
# collect_dynamic_libs('cv2')，会把已被 hook 过滤掉的 ffmpeg DLL 再加回来。
if (-not (Test-Path $DdddOcrModel)) {
    throw "缺少默认 OCR 模型：$DdddOcrModel；请先按 requirements.txt 安装 ddddocr"
}
$Cv2Hook = Join-Path $HooksDir 'hook-cv2.py'
if (-not (Test-Path $Cv2Hook)) {
    throw "缺少 cv2 打包 hook：$Cv2Hook"
}

# 自研 CRNN 模型（登录页算术验证码）是作者私有资产，**不入开源仓库**（见 models\README.md）。
# 因此这里按存在与否决定是否收集，缺模型不能让构建失败：
#   - 本地有 models\crnn.onnx -> 收进包，check_bundle.py 对它的断言是 required；
#   - CI / 克隆环境没有        -> 跳过 --add-data，check_bundle.py 把断言降为 notice。
# PyInstaller 对不存在的 --add-data 源目录会直接报错退出，所以必须先判存在再拼参数。
$CrnnModel = Join-Path $ProjectRoot 'models\crnn.onnx'
$ModelArgs = @()
if (Test-Path $CrnnModel) {
    Write-Host ("  收集自研 CRNN 模型：{0}（{1:N2} MiB）" -f $CrnnModel, ((Get-Item $CrnnModel).Length / 1MB))
    $ModelArgs = @('--add-data', ((Join-Path $ProjectRoot 'models') + ';models'))
}
else {
    Write-Host '  未发现 models\crnn.onnx：本次构建不含自研 CRNN 模型，登录验证码将退回手动输入' -ForegroundColor Yellow
}

# 注意：不要用 $args（PowerShell 自动变量），故命名为 $pyiArgs
$pyiArgs = @(
    '--noconfirm', '--clean',
    '--onefile', '--noconsole',
    '--name', $BaseName,
    # 显式排除训练期残留的深度学习框架。本项目只用 onnxruntime 做推理，
    # 不依赖 torch；但构建用的 venv 里装过 torch（曾用于训练验证码模型），
    # PyInstaller 的 torch hook 会把它整套打包进来 —— 实测占解压后 365 MiB
    # （68%），压缩后约 110 MiB，是 exe 体积的绝对大头。
    # torch 的依赖链（filelock/fsspec/jinja2/markupsafe/networkx/sympy/mpmath）
    # 随之不被引用，一并排除。
    '--exclude-module', 'torch',
    '--exclude-module', 'torchvision',
    '--exclude-module', 'torchaudio',
    '--exclude-module', 'onnxscript',
    '--exclude-module', 'onnxruntime.tools',
    # 应用图标：--icon 用于 exe 文件图标；--add-data 让程序运行时能读到图标
    '--icon', (Join-Path $ProjectRoot 'assets\app.ico'),
    '--add-data', ((Join-Path $ProjectRoot 'assets') + ';assets'),
    # 显式把 src 加入模块搜索路径，确保第一方模块都被收进包
    '--paths', $SourceDir,
    # pystray 的平台后端与 Pillow 的 tkinter 桥接是动态/隐式导入，显式声明避免漏收
    '--hidden-import', 'pystray._win32',
    '--hidden-import', 'PIL.ImageTk',
    # OCR 接口层：app 只依赖 src\ocr.py 的契约，具体实现由注册表惰性导入，
    # 静态分析看不到 → 必须显式声明，否则打包后 OCR 静默消失（只剩手输）。
    # 两套后端都要收：登录页是算术题（ocr_crnn），注销页是四位字母（ocr_helper）。
    # check_bundle.py 有对应断言，漏收会在构建阶段直接失败。
    '--hidden-import', 'ocr',
    '--hidden-import', 'ocr_crnn',
    '--hidden-import', 'ocr_helper',
    '--hidden-import', 'ddddocr',
    '--copy-metadata', 'ddddocr',
    '--add-data', ($DdddOcrModel + ';ddddocr'),
    # 自研 CRNN 模型：登录页算术验证码用，运行时按 models/crnn.onnx 查找。
    # $ModelArgs 在模型不存在时是空数组（PowerShell 会自动摊平，不会留下悬空参数）。
    $ModelArgs
    '--collect-all', 'onnxruntime',
    '--additional-hooks-dir', $HooksDir,
    # 产物与中间件都放 _work：build\ 根目录只留最终 exe 与配置样例
    '--distpath', $BaseDistDir,
    '--workpath', $BaseWorkDir,
    '--specpath', $BaseWorkDir,
    $EntryPoint
)

# 注意：pyinstaller.exe 会把 INFO 日志写到 stderr，在 $ErrorActionPreference='Stop'
# 下会被 PowerShell 误判为终止性错误（NativeCommandError）而中断构建，
# 因此调用原生命令期间临时放宽该设置，改以退出码判定成败。
$previousEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $Python -m PyInstaller @pyiArgs
$exitCode = $LASTEXITCODE
$ErrorActionPreference = $previousEap
if ($exitCode -ne 0) {
    throw "PyInstaller 基础构建失败（退出码 $exitCode）"
}
if (-not (Test-Path $BaseExe)) {
    throw "基础构建结束但未找到产物：$BaseExe"
}
Write-Host ("基础 exe {0}  {1} MB" -f (Split-Path -Leaf $BaseExe), [math]::Round((Get-Item $BaseExe).Length / 1MB, 1)) -ForegroundColor DarkGray

# ---------------------------------------------------------------- 2) 清单校验
Write-Host '==== 校验打包清单 ====' -ForegroundColor Cyan
if (-not (Test-Path $CheckScript)) {
    throw "缺少打包清单检查脚本：$CheckScript"
}
$tocDir = Join-Path $BaseWorkDir $BaseName
if (-not (Test-Path $tocDir)) {
    throw "未找到构建中间目录：$tocDir"
}
$previousEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $Python $CheckScript --target full --toc-dir $tocDir --json (Join-Path $tocDir 'check-bundle.json')
$checkExit = $LASTEXITCODE
$ErrorActionPreference = $previousEap
if ($checkExit -ne 0) {
    throw "打包清单检查未通过（退出码 $checkExit）；产物不可发布"
}

# ---------------------------------------------------------------- 3) 精简重打包
Write-Host '==== 精简重打包（输出最终单文件 exe） ====' -ForegroundColor Cyan
if (-not (Test-Path $SlimScript)) {
    throw "缺少重打包脚本：$SlimScript"
}
$previousEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $Python $SlimScript --exe $BaseExe --proj $ProjectRoot --src $SourceDir --out $FinalExe
$slimExit = $LASTEXITCODE
$ErrorActionPreference = $previousEap
if ($slimExit -ne 0) {
    throw "精简重打包失败（退出码 $slimExit）"
}
if (-not (Test-Path $FinalExe)) {
    throw "重打包结束但未找到最终产物：$FinalExe"
}

# 附一份配置样例到产物目录，便于分发时对照
if (Test-Path $SampleCfg) {
    Copy-Item -Path $SampleCfg -Destination $DistDir -Force
    Write-Host "已复制 config.sample.json 到 build\" -ForegroundColor DarkGray
}

$finalSize = [math]::Round((Get-Item $FinalExe).Length / 1MB, 1)
Write-Host ("产物 {0}  {1} MB" -f (Split-Path -Leaf $FinalExe), $finalSize) -ForegroundColor Green
Write-Host '构建完成。' -ForegroundColor Cyan
