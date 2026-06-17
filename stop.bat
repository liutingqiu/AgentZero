@echo off
echo 停止零 v5 ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5052" ^| findstr "LISTENING"') do (
    echo 终止服务进程 PID %%a
    taskkill /f /pid %%a 2>nul
)
echo 已停止。
timeout /t 2 >nul
