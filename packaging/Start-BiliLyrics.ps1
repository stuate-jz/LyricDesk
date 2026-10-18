# Start Bilibili with --remote-debugging-port=9225, then launch LyricDesk.
# ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less files as ANSI.
$ErrorActionPreference = 'SilentlyContinue'
$port = 9225

function Find-Bili {
    $direct = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\bilibili\bilibili.exe'),
        (Join-Path $env:LOCALAPPDATA 'bilibili\bilibili.exe'),
        (Join-Path $env:ProgramFiles 'bilibili\bilibili.exe')
    )
    foreach ($path in $direct) {
        if (Test-Path $path) { return $path }
    }

    $roots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    foreach ($root in $roots) {
        foreach ($key in (Get-ChildItem $root)) {
            $item = Get-ItemProperty $key.PSPath
            $hint = "$($item.InstallLocation) $($item.DisplayIcon)"
            if ($hint -match 'bilibili') {
                if ($item.DisplayIcon) {
                    $icon = ($item.DisplayIcon -split ',')[0].Trim('"')
                    if (Test-Path $icon) { return $icon }
                }
                $guess = Join-Path $item.InstallLocation 'bilibili.exe'
                if (Test-Path $guess) { return $guess }
            }
        }
    }
    return $null
}

$exe = Find-Bili
if (-not $exe) {
    Write-Host "[!] Bilibili desktop client not found. Install it first." -ForegroundColor Yellow
    exit 1
}

Write-Host "Bilibili : $exe"
Write-Host "Restarting it with remote debugging on port $port ..."
Get-Process bilibili -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 900
Start-Process -FilePath $exe -ArgumentList "--remote-debugging-port=$port"
Start-Sleep -Milliseconds 700

$lyric = Join-Path $PSScriptRoot 'LyricDesk.exe'
if (Test-Path $lyric) {
    Start-Process -FilePath $lyric
} else {
    Write-Host "[!] LyricDesk.exe not found next to this script. Start it manually." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. In LyricDesk: Settings -> Window & input ->" -ForegroundColor Green
Write-Host "turn on 'Bilibili client subtitles'." -ForegroundColor Green
