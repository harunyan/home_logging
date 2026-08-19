@echo off
chcp 65001 > nul
echo Building Go receiver server for Windows...
go build -ldflags "-s -w" -o home_logging_server.exe main.go
if %ERRORLEVEL% equ 0 (
    echo Build successful: home_logging_server.exe
) else (
    echo Build failed!
)
pause
