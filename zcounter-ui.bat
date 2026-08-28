@echo off
rem Double-click launcher for WSLg UI.
rem Resolve the WSL-side repository path from this batch file location.
cd /d "%USERPROFILE%" >nul 2>&1

set "WSL_DISTRO=Ubuntu"
set "ZC_DIR="
for /f "delims=" %%I in ('wsl.exe -d %WSL_DISTRO% -e wslpath -u "%~dp0."') do set "ZC_DIR=%%I"

if not defined ZC_DIR (
  echo.
  echo Could not resolve the zCounter directory from this launcher location.
  pause
  exit /b 1
)

wsl -d %WSL_DISTRO% -e bash -lc "cd '%ZC_DIR%' && .venv/bin/python -m zcounter.ui"
if errorlevel 1 (
  echo.
  echo zCounter UI exited with an error.
  pause
)
