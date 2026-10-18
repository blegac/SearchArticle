@echo off
:: ─────────────────────────────────────────────────────────────
::  SearchArticle
::  Windows launcher
::  Place this file at the PROJECT ROOT (next to the src folder)
:: ─────────────────────────────────────────────────────────────

:: Automatically cd into the .bat folder
cd /d "%~dp0"

:: Make the src/searcharticle package importable
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"

:: Use the local venv (.venv) if present, else the system Python
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

:: Check that Python is installed
%PY% --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERROR] Python is not installed or not on the PATH.
    echo  Download Python from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Check that the package exists
if not exist "src\searcharticle\__main__.py" (
    echo.
    echo  [ERROR] src\searcharticle\__main__.py not found.
    echo  Make sure this launcher is at the SearchArticle project root.
    echo.
    pause
    exit /b 1
)

:: Install dependencies if needed (silent when already installed)
echo  Checking dependencies...
%PY% -m pip install --quiet --upgrade customtkinter requests

:: Launch the application
echo  Launching SearchArticle...
%PY% -m searcharticle

:: If the script crashes, show the error before closing
if errorlevel 1 (
    echo.
    echo  [ERROR] The script ended with an error.
    echo  Read the message above for details.
    echo.
    pause
)
