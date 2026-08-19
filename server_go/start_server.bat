@echo off
chcp 65001 > nul
echo ==================================================
echo   Cat Home Logging Server (WinSV Go)
echo ==================================================

REM Set relay URL for XREA cloud (uncomment to enable or override)
set RELAY_OPT=-relay-url https://veris.jp/home_logging/api/db_write.php

REM Check if binary exists
if exist "home_logging_server.exe" (
    echo Starting compiled binary with cloud relay...
    home_logging_server.exe -port 8080 -data data\events.jsonl %RELAY_OPT%
) else (
    echo Running with Go...
    go run main.go -port 8080 -data data\events.jsonl %RELAY_OPT%
)

pause
