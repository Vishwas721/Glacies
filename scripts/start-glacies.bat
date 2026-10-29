@echo off
rem Start Glacies on this computer: PostGIS and Redis in Docker, then the API, the
rem simulation worker and the web app, each in its own window (close one to stop it).
rem
rem   scripts\start-glacies.bat          everything, then open the Easy view
rem   scripts\start-glacies.bat browse   no worker: look at finished results, use less memory
rem   scripts\start-glacies.bat stop     close the windows this script opened
setlocal
cd /d "%~dp0.."
set "MODE=%~1"
if /i "%MODE%"=="stop" goto stop
if not "%MODE%"=="" if /i not "%MODE%"=="browse" (
    echo Unknown option "%MODE%". Use: start-glacies [browse^|stop]
    exit /b 2
)

echo.
echo == Glacies ==
rem A run uses gigabytes of memory and 15-20 minutes: say so before starting.
powershell -NoProfile -Command ^
  "$b = Get-CimInstance Win32_Battery; $m = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB;" ^
  "if ($b) { $on = if ($b.BatteryStatus -eq 2) { 'charging' } else { 'ON BATTERY - plug in before a simulation' }; Write-Host ('Battery: {0}%% ({1})' -f $b.EstimatedChargeRemaining, $on) }" ^
  "Write-Host ('Free memory: {0:N1} GB' -f $m);" ^
  "if ($m -lt 4) { Write-Host 'Under 4 GB free: close some browser tabs, or use: start-glacies browse' -ForegroundColor Yellow }"

docker info >nul 2>&1
if errorlevel 1 (
    echo Docker is not running. Start Docker Desktop, wait until it says running, then try again.
    exit /b 1
)
echo Starting PostGIS and Redis...
docker compose up -d --wait
if errorlevel 1 (
    echo Docker could not start PostGIS and Redis; see the messages above.
    exit /b 1
)

call :serve api "Glacies API" 8000 "uv run uvicorn glacies.api.app:app"
if /i not "%MODE%"=="browse" call :worker
call :serve web "Glacies web" 5173 "cd web && pnpm dev"

rem 127.0.0.1, not localhost: Windows tries IPv6 first, and uvicorn listens on IPv4 only.
echo Waiting for the API...
powershell -NoProfile -Command ^
  "for ($i = 0; $i -lt 90; $i++) { try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8000/api/cities | Out-Null; exit 0 } catch { Start-Sleep 1 } }; exit 1"
if errorlevel 1 (
    echo The API did not answer within 90 s: look at the "Glacies API" window.
    exit /b 1
)
start "" http://localhost:5173/easy
echo.
echo Glacies is running: http://localhost:5173  (Easy view /easy, full screen /pro)
echo Stop it by closing the Glacies windows, or: scripts\start-glacies.bat stop
exit /b 0

:serve
rem %1 window id, %2 title, %3 port, %4 command; skip a server already listening on its port.
netstat -ano | findstr /r /c:":%~3 .*LISTENING" >nul
if not errorlevel 1 (
    echo %~2 is already running on port %~3.
    exit /b 0
)
call :window %1 %2 %4
exit /b 0

:worker
rem The worker listens on no port: look for its process instead (one worker only).
powershell -NoProfile -Command ^
  "$w = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'glacies(\.exe)?.? worker' };" ^
  "if ($w) { exit 0 } else { exit 1 }"
if not errorlevel 1 (
    echo Glacies worker is already running.
    exit /b 0
)
call :window worker "Glacies worker" "uv run glacies worker"
exit /b 0

:window
rem GLACIES_WINDOW in the command line lets "stop" find the window whatever terminal shows it.
start "%~2" cmd /k "set GLACIES_WINDOW=%~1&& %~3"
exit /b 0

:stop
powershell -NoProfile -Command ^
  "$w = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*GLACIES_WINDOW=*' };" ^
  "foreach ($p in $w) { taskkill /t /f /pid $p.ProcessId | Out-Null };" ^
  "Write-Host ('Closed {0} Glacies window(s).' -f @($w).Count)"
echo PostGIS and Redis keep running in Docker (docker compose stop ends them).
exit /b 0
