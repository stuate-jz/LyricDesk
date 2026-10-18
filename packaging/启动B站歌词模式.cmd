@echo off
rem Restart Bilibili with --remote-debugging-port=9225, then start LyricDesk.
rem (LyricDesk must have "Bilibili client subtitles" enabled in its settings.)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-BiliLyrics.ps1"
if errorlevel 1 pause
