@echo off
cd /d "E:\project\tools\zero"
echo 正在启动零 v5 ...
echo ────────────────────────────────────
echo 服务将在系统托盘运行。
echo 右键托盘图标 → 打开浏览器 / 停止 / 重启
echo ────────────────────────────────────
echo 启动后自动打开: http://127.0.0.1:5052
echo.
start /min E:\python\pythonw.exe zero_server.py
timeout /t 2 >nul
