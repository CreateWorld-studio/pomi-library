@echo off
title 资料库
cd /d "%~dp0"
if exist "C:\Python314\python.exe" (
  "C:\Python314\python.exe" "%~dp0skills\ziliao\ziliao.py" open
) else (
  python "%~dp0skills\ziliao\ziliao.py" open
)
if errorlevel 1 pause
