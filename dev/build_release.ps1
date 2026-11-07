<#
    正式发版打包脚本：生成 dist\LyricDesk.exe 与 Inno Setup 安装包。

    用法（项目根目录）：
        powershell -ExecutionPolicy Bypass -File dev\build_release.ps1

    版本号唯一真源：lyricdesk\__init__.py 的 __version__。
    打包前先校验版本元信息；不一致会直接停止，不生成半成品。
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "    $text" -ForegroundColor Green }

$root = Split-Path -Parent $PSScriptRoot
$initFile = Join-Path $root 'lyricdesk\__init__.py'
$installerFile = Join-Path $root 'installer.iss'
$updateFile = Join-Path $root 'packaging\update.json'
$python = 'C:\Program Files\Python312\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $found = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($found) { $python = $found.Source } else { throw '找不到 python.exe' }
}

$initText = Get-Content -Raw -LiteralPath $initFile
$versionMatch = [regex]::Match($initText, '__version__\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) { throw "__version__ 格式不正确：$initFile" }
$version = $versionMatch.Groups[1].Value

$installerText = Get-Content -Raw -LiteralPath $installerFile
$appVersionMatch = [regex]::Match($installerText, '#define\s+AppVersion\s+"([^"]+)"')
$outputMatch = [regex]::Match($installerText, 'OutputBaseFilename\s*=\s*([^\r\n]+)')
$jsonVersion = (Get-Content -Raw -LiteralPath $updateFile | ConvertFrom-Json).version
$expectedOutput = "LyricDesk-Setup-v$version"

if (-not $appVersionMatch.Success -or $appVersionMatch.Groups[1].Value -ne $version) {
    throw "installer.iss AppVersion 与 $version 不一致"
}
if (-not $outputMatch.Success -or $outputMatch.Groups[1].Value.Trim() -ne $expectedOutput) {
    throw "installer.iss OutputBaseFilename 必须是 $expectedOutput"
}
if ($jsonVersion -ne $version) {
    throw "packaging\update.json version=$jsonVersion，与 $version 不一致"
}

Write-Step "版本元信息校验通过：v$version"

Write-Step '运行 PyInstaller'
Push-Location $root
try {
    & $python -m PyInstaller 'desktop-lyric.spec' --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败，退出码 $LASTEXITCODE" }
} finally {
    Pop-Location
}

$iscc = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'
if (-not (Test-Path -LiteralPath $iscc)) {
    $localPrograms = Join-Path $env:LOCALAPPDATA 'Programs'
    $found = Get-ChildItem -LiteralPath $localPrograms -Filter 'ISCC.exe' -File -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found) { $iscc = $found.FullName }
}
if (-not (Test-Path -LiteralPath $iscc)) { throw '找不到 Inno Setup 7 的 ISCC.exe' }

Write-Step "生成安装包：$iscc"
Push-Location $root
try {
    & $iscc 'installer.iss'
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup 失败，退出码 $LASTEXITCODE" }
} finally {
    Pop-Location
}

$setup = Join-Path $root "dist\$expectedOutput.exe"
if (-not (Test-Path -LiteralPath $setup)) { throw "没有找到安装包：$setup" }
$item = Get-Item -LiteralPath $setup
$bytes = $item.Length
$mib = [math]::Round($bytes / 1MB, 2)
$declaredMb = [double](Get-Content -Raw -LiteralPath $updateFile | ConvertFrom-Json).size_mb
if ([math]::Abs($mib - $declaredMb) -gt 2) {
    throw "update.json size_mb=$declaredMb，实测 $mib MiB，相差超过 2"
}

Write-Ok "路径：$($item.FullName)"
Write-Ok "字节：$bytes"
Write-Ok "大小：$mib MiB"
Write-Ok "FileVersion：$($item.VersionInfo.FileVersion)"
