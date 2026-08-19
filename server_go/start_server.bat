@echo off
chcp 65001 > nul
echo ==================================================
echo   Cat Home Logging Server (WinSV Go)
echo ==================================================

REM Check if binary exists
if exist "home_logging_server.exe" (
    echo Starting compiled binary...
    home_logging_server.exe -port 8080 -data data\events.jsonl
) else (
    echo Running with Go...
    go run main.go -port 8080 -data data\events.jsonl
)

pause
