<#
.SYNOPSIS
    构建 GUIT-net-login 的单文件 exe。

.DESCRIPTION
    lite：不含 OCR（ddddocr / onnxruntime / opencv / numpy / PIL 全部排除），体积约 20 MB，
          分发时对方只需手输 4 位验证码。
    full：含 OCR，体积约 160 MB，双击后自动识别验证码。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build.ps1 -Target all
#>
[CmdletBinding()]
param(
    [ValidateSet('lite', 'full', 'all')]
    [string]$Target = 'all'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SourceDir   = Join-Path $ProjectRoot 'src'
$EntryPoint  = Join-Path $SourceDir 'app.py'
# 用 python -m PyInstaller 而非 pyinstaller.exe：venv 的 .exe 启动器内含绝对路径，
# 项目目录改名或移动后会失效，模块方式不受影响。
$Python      = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$DistDir     = Join-Path $ProjectRoot 'build'
$SampleCfg   = Join-Path $ProjectRoot 'config.sample.json'

if (-not (Test-Path $Python)) {
    throw "未找到 $Python；请先创建 .venv 并安装 requirements.txt"
}

function Build-One {
    param([Parameter(Mandatory = $true)][string]$Name)

    Write-Host "==== 构建 $Name ====" -ForegroundColor Cyan
    # 注意：不要用 $args（PowerShell 自动变量），故命名为 $pyiArgs
    $pyiArgs = @(
        '--noconfirm', '--clean',
        '--onefile', '--noconsole',
        '--name', "CampusNetLogin-$Name",
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
        $pyiArgs += @(
            '--collect-all', 'ddddocr',
            '--collect-all', 'onnxruntime',
            '--collect-binaries', 'cv2'
        )
    }
    else {
        # lite：去掉 OCR 相关（体积大头），但 **必须保留 PIL 与 pystray**——
        # 两者是界面基础能力（验证码图片解码、隐藏到系统托盘）。
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

    $exe = Join-Path $DistDir "CampusNetLogin-$Name.exe"
    if (-not (Test-Path $exe)) {
        throw "构建结束但未找到产物：$exe"
    }
    $sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host ("产物 {0}  {1} MB" -f (Split-Path -Leaf $exe), $sizeMb) -ForegroundColor Green
}

$targets = if ($Target -eq 'all') { @('lite', 'full') } else { @($Target) }
foreach ($t in $targets) { Build-One -Name $t }

# 附一份配置样例到产物目录，便于分发时对照
if (Test-Path $SampleCfg) {
    Copy-Item -Path $SampleCfg -Destination $DistDir -Force
    Write-Host "已复制 config.sample.json 到 build\" -ForegroundColor DarkGray
}

Write-Host '构建完成。产物位于 build\ 目录。' -ForegroundColor Cyan
