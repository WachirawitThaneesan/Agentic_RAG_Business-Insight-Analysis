@echo off
title Project Live Status - Read-only
chcp 65001 >nul
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -u "%~dp0scripts\show_project_status.py"
) else (
  py -3 -u "%~dp0scripts\show_project_status.py"
)
if errorlevel 1 (
  echo.
  echo Status viewer stopped. Saved results remain.
  pause
)
