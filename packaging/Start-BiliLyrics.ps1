# Restart Bilibili with --remote-debugging-port=9225 (only if needed),
# then make sure LyricDesk is running.
# ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less files as ANSI.
$ErrorActionPreference = 'SilentlyContinue'
$port = 9225
$debugUrl = "http://127.0.0.1:$port/json"

function Get-BiliExeIn($dir) {
    if (-not $dir -or -not (Test-Path -LiteralPath $dir)) { return $null }
    $files = @(Get-ChildItem -LiteralPath $dir -Filter '*.exe' -File |
        Where-Object { $_.Name -notmatch 'uninst|update|helper|crash|卸载' })
    # 主程序通常很大；先挑最大的那个，避免拿到小工具
    $big = $files | Sort-Object Length -Descending | Select-Object -First 1
    if ($big) { return $big.FullName }
    return $null
}

function Find-Bili {
    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\bilibili'),
        (Join-Path $env:LOCALAPPDATA 'bilibili'),
        (Join-Path $env:ProgramFiles 'bilibili')
    )
    if (${env:ProgramFiles(x86)}) { $roots += (Join-Path ${env:ProgramFiles(x86)} 'bilibili') }

    foreach ($root in $roots) {
        $exe = Get-BiliExeIn $root
        if ($exe) { return $exe }
    }

    $regRoots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    foreach ($regRoot in $regRoots) {
        foreach ($key in (Get-ChildItem $regRoot)) {
            $item = Get-ItemProperty $key.PSPath
            $hint = "$($item.DisplayName) $($item.InstallLocation) $($item.DisplayIcon) $($item.UninstallString)"
            if ($hint -notmatch 'bilibili') { continue }
            if ($item.InstallLocation) {
                $exe = Get-BiliExeIn $item.InstallLocation
                if ($exe) { return $exe }
            }
            foreach ($raw in @($item.DisplayIcon, $item.UninstallString)) {
                if (-not $raw) { continue }
                $path = ($raw -replace '^"', '') -replace '",.*$', ''
                $exe = Get-BiliExeIn (Split-Path -LiteralPath $path -Parent)
                if ($exe) { return $exe }
            }
        }
    }
    return $null
}

function Test-DebugPort {
    try {
        $resp = Invoke-WebRequest -Uri $debugUrl -UseBasicParsing -TimeoutSec 1
        return ($resp.StatusCode -eq 200 -and $resp.Content -match 'bilibili')
    } catch {
        return $false
    }
}

$exe = Find-Bili
if (-not $exe) {
    Write-Host "[!] Bilibili desktop client not found. Install it first." -ForegroundColor Yellow
    exit 1
}
Write-Host "Bilibili : $exe"

if (Test-DebugPort) {
    Write-Host "Bilibili is already running with remote debugging - not restarting it."
} else {
    Write-Host "Restarting Bilibili with remote debugging on port $port ..."
    Get-Process | Where-Object { $_.Path -eq $exe } | Stop-Process -Force
    Start-Sleep -Milliseconds 900
    Start-Process -FilePath $exe -ArgumentList "--remote-debugging-port=$port"
    Start-Sleep -Milliseconds 800
    if (-not (Test-DebugPort)) {
        Write-Host "[i] Port $port is not answering yet. Wait for Bilibili to finish loading." -ForegroundColor Yellow
    }
}

$lyric = Join-Path $PSScriptRoot 'LyricDesk.exe'
if (-not (Get-Process LyricDesk -ErrorAction SilentlyContinue)) {
    if (Test-Path -LiteralPath $lyric) {
        Start-Process -FilePath $lyric
    } else {
        Write-Host "[!] LyricDesk.exe not found next to this script. Start it manually." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Done. In LyricDesk: Settings -> Window & input ->" -ForegroundColor Green
Write-Host "turn on 'Bilibili client subtitles' (only needs to be done once)." -ForegroundColor Green
