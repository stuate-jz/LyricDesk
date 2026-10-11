<#
    一键「打包 + 覆盖安装目录 + 重启」脚本

    用途：改完代码之后跑一次，你桌面上/托盘里的那个桌面歌词立刻就变成刚改完的版本，
          不用手动卸载重装、也不用每次去点安装程序。

    用法（在项目根目录，或任意位置都行）：
        powershell -ExecutionPolicy Bypass -File dev\deploy_local.ps1

    可选参数：
        -SkipBuild   不重新打包，只把 dist\LyricDesk.exe 覆盖过去并重启（秒级，适合只改了资源文件）
        -Source      不打包也不动安装目录，直接用源码启动程序（启动最快，但要先退出已运行的实例）
        -NoRestart   覆盖完不自动启动

    先决条件：
        · Python 3.12（默认 C:\Program Files\Python312\python.exe）
        · PyInstaller（python -m PyInstaller --version 能打印版本）
        · 安装目录已存在（跑过一次安装程序即可）
#>

[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [switch]$Source,
    [switch]$NoRestart
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "    $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "    $text" -ForegroundColor Yellow }

# ---------- 路径 ----------
$root       = Split-Path -Parent $PSScriptRoot          # 项目根目录（本脚本在 dev\ 下）
$distExe    = Join-Path $root 'dist\LyricDesk.exe'
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\LyricDesk'
$installExe = Join-Path $installDir 'LyricDesk.exe'

$python = 'C:\Program Files\Python312\python.exe'
if (-not (Test-Path $python)) {
    $found = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($found) { $python = $found.Source } else { throw "找不到 python.exe，请先装 Python 3.12" }
}

Write-Step "项目目录：$root"

# ---------- 0. 先停掉正在运行的实例（否则 exe 被占用、复制会失败；单实例机制也会挡掉新进程）----------
Write-Step "停掉正在运行的 LyricDesk"
$running = @(Get-Process -Name LyricDesk -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
    $running | Stop-Process -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 5; $i++) {
        Start-Sleep -Milliseconds 800
        if (-not (Get-Process -Name LyricDesk -ErrorAction SilentlyContinue)) { break }
    }
    $left = @(Get-Process -Name LyricDesk -ErrorAction SilentlyContinue)
    if ($left.Count -gt 0) { throw "还有 $($left.Count) 个 LyricDesk 进程没退掉，请在任务管理器里手动结束后重试" }
    Write-Ok "已结束 $($running.Count) 个进程"
} else {
    Write-Ok "本来就没在运行"
}

# ---------- 快捷模式：直接用源码启动，不碰安装目录 ----------
if ($Source) {
    if (-not (Test-Path (Join-Path $root 'run.pyw'))) { throw "没找到 run.pyw，项目目录是不是不对？$root" }
    Write-Step "用源码启动（改代码后重启这个进程即可看到效果）"
    $pyw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
    if (-not (Test-Path $pyw)) { $pyw = $python }
    Start-Process -FilePath $pyw -ArgumentList (Join-Path $root 'run.pyw')
    Write-Ok "已启动：$pyw run.pyw"
    Write-Warn "以后每次改完代码，重跑一次本脚本（加 -Source）就会用最新代码启动。"
    return
}

if (-not (Test-Path $installDir)) {
    throw "安装目录不存在：$installDir`n请先跑一次 dist\桌面歌词-安装程序-v1.6.4.exe 装好，之后再用本脚本做增量更新。"
}

# ---------- 1. 打包 ----------
if ($SkipBuild) {
    Write-Step "跳过打包"
    if (-not (Test-Path $distExe)) { throw "dist\LyricDesk.exe 不存在，先去掉 -SkipBuild 跑一次完整打包" }
    Write-Ok ("用现有的：" + (Get-Item $distExe).LastWriteTime)
}
else {
    Write-Step "打包（PyInstaller，约 1 分钟）"
    Push-Location $root
    try {
        & $python -m PyInstaller 'desktop-lyric.spec' --noconfirm
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败（exit $LASTEXITCODE）" }
    } finally {
        Pop-Location
    }
    if (-not (Test-Path $distExe)) { throw "打包结束但没找到 $distExe" }
    Write-Ok ("新 exe：" + (Get-Item $distExe).LastWriteTime)
}

# ---------- 2. 覆盖安装目录里的 exe ----------
Write-Step "覆盖安装目录里的 exe"
try {
    Copy-Item -LiteralPath $distExe -Destination $installExe -Force
    Write-Ok ("已替换：" + (Get-Item $installExe).LastWriteTime)
}
catch {
    throw "复制失败（多半是文件还被占用）：$($_.Exception.Message)`n请确认托盘图标已退出后重试。"
}

# ---------- 3. 重启，让新版本立刻生效 ----------
if ($NoRestart) {
    Write-Step "按要求不自动启动"
} else {
    Write-Step "启动新版本"
    Start-Process -FilePath $installExe
    Start-Sleep -Milliseconds 1800
    $now = @(Get-Process -Name LyricDesk -ErrorAction SilentlyContinue).Count
    if ($now -gt 0) { Write-Ok "已启动（进程数 $now）" } else { Write-Warn "没检测到进程，请看一眼托盘区" }
}

Write-Host ""
Write-Host "完成：桌面上的桌面歌词已经是刚才改完的版本。" -ForegroundColor Green
