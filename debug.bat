@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 以调试模式启动（会显示控制台与错误信息），关闭窗口即退出。
"C:\Program Files\Python312\python.exe" run.pyw
echo.
echo ---- 程序已退出，按任意键关闭 ----
pause >nul
