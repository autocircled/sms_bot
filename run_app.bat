@echo off
title Playwright Scraper Desktop App
cd /d "%~dp0"
call .\env\Scripts\activate.bat
python app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
    pause
)
