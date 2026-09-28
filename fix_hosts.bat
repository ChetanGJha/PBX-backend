@echo off
:: Batch script to fix pbx.aikyamlabs.local mapping to 127.0.0.1 in Windows hosts file
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ========================================================
    echo  ERROR: Administrator permissions required!
    echo  Please right-click this file and select 'Run as administrator'.
    echo ========================================================
    pause
    exit /b 1
)

set HOSTS_FILE=%WINDIR%\System32\drivers\etc\hosts

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$path = '%HOSTS_FILE%';" ^
    "$lines = Get-Content $path | Where-Object { $_ -notmatch 'pbx\.aikyamlabs\.local' };" ^
    "$lines += '127.0.0.1`tpbx.aikyamlabs.local';" ^
    "Set-Content -Path $path -Value $lines -Encoding Ascii;" ^
    "Clear-DnsClientCache"

echo.
echo ========================================================
echo  SUCCESS: pbx.aikyamlabs.local updated to 127.0.0.1!
echo ========================================================
echo.
ping -n 2 pbx.aikyamlabs.local
pause
