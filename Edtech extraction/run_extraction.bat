@echo off
setlocal
cd /d "%~dp0"
py extractor.py %*
if errorlevel 1 (
    echo.
    echo Extraction did not complete successfully.
)
pause
