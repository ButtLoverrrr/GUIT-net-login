<#
.SYNOPSIS
    构建 GUIT-net-login 的单文件 exe。

.DESCRIPTION
    lite：不含 OCR（ddddocr / onnxruntime / cv2 / numpy / sympy / matplotlib 全部排除），
          体积约 19 MB，分发时对方只需手输 4 位验证码。
          注意：**PIL 与 pystray 必须保留**——验证码图片解码、托盘都依赖它们，不属于 OCR。
    full：含 OCR，双击后自动识别验证码。采用「精确收集」策略（体积压缩阶段 A）：
          - 只收 ddddocr 的默认模型 common_old.onnx；
            闲置的 common.onnx / common_det.onnx 不再收集（原 `--collect-all ddddocr` 会全收）；
          - 不再收集 OpenCV 的 FFmpeg 视频组件 opencv_videoio_ffmpeg*.dll，
            由 scripts\hooks\hook-cv2.py 覆盖官方 hook 实现；
          - 详见 docs\20261013-size-reduction-plan.md 阶段 A。

    构建完成后自动调用 scripts\check_bundle.py 校验打包清单（PKG/PYZ/Analysis 三层）：
    默认模型与必需模块必须在，闲置模型、FFmpeg 组件与未使用的 ddddocr.api 必须不在；
    校验失败即构建失败，避免违规产物被误发出去。

    校验只证明收集内容，不能证明运行成功；OCR 与界面仍需动态验证。

.PARAMETER Target
    lite / full / all（默认 all）。

.PARAMETER PythonPath
    可选：构建用解释器的绝对路径。默认使用本项目 `.venv\Scripts\python.exe`。
    在隔离工作副本中构建（副本没有自己的 .venv）时，必须显式传入原项目解释器；
    ddddocr 模型路径会依据该解释器所在环境定位，而不是副本目录。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1 -Target all

.EXAMPLE
    # 在隔离副本中构建（副本不含 .venv）
    powershell -NoProfile -ExecutionPolicy Bypass -File <副本>\scripts\build.ps1 `
        -Target all -PythonPath D:\Dev\Projects\GUIT-net-login\.venv\Scripts\python.exe
#>
[CmdletBinding()]
param(
    [ValidateSet('lite', 'full', 'all')]
    [string]$Target = 'all',

    [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SourceDir   = Join-Path $ProjectRoot 'src'
$EntryPoint  = Join-Path $SourceDir 'app.py'
$DistDir     = Join-Path $ProjectRoot 'build'
$SampleCfg   = Join-Path $ProjectRoot 'config.sample.json'
# 阶段 A：精确收集需要直接引用解释器环境内的资源文件、自定义 hook 目录与清单检查器
$HooksDir     = Join-Path $ProjectRoot 'scripts\hooks'
$CheckScript  = Join-Path $PSScriptRoot 'check_bundle.py'

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
# 注意：探测命令里只用 Python 单引号字符串。
# Windows 宿主 5.1 向原生命令传参会剥掉内嵌的双引号（经典引号问题），
# 若这里写成 get_paths()["purelib"]，实际到达 Python 的是 get_paths()[purelib] → NameError。
$pyProbe = @('-c', "import sysconfig; print(sysconfig.get_paths()['purelib'])")
$SitePackages = (& $Python @pyProbe | Select-Object -First 1)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($SitePackages)) {
    throw "无法用 $Python 定位 site-packages（退出码 $LASTEXITCODE）"
}
$SitePackages = $SitePackages.Trim()
if (-not (Test-Path $SitePackages)) {
    throw "解释器报告的 site-packages 不存在：$SitePackages"
}
$DdddOcrModel = Join-Path $SitePackages 'ddddocr\common_old.onnx'

function Build-One {
    param([Parameter(Mandatory = $true)][string]$Name)

    Write-Host "==== 构建 $Name ====" -ForegroundColor Cyan
    # 注意：不要用 $args（PowerShell 自动变量），故命名为 $pyiArgs
    $pyiArgs = @(
        '--noconfirm', '--clean',
        '--onefile', '--noconsole',
        '--name', "GUIT-net-login-$Name",
        # 应用图标：--icon 用于 exe 文件图标；--add-data 让程序运行时能读到图标
        '--icon', (Join-Path $ProjectRoot 'assets\app.ico'),
        '--add-data', ((Join-Path $ProjectRoot 'assets') + ';assets'),
        # 显式把 src 加入模块搜索路径：app.py 里的 `from version import __version__`
        # 依赖它才能被打进单文件包（否则运行时报 No module named 'version'）
        '--paths', $SourceDir,
        # pystray 的平台后端与 Pillow 的 tkinter 桥接是动态/隐式导入，显式声明避免漏收
        '--hidden-import', 'pystray._win32',
        '--hidden-import', 'PIL.ImageTk',
        '--distpath', $DistDir,
        '--workpath', (Join-Path $DistDir "_work\$Name"),
        '--specpath', $DistDir,
        $EntryPoint
    )

    if ($Name -eq 'full') {
        # 阶段 A：ddddocr 改为精确收集，不再用 `--collect-all ddddocr`。
        # 原写法会把三个 ONNX 模型（common 51.58 MiB、common_det 19.19 MiB、
        # common_old 12.98 MiB）连同 api/ 子包源码、logo.png、README.md 全部当 DATA 收进包，
        # 而本项目只用到默认模型 common_old.onnx（见 ddddocr\models\model_loader.py：
        # old=False 且 beta=False 时取 common_old.onnx）。
        #   - 代码：包内不含 importlib / __import__ / import_module，全部为静态 import，
        #     字节码分析会随 `import ddddocr` 自动收集 core / models / preprocessing / utils；
        #     此处仍显式声明 --hidden-import，避免将来把导入改成字符串形式后静默漏收
        #     （漏收会静默降级成手输，不易察觉）。
        #   - 数据：只需默认模型；字符集内联在 models\charset_manager.py，无独立字符集文件。
        #   - 许可：--copy-metadata 保留 ddddocr 的 MIT 许可与版本元数据。
        #   - FFmpeg 过滤不靠删参数：--additional-hooks-dir 让 scripts\hooks\hook-cv2.py
        #     覆盖官方 hook；同时必须移除 `--collect-binaries cv2`——它在 spec 中展开为
        #     collect_dynamic_libs('cv2')，会把已被 hook 过滤掉的 ffmpeg DLL 再加回来。
        if (-not (Test-Path $DdddOcrModel)) {
            throw "缺少默认 OCR 模型：$DdddOcrModel；请先按 requirements.txt 安装 ddddocr"
        }
        $Cv2Hook = Join-Path $HooksDir 'hook-cv2.py'
        if (-not (Test-Path $Cv2Hook)) {
            throw "缺少 cv2 打包 hook：$Cv2Hook"
        }

        $pyiArgs += @(
            '--hidden-import', 'ddddocr',
            '--copy-metadata', 'ddddocr',
            '--add-data', ($DdddOcrModel + ';ddddocr'),
            '--collect-all', 'onnxruntime',
            '--additional-hooks-dir', $HooksDir
        )
    }
    else {
        # lite：去掉 OCR 相关（体积大头），但 **必须保留 PIL 与 pystray**——
        # 两者是界面基础能力（验证码图片解码、隐藏到系统托盘），不属于 OCR。
        $pyiArgs += @(
            '--exclude-module', 'ddddocr',
            '--exclude-module', 'onnxruntime',
            '--exclude-module', 'cv2',
            '--exclude-module', 'numpy',
            '--exclude-module', 'sympy',
            '--exclude-module', 'matplotlib'
        )
    }

    # 注意：pyinstaller.exe 会把 INFO 日志写到 stderr，在 $ErrorActionPreference='Stop'
    # 下会被 PowerShell 误判为终止性错误（NativeCommandError）而中断构建，
    # 因此调用原生命令期间临时放宽该设置，改以退出码判定成败。
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Python -m PyInstaller @pyiArgs
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousEap

    if ($exitCode -ne 0) {
        throw "PyInstaller 构建 $Name 失败（退出码 $exitCode）"
    }

    $exe = Join-Path $DistDir "GUIT-net-login-$Name.exe"
    if (-not (Test-Path $exe)) {
        throw "构建结束但未找到产物：$exe"
    }
    $sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host ("产物 {0}  {1} MB" -f (Split-Path -Leaf $exe), $sizeMb) -ForegroundColor Green
}

$targets = if ($Target -eq 'all') { @('lite', 'full') } else { @($Target) }
foreach ($t in $targets) { Build-One -Name $t }

# 阶段 A：构建后立即校验打包清单（PKG / PYZ / Analysis 三层）——
# 默认模型与必需模块必须在，闲置模型、FFmpeg 组件与未使用的 ddddocr.api 必须不在。
# 通过独立 Python 进程执行并立即读取其退出码：0=通过，1=断言失败，2=清单缺失/损坏。
# 不通过即视为构建失败，避免把违规产物误分发出去（清单校验不能证明运行成功）。
if (-not (Test-Path $CheckScript)) {
    throw "缺少打包清单检查脚本：$CheckScript"
}
foreach ($t in $targets) {
    $tocDir = Join-Path $DistDir ("_work\{0}\GUIT-net-login-{0}" -f $t)
    if (-not (Test-Path $tocDir)) {
        throw "未找到构建中间目录：$tocDir"
    }
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Python $CheckScript --target $t --toc-dir $tocDir --json (Join-Path $tocDir 'check-bundle.json')
    $checkExit = $LASTEXITCODE
    $ErrorActionPreference = $previousEap
    if ($checkExit -ne 0) {
        throw "打包清单检查未通过（$t，退出码 $checkExit）；产物不可发布"
    }
}

# 附一份配置样例到产物目录，便于分发时对照
if (Test-Path $SampleCfg) {
    Copy-Item -Path $SampleCfg -Destination $DistDir -Force
    Write-Host "已复制 config.sample.json 到 build\" -ForegroundColor DarkGray
}

Write-Host '构建完成。产物位于 build\ 目录。' -ForegroundColor Cyan
