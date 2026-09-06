@echo off
echo Stopping Antigravity Mission Control Daemon...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :9090') do (
    taskkill /F /PID %%a >nul 2>&1
)
taskkill /F /IM cloudflared-windows-amd64.exe >nul 2>&1
echo Done.
