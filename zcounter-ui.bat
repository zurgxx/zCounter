@echo off
rem Double-click launcher for WSLg UI.
rem Edit ZC_DIR if your clone lives elsewhere in Linux.
cd /d "%USERPROFILE%" >nul 2>&1

set "WSL_DISTRO=Ubuntu"
set "ZC_DIR=/home/rock/work/zCounter"

wsl -d %WSL_DISTRO% -e bash -lc "cd '%ZC_DIR%' && .venv/bin/python -m zcounter.ui"
if errorlevel 1 (
  echo.
  echo zCounter UI exited with an error.
  pause
)
